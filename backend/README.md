# 智能模型量化部署一体化平台 — 后端

单体 FastAPI 服务，与 `../web`（React + Vite 前端）对接。覆盖：
设备管理（真 SSH 探活 / 板载指标）、ONNX 模型上传、量化任务 8 态状态机
（HAWQ 敏感度 → NSGA-II 位宽方案搜索 → 用户选帕累托方案 → AMCT 量化 → ATC 转 `.om`）、
`.om` 下载、SFTP 部署推送与性能指标回填、首页统计与量化效果对比。

> 算法**已是真实实现**：敏感度用权重谱范数（Hessian 代理）、方案搜索用 pymoo
> 的 NSGA-II、量化用华为 AMCT（未安装时降级到 onnxruntime QDQ，但那样 `.om`
> 只能到 FP16）、`.om` 由 CANN ATC 真实编译。详见 `docs/API_CONTRACT.md` 第 7 节
> 与根目录的 `DEPLOY.md`。

## 目录结构

```
backend/
├── app/
│   ├── main.py            # FastAPI 入口：路由挂载 + CORS + 建表 + /api/health /api/meta
│   ├── config.py          # config.yaml 加载 + 环境变量覆盖
│   ├── db.py              # SQLite 引擎与会话
│   ├── models.py          # SQLModel 表模型（Device/Model/QuantizationJob/Scheme/JobLog/Deployment）
│   ├── schemas.py         # 请求/响应模型（camelCase，与前端 types 对齐）
│   ├── executor.py        # subprocess 执行器 + JSONL 进度协议 + 取消/超时兜底
│   ├── scheduler.py       # 串行任务调度器（并发=1）
│   ├── ssh_client.py      # paramiko：探活 / 指标采集 / SFTP 推送
│   ├── pipeline.py        # 量化流水线（两阶段，scheme_ready 处挂起等用户选方案）
│   ├── layers.py          # 层信息（预设模板 / ONNX 解析 / 兜底推导）
│   ├── metrics.py         # 性能指标估算（占位口径，与算法脚本一致）
│   ├── presets.py         # 预设模型定义（与前端预设下拉一致）
│   └── routers/           # devices / models / jobs / deployments / stats / comparison
├── algorithms/            # 算法脚本（独立进程，不与 Web 共享代码）
│   ├── hawq_sensitivity.py    # ① 敏感度分析（权重谱范数）→ sensitivity.json
│   ├── nsga2_search.py        # ② pymoo NSGA-II 方案搜索 → schemes.json
│   ├── amct_quantize.py       # ④ AMCT 量化（不可用时降级 ort）→ quantized.onnx
│   ├── amct_onnx_runner.py    # ④ 的 AMCT 侧执行器（跑在独立 venv 里）
│   └── atc_convert.py         # ⑤ CANN ATC 编译 → model.om
├── tests/                 # pytest（92 个用例，覆盖 API/状态机/执行器/算法脚本/端到端）
├── scripts/smoke_http.py  # 对着运行中的服务跑完整 HTTP 链路自检（20 项）
├── docs/API_CONTRACT.md   # 前后端对接契约（真实响应示例 + 前端改造清单）
├── config.yaml            # 配置
└── requirements.txt
```

## 快速开始

### 服务器（Ubuntu 20.04 / Python 3.8）

```bash
cd ~/quant-deploy-backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl -s http://localhost:8000/api/health      # {"status":"ok","version":"0.2.0",...}
curl -s http://localhost:8000/api/stats       # 首页统计
```

接口文档：`http://<服务器>:8000/docs`；枚举与约定速查：`GET /api/meta`。

### 本地联调（Windows）

```bat
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端 `web/` 里 `npm run dev`，vite 已配好 `/api` → `http://localhost:8000` 代理
（换后端地址改 `web/.env.development` 的 `VITE_API_PROXY_TARGET`）。
只跑一个端口也可以：`cd web && npm run build` 之后，后端会自动把
`web/dist` 挂到根路径 `/`，直接访问 `http://localhost:8000` 即可。

### 测试

```bash
python -m pytest tests/ -q          # 76 passed，约 2 分钟
```

测试用临时目录做数据库与工作目录隔离，不会污染 `app.db` / `workspace/`。

### 端到端自检（对着真服务跑）

```bash
python scripts/smoke_http.py http://localhost:8000   # 直连后端
python scripts/smoke_http.py http://localhost:5173   # 走 vite 代理（等价于前端真实链路）
```

会走完：健康检查 → 建设备 → 探活 → 预设模型 → 量化任务 → 帕累托前沿 → 选方案 →
`.om` 下载 → 对比数据 → 一键部署（无真机时失败属预期）→ 清理冒烟数据。

## 配置（config.yaml）

