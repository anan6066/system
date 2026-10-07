# 服务器部署指南

把后端部署到 Linux 服务器（本地 Windows + WSL 的开发方式见 [`README.md`](README.md)）。

> **一句话**：`scp` 传代码 → 跑 `./deploy.sh check` → `./deploy.sh all`。

---

## 一、服务器要什么配置

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 系统 | Ubuntu 20.04 / 22.04 | CANN 官方支持；22.04 自带 Python 3.10 |
| **内存** | **8GB 起（16GB 舒服）** ★ | **ATC 转 .om 实测 4GB 会崩**（BrokenPipeError），6GB 是下限 |
| CPU | 8 核+ | ATC 用多进程并行编译 |
| 磁盘 | 系统盘 30GB + 数据盘 50GB | CANN 6GB + torch 3GB + 依赖 1GB + 产物 3GB |
| 带宽 | **5Mbps+** | CANN 两个包合计 2.2GB，小带宽会等到崩溃 |
| GPU | **不需要** | 当前算法全在 CPU 上跑。将来做真实 HAWQ 才需要（见文末） |

> ⚠️ **别选 vGPU 或数据中心训练卡**（H800 之类）—— 这个项目用不上，纯浪费钱。

---

## 二、部署步骤

### 1. 传代码

在**本地**执行（排除虚拟环境和产物）：

```bash
scp -r backend web deploy.sh user@<服务器IP>:~/quant-deploy/
```

建议把 `backend/presets_cache/` 一起带上（约 50MB），省得服务器重新下载 ImageNet 预训练权重。

### 2. 体检

```bash
ssh user@<服务器IP>
cd ~/quant-deploy
sed -i 's/\r$//' deploy.sh        # 从 Windows 传过去会有 CRLF，去掉
chmod +x deploy.sh
./deploy.sh check
```

**先看体检结果**：内存够不够、磁盘够不够、CANN 下载速度多少。速度低于 1MB/s 的话，建议本地下载好再传：

```bash
# 本地下好（需要带 Referer 头）
curl -L -O -H "Referer: https://www.hiascend.com/" \
  "https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.1/Ascend-cann-toolkit_9.1.1_linux-x86_64.run"
# 传到服务器的 ~/quant-deploy/.data/cann-installers/
```

### 3. 一键部署

```bash
API_KEY=$(openssl rand -hex 24) ./deploy.sh all
```

`all` = 装依赖 → 装 CANN → **装 AMCT** → 构建前端 → 配服务。

**`API_KEY` 必须设**，否则接口是裸奔的 —— 任何人只要能访问到端口，就能建设备、传模型、删数据，甚至让你的服务器去 SSH 别人的机器。

### 4. 验证

```bash
curl http://127.0.0.1:8000/api/health          # 期望 {"status":"ok",...}
journalctl -u quant-deploy -f                  # 看日志（systemd 环境）
./status.sh                                    # 看日志（容器环境）
```

浏览器开 `http://<服务器IP>:8000`（前端已挂在根路径）。

### 5. 关于 AMCT（决定 .om 的精度）

阶段 ④ 的量化有两条路：

| | 装了 AMCT | 没装（降级） |
| --- | --- | --- |
| 量化算法 | 华为 AMCT（IFMR）| onnxruntime QDQ |
| 产物算子 | `AscendQuant/AscendDequant` | `QuantizeLinear/DequantizeLinear` |
| **ATC 认识吗** | ✅ 认识 | ❌ **不认识 QDQ 格式** |
| 最终 `.om` | ✅ **INT8** | ⚠️ 只能到 FP16 |

实测差距（MobileNetV2，全 INT8 方案）：

```
              装了 AMCT        没装
quantized.onnx   3.6 MB        7.1 MB
model.om         6.5 MB        9.5 MB    ← 体积差 32%
```

**AMCT 不需要 NPU** —— 标定推理跑在 CPU 上（onnxruntime + AMCT 自定义算子）。
但它的自定义算子与 onnxruntime 版本强绑定（只支持到 1.20.0），而主环境用 1.23.2，
所以 `deploy.sh amct` 会**单独建一个 venv**（`<数据盘>/venvs/amct_onnx`），
后端用子进程调它。不想要 AMCT 时删掉那个目录即可，量化会自动降级。

单独安装：`./deploy.sh amct`

---

## 三、鉴权

后端支持 API Key，**默认关闭**（本机开发不用管）：

| 位置 | 配什么 |
| --- | --- |
| 后端 | 环境变量 `QUANT_DEPLOY_API_KEY`，或 `config.yaml` 的 `server.api_key`（环境变量优先） |
| 前端 | `web/.env.production` 的 `VITE_API_KEY`（构建前设好） |

前端要跟后端**用同一个值**，否则所有请求 401。

**免鉴权路径**：`/api/health`、`/api/meta`、`/docs`（探活和联调用）。

> 这只是挡「随手扫端口」的第一道门，不是强认证。真要对外开放，建议在前面再挂一层
> Nginx + HTTPS + 账号体系。

---

## 四、常用运维

```bash
sudo systemctl status quant-deploy     # 状态
sudo systemctl restart quant-deploy    # 重启
journalctl -u quant-deploy -n 100      # 最近日志
journalctl -u quant-deploy -f          # 实时日志
```

