"""A real repeated source query resumes the same Product worker without new judgments."""
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.mod_agent.evidence import reassessment
from src.mod_agent.evidence.models import EvidencePack
from tests.unit.test_mod_agent_cli import _public_patch_upstream_scenario


@pytest.mark.parametrize("query,task_limit,reused,query_calls", [
    ("Load", 5, True, 1),
    ("RefreshSharedState", 5, False, 1),
    ("Load", 4, False, 0),
])
def test_upstream_last_call_runs_query_without_reserving_conditional_findings(
    tmp_path, monkeypatch, capsys, query, task_limit, reused, query_calls,
):
    ordinary = reassessment.RequirementCoverageReassessmentFactory._reassess
    returned = []

    def capture(self, *args, **kwargs):
        pack = ordinary(self, *args, **kwargs)
        returned.append(pack)
        return pack

    monkeypatch.setattr(reassessment.RequirementCoverageReassessmentFactory, "_reassess", capture)
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        upstream_query=query, task_limit=task_limit, model_call_budget_policy="task_total_only")
    assert observed.exit_code == (1 if reused else 2)
    assert len(observed.requests) == task_limit
    assert observed.roles.count("patch_upstream_evidence_queries") == query_calls
    assert len(observed.searches) == 1 + query_calls
    assert len(observed.findings) == len(observed.planning) == 1
    assert len(observed.patch_contexts) == 1
    assert any(pack.budget_summary["reassessment"].get("reuse_current_evidence") for pack in returned) is reused
    assert "BUDGET_EXHAUSTED" in json.dumps(observed.result)


def test_same_complete_source_recheck_skips_findings_and_planning(tmp_path, monkeypatch, capsys):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        upstream_query="Load", task_limit=6)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", json.dumps(observed.result.get("blockers", []))
    assert observed.roles == ["product_requirement_projection", "product_requirement_findings", "planning",
        "patch", "patch_upstream_evidence_queries", "patch"]
    assert len(observed.searches) == 2
    assert len(observed.findings) == len(observed.planning) == 1
    before, resumed = observed.patch_contexts
    assert resumed == before
    same_plan = next(row for row in observed.worker_requests[-1]
        if row.get("message_type") == "patch_same_plan_assessment")
    assert "no new source facts" in same_plan["planning_rationale"]
    assert same_plan["approval_inherited"] is False
    for name, data in observed.source_bytes.items():
        assert (Path(observed.result["run_root"]) / "generated_mods/Example" / name).read_bytes() == data
    assert observed.result["actual_write_performed"] is False
    checkpoint = json.loads(Path(observed.result["workflow_checkpoint"]["path"]).read_text(encoding="utf-8"))
    audit = checkpoint["data"]["state_snapshot"]["runtime_summary"]["evidence_reassessment"]
    assert audit["query_count"] == 1 and audit["new_source_facts"] is False
    assert audit["findings_recomputed"] is audit["planning_recomputed"] is False
    assert audit["grants_new_authority"] is False


def test_same_plan_new_native_client_inherits_observed_prompt_calibration(tmp_path, monkeypatch, capsys):
    from src.libs.llm.agent_turn import OllamaChatAgentAdapter

    ordinary = OllamaChatAgentAdapter.complete_turn
    native_calls = []

    def capture(client, request):
        resumed = any(isinstance(message.content, dict)
            and message.content.get("message_type") == "patch_same_plan_assessment" for message in request.messages)
        native_calls.append({"client": id(client), "resumed": resumed,
                             "prior_calibrations": len(client._prompt_token_calibrations)})
        return ordinary(client, request)

    monkeypatch.setattr(OllamaChatAgentAdapter, "complete_turn", capture)
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        upstream_query="Load", task_limit=6)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval"
    resumed, = [call for call in native_calls if call["resumed"]]
    earlier = [call for call in native_calls if not call["resumed"]]
    assert resumed["client"] not in {call["client"] for call in earlier}
    assert resumed["prior_calibrations"] == 1
    assert observed.result["model_call_count"] == 6
    assert observed.result["actual_write_performed"] is False


def test_changed_scope_source_or_query_material_cannot_reuse_judgments(tmp_path, monkeypatch, capsys):
    validate = reassessment.validate_unchanged_source_reassessment
    admitted = []

    def capture(pack, **kwargs):
        result = validate(pack, **kwargs)
        if result is not None:
            admitted.append((pack, {**kwargs, "state": deepcopy(kwargs["state"]),
                "feature_data": deepcopy(kwargs["feature_data"])}))
        return result

    monkeypatch.setattr(reassessment, "validate_unchanged_source_reassessment", capture)
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys, upstream_query="Load", task_limit=6)
    assert observed.exit_code == 0 and admitted
    pack, kwargs = admitted[0]
    assert validate(pack, **kwargs) is not None
    for field in ("user_request", "target_behavior", "non_goals"):
        feature = deepcopy(kwargs["feature_data"])
        feature[field] = ["new boundary"] if field == "non_goals" else "different user intent"
        assert validate(pack, **{**kwargs, "feature_data": feature}) is None
    for kind in ("feature_spec", "evidence_pack", "implementation_plan"):
        state = deepcopy(kwargs["state"])
        state["artifact_hashes"][kind] = "0" * 64
        assert validate(pack, **{**kwargs, "state": state}) is None
    for field in ("user_request", "target_mod"):
        state = deepcopy(kwargs["state"])
        state[field] = "different scope"
        assert validate(pack, **{**kwargs, "state": state}) is None
    for change in ("new_items", "api", "gap", "query_miss", "query_identity", "partial"):
        summary = deepcopy(pack.budget_summary)
        items = pack.items
        if change == "new_items":
            summary["reassessment"]["new_item_count"] = 1
            summary["reassessment"]["new_evidence_ids"] = ["new_fact"]
        elif change == "api":
            summary["dependency_api_supplement"] = {"status": "observed_metadata_only",
                "visible_metadata": {"methods": [{"name": "new_api_fact"}]}}
        elif change == "gap":
            summary["reassessment"]["queries"][0]["gap_ids"] = ["new_gap"]
        elif change == "query_miss":
            summary["reassessment"]["per_query_execution"][0]["retrieval_status"] = "no_matches"
        elif change == "query_identity":
            summary["reassessment"]["per_query_execution"][0]["query_sha256"] = "0" * 64
        else:
            items = (replace(items[0], span={"start_line": 2, "end_line": 2}), *items[1:])
        assert validate(replace(pack, items=items, budget_summary=summary), **kwargs) is None
    source = Path(kwargs["workspace_root"]) / pack.items[0].source_path
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\n// source drift\n")
        assert validate(pack, **kwargs) is None
    finally:
        source.write_bytes(original)


