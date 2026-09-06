"""Recovery uses the same worker and exposes tested code, facts and constraints."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.libs.llm import AgentToolCall, OllamaChatAgentAdapter
from src.mod_agent.fresh_planning_continuation import run_fresh_patch_continuation
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from src.mod_agent.workflow.graph import _valid_patch_agent_loop_receipt
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _patch_request,
    _PatchAgentTurnClient,
    _source_hashes,
)
from tests.unit.test_patch_behavior_feedback import _adapter, _BehaviorOracle


class _InvestigatingClient(_PatchAgentTurnClient):
    def __init__(self):
        super().__init__()
        self.investigated_failure = False

    def complete_turn(self, request):
        response = super().complete_turn(request)
        feedback = next((m.content for m in request.messages if isinstance(m.content, dict)
                         and m.content.get("message_type") == "patch_behavior_correction"), None)
        if feedback and not self.investigated_failure:
            self.investigated_failure = True
            assert request.tools, "Failure correction must retain legal read tools."
            source_tool = next(t for t in request.tools if t.name == "inspect_plan_binding_source")
            selected = source_tool.parameters["properties"]["binding_id"]["enum"][0]
            return replace(response, content=None, tool_calls=(AgentToolCall(
                call_id="inspect-after-failure", name="inspect_plan_binding_source",
                arguments={"binding_id": selected},
            ),), stop_reason="tool_calls", provider_state={"content": "", "tool_calls": [{
                "function": {"name": "inspect_plan_binding_source", "arguments": {"binding_id": selected}},
            }]})
        if response.content and not feedback:
            return replace(response, content=response.content.replace(
                "RecordRuntimeMarker", "RecordMissingMarker"))
        return response


@pytest.mark.parametrize("model_budget", [4, 5])
def test_feedback_can_drive_new_inspection_without_losing_tested_draft_or_obligations(tmp_path, model_budget):
    inputs = _inputs(tmp_path)
    before = _source_hashes(inputs.workspace)
    client = _InvestigatingClient()
    oracle = _BehaviorOracle(tmp_path / "observations")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        finalize_after_first_observation=False, require_source_inspection=False,
        enable_supporting_reads=True,
        max_total_model_turns=model_budget,
    )
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=model_budget,
    )
    assert result.status == "terminal", result.to_dict()
    assert client.investigated_failure
    assert len(client.requests) == 4
    assert len(oracle.contexts) == 2
    assert oracle.reports[-1]["status"] == "passed"
    assert _source_hashes(inputs.workspace) == before
    final = client.requests[-1]
    feedback = next(m.content for m in final.messages if isinstance(m.content, dict)
                    and m.content.get("message_type") == "patch_behavior_correction")
    assert feedback["revision_semantics"] == "complete_replacement_relative_to_B0"
    draft = next(m.content for m in final.messages if m.role == "assistant")
    tested = json.loads(draft)["changes"]
    assert [c["after_text"] for c in tested] == [
        c["patch"]["after_text"] for c in oracle.contexts[0]["generated_changes"]]
    assert feedback["validator_feedback"]["observations"] == oracle.reports[0]["observations"]
    assert final.messages[0].content == client.requests[0].messages[0].content
    assert final.messages[1].content == client.requests[0].messages[1].content
    captured = []
    def send(_url, payload, _headers):
        captured.append(payload)
        return {"model": client.model, "message": {"content": "{}"}, "done": True}
    serializer = OllamaChatAgentAdapter(model=client.model, base_url="http://127.0.0.1:11434",
                                       max_output_tokens=64, request_sender=send)
    serializer.complete_turn(final)
    payload = captured[0]
    wire_messages = json.dumps(payload["messages"])
    assert "RecordMissingMarker" in wire_messages
    assert "complete_replacement_relative_to_B0" in wire_messages
    receipt = adapter.patch_attempt_receipt()
    correction = receipt["patch_agent_loop"]["behavior_correction"]
    assert correction["model_call_count"] == 2
    assert correction["execution"]["tool_rounds_used"] == 1
    assert receipt["model_call_count"] == 4
    capacity = receipt["patch_agent_loop"]["recovery_capacity_at_failure"]
    assert capacity["can_read_consume_and_revise"] is True
    assert capacity["remaining_model_turns"] >= 2
    assert capacity["remaining_binding_reads"] >= 1
    assert capacity["affordable_unread_binding_ids"]
    feedback_budget = receipt["patch_agent_loop"]["behavior_feedback_budget"]
    assert capacity["feedback_utf8_bytes"] == feedback_budget["feedback_utf8_bytes"]
    assert capacity["remaining_observation_bytes_after_feedback"] == feedback_budget["limit"] - feedback_budget["combined_utf8_bytes"]


class _DeclaredOracle:
    """An actually executed deterministic synthetic static check, not game Runtime."""
    def __init__(self, root, *, reusable=True):
        self.root = root
        self.reusable = reusable
        self.environment = 1
        self.contexts = []
        self.reports = []

    def verification_identity(self):
        def sha(text):
            return hashlib.sha256(text.encode()).hexdigest()
        return {"validator_sha256": sha("synthetic-static-marker-v1"),
                "inputs_sha256": sha("require RecordRepairMarker"),
                "environment_sha256": sha(str(self.environment)),
                "deterministic_reuse_allowed": self.reusable}

    def __call__(self, context):
        self.contexts.append(deepcopy(context))
        passed = all("RecordRepairMarker();" in row["patch"]["after_text"] for row in context["generated_changes"])
        report = {"status": "passed" if passed else "behavior_failed",
                  "failure_owner": None if passed else "patch_implementation",
                  "owner_binding_ids": [] if passed else [context["generated_changes"][0]["edit_binding_id"]],
                  "observations": [] if passed else [{"check_id": "synthetic_static_marker", "input": {"enabled": True},
                      "expected": {"marker_present": True}, "observed": {"marker_present": False}}],
                  "generated_changes_sha256": context["generated_changes_sha256"],
                  "source_snapshot_sha256": context["source_snapshot_sha256"],
                  "execution_origin": "executed", "verification_scope": "synthetic static check"}
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / f"execution-{len(self.contexts)}.json"
        data = json.dumps(report, sort_keys=True).encode()
        p.write_bytes(data)
        report["report_ref"] = {"path": str(p), "sha256": hashlib.sha256(data).hexdigest()}
        self.reports.append(deepcopy(report))
        return report


class _RepeatFailedClient(_InvestigatingClient):
    def __init__(self, on_investigation=None):
        super().__init__()
        self.on_investigation = on_investigation

    def complete_turn(self, request):
        response = super().complete_turn(request)
        if self.investigated_failure and self.on_investigation:
            self.on_investigation()
        if response.content:
            payload = json.loads(response.content.replace("RecordMissingMarker", "RecordRuntimeMarker"))
            for row in payload["changes"]:
                row["rationale"] = f"Explanation changed on turn {len(self.requests)}."
            return replace(response, content=json.dumps(payload))
        return response


@pytest.mark.parametrize("reuse,change_environment", [(True, False), (False, False), (True, True)])
def test_repeated_failed_materialized_code_uses_same_budget_and_only_explicit_reuse(tmp_path, reuse, change_environment):
    from tests.unit.test_patch_repair_continuation import _repair_case
    inputs, request, _ = _repair_case(tmp_path)
    oracle = _DeclaredOracle(tmp_path / "verification", reusable=reuse)
    client = _RepeatFailedClient(lambda: setattr(oracle, "environment", 2) if change_environment else None)
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        finalize_after_first_observation=False, require_source_inspection=False, enable_supporting_reads=True,
    )
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.reason == "PATCH_BEHAVIOR_CORRECTION_FAILED"
    receipt = adapter.patch_attempt_receipt()
    rows = receipt["patch_agent_loop"]["behavior_evaluations"]
    assert len(client.requests) == 4
    assert all(row["code_revision"]["same_materialized_code"] for row in rows)
    assert rows[0]["materialized_code_identity"]["baseline_sha256"] != rows[0]["materialized_code_identity"]["code_sha256"]
    feedback = next(m.content for m in client.requests[2].messages if isinstance(m.content, dict)
                    and m.content.get("message_type") == "patch_behavior_correction")
    assert feedback["validator_feedback"]["code_revision"]["same_materialized_code"]
    assert "exactly the same as the known failed version" in feedback["required_action"]
    if reuse and not change_environment:
        assert len(oracle.contexts) == 1
        assert rows[1]["execution_origin"] == "reused" and rows[1]["callback_invoked"] is False
        assert rows[1]["reused_from_report_ref"] == oracle.reports[0]["report_ref"]
        old = Path(oracle.reports[0]["report_ref"]["path"])
        assert hashlib.sha256(old.read_bytes()).hexdigest() == oracle.reports[0]["report_ref"]["sha256"]
        assert rows[1]["generated_changes_sha256"] != rows[0]["generated_changes_sha256"]
        assert rows[1]["materialized_code_identity"] == rows[0]["materialized_code_identity"]
    else:
        assert len(oracle.contexts) == 2
        assert rows[1]["execution_origin"] == "executed"


def test_first_output_passes_without_forcing_inspection_or_failure(tmp_path):
    class DirectClient(_PatchAgentTurnClient):
        def complete_turn(self, request):
            self.requests.append(request)
            generator = _PatchAgentTurnClient()
            generator.requests = [None]  # Reuse its synthetic complete-output builder only.
            return generator.complete_turn(request)
    inputs = _inputs(tmp_path)
    client = DirectClient()
    oracle = _BehaviorOracle(tmp_path / "verification")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(require_source_inspection=False,
        finalize_after_first_observation=False, enable_supporting_reads=True)
    result = run_fresh_patch_continuation(_patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    assert result.status == "terminal", result.to_dict()
    assert len(client.requests) == len(oracle.contexts) == 1
    assert adapter.patch_attempt_receipt()["patch_agent_loop"]["tool_rounds_used"] == 0


@pytest.mark.parametrize("finalize,byte_limit", [(False, 32768), (True, 32768), (False, 20)])
def test_failure_capacity_counts_prior_correction_reads_and_actual_policy(tmp_path, finalize, byte_limit):
    inputs = _inputs(tmp_path)
    adapter = _adapter(inputs, _InvestigatingClient(), _BehaviorOracle(tmp_path / "observations"))
    adapter.patch_agent_loop_policy = PatchAgentLoopPolicy(
        finalize_after_first_observation=finalize, max_observation_bytes=byte_limit)
    adapter._receipt["model_call_count"] = 2
    adapter._receipt["patch_agent_loop"] = {
        "tool_rounds_used": 0, "total_observation_bytes": 0, "observation_trace": [],
        "validator_correction": {"execution": {
            "tool_rounds_used": 1, "total_observation_bytes": 100,
            "observation_trace": [{"binding_id": "read-during-header-revision"}],
        }},
    }
    inspector = SimpleNamespace(
        available_read_binding_ids=("read-during-header-revision", "unread"),
        inspect=lambda **_: SimpleNamespace(model_payload_bytes=100))
    feedback = {"exact_final_feedback": "measured observations"}
    capacity = adapter._failure_capacity(inspector, feedback)
    assert "read-during-header-revision" not in capacity["affordable_unread_binding_ids"]
    assert capacity["remaining_binding_reads"] == 2
    assert capacity["read_phase_allowed_by_policy"] is not finalize
    assert capacity["can_read_consume_and_revise"] is (not finalize and byte_limit > 20)
    assert capacity["direct_revision_available"] is (byte_limit > 20)


@pytest.mark.parametrize("policy", [None, [], "invalid-policy", 5])
def test_graph_rejects_malformed_worker_policy_without_crashing(policy):
    assert _valid_patch_agent_loop_receipt({"policy": policy}, model_call_count=1) is False


@pytest.mark.parametrize("origin", ["incomplete", "unknown", "executed"])
def test_passed_behavior_report_cannot_claim_incomplete_execution(tmp_path, origin):
    class OriginOracle(_BehaviorOracle):
        def __call__(self, context):
            report = super().__call__(context)
            report["execution_origin"] = origin
            path = Path(report["report_ref"]["path"])
            persisted = {key: value for key, value in report.items() if key != "report_ref"}
            raw = json.dumps(persisted, sort_keys=True).encode()
            path.write_bytes(raw)
            report["report_ref"] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
            return report

    inputs = _inputs(tmp_path)
    client = _PatchAgentTurnClient()
    oracle = OriginOracle(tmp_path / "verification")
    adapter = _adapter(inputs, client, oracle)
    adapter.enable_recovery_loop = True
    result = run_fresh_patch_continuation(
        _patch_request(inputs), patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace), max_model_calls=5)
    receipt = adapter.patch_attempt_receipt()
    report = receipt["patch_agent_loop"]["behavior_evaluations"][-1]
    if origin == "incomplete":
        assert result.reason == "PATCH_BEHAVIOR_OBSERVATION_INVALID"
        assert result.patch_proposal_artifact is None
        assert report["admission"] == "rejected"
        assert len(oracle.contexts) == 1
    else:
        assert result.status == "terminal", result.to_dict()
        assert report["execution_origin"] == origin
        # Graph admission must also reject an explicitly contradictory report
        # supplied through a different factory, without rejecting legacy unknown.
        loop = deepcopy(receipt["patch_agent_loop"])
        loop["behavior_evaluations"][-1]["execution_origin"] = "incomplete"
        assert _valid_patch_agent_loop_receipt(loop, model_call_count=receipt["model_call_count"]) is False
