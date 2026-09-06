"""Public CLI qualification of covered-window reuse with a synthetic transport.

Only HTTP transport is substituted. Product binding, worker, serializers,
materialization, the selected verifier file, Review and Dry-run stay real.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import httpx

from src.mod_agent.cli import main
from src.mod_agent.local_entry import _restore_patch_agent_context
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    expand_patch_source_observations,
)
from tests.unit.test_patch_repair_cli import (
    _five_binding_repair_case,
    _message_jsons,
    _OfflineOllamaTransport,
    _public_case,
    _sha,
    _source_hashes,
)


def _coverage_case(tmp_path):
    methods = {
        "Behavior.cs": (
            "public sealed class Behavior\n{\n    public void ChangeMarkerA()\n    {\n"
            + "".join(f"        // SYNTHETIC_RETAINED_CONTEXT_{line:02d}\n" for line in range(70))
            + "        KeepExistingFeedback();\n    }\n"
            + "    public void ChangeMarkerB()\n    {\n        KeepExistingFeedback();\n    }\n"
            + "    public void ChangeMarkerC()\n    {\n        KeepExistingFeedback();\n    }\n}\n"
        ),
        "StateD.cs": "public sealed class StateD\n{\n    public void ChangeMarkerD()\n    {\n        KeepExistingFeedback();\n    }\n}\n",
        "StateE.cs": "public sealed class StateE\n{\n    public void ChangeMarkerE()\n    {\n        KeepExistingFeedback();\n    }\n}\n",
        "Configuration.cs": 'public sealed class Configuration\n{\n    public const string ConfigKey = "Marker.Enabled";\n}\n',
        "Preservation.cs": "public sealed class Preservation\n{\n    public void PreserveFeedback() { }\n}\n",
    }
    prepared = _five_binding_repair_case(tmp_path / "case", source_files=methods)
    policy = PatchAgentLoopPolicy(
        max_total_model_turns=5, max_tool_rounds=6, max_observation_bytes=32768,
        context_radius_lines=64, finalize_after_first_observation=False,
        require_source_inspection=False, enable_supporting_reads=True,
        allow_upstream_request=True, allow_batched_reads=True,
        reuse_covered_source_observations=True,
    )
    case = _public_case(tmp_path, preparation=prepared, selected_policy=asdict(policy))
    plan = case.inputs.store.read(case.request.implementation_plan_ref)["data"]
    inspector = PlanBoundSourceInspector(
        workspace_root=case.inputs.workspace, implementation_plan=plan, policy=policy,
        evidence_pack=case.inputs.store.read(case.request.evidence_pack_ref)["data"],
    )
    ordered = sorted(plan["binding_registry"]["edit_bindings"],
                     key=lambda row: (row["canonical_target_path"], row["target_span"]["start_line"]))
    case.initial_reads = [row["binding_id"] for row in ordered]
    assert len(case.initial_reads) == 5
    supporting = [key for key in inspector.available_read_binding_ids if key not in case.initial_reads]
    assert len(supporting) == 2
    case.followup_reads = [case.initial_reads[index] for index in (0, 1, 3)] + supporting
    case.expected = {
        binding: inspector.inspect(binding_id=binding, observation_id=f"fixture-{index}").model_view()
        for index, binding in enumerate(inspector.available_read_binding_ids)
    }
    first = case.expected[case.initial_reads[0]]
    for binding in case.initial_reads[1:3]:
        observed = case.expected[binding]
        assert observed["source_hash"] == first["source_hash"]
        assert first["excerpt_span"]["start_line"] < observed["excerpt_span"]["start_line"]
        assert observed["excerpt_span"]["end_line"] <= first["excerpt_span"]["end_line"]
    case.policy = policy
    return case


class _CoveredTransport(_OfflineOllamaTransport):
    def __init__(self, root, case, *, direct=False, fail_before_consumption=False, no_improvement=False):
        super().__init__(root)
        self.case = case
        self.direct = direct
        self.fail_before_consumption = fail_before_consumption
        self.no_improvement = no_improvement

    def __call__(self, request):
        if request.method != "POST" or request.url.path != "/api/chat":
            return super().__call__(request)
        assert request.url.scheme == "http" and request.url.host == "127.0.0.1" and request.url.port == 11434
        self.requests.append((request.method, str(request.url)))
        payload = json.loads(request.content)
        self.chat_requests.append((request.content, payload))
        number = len(self.chat_requests)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"request-{number:03d}.json").write_bytes(request.content)
        if self.fail_before_consumption and number == 2:
            raise httpx.ConnectError("Synthetic transport failure before any model response.", request=request)
        decoded = _message_jsons(payload)
        feedback = [value for _, value in decoded if value.get("message_type") == "patch_behavior_correction"]
        if not self.direct and number in (1, 3):
            if number == 1:
                assert all(role != "tool" for role, _ in decoded)
                state = next(value for _, value in reversed(decoded)
                             if value.get("message_type") == "patch_agent_loop_state")
                assert state["prior_observations"] == []
                selected = self.case.initial_reads
            else:
                assert feedback
                assert feedback[-1]["validator_feedback"]["observations"][0]["check_id"] == "cli_synthetic_repair_marker"
                assert any(message["role"] == "assistant" and message.get("content") == self.generated_texts[0]
                           for message in payload["messages"])
                selected = self.case.followup_reads
            tool = next(item["function"] for item in payload["tools"]
                        if item["function"]["name"] == "inspect_plan_binding_source")
            assert set(selected).issubset(tool["parameters"]["properties"]["binding_id"]["enum"])
            self.read_bindings.extend(selected)
            message = {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": tool["name"], "arguments": {"binding_id": binding}}}
                for binding in selected
            ]}
        else:
            if self.direct:
                assert number == 1
            else:
                assert number in (2, 4)
                tools = [value for role, value in decoded if role == "tool"]
                assert len(tools) == (5 if number == 2 else 10)
                expanded = expand_patch_source_observations(tools)
                for observation in expanded:
                    assert observation["excerpt"] == self.case.expected[observation["binding_id"]]["excerpt"]
                if number == 4:
                    assert feedback
            prompt = _restore_patch_agent_context(next(value for _, value in decoded if "required_change_units" in value))
            marker = "RecordRepairMarker" if self.direct or (number == 4 and not self.no_improvement) else "RecordTemporaryMarker"
            changes = [{
                "edit_binding_id": unit["edit_binding_id"], "rationale": "Synthetic covered-source CLI example.",
                "rollback_hint": "Restore original exact source.",
                "after_text": prompt["edit_binding_contexts"][unit["edit_binding_id"]]["source_excerpt"].replace(
                    "KeepExistingFeedback();", "KeepExistingFeedback();\n        RecordRuntimeMarker();\n        " + marker + "();"),
            } for unit in prompt["required_change_units"]]
            content = json.dumps({"changes": changes})
            self.generated_texts.append(content)
            message = {"role": "assistant", "content": content}
        return httpx.Response(200, json={
            "model": "qwen3:4b-instruct", "message": message, "done": True,
            "done_reason": "stop", "prompt_eval_count": 200, "eval_count": 40,
        }, request=request)


def _install(monkeypatch, root, case, **kwargs):
    handler = _CoveredTransport(root, case, **kwargs)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))

    def forbid_socket(*_args, **_kwargs):
        raise AssertionError("This acceptance permits no real network.")

    monkeypatch.setattr("socket.socket.connect", forbid_socket)
    monkeypatch.setattr("socket.socket.connect_ex", forbid_socket)
    return handler


def _invoke(case, capsys):
    code = main(case.argv)
    public = json.loads(capsys.readouterr().out)
    journal = json.loads(Path(public["attempt_receipt"]["path"]).read_text(encoding="utf-8"))
    return code, public, journal


def test_public_cli_reuses_covered_windows_across_failure_without_resetting_shared_budget(tmp_path, monkeypatch, capsys):
    case = _coverage_case(tmp_path)
    before = _source_hashes(case.inputs.workspace)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, public, journal = _invoke(case, capsys)
    assert code == 0, public
    assert public["execution_counts"]["model"] == 4
    assert public["execution_counts"]["review"] == public["execution_counts"]["dry_run"] == 1
    assert public["execution_counts"]["apply"] == 0
    factory = journal["factory_receipt"]
    initial = factory["patch_agent_loop"]
    correction = initial["behavior_correction"]["execution"]
    assert initial["read_accounting_version"] == correction["read_accounting_version"] == "new_source_window_v2"
    assert initial["dispatched_binding_reads"] == correction["dispatched_binding_reads"] == 5
    assert initial["tool_rounds_used"] == 3 and initial["reused_source_observations"] == 2
    assert correction["tool_rounds_used"] == 2 and correction["reused_source_observations"] == 3
    assert [item["read_cost"] for item in initial["observation_trace"]] == [1, 0, 0, 1, 1]
    assert [item["read_cost"] for item in correction["observation_trace"]] == [0, 0, 0, 1, 1]
    assert all(item["admitted_to_model"] is True for item in [*initial["observation_trace"], *correction["observation_trace"]])
    capacity = initial["recovery_capacity_at_failure"]
    assert capacity["can_read_consume_and_revise"] is True
    assert capacity["can_read_new_source_consume_and_revise"] is True
    assert capacity["remaining_model_turns"] >= 2
    assert capacity["remaining_binding_reads"] == 3
    estimated = {item["binding_id"]: item for item in capacity["source_read_cost_estimates"]}
    assert [estimated[binding]["read_cost"] for binding in case.followup_reads] == [0, 0, 0, 1, 1]
    assert capacity["remaining_observation_bytes_after_feedback"] > 0
    assert [item["status"] for item in initial["behavior_evaluations"]] == ["behavior_failed", "passed"]
    assert len(list(case.reports.glob("report-*.json"))) == 2
    assert factory["model_call_count"] <= case.policy.max_total_model_turns == 5
    assert initial["tool_rounds_used"] + correction["tool_rounds_used"] <= case.policy.max_tool_rounds == 6
    assert initial["total_observation_bytes"] + correction["total_observation_bytes"] < case.policy.max_observation_bytes == 32768
    final_messages = handler.chat_requests[-1][1]["messages"]
    assert final_messages[:2] == handler.chat_requests[0][1]["messages"][:2]
    assert "PreserveFeedback must remain unchanged." in json.dumps(final_messages)
    assert any(message["role"] == "assistant" and message.get("content") == handler.generated_texts[0]
               for message in final_messages)
    final_feedback = next(value for _, value in _message_jsons(handler.chat_requests[-1][1])
                          if value.get("message_type") == "patch_behavior_correction")
    assert final_feedback["validator_feedback"]["observations"] == initial["behavior_evaluations"][0]["observations"]
    final_tools = [value for role, value in _message_jsons(handler.chat_requests[-1][1]) if role == "tool"]
    assert len(final_tools) == 10
    assert any("source_excerpt_span" in value.get("excerpt_ref", {}) for value in final_tools)
    assert len(expand_patch_source_observations(final_tools)) == 10
    for turn, (wire, _) in zip(factory["worker_turns"], handler.chat_requests, strict=True):
        assert turn["provider_diagnostic"]["request_identity"]["provider_body_sha256"] == _sha(wire)
    assert _source_hashes(case.inputs.workspace) == before


def test_public_cli_covered_reuse_policy_still_allows_a_direct_passing_output(tmp_path, monkeypatch, capsys):
    case = _coverage_case(tmp_path)
    handler = _install(monkeypatch, tmp_path / "wire", case, direct=True)
    code, public, journal = _invoke(case, capsys)
    assert code == 0, public
    assert len(handler.chat_requests) == 1 and handler.read_bindings == []
    loop = journal["factory_receipt"]["patch_agent_loop"]
    assert loop["dispatched_binding_reads"] == loop["tool_rounds_used"] == 0
    assert len(loop["behavior_evaluations"]) == 1


def test_new_cli_attempt_does_not_inherit_unconsumed_observations_from_disk(tmp_path, monkeypatch, capsys):
    case = _coverage_case(tmp_path)
    failed_handler = _install(monkeypatch, tmp_path / "failed-wire", case, fail_before_consumption=True)
    code, public, failed_journal = _invoke(case, capsys)
    assert code != 0
    assert len(failed_handler.chat_requests) == 2
    assert public["patch_proposal_artifact"] is None
    observations = failed_journal["factory_receipt"]["patch_agent_loop"]["observation_trace"]
    assert len(observations) == 5
    assert all(item["admitted_to_model"] is False for item in observations)
    case.argv[case.argv.index("--attempt-id") + 1] = "fresh-attempt-after-unconsumed-source"
    handler = _install(monkeypatch, tmp_path / "fresh-wire", case)
    code, public, fresh_journal = _invoke(case, capsys)
    assert code == 0, public
    assert len(handler.chat_requests) == 4
    fresh = fresh_journal["factory_receipt"]["patch_agent_loop"]
    assert fresh["tool_rounds_used"] == 3
    assert fresh["dispatched_binding_reads"] == 5


def test_covered_reads_do_not_turn_an_unchanged_failed_revision_into_success(tmp_path, monkeypatch, capsys):
    case = _coverage_case(tmp_path)
    before = _source_hashes(case.inputs.workspace)
    handler = _install(monkeypatch, tmp_path / "wire", case, no_improvement=True)
    code, public, journal = _invoke(case, capsys)
    assert code != 0
    assert public["reason"] == "PATCH_BEHAVIOR_CORRECTION_FAILED"
    assert public["patch_proposal_artifact"] is None
    assert public["execution_counts"]["apply"] == 0
    assert len(handler.chat_requests) == 4 and len(handler.read_bindings) == 10
    assert handler.generated_texts[0] == handler.generated_texts[1]
    evaluations = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"]
    assert [item["status"] for item in evaluations] == ["behavior_failed", "behavior_failed"]
    assert evaluations[0]["execution_origin"] == "executed"
    assert evaluations[1]["execution_origin"] == "reused"
    assert evaluations[1]["callback_invoked"] is False
    assert evaluations[1]["code_revision"]["same_materialized_code"] is True
    assert evaluations[1]["materialized_code_identity"] == evaluations[0]["materialized_code_identity"]
    assert len(list(case.reports.glob("report-*.json"))) == 1
    assert _source_hashes(case.inputs.workspace) == before
