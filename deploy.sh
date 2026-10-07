#!/usr/bin/env bash
# ============================================================================
#  智能模型量化部署一体化平台 —— 服务器部署脚本
#
#  用法（在项目根目录执行）：
#      ./deploy.sh check     环境体检，只读不装东西 —— 先跑这个
#      ./deploy.sh deps      建 venv 并安装 Python 依赖
#      ./deploy.sh cann      下载并安装 CANN 工具链（ATC 转 .om 必需）
#      ./deploy.sh frontend  构建前端并放到后端静态目录（单端口交付）
#      ./deploy.sh service   注册 systemd 服务（开机自启 + 崩溃重启）
#      ./deploy.sh all       = deps + cann + frontend + service
#
#  可用环境变量覆盖：
#      APP_DIR      后端目录（默认：脚本所在目录/backend）
#      DATA_DIR     大文件落盘目录（默认 /data，不存在就退到 APP_DIR 同级）
#      CANN_VER     CANN 版本（默认 9.1.1）
#      SOC_VERSION  目标芯片（默认 Ascend310B4 = Atlas 200I DK A2）
#      API_KEY      API 鉴权密钥（留空 = 不鉴权，对外部署务必设置）
#
#  若从 Windows 拷过来后报 "bad interpreter"，先去掉 CRLF：
#      sed -i 's/\r$//' deploy.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$SCRIPT_DIR/backend}"

