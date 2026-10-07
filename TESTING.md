# 前后端测试手册（本工作区自测用）

适用目录：`C:\Users\Lenovo\Desktop\system`
（`backend/` 后端 + `web/` 前端 + `tools/` 本地运行环境 + `HD/` 需求与计划文档）

> 本文里的每条命令都在本机实跑过，预期输出按实际结果写。
> 命令里的 `scripts\local.cmd` 都在 **`backend` 目录下**执行。

---

## 0. 先读：本工作区的环境事实

| 事实 | 说明 |
| --- | --- |
| **没有系统 Python** | PATH 上的 `python` 是 Microsoft Store 占位桩（执行返回 9009）。真解释器在 `tools\py38\python.exe`（Python 3.8.10，依赖与服务器 `requirements.txt` 完全一致） |
| Node / npm | v24.21.0 / 11.19.0，`web\node_modules` 已安装 |
| 后端快捷脚本 | `backend\scripts\local.cmd {test\|quick\|e2e\|lint\|serve\|smoke\|clean}` |
| 端口 | 后端 8000、前端 dev 5173、前端 preview 4173（默认都空闲） |
| 没有 WSL、没有 sshd | 涉及 SSH 的"真机"链路要用 ECS 服务器或开发板，见第 6 节 |
| 数据落点 | `backend\app.db`（SQLite）+ `backend\workspace\<job_id>\`（任务产物）+ `backend\workspace\uploads\`（上传的 onnx） |
| 测试隔离 | pytest 用系统临时目录做库与工作目录，**不会**动 `app.db` / `workspace` |

命令行里统一用：`C:\Users\Lenovo\Desktop\system\tools\py38\python.exe`（下称"本地解释器"）。

---

## 1. 五分钟自检（每次改动后先跑这几条）

```bat
cd C:\Users\Lenovo\Desktop\system\backend
scripts\local.cmd quick        :: → 47 passed in ~31s
scripts\local.cmd lint         :: → 只有 3 行 "imported but unused"（预期，见下）

cd ..\web
npx tsc --noEmit               :: → 无任何输出（0 错误）
```

`lint` 的 3 行为什么是预期的：`app\db.py`、`tests\conftest.py`、`tests\test_models_smoke.py` 里
`import app.models` 是为了把表模型注册进 SQLAlchemy metadata，属于"必须但不使用"的导入。

---

## 2. 后端测试

### 2.1 pytest（不需要起服务）

| 命令（在 `backend` 下） | 用例数 | 耗时 | 用途 |
| --- | --- | --- | --- |
| `scripts\local.cmd quick` | 47 | ~31s | 日常回归：设备/模型/统计/流水线/执行器/算法脚本 |
| `scripts\local.cmd e2e` | 29 | ~75s | 端到端：任务状态机、选方案、部署推送、对比 |
| `scripts\local.cmd test` | 76 | ~106s | 全量（提交前跑这个） |

单文件、单用例、按关键字：

```bat
"C:\Users\Lenovo\Desktop\system\tools\py38\python.exe" -m pytest tests\test_devices.py --no-header
"C:\Users\Lenovo\Desktop\system\tools\py38\python.exe" -m pytest tests\test_jobs_api.py -k "cancel or select" -v
"C:\Users\Lenovo\Desktop\system\tools\py38\python.exe" -m pytest tests\test_deployments.py::test_push_failure_marks_failed -v
```

覆盖范围（对着计划文档的 15 个 Task 逐项落）：健康检查与契约元信息、设备 CRUD/探活/指标、
模型上传下载删除/预设/层信息、任务 8 态状态机与防重入、帕累托前沿与推荐方案、`.om` 下载、
取消与超时、四个算法脚本的 JSONL 协议与产物、部署推送成功/失败/重试/实测指标、统计与对比。

### 2.2 起真服务 + HTTP 全链路自检

两个窗口：

```bat
:: 窗口 A（保持在跑）
cd C:\Users\Lenovo\Desktop\system\backend
scripts\local.cmd serve
:: → starting backend on http://127.0.0.1:8000
::   Swagger UI: http://127.0.0.1:8000/docs

