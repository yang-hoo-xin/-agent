"""Public upstream return acceptance with synthetic responses at HTTP only.

The existing CLI, provider assembly, source search, Findings, Planning, Patch
worker, evaluator factory, Review and Dry-run all execute their production code.
No response here is real Mod code or evidence of real-model quality.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from src.mod_agent.artifacts import ArtifactRef
from src.mod_agent.cli import main
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    _restore_patch_agent_context,
)
from src.mod_agent.patch_upstream_configuration import PatchUpstreamConfiguration
from src.mod_agent.proposal.patch_agent_loop import (
    PATCH_UPSTREAM_REQUEST_TOOL_NAME,
    PatchAgentLoopPolicy,
)
from tests.unit import test_fresh_planning_continuation as source_fixture
from tests.unit.test_patch_repair_cli import (
    _message_jsons,
    _OfflineOllamaTransport,
    _public_case,
    _sha,
    _source_hashes,
    _write_json,
)


def _case(tmp_path, monkeypatch, *, evidence=False, max_model_calls=5):
    original = source_fixture._write_sources

    def sources(workspace):
        result = original(workspace)
        (result.parent / "SharedState.cs").write_text(
            "public sealed class SharedState\n{\n    public void RefreshSharedState()\n    {\n"
            "        KeepExistingFeedback();\n    }\n}\n", encoding="utf-8")
        return result

    monkeypatch.setattr(source_fixture, "_write_sources", sources)
    policy = PatchAgentLoopPolicy(max_total_model_turns=max_model_calls, max_tool_rounds=6,
        require_source_inspection=False, finalize_after_first_observation=False,
        enable_supporting_reads=True, allow_upstream_request=True, allow_batched_reads=True)
    case = _public_case(tmp_path, selected_policy=asdict(policy))
    factory_source = case.factory.read_text(encoding="utf-8")
    needle = '        report = {"status": "passed" if passed else "behavior_failed",'
    assert factory_source.count(needle) == 1
    factory_source = factory_source.replace(needle,
        '        current_bindings = sorted(row["binding_id"] for row in context["implementation_plan"]["binding_registry"]["edit_bindings"])\n'
        '        assert {row["edit_binding_id"] for row in context["generated_changes"]}.issubset(current_bindings)\n'
        '        report = {"observed_plan_binding_ids": current_bindings, "status": "passed" if passed else "behavior_failed",')
    case.factory.write_text(factory_source, encoding="utf-8")
    case.config["behavior_evaluator"]["factory_ref"]["sha256"] = _sha(case.factory.read_bytes())
    _write_json(case.config_path, case.config)
    profile = {"profile_version": LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        "base_url": "http://127.0.0.1:11434", "model": "qwen3:4b-instruct",
        "context_window": 49152, "output_budget": 4096, "timeout_seconds": 30.0}
    configuration = {"schema_version": "patch_upstream_configuration_v1", "planning_profile": profile,
        "evidence": {"profile": deepcopy(profile), "search_root": "generated_mods/SyntheticMod",
                     "max_additional_queries": 1} if evidence else None}
    path = _write_json(tmp_path / "upstream.json", configuration)
    case.argv.extend(["--patch-upstream-config", str(path)])
    case.upstream_path, case.upstream = path, configuration
    case.evidence = evidence
    return case


class _UpstreamTransport(_OfflineOllamaTransport):
    def __init__(self, root, case, *, planning_stop=False, fail_first=False, planning_timeout=False, direct_pass=False):
        super().__init__(root)
        self.case = case
        self.planning_stop = planning_stop
        self.fail_first = fail_first
        self.upstream_sent = False
        self.planning_sent = False
        self.patch_prompts = []
        self.stage_roles = []
        self.latest_failed_raw = None
        self.new_failure = None
        self.new_failure_ref = None
        self.planning_timeout = planning_timeout
        self.direct_pass = direct_pass

    def __call__(self, request):
        if request.method != "POST" or request.url.path != "/api/chat":
            return super().__call__(request)
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        self.requests.append((request.method, str(request.url)))
        payload = json.loads(request.content)
        self.chat_requests.append((request.content, payload))
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"request-{len(self.chat_requests):03d}.json").write_bytes(request.content)
        decoded = _message_jsons(payload)
        messages = [value for _, value in decoded]
        query = next((value for value in messages if value.get("message_type") == "patch_upstream_evidence_queries"), None)
        findings = next((value for value in messages if value.get("message_type") == "product_requirement_findings"), None)
        planning = next((value for value in messages if "allowed_edit_evidence_ids" in value), None)
        if query is not None:
            self.stage_roles.append("evidence_query")
            assert query["failure_feedback"]["observed_failure"]
            content = {"queries": [{"query": "RefreshSharedState", "requirement_id": query["requirements"][0]["requirement_id"]}]}
        elif findings is not None:
            self.stage_roles.append("evidence_findings")
            old = self.case.inputs.store.read(self.case.request.evidence_pack_ref)["data"]
            old_ids = {item["evidence_id"] for item in old["items"]}
            current_ids = {item["evidence_id"] for item in findings["source_observations"]}
            assert old_ids < current_ids
            new_ids = sorted(current_ids - old_ids)
            assert len(new_ids) == 1
            rows = [{"relation_index": index, **{key: row[key] for key in (
                "relationship", "evidence_ids", "edit_target_evidence_ids", "unresolved_gaps")}}
                for index, row in enumerate(old["requirement_coverage"]["findings"], 1)
                if index in payload["format"]["properties"]["findings"]["items"]["properties"]["relation_index"]["enum"]]
            rows[0]["evidence_ids"] = [*rows[0]["evidence_ids"], *new_ids]
            rows[0]["edit_target_evidence_ids"] = [*rows[0]["edit_target_evidence_ids"], *new_ids]
            content = {"findings": rows}
        elif planning is not None:
            self.stage_roles.append("planning")
            self.planning_sent = True
            if self.planning_timeout:
                raise httpx.ReadTimeout("Synthetic upstream transport timeout.", request=request)
            assert any("observed_failure" in value for value in planning["semantic_feedback"])
            if self.fail_first:
                assert "cli_synthetic_repair_marker" in json.dumps(planning["semantic_feedback"])
            candidate = planning.get("candidate_scope_contract", {}).get("mode") == "candidate_edit_scope"
            content = {"decision": "needs_evidence" if self.planning_stop and not candidate else "select_targets",
                "selected_evidence_ids": [] if self.planning_stop else planning["allowed_edit_evidence_ids"],
                "rationale": "Synthetic task: update the behavior and any newly observed shared state while preserving feedback.",
                ("verification_questions" if candidate else "missing_evidence"):
                    ["Synthetic missing state owner."] if self.planning_stop else []}
        else:
            self.stage_roles.append("patch")
            prompt = _restore_patch_agent_context(next(value for value in messages if "required_change_units" in value))
            self.patch_prompts.append(prompt)
            feedback = next((value for value in reversed(messages) if value.get("message_type") == "patch_behavior_correction"), None)
            if self.direct_pass:
                content = self._patch(prompt, passed=True)
            elif self.fail_first and not self.generated_texts:
                content = self._patch(prompt, passed=False)
                self.latest_failed_raw = json.dumps(content)
            elif not self.upstream_sent:
                if self.fail_first:
                    assert feedback is not None
                    assert feedback["validator_feedback"]["observations"][0]["check_id"] == "cli_synthetic_repair_marker"
                    self.new_failure = deepcopy(feedback["validator_feedback"])
                    checked_file = next(self.case.reports.glob("report-*.json"))
                    self.new_failure_ref = {"path": str(checked_file), "sha256": _sha(checked_file.read_bytes())}
                    assert any(message["role"] == "assistant" and message.get("content") == self.latest_failed_raw
                               for message in payload["messages"])
                tool = next(value["function"] for value in payload["tools"]
                            if value["function"]["name"] == PATCH_UPSTREAM_REQUEST_TOOL_NAME)
                self.upstream_sent = True
                return self._response(request, {"role": "assistant", "content": "", "tool_calls": [{"function": {
                    "name": tool["name"], "arguments": {"required_owner": "evidence" if self.case.evidence else "planning",
                        "reason": "Synthetic failed preservation requires reassessing the shared state owner.",
                        "source_refs": ["binding://edit_binding_001"]}}}]})
            else:
                assert self.planning_sent
                assert "PreserveFeedback must remain unchanged." in json.dumps(payload)
                if self.fail_first:
                    carried = next(value for value in messages if value.get("message_type") == "patch_replanned_context")
                    assert carried["validator_feedback"]["observations"] == self.new_failure["observations"]
                    assert carried["validator_feedback"]["generated_changes_sha256"] == self.new_failure["generated_changes_sha256"]
                    assert any(message["role"] == "assistant" and message.get("content") == self.latest_failed_raw
                               for message in payload["messages"])
                content = self._patch(prompt, passed=True)
            self.generated_texts.append(json.dumps(content))
        return self._response(request, {"role": "assistant", "content": json.dumps(content)})

    def _patch(self, prompt, *, passed):
        marker = "RecordRepairMarker" if passed else "RecordStillMissingMarker"
        return {"changes": [{"edit_binding_id": unit["edit_binding_id"],
            "rationale": "Synthetic transport response; not a real Mod implementation.", "rollback_hint": "Restore the original span.",
            "after_text": source_fixture._fixture_visible_binding_text(
                prompt, unit["edit_binding_id"], self.chat_requests[-1][1]["messages"]).replace(
                "KeepExistingFeedback();", f"KeepExistingFeedback();\n        RecordRuntimeMarker();\n        {marker}();")}
            for unit in prompt["required_change_units"]]}

    @staticmethod
    def _response(request, message):
        return httpx.Response(200, json={"model": "qwen3:4b-instruct", "message": message, "done": True,
            "done_reason": "stop", "prompt_eval_count": 200, "eval_count": 40}, request=request)


def _install(monkeypatch, root, case, **kwargs):
    handler = _UpstreamTransport(root, case, **kwargs)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))

    def forbid(*_args, **_kwargs):
        raise AssertionError("No real network is allowed in this offline public CLI acceptance.")

    monkeypatch.setattr("socket.socket.connect", forbid)
    monkeypatch.setattr("socket.socket.connect_ex", forbid)
    return handler


def _run(case, capsys):
    code = main(case.argv)
    return code, json.loads(capsys.readouterr().out)


def _new_revision(case, kind):
    initial = getattr(case.request, kind + "_ref")
    revisions = case.inputs.store.list_feature_artifact_revisions(initial.feature_id, kind)
    added = [reference for reference in revisions if reference != initial]
    assert len(added) == 1
    return added[0]


def _assert_failed_cache_revalidates_final_refs(case, capsys, handler, result, refs):
    calls = len(handler.requests)
    marker = case.marker.read_bytes()
    code, cached = _run(case, capsys)
    assert code != 0 and cached["first_failure"] == result["first_failure"]
    for ref in refs:
        assert cached[ref.artifact_type + "_artifact"] == asdict(ref)
    assert len(handler.requests) == calls and case.marker.read_bytes() == marker
    for ref in refs:
        path = Path(ref.path)
        original = path.read_bytes()
        document = json.loads(original)
        document["data"]["message"] += " Synthetic final Artifact corruption."
        try:
            _write_json(path, document)
            code, rejected = _run(case, capsys)
            assert code != 0 and rejected["first_failure"]["code"] in {
                "PATCH_CONTINUATION_ARTIFACT_INVALID", "PATCH_CONTINUATION_ANCESTRY_STALE"}
            assert len(handler.requests) == calls and case.marker.read_bytes() == marker
        finally:
            path.write_bytes(original)


def test_public_cli_evidence_replanning_reassembles_new_bindings_and_original_review(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch, evidence=True)
    before = _source_hashes(case.inputs.workspace)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code == 0, result
    assert handler.stage_roles == ["patch", "evidence_query", "evidence_findings", "planning", "patch"]
    assert result["execution_counts"]["model"] == 5
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert result["execution_counts"]["apply"] == result["execution_counts"]["build"] == result["execution_counts"]["runtime"] == 0
    assert len(handler.patch_prompts[0]["required_change_units"]) == 1
    assert len(handler.patch_prompts[-1]["required_change_units"]) == 2
    proposal = case.inputs.store.read(ArtifactRef(**result["patch_proposal_artifact"]))["data"]
    assert len(proposal["diff_intent"]) == 2
    assert proposal["context_pack"]["implementation_plan_hash"] != case.request.implementation_plan_ref.artifact_hash
    report = json.loads(next(case.reports.glob("report-*.json")).read_text())
    assert len(report["observed_plan_binding_ids"]) == 2
    assert report["status"] == "passed"
    assert _source_hashes(case.inputs.workspace) == before
    calls = len(handler.requests)
    marker = case.marker.read_bytes()
    code, cached = _run(case, capsys)
    assert code == 0 and cached["patch_proposal_artifact"] == result["patch_proposal_artifact"]
    assert len(handler.requests) == calls and case.marker.read_bytes() == marker
    case.upstream["planning_profile"]["timeout_seconds"] += 1
    _write_json(case.upstream_path, case.upstream)
    code, changed = _run(case, capsys)
    assert code != 0 and changed["first_failure"]["code"] == "PATCH_CONTINUATION_ATTEMPT_IDENTITY_CONFLICT"
    assert len(handler.requests) == calls and case.marker.read_bytes() == marker
    case.upstream["planning_profile"]["timeout_seconds"] -= 1
    _write_json(case.upstream_path, case.upstream)
    plan_path = Path(result["implementation_plan_artifact"]["path"])
    altered = json.loads(plan_path.read_text())
    altered["data"]["side_effect_boundaries"].append("Synthetic stored Artifact tamper.")
    _write_json(plan_path, altered)
    code, altered_result = _run(case, capsys)
    assert code != 0 and altered_result["status"] != "terminal"
    assert len(handler.requests) == calls and case.marker.read_bytes() == marker


def test_public_cli_current_failed_revision_returns_to_planning_then_same_worker_contract(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    before = _source_hashes(case.inputs.workspace)
    handler = _install(monkeypatch, tmp_path / "wire", case, fail_first=True)
    code, result = _run(case, capsys)
    assert code == 0, result
    assert handler.stage_roles == ["patch", "patch", "planning", "patch"]
    carried = next(value for _, value in _message_jsons(handler.chat_requests[-1][1])
        if value.get("message_type") == "patch_replanned_context")
    assert carried["upstream_request"]["origin"] == "model"
    assert all(carried["upstream_request"]["reason"] not in boundary
        for boundary in handler.patch_prompts[-1]["constraints"])
    assert set(handler.patch_prompts[0]["constraints"]).issubset(handler.patch_prompts[-1]["constraints"])
    assert handler.new_failure is not None
    report = handler.new_failure_ref
    assert _sha(Path(report["path"]).read_bytes()) == report["sha256"]
    assert json.loads(Path(report["path"]).read_text())["status"] == "behavior_failed"
    assert len(list(case.reports.glob("report-*.json"))) == 2
    assert case.marker.read_text().splitlines() == ["constructed"]
    assert len(handler.generated_texts) == 2 and handler.generated_texts[0] != handler.generated_texts[1]
    assert result["execution_counts"]["model"] == 4
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert _source_hashes(case.inputs.workspace) == before


def test_public_cli_empty_candidate_scope_cannot_reuse_old_plan_or_review(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    handler = _install(monkeypatch, tmp_path / "wire", case, planning_stop=True)
    code, result = _run(case, capsys)
    assert code != 0, result
    assert handler.stage_roles == ["patch", "planning"]
    assert result["patch_proposal_artifact"] is None and result["proposal_review_artifact"] is None
    assert result["execution_counts"]["apply"] == 0
    new_plan = _new_revision(case, "implementation_plan")
    assert case.inputs.store.semantic_read_immutable(new_plan)["status"] == "blocked"
    assert result["implementation_plan_artifact"] == asdict(new_plan)
    assert result["evidence_pack_artifact"] == asdict(case.request.evidence_pack_ref)
    _assert_failed_cache_revalidates_final_refs(case, capsys, handler, result, [new_plan])


def test_public_cli_evidence_and_planning_share_original_five_call_budget(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch, evidence=True, max_model_calls=4)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code != 0, result
    assert handler.stage_roles == ["patch", "evidence_query", "evidence_findings", "planning"]
    assert result["patch_proposal_artifact"] is None and result["execution_counts"]["apply"] == 0
    new_plan = _new_revision(case, "implementation_plan")
    new_evidence = _new_revision(case, "evidence_pack")
    assert result["implementation_plan_artifact"] == asdict(new_plan)
    assert result["evidence_pack_artifact"] == asdict(new_evidence)
    _assert_failed_cache_revalidates_final_refs(case, capsys, handler, result, [new_plan, new_evidence])


def test_public_cli_upstream_timeout_consumes_shared_attempt_and_never_retries(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    handler = _install(monkeypatch, tmp_path / "wire", case, planning_timeout=True)
    code, result = _run(case, capsys)
    assert code != 0, result
    assert handler.stage_roles == ["patch", "planning"]
    assert result["execution_counts"]["model"] == 2
    assert result["patch_proposal_artifact"] is None and result["execution_counts"]["apply"] == 0
    journal = json.loads(Path(result["attempt_receipt"]["path"]).read_text())
    failed = [event for event in journal["events"] if event.get("phase") == "patch_upstream_provider_turn"
              and event.get("status") == "failed"]
    assert len(failed) == 1 and failed[0]["shared_model_budget"]["consumed"] == 2


def test_public_cli_configured_upstream_does_not_force_replanning_when_repair_passes(tmp_path, monkeypatch, capsys):
    case = _case(tmp_path, monkeypatch)
    handler = _install(monkeypatch, tmp_path / "wire", case, direct_pass=True)
    code, result = _run(case, capsys)
    assert code == 0, result
    assert handler.stage_roles == ["patch"] and result["execution_counts"]["model"] == 1
    assert result["execution_counts"]["planning"] == 0
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert result["implementation_plan_artifact"] == asdict(case.request.implementation_plan_ref)


@pytest.mark.parametrize("invalid", ["remote_provider", "escape_search_root", "unbound_repair", "missing_recovery"])
def test_public_cli_invalid_upstream_configuration_stops_before_any_http(tmp_path, monkeypatch, capsys, invalid):
    case = _case(tmp_path, monkeypatch, evidence=True)
    if invalid == "remote_provider":
        case.upstream["planning_profile"]["base_url"] = "https://example.com"
    elif invalid == "escape_search_root":
        case.upstream["evidence"]["search_root"] = "../outside"
    elif invalid == "unbound_repair":
        index = case.argv.index("--repair-inputs")
        del case.argv[index:index + 2]
    else:
        case.config["enable_recovery_loop"] = False
        _write_json(case.config_path, case.config)
    _write_json(case.upstream_path, case.upstream)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    code, result = _run(case, capsys)
    assert code != 0 and result["patch_proposal_artifact"] is None
    assert handler.requests == []


def test_upstream_configuration_load_and_assembly_have_no_network_or_factory_execution(tmp_path, monkeypatch):
    case = _case(tmp_path, monkeypatch, evidence=True)
    handler = _install(monkeypatch, tmp_path / "wire", case)
    configuration = PatchUpstreamConfiguration.load(case.upstream_path)
    providers = configuration.assemble(case.request, reserve_model_call=lambda role: None)
    assert providers["planning_target_selection_factory"] is not None
    assert providers["evidence_pack_factory"] is not None
    assert handler.requests == [] and not case.marker.exists()
    assert configuration.reference == {"path": str(case.upstream_path), "sha256": _sha(case.upstream_path.read_bytes())}
