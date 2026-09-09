"""Every recovery segment remains visible to Graph admission and read-side queries."""
from copy import deepcopy

import pytest

from src.mod_agent.proposal.patch_agent_loop import iter_patch_recovery_revisions
from src.mod_agent.workflow.graph import _valid_patch_agent_loop_receipt
from src.observability.patch_execution_index import _phases
from tests.unit.test_patch_read_accounting_admission import _loop


def _continuous():
    loop = _loop()
    loop.update(total_observation_bytes=100, recovery_observation_bytes=200)
    loop["policy"].update(max_observation_bytes=500, max_total_model_turns=5)
    revisions = []
    for index in range(1, 3):
        revisions.append({"revision_index": index, "message_type": "patch_behavior_correction",
            "status": "completed", "attempt_count": 1, "model_call_count": 1,
            "response": {"output_sha256": str(index) * 64}, "execution": {
                "status": "completed", "model_turns_used": 1, "usage_by_turn": [{}],
                "tool_rounds_used": 0, "observation_trace": [], "total_observation_bytes": 100,
                "dispatched_binding_reads": 0, "reused_source_observations": 0,
                "read_accounting_version": "new_source_window_v2"}})
    loop.update(recovery_revisions=revisions, behavior_correction=deepcopy(revisions[-1]),
        behavior_evaluations=[{"status": "passed", "admission": "accepted", "execution_origin": "executed"}])
    return loop


def test_graph_accepts_complete_recovery_ledger_at_exact_byte_limit():
    loop = _continuous()
    assert _valid_patch_agent_loop_receipt(loop, model_call_count=4)
    assert len(iter_patch_recovery_revisions(loop)) == 2
    assert len(list(_phases(loop))) == 3


@pytest.mark.parametrize("damage", ["lost_first", "sequence", "alias", "bytes", "calls", "usage", "malformed"])
def test_graph_rejects_truncated_or_inconsistent_recovery_ledger(damage):
    loop = _continuous()
    if damage == "lost_first":
        loop["recovery_revisions"].pop(0)
    elif damage == "sequence":
        loop["recovery_revisions"][0]["revision_index"] = 2
    elif damage == "alias":
        loop["behavior_correction"]["response"]["output_sha256"] = "0" * 64
    elif damage == "bytes":
        loop["recovery_observation_bytes"] += 1
    elif damage == "calls":
        loop["recovery_revisions"][0]["model_call_count"] = 2
    elif damage == "usage":
        loop["recovery_revisions"][0]["execution"]["usage_by_turn"] = []
    else:
        loop["recovery_revisions"] = {}
    assert not _valid_patch_agent_loop_receipt(loop, model_call_count=4)


def test_old_receipt_still_projects_latest_slots_without_new_history_claim():
    loop = _continuous()
    del loop["recovery_revisions"]
    assert len(iter_patch_recovery_revisions(loop)) == 1
    assert len(list(_phases(loop))) == 2
    assert not _valid_patch_agent_loop_receipt(loop, model_call_count=4)


@pytest.mark.parametrize("extra", [None, "consumed_model_turns", "consumed_tool_rounds", "consumed_observation_bytes"])
def test_prior_worker_usage_is_not_reset_at_same_plan_return(extra):
    loop = _continuous()
    loop["prior_worker_budget"] = {
        "consumed_model_turns": 1, "consumed_tool_rounds": 5, "consumed_observation_bytes": 10,
    }
    loop["policy"]["max_observation_bytes"] = 510
    if extra:
        loop["prior_worker_budget"][extra] += 1
    assert _valid_patch_agent_loop_receipt(loop, model_call_count=4) is (extra is None)