:: 窗口 B
cd C:\Users\Lenovo\Desktop\system\backend
scripts\local.cmd smoke
```

`smoke` 预期 **20/20 通过**（约 20~30s），典型输出结尾：

```
[OK  ] GET /api/health -- {'status': 'ok', 'version': '0.2.0', ...}
[OK  ] POST /api/models/preset -- MobileNetV2 层数=8
[OK  ] 轮询到 scheme_ready -- 进度 100%
[OK  ] GET .../schemes -- 推荐方案 #1
[OK  ] 轮询到 om_ready -- hasOm=True
[OK  ] GET .../om/download -- 38 字节
[OK  ] GET /api/comparison -- [...]
[OK  ] 部署日志与失败回执 -- status=failed（无真机时失败属预期）: timed out
通过 20 项，失败 0 项
```

**"部署"那步失败是正常的**：它会真的 SSH 连你建的那台假设备，10 秒超时后失败。
这恰好验证了失败路径、日志回执和任务状态回退。想让它成功，见第 6 节。

### 2.3 手工点接口

- Swagger UI：<http://127.0.0.1:8000/docs> —— 每个接口都能点 "Try it out" 直接发请求
- 契约速查：<http://127.0.0.1:8000/api/meta> —— 状态机枚举、字段约定、错误格式、轮询建议

PowerShell 手工走一遍（设备 → 探活 → 指标）：

```powershell
$b = '{"name":"手测板","ip":"10.0.0.9","port":22,"username":"root","password":"x","npuType":"ascend"}'
$d = Invoke-RestMethod http://127.0.0.1:8000/api/devices -Method POST -ContentType application/json -Body $b
Invoke-RestMethod "http://127.0.0.1:8000/api/devices/$($d.id)/check" -Method POST   # 约 10s 后返回 online=false
Invoke-RestMethod "http://127.0.0.1:8000/api/devices/$($d.id)/metrics"             # 连不上 → HTTP 502 + detail
```

### 2.4 查数据与产物

```powershell
# 库里有什么（用本地解释器读 SQLite）
cd C:\Users\Lenovo\Desktop\system\backend
& ..\tools\py38\python.exe -c "import sqlite3;c=sqlite3.connect('app.db');print(c.execute('select name,ip,status from device').fetchall());print(c.execute('select status,count(*) from quantizationjob group by status').fetchall())"

# 任务产物
dir workspace
dir workspace\<job_id>     # model.onnx / layers.json / sensitivity.json / schemes.json /
                           # selected_scheme.json / quantized.onnx / model.om
```

### 2.5 失败诊断

| 想知道什么 | 怎么看 |
| --- | --- |
| 任务为什么失败 | `GET /api/quantization/jobs/{id}` 的 `error`（脚本 stderr 尾部）；`GET .../logs` 看阶段流水 |
| 部署为什么失败 | `GET /api/deployments/{id}` 的 `error` + `logs`（带 info/success/warning/error 分级） |
| 指标是不是真的 | `metricsSource`：`measured`=开发板实测，`estimated`=按方案估算 |
| 请求/响应的原文 | 后端控制台会打印每条请求；或让前端在 DevTools → Network 里看 |

---

## 3. 前端测试

```bat
cd C:\Users\Lenovo\Desktop\system\web

npx tsc --noEmit        :: 类型检查，应 0 错误（改造前基线有 20+ 处错误）
npm run build           :: 生产构建 → dist/（约 865KB JS / 31KB CSS，~8s）
npm run preview         :: 用 dist 起本地服务 http://localhost:4173（已配 /api 代理）
npm run dev             :: 开发服务器 http://localhost:5173（已配 /api 代理）
```

只想确认"前端能不能拿到后端数据"，不用开浏览器：

```powershell
Invoke-RestMethod http://localhost:5173/api/health    # 走 vite 代理 → 后端
Invoke-RestMethod http://localhost:5173/api/devices   # 有数据说明代理与后端都通
```

代理目标在 `web\.env.development`：

```ini
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://localhost:8000    # 换 ECS 就改这里
```

---

## 4. 前后端联调 + 逐页走查（重点）

### 4.1 启动（两个窗口）

```bat
:: 窗口 A —— 后端
cd C:\Users\Lenovo\Desktop\system\backend
scripts\local.cmd serve

