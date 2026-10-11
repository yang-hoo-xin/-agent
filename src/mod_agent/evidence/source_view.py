"""Small-file source views and the policy retained by one normal product run.

File-sized evidence changes reading granularity, not source freshness or write
approval. Old runs without a policy retain method/window views.
为什么要有它：默认值、绑定和读写常在同一小文件，续接不能悄悄换读取单位。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from .models import DETERMINISTIC_EVIDENCE_AUTHORITY, EvidenceItem

NORMAL_RUN_SMALL_FILE_MAX_BYTES = 8192
POLICY_VERSION = "source_view_policy_v1"


def source_view_policy(small_file_max_bytes: int = 0) -> dict[str, object]:
    if type(small_file_max_bytes) is not int or small_file_max_bytes < 0:
        raise ValueError("SOURCE_VIEW_SMALL_FILE_LIMIT_INVALID")
    return {"schema_version": POLICY_VERSION, "small_file_max_bytes": small_file_max_bytes}


def source_view_policy_from_manifest(manifest: Mapping[str, object]) -> dict[str, object]:
    if "source_view_policy" not in manifest:
        return source_view_policy(0)
    policy = manifest["source_view_policy"]
    if (not isinstance(policy, Mapping) or set(policy) != {"schema_version", "small_file_max_bytes"}
            or policy["schema_version"] != POLICY_VERSION):
        raise ValueError("SOURCE_VIEW_POLICY_INVALID")
    return source_view_policy(policy["small_file_max_bytes"])


def run_small_file_max_bytes(run_root: str | Path) -> int:
    """Restore a saved run's policy; absence is the old explicit zero behavior."""
    path = Path(run_root) / "run_manifest.json"
    if not path.exists():
        return 0
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ValueError("SOURCE_VIEW_MANIFEST_INVALID")
    return int(source_view_policy_from_manifest(manifest)["small_file_max_bytes"])


def is_small_csharp_file(path: Path, source_bytes: bytes, small_file_max_bytes: int) -> bool:
    return (path.suffix.lower() == ".cs" and small_file_max_bytes > 0
            and 0 < len(source_bytes) <= small_file_max_bytes)


def whole_file_source_item(*, workspace_root: Path, selected_path: Path,
                           source_bytes: bytes) -> EvidenceItem:
    """Retain exact decoded text/raw-byte identity, with no invented method facts."""
    root, path = Path(workspace_root).resolve(), Path(selected_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("SOURCE_VIEW_PATH_ESCAPE")
    text = source_bytes.decode("utf-8")
    count = len(text.splitlines())
    if not count:
        raise ValueError("SOURCE_VIEW_EMPTY_FILE")
    relative = path.relative_to(root).as_posix()
    digest = hashlib.sha256(source_bytes).hexdigest()
    evidence_id = "rg_live_" + hashlib.sha256(f"{relative}:{digest}:1:{count}".encode()).hexdigest()[:16]
    return EvidenceItem(evidence_id=evidence_id, source_type="target_source", source_path=relative,
        symbol=None, span={"start_line": 1, "end_line": count}, retrieval_method="rg_live_read",
        score=1.0, claim_supported="Live source file retained completely under the small-file source-view policy.",
        excerpt=text, chunk_id=f"live:{relative}:1:{count}", document_id=f"live:{relative}",
        source_ref=str(path), source_hash=digest, file_hash=digest, doc_hash=digest,
        authority=DETERMINISTIC_EVIDENCE_AUTHORITY)
