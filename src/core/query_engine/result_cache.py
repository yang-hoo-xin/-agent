"""Exact-input JSON model-result cache; incomplete calls have no publication path."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class QueryResultCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def get(self, binding):
        path = self.directory / (fingerprint(binding) + ".json")
        try:
            record = json.loads(path.read_bytes())
            if (record["version"] == "query_model_cache_v1" and record["binding"] == binding
                    and record["value_sha256"] == fingerprint(record["value"])):
                return record["value"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, binding, value):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / (fingerprint(binding) + ".json")
        temporary = self.directory / ("." + uuid4().hex + ".tmp")
        record = {"version": "query_model_cache_v1", "binding": binding, "value": value, "value_sha256": fingerprint(value)}
        # 为什么要有它：完整有效结果才原子发布，取消、超时和部分流输出不能占据命中键。
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(canonical(record))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