# 数据盘探测：各家云平台叫法不同（/data、autodl-tmp…），
# 30GB 系统盘装不下 CANN + torch，所以优先挑一个独立挂载点。
detect_data_dir() {
    for candidate in /data "$HOME/autodl-tmp" /root/autodl-tmp /mnt/data /workspace "$SCRIPT_DIR/.data"; do
        if [ -d "$candidate" ] && [ -w "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
}
DATA_DIR="${DATA_DIR:-$(detect_data_dir)}"
VENV_DIR="$DATA_DIR/venvs/quant"
# CANN 要求安装路径的**所有父目录都是 755**（断言可被其他用户读取）。
# /root 是 700 —— 所以即便数据盘 /root/autodl-tmp 是 755，装在它下面照样失败：
#     [ERROR] the given dir, or its parents, permission is invalid.
# 因此 CANN 默认装到官方的 /usr/local/Ascend（父目录全是 755），不吃这个亏。
CANN_HOME="${CANN_HOME:-/usr/local/Ascend}"
CANN_INSTALLER_DIR="$DATA_DIR/cann-installers"
CANN_VER="${CANN_VER:-9.1.1}"
SOC_VERSION="${SOC_VERSION:-Ascend310B4}"
API_KEY="${API_KEY:-}"
SERVICE_NAME="quant-deploy"
# 监听端口。注意 GPU 云平台（AutoDL / seetacloud 等）的「自定义服务」有固定端口：
#   AutoDL 系：6006（TensorBoard 占 6007、JupyterLab 占 8888，别撞）
#   平台的公网地址写在容器里的 /init/others/help，形如
#     export AutoDLService6006URL=https://uXXXX-XXXX-XXXX.westd.seetacloud.com:8443
#   把服务跑在 6006 上，那个地址就直接能用，无需在控制台做任何映射。
PORT="${PORT:-8000}"
CANN_REPO="https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%20${CANN_VER}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[36m%s\033[0m\n' "$*"; }
warn()  { printf '\033[33m%-14s %s\033[0m\n' "$1" "$2"; }

die() { red "✗ $*"; exit 1; }

# sudo 前缀（root 下为空）
sudo_prefix() { [ "$(id -u)" -ne 0 ] && echo "sudo"; }

# 系统 python3 是 CANN 的 ATC 认的那个。有些 GPU 平台只有 conda 的
# python3，没有 /usr/bin/python3 —— 这时补装一个，避免 ATC 报
# "No module named 'numpy'" 或找不到解释器。
ensure_system_python() {
    if [ -x /usr/bin/python3 ]; then
        return 0
    fi
    blue "===== 本机没有 /usr/bin/python3（只有 conda），补装系统 Python ====="
    $(sudo_prefix) apt-get update -qq
    $(sudo_prefix) apt-get install -y -qq python3 python3-dev python3-pip python3-venv
    [ -x /usr/bin/python3 ] || die "系统 python3 安装失败"
    green "✓ 系统 Python: $(/usr/bin/python3 --version)"
}

# 找一个能用的 python3。
# 非交互式 SSH 的 PATH 里往往没有 conda（要 .bashrc 才加进去），
# 所以不能只靠 command -v，得把常见安装位置都试一遍。
find_any_python() {
    for candidate in /usr/bin/python3 "$(command -v python3 2>/dev/null)" \
                     "$HOME/miniconda3/bin/python3" /root/miniconda3/bin/python3 \
                     /opt/conda/bin/python3 /usr/local/bin/python3; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

# 建 venv 用的解释器：优先系统 python3，保证环境与开发机一致
resolve_python() {
    if [ -x /usr/bin/python3 ]; then
        echo /usr/bin/python3
    else
        find_any_python || die "找不到任何 python3"
    fi
}

# --------------------------------------------------------------------------- #
# 体检
# --------------------------------------------------------------------------- #
cmd_check() {
    blue "===== 系统 ====="
    . /etc/os-release 2>/dev/null && echo "OS: $PRETTY_NAME ($VERSION_CODENAME)"
    echo "内核: $(uname -r)"

    blue "===== Python ====="
    local py
    py="$(find_any_python)" || die "系统里找不到任何 python3"
    echo "可用解释器: $py"
    "$py" --version
    "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' \
        || die "Python 版本过低（需要 3.9+）"
    if [ ! -x /usr/bin/python3 ]; then
        warn "提示" "/usr/bin/python3 不存在（只有 conda）—— deps 步骤会自动补装"
    fi

    blue "===== 内存 ====="
    local mem_gb
    mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
    echo "总内存: ${mem_gb} GB"
    # ATC 编译实测 4GB 会因内存不足崩（BrokenPipeError），6GB 才稳
    if [ "$mem_gb" -lt 6 ]; then
        red "⚠ 内存不足 6GB —— ATC 转 .om 会失败，建议升配或加 swap"
    elif [ "$mem_gb" -lt 8 ]; then
        warn "内存" "偏紧，建议确认有 swap 兜底"
    else
        green "✓ 内存充足"
    fi

    blue "===== 磁盘 ====="
    df -h / "$DATA_DIR" 2>/dev/null | grep -v tmpfs || true
    local avail_gb
    avail_gb=$(df -BG --output=avail "$DATA_DIR" 2>/dev/null | tail -1 | tr -dc '0-9')
    # CANN 6GB + torch 3GB + 依赖 1GB + 项目产物 3GB
    if [ -n "$avail_gb" ] && [ "$avail_gb" -lt 20 ]; then
        red "⚠ $DATA_DIR 只剩 ${avail_gb}GB —— 建议至少 20GB"
    fi

    blue "===== GPU（可选，只有将来跑真实 HAWQ 才需要）====="
    if command -v nvidia-smi >/dev/null 2>&1; then
        nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
        echo "提示：多数 AI 框架在 CUDA 13.x 上的支持还不全，建议用 cu128 构建的 torch"
    else
        echo "(无 NVIDIA 驱动 —— 本项目当前算法全在 CPU 上跑，不影响)"
    fi

    blue "===== CANN 下载速度（决定要不要本地下好再传）====="
    timeout 25 curl -s -o /dev/null -w '下载速度: %{speed_download} B/s\n' \
        -H "Referer: https://www.hiascend.com/" \
        -r 0-20000000 \
        "$CANN_REPO/Ascend-cann-toolkit_${CANN_VER}_linux-x86_64.run" 2>/dev/null || echo "(测速失败)"

    blue "===== 编译依赖 ====="
    for tool in git gcc g++ make cmake; do
        printf '%-8s ' "$tool"
        command -v "$tool" >/dev/null 2>&1 && echo "✓ 已装" || warn "缺失" "装 CANN 前需要"
    done

    echo
    blue "体检结束。目录规划："
    echo "  应用目录: $APP_DIR"
    echo "  数据目录: $DATA_DIR"
    echo "  venv    : $VENV_DIR"
    echo "  CANN    : $CANN_HOME"
}

# --------------------------------------------------------------------------- #
# Python 依赖
# --------------------------------------------------------------------------- #
cmd_deps() {
    [ -f "$APP_DIR/requirements.txt" ] || die "找不到 $APP_DIR/requirements.txt"

    ensure_system_python

    blue "===== 创建 venv: $VENV_DIR ====="
    mkdir -p "$(dirname "$VENV_DIR")"
    if [ -x "$VENV_DIR/bin/python" ]; then
        echo "已存在，复用"
    else
        "$(resolve_python)" -m venv "$VENV_DIR" || die "建 venv 失败（缺 python3-venv？）"
    fi
    "$VENV_DIR/bin/python" -V

    blue "===== 安装依赖（torch 约 200MB）====="
    # torch 的 +cpu 轮子只在 download.pytorch.org 上，国内实测 29 B/s（等于卡死）。
    # 默认走国内源：PyPI 用清华，torch 用阿里 pytorch-wheels（实测 11 MB/s）。
    # 海外机器或想用官方源，覆盖这两个变量即可：
    #   PIP_INDEX=https://pypi.org/simple PIP_FIND_LINKS= ./deploy.sh deps
    local pip_index="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
    local pip_links="${PIP_FIND_LINKS:-https://mirrors.aliyun.com/pytorch-wheels/cpu/}"
    echo "PyPI 源: $pip_index"
    echo "torch 源: $pip_links"

    "$VENV_DIR/bin/pip" install -q --upgrade pip
    # shellcheck disable=SC2086
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" \
        -i "$pip_index" --find-links "$pip_links" --timeout 60

    blue "===== 验证关键包 ====="
    "$VENV_DIR/bin/python" - <<'PY'
import sys
mods = ["fastapi", "sqlmodel", "paramiko", "numpy", "onnx", "onnxruntime", "pymoo", "torch", "torchvision"]
missing = []
for name in mods:
    try:
        __import__(name)
    except ImportError:
        missing.append(name)
if missing:
    print("缺包:", ", ".join(missing)); sys.exit(1)
import torch
print("torch", torch.__version__, "| CUDA 可用:", torch.cuda.is_available())
print("全部依赖就绪")
PY
    green "✓ 依赖装好了"
}

# --------------------------------------------------------------------------- #
# CANN（ATC 转 .om）
# --------------------------------------------------------------------------- #
ops_package_for() {
    case "$1" in
        Ascend310B*) echo "Ascend-cann-310b-ops" ;;
        Ascend310P*) echo "Ascend-cann-310p-ops" ;;
        Ascend910B*) echo "Ascend-cann-910b-ops" ;;
        Ascend910*)  echo "Ascend-cann-910-ops" ;;
        *)           echo "" ;;
    esac
}

