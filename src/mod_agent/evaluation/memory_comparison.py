"""Freeze existing TaskMemory stores/settings for a bounded on/off comparison.

Preparation only: no provider selection, transport, business execution, memory
recording, hidden task access or performance claim. Original Artifact identities
and evidence references are preserved without rebasing or rewriting lessons.
"""
from __future__ import annotations

import hashlib
import math
import shutil
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import yaml

from src.core.settings import TaskMemorySettings
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError
from src.mod_agent.evaluation.independent_preparation import digest, file_ref, write_once
from src.mod_agent.model_qualification import read_bound_json

ARMS = ("memory_off", "memory_on")
INVARIANTS = {"task", "model", "tools", "permissions", "budget", "judge", "initial_environment"}


def snapshot_files(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Memory root must be a directory")
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Memory snapshot does not follow symlinks")
        if path.is_file():
            rows.append({"path": path.relative_to(root).as_posix(),
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def _evidence_state(reference, store_root):
    try:
        if reference["kind"] == "json_file":
            return {"available": True, "sha256": file_ref(reference["path"])["sha256"]}
        reader = ArtifactStore(reference.get("store_root", store_root))
        value = reader.read(ArtifactRef(**reference["artifact_ref"]))
        return {"available": True, "sha256": digest(value)}
    except (OSError, ValueError, ArtifactStoreError) as exc:
        # Pre-existing unavailable evidence stays unavailable; details remain in
        # the original TaskMemory revalidation, not in this comparison protocol.
        return {"available": False, "failure_class": type(exc).__name__}


def _memory_dependencies(root):
    store = ArtifactStore(root)
    refs = {}
    expirations = []
    for feature_id in store.list_feature_ids():
        for ref in store.list_feature_artifacts(feature_id):
            if ref.artifact_type != "task_memory":
                continue
            payload = store.read(ref)["data"]
            for evidence in payload["evidence_refs"]:
                refs[digest(evidence)] = evidence
            if payload.get("expires_at") is not None:
                expirations.append({"artifact_ref": asdict(ref), "expires_at": payload["expires_at"]})
    return ([{"reference": refs[key], "state": _evidence_state(refs[key], str(root))}
             for key in sorted(refs)], expirations)


def prepare_memory_pair(*, settings_path, memory_root, invariants, output_root):
    if set(invariants) != INVARIANTS or any(not isinstance(v, dict) or not v for v in invariants.values()):
        raise ValueError("Freeze task/model/tools/permissions/budget/judge/initial_environment identities")
    settings_path, memory_root = Path(settings_path).resolve(strict=True), Path(memory_root).resolve(strict=True)
    output_root = Path(output_root).resolve()
    if output_root.is_relative_to(memory_root) or memory_root.is_relative_to(output_root):
        raise ValueError("Comparison and original memory roots must be disjoint")
    settings_ref = file_ref(settings_path)
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    configuration = TaskMemorySettings(**settings.get("task_memory", {}))
    before = snapshot_files(memory_root)
    dependencies, expirations = _memory_dependencies(memory_root)
    if expirations:
        raise ValueError("Time-expiring lessons need an explicit common evaluation window before freezing")
    output_root.mkdir(parents=True, exist_ok=False)
    arms = []
    for arm in ARMS:
        arm_root = output_root / arm
        arm_root.mkdir()
        copied_memory = arm_root / "memory"
        shutil.copytree(memory_root, copied_memory)
        for name in ("workspace", "cache", "receipts"):
            (arm_root / name).mkdir()
        selected = deepcopy(settings)
        selected["task_memory"] = asdict(TaskMemorySettings(
            enabled=arm == "memory_on", store_root=str(copied_memory),
            max_context_chars=configuration.max_context_chars))
        config_path = arm_root / "settings.yaml"
        with config_path.open("x", encoding="utf-8") as stream:
            yaml.safe_dump(selected, stream, allow_unicode=True, sort_keys=False)
        if snapshot_files(copied_memory) != before:
            raise ValueError("Memory changed while freezing the pair")
        arms.append({"arm": arm, "settings_ref": file_ref(config_path), "memory_root": str(copied_memory),
                     "workspace_root": str(arm_root / "workspace"), "cache_root": str(arm_root / "cache"),
                     "receipts_root": str(arm_root / "receipts")})
    if snapshot_files(memory_root) != before or file_ref(settings_path) != settings_ref:
        raise ValueError("Preparation inputs changed during copying")
    protocol = {"scope": "memory_on_off_preparation_only", "invariants": deepcopy(invariants),
        "invariants_sha256": digest(invariants), "base_settings_ref": settings_ref,
        "shared_settings_sha256": digest({k: v for k, v in settings.items() if k != "task_memory"}),
        "max_context_chars": configuration.max_context_chars, "original_memory_root": str(memory_root),
        "snapshot_files": before, "memory_snapshot_sha256": digest(before), "dependencies": dependencies,
        "arms": arms, "only_semantic_configuration_difference": "task_memory.enabled",
        "physical_directory_differences": "independent memory/workspace/cache/receipts roots",
        "source_authority": "original TaskMemory revalidation remains mandatory",
        "new_lessons_during_pair": "not_allowed_in_frozen_copies",
        "independence": "not_established_by_preparation", "model_calls": 0,
        "success_rate_improvement": "not_demonstrated", "cleanup": "retain both roots and receipts"}
    reference = write_once(output_root / "memory-pair.json", protocol)
    verify_memory_pair(reference)
    return reference


def verify_memory_pair(protocol_ref):
    protocol = read_bound_json(protocol_ref)
    if protocol["invariants_sha256"] != digest(protocol["invariants"]):
        raise ValueError("Comparison invariant drift")
    for arm in protocol["arms"]:
        if snapshot_files(arm["memory_root"]) != protocol["snapshot_files"]:
            raise ValueError("Frozen memory changed; results cannot be paired")
        if file_ref(arm["settings_ref"]["path"]) != arm["settings_ref"]:
            raise ValueError("Comparison settings changed")
        settings = yaml.safe_load(Path(arm["settings_ref"]["path"]).read_text(encoding="utf-8"))
        expected = asdict(TaskMemorySettings(enabled=arm["arm"] == "memory_on",
            store_root=arm["memory_root"], max_context_chars=protocol["max_context_chars"]))
        if settings["task_memory"] != expected or digest({k: v for k, v in settings.items()
                                                        if k != "task_memory"}) != protocol["shared_settings_sha256"]:
            raise ValueError("A non-memory strategy setting changed")
        # A local Artifact reference without store_root resolves against the
        # corresponding frozen copy. Explicit origin-store references stay intact.
        for dependency in protocol["dependencies"]:
            if _evidence_state(dependency["reference"], arm["memory_root"]) != dependency["state"]:
                raise ValueError("Bound memory evidence changed or became unavailable")
    return {"status": "frozen_pair_intact", "protocol_ref": dict(protocol_ref),
            "model_calls": 0, "observed_task_success_rate": None}


def summarize_memory_outcomes(rows):
    """Descriptive first-attempt accounting, never a causal improvement claim.

    Rows use the existing independent per-task result fields. Their referenced
    business/judge evidence must be supplied and validated by the execution owner.
    """
    if any(r["arm"] not in ARMS or type(r["attempt"]) is not int or r["attempt"] < 1 for r in rows):
        raise ValueError("Invalid arm or attempt identity")
    identities = [(r["task_id"], r["arm"], r["attempt"]) for r in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate task attempt")
    tasks = sorted({r["task_id"] for r in rows})

    def metric_total(first, field):
        values = [row.get(field) for row in first.values()]
        types = (int, float) if field == "native_duration_ms" else (int,)
        return (sum(values) if len(first) == len(tasks)
                and all(type(value) in types and value >= 0 and math.isfinite(value) for value in values) else None)

    result = {"distinct_task_count": len(tasks), "attempt_count": len(rows), "by_arm": {},
              "success_rate_improvement": "not_demonstrated", "evidence_validation": "execution_owner_required"}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        first = {r["task_id"]: r for r in selected if r["attempt"] == 1}
        known = [r for r in first.values() if type(r["verdict"]["task_success"]) is bool]
        successes = sum(r["verdict"]["task_success"] is True for r in known)
        result["by_arm"][arm] = {"first_attempt_task_count": len(first), "resolved_task_count": len(known),
            "missing_or_unknown_task_count": len(tasks) - len(known), "successes": successes,
            "task_success_rate": successes / len(tasks) if tasks and len(known) == len(tasks) else None,
            "repeat_attempt_count": sum(r["attempt"] > 1 for r in selected),
            **{field: metric_total(first, field)
               for field in ("native_model_calls", "human_technical_interventions", "requirement_clarifications", "approvals",
                             "repeated_investigations", "incorrect_revisions", "native_duration_ms",
                             "native_input_tokens", "native_output_tokens")}}
    return result
