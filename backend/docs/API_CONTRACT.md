# 前后端对接契约（web ↔ backend）

> 面向负责前端接入的会话：本文档是**已经在跑的代码**的真实响应（不是设计稿），
> 每个示例都从 `scripts/smoke_http.py` 的实跑结果里抓取。
> 前端 `web/src/types/index.ts` 的字段命名已全部对齐，只有文末"需要前端调整"的少数几处要动。

- 后端基址：`http://<服务器>:8000`，接口前缀 `/api`
- 交互式文档：`GET /docs`（Swagger UI）、`GET /api/meta`（枚举与约定速查）
- 自检脚本：`python scripts/smoke_http.py http://<服务器>:8000`（跑完整链路，20 项全绿）

---

## 1. 接入方式（前端已按此配置，无需再改）

### 1.1 Vite 代理（已内置）

`web/vite.config.ts` 已配好 dev/preview 代理，`web/.env.development` 提供两个变量：

```ts
// web/vite.config.ts（现状）
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  const proxy = { '/api': { target, changeOrigin: true } }
  return { plugins: [react()], server: { port: 5173, proxy }, preview: { port: 4173, proxy } }
})
```

```ini
# web/.env.development
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://localhost:8000   # 换 ECS：http://121.43.244.6:8000
```

前端代码里一律用相对路径 `/api/...`。

### 1.2 直连（跨域）

后端已开 CORS，`config.yaml` 的 `server.cors_origins` 默认允许
`localhost:5173 / 127.0.0.1:5173 / localhost:3080 / 127.0.0.1:3080`；
换端口时改这个列表即可（或填 `"*"`）。

### 1.3 单 URL 交付

`web/` 执行 `npm run build` 后，若 `web/dist/index.html` 存在，
后端会自动把它挂在根路径 `/`，此时只跑 8000 一个端口即可访问整个平台
（也可用 `QUANT_DEPLOY_STATIC_DIR` 指定构建产物目录）。

---

## 2. 通用约定

| 约定 | 说明 |
| --- | --- |
| 字段命名 | 全部 camelCase，与 `web/src/types/index.ts` 一致，**无需做字段映射** |
| 主键 | 32 位 hex 字符串；`Scheme.index`、`JobLog.id` 是整数 |
| 时间 | ISO8601 UTC 且带 `Z`（如 `2026-09-10T02:31:28Z`），前端 `new Date(x).toLocaleString()` 会正确转本地时区；**不会是 null**（设备创建时 `lastConnected` 即写入） |
| 错误 | HTTP 4xx/5xx + `{"detail": "错误说明"}`（中文，可直接展示） |
| 数值 | 百分比为 0~100 的浮点；体积单位 KB（层）/ MB（模型）；延迟单位 ms；内存单位 MB |
| 列表 | 直接返回数组（没有分页包裹），需要时用 `?limit=` |
| 逻辑删除 | 无；`DELETE` 都是真删（模型删除会级联清理它的任务/方案/日志/部署记录） |

常见错误码：

- `400` 参数/状态不符（如模型文件丢失、还没有 `.om`、方案序号不存在）
- `404` 资源不存在（任务/模型/设备/部署记录）
- `409` 状态冲突（任务已有进行中、当前状态不可选方案、任务已结束不可取消、部署进行中不可删）
- `502` SSH 采集失败（`detail` 里带真实原因，如认证失败/超时）

---

## 3. 接口清单

