from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts import prepare_patch_sft_data as data
from scripts import run_patch_sft_eval as evaluation
from src.libs.llm import ChatResponse
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
from src.mod_agent.model_qualification import canonical_hash, read_bound_json
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector
from tests.unit import test_patch_sft_eval as fixtures


def _recorded_input():
    return {
        "initial_state": {"Count": 0, "Total": 0},
        "operations": [{"step": 1, "action": "call", "member": "Apply",
                        "arguments": {"sample": 7, "publish": False}}],
        "observation": {"member": "Count", "step": 1},
    }


def test_explicit_verifier_input_survives_feedback_without_aliasing() -> None:
    row = {"group": "new", "input": _recorded_input()}
    expected = deepcopy(row["input"])
    projected = evaluation._observation_input(row, case_id="unrelated-task")
    row["input"]["operations"].append({"step": 2, "action": "later"})
    assert projected == expected
    report = {"observations": [{"check_id": "observed_count", "input": projected}]}
    feedback = LocalOllamaInitialPatchAdapter._model_failure_feedback(report)
    assert feedback["observations"][0]["input"] == expected
    report["observations"][0]["input"]["initial_state"]["Count"] = 100
    assert feedback["observations"][0]["input"] == expected


@pytest.mark.parametrize("extra", [{}, {"input": None}])
def test_missing_recorded_input_stays_unknown_without_reconstructed_steps(extra) -> None:
    value = evaluation._observation_input({"group": "new", **extra}, case_id="arbitrary-task")
    assert value == {"case_id": "arbitrary-task", "group": "new", "execution_context_status": "unknown"}
    assert "operations" not in value and "initial_state" not in value


def test_teacher_and_live_oracle_preserve_explicit_process_input(tmp_path, monkeypatch) -> None:
    execute = fixtures._fake_execution

    def with_input(root, source, program, tools):
        report = execute(root, source, program, tools)
        report.pop("report_ref")
        for row in report["checks"]:
            row["input"] = _recorded_input()
        return {**report, "report_ref": data.save(root / "behavior-input.json", report)}

    monkeypatch.setattr(fixtures, "_fake_execution", with_input)
    task, manifest, profile, _ = fixtures._fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(evaluation, "execute_version", with_input)
    monkeypatch.setattr(evaluation, "toolchain", lambda: {})
    evaluation.prepare_eval(
        manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
        mode="fixed_failure", attempt_id="process-input", output_root=tmp_path / "attempt",
    )
    teacher = json.loads((tmp_path / "attempt/fixed-failure.json").read_text(encoding="utf-8"))
    assert teacher["observations"][0]["input"] == _recorded_input()
    request = evaluation._request(read_bound_json(task["continuation_input_ref"]))
    admitted, generator, prepared = evaluation._contract(request)
    raw = read_bound_json(task["raw_request_ref"])
    content = next(row["content"] for row in raw["messages"] if row["role"] == "assistant")
    generated = generator.materialize_prepared_native(
        prepared, ChatResponse(content=content, model="offline-recorded-C1"),
    )
    materialized = materialize_exact_text_patch(
        workspace_root=request.workspace_root, diff_intent=generated.changes,
        implementation_plan=admitted.implementation_plan,
    )
    inspector = PlanBoundSourceInspector(
        workspace_root=request.workspace_root, implementation_plan=admitted.implementation_plan,
        policy=PatchAgentLoopPolicy(),
    )
    oracle = evaluation.OwnedSftOracle(
        manifest_ref=manifest, case_id=task["case_id"], output_root=tmp_path / "verification",
    )
    report = oracle({
        "generated_changes": generated.changes,
        "generated_changes_sha256": canonical_hash(generated.changes),
        "implementation_plan": admitted.implementation_plan,
        "materialized_code_identity": {
            "baseline_sha256": materialized.baseline_sha256,
            "code_sha256": materialized.code_sha256, "files": sorted(materialized.files),
        },
        "source_snapshot_sha256": inspector.source_snapshot_sha256,
        "model_response": {"output_sha256": "offline-record-only"},
    })
    assert report["status"] == "behavior_failed"
    assert report["observations"][0]["input"] == _recorded_input()
    assert report["verification_summary"]["checks"] == 2