**改了 Python 代码**：`sudo systemctl restart quant-deploy`
**改了前端**：本地 `npm run build` → 传 `dist` → 重启后端（或服务器上跑 `./deploy.sh frontend`）
**重置数据**：停服务 → 删 `backend/app.db` 和 `backend/workspace/` → 启服务

---

## 五、常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 任务在 `converting` 失败，error 含 `ATC`/`atc` | 没装 CANN，或 `SOC_VERSION` 与目标芯片不匹配 | 跑 `./deploy.sh cann`；确认 `config.yaml` 的 `algorithms.soc_version` |
| **pip 卡住不动（0 字节/分钟）** | **`download.pytorch.org` 在国内基本拉不动**（实测 29 B/s） | `deploy.sh deps` 已默认走国内源（清华 PyPI + 阿里 pytorch-wheels）。手动装时见 `requirements.txt` 里的说明 |
| **CANN 装到一半报 `permission is invalid`** | **CANN 要求安装路径的父目录全是 755**，而 `/root` 是 700 | 装到默认的 `/usr/local/Ascend`；`deploy.sh` 已默认如此，且会提前拦下 `/root/*` 路径 |
| **ATC 报 `EC0010 ModuleNotFoundError: scipy`（或 numpy）** | **ATC 用的 python3 取决于调用方 shell**：后端走 `bash -lc`，登录 shell 会激活 conda，此时 `python3` 是 conda 的；手动测时又是 `/usr/bin/python3` | `deploy.sh cann` 会给**所有** python3 都装一遍。手动补：`bash -lc "python3 -m pip install scipy numpy sympy cffi pyyaml psutil attrs decorator cython requests absl-py"` |
| ATC 报 `BrokenPipeError` / `leaked semaphore` | **内存不足**（实测 4GB 必挂） | 升内存到 8GB+，或加 swap |
| ATC 报 `rtSetSocVersion failed` | `soc_version` 写得不完整 | 必须写全型号：`Ascend310B4` 而不是 `Ascend310B`。合法值见 `<CANN>/x86_64-linux/data/platform_config/*.ini` |
| ATC 日志里出现「降级为 FP16/FP32 版本重试」 | **没装 AMCT**：降级路径产的是 onnxruntime QDQ 图，ATC 不认 | 跑 `./deploy.sh amct`。这是当前唯一能拿到 INT8 `.om` 的途径 |
| 任务日志出现「AMCT 不可用或失败，降级到 onnxruntime QDQ」 | AMCT venv 缺失或构建失败 | 跑 `./deploy.sh amct`；或 `QUANT_AMCT_PYTHON=<路径>` 手动指定 |
| AMCT 报 `Layer xxx does not support quantization` | `skip_layers` 里混进了不可量化的节点 | 已修（只传 Conv/Gemm/MatMul/ConvTranspose/AveragePool/LSTM/GRU）。若仍出现，检查该层类型是否在 `amct_onnx/capacity/capacity_config.csv` 的 `QUANTIZABLE_TYPES` 里 |
| AMCT 构建报 `onnxruntime_float16.h: No such file` | AMCT 的下载脚本只在 ort==v1.16.0 时拉这个头文件，v1.20.0 漏了 | 已修（`deploy.sh amct` 手动补下载，走 jsDelivr 镜像） |
| 模型上传报「不是合法的 ONNX」 | 上传的文件确实不是 ONNX | 用真实导出的 `.onnx` |
| 前端页面 401 | 前后端 API Key 不一致 | 两边配成同一个值，重新构建前端 |
| 前端页面黄条「无法连接后端」 | 后端没起，或跨域被拦 | `./status.sh` 或 `systemctl status`；跨域时把前端来源加进 `config.yaml` 的 `server.cors_origins` |
| 部署到板子失败 | 服务器连不到板子 | 板子在内网的话服务器推不过去，需公网 IP 或 VPN |
| `/data/models` 不存在 | 部署时默认推这个目录 | 在板子上 `mkdir -p /data/models`，或改 `config.yaml` 的 `deployment.default_target_dir` |
| 容器重启后服务没了 | **GPU 云平台的容器大多没有 systemd**，平台不会自动拉起你的进程 | `./start.sh` 重新启动；想自启就把 `start.sh` 加到 `~/.bashrc` |

---

## 六、将来要跑真实 HAWQ 时

HAWQ 需要 PyTorch 反向传播算 Hessian，**这时 GPU 才有用**。

从 CPU 版换成 CUDA 版：

```bash
$VENV/bin/pip install torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu128
```

- **`cu128`**：RTX 50 系（Blackwell / sm_120）必须用这个；40 系及更早可用 `cu124`
- **`2.7.1`**：首个完整支持 Blackwell 的稳定版，且与本机验证过的版本一致
- 下载量从 200MB 涨到 2.5GB，注意带宽

选卡建议：本项目模型都是小 CNN（MobileNetV2 / ResNet18 / YOLOv8n / EfficientNet-B0），
**4GB 显存就够，8GB 很舒服** —— 最便宜的卡都远超需求，别买数据中心卡。

---

## 七、安全清单（对外暴露前逐条确认）

- [ ] `API_KEY` 已设置（`./deploy.sh check` 会提醒）
- [ ] 安全组只放行 8000；22 端口限来源 IP
- [ ] 设备密码目前**明文存在 SQLite** —— 别用高权限账号
- [ ] 建议前置 Nginx + HTTPS（现在是裸 HTTP，Key 会明文传输）
- [ ] 定期备份 `backend/app.db` 和 `backend/workspace/`