| 方法 | 路径 | 用途 | 对应页面 |
| --- | --- | --- | --- |
| GET | `/api/health` | 健康检查 | 全部 |
| GET | `/api/meta` | 枚举/约定速查 | 全部 |
| GET | `/api/stats` | 首页统计（真实聚合） | HomePage |
| GET | `/api/devices` | 设备列表 | DevicesPage / DeploymentPage |
| POST | `/api/devices` | 添加设备 | DevicesPage |
| GET | `/api/devices/{id}` | 设备详情 | DevicesPage |
| PUT | `/api/devices/{id}` | 编辑设备 | DevicesPage |
| DELETE | `/api/devices/{id}` | 删除设备 | DevicesPage |
| POST | `/api/devices/{id}/check` | 真实 SSH 探活（"检测"按钮） | DevicesPage |
| POST | `/api/devices/check-all` | 批量探活 | DevicesPage / HomePage |
| GET | `/api/devices/{id}/metrics` | 板载 CPU/内存采集（监控轮询） | DevicesPage |
| GET | `/api/devices/{id}/metrics/history` | 监控折线历史点 | DevicesPage |
| GET | `/api/models` | 模型列表（含层信息） | QuantizationPage / DeploymentPage |
| POST | `/api/models` | 上传 ONNX（multipart，字段名 `file`） | QuantizationPage |
| GET | `/api/models/presets` | 预设模型下拉 | QuantizationPage |
| POST | `/api/models/preset` | 把预设实例化成模型记录 | QuantizationPage |
| GET | `/api/models/{id}` | 模型详情 | 详情/轮询 |
| GET | `/api/models/{id}/layers` | 模型层信息 | QuantizationPage |
| GET | `/api/models/{id}/download` | 下载原始 ONNX | QuantizationPage |
| DELETE | `/api/models/{id}` | 删除模型 | QuantizationPage |
| POST | `/api/quantization/jobs` | 创建量化任务（生成方案） | QuantizationPage |
| GET | `/api/quantization/jobs` | 任务列表（`?modelId=&status=&limit=`） | 历史/调试 |
| GET | `/api/quantization/jobs/{id}` | 任务进度轮询 | QuantizationPage |
| GET | `/api/quantization/jobs/{id}/schemes` | 帕累托前沿（选方案 UI） | QuantizationPage |
| GET | `/api/quantization/jobs/{id}/layers` | 选定方案的层明细 | QuantizationPage |
| GET | `/api/quantization/jobs/{id}/sensitivity` | 各层敏感度 | QuantizationPage（可选） |
| GET | `/api/quantization/jobs/{id}/logs` | 进度日志 | QuantizationPage（可选） |
| POST | `/api/quantization/jobs/{id}/select` | 选定方案 → 开始量化 | QuantizationPage |
| GET | `/api/quantization/jobs/{id}/om/download` | 导出/下载 `.om` | QuantizationPage |
| POST | `/api/quantization/jobs/{id}/cancel` | 取消任务 | QuantizationPage |
| DELETE | `/api/quantization/jobs/{id}` | 删除任务 | 清理 |
| GET | `/api/deployments` | 部署历史（`?modelId=&deviceId=&status=`） | DeploymentPage |
| POST | `/api/deployments` | 一键部署 | DeploymentPage |
| GET | `/api/deployments/{id}` | 部署详情/日志轮询 | DeploymentPage |
| POST | `/api/deployments/{id}/retry` | 失败重试 | DeploymentPage |
| DELETE | `/api/deployments/{id}` | 删除部署记录 | DeploymentPage |
| GET | `/api/comparison` | 对比数据（`?deploymentId=` 或 `?jobId=` 或 `?modelId=`） | ComparisonPage |

---

## 4. 关键接口的请求/响应

### 4.1 设备

`POST /api/devices`

```json
{ "name": "昇腾开发板-01", "ip": "192.168.1.101", "port": 22,
  "username": "root", "password": "secret", "npuType": "ascend" }
```

可选字段：`authType`（`"pwd"`/`"key"`，默认 `pwd`）、`keyPath`（密钥登录必填）、`note`。

`200` 响应（`GET /api/devices` 返回同样的对象数组）：

```json
{
  "id": "e251ace1fa5c49a3ba37be1474e363f0",
  "name": "昇腾开发板-01",
  "ip": "192.168.1.101",
  "port": 22,
  "username": "root",
  "authType": "pwd",
  "npuType": "ascend",
  "status": "offline",
  "cpuUsage": 0.0,
  "memoryUsage": 0.0,
  "npuUsage": null,
  "note": null,
  "lastConnected": "2026-09-10T02:31:28Z",
  "lastChecked": null,
  "lastError": null,
  "createdAt": "2026-09-10T02:31:28Z",
  "updatedAt": "2026-09-10T02:31:28Z"
}
```

