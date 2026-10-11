"""Task-only quotas retain stage accounting and stop exactly at the total boundary."""
import json
from copy import deepcopy

import pytest

from src.mod_agent.initial_findings_continuation import _budget
from src.mod_agent.local_entry import (
    LocalEntryError,
    _preflight_request_model_calls,
    _reserve_request_model_call,
)
from src.mod_agent.model_call_budget import as_task_total_only, call_allowance
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401
from tests.unit.test_patch_agent_loop import _fixture, _response, _run, _ScriptedClient, _tool_call


def historical_budget():
    limits = {"requirement_projection": 2, "requirement_findings": 5, "planning": 1, "initial_patch": 2, "repair": 3}
    used = {"requirement_projection": 2, "requirement_findings": 5, "planning": 0, "initial_patch": 0, "repair": 1}
    return {"maximum": 13, "consumed": 8, "remaining": 5,
        "count_basis": "reserved_provider_invocations_not_transport_proof",
        "by_stage": {key: {"maximum": limit, "consumed": used[key], "remaining": limit-used[key]}
                     for key, limit in limits.items()}}


def test_task_total_passes_old_stage_zero_and_preserves_both_snapshot_forms():
    original = historical_budget()
    before = deepcopy(original)
    roles = ("initial_findings_queries", "requirement_findings", "planning", "initial_patch")
    assert not _preflight_request_model_calls(original, roles)["admitted"]
    current = as_task_total_only(original)
    assert _preflight_request_model_calls(current, roles)["admitted"]
    assert current["by_stage"]["requirement_findings"] == {"consumed": 5}
    for stage in ("repair", "requirement_findings", "planning", "initial_patch"):
        current = _reserve_request_model_call(current, stage)
    assert current["consumed"] == 12 and current["remaining"] == 1
    assert current["by_stage"]["requirement_findings"] == {"consumed": 6}
    assert _budget(current) == current and _budget(original) == before
    assert original == before
    current = _reserve_request_model_call(current, "initial_patch")
    assert current["consumed"] == 13 and current["remaining"] == 0
    frozen = deepcopy(current)
    with pytest.raises(LocalEntryError, match="PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED"):
        _reserve_request_model_call(current, "requirement_findings")
    assert not _preflight_request_model_calls(current, ("requirement_findings",))["admitted"]
    assert current == frozen


def test_shared_worker_can_exceed_old_five_turn_limit_without_changing_tool_guards(tmp_path):
    budget = as_task_total_only(historical_budget())
    budget["by_stage"]["requirement_projection"]["consumed"] = 0
    budget["by_stage"]["repair"]["consumed"] = 0
    budget.update(consumed=5, remaining=8)
    assert call_allowance(budget, "requirement_findings", local_limit=0) == 8
    policy = PatchAgentLoopPolicy(model_call_budget_policy="task_total_only", max_total_model_turns=8,
        max_tool_rounds=6, finalize_after_first_observation=False, require_source_inspection=False)
    _, _, _, inspector = _fixture(tmp_path, binding_count=6, policy=policy)
    replies = [_response(turn=i, tool_calls=(_tool_call(f"edit_binding_{i:03d}", turn=i),)) for i in range(1, 7)]
    replies.append(_response(turn=7, content='{"changes":[]}'))
    client = _ScriptedClient(replies)
    result = _run(client, inspector)
    assert result.completed and result.model_turns_used == 7 and result.tool_rounds_used == 6
    assert inspector.policy.max_tool_rounds == 6


def test_total_budget_reassessment_continues_useful_second_cycle(tmp_path):
    from tests.unit.test_findings_reassessment_budget import _budget as initial_budget
    from tests.unit.test_findings_reassessment_budget import _factory
    from tests.unit.test_requirement_coverage import _initial_findings_reassessment_case

    case = _initial_findings_reassessment_case(tmp_path)
    budget = as_task_total_only(initial_budget())
    calls = []
    result = _factory(case, tmp_path, budget, calls, cycles=1, first_findings_missing=True).reassess_initial(
        case.state, case.feature)
    assert [role for role, _ in calls] == ["initial_findings_queries", "requirement_findings"] * 2
    assert result.can_generate_patch
    assert budget["consumed"] == 7


def test_product_upstream_uses_total_budget_after_first_replan(tmp_path, monkeypatch, capsys):
    from tests.unit.test_mod_agent_cli import _public_patch_upstream_scenario

    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        owner="planning", repeat_upstream=True, task_limit=13)
    assert "model_call_budget" in observed.result, observed.result
    assert observed.result["model_call_budget"]["policy"] == "task_total_only"
    assert observed.result["model_call_budget"]["consumed"] <= 13
    assert observed.roles.count("planning") >= 3, observed.result.get("blockers")
    assert observed.roles.count("patch") >= 3


def test_normal_fresh_task_defaults_to_total_only_without_stage_file(execution_config, monkeypatch, capsys):
    from tests.unit.test_dsh_run_request import _call, _install_execution_boundaries
    value = json.loads(execution_config.read_text(encoding="utf-8"))
    for option in ("--stage-model-call-limits", "--model-call-budget-policy"):
        index = value["arguments"].index(option)
        del value["arguments"][index:index + 2]
    execution_config.write_text(json.dumps(value), encoding="utf-8")
    _install_execution_boundaries(execution_config.parent, monkeypatch)
    assert _call(execution_config, "make Load record deterministic product diagnostics", monkeypatch) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "awaiting_approval"
    assert result["model_call_budget"]["policy"] == "task_total_only"
    assert result["model_call_budget"]["maximum"] == 9
    assert result["model_call_budget"]["consumed"] == 4
    assert all(set(row) == {"consumed"} for row in result["model_call_budget"]["by_stage"].values())
