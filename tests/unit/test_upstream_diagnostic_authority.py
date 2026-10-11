"""Public-entry regression: a worker hypothesis must not become an obligation."""
import json
from pathlib import Path

from src.mod_agent.planning.implementation_plan import PLATFORM_SIDE_EFFECT_BOUNDARIES
from tests.unit.test_mod_agent_cli import _public_patch_upstream_scenario


def test_run_request_keeps_wrong_algorithm_diagnostic_and_original_scope(tmp_path, monkeypatch, capsys):
    reason = "Validate all transfers against original balances first, then apply every transfer."
    request = "Change Load behavior while preserving the public API and existing shared state."
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        owner="planning", upstream_reason=reason, request_description=request)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", observed.result
    initial, resumed = observed.patch_contexts
    assert all(reason not in boundary for boundary in resumed["constraints"])
    assert set(initial["constraints"]).issubset(resumed["constraints"])
    assert set(PLATFORM_SIDE_EFFECT_BOUNDARIES).issubset(resumed["constraints"])
    for field in ("request", "target_behavior", "acceptance_criteria", "runtime_verification_plan"):
        assert resumed[field] == initial[field]
    assert resumed["request"] == request
    assert resumed["allowed_edit_binding_ids"] == initial["allowed_edit_binding_ids"]
    assert resumed["edit_binding_contexts"] == initial["edit_binding_contexts"]
    plan = json.loads(Path(observed.result["artifacts"]["implementation_plan"]).read_text(encoding="utf-8"))
    assert all(reason not in boundary for boundary in plan["data"]["side_effect_boundaries"])
    diagnostics = [json.loads(value) for value in observed.planning[-1]["semantic_feedback"]
        if value.startswith("{") and "recommendation_is_not_observation" in value]
    assert len(diagnostics) == 1
    assert diagnostics[0]["recommendation"]["reason"] == reason
    assert diagnostics[0]["recommendation"]["origin"] == "model"
    assert diagnostics[0]["recommendation"]["source_refs"] == ["binding://edit_binding_001"]
    assert diagnostics[0]["observed_failure"] == []
    assert diagnostics[0]["failure_report_ref"] is None
    carried = next(value for value in observed.worker_requests[-1]
        if value.get("message_type") == "patch_replanned_context")
    assert carried["upstream_request"]["reason"] == reason
    assert carried["upstream_request"]["origin"] == "model"
    assert "hypotheses" in carried["upstream_request_semantics"]
    assert "constraints" in carried["upstream_request_semantics"]
    assert carried["prior_code_role"] == "no_failed_code_generated"
    for name, before in observed.source_bytes.items():
        assert (Path(observed.result["run_root"]) / "generated_mods" / "Example" / name).read_bytes() == before
    assert not observed.result["actual_write_performed"]
