"""算法脚本执行器：subprocess 编排 + JSONL 进度协议。

协议：脚本 stdout 每行一个 JSON 对象 {"stage", "percent", "message"}；
执行器逐行解析并回调 on_progress，stderr 留最后 50 行用于失败诊断。

取消/超时：
* 独立 watcher 线程监听 cancel_event —— 脚本长时间没有 stdout 输出时也能取消；
* POSIX 下按进程组发送信号（start_new_session），避免 ATC 等外部工具变孤儿进程；
* SIGTERM 后等待 grace 秒才强杀，最后兜底 close 管道，杜绝进程/句柄泄漏。

返回 (exit_code, stderr_tail)：
    0 成功；-1 被取消；-2 超时；其他为脚本真实退出码；127 无法启动脚本。
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .config import get

ProgressCallback = Callable[[str, int, str], None]

EXIT_CANCELED = -1
EXIT_TIMEOUT = -2
EXIT_SPAWN_FAILED = 127


def _terminate(proc: subprocess.Popen, grace: float) -> None:
    """先温和终止，超时后强杀；整个进程组一起处理。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:  # noqa: BLE001 —— 进程可能刚好退出
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=max(grace, 0.1))
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass


def _parse_line(line: str) -> Optional[Tuple[str, int, str]]:
    text = (line or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    stage = str(obj.get("stage", "") or "")
    if not stage:
        return None
    try:
        percent = int(float(obj.get("percent", 0)))
    except (TypeError, ValueError):
        percent = 0
    message = str(obj.get("message", "") or "")
    return (stage, max(0, min(100, percent)), message)


def run_script(
    script: Path,
    workdir: Path,
    on_progress: ProgressCallback,
    cancel_event: Optional[threading.Event] = None,
    timeout: Optional[float] = None,
    grace_seconds: Optional[float] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str]:
    """运行算法脚本，返回 (退出码, stderr 尾部)。

    参数：
        script       算法脚本路径（用当前解释器 sys.executable 拉起）
        workdir      任务工作目录，同时作为脚本 cwd 和第一个参数
        on_progress  (stage, percent, message) 回调
        cancel_event 置位即取消任务
        timeout      整体超时（秒），None 表示不限制
    """
    script = Path(script)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if not script.exists():
        return (EXIT_SPAWN_FAILED, "算法脚本不存在: %s" % script)

    grace = float(grace_seconds if grace_seconds is not None
                  else (get("scheduler.cancel_grace_seconds", 5) or 5))

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    if extra_env:
        env.update(extra_env)

    popen_kwargs = dict(
        cwd=str(workdir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen([sys.executable, str(script), str(workdir)], **popen_kwargs)
    except OSError as exc:
        return (EXIT_SPAWN_FAILED, "无法启动算法脚本: %s" % exc)

    stderr_tail: deque = deque(maxlen=50)
    stdout_queue: "queue.Queue[Optional[str]]" = queue.Queue()
    stop_watcher = threading.Event()
    canceled = threading.Event()
    timed_out = threading.Event()

    def _drain_stderr() -> None:
        try:
            for line in proc.stderr:  # type: ignore[union-attr]
                stderr_tail.append(line.rstrip())
        except Exception:  # noqa: BLE001 —— 管道被关闭
            pass

    def _pump_stdout() -> None:
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                stdout_queue.put(line)
        except Exception:  # noqa: BLE001
            pass
        finally:
            stdout_queue.put(None)

    def _watcher() -> None:
        deadline = (time.time() + timeout) if timeout else None
        while not stop_watcher.wait(0.2):
            if cancel_event is not None and cancel_event.is_set():
                canceled.set()
                _terminate(proc, grace)
                return
            if deadline is not None and time.time() >= deadline:
                timed_out.set()
                stderr_tail.append("算法脚本执行超时（%ss），已终止" % timeout)
                _terminate(proc, grace)
                return

    stderr_thread = threading.Thread(target=_drain_stderr, name="exec-stderr", daemon=True)
    stdout_thread = threading.Thread(target=_pump_stdout, name="exec-stdout", daemon=True)
    watcher_thread = threading.Thread(target=_watcher, name="exec-watch", daemon=True)
    stderr_thread.start()
    stdout_thread.start()
    watcher_thread.start()

    try:
        while True:
            try:
                line = stdout_queue.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None and not stdout_thread.is_alive():
                    break
                continue
            if line is None:
                break
            parsed = _parse_line(line)
            if parsed is None:
                continue
            try:
                on_progress(*parsed)
            except Exception:  # noqa: BLE001 —— 回调（落库）异常不能中断脚本
                pass

        try:
            proc.wait(timeout=grace + 5)
        except Exception:  # noqa: BLE001
            _terminate(proc, grace)
    finally:
        stop_watcher.set()
        if proc.poll() is None:
            _terminate(proc, grace)
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        watcher_thread.join(timeout=2)

    tail = "\n".join(stderr_tail)
    if canceled.is_set():
        return (EXIT_CANCELED, tail or "任务已取消")
    if timed_out.is_set():
        return (EXIT_TIMEOUT, tail or "算法脚本执行超时")
    return (int(proc.returncode if proc.returncode is not None else -3), tail)
