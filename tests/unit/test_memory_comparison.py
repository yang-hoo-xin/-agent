"""Public controlled memory fixtures; no business memory or sealed materials."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.prepare_memory_comparison import main
from src.core.settings import TaskMemorySettings
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evaluation.memory_comparison import (
    prepare_memory_pair,
    summarize_memory_outcomes,
    verify_memory_pair,
)
from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
from src.mod_agent.planning.task_memory import TaskMemory
from tests.unit.test_fresh_planning_continuation import _inputs
from tests.unit.test_planning_task_memory import _client, _record


def prepare(tmp_path):
    inputs = _inputs(tmp_path / "public")
    memory_root = tmp_path / "before-memory"
    memory = TaskMemory(ArtifactStore(memory_root))
    lesson, evidence = _record(memory, inputs, tmp_path)
    settings = tmp_path / "settings.yaml"
    settings.write_text(yaml.safe_dump({"fixed_other_settings": {"value": 1},
        "task_memory": {"enabled": False, "max_context_chars": 6000}}))
    invariants = {key: {"identity": "public-controlled-" + key} for key in
        ("task", "model", "tools", "permissions", "budget", "judge", "initial_environment")}
    ref = prepare_memory_pair(settings_path=settings, memory_root=memory_root,
        invariants=invariants, output_root=tmp_path / "pair")
    return inputs, memory, lesson, evidence, settings, invariants, ref


def test_frozen_pair_reaches_original_planning_wire_only_as_automatic_memory(tmp_path):
    inputs, memory, lesson, _, _, _, reference = prepare(tmp_path)
    protocol = json.loads(Path(reference["path"]).read_text())
    evidence_pack = inputs.store.read(inputs.evidence_ref)["data"]
    wires, receipts = {}, {}
    for arm in protocol["arms"]:
        settings = yaml.safe_load(Path(arm["settings_ref"]["path"]).read_text())
        captured = []
        selector = ModelPlanningTargetSelector.from_settings(
            settings=SimpleNamespace(task_memory=TaskMemorySettings(**settings["task_memory"])),
            client=_client(captured), workspace_root=inputs.workspace,
            receipt_path=Path(arm["receipts_root"]) / "planning.json",
            model_identity={"digest": "current-model-digest"})
        selector(inputs.feature_payload, evidence_pack)
        wires[arm["arm"]] = json.loads(captured[0]["messages"][1]["content"])
        receipts[arm["arm"]] = json.loads(selector.receipt_path.read_text())
    on = deepcopy(wires["memory_on"])
    view = on.pop("retrieved_experience")
    assert on == wires["memory_off"]
    assert view["lessons"][0]["artifact_hash"] == lesson.artifact_hash
    assert receipts["memory_on"]["task_memory"]["model_lesson_refs"][0]["artifact_hash"] == lesson.artifact_hash
    assert "task_memory" not in receipts["memory_off"]
    assert all(r["model_responses_received"] == 1 for r in receipts.values())
    assert verify_memory_pair(reference)["status"] == "frozen_pair_intact"
    # New experiences go to the live origin only after this test's fixed inputs;
    # neither frozen arm can consume them or change original lesson identities.
    _record(memory, inputs, tmp_path, "later-lesson", scope="later")
    assert verify_memory_pair(reference)["status"] == "frozen_pair_intact"


@pytest.mark.parametrize("kind", ["memory_write", "settings_write", "evidence_write"])
def test_pair_rejects_cross_arm_learning_settings_or_bound_evidence_drift(tmp_path, kind):
    _, _, _, evidence, _, _, reference = prepare(tmp_path)
    protocol = json.loads(Path(reference["path"]).read_text())
    arm = protocol["arms"][1]
    if kind == "memory_write":
        (Path(arm["memory_root"]) / "new-learning.json").write_text("{}")
    elif kind == "settings_write":
        path = Path(arm["settings_ref"]["path"])
        path.write_text(path.read_text() + "another_option: true\n")
    else:
        evidence.write_text("{}")
    with pytest.raises(ValueError):
        verify_memory_pair(reference)


def test_protocol_identity_and_output_reuse_are_not_silent(tmp_path):
    _, memory, _, _, settings, invariants, reference = prepare(tmp_path)
    wrong = {**reference, "sha256": "0" * 64}
    with pytest.raises(ValueError):
        verify_memory_pair(wrong)
    with pytest.raises(FileExistsError):
        prepare_memory_pair(settings_path=settings, memory_root=memory.store.root,
                            invariants=invariants, output_root=tmp_path / "pair")


def test_time_dependent_lessons_require_an_explicit_window(tmp_path):
    inputs, memory, _, _, settings, invariants, _ = prepare(tmp_path)
    _record(memory, inputs, tmp_path, "expiring", expires_at="2099-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="common evaluation window"):
        prepare_memory_pair(settings_path=settings, memory_root=memory.store.root,
                            invariants=invariants, output_root=tmp_path / "another-pair")


def test_cli_freezes_and_verifies_without_model_execution(tmp_path, capsys):
    _, memory, _, _, settings, invariants, _ = prepare(tmp_path)
    identities = tmp_path / "identities.json"
    identities.write_text(json.dumps(invariants))
    assert main(["--settings", str(settings), "--memory-root", str(memory.store.root),
                 "--invariants", str(identities), "--output-root", str(tmp_path / "cli-pair")]) == 0
    reference = json.loads(capsys.readouterr().out)
    assert main(["--verify", reference["path"], "--sha256", reference["sha256"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model_calls"] == 0 and result["observed_task_success_rate"] is None


def test_first_attempts_unknowns_and_clarification_are_not_technical_rescues():
    def row(arm, attempt, success, **values):
        return {"task_id": "public-exposed", "arm": arm, "attempt": attempt,
                "verdict": {"task_success": success}, **values}
    rows = [row("memory_off", 1, False, requirement_clarifications=1, approvals=1),
            row("memory_off", 2, True), row("memory_on", 1, None, native_model_calls=0, native_duration_ms=1.25)]
    report = summarize_memory_outcomes(rows)
    assert report["distinct_task_count"] == 1 and report["attempt_count"] == 3
    off, on = report["by_arm"]["memory_off"], report["by_arm"]["memory_on"]
    assert off["task_success_rate"] == 0 and off["repeat_attempt_count"] == 1
    assert off["requirement_clarifications"] == 1 and off["approvals"] == 1
    assert off["human_technical_interventions"] is None and off["incorrect_revisions"] is None
    assert on["task_success_rate"] is None and on["native_model_calls"] == 0
    assert on["native_duration_ms"] == 1.25
    assert report["success_rate_improvement"] == "not_demonstrated"
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_memory_outcomes([rows[0], rows[0]])