:: 窗口 B —— 前端
cd C:\Users\Lenovo\Desktop\system\web
npm run dev
```

浏览器打开 <http://localhost:5173>。

### 4.2 先灌一套演示数据（推荐，省得页面全空）

```bat
cd C:\Users\Lenovo\Desktop\system\backend
:: 2 台设备 + 2 个已量化模型 + 一条演示用"成功部署"记录（含指标），并让一台设备显示为在线
"..\tools\py38\python.exe" scripts\seed_demo.py --fake-online --fake-deployment
```

输出会打印每一步（建设备、跑量化、选推荐方案、写演示部署记录）和最终统计。
**注意**：`--fake-online` 与 `--fake-deployment` 是直接改 SQLite 的演示数据，
只为让界面有东西可看；真实状态请以设备页"检测"和真实部署结果为准。

### 4.3 逐页走查清单

**首页**
1. 应看到四个卡片：活跃设备 `1/2`、已量化模型 `2`、部署次数 `1`、平均延迟 `14.8ms`
2. 点右上"刷新"→ 卡片会重新拉一次 `GET /api/stats`
3. 若后端没起，会出现黄条"统计数据加载失败：无法连接后端服务…"

**设备管理**
1. 设备卡片应有两张：`演示板-01`（在线）、`演示板-02`（离线）
2. 点 `演示板-01` → 右侧出现监控面板；约 2 秒后出现黄色横幅"指标采集失败：…"，
   这是**预期**：设备是演示数据里改成在线状态，但 SSH 真的连不上
3. 点"检测"→ 顶部提示探活失败原因（`timed out`），卡片状态变为**离线**
4. 点"监控"→ 面板切换；点"添加设备"→ 填名称/IP/账号/密码 → 卡片出现（真实落库）
5. 编辑 / 删除都要点一遍，确认列表实时变化
6. 要看到真实曲线，需要一台 SSH 可达的 Linux 机器（第 6 节）

**模型量化**
1. 选"预设模型" → 下拉里应有 4 个预设（MobileNetV2 / ResNet18 / YOLOv8 / EfficientNet-B0）
2. 点"生成量化方案" → 步骤条走到"分析中"，进度条下方出现**真实进度日志**
   （`加载 ONNX 模型` → `识别网络层结构` → `计算各层 Hessian 谱` → `帕累托前沿生成完毕`）
3. 约 2 秒后右侧出现 **6 个方案的帕累托前沿**：每个方案显示体积/延迟/精度损失/压缩率，
   带"推荐"角标的方案默认选中
4. **点不同方案** → 下面的"层配置预览"和三个统计卡（INT8 层 / FP16 层 / 压缩率）随之变化
5. 点"开始量化"→ 步骤条走到"量化中"，进度到 100% 后出现"量化完成"卡片
6. 点"导出量化后模型（.om）"→ 浏览器下载 `MobileNetV2_xxxxxxxx.om`
   （占位实现下它就是占位字节，真实接入 CANN 后是真 .om）
7. 也可点"取消任务"验证取消路径（任务变失败并给出"任务已取消"）

**一键部署**
1. 模型下拉应只列**已量化**的模型（2 个）；设备下拉列非离线设备
2. 点"一键部署"→ 日志区按后端真实回执逐条追加：
   `开始部署任务` → `正在上传量化模型文件...` → 约 10 秒后 `部署异常: timed out`（error 红字）
3. 出现失败横幅 + "重试"按钮；点重试会再发一次 `POST /api/deployments/{id}/retry`
4. 下方"部署历史"点任意一条 → 详情弹窗（部署时间/目标设备/推送目录/状态/性能指标/完整日志/模型层信息）
5. 弹窗里"删除记录"、"重新部署"都点一遍

**效果对比**
1. 下拉会自动选中最近一条**成功**的部署记录（演示数据那条）
2. 应看到 4 张变化卡（精度/延迟/内存/功耗）、性能雷达图、指标对比柱状图、详细对比表
3. 表格里"传统全 INT8 vs 混合精度"两列由后端按层位宽重算，口径与部署指标一致
4. 若没有成功部署记录，页面会提示"请先完成一次模型部署"

### 4.4 顺便观察两件事

- **DevTools → Network**：设备页监控是 **2s** 一次 `/api/devices/{id}/metrics`；
  任务进度是 **1.2s** 一次 `/api/quantization/jobs/{id}`；部署日志是 **1s** 一次 `/api/deployments/{id}`
- **后端窗口**：每来一个请求 uvicorn 都会打一行访问日志，可直接对照页面操作

### 4.5 单端口模式（不想开两个服务）

```bat
cd C:\Users\Lenovo\Desktop\system\web
npm run build
:: 然后只启动后端，访问 http://127.0.0.1:8000
```
后端启动时会检测 `web\dist\index.html` 并自动挂到根路径 `/`，已验证可访问。

---

## 5. 数据管理

| 想做什么 | 命令 |
| --- | --- |
| 灌演示数据 | `..\tools\py38\python.exe scripts\seed_demo.py`（幂等，可重复跑） |
| 设备显示为在线（仅界面走查） | `... seed_demo.py --fake-online` |
| 造一条"成功部署"记录（仅有真机时才真实） | `... seed_demo.py --fake-deployment` |
| 真实发一次部署（会真连设备） | `... seed_demo.py --with-deployment` |
| 接入真机并探活 | `... seed_demo.py --real-device <HOST> <USER> <PASSWORD>` 或 `--key <私钥路径>` |
| **重置全部数据** | `scripts\local.cmd clean`（删 `app.db` 与 `workspace`，下次启动自动重建） |
| 前端"重置" | 直接刷新浏览器即可（状态都在后端，前端不落 localStorage） |

---

## 6. 涉及 SSH 的真机测试怎么搞

设备的探活/指标、部署推送都需要一台能 SSH 的 Linux 机器。三种办法：

**方案 A：拿 ECS 服务器当靶子（最省事，推荐）**

```bat
cd C:\Users\Lenovo\Desktop\system\backend
:: 密码登录
"..\tools\py38\python.exe" scripts\seed_demo.py --real-device 121.43.244.6 ecs-user 你的密码
:: 或用已授权的私钥
"..\tools\py38\python.exe" scripts\seed_demo.py --real-device 121.43.244.6 ecs-user --key %USERPROFILE%\.ssh\id_rsa
```
这条命令会建设备、真探活、真采指标。之后：
- 设备页能看到真实 CPU/内存曲线（2s 一个点）
- 一键部署会真 SFTP 把 `.om` 推到 `/data/models`（可在服务器上 `ls /data/models` 核对）
- 部署成功后 `metricsSource` 若为 `estimated`，说明没配 `deployment.bench_command`（配置了才是实测）

**方案 B：装 WSL2**（本机目前未安装，需管理员权限 + 重启）
```powershell
wsl --install -d Ubuntu
# 进 WSL 后： sudo apt update && sudo apt install -y openssh-server && sudo service ssh start
# 然后同样用 seed_demo.py --real-device 127.0.0.1 <用户名> <密码>
```
好处：Linux 环境，`top`/`free` 都可用，后续接 CANN/AMCT/ATC 也在 Linux 上。

**方案 C：Windows 开 OpenSSH Server**（管理员）
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.0.0
Start-Service sshd
```
探活与 SFTP 可用，但**指标采集命令是 Linux 的**（`top -bn1`、`free -m`、`/proc/meminfo`），
在 Windows 上会返回 `0.0`，不要据此判断功能坏了。

