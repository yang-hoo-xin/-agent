"""Graph admission understands source reuse without forgiving fabricated counts."""

from copy import deepcopy

import pytest

from src.mod_agent.workflow.graph import _valid_patch_agent_loop_receipt


def _loop():
    return {
        "enabled": True, "status": "completed", "model_turns_used": 2,
        "tool_rounds_used": 1, "dispatched_binding_reads": 2,
        "reused_source_observations": 1, "read_accounting_version": "new_source_window_v2",
        "policy": {"max_tool_rounds": 6, "require_source_inspection": True,
                   "reuse_covered_source_observations": True},
        "usage_by_turn": [{}, {}],
        "observation_trace": [
            {"observation_id": "obs-1", "admitted_to_model": True, "read_cost": 1,
             "observation_origin": "current_source_read"},
            {"observation_id": "obs-2", "admitted_to_model": True, "read_cost": 0,
             "observation_origin": "prior_visible_source_reuse"},
        ],
        "termination": {"status": "completed", "code": "PATCH_AGENT_MODEL_FINISHED"},
    }


def test_graph_accepts_verified_reuse_accounting_in_initial_and_recovery_phases():
    value = _loop()
    assert _valid_patch_agent_loop_receipt(value, model_call_count=2)
    execution = deepcopy(value)
    for index, observation in enumerate(execution["observation_trace"], 3):
        observation["observation_id"] = f"obs-{index}"
    value["behavior_correction"] = {
        "status": "completed", "attempt_count": 1, "model_call_count": 2,
        "response": {}, "execution": execution,
    }
    value["behavior_evaluations"] = [{"status": "passed", "admission": "accepted",
                                      "execution_origin": "executed"}]
    assert _valid_patch_agent_loop_receipt(value, model_call_count=4)


@pytest.mark.parametrize("damage", ["cost", "origin", "dispatch", "reuse", "version", "disabled"])
def test_graph_rejects_inconsistent_source_reuse_accounting(damage):
    value = _loop()
    if damage == "cost":
        value["observation_trace"][1]["read_cost"] = 1
    elif damage == "origin":
        value["observation_trace"][1]["observation_origin"] = "current_source_read"
    elif damage == "dispatch":
        value["dispatched_binding_reads"] = 1
    elif damage == "reuse":
        value["reused_source_observations"] = 2
    elif damage == "version":
        value["read_accounting_version"] = "binding_dispatch_v1"
    else:
        value["policy"]["reuse_covered_source_observations"] = False
    assert not _valid_patch_agent_loop_receipt(value, model_call_count=2)
