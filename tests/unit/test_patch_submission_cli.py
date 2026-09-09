"""Offline public external continuation: strict submission and behavior recovery.

Only HTTP is substituted. Responses and the existing marker evaluator are
synthetic; this does not measure live-model quality or compile a real Mod.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest

from src.mod_agent.external_patch import PATCH_FEEDBACK_DATA_CLASSES
from src.mod_agent.local_entry import _restore_patch_agent_context, _sha256_json
from src.mod_agent.product_executor import SOURCE_DISCLOSURE_DATA_CLASSES
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_external_patch import _consent, _profile, _run
from tests.unit.test_fresh_planning_continuation import _patch_request, _source_hashes
from tests.unit.test_patch_repair_cli import _message_jsons, _public_case
from tests.unit.test_patch_upstream_cli import _UpstreamTransport


class _SubmissionTransport:
    def __init__(self, actions):
        self.actions = actions
        self.calls, self.wires, self.outputs, self.reads = [], [], [], []

    def __call__(self, request):
        assert request.url.scheme == "https" and request.url.host == "dashscope.example"
        assert request.headers["Authorization"] == "Bearer unit-test-secret"
        self.calls.append((request.method, request.url.path))
        if request.method == "GET":
            assert request.url.path == "/api/v1/models"
            return httpx.Response(200, json={"output": {"models": [{"model": "qwen3.6-plus", "provider": "qwen"}],
                "total": 1}}, request=request)
        assert request.url.path == "/compatible-mode/v1/chat/completions"
        self.wires.append(request.content)
        number = len(self.wires)
        assert number <= len(self.actions), "Unexpected extra model send"
        action = self.actions[number - 1]
        payload = json.loads(request.content)
        assert payload["model"] == "qwen3.6-plus" and payload["enable_thinking"] is False
        values = _message_jsons(payload)
        prompt = _restore_patch_agent_context(next(row for _, row in values if "required_change_units" in row))
        assert "PreserveFeedback must remain unchanged." in json.dumps(payload)
        if action in ("read", "read_with_prose"):
            tool = next(row["function"] for row in payload["tools"]
                if row["function"]["name"] == "inspect_plan_binding_source")
            selected = next(value for value in tool["parameters"]["properties"]["binding_id"]["enum"]
                if value not in self.reads)
            self.reads.append(selected)
            message = {"role": "assistant", "content": "Inspecting first." if action == "read_with_prose" else None,
                "tool_calls": [{"id": f"submission-source-{number}", "type": "function",
                    "function": {"name": tool["name"], "arguments": json.dumps({"binding_id": selected})}}]}
            stop = "tool_calls"
        else:
            stop = action if action in ("length", "max_tokens", "max_output_tokens", "incomplete") else "stop"
            output = json.dumps(_UpstreamTransport._patch(prompt, passed=action != "failed"))
            if action == "prose":
                output = "Explanation preceding the requested JSON.\n" + output
            if stop != "stop":
                output = '{"changes":['
            self.outputs.append(output)
            message = {"role": "assistant", "content": output}
        return httpx.Response(200, json={"id": f"submission-{number}", "model": "qwen3.6-plus",
            "choices": [{"message": message, "finish_reason": stop}],
            "usage": {"prompt_tokens": 250, "completion_tokens": 60}}, request=request)


def _install(monkeypatch, actions):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-secret")
    handler = _SubmissionTransport(actions)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No real external model or network is allowed.")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)
    return handler


def _case(tmp_path, *, turns=5):
    return _public_case(tmp_path, selected_policy=asdict(PatchAgentLoopPolicy(
        max_total_model_turns=turns, max_tool_rounds=3, max_observation_bytes=32768,
        finalize_after_first_observation=False, require_source_inspection=False,
        enable_supporting_reads=True, allow_upstream_request=True, allow_batched_reads=True,
    )))


def _receipt(result):
    return json.loads(Path(result.attempt_receipt["path"]).read_text())["factory_receipt"]


def _profile_json():
    return replace(_profile(), output_format_policy="json_when_patch_submission_allowed")


def test_public_external_format_then_behavior_recovery_reaches_original_review_and_dry_run(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["read", "prose", "failed", "read", "passed"])
    before = _source_hashes(case.inputs.workspace)

    result = _run(case, profile, _consent(profile))

    assert result.status == "terminal", result.to_dict()
    assert result.execution_counts["model"] == len(transport.wires) == 5
    assert result.execution_counts["review"] == result.execution_counts["dry_run"] == 1
    assert result.execution_counts["apply"] == result.execution_counts["build"] == result.execution_counts["runtime"] == 0
    assert len(transport.reads) == 2 and _source_hashes(case.inputs.workspace) == before
    receipt = _receipt(result)
    loop = receipt["patch_agent_loop"]
    assert [row["status"] for row in loop["submission_trace"]] == ["rejected", "accepted"]
    rejected = loop["submission_trace"][0]
    assert rejected["turn_index"] == 2 and rejected["consumed_in_model_turn"] == 3
    assert rejected["feedback_queued"] and rejected["feedback_in_request"] and rejected["followup_response_observed"]
    assert rejected["feedback_payload_bytes"] > 0 and "feedback_sent" not in rejected
    correction = loop["behavior_correction"]["execution"]
    capacity = loop["recovery_capacity_at_failure"]
    assert capacity["remaining_model_turns"] == 2 and capacity["remaining_binding_reads"] == 2
    assert capacity["remaining_observation_bytes_after_feedback"] > 0 and capacity["can_read_consume_and_revise"] is True
    assert [row["status"] for row in correction["submission_trace"]] == ["accepted"]
    assert [row["status"] for row in loop["behavior_evaluations"]] == ["behavior_failed", "passed"]
    assert all(row["execution_origin"] == "executed" for row in loop["behavior_evaluations"])
    assert len(list(case.reports.glob("report-*.json"))) == 2
    wires = [json.loads(raw) for raw in transport.wires]
    format_feedback = next(row for _, row in _message_jsons(wires[2]) if row.get("message_type") == "patch_submission_feedback")
    assert format_feedback["response_sha256"] == hashlib.sha256(transport.outputs[0].encode()).hexdigest()
    assert format_feedback["code_validation_performed"] is False
    assert any(row["role"] == "assistant" and row.get("content") == transport.outputs[0] for row in wires[2]["messages"])
    assert any(row["role"] == "assistant" and row.get("content") == transport.outputs[1] for row in wires[3]["messages"])
    behavior_feedback = next(row for _, row in _message_jsons(wires[3]) if row.get("message_type") == "patch_behavior_correction")
    assert behavior_feedback["validator_feedback"]["observations"][0]["check_id"] == "cli_synthetic_repair_marker"
    assert len([row for row in wires[2]["messages"] if row["role"] == "tool"]) == 1
    assert len([row for row in wires[4]["messages"] if row["role"] == "tool"]) == 2
    assert all(row.get("tool_call_id") for row in wires[4]["messages"] if row["role"] == "tool")
    admitted = [Path(row["path"]).read_text(encoding="utf-8") for row in receipt["model_responses"]]
    assert transport.outputs[0] not in admitted
    assert admitted == transport.outputs[1:]
    retained = json.loads(Path(receipt["worker_turns"][1]["response_ref"]["path"]).read_text())
    assert retained["content"] == transport.outputs[0]
    for wire, sent in zip(transport.wires, receipt["external_provider_requests"], strict=True):
        assert sent["request_identity"]["provider_body_sha256"] == hashlib.sha256(wire).hexdigest()
        assert set(PATCH_FEEDBACK_DATA_CLASSES) <= set(sent["requested_data_classes"])
    for turn in receipt["worker_turns"]:
        raw = Path(turn["request_ref"]["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == turn["request_ref"]["sha256"]
        assert _sha256_json(json.loads(raw)) == turn["request_sha256"]


def test_public_external_behavior_revision_corrects_format_then_reads_with_same_remaining_budget(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["read", "failed", "prose", "read", "passed"])
    before = _source_hashes(case.inputs.workspace)

    result = _run(case, profile, _consent(profile))

    assert result.status == "terminal", result.to_dict()
    assert result.execution_counts["model"] == len(transport.wires) == 5
    assert result.execution_counts["review"] == result.execution_counts["dry_run"] == 1
    assert result.execution_counts["apply"] == result.execution_counts["build"] == result.execution_counts["runtime"] == 0
    assert _source_hashes(case.inputs.workspace) == before and len(transport.reads) == 2
    receipt = _receipt(result)
    loop = receipt["patch_agent_loop"]
    assert [row["status"] for row in loop["submission_trace"]] == ["accepted"]
    capacity = loop["recovery_capacity_at_failure"]
    assert capacity["remaining_model_turns"] == 3 and capacity["remaining_binding_reads"] == 2
    assert capacity["remaining_observation_bytes_after_feedback"] > 0
    correction = loop["behavior_correction"]["execution"]
    assert correction["model_turns_used"] == loop["behavior_correction"]["model_call_count"] == 3
    assert correction["tool_rounds_used"] == loop["tool_rounds_used"] == 1
    assert [row["status"] for row in correction["submission_trace"]] == ["rejected", "accepted"]
    rejected, accepted = correction["submission_trace"]
    assert rejected["turn_index"] == 3 and accepted["turn_index"] == 5
    assert rejected["feedback_in_request"] and rejected["followup_response_observed"]
    assert rejected["consumed_in_model_turn"] == 4 and rejected["feedback_payload_bytes"] > 0
    assert [row["status"] for row in loop["behavior_evaluations"]] == ["behavior_failed", "passed"]
    assert len(list(case.reports.glob("report-*.json"))) == 2
    final = json.loads(transport.wires[-1])
    assert any(row["role"] == "assistant" and row.get("content") == transport.outputs[0]
        for row in final["messages"])
    assert any(row["role"] == "assistant" and row.get("content") == transport.outputs[1]
        for row in final["messages"])
    values = _message_jsons(final)
    behavior = next(row for _, row in values if row.get("message_type") == "patch_behavior_correction")
    assert behavior["validator_feedback"]["observations"][0]["check_id"] == "cli_synthetic_repair_marker"
    submission = next(row for _, row in values if row.get("message_type") == "patch_submission_feedback")
    assert submission["response_sha256"] == hashlib.sha256(transport.outputs[1].encode()).hexdigest()
    assert submission["code_validation_performed"] is False
    assert len([row for row in final["messages"] if row["role"] == "tool"]) == 2
    assert "PreserveFeedback must remain unchanged." in json.dumps(final)
    assert [Path(row["path"]).read_text(encoding="utf-8") for row in receipt["model_responses"]] == [
        transport.outputs[0], transport.outputs[2]]
    for turn in receipt["worker_turns"]:
        raw = Path(turn["request_ref"]["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == turn["request_ref"]["sha256"]
        assert _sha256_json(json.loads(raw)) == turn["request_sha256"]


@pytest.mark.parametrize("actions", [["passed"], ["read_with_prose", "passed"]])
def test_valid_submission_and_tool_text_do_not_force_format_retry(tmp_path, monkeypatch, actions):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, actions)
    result = _run(case, profile, _consent(profile))
    assert result.status == "terminal", result.to_dict()
    assert len(transport.wires) == len(actions)
    assert [row["status"] for row in _receipt(result)["patch_agent_loop"]["submission_trace"]] == ["accepted"]
    assert not any(row.get("message_type") == "patch_submission_feedback"
        for raw in transport.wires for _, row in _message_jsons(json.loads(raw)))


@pytest.mark.parametrize("stop", ["length", "max_tokens", "max_output_tokens", "incomplete"])
def test_incomplete_external_output_stops_without_submission_retry_or_verifier(tmp_path, monkeypatch, stop):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, [stop])
    result = _run(case, profile, _consent(profile))
    assert result.status != "terminal" and len(transport.wires) == 1
    receipt = _receipt(result)
    assert receipt["patch_agent_loop"]["termination"]["code"] == "PATCH_AGENT_RESPONSE_INCOMPLETE"
    assert receipt["patch_agent_loop"]["submission_trace"][0]["status"] == "incomplete"
    assert receipt["model_response"] is None and not receipt["model_responses"]
    assert not list(case.reports.glob("report-*.json"))


def test_initial_submission_feedback_requires_existing_feedback_disclosure_before_second_send(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["prose"])
    initial = replace(_patch_request(case.inputs), attempt_id="initial-format-feedback-unapproved")
    result = _run(case, profile, _consent(profile, feedback=False), request=initial)
    assert result.status != "terminal" and len(transport.wires) == 1, result.to_dict()
    receipt = _receipt(result)
    assert receipt["external_provider_requests"][0]["requested_data_classes"] == list(SOURCE_DISCLOSURE_DATA_CLASSES)
    stopped = receipt["patch_agent_loop"]["termination"]
    assert stopped["code"] == "PATCH_AGENT_PROVIDER_TURN_FAILED"
    assert stopped["provider_diagnostic"]["failure_boundary"] == "external_patch_admission"
    assert stopped["provider_diagnostic"]["provider_request_started"] is False
    rejection = receipt["patch_agent_loop"]["submission_trace"][0]
    assert rejection["feedback_queued"] and rejection["feedback_in_request"]
    assert rejection["followup_response_observed"] is False
    assert receipt["model_response"] is None and not list(case.reports.glob("report-*.json"))


def test_initial_submission_feedback_approved_wire_and_record_have_same_data_classes(tmp_path, monkeypatch):
    case = _case(tmp_path)
    profile = _profile_json()
    transport = _install(monkeypatch, ["prose", "passed"])
    initial = replace(_patch_request(case.inputs), attempt_id="initial-format-feedback-approved")
    result = _run(case, profile, _consent(profile), request=initial)
    assert result.status == "terminal", result.to_dict()
    sent = _receipt(result)["external_provider_requests"]
    assert sent[0]["requested_data_classes"] == list(SOURCE_DISCLOSURE_DATA_CLASSES)
    assert sent[1]["requested_data_classes"] == [*SOURCE_DISCLOSURE_DATA_CLASSES, *PATCH_FEEDBACK_DATA_CLASSES]
    assert any(row.get("message_type") == "patch_submission_feedback" for _, row in _message_jsons(json.loads(transport.wires[1])))
    assert sent[1]["request_identity"]["provider_body_sha256"] == hashlib.sha256(transport.wires[1]).hexdigest()


def test_format_correction_cannot_spend_model_turns_reserved_for_behavior_repair(tmp_path, monkeypatch):
    case = _case(tmp_path, turns=3)
    profile = _profile_json()
    transport = _install(monkeypatch, ["prose"])
    initial = replace(_patch_request(case.inputs), attempt_id="fresh-format-reserved-for-repair")
    result = _run(case, profile, _consent(profile), request=initial)
    assert result.status != "terminal" and len(transport.wires) == 1
    receipt = _receipt(result)
    loop = receipt["patch_agent_loop"]
    assert loop["termination"]["code"] == "PATCH_AGENT_SUBMISSION_CORRECTION_BUDGET_EXHAUSTED"
    assert loop["submission_trace"][0]["feedback_queued"] is False
    assert receipt["model_response"] is None and not receipt["model_responses"]
    assert not list(case.reports.glob("report-*.json"))


def test_bound_repair_can_correct_format_without_a_second_fresh_reservation(tmp_path, monkeypatch):
    case = _case(tmp_path, turns=3)
    profile = _profile_json()
    transport = _install(monkeypatch, ["prose", "passed"])
    result = _run(case, profile, _consent(profile))
    assert result.status == "terminal", result.to_dict()
    assert len(transport.wires) == 2
    loop = _receipt(result)["patch_agent_loop"]
    assert loop["submission_trace"][0]["feedback_queued"] is True
    assert loop["behavior_evaluations"][-1]["status"] == "passed"
