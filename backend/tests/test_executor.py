import threading
from pathlib import Path

from app.executor import run_script

PROGRESS_SCRIPT = """
import json, sys, time
from pathlib import Path
workdir = Path(sys.argv[1])
for p in (10, 60, 100):
    print(json.dumps({"stage": "demo", "percent": p, "message": "step-%d" % p}), flush=True)
    time.sleep(0.05)
(workdir / "out.txt").write_text("done")
"""

NOISE_SCRIPT = """
import sys
print("这一行不是 JSON，应被忽略")
print("")
print('{"stage": "demo", "percent": "bad", "message": "x"}')
print('{"nosstage": 1}')
"""

SLOW_SCRIPT = """
import time
while True:
    time.sleep(0.2)
"""

STDERR_SCRIPT = """
import sys
print('boom', file=sys.stderr)
sys.exit(3)
"""

UTF8_SCRIPT = """
import json
print(json.dumps({"stage": "demo", "percent": 50, "message": "中文进度 ✓"}, ensure_ascii=False))
"""


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_progress_and_exit_code(tmp_path):
    script = _write(tmp_path / "fake_algo.py", PROGRESS_SCRIPT)
    progress = []
    code, tail = run_script(script, tmp_path, lambda s, p, m: progress.append((s, p, m)))
    assert code == 0, tail
    assert progress == [("demo", 10, "step-10"),
                        ("demo", 60, "step-60"),
                        ("demo", 100, "step-100")]
    assert (tmp_path / "out.txt").read_text() == "done"


def test_malformed_lines_are_ignored(tmp_path):
    script = _write(tmp_path / "noise.py", NOISE_SCRIPT)
    progress = []
    code, _ = run_script(script, tmp_path, lambda s, p, m: progress.append((s, p, m)))
    assert code == 0
    assert progress == [("demo", 0, "x")]          # percent 非法 -> 归零，缺 stage -> 丢弃


def test_utf8_messages(tmp_path):
    script = _write(tmp_path / "utf8.py", UTF8_SCRIPT)
    progress = []
    code, tail = run_script(script, tmp_path, lambda s, p, m: progress.append((s, p, m)))
    assert code == 0, tail
    assert progress == [("demo", 50, "中文进度 ✓")]


def test_failure_captures_stderr(tmp_path):
    script = _write(tmp_path / "bad.py", STDERR_SCRIPT)
    code, tail = run_script(script, tmp_path, lambda *args: None)
    assert code == 3
    assert "boom" in tail


def test_cancel_kills_process(tmp_path):
    script = _write(tmp_path / "slow.py", SLOW_SCRIPT)
    cancel = threading.Event()
    cancel.set()                                   # 跑之前就取消：没有 stdout 也必须能响应
    code, tail = run_script(script, tmp_path, lambda *args: None, cancel_event=cancel)
    assert code == -1
    assert "取消" in tail


def test_cancel_during_run(tmp_path):
    script = _write(tmp_path / "slow2.py", SLOW_SCRIPT)
    cancel = threading.Event()
    timer = threading.Timer(0.5, cancel.set)
    timer.start()
    try:
        code, _ = run_script(script, tmp_path, lambda *args: None, cancel_event=cancel)
    finally:
        timer.cancel()
    assert code == -1


def test_timeout_kills_process(tmp_path):
    script = _write(tmp_path / "slow3.py", SLOW_SCRIPT)
    code, tail = run_script(script, tmp_path, lambda *args: None, timeout=0.5)
    assert code == -2
    assert "超时" in tail


def test_missing_script(tmp_path):
    code, tail = run_script(tmp_path / "nope.py", tmp_path, lambda *args: None)
    assert code == 127
    assert "不存在" in tail
