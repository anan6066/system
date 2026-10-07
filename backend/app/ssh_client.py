"""设备通道：paramiko SSH 探活 / 板载指标采集 / SFTP 部署推送。"""
import re
import time
from typing import Any, Dict, Optional, Tuple

import paramiko

from .config import get
from .models import Device, now_iso

_IDLE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*id")


def _connect_kwargs(device: Device) -> Dict[str, Any]:
    timeout = float(get("ssh.timeout", 10) or 10)
    kwargs: Dict[str, Any] = {
        "hostname": device.ip,
        "port": int(device.port or 22),
        "username": device.username,
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if device.authType == "key":
        kwargs["key_filename"] = device.keyPath or ""
    else:
        kwargs["password"] = device.password or ""
    return kwargs


def _client(device: Device) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(**_connect_kwargs(device))
    return client


def run_command(device: Device, command: str, timeout: Optional[float] = None) -> str:
    """执行远端命令并返回 stdout（失败抛异常）。"""
    limit = float(timeout or get("ssh.timeout", 10) or 10)
    client = _client(device)
    try:
        _, stdout, stderr = client.exec_command(command, timeout=limit)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        if code != 0 and not out.strip():
            raise RuntimeError(err.strip() or "远端命令退出码 %s" % code)
        return out
    finally:
        client.close()


def probe(device: Device) -> Tuple[bool, str]:
    """SSH 探活，返回 (是否在线, 错误信息)。"""
    try:
        client = _client(device)
    except Exception as exc:  # noqa: BLE001 —— 连接失败原因多样（超时/认证/网络），统一捕获
        return (False, str(exc))
    try:
        _, stdout, _ = client.exec_command("echo ok",
                                           timeout=float(get("ssh.timeout", 10) or 10))
        out = stdout.read().decode("utf-8", errors="replace").strip()
        return (out == "ok", "" if out == "ok" else "远端返回异常: %r" % out)
    except Exception as exc:  # noqa: BLE001
        return (False, str(exc))
    finally:
        client.close()


def _parse_cpu(text: str) -> Optional[float]:
    """从 top 的 %Cpu 行解析占用率；解析不出来返回 None。"""
    match = _IDLE_RE.search(text or "")
    if not match:
        return None
    idle = float(match.group(1))
    return round(max(0.0, min(100.0, 100.0 - idle)), 1)


def _parse_meminfo(text: str) -> Optional[float]:
    total = available = None
    for line in (text or "").splitlines():
        if line.startswith("MemTotal:"):
            total = float(line.split()[1])
        elif line.startswith("MemAvailable:"):
            available = float(line.split()[1])
        elif line.startswith("MemFree:") and available is None:
            available = float(line.split()[1])
    if not total:
        return None
    used = max(0.0, total - (available or 0.0))
    return round(used / total * 100.0, 1)


_NPU_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%?")


def _parse_npu(text: str) -> Optional[float]:
    """从 npu-smi info 里尽力抓一个 AICore 占用率（抓不到返回 None）。"""
    for line in (text or "").splitlines():
        if "AICore" in line or "aicore" in line.lower():
            percents = re.findall(r"([0-9]{1,3})\s*%", line)
            if percents:
                return float(percents[0])
    return None


def get_metrics(device: Device) -> Dict[str, Any]:
    """采集板载 CPU/内存（可选 NPU）占用，返回前端 Device 的 cpuUsage/memoryUsage。"""
    client = _client(device)
    timeout = float(get("ssh.timeout", 10) or 10)
    try:
        cpu_usage = memory_usage = None
        npu_usage = None

        cpu_command = get("ssh.metrics_cpu_command", "top -bn1 | grep -i '%Cpu'")
        try:
            _, stdout, _ = client.exec_command(cpu_command, timeout=timeout)
            cpu_usage = _parse_cpu(stdout.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            cpu_usage = None
        if cpu_usage is None:
            # 兜底：直接从 /proc/stat 算一次瞬时占用
            try:
                _, stdout, _ = client.exec_command(
                    "awk '/^cpu /{u=$2+$4; t=$2+$3+$4+$5+$6+$7+$8; printf \"%.1f\", u*100/t}' /proc/stat",
                    timeout=timeout)
                text = stdout.read().decode("utf-8", errors="replace").strip()
                cpu_usage = round(float(text), 1) if text else 0.0
            except Exception:  # noqa: BLE001
                cpu_usage = 0.0

        mem_command = get("ssh.metrics_mem_command",
                          "free -m | awk '/Mem:/ {printf \"%.1f\", $3/$2*100}'")
        try:
            _, stdout, _ = client.exec_command(mem_command, timeout=timeout)
            text = stdout.read().decode("utf-8", errors="replace").strip()
            memory_usage = round(float(text), 1) if text else None
        except Exception:  # noqa: BLE001
            memory_usage = None
        if memory_usage is None:
            try:
                _, stdout, _ = client.exec_command("cat /proc/meminfo", timeout=timeout)
                memory_usage = _parse_meminfo(stdout.read().decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                pass

        npu_command = get("ssh.metrics_npu_command", "")
        if npu_command:
            try:
                _, stdout, _ = client.exec_command(npu_command, timeout=timeout)
                npu_usage = _parse_npu(stdout.read().decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                npu_usage = None

        return {
            "cpuUsage": cpu_usage if cpu_usage is not None else 0.0,
            "memoryUsage": memory_usage if memory_usage is not None else 0.0,
            "npuUsage": npu_usage,
            "collectedAt": now_iso(),
        }
    finally:
        client.close()


def push_file(device: Device, local_path: str, remote_dir: str) -> str:
    """SFTP 推送本地文件到远端目录（目录不存在则逐级创建），返回远端文件路径。"""
    target_dir = (remote_dir or "/tmp").rstrip("/") or "/"
    filename = str(local_path).replace("\\", "/").rsplit("/", 1)[-1]
    remote_path = "%s/%s" % (target_dir, filename)

    client = _client(device)
    try:
        sftp = client.open_sftp()
        try:
            _ensure_remote_dir(sftp, target_dir)
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()
        return remote_path
    finally:
        client.close()


def _ensure_remote_dir(sftp: paramiko.SFTPClient, target_dir: str) -> None:
    """逐级创建远端目录（已存在则忽略）。"""
    if target_dir in ("", "/"):
        return
    parts = [part for part in target_dir.split("/") if part]
    current = "/" if target_dir.startswith("/") else ""
    for part in parts:
        current = "%s%s" % (current, part) if current.endswith("/") else "%s/%s" % (current, part)
        try:
            sftp.stat(current)
        except IOError:
            try:
                sftp.mkdir(current)
            except IOError:
                # 并发/权限竞争，忽略；后续 put 失败会给出真实原因
                pass
        current = current + "/"


def measure_latency(device: Device) -> Tuple[bool, Optional[float], str]:
    """探活并返回往返耗时（毫秒），供前端"检测"按钮展示。"""
    start = time.time()
    online, error = probe(device)
    cost = round((time.time() - start) * 1000.0, 1)
    return (online, cost if online else None, error)
