"""② NSGA-II 位宽方案搜索（真实实现）。

输入：workdir/sensitivity.json（① 的产物）、workdir/layers.json（层体积）；
产物：workdir/schemes.json = [
        {"index", "layer_config", "objectives", "metrics", "layers", "stats"}, ...
      ] 恰好 6 个，按体积升序、精度损失降序排列。

优化问题：每层选一个位宽（INT8/FP16/FP32），三个目标同时最小化
  size          量化后/原始体积比（0~1）
  accuracy_loss 平均精度损失（百分点）—— 由敏感度 × 位宽权重累加
  latency       相对 FP32 的延迟比（0~1）
用 pymoo 的 NSGA-II 求帕累托前沿，再从前沿里挑 6 个有代表性的方案。

前沿取 6 个点这件事本身有讲究：真实的帕累托前沿常常只有 3~5 个点，
不足以铺满前端需要的 6 张卡片。所以候选池由三部分组成（NSGA-II 前沿 +
两条贪心升级扫描），最后在 (体积, 损失) 平面上取一条**单调链**再等距采样 ——
这样"体积升序 ⇔ 损失降序"由构造保证，不会因前沿形状而翻车。

位宽系数与 app/metrics.py、app/layers.py 保持同步（三处必须一致）。
"""
import json
import sys
import time
from pathlib import Path

STAGE = "scheme_search"
SLEEP = 0.15
SCHEME_COUNT = 6
POP_SIZE = 40
N_GENERATION = 60
SEED = 42

DEFAULT_SENSITIVITY = 0.5
DEFAULT_SIZE_KB = 1024
HIGH_SENSITIVITY = 0.7

BIT_NAMES = ("INT8", "FP16", "FP32")
# 与 app/layers.py:BIT_FACTOR、app/metrics.py:LAT_FACTOR/ACC_LOSS_WEIGHT 同步
BIT_FACTOR = {"INT8": 0.25, "FP16": 0.5, "FP32": 1.0}
LAT_FACTOR = {"INT8": 0.25, "FP16": 0.45, "FP32": 1.0}
ACC_LOSS_WEIGHT = {"INT8": 13.0, "FP16": 2.0, "FP32": 0.0}
MS_PER_KB_FP32 = 0.004

try:
    import numpy as np
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import Problem
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PolynomialMutation
    from pymoo.operators.sampling.rnd import IntegerRandomSampling
    from pymoo.optimize import minimize

    HAS_PYMOO = True
except ImportError:  # pragma: no cover - 只在无 pymoo 的环境走到
    HAS_PYMOO = False


