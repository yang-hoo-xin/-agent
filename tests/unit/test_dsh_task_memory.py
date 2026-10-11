"""DSH uses the original bound task records for experience, never a model answer."""

import json

import pytest

from scripts import dsh_task_memory as owner
from src.mod_agent.artifacts import ArtifactStore
from tests.unit.test_task_memory import _execution_journal, _json_ref


@pytest.fixture
def case(tmp_path):
    source = ArtifactStore(tmp_path / "run" / "a")
    journal, _ = _execution_journal(tmp_path, source)
    journal.update(receipt_version="patch_continuation_attempt_v1", feature_id=journal["selected_artifacts"]["feature_spec"]["feature_id"],
                   parent_product_run_id="public-one")
    path = source.root / "cr" / "attempt.json"
    path.parent.mkdir(parents=True)
    ref = _json_ref(path, journal)
    profile = tmp_path / "investigation.json"
    profile.write_text(json.dumps({"artifactStoreRoot": str(source.root), "featureId": journal["feature_id"],
        "runId": journal["run_id"], "currentContext": {"target_mod": "ExampleMod", "model": "test-model"}}))
    return {"source": source, "journal": journal, "ref": ref, "profile": profile,
            "arguments": {"memory_root": str(tmp_path / "memory"), "investigation_config": str(profile)}}


def test_dsh_records_and_queries_same_bound_history_without_changing_source(case):
    original = owner._absolute(case["ref"]["path"]).read_bytes()
    recorded = owner.run_memory(**case["arguments"], action="remember")
    assert recorded["artifact_writes_performed"] is True
    assert recorded["model_calls_performed"] == 0
    repeated = owner.run_memory(**case["arguments"], action="remember")
    assert repeated["artifact_writes_performed"] is False
    assert repeated["records"][0]["artifact_ref"] == recorded["records"][0]["artifact_ref"]
    result = owner.run_memory(**case["arguments"], action="query", query="First Shot timeout")
    assert result["model_view"]["lessons"]
    assert result["authority"] == "planning_only"
    assert result["read_only"] is True
    assert str(case["source"].root) not in json.dumps(result["model_view"])
    assert owner._absolute(case["ref"]["path"]).read_bytes() == original


def test_public_run_terminal_hook_accepts_original_receipt_metadata(case, monkeypatch):
    monkeypatch.setattr(owner, "inspect_run", lambda **kwargs: {
        "status": "recorded", "run_root": str(case["source"].root.parent),
        "result": {"patch_execution_receipts": [{**case["ref"], "model_call_count": 1, "status": "continuation_failed"}]}})
    result = owner.run_memory(memory_root=case["arguments"]["memory_root"], action="remember",
        execution_config="verified-by-original-inspect-run", run_id="public-one")
    assert result["status"] == "recorded"
    assert result["records"][0]["run_id"] == case["journal"]["run_id"]


def test_dsh_same_run_from_two_stores_reports_each_import_and_reuse(tmp_path, monkeypatch):
    from src.mod_agent.planning.task_memory import TaskMemory

    results = []
    for name in ("a", "b"):
        folder = tmp_path / name
        folder.mkdir()
        source = ArtifactStore(folder / "a")
        journal, _ = _execution_journal(folder, source)
        journal.update(receipt_version="patch_continuation_attempt_v1", parent_product_run_id="public-one")
        path = source.root / "cr" / "attempt.json"
        path.parent.mkdir(parents=True)
        ref = _json_ref(path, journal)
        monkeypatch.setattr(owner, "inspect_run", lambda **kwargs: {
            "status": "recorded", "run_root": str(folder), "result": {"patch_execution_receipts": [ref]}})
        args = dict(memory_root=str(tmp_path / "memory"), action="remember",
                    execution_config="verified-by-original-inspect-run", run_id="public-one")
        first = owner.run_memory(**args)
        repeated = owner.run_memory(**args)
        assert first["records"][0]["status"] == "recorded"
        assert repeated["records"][0]["status"] == "reused"
        assert repeated["read_only"] is True
        results.append(first["records"][0])
    assert results[0]["lesson_id"] != results[1]["lesson_id"]
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    found = memory.retrieve("First Shot timeout", {"target_mod": "ExampleMod", "model": "test-model"}, max_chars=24000)
    assert {item["lesson_id"] for item in found["relevant_lessons"]} == {item["lesson_id"] for item in results}


def test_public_run_does_not_remember_another_tasks_receipt(case, monkeypatch):
    monkeypatch.setattr(owner, "inspect_run", lambda **kwargs: {
        "status": "recorded", "run_root": str(case["source"].root.parent),
        "result": {"patch_execution_receipts": [case["ref"]]}})
    with pytest.raises(ValueError, match="PARENT_MISMATCH"):
        owner.run_memory(memory_root=case["arguments"]["memory_root"], action="remember",
            execution_config="verified-by-original-inspect-run", run_id="other-public-run")


def test_current_context_mismatch_filters_existing_experience(case):
    owner.run_memory(**case["arguments"], action="remember")
    config = json.loads(case["profile"].read_text())
    config["currentContext"]["model"] = "different-model"
    case["profile"].write_text(json.dumps(config))
    result = owner.run_memory(**case["arguments"], action="query", query="First Shot")
    assert not result["model_view"]["lessons"]
    assert result["retrieved_experience"]["unavailable_evidence"]


def test_no_patch_record_is_reported_without_inventing_memory(case, monkeypatch):
    monkeypatch.setattr(owner, "inspect_run", lambda **kwargs: {
        "status": "recorded", "run_root": str(case["source"].root.parent), "result": {"status": "partial"}})
    result = owner.run_memory(memory_root=case["arguments"]["memory_root"], action="remember",
        execution_config="verified-by-original-inspect-run", run_id="public-one")
    assert result["records"] == []
    assert result["artifact_writes_performed"] is False


def test_investigation_cli_requires_a_single_explicit_task(tmp_path):
    from scripts.engineering_cognition import EngineeringCognitionError, build_projection
    from tests.unit.test_patch_execution_index import _fixture

    root, path, journal, _report = _fixture(tmp_path)
    before = path.read_bytes()
    with pytest.raises(EngineeringCognitionError, match="explicit"):
        build_projection("verification-claims", query="patch-investigation", artifact_store_root=root)
    result = build_projection("verification-claims", query="patch-investigation", artifact_store_root=root,
                              run_id=journal["run_id"])
    assert result["subquery"] == "patch-investigation"
    stages = result["data"]["attempts"][0]["investigation_chain"]["stages"]
    assert len(stages) == 6
    assert result["read_only"] is True
    assert result["data"]["model_calls_performed"] == 0
    assert path.read_bytes() == before
