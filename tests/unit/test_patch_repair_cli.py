"""Public Repair CLI acceptance with only the HTTP transport replaced offline.

The selected evaluator is a real hashed fixture file. Its static marker check
and all model responses are synthetic test data, not a Mod implementation or a
claim of live-model quality. Adapter, worker, Graph and serializers stay real.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.mod_agent.cli import main
from src.mod_agent.fresh_planning_continuation import _canonical_sha256
from src.mod_agent.local_entry import _restore_patch_agent_context
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_fresh_planning_continuation import _patch_cli_args, _source_hashes
from tests.unit.test_patch_repair_continuation import _repair_case

_FACTORY_SOURCE = '''import hashlib
import json
import sys
from pathlib import Path

def digest(value):
    return hashlib.sha256(value).hexdigest()

class Evaluator:
    def __init__(self, output_root):
        self.output_root = Path(output_root)
        self.calls = 0

    def verification_identity(self):
        return {"validator_sha256": digest(Path(__file__).read_bytes()),
                "inputs_sha256": digest(b"require RecordRepairMarker();"),
                "environment_sha256": digest(sys.version.encode()),
                "deterministic_reuse_allowed": True}

    def __call__(self, context):
        self.calls += 1
        passed = all("RecordRepairMarker();" in change["patch"]["after_text"]
                     for change in context["generated_changes"])
        report = {"status": "passed" if passed else "behavior_failed",
                  "failure_owner": None if passed else "patch_implementation",
                  "owner_binding_ids": [] if passed else [context["generated_changes"][0]["edit_binding_id"]],
                  "observations": [] if passed else [{"check_id": "cli_synthetic_repair_marker",
                      "input": {"enabled": True}, "expected": {"repair_marker_present": True},
                      "observed": {"repair_marker_present": False}}],
                  "generated_changes_sha256": context["generated_changes_sha256"],
                  "source_snapshot_sha256": context["source_snapshot_sha256"],
                  "materialized_code_identity": context["materialized_code_identity"],
                  "verification_identity": self.verification_identity(),
                  "execution_origin": "executed", "verification_scope": "synthetic static marker check"}
        self.output_root.mkdir(parents=True, exist_ok=True)
        path = self.output_root / ("report-%03d.json" % self.calls)
        raw = json.dumps(report, ensure_ascii=False, sort_keys=True).encode()
        path.write_bytes(raw)
        report["report_ref"] = {"path": str(path), "sha256": digest(raw)}
        return report

def build_evaluator(*, output_root, construction_marker):
    marker = Path(construction_marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.open("a", encoding="utf-8") as stream:
        stream.write("constructed\\n")
    return Evaluator(output_root)
'''


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _public_case(tmp_path):
    inputs, request, parent = _repair_case(tmp_path / "case")
    factory = tmp_path / "selected_evaluator.py"
    factory.write_text(_FACTORY_SOURCE, encoding="utf-8")
    marker = tmp_path / "factory-constructions.txt"
    reports = tmp_path / "verifier-results"
    policy = PatchAgentLoopPolicy(
        max_total_model_turns=4, max_tool_rounds=3,
        finalize_after_first_observation=False, require_source_inspection=False,
        enable_supporting_reads=True, allow_upstream_request=True, allow_batched_reads=True,
    )
    config = {
        "schema_version": "patch_worker_configuration_v1", "policy": asdict(policy),
        "enable_recovery_loop": True,
        "behavior_evaluator": {
            "factory_ref": {"path": str(factory), "sha256": _sha(factory.read_bytes())},
            "factory_name": "build_evaluator",
            "kwargs": {"output_root": str(reports), "construction_marker": str(marker)},
        },
    }
    config_path = _write_json(tmp_path / "worker.json", config)
    repair = {key: asdict(getattr(request, key)) if key in (
        "repair_parent_proposal_ref", "repair_parent_review_ref") else dict(getattr(request, key))
        for key in ("repair_parent_proposal_ref", "repair_parent_review_ref", "repair_failure_report_ref",
                    "repair_parent_response_ref", "repair_parent_attempt_ref")}
    repair_path = _write_json(tmp_path / "repair-inputs.json", repair)
    argv = _patch_cli_args(request)
    argv[argv.index("--ollama-context-window") + 1] = "49152"
    argv.extend(["--patch-worker-config", str(config_path), "--repair-inputs", str(repair_path),
                 "--attempt-id", "public-cli-synthetic-recovery"])
    return SimpleNamespace(inputs=inputs, request=request, parent=parent, argv=argv, config=config,
                           config_path=config_path, repair=repair, repair_path=repair_path,
                           factory=factory, marker=marker, reports=reports)


def _message_jsons(payload):
    values = []
    for message in payload["messages"]:
        try:
            decoded = json.loads(message.get("content") or "null")
        except (TypeError, ValueError):
            continue
        if isinstance(decoded, dict):
            values.append((message["role"], decoded))
    return values


class _OfflineOllamaTransport:
    def __init__(self, root, *, scenario="recover"):
        self.root = root
        self.scenario = scenario
        self.requests = []
        self.chat_requests = []
        self.read_bindings = []
        self.generated_texts = []

    def __call__(self, request):
        self.requests.append((request.method, str(request.url)))
        assert request.url.scheme == "http" and request.url.host == "127.0.0.1" and request.url.port == 11434
        model = "qwen3:4b-instruct"
        if request.method == "GET" and request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{
                "name": model, "model": model, "digest": "a" * 64,
                "modified_at": "2026-09-04T00:00:00Z", "size": 1,
                "details": {"context_length": 262144}, "capabilities": ["completion", "tools"],
            }]}, request=request)
        assert request.method == "POST" and request.url.path == "/api/chat", self.requests
        payload = json.loads(request.content)
        assert payload["model"] == model
        assert payload["stream"] is False and payload["think"] is False
        self.chat_requests.append((request.content, payload))
        number = len(self.chat_requests)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"request-{number:03d}.json").write_bytes(request.content)
        decoded = _message_jsons(payload)
        feedback = [value for _, value in decoded if value.get("message_type") == "patch_behavior_correction"]
        tool_results = [value for role, value in decoded if role == "tool"]
        if self.scenario != "direct_pass" and number in (1, 3):
            if number == 1:
                assert any(value.get("message_type") == "patch_repair_context" for _, value in decoded)
            else:
                assert feedback and tool_results
                assert feedback[-1]["validator_feedback"]["observations"][0]["check_id"] == "cli_synthetic_repair_marker"
                assert any(message["role"] == "assistant" and message.get("content") == self.generated_texts[0]
                           for message in payload["messages"])
            source_tool = next(tool["function"] for tool in payload["tools"]
                               if tool["function"]["name"] == "inspect_plan_binding_source")
            binding = next(value for value in source_tool["parameters"]["properties"]["binding_id"]["enum"]
                           if value not in self.read_bindings)
            self.read_bindings.append(binding)
            message = {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": source_tool["name"], "arguments": {"binding_id": binding}},
            }]}
        else:
            if self.scenario != "direct_pass":
                assert number in (2, 4)
                assert {value["binding_id"] for value in tool_results} == set(self.read_bindings)
                if number == 4:
                    assert feedback and len(tool_results) == 2
            else:
                assert number == 1
            prompt = next(value for _, value in decoded if "required_change_units" in value)
            prompt = _restore_patch_agent_context(prompt)
            repaired = self.scenario == "direct_pass" or (self.scenario == "recover" and number == 4)
            marker = "RecordRepairMarker" if repaired else (
                "RecordTemporaryMarker" if number == 2 else "RecordAnotherMissingMarker")
            changes = [{
                "edit_binding_id": unit["edit_binding_id"], "rationale": "Synthetic CLI transport fixture.",
                "rollback_hint": "Restore the original exact span.",
                "after_text": prompt["edit_binding_contexts"][unit["edit_binding_id"]]["source_excerpt"].replace(
                    "KeepExistingFeedback();", "KeepExistingFeedback();\n        RecordRuntimeMarker();\n        " + marker + "();"),
            } for unit in prompt["required_change_units"]]
            content = json.dumps({"changes": changes})
            self.generated_texts.append(content)
            message = {"role": "assistant", "content": content}
        return httpx.Response(200, json={"model": model, "message": message, "done": True,
                                        "done_reason": "stop", "prompt_eval_count": 200, "eval_count": 40},
                              request=request)


def _install_transport(monkeypatch, root, *, scenario="recover"):
    handler = _OfflineOllamaTransport(root, scenario=scenario)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    def forbid_socket(*_args, **_kwargs):
        raise AssertionError("No real network connection is allowed in this CLI acceptance.")
    monkeypatch.setattr("socket.socket.connect", forbid_socket)
    monkeypatch.setattr("socket.socket.connect_ex", forbid_socket)
    return handler


def _run(case, capsys):
    code = main(case.argv)
    captured = capsys.readouterr()
    return code, json.loads(captured.out)


def test_public_repair_cli_runs_read_generate_fail_read_revise_and_exact_review(tmp_path, monkeypatch, capsys):
    case = _public_case(tmp_path)
    before = _source_hashes(case.inputs.workspace)
    handler = _install_transport(monkeypatch, tmp_path / "wire")
    code, public = _run(case, capsys)
    assert code == 0, public
    assert public["status"] == "terminal"
    assert public["execution_counts"]["model"] == 4
    assert public["execution_counts"]["review"] == public["execution_counts"]["dry_run"] == 1
    assert public["execution_counts"]["apply"] == public["execution_counts"]["build"] == public["execution_counts"]["runtime"] == 0
    assert public["patch_proposal_artifact"]["artifact_hash"] != case.parent.patch_proposal_artifact["artifact_hash"]
    assert _source_hashes(case.inputs.workspace) == before
    journal = json.loads(Path(public["attempt_receipt"]["path"]).read_text())
    factory = journal["factory_receipt"]
    assert factory["adapter"] == "LocalOllamaInitialPatchAdapter"
    assert factory["behavior_evaluator_configuration"]["configuration_ref"] == {
        "path": str(case.config_path), "sha256": _sha(case.config_path.read_bytes()),
    }
    assert factory["behavior_evaluator_configuration"]["factory_ref"] == case.config["behavior_evaluator"]["factory_ref"]
    assert factory["behavior_evaluator_configuration"]["kwargs_sha256"] == _canonical_sha256(
        case.config["behavior_evaluator"]["kwargs"])
    assert journal["worker_configuration_ref"] == factory["behavior_evaluator_configuration"]["configuration_ref"]
    assert journal["worker_profile_sha256"] == _canonical_sha256(factory["profile"])
    assert len(handler.chat_requests) == 4 and len(handler.read_bindings) == 2
    assert len(list(case.reports.glob("report-*.json"))) == 2
    assert case.marker.read_text().splitlines() == ["constructed"]
    loop = factory["patch_agent_loop"]
    assert loop["tool_rounds_used"] == loop["behavior_correction"]["execution"]["tool_rounds_used"] == 1
    assert loop["behavior_correction"]["model_call_count"] == 2
    assert [row["status"] for row in loop["behavior_evaluations"]] == ["behavior_failed", "passed"]
    assert all(row["execution_origin"] == "executed" for row in loop["behavior_evaluations"])
    capacity = loop["recovery_capacity_at_failure"]
    assert capacity["can_read_consume_and_revise"] is True
    assert capacity["remaining_model_turns"] == 2 and capacity["remaining_binding_reads"] >= 1
    first_messages = handler.chat_requests[0][1]["messages"]
    final_messages = handler.chat_requests[-1][1]["messages"]
    assert final_messages[:2] == first_messages[:2]
    assert "PreserveFeedback must remain unchanged." in json.dumps(final_messages)
    for turn, (wire, _) in zip(factory["worker_turns"], handler.chat_requests, strict=True):
        assert turn["provider_diagnostic"]["request_identity"]["provider_body_sha256"] == _sha(wire)
        assert turn["response_origin"] == "live_provider_response"


def test_public_repair_cli_first_draft_can_pass_without_forced_read_and_cached_attempt_sends_nothing(tmp_path, monkeypatch, capsys):
    case = _public_case(tmp_path)
    handler = _install_transport(monkeypatch, tmp_path / "wire", scenario="direct_pass")
    code, first = _run(case, capsys)
    assert code == 0, first
    assert len(handler.chat_requests) == 1 and handler.read_bindings == []
    assert len(list(case.reports.glob("report-*.json"))) == 1
    count = len(handler.requests)
    marker = case.marker.read_bytes()
    code, resumed = _run(case, capsys)
    assert code == 0, resumed
    assert len(handler.requests) == count
    assert case.marker.read_bytes() == marker
    assert resumed["patch_proposal_artifact"] == first["patch_proposal_artifact"]


def test_public_repair_cli_persistent_failure_stops_without_apply(tmp_path, monkeypatch, capsys):
    case = _public_case(tmp_path)
    before = _source_hashes(case.inputs.workspace)
    handler = _install_transport(monkeypatch, tmp_path / "wire", scenario="persistent_failure")
    code, public = _run(case, capsys)
    assert code != 0
    assert public["reason"] == "PATCH_BEHAVIOR_CORRECTION_FAILED"
    assert len(handler.chat_requests) == 4
    assert public["patch_proposal_artifact"] is None
    assert public["execution_counts"]["apply"] == 0
    assert public["product_source_writes_performed"] is False
    assert _source_hashes(case.inputs.workspace) == before


@pytest.mark.parametrize("invalid", ["worker_schema", "factory_hash", "repair_field", "repair_hash"])
def test_public_repair_cli_invalid_config_or_refs_stop_before_transport(tmp_path, monkeypatch, capsys, invalid):
    case = _public_case(tmp_path)
    if invalid == "worker_schema":
        del case.config["policy"]
        _write_json(case.config_path, case.config)
    elif invalid == "factory_hash":
        case.config["behavior_evaluator"]["factory_ref"]["sha256"] = "0" * 64
        _write_json(case.config_path, case.config)
    elif invalid == "repair_field":
        del case.repair["repair_parent_attempt_ref"]
        _write_json(case.repair_path, case.repair)
    else:
        case.repair["repair_failure_report_ref"]["sha256"] = "0" * 64
        _write_json(case.repair_path, case.repair)
    handler = _install_transport(monkeypatch, tmp_path / "wire")
    code, public = _run(case, capsys)
    assert code != 0, public
    assert handler.requests == []
    assert not case.marker.exists()
    assert public["execution_counts"]["model"] == 0