def emit(percent: int, message: str) -> None:
    print(json.dumps({"stage": STAGE, "percent": percent, "message": message},
                     ensure_ascii=False), flush=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def build_layers(workdir: Path, sensitivity):
    """层顺序严格沿用 layers.json（即预设模板顺序 / ONNX 里的出现顺序）。

    不能按层名排序 —— 字母序会把 backbone.stem 排到 backbone.stage1 后面，
    层配置预览的顺序就乱了。
    """
    raw = load_json(workdir / "layers.json", [])
    names, sizes, kinds = [], {}, {}
    for item in raw:
        if isinstance(item, dict) and "name" in item:
            name = str(item["name"])
            names.append(name)
            sizes[name] = int(item.get("sizeKb", DEFAULT_SIZE_KB) or DEFAULT_SIZE_KB)
            kinds[name] = str(item.get("kind", "conv"))
    # sensitivity 里有、layers.json 里没有的层，按敏感度文件的顺序补在后面
    for name in sensitivity:
        if name not in sizes:
            names.append(name)
            sizes[name] = DEFAULT_SIZE_KB
            kinds[name] = "fc" if name.startswith("fc") else "conv"
    return [{"name": name, "sizeKb": sizes[name], "kind": kinds[name]} for name in names]


def evaluate(config, layers, sensitivity):
    """config: 与 layers 等长的序列，元素 0/1/2 -> INT8/FP16/FP32。"""
    layer_config = {}
    layer_view = []
    original_kb = quantized_kb = 0
    latency_ms = fp32_latency_ms = 0.0
    loss_sum = 0.0
    for layer, choice in zip(layers, config):
        name = layer["name"]
        bit = BIT_NAMES[int(choice)]
        size_kb = float(layer["sizeKb"])
        layer_config[name] = bit
        original_kb += int(size_kb)
        quantized_kb += int(round(size_kb * BIT_FACTOR[bit]))
        latency_ms += size_kb * MS_PER_KB_FP32 * LAT_FACTOR[bit]
        fp32_latency_ms += size_kb * MS_PER_KB_FP32
        loss_sum += sensitivity.get(name, DEFAULT_SENSITIVITY) * ACC_LOSS_WEIGHT[bit]
        layer_view.append({
            "name": name,
            "type": bit,
            "originalSize": int(size_kb),
            "quantizedSize": int(round(size_kb * BIT_FACTOR[bit])),
        })

    counted = len(layers) or 1
    size_ratio = (quantized_kb / original_kb) if original_kb else 1.0
    metrics = {
        "sizeMb": round(quantized_kb / 1024.0, 2),
        "originalSizeMb": round(original_kb / 1024.0, 2),
        "compressionRatio": round(1.0 - size_ratio, 4),
        "latencyMs": round(latency_ms, 2),
        "accuracyLossPct": round(loss_sum / counted, 2),
    }
    objectives = {
        "size": round(size_ratio, 4),
        "accuracy_loss": metrics["accuracyLossPct"],
        "latency": round((latency_ms / fp32_latency_ms) if fp32_latency_ms else 1.0, 4),
    }
    stats = {
        "int8Layers": sum(1 for item in layer_view if item["type"] == "INT8"),
        "fp16Layers": sum(1 for item in layer_view if item["type"] == "FP16"),
        "fp32Layers": sum(1 for item in layer_view if item["type"] == "FP32"),
        "originalSizeKb": original_kb,
        "quantizedSizeKb": quantized_kb,
        "compressionRatio": metrics["compressionRatio"],
    }
    return {"layer_config": layer_config, "objectives": objectives,
            "metrics": metrics, "layers": layer_view, "stats": stats}


def _objectives(config, layers, sensitivity):
    result = evaluate(config, layers, sensitivity)["objectives"]
    return (result["size"], result["accuracy_loss"], result["latency"])


class BitWidthProblem(Problem):
    """n_obj=3、n_var=层数、整数变量 {0,1,2}。"""

    def __init__(self, layers, sensitivity):
        super().__init__(n_var=len(layers), n_obj=3, xl=0, xu=2, vtype=int)
        self.layers = layers
        self.sensitivity = sensitivity

    def _evaluate(self, X, out, *args, **kwargs):
        out["F"] = np.array([_objectives(row, self.layers, self.sensitivity) for row in X])


def run_nsga2(layers, sensitivity, progress=None):
    """返回帕累托集里的 config 列表（每个是 tuple[int,...]）。"""
    problem = BitWidthProblem(layers, sensitivity)
    algorithm = NSGA2(
        pop_size=POP_SIZE,
        sampling=IntegerRandomSampling(),
        crossover=SBX(prob=0.9, eta=15),
        mutation=PolynomialMutation(prob=1.0 / max(len(layers), 2), eta=20),
        eliminate_duplicates=True,
    )

    class _Reporter:
        """每 10 代汇报一次，让前端进度条有真实推进。"""

        def __init__(self):
            self.last = 0

        def notify(self, algorithm_obj):
            generation = algorithm_obj.n_gen
            if progress and generation - self.last >= 10:
                self.last = generation
                optimal = algorithm_obj.opt
                front_size = len(optimal) if optimal is not None else 0
                progress(generation, front_size)

    reporter = _Reporter()
    result = minimize(problem, algorithm, ("n_gen", N_GENERATION), seed=SEED,
                      verbose=False, callback=reporter.notify)
    if result.X is None:
        return []
    matrix = np.atleast_2d(result.X)
    return [tuple(int(v) for v in row) for row in matrix]


def greedy_sweep(layers, sensitivity, order):
    """从全 INT8 出发，按 order 指定的层序逐层升级（INT8→FP16→FP32）。"""
    config = [0] * len(layers)
    chain = [tuple(config)]
    for position in order:
        for bit in (1, 2):
            config = list(config)
            config[position] = bit
            chain.append(tuple(config))
    return chain


def build_candidate_pool(layers, sensitivity, nsga_configs):
    pool = set(nsga_configs)
    pool.add(tuple([0] * len(layers)))   # 全 INT8
    pool.add(tuple([2] * len(layers)))   # 全 FP32

    # 敏感度升序 / 降序两条扫描：前者贴近"牺牲精度换体积"，后者贴近"保精度"
    by_sensitivity = sorted(range(len(layers)),
                            key=lambda i: (sensitivity.get(layers[i]["name"], DEFAULT_SENSITIVITY),
                                           layers[i]["name"]))
    pool.update(greedy_sweep(layers, sensitivity, by_sensitivity))
    pool.update(greedy_sweep(layers, sensitivity, list(reversed(by_sensitivity))))
    return pool


def monotone_chain(pool, layers, sensitivity):
    """按体积升序（同体积时损失大的在前）贪心取出损失非递增的链。

    这样得到的序列天然满足 sizes 非降、losses 非增 —— 前端方案卡片
    从左到右就是"越小越快但越不准"到"越大越准"的取舍曲线。

    全 FP32 的配置被排除：那等于"不量化"，而这是个量化平台，
    每个候选方案都应该真的压了一点体积，否则白白占掉一张方案卡片。
    """
    all_fp32 = tuple([2] * len(layers))
    scored = []
    for config in pool:
        if config == all_fp32:
            continue
        obj = _objectives(config, layers, sensitivity)
        scored.append((obj[0], -obj[1], config))
    scored.sort()

    chain, best_loss = [], None
    for size, neg_loss, config in scored:
        loss = -neg_loss
        if best_loss is None or loss <= best_loss + 1e-12:
            chain.append(config)
            best_loss = loss
    return chain


def pick_six(chain, layers, sensitivity):
    """在单调链上等距取 6 个；不足 6 个时允许重复取端点。"""
    if not chain:
        chain = [tuple([2] * len(layers))]
    if len(chain) >= SCHEME_COUNT:
        indices = [round(i * (len(chain) - 1) / (SCHEME_COUNT - 1)) for i in range(SCHEME_COUNT)]
        return [chain[i] for i in indices]
    picked = list(chain)
    while len(picked) < SCHEME_COUNT:
        picked.append(chain[-1])
    return picked


def enforce_conservative(config, layers, sensitivity):
    """最保守方案里，高敏感层不允许是 INT8。"""
    adjusted = list(config)
    for position, layer in enumerate(layers):
        score = sensitivity.get(layer["name"], DEFAULT_SENSITIVITY)
        if score >= HIGH_SENSITIVITY and adjusted[position] == 0:
            adjusted[position] = 1
    return tuple(adjusted)


def build_scheme(index, config, layers, sensitivity):
    result = evaluate(config, layers, sensitivity)
    result["index"] = index
    return {"index": index, "layer_config": result["layer_config"],
            "objectives": result["objectives"], "metrics": result["metrics"],
            "layers": result["layers"], "stats": result["stats"]}


def fallback_schemes(layers, sensitivity):
    """无 pymoo 时的降级路径：按 INT8 覆盖率铺开 6 个方案（原占位策略）。"""
    ratios = [1.0, 0.85, 0.7, 0.55, 0.4, 0.25]
    ordered = sorted(range(len(layers)),
                     key=lambda i: (sensitivity.get(layers[i]["name"], DEFAULT_SENSITIVITY),
                                    layers[i]["name"]))
    schemes = []
    for index, ratio in enumerate(ratios):
        quota = int(round(len(ordered) * ratio))
        config = [1] * len(layers)
        for position in ordered[:quota]:
            config[position] = 0
        for position in ordered[quota:]:
            if sensitivity.get(layers[position]["name"], DEFAULT_SENSITIVITY) >= 0.85:
                config[position] = 2
        schemes.append(build_scheme(index, tuple(config), layers, sensitivity))
    return schemes


def main() -> None:
    workdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    sensitivity_doc = load_json(workdir / "sensitivity.json", {})
    sensitivity = sensitivity_doc.get("layers", {}) if isinstance(sensitivity_doc, dict) else {}
    if not isinstance(sensitivity, dict) or not sensitivity:
        sensitivity = {"conv1": DEFAULT_SENSITIVITY, "fc1": DEFAULT_SENSITIVITY}
    sensitivity = {str(k): float(v) for k, v in sensitivity.items()}

    layers = build_layers(workdir, sensitivity)
    emit(10, "初始化种群（%d 层，%d 个体）" % (len(layers), POP_SIZE))
    time.sleep(SLEEP)

    if HAS_PYMOO:
        def on_generation(generation, front_size):
            percent = 10 + int(60 * min(generation, N_GENERATION) / N_GENERATION)
            emit(percent, "NSGA-II 第 %d 代，非支配解 %d 个" % (generation, front_size))

        nsga_configs = run_nsga2(layers, sensitivity, progress=on_generation)
        emit(75, "帕累托前沿 %d 个非支配解，筛选代表方案" % len(nsga_configs))
        time.sleep(SLEEP)

        pool = build_candidate_pool(layers, sensitivity, nsga_configs)
        chain = monotone_chain(pool, layers, sensitivity)
        configs = pick_six(chain, layers, sensitivity)
        # 最后（最保守）的方案修正高敏感层
        configs[-1] = enforce_conservative(configs[-1], layers, sensitivity)
        schemes = [build_scheme(index, config, layers, sensitivity)
                   for index, config in enumerate(configs)]
        emit(90, "已从 %d 个候选解中选出 %d 个代表性方案" % (len(pool), len(schemes)))
    else:
        emit(30, "缺少 pymoo，降级为覆盖率扫描（结果仍为确定性）")
        time.sleep(SLEEP)
        schemes = fallback_schemes(layers, sensitivity)
        emit(90, "已生成 %d 个方案（降级路径）" % len(schemes))

    # 兜底：链路末端保证严格 6 个（任何分支都不该走到这里）
    while len(schemes) < SCHEME_COUNT:
        schemes.append(dict(schemes[-1], index=len(schemes)))

    (workdir / "schemes.json").write_text(
        json.dumps(schemes, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(100, "帕累托前沿生成完毕")
    time.sleep(SLEEP)


if __name__ == "__main__":
    main()
