# 智能模型量化部署一体化平台

ONNX 模型混合精度量化 → 帕累托方案优选 → 一键部署到昇腾 NPU 开发板 → 性能对比。

- **后端**：FastAPI + SQLModel/SQLite，跑在 **WSL 的 Ubuntu 22.04** 里
- **前端**：React + Vite + TypeScript，跑在 **Windows** 上
- **浏览器访问**：<http://localhost:5173>

> 本机环境已经配置完毕，直接看「[二、启动](#二启动)」即可。
> **要部署到服务器**见 [`DEPLOY.md`](DEPLOY.md)（含配置要求、鉴权、常见问题）。
> 从零搭建的完整说明见 [`TESTING.md`](TESTING.md)。

---

## 一、这套东西是怎么跑起来的

```
        Windows                              WSL / Ubuntu 22.04
┌──────────────────────────┐        ┌──────────────────────────────┐
│  浏览器                   │        │                              │
│    ↓ localhost:5173      │        │                              │
│  Vite dev server         │ ──────▶│  uvicorn  localhost:8000     │
│    ↑ 代码: web/          │  /api  │    ↑ 代码: /mnt/c/.../backend │
│                          │  代理   │    ↑ venv: /root/.venvs/quant │
└──────────────────────────┘        └──────────────────────────────┘
```

代码**只有一份**，就在 `C:\Users\PC\Desktop\system`。WSL 通过 `/mnt/c` 读取同一批文件，
所以在 Windows 里用 VS Code 改代码，Linux 侧立刻生效，不需要同步。

---

## 二、启动

需要**两个窗口**，都要保持开着。

### 窗口 A —— 后端（Ubuntu）

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\wsl.cmd serve
```

看到这一行就是起来了：

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 窗口 B —— 前端（Windows）

```bat
cd C:\Users\PC\Desktop\system\web
npm run dev
```

看到 `Local: http://localhost:5173/` 即可。

### 然后

浏览器打开 **<http://localhost:5173>**

---

## 三、停止

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\wsl.cmd stop          :: 停后端
```

前端窗口直接按 `Ctrl+C`。

> ⚠️ **直接关掉窗口 A 不会停止后端**。WSL 里的进程独立于 Windows 客户端，
> 会继续占着 8000 端口，下次启动就会报 `address already in use`。
> 停后端请用 `wsl.cmd stop`。

---

## 四、界面怎么用

左侧边栏五个页面：

### 1. 首页
概览卡片：活跃设备 / 已量化模型 / 部署次数 / 平均延迟。右上角「刷新」重新拉数据。

### 2. 模型量化
主流程所在页面：

1. 选**预设模型**（MobileNetV2 / ResNet18 / YOLOv8 / EfficientNet-B0），或上传自己的 `.onnx`
2. 点「生成量化方案」→ 进度条 + 实时日志（加载模型 → 识别层结构 → 计算敏感度 → 帕累托前沿）
3. 出现 **6 个候选方案**，每个显示体积 / 延迟 / 精度损失 / 压缩率，带「推荐」角标的默认选中
4. **点不同方案**可以对比：下方「层配置预览」和三个统计卡会跟着变
5. 点「开始量化」→ 进度到 100% 后出现「量化完成」
6. 点「导出量化后模型（.om）」下载产物

### 3. 一键部署
1. 选一个**已量化**的模型 + 目标设备
2. 点「一键部署」→ 日志区逐条追加真实回执
3. 失败会出「重试」按钮；下方「部署历史」点任意一条看详情弹窗

> 没有真实设备时，部署会在约 10 秒后以 `timed out` 失败 —— **这是预期行为**，
> 正好验证失败路径、日志回执和重试。想让它成功，见「[六、真机链路](#六真机链路wsl-当靶机)」。

### 4. 效果对比
自动选中最近一条**成功**的部署记录，展示精度/延迟/内存/功耗的变化卡、雷达图、对比表。

> 没有成功部署记录时页面会提示「请先完成一次模型部署」。
> 想先看界面效果，可以灌演示数据（见下）。

### 5. 设备管理
设备卡片列表。点设备 → 右侧监控面板（每 2 秒刷新 CPU/内存曲线）。
支持添加 / 编辑 / 删除 / 检测（SSH 探活）。

---

## 五、常用操作

### 灌演示数据（让界面不是空的）

```bat
cd C:\Users\PC\Desktop\system\backend
..\tools\py38\python.exe scripts\seed_demo.py --fake-online --fake-deployment
```

会建 2 台设备、2 个已量化模型、1 条成功部署记录。
`--fake-online` / `--fake-deployment` 直接改数据库，只为让界面有东西可看，不是真实状态。

### 跑测试

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\wsl.cmd quick      :: 快的子集
scripts\wsl.cmd test       :: 全量
```

前端类型检查与构建：

```bat
cd C:\Users\PC\Desktop\system\web
npx tsc --noEmit
npm run build
```

### 看环境状态

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\wsl.cmd doctor     :: 发行版 / venv / sshd / 端口 一次看全
```

### 进 Linux shell

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\wsl.cmd shell
```

### 接口文档

- Swagger UI：<http://localhost:8000/docs>（每个接口都能点 "Try it out"）
- 契约速查：<http://localhost:8000/api/meta>

### 重置数据

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\local.cmd clean    :: 删 app.db 与 workspace，下次启动自动重建
```

---

## 六、真机链路（WSL 当靶机）

设备探活、指标采集、部署推送都需要一台能 SSH 的 Linux 机器。本机的 WSL 就能充当这个角色。

**1. 让 WSL 的 sshd 起来**（`serve` 会自动做，也可手动）：

```bat
cd C:\Users\PC\Desktop\system\backend
scripts\wsl.cmd ssh
```

**2. 注册成设备**：

```bat
..\tools\py38\python.exe scripts\seed_demo.py --real-device 127.0.0.1 quant <密码>
```

> SSH 用户是 `quant`。密码在首次配置时生成过；忘了就在 Linux shell 里重设：
> `passwd`（当前就是 quant 用户），或 `sudo passwd quant`。

**3. 之后**：

- 设备页能看到**真实的** CPU / 内存曲线（每 2 秒一个点）
- 一键部署会真的通过 SFTP 把 `.om` 推到 `/data/models`
- 部署成功后 `metricsSource` 若为 `estimated`，说明没配 `deployment.bench_command`

---

## 七、目录结构

```
system/
├── backend/                 FastAPI 后端
│   ├── app/                 主要代码（路由 / 模型 / 调度器 / 执行器 / SSH）
│   ├── algorithms/          4 个算法脚本（当前是占位实现，协议已定型）
│   ├── tests/               pytest（76 个用例）
│   ├── scripts/
│   │   ├── wsl.cmd          ★ 在 WSL 里跑后端 / 测试
│   │   ├── local.cmd        在 Windows 里跑后端 / 测试（旧方式，仍可用）
│   │   └── seed_demo.py     灌演示数据 / 接真机
│   ├── docs/API_CONTRACT.md 前后端接口契约
│   └── config.yaml          配置（算法路径 / SSH 超时 / 部署目录等）
├── web/                     React 前端
│   ├── src/pages/           5 个页面
│   ├── src/api/             接口封装
│   └── .env.development     代理目标（默认指向 localhost:8000）
├── tools/py38/              嵌入式 Python 3.8（Windows 侧脚本用）
├── HD/                      需求与计划文档
├── TESTING.md               完整测试手册（逐页走查清单）
└── README.md                ← 本文件
```

---

## 八、常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `address already in use` | 旧后端进程还在（关窗口没杀掉） | `scripts\wsl.cmd stop` 后重试 |
| 页面黄条「无法连接后端服务」 | 后端没起，或 WSL 空闲后自动关停了 | `scripts\wsl.cmd serve` |
| `npm run dev` 提示 5173 被占 | 有旧的 vite 进程 | 用它提示的新端口（如 5174），或关掉旧窗口 |
| 设备一直离线、指标为 0 | 没接真机，或 SSH 连不上 | 见第六节；这是预期行为 |
| 监控面板报「指标采集失败」 | 设备状态在线但 SSH 连不上（`--fake-online` 的演示数据） | 正常；点「检测」会把状态纠正为离线 |
| 部署立刻失败、error 是 `timed out` | 目标设备不可达 | 接真机，或只验证失败路径 |
| 任务停在 `pending` | 调度器并发=1，前面还有任务在跑 | 等它跑完，或看 `GET /api/quantization/jobs` 队列 |
| 对比页空白 | 没有 `status=success` 的部署记录 | 用真机部署一次，或 `--fake-deployment` 看界面 |
| 想恢复干净状态 | —— | `scripts\local.cmd clean` 后重启后端 |

---

## 九、环境说明（本机现状）

| 组件 | 位置 / 版本 | 备注 |
| --- | --- | --- |
| WSL 发行版 | `E:\WSL\Ubuntu-22.04` | Ubuntu 22.04.5 LTS，已从 C 盘移到 E 盘 |
| 后端 Python | `/root/.venvs/quant`（Python 3.10.12） | venv 放在 Linux 侧，避免 `/mnt/c` 慢速 I/O |
| 项目代码 | `C:\Users\PC\Desktop\system` | 未搬家，WSL 经 `/mnt/c` 读取 |
| 前端 Node | Windows 侧 | `web\node_modules` 已安装 |
| 数据库 | `backend\app.db` | SQLite，两端共用同一份 |
| 任务产物 | `backend\workspace\<job_id>\` | onnx / json / .om |

### 两个容易踩的点

1. **WSL2 空闲约 30 秒会自动关停发行版**，关停后 8000 端口不通。
   `scripts\wsl.cmd serve` 已内置保活进程防止这一点；WSL 重启后需要重新 `serve` 一次。

2. **在 Git Bash 里直接调 `wsl` 命令会出错**（`execvpe ... failed`）——
   Git Bash 会把 `/bin/echo` 这类路径改写成 Windows 路径。
   `wsl.cmd` 是 cmd 脚本，不受影响；如果你在 Git Bash 里手敲 `wsl`，先执行 `export MSYS_NO_PATHCONV=1`。

---

## 十、已知边界

- `algorithms/` 下 4 个脚本是**占位实现**（协议与产物格式已定型，换真实现时前后端不用改）
- CANN / AMCT / ATC 真实工具链尚未接入
- **无鉴权**：对外暴露前需要加认证；设备密码当前明文存在 SQLite
- 服务器内存 1.8G（已配 4G swap），正式跑算法前建议升级实例