- 密码**永不回传**（`password` 不在响应里）
- `status ∈ {online, offline, busy}`；`busy` 在部署推送期间由后端置位，结束后回到 `online`
- `cpuUsage/memoryUsage` 是最近一次采集值，离线设备为 `0.0`

`POST /api/devices/{id}/check`

```json
{ "online": false, "status": "offline", "latencyMs": null,
  "lastConnected": "2026-09-10T02:31:28Z", "error": "timed out" }
```

（同一时刻设备的 `status` / `lastConnected` / `lastError` 已落库，随后 `GET /api/devices` 就是新状态。）

`POST /api/devices/check-all`

```json
{ "total": 2, "online": 1, "offline": 1,
  "results": [ { "id": "…", "name": "板1", "online": true,
                 "status": "online", "latencyMs": 231.4, "error": "" } ] }
```

`GET /api/devices/{id}/metrics`

```json
{ "cpuUsage": 42.5, "memoryUsage": 63.2, "npuUsage": 12.0,
  "collectedAt": "2026-09-10T02:31:28Z" }
```

`GET /api/devices/{id}/metrics/history?limit=30` — 直接把 `samples` 喂给 recharts：

```json
{ "deviceId": "e251ace1fa5c49a3ba37be1474e363f0",
  "samples": [ { "timestamp": 1789007488000, "cpu": 42.5, "memory": 63.2 } ] }
```

`timestamp` 是 **epoch 毫秒**（对齐前端 `DeviceMetrics` 接口）。

### 4.2 模型

`POST /api/models`（multipart）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `file` | file | 必须是 `.onnx`，空文件 400，超过 `max_upload_mb`（默认 500MB）400 |
| `targetNPU` | text，可选 | 默认 `ascend` |
| `baseAccuracy` | text，可选 | 浮点基线 Top-1，默认 72.0，用于估算量化后精度 |

`GET /api/models/presets`

```json
[ { "id": "mobilenetv2", "name": "MobileNetV2", "description": "轻量级图像分类模型",
    "size": "14MB", "fileSize": 14680064, "baseAccuracy": 71.8,
    "layerCount": 8, "targetNPU": "ascend" } ]
```

预设共 4 个：`mobilenetv2`、`resnet18`、`yolov8`、`efficientnet-b0`
（id/name/description/size 与前端 `mockData.presetModels` 一致，可直接替换数据源）。

`POST /api/models/preset` — 请求 `{ "preset": "mobilenetv2" }`，返回 `ModelOut`：

```json
{
  "id": "3f33ceec45da406a9ecc510c22dbb290",
  "name": "MobileNetV2",
  "type": "preset",
  "preset": "mobilenetv2",
  "fileSize": 14680064,
  "targetNPU": "ascend",
  "status": "idle",
  "baseAccuracy": 71.8,
  "layerCount": 8,
  "quantizationLayers": [
    { "name": "conv1", "type": "FP32", "originalSize": 256, "quantizedSize": 256 },
    { "name": "conv2_1", "type": "FP32", "originalSize": 512, "quantizedSize": 512 },
    { "name": "conv2_2", "type": "FP32", "originalSize": 512, "quantizedSize": 512 },
    { "name": "conv3_1", "type": "FP32", "originalSize": 1024, "quantizedSize": 1024 },
    { "name": "conv3_2", "type": "FP32", "originalSize": 1024, "quantizedSize": 1024 },
    { "name": "conv4_1", "type": "FP32", "originalSize": 2048, "quantizedSize": 2048 },
    { "name": "conv4_2", "type": "FP32", "originalSize": 2048, "quantizedSize": 2048 },
    { "name": "fc", "type": "FP32", "originalSize": 4096, "quantizedSize": 4096 }
  ],
  "latestJobId": null,
  "createdAt": "2026-09-10T02:31:28Z",
  "updatedAt": "2026-09-10T02:31:28Z"
}
```

