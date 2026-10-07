"""在 AMCT 专用 Python 环境下执行 ONNX 量化。

为什么必须是独立进程：AMCT 的自定义算子（libamct_onnx_ops.so）与 onnxruntime
版本强绑定 —— 它只支持 1.20.0 及更早，而项目主环境用的是 1.23.2。两个版本
没法装进同一个 venv，所以量化这一步单独用一个 venv，由 amct_quantize.py 以
子进程方式调起（和项目既有的"算法脚本独立进程"架构一致）。

协议：stdout 逐行输出 {"stage": "quantizing", "percent", "message"}，
      与主脚本完全一致，由 amct_quantize.py 原样转发。
输入：workdir/_amct_job.json
      {"input_name", "input_shape", "skip_nodes": [...], "samples": N}
      workdir/model.onnx
产物：workdir/quantized.onnx        带 AscendQuant/AscendDequant 的部署模型（INT8）
      workdir/_amct_fakequant.onnx  fake-quant 模型（调试用）

退出码：0 成功；2 输入/模型问题；3 AMCT 不可用；其它为异常。
"""
import json
import os
import sys
import time
from pathlib import Path

STAGE = "quantizing"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def emit(percent: int, message: str) -> None:
    print(json.dumps({"stage": STAGE, "percent": percent, "message": message},
                     ensure_ascii=False), flush=True)


def main() -> None:
    workdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    job_path = workdir / "_amct_job.json"
    model_path = workdir / "model.onnx"
    deploy_path = workdir / "quantized.onnx"

    if not model_path.exists():
        print("找不到 model.onnx", file=sys.stderr)
        raise SystemExit(2)
    if not job_path.exists():
        print("找不到 _amct_job.json", file=sys.stderr)
        raise SystemExit(2)

    job = json.loads(job_path.read_text(encoding="utf-8"))
    skip_nodes = list(job.get("skip_nodes") or [])
    samples = int(job.get("samples") or 16)
    input_name = job.get("input_name") or "images"
    input_shape = [int(v) for v in (job.get("input_shape") or [1, 3, 224, 224])]

    emit(10, "加载 AMCT 工具链")
    try:
        import numpy as np
        import onnxruntime as ort

        import amct_onnx as amct
    except ImportError as exc:
        print("AMCT 环境不完整: %s" % exc, file=sys.stderr)
        raise SystemExit(3)

    if amct.AMCT_SO is None:
        print("AMCT 自定义算子库未加载（libamct_onnx_ops.so 缺失或构建失败）",
              file=sys.stderr)
        raise SystemExit(3)

    time.sleep(0.1)
    emit(25, "生成量化配置（%d 层跳过）" % len(skip_nodes))

    workdir = Path(workdir)
    config_file = str(workdir / "_amct_quant_config.json")
    modified_file = str(workdir / "_amct_modified.onnx")
    record_file = str(workdir / "_amct_record.txt")
    save_prefix = str(workdir / "_amct_result")

    try:
        amct.create_quant_config(config_file, str(model_path),
                                 skip_layers=skip_nodes, batch_num=samples)
    except Exception as exc:  # noqa: BLE001
        print("create_quant_config 失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    time.sleep(0.1)
    emit(45, "插入量化算子（IFMR 激活量化 + 权重量化）")

    try:
        amct.quantize_model(config_file, str(model_path), modified_file, record_file)
    except Exception as exc:  # noqa: BLE001
        print("quantize_model 失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    time.sleep(0.1)
    emit(65, "标定推理（%d 个合成样本，CPU）" % samples)

    # 标定：用 AMCT 的自定义算子跑推理，把激活范围记进 record_file。
    # 必须把 amct.AMCT_SO 作为 session options 传进去，否则 onnxruntime
    # 不认识 amct.customop 域里的 IFMR 节点。
    try:
        session = ort.InferenceSession(modified_file, amct.AMCT_SO,
                                       providers=["CPUExecutionProvider"])
        rng = np.random.default_rng(20240916)
        feed_name = input_name
        declared = {value.name for value in
                    __import__("onnx").load(modified_file,
                                            load_external_data=False).graph.input}
        if feed_name not in declared:
            feed_name = next(iter(declared))
        for _ in range(samples):
            data = rng.standard_normal(input_shape).astype(np.float32)
            session.run(None, {feed_name: data})
    except Exception as exc:  # noqa: BLE001
        print("标定推理失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    time.sleep(0.1)
    emit(85, "生成部署模型（AscendQuant/AscendDequant）")

    try:
        amct.save_model(modified_file, record_file, save_prefix)
    except Exception as exc:  # noqa: BLE001
        print("save_model 失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    produced = Path(save_prefix + "_deploy_model.onnx")
    if not produced.exists():
        print("AMCT 未产出部署模型: %s" % produced, file=sys.stderr)
        raise SystemExit(2)
    produced.replace(deploy_path)

    # 收拾中间文件，只留契约产物和一份 fake-quant（便于排查）
    fake = Path(save_prefix + "_fake_quant_model.onnx")
    if fake.exists():
        fake.replace(workdir / "_amct_fakequant.onnx")
    for leftover in (config_file, modified_file, record_file, job_path):
        try:
            Path(leftover).unlink(missing_ok=True)
        except OSError:
            pass

    emit(100, "AMCT 量化完成")
    time.sleep(0.1)


if __name__ == "__main__":
    main()
