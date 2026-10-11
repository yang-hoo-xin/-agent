"""Process-safe serialization of existing checkpoint admission and report commit.

The OS lock grants no execution authority and is released on process exit.
Durable ResumeReports remain the original consumption record.
为什么要有它：两个调用不能同时通过旧preflight后各自提交accepted report；提交失败仍沿用原恢复语义。
"""
from __future__ import annotations

import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def checkpoint_resume_lock(store_root, checkpoint_ref):
    key = hashlib.sha256((checkpoint_ref.feature_id + "\0" + checkpoint_ref.artifact_hash).encode()).hexdigest()
    directory = Path(store_root) / "checkpoint_resume_locks"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (key + ".lock")).open("a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + 10
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("CHECKPOINT_RESUME_LOCK_TIMEOUT") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