量化完成后同一个模型的 `status` 变 `completed`，`quantizationLayers` 变成选中方案的**真实位宽与体积**
（`INT8` 层 `quantizedSize = originalSize × 0.25`，`FP16` × 0.5，`FP32` × 1.0），
所以 `QuantizationPage` 的层列表和 `DeploymentPage` 的"模型层信息"可以直接渲染。

### 4.3 量化任务（8 态状态机）

`POST /api/quantization/jobs` — 请求 `{ "modelId": "…" }`（可选 `targetNPU`），立即返回：

```json
{ "id": "fc3a11235a8e4f2d9447dccc80e04ccd", "modelId": "3f33ceec…", "modelName": "MobileNetV2",
  "status": "pending", "progress": 0, "message": "", "stage": "", "targetNPU": "ascend",
  "selectedSchemeIndex": null, "schemeCount": 0, "hasOm": false, "omPath": null, "error": null,
  "createdAt": "2026-09-10T02:31:28Z", "updatedAt": "2026-09-10T02:31:28Z",
  "startedAt": null, "finishedAt": null }
```

规则：

- 模型文件丢失 → `400`；同一模型已有进行中的任务 → `409`
- 后端把模型拷进独立工作目录并**异步**跑 ① HAWQ → ② NSGA-II

`GET /api/quantization/jobs/{id}` — 建议 1~2s 轮询一次：

```json
{ "id": "fc3a11235a8e4f2d9447dccc80e04ccd", "modelId": "3f33ceec…", "modelName": "MobileNetV2",
  "status": "scheme_ready", "progress": 100,
  "message": "已生成 6 个帕累托方案，请选择", "stage": "scheme_ready",
  "targetNPU": "ascend", "selectedSchemeIndex": null, "schemeCount": 6,
  "hasOm": false, "omPath": null, "error": null,
  "createdAt": "2026-09-10T02:31:28Z", "updatedAt": "2026-09-10T02:31:31Z",
  "startedAt": "2026-09-10T02:31:28Z", "finishedAt": null }
```

状态取值（同时见 `/api/meta`）：

```
pending → sensitivity_analysis → scheme_search → scheme_ready
        → quantizing → converting → om_ready → deploying → deployed
任意阶段失败 → failed（error 字段是脚本 stderr 尾部）
```

前端页面阶段映射建议：

| 前端步骤 | 后端 status | 前端进度提示 |
| --- | --- | --- |
| `analyzing` | `pending` / `sensitivity_analysis` / `scheme_search` | 直接显示 `message` + `progress` |
| `plan` | `scheme_ready` | 渲染 `GET .../schemes` 让用户选 |
| `quantizing` | `quantizing` / `converting` | 进度条用 `progress` |
| `complete` | `om_ready` | 出现"导出量化后模型" |
| 失败 | `failed` | 展示 `error` |

`GET /api/quantization/jobs/{id}/schemes` — 帕累托前沿（每个方案一份，`recommended` 只有一个 `true`）：

```json
[
  {
    "index": 1,
    "layerConfig": { "conv1": "INT8", "conv2_1": "INT8", "conv2_2": "INT8",
                     "conv3_1": "INT8", "conv3_2": "INT8", "conv4_1": "INT8",
                     "conv4_2": "INT8", "fc": "FP16" },
    "objectives": { "size": 0.3389, "accuracy_loss": 3.57, "latency": 0.3211 },
    "metrics": { "sizeMb": 3.81, "originalSizeMb": 11.25, "compressionRatio": 0.6611,
                 "latencyMs": 14.8, "accuracyLossPct": 3.57 },
    "layers": [
      { "name": "conv1", "type": "INT8", "originalSize": 256, "quantizedSize": 64 },
      { "name": "fc", "type": "FP16", "originalSize": 4096, "quantizedSize": 2048 }
    ],
    "stats": { "int8Layers": 7, "fp16Layers": 1, "fp32Layers": 0,
               "originalSizeKb": 11520.0, "quantizedSizeKb": 3904.0,
               "compressionRatio": 0.6611 },
    "isSelected": false,
    "recommended": true
  }
]
```

