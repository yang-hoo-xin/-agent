"""DSH task-experience adapter. Records bound facts; never trains or executes a Mod."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

from scripts.dsh_run_request import inspect_run
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.planning.task_memory import TaskMemory, memory_model_view
from src.observability.patch_execution_index import project_patch_executions


def _absolute(value: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute() or value.startswith(("\\\\", "//")):
        raise ValueError("MEMORY_LOCAL_ABSOLUTE_PATH_REQUIRED")
    path = Path(value).resolve()
    for parent in (path, *path.parents):
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("MEMORY_REPARSE_PATH_REJECTED")
    return path


def _profile(path: str) -> dict:
    raw = _absolute(path).read_text(encoding="utf-8")
    if len(raw) > 32768:
        raise ValueError("MEMORY_PROFILE_TOO_LARGE")
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) - {"artifactStoreRoot", "featureId", "runId", "currentContext"}
            or not all(isinstance(value.get(key), str) and value[key] for key in ("artifactStoreRoot", "featureId", "runId"))):
        raise ValueError("MEMORY_PROFILE_INVALID")
    value["artifactStoreRoot"] = str(_absolute(value["artifactStoreRoot"]))
    context = value.get("currentContext", {})
    if not isinstance(context, dict) or any(not isinstance(key, str) or type(item) not in (str, int, float, bool, type(None))
                                           for key, item in context.items()):
        raise ValueError("MEMORY_CURRENT_CONTEXT_INVALID")
    return value


def _journal(ref: dict, source_store: ArtifactStore, *, parent_run_id: str | None = None) -> dict:
    if set(ref) != {"path", "sha256"}:
        raise ValueError("MEMORY_JOURNAL_REFERENCE_INVALID")
    path = _absolute(ref["path"])
    if not path.is_relative_to((source_store.root / "cr").resolve()):
        raise ValueError("MEMORY_JOURNAL_OUTSIDE_SOURCE_STORE")
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("MEMORY_JOURNAL_HASH_MISMATCH")
    value = json.loads(raw)
    if value.get("receipt_version") != "patch_continuation_attempt_v1":
        raise ValueError("MEMORY_JOURNAL_TYPE_INVALID")
    if parent_run_id is not None and value.get("parent_product_run_id") != parent_run_id:
        raise ValueError("MEMORY_JOURNAL_PARENT_MISMATCH")
    return value


def run_memory(*, memory_root: str, action: str, investigation_config: str | None = None,
               execution_config: str | None = None, run_id: str | None = None, query: str = "") -> dict:
    base = {"entry": "dsh-task-memory", "authority": "planning_only", "model_calls_performed": 0,
            "product_source_writes_performed": False, "artifact_writes_performed": False, "read_only": True}
    if action not in ("remember", "query") or bool(investigation_config) == bool(execution_config):
        raise ValueError("MEMORY_ACTION_OR_CONFIGURATION_INVALID")
    memory = TaskMemory(ArtifactStore(_absolute(memory_root)))
    if action == "query":
        if execution_config or not query.strip() or len(query.encode("utf-8")) > 32768:
            raise ValueError("MEMORY_QUERY_INVALID")
        selected = _profile(investigation_config)
        # Local evidence joins can be larger than the separately bounded model view.
        retrieved = memory.retrieve(query, selected.get("currentContext", {}), max_chars=16000)
        return {**base, "status": "queried", "retrieved_experience": retrieved,
                "model_view": memory_model_view(retrieved, max_chars=3000),
                "notice": "历史执行事实供规划参考；不是已验证根因、修法或模型训练结果。"}
    parent_id = None
    if execution_config:
        if not run_id:
            raise ValueError("MEMORY_PUBLIC_RUN_REQUIRED")
        original = inspect_run(execution_config=execution_config, run_id=run_id)
        if original["status"] != "recorded" or not original.get("result"):
            return {**base, "status": "not_available", "reason": "No original product result."}
        source_store = ArtifactStore(Path(original["run_root"]) / "a")
        recorded = original["result"].get("patch_execution_receipts", [])
        if not isinstance(recorded, list):
            raise ValueError("MEMORY_JOURNAL_REFERENCES_INVALID")
        refs = [{key: row[key] for key in ("path", "sha256")} for row in recorded]
        parent_id = run_id
    else:
        selected = _profile(investigation_config)
        source_store = ArtifactStore(selected["artifactStoreRoot"])
        result = project_patch_executions(source_store.root, feature_id=selected["featureId"], run_id=selected["runId"])
        if len(result["attempts"]) != 1:
            raise ValueError("MEMORY_RUN_NOT_UNIQUE_OR_MISSING")
        refs = [result["attempts"][0]["journal_ref"]]
    if not isinstance(refs, list):
        raise ValueError("MEMORY_JOURNAL_REFERENCES_INVALID")
    results = []
    for ref in refs:
        journal = _journal(ref, source_store, parent_run_id=parent_id)
        if journal.get("status") not in ("terminal", "continuation_failed", "awaiting_approval"):
            results.append({"run_id": journal.get("run_id"), "status": "not_terminal"})
            continue
        # Pre-Patch failures may have no original worker/request identities.
        if not journal.get("factory_receipt", {}).get("patch_agent_loop", {}).get("model"):
            results.append({"run_id": journal.get("run_id"), "status": "no_worker_evidence"})
            continue
        lesson_id = memory.execution_lesson_id(journal["run_id"], source_store=source_store)
        before = memory.current(lesson_id)
        reference = memory.record_execution(ref, source_store=source_store)
        changed = before != reference
        base["artifact_writes_performed"] |= changed
        results.append({"run_id": journal["run_id"], "status": "recorded" if changed else "reused",
                        "lesson_id": lesson_id, "artifact_ref": asdict(reference)})
    return {**base, "status": "recorded" if base["artifact_writes_performed"] else "no_new_revision",
            "read_only": not base["artifact_writes_performed"], "records": results,
            "notice": "按原记录生成事实型经验；没有推断正确修法、改变策略或训练模型。"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--memory-root", required=True)
    parser.add_argument("--action", choices=("remember", "query"), required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--investigation-config")
    source.add_argument("--execution-config")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.buffer.read(32769).decode("utf-8") if args.action == "query" else ""
        result = run_memory(memory_root=args.memory_root, action=args.action,
                            investigation_config=args.investigation_config,
                            execution_config=args.execution_config, run_id=args.run_id, query=text)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        result = {"entry": "dsh-task-memory", "authority": "planning_only", "status": "blocked", "reason": str(error),
                  "model_calls_performed": 0, "product_source_writes_performed": False,
                  "read_only": args.action == "query", "artifact_writes_performed": False if args.action == "query" else None}
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