cmd_cann() {
    local ops_pkg
    ops_pkg="$(ops_package_for "$SOC_VERSION")"
    [ -n "$ops_pkg" ] || die "不认识的 SOC_VERSION=$SOC_VERSION（310B/310P/910B/910）"

    # CANN 断言安装路径的父目录必须 755。装在 /root 下面必然失败，
    # 与其等到解压 2GB 后才报错，不如这里先拦下来。
    case "$CANN_HOME" in
        /root/*)
            die "CANN 不能装在 $CANN_HOME —— /root 权限是 700，CANN 要求父目录 755。
    改用默认路径重跑：  ./deploy.sh cann
    或指定别处：        CANN_HOME=/opt/Ascend ./deploy.sh cann"
            ;;
    esac

    blue "===== 安装系统依赖（ATC 要用系统 python3，不是 venv）====="
    local SUDO=""
    [ "$(id -u)" -ne 0 ] && SUDO="sudo"
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq gcc g++ make net-tools cmake python3-dev python3-pip patchelf

    mkdir -p "$CANN_INSTALLER_DIR"
    cd "$CANN_INSTALLER_DIR"

    local toolkit="${ops_pkg%%-ops}"
    for name in "Ascend-cann-toolkit" "$ops_pkg"; do
        local file="${name}_${CANN_VER}_linux-x86_64.run"
        if [ -f "$file" ]; then
            echo "$file 已存在，跳过下载"
            continue
        fi
        blue "下载 $file ..."
        curl -L --retry 3 -o "$file" \
            -H "Referer: https://www.hiascend.com/" \
            "$CANN_REPO/${file}"
        [ -s "$file" ] || die "$file 下载失败（检查网络/带宽）"
        chmod +x "$file"
    done

    blue "===== 安装 CANN 到 $CANN_HOME ====="
    mkdir -p "$CANN_HOME"
    ./Ascend-cann-toolkit_${CANN_VER}_linux-x86_64.run --install --quiet --install-path="$CANN_HOME"
    ./${ops_pkg}_${CANN_VER}_linux-x86_64.run --install --quiet --install-path="$CANN_HOME"

    blue "===== 给所有 python3 装 CANN 运行时依赖 ====="
    # ATC 调的是 "python3"（不是 venv），而具体是哪个 python3 取决于调用方的
    # shell：后端通过 `bash -lc` 调 atc，**登录 shell 会激活 conda**，
    # 这时 python3 指的是 conda 的；手动跑非登录 shell 时又是 /usr/bin/python3。
    # 两边都装，省得 ATC 报 EC0010 ModuleNotFoundError: No module named 'scipy'。
    local cann_pkgs="attrs cython numpy decorator sympy cffi pyyaml psutil scipy requests absl-py protobuf==3.20.0"
    local candidates="/usr/bin/python3 $HOME/miniconda3/bin/python3 /root/miniconda3/bin/python3
        /opt/conda/bin/python3 /usr/local/bin/python3 $(command -v python3 2>/dev/null)"
    echo "$candidates" | tr ' ' '\n' | grep -v '^$' | sort -u | while read -r py; do
        [ -x "$py" ] || continue
        echo "→ $py"
        if ! $SUDO "$py" -m pip install -q $cann_pkgs 2>/dev/null; then
            warn "跳过" "$py 缺 pip 或装依赖失败"
        fi
    done

    blue "===== 验证 atc ====="
    # shellcheck disable=SC1091
    source "$CANN_HOME/ascend-toolkit/set_env.sh"
    command -v atc >/dev/null 2>&1 || die "atc 不在 PATH —— 检查安装是否成功"
    atc --help >/dev/null 2>&1 && green "✓ atc 可用"

    blue "===== 清理安装包（省约 4GB）====="
    rm -f "$CANN_INSTALLER_DIR"/*.run
    echo "安装包已删；需要重装就重新跑本命令"

    green "✓ CANN 装好了。记得把 SOC_VERSION 告诉后端（config.yaml 的 algorithms.soc_version）"
}

# --------------------------------------------------------------------------- #
# 前端（单端口交付）
# --------------------------------------------------------------------------- #
cmd_frontend() {
    local web_dir="$SCRIPT_DIR/web"
    [ -d "$web_dir" ] || die "找不到 $web_dir"

    if ! command -v npm >/dev/null 2>&1; then
        warn "跳过" "没装 npm —— 前端可留在本机跑，vite 代理到服务器即可"
        return 0
    fi

    blue "===== 构建前端 ====="
    cd "$web_dir"
    [ -d node_modules ] || npm install
    [ -f .env.production ] || die "缺 .env.production（需要配 VITE_API_KEY）"
    npm run build

    blue "===== 拷到后端静态目录 ====="
    local target="$APP_DIR/../web-dist"
    rm -rf "$target"
    cp -r dist "$target"
    green "✓ 前端产物: $target"
    echo "  后端启动时会自动挂到根路径，直接访问 http://<服务器IP>:$PORT"
    echo "  也可用环境变量指定: QUANT_DEPLOY_STATIC_DIR=/path/to/dist"
}

# --------------------------------------------------------------------------- #
# systemd
# --------------------------------------------------------------------------- #
cmd_service() {
    if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
        cmd_service_systemd
    else
        cmd_service_container
    fi
}

# --------------------------------------------------------------------------- #
# 容器环境（无 systemd）—— 生成 start/stop/status 三个脚本
#
# GPU 云平台的容器大多是 bash 当 PID 1，没有 systemd。这时用 nohup 托管：
# 进程在 SSH 断开后依然存活，配合 PID 文件做启停。
# --------------------------------------------------------------------------- #
cmd_service_container() {
    blue "===== 检测到容器环境（无 systemd），生成管理脚本 ====="

    local key_line=""
    [ -n "$API_KEY" ] && key_line="export QUANT_DEPLOY_API_KEY='$API_KEY'"
    local static_line="export QUANT_DEPLOY_STATIC_DIR='$APP_DIR/../web-dist'"

    cat > "$SCRIPT_DIR/start.sh" <<'TEMPLATE'
#!/usr/bin/env bash
# 启动后端（容器环境用 nohup 托管，日志写 server.log）
set -u
APP_DIR="__APP_DIR__"
VENV="__VENV_DIR__"
PORT=__PORT__

cd "$APP_DIR" || { echo "找不到 $APP_DIR"; exit 1; }
PIDFILE="$APP_DIR/server.pid"
LOGFILE="$APP_DIR/server.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "已在运行 (pid $(cat "$PIDFILE"))"
    exit 0
fi

export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export SOC_VERSION="__SOC_VERSION__"
__STATIC_LINE__
__KEY_LINE__

nohup "$VENV/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" \
    > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        echo "✓ 后端已启动 (pid $(cat "$PIDFILE"))"
        echo "  本机访问: http://127.0.0.1:$PORT"
        echo "  外网访问: http://<服务器IP>:$PORT   (需放行端口)"
        exit 0
    fi
done
echo "✗ 10 秒内没起来，看日志: tail -50 $LOGFILE"
exit 1
TEMPLATE

    cat > "$SCRIPT_DIR/stop.sh" <<'TEMPLATE'
#!/usr/bin/env bash
set -u
PIDFILE="__APP_DIR__/server.pid"
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        for _ in 1 2 3 4 5; do sleep 1; kill -0 "$PID" 2>/dev/null || break; done
        kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null
        echo "已停止 (pid $PID)"
    else
        echo "进程不在了，清理 PID 文件"
    fi
    rm -f "$PIDFILE"
else
    echo "没有 PID 文件，可能没在跑"
fi
TEMPLATE

    cat > "$SCRIPT_DIR/status.sh" <<'TEMPLATE'
#!/usr/bin/env bash
set -u
APP_DIR="__APP_DIR__"
PORT=__PORT__
PIDFILE="$APP_DIR/server.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "运行中 (pid $(cat "$PIDFILE"))"
else
    echo "未运行"
fi
printf "健康检查: "
curl -sf "http://127.0.0.1:$PORT/api/health" || echo "(无响应)"
echo
printf "最近日志:\n"; tail -5 "$APP_DIR/server.log" 2>/dev/null || echo "(无日志)"
TEMPLATE

    # 模板占位符替换（用 awk 避免 sed 分隔符被路径里的 / 干扰）
    for f in start.sh stop.sh status.sh; do
        awk -v app="$APP_DIR" -v venv="$VENV_DIR" -v port="$PORT" \
            -v soc="$SOC_VERSION" -v key="$key_line" -v static="$static_line" '
            {
                gsub(/__APP_DIR__/, app)
                gsub(/__VENV_DIR__/, venv)
                gsub(/__PORT__/, port)
                gsub(/__SOC_VERSION__/, soc)
                gsub(/__KEY_LINE__/, key)
                gsub(/__STATIC_LINE__/, static)
                print
            }' "$SCRIPT_DIR/$f" > "$SCRIPT_DIR/$f.tmp" && mv "$SCRIPT_DIR/$f.tmp" "$SCRIPT_DIR/$f"
        chmod +x "$SCRIPT_DIR/$f"
    done

    blue "===== 启动服务 ====="
    "$SCRIPT_DIR/start.sh"

    echo
    yellow_note
}

yellow_note() {
    warn "提示" "容器重启后需要重新执行 ./start.sh（平台不会自动拉起）"
    echo "        想开机自启的话，把下面这行加到 ~/.bashrc 末尾："
    echo "        [ -x $SCRIPT_DIR/start.sh ] && $SCRIPT_DIR/start.sh >/dev/null 2>&1"
}

# --------------------------------------------------------------------------- #
# systemd（物理机 / 标准虚拟机）
# --------------------------------------------------------------------------- #
cmd_service_systemd() {
    local SUDO=""
    [ "$(id -u)" -ne 0 ] && SUDO="sudo"
    local unit="/etc/systemd/system/${SERVICE_NAME}.service"
    local api_key_line=""
    [ -n "$API_KEY" ] && api_key_line="Environment=QUANT_DEPLOY_API_KEY=$API_KEY"

    blue "===== 写入 $unit ====="
    $SUDO tee "$unit" >/dev/null <<EOF
[Unit]
Description=量化部署平台后端
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8
Environment=SOC_VERSION=$SOC_VERSION
Environment=QUANT_DEPLOY_STATIC_DIR=$APP_DIR/../web-dist
$api_key_line
# 注意：这里**不要**用 EnvironmentFile 加载 CANN 的 set_env.sh ——
# 那个文件是 shell 脚本（export X=$X:...），systemd 的 EnvironmentFile
# 不解析变量展开，会把字面量 "$LD_LIBRARY_PATH" 当值写进去。
# 后端本身也不需要它：atc_convert.py 会自己 source 后再调 atc。
ExecStart=$VENV_DIR/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable "$SERVICE_NAME"
    $SUDO systemctl restart "$SERVICE_NAME"
    sleep 3

    blue "===== 服务状态 ====="
    $SUDO systemctl status "$SERVICE_NAME" --no-pager | head -12 || true

    if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        green "✓ 后端已就绪: http://<服务器IP>:$PORT"
    else
        red "✗ 健康检查失败，看日志: journalctl -u $SERVICE_NAME -n 50"
    fi
}

# --------------------------------------------------------------------------- #
cmd_all() {
    cmd_deps
    cmd_cann
    cmd_frontend
    cmd_service
    echo
    green "===== 部署完成 ====="
    echo "  健康检查: curl http://127.0.0.1:$PORT/api/health"
    echo "  接口文档: http://<服务器IP>:$PORT/docs"
    echo "  查看日志: journalctl -u $SERVICE_NAME -f"
    if [ -z "$API_KEY" ]; then
        red "  ⚠ 未设置 API_KEY —— 对外暴露前务必重跑: API_KEY=xxx ./deploy.sh service"
    fi
    echo "  安全组只放行 $PORT（22 建议限来源 IP）"
}

case "${1:-check}" in
    check)    cmd_check ;;
    deps)     cmd_deps ;;
    cann)     cmd_cann ;;
    frontend) cmd_frontend ;;
    service)  cmd_service ;;
    all)      cmd_all ;;
    *)        echo "用法: $0 {check|deps|cann|frontend|service|all}"; exit 1 ;;
esac