- `layerConfig` 给"每层位宽"表格；`layers` 直接就是 `QuantizationLayer[]`（`originalSize`/`quantizedSize` 单位 KB）
- `stats.compressionRatio` 就是前端"压缩率"卡片要的百分比（×100 即可）
- `objectives`：NSGA-II 的归一化目标（体积比 0~1、精度损失百分点、延迟比 0~1）
- `metrics`：换算后的物理量，方案卡片直接展示更直观

`GET /api/quantization/jobs/{id}/layers` → 选定方案的 `layers` 数组（等价于 `models[].quantizationLayers`）。

`POST /api/quantization/jobs/{id}/select`

```json
{ "schemeIndex": 1 }        // 也可以传 {} 或 {"recommended": true}，由后端按膝点推荐
```

返回变 `quantizing` 的 `JobOut`；状态不是 `scheme_ready` → `409`，方案序号不存在 → `400`。

`GET /api/quantization/jobs/{id}/om/download` → `200` 二进制流，
`Content-Disposition: attachment; filename="MobileNetV2_fc3a1123.om"`；
未生成时 `404`。前端可直接

```ts
window.location.href = `/api/quantization/jobs/${jobId}/om/download`;
```

`GET /api/quantization/jobs/{id}/logs`（可选，做"详细进度流水"时用）：

```json
[ { "id": 1, "timestamp": "2026-09-10T02:31:28Z", "stage": "", "percent": 0,
    "message": "任务已创建，排队等待算法执行", "level": "info" },
  { "id": 2, "timestamp": "2026-09-10T02:31:28Z", "stage": "sensitivity_analysis",
    "percent": 0, "message": "开始量化任务：① HAWQ 敏感度分析", "level": "info" } ]
```

### 4.4 部署推送

`POST /api/deployments`

```json
{ "modelId": "3f33ceec…", "deviceId": "e251ace1…", "targetDir": "/data/models" }
```

- `modelId`：前端选中的"已量化模型"，后端自动找它最新一个带 `.om` 的任务；
  也可以直接传 `jobId`
- `targetDir` 可省略（默认 `/data/models`，`config.yaml` 可改），`remoteDir` 是它的别名
- `runBenchmark`（默认 `true`）：是否执行真机推理测试（未配置 `bench_command` 时自动跳过并标注估算）
- 模型没有 `.om` → `400`；设备不存在 → `400`；设备离线也可以推送（由 SSH 真连结果决定成败）

`200` 立刻返回 `pending` 记录，后台异步推送；随后轮询 `GET /api/deployments/{id}`：

```json
{
  "id": "368018707cd946c0a3b494d8142d2a1d",
  "jobId": "fc3a11235a8e4f2d9447dccc80e04ccd",
  "modelId": "3f33ceec…",
  "deviceId": "e251ace1…",
  "modelName": "MobileNetV2",
  "deviceName": "昇腾开发板-01",
  "targetDir": "/data/models",
  "remoteFile": null,
  "status": "failed",
  "progress": 0,
  "logs": [
    { "id": "1", "timestamp": "10:31:33", "message": "开始部署任务", "type": "info" },
    { "id": "2", "timestamp": "10:31:33", "message": "正在上传量化模型文件...", "type": "info" },
    { "id": "3", "timestamp": "10:31:43", "message": "部署异常: timed out", "type": "error" }
  ],
  "metrics": null,
  "metricsSource": null,
  "error": "timed out",
  "startTime": "2026-09-10T02:31:33Z",
  "endTime": "2026-09-10T02:31:43Z",
  "createdAt": "2026-09-10T02:31:33Z",
  "updatedAt": "2026-09-10T02:31:43Z"
}
```

