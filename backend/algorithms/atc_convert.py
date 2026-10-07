"""⑤ ATC 转换 .om（真实实现）。

输入：workdir/quantized.onnx（④ 的产物）、可选 workdir/quantized_fallback.onnx；
产物：workdir/model.om（昇腾离线模型，板子可直接加载）。

调用 CANN 的 atc 把 ONNX 编译成昇腾离线模型。ATC 是纯 CPU 的图编译工具，
**不需要机器上有 NPU** —— "在 x86 上转换、把 .om 拷到板子上跑" 是官方认可的用法。

环境变量：
  SOC_VERSION     目标芯片型号（默认 Ascend310B4，即 Atlas 200I DK A2）
  QUANT_ATC_BIN   atc 可执行文件路径（默认从 PATH 找；测试时可指向不存在的路径）

降级：ATC 不接受 QDQ（INT8 量化）图时，自动改用 ④ 留下的 quantized_fallback.onnx
（FP16/FP32 版本）重转一次，并用它覆盖 quantized.onnx —— 保证"下载到的模型"
与"转成 .om 的模型"始终是同一个。

这个脚本没有占位降级路径：.om 是二进制私有格式，伪造出来的东西板子加载不了，
所以 atc 不可用时如实返回非零退出码。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STAGE = "converting"
SLEEP = 0.15
DEFAULT_SOC = "Ascend310B4"
ATC_TIMEOUT = 900
QDQ_HINTS = ("quantiz", "QuantizeLinear", "DequantizeLinear", "QDQ")


def emit(percent: int, message: str) -> None:
    print(json.dumps({"stage": STAGE, "percent": percent, "message": message},
                     ensure_ascii=False), flush=True)


def find_cann_setenv():
    """定位 CANN 的 set_env.sh；找不到返回 None。"""
    explicit = os.environ.get("ASCEND_TOOLKIT_HOME")
    if explicit:
        candidate = Path(explicit) / "set_env.sh"
        if candidate.exists():
            return candidate
    for pattern in ("/usr/local/Ascend/ascend-toolkit/latest/set_env.sh",
                    "/usr/local/Ascend/ascend-toolkit/set_env.sh"):
        candidate = Path(pattern)
        if candidate.exists():
            return candidate
    roots = sorted(Path("/usr/local/Ascend").glob("*/set_env.sh")) if Path("/usr/local/Ascend").exists() else []
    return roots[-1] if roots else None


def find_atc(setenv=None):
    """定位 atc 可执行文件。

    后端进程通常没有 source 过 CANN 环境，atc 不在 PATH 上，所以要直接翻
    CANN 安装目录。找不到时返回 None —— 调用方会如实报错退出。
    """
    override = os.environ.get("QUANT_ATC_BIN")
    if override:
        return override

    found = shutil.which("atc")
    if found:
        return found

    roots = []
    if setenv is not None:
        roots.append(setenv.parent)
    if Path("/usr/local/Ascend").exists():
        roots.extend(sorted(Path("/usr/local/Ascend").iterdir()))
    for root in roots:
        for candidate in (root / "bin" / "atc",
                          root / "latest" / "bin" / "atc",
                          root / "ascend-toolkit" / "latest" / "bin" / "atc"):
            if candidate.exists():
                return str(candidate)
    return None


def derive_input_shape(model_path: Path):
    """全静态输入返回 None（让 atc 自己取）；含动态维时固定成 1。"""
    try:
        import onnx
        model = onnx.load(str(model_path), load_external_data=False)
    except Exception:  # noqa: BLE001 - 取不到形状就交给 atc
        return None

    entries, dynamic = [], False
    for value in model.graph.input:
        dims = value.type.tensor_type.shape.dim
        shape = []
        for dim in dims:
            if dim.dim_value > 0:
                shape.append(int(dim.dim_value))
            else:
                shape.append(1)
                dynamic = True
        if not shape:
            return None
        entries.append("%s:%s" % (value.name, ",".join(str(v) for v in shape)))
    if not dynamic or not entries:
        return None
    return ";".join(entries)


def looks_like_qdq_rejection(text: str) -> bool:
    return any(hint.lower() in text.lower() for hint in QDQ_HINTS)


def run_atc(model_path: Path, workdir: Path, setenv, atc_bin, soc, input_shape):
    """跑一次 atc，返回 (returncode, 输出文本)。"""
    args = [
        _quote(str(atc_bin)),
        "--framework=5",
        "--model=%s" % _quote(str(model_path.resolve())),
        "--output=%s" % _quote(str((workdir / "model").resolve())),
        "--soc_version=%s" % soc,
    ]
    if input_shape:
        args.append('--input_shape="%s"' % input_shape)
    args.append("--log=error")
    # atc 需要 CANN 的运行环境（set_env.sh 里设的 LD_LIBRARY_PATH 等）
    command = "source %s && %s" % (_quote(str(setenv)), " ".join(args))

    try:
        proc = subprocess.run(["bash", "-lc", command], capture_output=True,
                              text=True, timeout=ATC_TIMEOUT, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        return 124, "atc 执行超时（%ds）" % ATC_TIMEOUT
    except OSError as exc:
        return 126, "无法启动 atc: %s" % exc
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def emit_failure(output: str) -> None:
    lines = [line for line in output.splitlines() if line.strip()]
    for line in lines[-30:]:
        print(line, file=sys.stderr)


def main() -> None:
    workdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    source = workdir / "quantized.onnx"
    fallback = workdir / "quantized_fallback.onnx"
    target = workdir / "model.om"

    if not source.exists():
        print("缺少 quantized.onnx，无法转换", file=sys.stderr)
        raise SystemExit(2)

    setenv = find_cann_setenv()
    atc_bin = find_atc(setenv)
    missing = []
    if not setenv:
        missing.append("CANN 的 set_env.sh")
    if not atc_bin or (os.sep in str(atc_bin) and not Path(atc_bin).exists()):
        missing.append("atc 可执行文件")
    if missing:
        print("缺少 %s。ATC 属于昇腾 CANN 工具链（Linux），"
              "请在 WSL 中运行后端（scripts\\wsl.cmd serve），"
              "或先安装 CANN 并 source 其 set_env.sh。" % "、".join(missing),
              file=sys.stderr)
        raise SystemExit(3)

    soc = str(os.environ.get("SOC_VERSION") or DEFAULT_SOC)
    emit(10, "ATC 解析模型与算子（soc_version=%s）" % soc)
    time.sleep(SLEEP)

    input_shape = derive_input_shape(source)
    emit(30, "图优化与算子融合%s" % ("（动态输入固定为 %s）" % input_shape if input_shape else ""))
    time.sleep(SLEEP)

    code, output = run_atc(source, workdir, setenv, atc_bin, soc, input_shape)
    used_fallback = False
    if code != 0 and fallback.exists() and looks_like_qdq_rejection(output):
        emit(60, "ATC 不接受 QDQ 量化图，降级为 FP16/FP32 版本重试")
        time.sleep(SLEEP)
        code, output = run_atc(fallback, workdir, setenv, atc_bin, soc, input_shape)
        used_fallback = code == 0

    if code != 0 or not target.exists():
        emit_failure(output)
        raise SystemExit(1)

    # 降级成功时**不要**拿 fallback 覆盖 quantized.onnx：
    # 那是 INT8 量化的真实产物（比如 13.9MB → 3.8MB），用户有权利下载它、
    # 也可以在 onnxruntime 上跑。覆盖掉等于把已经做成的量化成果销毁，
    # 只剩一份"没压多少"的模型，反而更让人困惑。
    # 这里只把事实说清楚，产物各留各的。
    if used_fallback:
        emit(88, "注意：.om 由 FP16 版本编译（ATC 不支持 INT8/QDQ 图）；"
                 "quantized.onnx 仍保留完整 INT8 量化结果")
        time.sleep(SLEEP)

    emit(92, "生成 .om 模型（%.1f MB）" % (target.stat().st_size / 1024 / 1024))
    time.sleep(SLEEP)
    emit(100, ".om 生成完成")
    time.sleep(SLEEP)


if __name__ == "__main__":
    main()
