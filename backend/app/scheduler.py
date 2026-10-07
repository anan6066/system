"""进程内任务调度器：线程池并发=1，保证算法/推送串行执行。"""
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict

from .config import get


class Scheduler:
    """串行任务调度器。

    * new_cancel_event() 每次返回全新 Event（同一任务的两个阶段互不串扰）；
    * 任务被取消后 Event 会一直置位，直到该阶段结束由 finish 清理；
    * wait_idle() 供测试与关闭流程等待队列排空。
    """

    def __init__(self, max_workers: int = 1):
        self.max_workers = max(1, int(max_workers))
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers,
                                        thread_name_prefix="quant-job")
        self._lock = threading.Lock()
        self._cancel_events: Dict[str, threading.Event] = {}
        self._active = 0
        self._idle = threading.Event()
        self._idle.set()

    # ---- 取消 ---------------------------------------------------------- #
    def new_cancel_event(self, job_id: str) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._cancel_events[job_id] = event
        return event

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def is_canceled(self, job_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(job_id)
        return bool(event is not None and event.is_set())

    def release(self, job_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(job_id, None)

    # ---- 调度 ---------------------------------------------------------- #
    def submit(self, fn: Callable[[], None]) -> Future:
        with self._lock:
            self._active += 1
            self._idle.clear()
        try:
            return self._pool.submit(self._run, fn)
        except RuntimeError:
            self._release_slot()
            raise

    def _run(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        finally:
            self._release_slot()

    def _release_slot(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            if self._active == 0:
                self._idle.set()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"active": self._active, "workers": self.max_workers}

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """等待队列排空（测试与进程退出用）。"""
        return self._idle.wait(timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)


def _max_workers() -> int:
    try:
        return int(get("scheduler.max_concurrent_jobs", 1) or 1)
    except (TypeError, ValueError):
        return 1


scheduler = Scheduler(max_workers=_max_workers())


def get_scheduler() -> Scheduler:
    return scheduler