成功路径的日志剧本（与前端 mock 的叙事一致，`type` 已带好，直接渲染）：

```
开始部署任务            info      ← 创建时写入
正在上传量化模型文件...   info
模型文件上传完成 -> /data/models/model.om   success
正在初始化 NPU 环境...    info
NPU 初始化成功            success
开始推理速度测试...       info
推理测试完成              success
正在采集性能指标...       info
部署成功                  success
```

成功时 `metrics` 形如：

```json
{ "inferenceSpeed": 14.8, "memoryUsage": 188.6, "top1Accuracy": 68.2 }
```

- `metricsSource = "measured"` 表示来自开发板实测（`config.yaml: deployment.bench_command`
  输出最后一行 JSON，键可为 `inferenceSpeed/latencyMs`、`memoryUsage/memoryMb`、`top1Accuracy/accuracy`）
- `metricsSource = "estimated"` 表示按方案估算（无板子/未配置 bench 时的占位口径），
  日志里会有一条 `warning` 说明，前端可据此加"估算值"角标
- 失败的部署会把任务状态退回 `om_ready`，可直接 `POST /api/deployments/{id}/retry`

### 4.5 首页统计

`GET /api/stats`

```json
{ "activeDevices": 1, "onlineDevices": 1, "busyDevices": 0, "totalDevices": 1,
  "totalModels": 1, "quantizedModels": 1,
  "totalJobs": 1, "runningJobs": 0, "readyJobs": 1, "failedJobs": 0,
  "totalDeployments": 1, "successfulDeployments": 0,
  "avgInferenceSpeed": null, "avgLatencyMs": null, "avgTop1Accuracy": null,
  "generatedAt": "2026-09-10T02:31:43Z" }
```

HomePage 四个卡片建议映射：活跃设备→`activeDevices`、已量化模型→`quantizedModels`、
部署次数→`totalDeployments`、平均延迟→`avgLatencyMs`（无成功部署时为 `null`，显示 `--`）。

### 4.6 效果对比

`GET /api/comparison?jobId=…`（或 `?deploymentId=…` / `?modelId=…`；都不传 → `400`）

```json
{ "deploymentId": null, "jobId": "fc3a1123…", "modelId": "3f33ceec…",
  "modelName": "MobileNetV2", "mode": "job",
  "mixedPrecisionLayers": 7, "traditionalLayers": 8,
  "rows": [
    { "metric": "Top-1 准确率 (%)", "traditionalINT8": 67.6, "mixedPrecision": 68.2, "unit": "%" },
    { "metric": "推理延迟 (ms)",    "traditionalINT8": 11.52, "mixedPrecision": 14.8, "unit": "ms" },
    { "metric": "模型大小 (MB)",    "traditionalINT8": 2.81,  "mixedPrecision": 3.81, "unit": "MB" },
    { "metric": "内存占用 (MB)",    "traditionalINT8": 170.6, "mixedPrecision": 188.6, "unit": "MB" }
  ],
  "radar": [
    { "metric": "精度", "traditional": 67.6, "mixedPrecision": 68.2 },
    { "metric": "速度", "traditional": 77.0, "mixedPrecision": 70.4 },
    { "metric": "效率", "traditional": 74.2, "mixedPrecision": 69.7 },
    { "metric": "内存", "traditional": 65.9, "mixedPrecision": 62.3 },
    { "metric": "功耗", "traditional": 81.6, "mixedPrecision": 76.3 }
  ] }
```

两列口径严格可比：基线 = **同一模型全部层 INT8**，混合 = 用户实际选定的位宽组合。
`radar` 已是 0~100 的分数，前端 `ComparisonPage` 的雷达图可以直接换成这个数据源
（`RadarItem` 字段名与 `radarChartData` 对齐：`metric/traditional/mixedPrecision`）。

---

## 5. 建议的前端调用流程

### DevicesPage