---

## 7. 在 ECS 服务器上跑同一套

```bash
scp -r backend ecs-user@121.43.244.6:~/quant-deploy-backend/
ssh ecs-user@121.43.244.6 'cd ~/quant-deploy-backend && ./venv/bin/python -m pytest tests/ -q'
ssh ecs-user@121.43.244.6 'cd ~/quant-deploy-backend && ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000'
```
前端在服务器上单端口交付：
```bash
cd web && npm run build && scp -r dist ecs-user@121.43.244.6:~/quant-deploy-backend/../web-dist/
```
然后访问 `http://121.43.244.6:8000`（需在阿里云安全组放行 8000）。
`scripts\local.cmd` 只在 Windows 用；Linux 上直接 `./venv/bin/python -m pytest`。

---

## 8. 排查表

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `python` 提示不是内部命令 / 返回 9009 | PATH 上的 python 是 Store 占位桩 | 用 `tools\py38\python.exe` 或 `scripts\local.cmd` |
| 前端页面黄条"无法连接后端服务" | 后端没起 / 端口不对 | 先 `scripts\local.cmd serve`；确认 `web\.env.development` 的代理目标 |
| `npm run dev` 起不来，提示端口占用 | 5173 被占 | 关掉旧进程，或 `npm run dev -- --port 5174` |
| 设备一直离线、指标 0 | 没有真机 / SSH 命令在 Windows 不可用 | 见第 6 节；这是预期行为 |
| 监控面板出现"指标采集失败" | 设备状态在线但 SSH 连不上（常见于 `--fake-online`） | 正常；点"检测"会把状态纠正为离线 |
| 部署立刻失败、error 是 `timed out` | 目标设备不可达 | 用真机，或只验证失败路径（日志/重试都已覆盖） |
| 任务停在 `pending` | 调度器并发=1，前面还有任务在跑 | 等它跑完；`GET /api/quantization/jobs` 看队列 |
| 选方案返回 409 | 任务不是 `scheme_ready` | 等前端轮询到"待选方案"再点 |
| 对比页空白 | 没有 `status=success` 的部署记录 | 用真机部署一次，或 `--fake-deployment` 看界面 |
| 想要干净的初始状态 | —— | `scripts\local.cmd clean` 后重启后端 |

---

## 9. 回归清单

| 改了什么 | 最少要跑 |
| --- | --- |
| 后端 `app/`、`algorithms/` | `scripts\local.cmd test`（76 用例）+ `serve` 后 `smoke`（20 项） |
| 后端接口字段/响应结构 | 上面两条 + 前端 `npx tsc --noEmit`（类型不对会直接报错） |
| 前端页面/组件 | `cd web && npx tsc --noEmit && npm run build`，再按 4.3 走查相关页面 |
| 前端 api 层 / store | 同上 + 联调一次（第 4 节）确认轮询与错误提示正常 |
| 配置（`config.yaml` / `.env.development`） | `smoke` + 前端页面刷新 |
