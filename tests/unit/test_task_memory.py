"""Task experience remains source-bound, versioned, and planning-only."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError
from src.mod_agent.planning.task_memory import TaskMemory, memory_model_view


def _json_ref(path: Path, value: object) -> dict[str, str]:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _record(memory: TaskMemory, path: Path, *, lesson_id: str = "budget-example",
            status: str = "budget_exhausted", scope: str = "patch-observation-budget",
            previous=None, **overrides):
    document = {
        "request": "Investigate First Shot observation budget", "status": status,
        "calls": 1, "root_cause": "unknown", "raw_request_path": str(path.resolve()),
    }
    args = {
        "lesson_id": lesson_id,
        "evidence_refs": [{"evidence_id": "run", "kind": "json_file", **_json_ref(path, document)}],
        "request": {"evidence_id": "run", "locator": ["request"]},
        "facts": [{"scope": scope, "key": "status", "role": "failure",
                   "evidence_id": "run", "locator": ["status"]},
                  {"scope": scope, "key": "calls", "role": "observation",
                   "evidence_id": "run", "locator": ["calls"]}],
        "outcome": {"evidence_id": "run", "locator": ["status"]},
        "applicability": {"target_mod": "ExampleMod", "model": "test-model"},
        "unknowns": ["Root cause is unknown."],
        "invalidation_conditions": ["Recheck source hashes, source APIs and bindings."],
        "previous_revision_ref": previous,
    }
    args.update(overrides)
    return memory.record(**args)


@pytest.fixture
def context():
    return {"target_mod": "ExampleMod", "model": "test-model"}


def test_restart_retrieves_original_bound_facts_and_full_refs(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = _record(memory, tmp_path / "run.json")
    result = TaskMemory(ArtifactStore(tmp_path / "memory")).retrieve("First Shot budget", context)
    lesson = result["relevant_lessons"][0]
    assert lesson["artifact_ref"] == asdict(ref)
    assert lesson["facts"][0]["value"] == "budget_exhausted"
    assert lesson["request"]["value"] == "Investigate First Shot observation budget"
    assert result["failed_patterns"][0]["facts"][0]["key"] == "status"
    assert result["authority"] == "planning_only"
    assert result["reusable_patterns"] == []


def test_revisions_preserve_history_and_require_current_ref(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    first = _record(memory, tmp_path / "old.json")
    with pytest.raises(ValueError, match="exact current"):
        _record(memory, tmp_path / "new.json", status="finished")
    second = _record(memory, tmp_path / "new.json", status="finished", previous=first)
    assert memory.history("budget-example") == [first, second]
    assert memory.store.read(first)["data"]["facts"][0]["value"] == "budget_exhausted"
    assert memory.store.read(second)["data"]["previous_revision_ref"] == asdict(first)
    assert memory.retrieve("First Shot", context)["relevant_lessons"][0]["revision"] == 2
    with pytest.raises(ValueError, match="exact current"):
        _record(memory, tmp_path / "third.json", previous=first)


def test_exact_locators_reject_case_guess_and_supplied_values(tmp_path):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    with pytest.raises(ValueError, match="exact locator"):
        _record(memory, tmp_path / "case.json", request={"evidence_id": "run", "locator": ["Request"]})
    with pytest.raises(ValueError, match="not supplied"):
        _record(memory, tmp_path / "value.json", request={
            "evidence_id": "run", "locator": ["request"], "value": "invented root cause"})
    assert memory.store.list_feature_ids() == []


@pytest.mark.parametrize("context_update", [{"model": "different"}, {"Model": "test-model"}])
def test_mismatched_or_missing_exact_context_is_unavailable(tmp_path, context, context_update):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = _record(memory, tmp_path / "run.json")
    supplied = {"target_mod": context["target_mod"], **context_update}
    result = memory.retrieve("First Shot", supplied)
    assert result["relevant_lessons"] == []
    assert result["failed_patterns"] == []
    assert result["unavailable_evidence"][0]["artifact_ref"] == asdict(ref)


def test_changed_source_hash_and_expiry_preserve_history_without_hints(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    path = tmp_path / "run.json"
    first = _record(memory, path)
    path.write_text('{"status":"success"}', encoding="utf-8")
    result = memory.retrieve("First Shot", context)
    assert not result["relevant_lessons"]
    assert "hash changed" in result["unavailable_evidence"][0]["reasons"][0]
    _record(memory, tmp_path / "expired.json", lesson_id="old-experience",
            expires_at="2000-01-01T00:00:00+00:00")
    assert any("experience expired" in item["reasons"]
               for item in memory.retrieve("First Shot", context)["unavailable_evidence"])
    assert memory.history("budget-example") == [first]


def test_explicit_conflicting_values_exclude_both_sources_without_merge(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    first = _record(memory, tmp_path / "one.json", lesson_id="one")
    second = _record(memory, tmp_path / "two.json", lesson_id="two", status="finished")
    result = memory.retrieve("First Shot", context)
    assert not result["relevant_lessons"]
    conflict = result["unavailable_evidence"][0]
    assert conflict["reason"] == "conflicting_scope_key_values"
    assert conflict["scope"] == "patch-observation-budget"
    assert {item["artifact_hash"] for item in conflict["artifact_refs"]} == {
        first.artifact_hash, second.artifact_hash}
    assert memory.history("one") == [first]
    assert memory.history("two") == [second]


def test_distinct_scopes_or_matching_values_are_not_merged(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    _record(memory, tmp_path / "one.json", lesson_id="one")
    _record(memory, tmp_path / "two.json", lesson_id="two")
    _record(memory, tmp_path / "three.json", lesson_id="three", status="finished", scope="other-run")
    result = memory.retrieve("First Shot", context, max_chars=15000)
    assert len(result["relevant_lessons"]) == 3
    assert not result["unavailable_evidence"]


def test_context_budget_drops_whole_fields_and_preserves_full_reference(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = _record(memory, tmp_path / "run.json")
    for budget in (256, 1000, 2200, 6000):
        result = memory.retrieve("First Shot", context, max_chars=budget)
        assert len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= budget
        for lesson in result["relevant_lessons"]:
            assert lesson["artifact_ref"] == asdict(ref)
            assert all(fact["value"] in ("budget_exhausted", 1) for fact in lesson["facts"])
    with pytest.raises(ValueError, match="at least 256"):
        memory.retrieve("First Shot", context, max_chars=10)


def test_model_view_keeps_facts_hashes_and_omits_request_and_absolute_paths(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = _record(memory, tmp_path / "run.json")
    retrieved = memory.retrieve("First Shot", context)
    lesson = retrieved["relevant_lessons"][0]
    lesson["facts"].append({"scope": "io", "key": "path", "value": r"C:\private\code.cs",
                            "role": "observation"})
    lesson["facts"].append({"scope": "io", "key": "embedded", "value": r"source=C:\private\code.cs",
                            "role": "observation"})
    view = memory_model_view(retrieved)
    assert view["lessons"][0]["artifact_hash"] == ref.artifact_hash
    text = json.dumps(view, ensure_ascii=False)
    assert "Investigate First Shot observation budget" not in text
    assert "private" not in text
    assert str(tmp_path) not in text
    assert view["lessons"][0]["facts"][0]["value"] == "budget_exhausted"
    assert view["omitted_count"] == 2
    assert len(json.dumps(memory_model_view(retrieved, max_chars=256), separators=(",", ":"))) <= 256


def test_registry_rejects_authority_escalation_in_direct_write(tmp_path):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = _record(memory, tmp_path / "run.json")
    payload = copy.deepcopy(memory.store.read(ref)["data"])
    payload["authority"] = "write_allowed"
    with pytest.raises(ArtifactStoreError, match="planning-only"):
        memory.store.write(feature_id=ref.feature_id, artifact_type="task_memory", payload=payload)


def test_directly_stored_unbound_fact_is_excluded_after_source_revalidation(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = _record(memory, tmp_path / "run.json")
    payload = copy.deepcopy(memory.store.read(ref)["data"])
    payload["facts"][0]["value"] = "fabricated successful repair"
    memory.store.write(feature_id=ref.feature_id, artifact_type="task_memory", payload=payload)
    result = memory.retrieve("First Shot", context)
    assert not result["relevant_lessons"]
    assert "stored selection does not match bound evidence" in result["unavailable_evidence"][0]["reasons"]


def _execution_journal(tmp_path: Path, source_store: ArtifactStore):
    feature = source_store.write(feature_id="source_task", artifact_type="feature_spec", payload={
        "node_name": "draft_feature_spec", "stage": "feature_spec", "message": "source fixture",
        "feature_id": "source_task", "user_request": "Investigate First Shot timeout",
        "target_behavior": "Investigate First Shot timeout", "target_mod": "ExampleMod",
        "risk_level": "medium", "non_goals": [], "acceptance_criteria": [],
        "evidence_requirements": [], "runtime_verification_plan": [], "blocked": False, "blockers": [],
    })
    request_ref = _json_ref(tmp_path / "request.json", {"messages": [{"content": "untrusted model input"}]})
    journal = {
        "run_id": "execution-one", "selected_artifacts": {"feature_spec": asdict(feature)},
        "status": "continuation_failed", "model_call_count": 1, "max_model_calls": 5,
        "proposal_admitted": False,
        "factory_receipt": {"patch_agent_loop": {
            "model": "test-model", "provider": "test-provider", "total_observation_bytes": 64,
            "policy": {"max_observation_bytes": 32},
            "termination": {"code": "BUDGET_EXHAUSTED", "status": "blocked"},
        }, "worker_turns": [{"status": "responded", "error_type": None,
                             "request_ref": request_ref}]},
    }
    return journal, _json_ref(tmp_path / "journal.json", journal)


def test_execution_import_is_idempotent_and_does_not_require_a_response(tmp_path, context):
    source_store = ArtifactStore(tmp_path / "source")
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    _, journal_ref = _execution_journal(tmp_path, source_store)
    first = memory.record_execution(journal_ref, source_store=source_store)
    second = memory.record_execution(journal_ref, source_store=source_store)
    assert first == second
    assert memory.history(memory.execution_lesson_id("execution-one", source_store=source_store)) == [first]
    result = memory.retrieve("First Shot timeout", context, max_chars=12000)
    lesson = result["relevant_lessons"][0]
    assert lesson["outcome"]["value"] == "continuation_failed"
    assert lesson["request"]["value"] == "Investigate First Shot timeout"
    assert any(fact["key"] == "termination.code" for fact in lesson["facts"])
    assert not result["reusable_patterns"]


def test_same_run_id_in_independent_stores_remains_independently_retrievable(tmp_path, context):
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    imported = []
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        source = ArtifactStore(folder / "store")
        _, journal_ref = _execution_journal(folder, source)
        ref = memory.record_execution(journal_ref, source_store=source)
        imported.append(ref)
        assert memory.record_execution(journal_ref, source_store=source) == ref
    result = memory.retrieve("First Shot timeout", context, max_chars=24000)
    lessons = result["relevant_lessons"]
    assert len(lessons) == 2
    assert len({item["lesson_id"] for item in lessons}) == 2
    assert {item["artifact_ref"]["artifact_hash"] for item in lessons} == {ref.artifact_hash for ref in imported}
    assert all(len(memory.history(item["lesson_id"])) == 1 for item in lessons)


def test_new_source_identity_preserves_legacy_lesson_bytes_and_references(tmp_path, context, monkeypatch):
    source = ArtifactStore(tmp_path / "source")
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    _, journal_ref = _execution_journal(tmp_path, source)
    legacy_id = "execution:execution-one"
    with monkeypatch.context() as patch:
        patch.setattr(memory, "execution_lesson_id", lambda *args, **kwargs: legacy_id)
        legacy = memory.record_execution(journal_ref, source_store=source)
    before = {path: path.read_bytes() for path in Path(legacy.path).parent.rglob("*") if path.is_file()}
    scoped = memory.record_execution(journal_ref, source_store=source)
    assert scoped.feature_id != legacy.feature_id
    assert memory.current(legacy_id) == legacy
    assert memory.history(legacy_id) == [legacy]
    assert memory.record_execution(journal_ref, source_store=source) == scoped
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert {item["lesson_id"] for item in memory.retrieve("First Shot", context, max_chars=24000)["relevant_lessons"]} == {
        legacy_id, memory.execution_lesson_id("execution-one", source_store=source)}


def test_model_upstream_explanation_is_not_promoted_to_experience_fact(tmp_path, context):
    source_store = ArtifactStore(tmp_path / "source")
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    journal, _ = _execution_journal(tmp_path, source_store)
    journal["factory_receipt"]["patch_agent_loop"]["termination"] = {
        "code": "PATCH_AGENT_UPSTREAM_REQUESTED", "status": "upstream_requested", "turn_index": 1,
        "reason": "MODEL_INVENTED_ROOT_CAUSE", "upstream_request": {"reason": "MODEL_INVENTED_ROOT_CAUSE"},
    }
    reference = _json_ref(tmp_path / "journal.json", journal)
    remembered = memory.record_execution(reference, source_store=source_store)
    facts = memory.store.read(remembered)["data"]["facts"]
    assert "MODEL_INVENTED_ROOT_CAUSE" not in json.dumps(facts)
    view = memory_model_view(memory.retrieve("First Shot", context, max_chars=12000))
    assert "MODEL_INVENTED_ROOT_CAUSE" not in json.dumps(view)
    assert "PATCH_AGENT_UPSTREAM_REQUESTED" in json.dumps(view)


def test_execution_changed_evidence_creates_revision_and_bad_request_hash_blocks(tmp_path):
    source_store = ArtifactStore(tmp_path / "source")
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    journal, journal_ref = _execution_journal(tmp_path, source_store)
    first = memory.record_execution(journal_ref, source_store=source_store)
    journal["model_call_count"] = 2
    changed = _json_ref(tmp_path / "journal.json", journal)
    second = memory.record_execution(changed, source_store=source_store)
    assert first != second
    assert memory.history(memory.execution_lesson_id("execution-one", source_store=source_store)) == [first, second]
    (tmp_path / "request.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash changed"):
        memory.record_execution(changed, source_store=source_store)