```ts
// 初次进入：拉真实列表（store 初始值不要再放 mockDevices）
const devices = await api.get<Device[]>('/api/devices');

// "检测"按钮
const res = await api.post<CheckResult>(`/api/devices/${id}/check`);
// 用 res.online / res.latencyMs 提示，列表状态由后端落库，重新 GET 即可

// "监控"：2s 轮询，组件已按这个节奏写死
const metrics = await api.get<Metrics>(`/api/devices/${id}/metrics`);        // 实时值
const history = await api.get<History>(`/api/devices/${id}/metrics/history`); // 初始曲线
```

`GET /api/devices/{id}/metrics` 在设备连不上时返回 `502`，
轮询里要捕获并把曲线断点保留（不要把设备标成离线，状态由 `check` 决定）。

### QuantizationPage

```
1. 预设：GET /api/models/presets  → 下拉
   自定义：POST /api/models (multipart file) → 得到 modelId
   （预设选中后：POST /api/models/preset {preset})
2. "生成量化方案"：POST /api/quantization/jobs {modelId} → jobId
3. 轮询 GET /api/quantization/jobs/{jobId}（1s）：
   status=sensitivity_analysis/scheme_search 时更新进度文案（message、progress）
   status=scheme_ready → GET .../schemes，渲染帕累托前沿（替换 mockLayers 假生成）
4. 用户选方案 → POST .../select {schemeIndex}
5. 继续轮询到 om_ready，期间用 progress 驱动进度条
6. "导出量化后模型" → 跳转 /api/quantization/jobs/{jobId}/om/download
```

### DeploymentPage

```
1. 模型下拉：GET /api/models → 过滤 status === 'completed'
   设备下拉：GET /api/devices  → 过滤 status === 'online'
2. POST /api/deployments {modelId, deviceId}（targetDir 可省略）
3. 轮询 GET /api/deployments/{id}（1s）→ logs/status/metrics/progress
   logs 类型已区分 info/success/warning/error，直接喂现有日志组件
4. 历史列表：GET /api/deployments（含 modelName/deviceName，可直接显示）
5. 详情弹窗：GET /api/deployments/{id}；失败可 POST /{id}/retry
```

### HomePage / ComparisonPage

```
HomePage:       GET /api/stats
ComparisonPage: GET /api/deployments?status=success 拿历史 → 选中后
                GET /api/comparison?deploymentId=… （rows + radar 都已算好）
```

### 建议的 api 层骨架（`web/src/api/`）

```ts
// client.ts
const BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let detail = `请求失败 (${res.status})`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* 非 JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(p: string, body: unknown) => request<T>(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  del: <T>(p: string) => request<T>(p, { method: 'DELETE' }),
  upload: <T>(p: string, file: File, extra?: Record<string, string>) => {
    const form = new FormData();
    form.append('file', file);
    Object.entries(extra ?? {}).forEach(([k, v]) => form.append(k, v));
    return request<T>(p, { method: 'POST', body: form });
  },
};
```

---

## 6. 前端接入现状（已完成）

前端已经按本文档完成对接，`web/src` 现在的结构：

```
web/src/
├── api/            # client.ts（fetch 封装 + ApiError + 错误文案）+ 各资源模块 + index.ts
├── hooks/          # useDeviceMetrics.ts（设备监控 2s 轮询 + 历史曲线）
├── utils/format.ts # npuLabel / 状态文案 / 体积时间格式化 / NPU 下拉选项
├── types/index.ts  # 与后端响应逐字段对齐（含 Job / Scheme / Stats / Comparison）
├── store/appStore.ts  # devices/models/presets/deployments/stats/comparison 全部走真实接口
└── pages/*.tsx     # 五个页面全部替换掉 mock 逻辑
```

