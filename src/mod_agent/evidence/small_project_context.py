"""Bounded current-source context after empty lexical searches, without coverage authority."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from src.core.trace.execution_trace import trace_operation
from src.mod_agent.upstream_trace import (
    material_identities,
    observe_local_tool_bodies,
    payload_sha256,
    update_observation,
)

from .source_view import whole_file_source_item


def context_policy(*, enabled=False):
    return {"schema_version": "small_project_source_context_v1", "enabled": enabled,
            "max_files": 4, "max_total_bytes": 8192, "max_entries": 256}


def validate_context_policy(value):
    if (not isinstance(value, dict) or type(value.get("enabled")) is not bool
            or value != context_policy(enabled=value["enabled"])
            or any(type(value[key]) is not int for key in ("max_files", "max_total_bytes", "max_entries"))):
        raise ValueError("SMALL_PROJECT_CONTEXT_POLICY_INVALID")
    return dict(value)


def run_context_policy(workspace_root):
    manifest = Path(workspace_root) / "run_manifest.json"
    if not manifest.is_file():
        return context_policy()
    value = json.loads(manifest.read_text(encoding="utf-8"))
    return validate_context_policy(value.get("small_project_context_policy", context_policy()))


def _plain(path, *, directory):
    status = path.lstat()
    if (stat.S_ISLNK(status.st_mode)
            or getattr(status, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not (stat.S_ISDIR(status.st_mode) if directory else stat.S_ISREG(status.st_mode))):
        raise ValueError("source_entry_not_plain")
    return status


def collect_small_project_context(*, workspace_root, search_root, max_items, small_file_max_bytes, policy):
    """Keep lexical misses intact; separately retain the complete bounded source set.

    为什么要有它：尚未新增的名字无法命中空骨架，当前源码可供模型判断但不能自动证明需求已满足。
    """
    inputs = {"search_root": str(search_root), "max_items": max_items,
              "small_file_max_bytes": small_file_max_bytes, "policy": policy}
    with trace_operation("evidence.source_context", kind="tool", attributes={
            "input_payload_sha256": payload_sha256(inputs)}) as span:
        with observe_local_tool_bodies(span, inputs) as record:
            items, audit = _collect(workspace_root=workspace_root, search_root=search_root,
                max_items=max_items, small_file_max_bytes=small_file_max_bytes, policy=policy)
            record({"audit": audit, "items": [item.to_dict() for item in items]})
        update_observation(span, produced_materials=material_identities(items),
                           evidence_item_count=len(items), retrieval_status=audit["status"])
        return items, audit


def _collect(*, workspace_root, search_root, max_items, small_file_max_bytes, policy):
    audit = {"origin": "bounded_small_project_context", "policy": dict(policy),
             "status": "unavailable", "enumerated_entries": 0, "bytes_read": 0,
             "evidence_ids": [], "lexical_match_claimed": False, "semantic_support_claimed": False}
    try:
        workspace = Path(workspace_root).resolve(strict=True)
        root = workspace / search_root
        relative = root.relative_to(workspace)
        if ".." in relative.parts:
            raise ValueError("source_scope_rejected")
        cursor = workspace
        _plain(cursor, directory=True)
        for part in relative.parts:
            cursor /= part
            _plain(cursor, directory=True)
        files, pending, total = [], [root], 0
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    audit["enumerated_entries"] += 1
                    if audit["enumerated_entries"] >= policy["max_entries"]:
                        raise ValueError("entry_limit_reached")
                    if entry.name.lower() in {"bin", "obj", ".git"}:
                        continue
                    path = Path(entry.path)
                    status = _plain(path, directory=entry.is_dir(follow_symlinks=False))
                    if stat.S_ISDIR(status.st_mode):
                        pending.append(path)
                    elif path.suffix.lower() == ".cs":
                        files.append(path)
                        total += status.st_size
                        if len(files) > min(max_items, policy["max_files"]):
                            raise ValueError("file_limit_exceeded")
                        if not 0 < status.st_size <= small_file_max_bytes:
                            raise ValueError("file_size_limit_exceeded")
                        if total > policy["max_total_bytes"]:
                            raise ValueError("total_byte_limit_exceeded")
        items = []
        for path in sorted(files):
            if path.resolve(strict=True) != path:
                raise ValueError("source_entry_changed")
            expected = _plain(path, directory=False)
            remaining = policy["max_total_bytes"] - audit["bytes_read"]
            if not 0 < expected.st_size <= min(small_file_max_bytes, remaining):
                raise ValueError("read_byte_limit_exceeded")
            with path.open("rb") as stream:
                data = stream.read(expected.st_size)
                after = os.fstat(stream.fileno())
            audit["bytes_read"] += len(data)
            if (len(data) != expected.st_size or after.st_size != expected.st_size
                    or after.st_mtime_ns != expected.st_mtime_ns):
                raise ValueError("source_entry_changed")
            items.append(whole_file_source_item(workspace_root=workspace, selected_path=path, source_bytes=data))
        audit.update(status="observed" if items else "no_source_files",
                     file_count=len(files), evidence_ids=[item.evidence_id for item in items])
        return tuple(items), audit
    except (OSError, ValueError) as error:
        audit.update(status="unavailable", reason=str(error))
        return (), audit
