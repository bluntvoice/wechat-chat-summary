"""跨桥接子进程的非阻塞任务锁；进程退出后由操作系统释放。"""
from contextlib import contextmanager
from hashlib import sha256
import os

from .desktop_config import ensure_desktop_data_dir


@contextmanager
def report_lock(key: str):
    folder = ensure_desktop_data_dir() / "jobs" / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (sha256(key.encode("utf-8")).hexdigest() + ".lock")
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("该群聊日期已有任务正在执行，请等待完成后重试。") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