| 位置 | 改造前 | 改造后 |
| --- | --- | --- |
| `types/index.ts` | `npuType: 'kirin' \| 'rockchip'` | 增加 `'ascend'`（后端默认值），`preset` 改为 slug 字符串 |
| `store/appStore.ts` | 初值 = mock 数组，增删改只改本地 | 初值 `[]`，全部 action 调后端接口；新增 `presets / stats / comparison` 与 loading/error 状态 |
| `data/mockData.ts` | 五个页面共享假数据 | **已删除**（改为 `GET /api/models/presets` 等真实数据源） |
| `QuantizationPage` | 假 layers + 随机进度 | 预设/上传 → 创建任务 → 轮询 `GET /jobs/{id}` → 帕累托前沿选方案 → `select` → 轮询到 `om_ready` → 下载 `.om`，并展示真实进度日志 |
| `DevicesPage` | 随机漂移的监控曲线、假检测 | 真实 CRUD + `/check`（带往返延迟提示）+ `/metrics` 2s 轮询 + `/metrics/history` 初始曲线 + 批量检测 |
| `DeploymentPage` | 假日志 + `Math.random()` 成败 | `POST /deployments` + 1s 轮询日志/进度/指标 + 历史列表 + 详情弹窗 + 失败重试 + 估算值角标 |
| `HomePage` | stats 写死 | `GET /api/stats`（活跃设备/已量化模型/部署次数/平均延迟真实聚合） |
| `ComparisonPage` | 前端乘系数推算 | `GET /api/comparison?deploymentId=` 的 rows + radar（后端按层位宽重算，口径与部署指标一致） |
| `components/ui/Button.tsx` | 与 framer-motion 类型冲突 | 改用 `HTMLMotionProps<'button'>`，`npx tsc --noEmit` 现在零错误 |
| `vite.config.ts` | 无代理 | dev/preview 代理 `/api` → `VITE_API_PROXY_TARGET` |

### 本地跑起来

```bash
# 1) 后端
cd backend && ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000   # Windows: venv\Scripts\uvicorn

# 2) 前端
cd web && npm run dev        # http://localhost:5173
```

或者只跑后端一个端口：`cd web && npm run build`，
后端检测到 `web/dist/index.html` 会自动把前端挂到根路径 `/`，
直接访问 `http://localhost:8000` 即可（已验证）。

### 联调自检

```bash
cd backend && python scripts/smoke_http.py http://localhost:5173   # 走 vite 代理，跑完整链路
```

### 已解决的字段差异

| 前端原字段 | 处理方式 |
| --- | --- |
| `Device.npuType: 'kirin' \| 'rockchip' \| 'other'` | 类型加 `'ascend'`；显示文案改由 `utils/format.npuLabel()` 统一映射 |
| `ModelConfig.status` | 直接用后端 `idle/processing/completed/failed`，`DeploymentPage` 过滤 `completed` |
| `Deployment.modelId/deviceId` | 后端额外返回 `modelName/deviceName`，历史列表与详情弹窗直接显示，无需再查表 |
| `Deployment.metrics` | 后端新增 `metricsSource`（`measured`/`estimated`），UI 上以角标区分实测与估算 |
| 对比页 `radarChartData` | 改用 `GET /api/comparison` 的 `radar`（字段名同为 `metric/traditional/mixedPrecision`） |

---

## 7. 当前实现边界（避免误判为 bug）

1. **算法是占位实现**：HAWQ 敏感度用层名 md5 派生、NSGA-II 用"INT8 覆盖率 + 敏感度排序"生成 6 个非支配解、
   AMCT/ATC 只做文件搬运。协议（JSONL 进度）、产物文件名、状态机都是最终形态，换真实现时前端零改动。
2. **性能指标在无板子时是估算值**：`metricsSource="estimated"`；配好 `deployment.bench_command` 后为实测值。
3. **上传的 ONNX 不做真实解析**：装了 `onnx` 包就读取真实层名与权重大小，否则用层数固定的占位层表；
   预设模型走预设层模板。
4. **无鉴权**：接口是全开的，仅限内网/联调环境；对外暴露前需加认证（当前不在范围内）。
5. **任务并发为 1**：服务器内存小，算法与部署推送共用一个串行线程池；排队时任务停在 `pending`。
6. **设备密码明文存 SQLite**：内网联调可接受，上线前应换成密钥或加密存储。