@pytest.mark.parametrize("material", ["new_source", "api_metadata"])
def test_new_material_still_runs_original_findings_and_planning(tmp_path, monkeypatch, capsys, material):
    if material == "api_metadata":
        initialize = reassessment.RequirementCoverageReassessmentFactory.__init__

        def configured(self, **kwargs):
            initialize(self, **kwargs)
            self.source_augmentation_factory = lambda _projection, retrieved: EvidencePack(
                query=retrieved.query, readiness="partial", can_generate_patch=False,
                provenance_validation={"target_code_executed": False},
                budget_summary={"dependency_api_supplement": {"status": "observed_metadata_only",
                    "model_calls_performed": 0, "visible_metadata": {"methods": [{"name": "synthetic new API fact"}]}}})

        monkeypatch.setattr(reassessment.RequirementCoverageReassessmentFactory, "__init__", configured)
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        upstream_query="Load" if material == "api_metadata" else "RefreshSharedState")
    assert observed.exit_code == 0, observed.result
    assert len(observed.searches) == 2 and len(observed.findings) == len(observed.planning) == 2
    assert observed.roles[-3:] == ["product_requirement_findings", "planning", "patch"]
    assert not any(row.get("message_type") == "patch_same_plan_assessment" for row in observed.worker_requests[-1])


def test_two_source_rechecks_preserve_both_audits_and_cumulative_worker_history(tmp_path, monkeypatch, capsys):
    observed = _public_patch_upstream_scenario(tmp_path, monkeypatch, capsys,
        upstream_query=("Load", "Plugin"), upstream_repeat_count=1,
        model_call_budget_policy="task_total_only", task_limit=8)
    assert observed.exit_code == 0 and observed.result["status"] == "awaiting_approval", json.dumps(observed.result.get("blockers", []))
    assert observed.roles == ["product_requirement_projection", "product_requirement_findings", "planning",
        "patch", "patch_upstream_evidence_queries", "patch", "patch_upstream_evidence_queries", "patch"]
    assert len(observed.searches) == 3 and len(observed.findings) == len(observed.planning) == 1
    assert observed.result["model_call_count"] == 8
    assert all(context == observed.patch_contexts[0] for context in observed.patch_contexts)
    checkpoint = json.loads(Path(observed.result["workflow_checkpoint"]["path"]).read_text(encoding="utf-8"))
    state = checkpoint["data"]["state_snapshot"]
    history = state["runtime_summary"]["evidence_reassessment_history"]
    assert len(history) == 2 and history[0]["repair_plan_hash"] != history[1]["repair_plan_hash"]
    assert [row["queries"][0]["query"] for row in history] == ["Load", "Plugin"]
    assert all(row["per_query_execution"][0]["retrieval_status"] == "source_observations_returned" for row in history)
    traced = [row["details"]["source_reassessment"] for row in state["trace_events"]
        if row["node_name"] == "retrieve_evidence" and row["event_type"] == "node_finished"
        and "source_reassessment" in row.get("details", {})]
    assert traced == history
    loop_states = [next(row for row in rows if row.get("message_type") == "patch_agent_loop_state")
        for rows in observed.worker_requests]
    assert [row["budget_state"]["model_turns_used"] for row in loop_states] == [0, 1, 2]
    # 为什么要有它：审查说明不能替代原生工具回复；模型必须看到自己的补查请求已经完成。
    patch_payloads = [payload for role, payload in zip(observed.roles, observed.requests, strict=True)
                      if role == "patch"]
    for expected, payload in enumerate(patch_payloads):
        messages = payload["messages"]
        outcomes = [message for message in messages if message["role"] == "tool"
                    and message.get("tool_name") == "request_patch_upstream"]
        assert len(outcomes) == expected
        for outcome in outcomes:
            index = messages.index(outcome)
            call = messages[index - 1]
            assert call["role"] == "assistant"
            assert call["tool_calls"][0]["function"]["name"] == "request_patch_upstream"
            result = json.loads(outcome["content"])
            assert result["status"] == "completed"
            assert result["decision"] == "retain_current_plan"
            assert result["approval_inherited"] is False