| 键 | 说明 |
| --- | --- |
| `workspace_dir` / `db_path` | 任务工作目录根 / SQLite 路径 |
| `max_upload_mb` | ONNX 上传上限（默认 500） |
| `algorithms.*` | 四个算法脚本路径（换真实现只需替换同名文件） |
| `ssh.timeout` | SSH 连接/命令超时 |
| `ssh.metrics_*_command` | 指标采集命令（可按板子环境覆盖） |
| `scheduler.max_concurrent_jobs` | 任务并发（默认 1，服务器内存小勿调高） |
| `scheduler.cancel_grace_seconds` | 取消时 SIGTERM 之后的强杀等待 |
| `deployment.default_target_dir` | 前端未指定目标目录时的默认推送目录 |
| `deployment.bench_command` | 真机推理测试命令；**留空 = 用方案估算指标并标注 `estimated`** |
| `server.cors_origins` | 允许的前端来源（直连跨域时用） |

环境变量覆盖：`QUANT_DEPLOY_CONFIG`、`QUANT_DEPLOY_DB`、`QUANT_DEPLOY_WORKSPACE`、
`QUANT_DEPLOY_STATIC_DIR`（指向已构建的前端，挂到根路径做单 URL 交付）。

## 量化任务状态机

```
上传 ONNX
  ↓
pending              排队（并发=1）
  ↓
sensitivity_analysis ① HAWQ 敏感度分析
  ↓
scheme_search        ② NSGA-II 位宽方案搜索
  ↓
scheme_ready         挂起：等前端从帕累托前沿里选一个方案（GET .../schemes）
  ↓
quantizing           ④ AMCT 按选中方案量化
  ↓
converting           ⑤ ATC 转 .om
  ↓
om_ready             可下载 / 可部署
  ↓
deploying            SFTP 推送到开发板指定目录
  ↓
deployed
（任意阶段失败 → failed，stderr 尾部写入 error；取消 → failed + "任务已取消"）
```

`GET /api/quantization/jobs/{id}` 轮询即可拿到 `status` / `progress` / `message`。

## 算法脚本协议

脚本与 Web 进程隔离，由 `app/executor.py` 用当前解释器拉起，参数是任务工作目录：

```
python algorithms/xxx.py <workdir>      # cwd = workdir
```

- **进度**：stdout 每行一个 JSON `{"stage": "...", "percent": 0-100, "message": "..."}`
- **产物**（都在 workdir）：

| 文件 | 产出者 | 内容 |
| --- | --- | --- |
| `model.onnx` | 后端 | 上传/预设模型的副本 |
| `layers.json` | 后端 | `[{name, sizeKb, kind}]` 层结构 |
| `sensitivity.json` | ① | `{"layers": {层名: 敏感度}}` |
| `schemes.json` | ② | `[{index, layer_config, objectives, metrics, layers, stats}]` |
| `selected_scheme.json` | 后端 | 用户选定的方案 |
| `quantized.onnx` | ④ | AMCT 产物 |
| `model.om` | ⑤ | 最终可部署模型 |

- **失败**：非零退出码；stderr 最后 50 行写入任务的 `error` 字段
- **取消 / 超时**：执行器用独立 watcher 线程监听，POSIX 下按进程组 SIGTERM→SIGKILL，
  脚本长时间无输出也能被取消，不留孤儿进程

## 与前端的功能对应（前后端已对接）

| 前端页面 | 主要接口 |
| --- | --- |
| HomePage | `GET /api/stats` |
| QuantizationPage | `GET /api/models/presets`、`POST /api/models`、`POST /api/quantization/jobs`、`GET .../schemes`、`POST .../select`、`GET .../om/download` |
| DevicesPage | `GET/POST/PUT/DELETE /api/devices`、`POST /{id}/check`、`GET /{id}/metrics[/history]` |
| DeploymentPage | `POST /api/deployments`、`GET /api/deployments/{id}`（logs/metrics） |
| ComparisonPage | `GET /api/comparison?deploymentId=`（rows + radar） |

前端接入层在 `../web/src`：`api/`（fetch 封装 + 各资源模块）、`hooks/useDeviceMetrics.ts`
（设备监控轮询）、`store/appStore.ts`（全部 action 走真实接口）、`utils/format.ts`（文案与格式化）。
原来的 `web/src/data/mockData.ts` 已删除。

字段、错误码、状态映射与前端接入明细见 `docs/API_CONTRACT.md`。

## 待办 / 已知边界

- **精度取决于是否装了 AMCT**：装了 → `.om` 是真 INT8；没装 → 降级 onnxruntime
  QDQ，而 ATC 不认 QDQ 格式，`.om` 只能到 FP16。AMCT 安装见根目录 `DEPLOY.md`
- **标定用合成数据**，页面上的「精度损失」是估算值，真精度要在板子上实测
- **无昇腾硬件**，`.om` 只验证了格式（IMOD 头、ATC 真实编译），没验证真机运行结果
- 无用户体系：只有 API Key 一道门；设备密码明文存 SQLite
- 真实 HAWQ（PyTorch 反传算 Hessian）尚未接入，当前用谱范数代理
- 联调需在阿里云安全组放行 8000 端口
