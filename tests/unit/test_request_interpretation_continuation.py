"""Same-task corrected derivation uses fresh model roles and preserves consumed history."""
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent import initial_findings_continuation as continuation
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence import reassessment
from src.mod_agent.planning import FeatureSpecBuilder, ModPlanningBriefBuilder, RequestPlanner
from src.mod_agent.workflow import graph
from tests.unit.test_dsh_new_project import initialize
from tests.unit.test_dsh_new_project import profile as profile  # noqa: F401
from tests.unit.test_dsh_run_request import _call, _install_execution_boundaries
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401
from tests.unit.test_initial_findings_continuation import _provider_backend


def _ref(path):
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return _ref(path)


def _missing(response, request):
    body = response.json()
    content = json.loads(body["message"]["content"])
    for row in content["findings"]:
        row.update(relationship="missing", evidence_ids=[], edit_target_evidence_ids=[],
                   unresolved_gaps=["Current input lifecycle not understood."])
    body["message"]["content"] = json.dumps(content)
    return httpx.Response(200, request=request, json=body)


def _query(native, payload, request, *, text="Load"):
    content = {"queries": [{"query": text, "metadata_queries": [],
        "gap_ids": [payload["gap_investigation_targets"][0]["gap_id"]],
        "requirement_id": payload["requirements"][0]["requirement_id"],
        "current_fact_needed": "Current lifecycle", "modification_impact": "Binds current source",
        "authorized_source": "target_source"}]}
    return httpx.Response(200, request=request, json={"model": native["model"],
        "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
        "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})


def _at_four(config_path, monkeypatch, capsys):
    config = json.loads(config_path.read_text())
    config["arguments"] += ["--run-id", "revision_run", "--request-id", "revision_request"]
    config["arguments"][config["arguments"].index("--task-model-call-limit") + 1] = "13"
    _write(config_path, config)
    limits = {"requirement_projection": 1, "requirement_findings": 3,
              "planning": 1, "initial_patch": 4, "repair": 4}
    _write(config_path.parent / "limits.json", limits)
    _, _, builds = _install_execution_boundaries(config_path.parent, monkeypatch)
    original_transport = httpx.HTTPTransport.handle_request

    class LegacyPlanner:
        def plan(self, *args, **kwargs):
            return replace(RequestPlanner().plan(*args, **kwargs), request_interpretation={})

    def missing_transport(client, request):
        if request.method == "POST":
            native = json.loads(request.content)
            payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
            if payload.get("message_type") == "initial_findings_evidence_queries":
                return _query(native, payload, request)
            response = original_transport(client, request)
            return _missing(response, request) if payload.get("message_type") == "product_requirement_findings" else response
        return original_transport(client, request)

    def fail_merge(*_):
        raise ValueError("PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT")

    with monkeypatch.context() as old:
        from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
        original_init = StructuredModelRequirementCoverageProvider.__init__
        def historical_init(self, complete_json, **kwargs):
            # 为什么要有它：旧语义修订夹具的原Findings不能因正常入口升级而换成新的native输出协议。
            kwargs["native_findings_contract"] = None
            original_init(self, complete_json, **kwargs)
        old.setattr(StructuredModelRequirementCoverageProvider, "__init__", historical_init)
        old.setattr(graph, "RequestPlanner", LegacyPlanner)
        old.setattr(httpx.HTTPTransport, "handle_request", missing_transport)
        with monkeypatch.context() as broken:
            broken.setattr(reassessment, "merge_reobserved_source_item", fail_merge)
            assert _call(config_path, "make Load record deterministic product diagnostics", monkeypatch) != 0
        original = json.loads(capsys.readouterr().out)
        assert original["model_call_count"] == 3
        root = Path(original["run_root"])
        allocation = config_path.parent / "allocation.json"
        _write(allocation, {"stage_model_call_limits": limits, "max_execution_seconds": 1800,
            "findings_contract_version": "3", "include_downstream_preflight": True,
            "provider_backend": _provider_backend(config_path.parent)})
        args = {"run_root": root, "run_id": original["run_id"],
                "execution_config": config_path, "allocation_config": allocation}
        preview = continuation.preview_initial_findings_execution(**args)
        result = continuation.execute_initial_findings_continuation(**args,
            decision={"decision": "approve", "reviewer": "fixture", "scope_hash": preview["scope_hash"]})
        assert result["status"] == "domain_blocked", result.get("blockers")
        assert result["model_call_count"] == 4
    return args, result, original_transport, builds


def _select_revision(args, result):
    root, temp = args["run_root"], args["execution_config"].parent
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    plan = RequestPlanner().plan(manifest["request"], target_mod=Path(manifest["target_source"]).name)
    brief = ModPlanningBriefBuilder().build(plan, target_game="gtfo").to_artifact_payload()
    payloads = {"request_planning_report": plan.to_artifact_payload(), "mod_planning_brief": brief,
        "feature_spec": FeatureSpecBuilder().build(plan, planning_brief=brief).to_artifact_payload()}
    store = ArtifactStore(temp / "corrected_store")
    references = {}
    upstream = []
    for role, payload in payloads.items():
        ref = store.write(feature_id=plan.feature_id, artifact_type=role, payload=payload, upstream_refs=upstream)
        references[role] = {"path": ref.path, "artifact_hash": ref.artifact_hash}
        upstream.append(ref)
    derivation = _write(temp / "derivation.json", {
        "schema_version": "request_interpretation_revision_v2", "historical_run_id": args["run_id"],
        "unchanged_user_request": True, "model_calls_performed": 0, "product_run_started": False,
        "historical_sources": {role: _ref(Path(result["artifacts"][role])) for role in payloads},
        "corrected_artifacts": references})
    from src.mod_agent import cli
    from src.mod_agent.evidence import requirement_coverage_provider
    config = json.loads(args["execution_config"].read_text())
    parsed = cli.build_parser().parse_args(["run-request", *config["arguments"], "--", manifest["request"]])
    bindings = [_ref(args["execution_config"]), *[_ref(Path(p)) for p in (
        parsed.settings, parsed.stage_model_call_limits, parsed.patch_worker_config) if p]]
    scope = {"run_id": args["run_id"], "request_id": manifest["request_id"], "task_model_call_limit": 13,
        "run_root": str(root), "target_project": manifest["target_source"],
        "source_snapshot_sha256": manifest["source_snapshot_sha256"], "bindings": bindings,
        "dsh_command_timeout_ms": 1800000, "model": {"name": manifest["local_model_identity"]["model"],
            "digest": manifest["local_model_identity"]["digest"], "base_url": manifest["local_model_identity"]["base_url"],
            "context_window": parsed.ollama_context_window, "max_output_tokens": parsed.ollama_max_output_tokens,
            "request_timeout_seconds": parsed.ollama_timeout_seconds}}
    scope_file = temp / "original-scope.json"
    _write(scope_file, {"scope": scope, "scope_sha256": continuation._digest(scope)})
    authorization = temp / "authorization.json"
    _write(authorization, {"approved": True, "scope_file": str(scope_file),
        "scope_sha256": continuation._digest(scope), "model_digest": manifest["local_model_identity"]["digest"]})
    limits = {"requirement_projection": 2, "requirement_findings": 4,
              "planning": 1, "initial_patch": 3, "repair": 3}
    decision = _write(temp / "decision.json", {"run_id": args["run_id"],
        "original_authorization_ref": str(authorization), "prior_budget": result["model_call_budget"],
        "selected_stage_model_call_limits": limits, "task_maximum": 13, "prior_consumed": 4,
        **{key: False for key in ("refund_performed", "history_moved_between_stages", "user_request_changed",
                                 "model_changed", "new_external_or_runtime_effects_authorized")}})
    frozen = _write(temp / "frozen.json", {"shared_production_files_frozen": True,
        "files": [_ref(Path(requirement_coverage_provider.__file__))]})
    allocation = json.loads(args["allocation_config"].read_text())
    allocation.update(stage_model_call_limits=limits, resume_mode="accepted_findings_reassessment_revision",
        request_interpretation_revision={"store_root": str(store.root), "derivation_ref": derivation,
                                        "decision_ref": decision, "frozen_files_ref": frozen})
    _write(args["allocation_config"], allocation)
    return allocation, authorization


@pytest.mark.parametrize("needs_query", [False, True])
def test_normal_advance_consumes_corrected_revision_once(execution_config, monkeypatch, capsys, needs_query):
    args, previous, transport, builds = _at_four(execution_config, monkeypatch, capsys)
    allocation, authorization = _select_revision(args, previous)
    root = args["run_root"]
    frozen = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()
              and (not p.is_relative_to(root / "a") or "r" in p.relative_to(root / "a").parts)}
    roles = []
    new_findings = 0
    def actual_transport(client, request):
        nonlocal new_findings
        if request.method != "POST":
            return transport(client, request)
        native = json.loads(request.content)
        payload = json.loads(next(m["content"] for m in native["messages"] if m["role"] == "user"))
        role = payload.get("message_type")
        roles.append(role)
        if role == "product_requirement_projection":
            assert payload["request_interpretation"]["schema_version"] == "request_interpretation_v2"
        if role == "initial_findings_evidence_queries":
            return _query(native, payload, request, text="Load lifecycle")
        response = transport(client, request)
        if role == "product_requirement_findings":
            new_findings += 1
            if needs_query and new_findings == 1:
                response = _missing(response, request)
        return response
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", actual_transport)
    call = {"execution_config": str(execution_config), "run_id": args["run_id"],
            "allocation_config": str(args["allocation_config"])}
    invalid = deepcopy(allocation)
    invalid["stage_model_call_limits"]["repair"] += 1
    _write(args["allocation_config"], invalid)
    with pytest.raises(ValueError, match="REQUEST_INTERPRETATION_REVISION_DECISION_INVALID"):
        bridge.advance_task(**call)
    _write(args["allocation_config"], allocation)
    auth = authorization.read_bytes()
    _write(authorization, {**json.loads(auth), "approved": False})
    with pytest.raises(ValueError, match="REQUEST_INTERPRETATION_REVISION_AUTHORIZATION_CHANGED"):
        bridge.advance_task(**call)
    authorization.write_bytes(auth)
    original_manifest = root / "run_manifest.json"
    manifest_raw = original_manifest.read_bytes()
    manifest = json.loads(manifest_raw)
    _write(original_manifest, {**manifest, "request": manifest["request"] + " changed"})
    try:
        with pytest.raises(ValueError, match="REQUEST_INTERPRETATION_REVISION_REQUEST_CHANGED"):
            bridge.advance_task(**call)
    finally:
        original_manifest.write_bytes(manifest_raw)
    plugin = Path(manifest["target_source"]) / "Plugin.cs"
    plugin_raw = plugin.read_bytes()
    plugin.write_bytes(plugin_raw + b"\n// changed source")
    try:
        with pytest.raises(ValueError, match="INITIAL_FINDINGS_SOURCE_CHANGED"):
            bridge.advance_task(**call)
    finally:
        plugin.write_bytes(plugin_raw)
    assert roles == []
    completed = bridge.advance_task(**call)
    assert completed["status"] == "awaiting_approval", completed.get("blockers", completed.get("reason"))
    assert completed["prior_model_call_count"] == 4
    assert completed["model_call_count"] == (10 if needs_query else 8)
    assert completed["model_call_budget"]["maximum"] == 13
    assert {k: v["consumed"] for k, v in completed["model_call_budget"]["by_stage"].items()} == {
        "requirement_projection": 2, "requirement_findings": 4 if needs_query else 3,
        "planning": 1, "initial_patch": 1, "repair": 2 if needs_query else 1}
    assert completed["model_call_budget"]["by_stage"]["requirement_projection"]["consumed"] == 2
    assert completed["projection_model_calls_performed"] == 1
    assert completed["baseline_builds_performed"] == 0 and len(builds) == 1
    assert completed["actual_write_performed"] is False
    assert roles[:2] == ["product_requirement_projection", "product_requirement_findings"]
    assert roles.count("product_requirement_projection") == 1
    assert len(roles) == (6 if needs_query else 4)
    assert set(completed["request_interpretation_revision"]["graph_artifact_refs"]) == {
        "request_planning_report", "mod_planning_brief", "feature_spec"}
    assert all(p.read_bytes() == before for p, before in frozen.items())
    count = len(roles)
    repeated = bridge.advance_task(**call)
    assert repeated["scope_hash"] == completed["scope_hash"] and len(roles) == count
    assert repeated["model_call_count"] == completed["model_call_count"]


def test_normal_advance_starts_prepared_project_and_does_not_start_twice(profile, monkeypatch, capsys):
    value = initialize(profile)
    calls = []
    expected = {"run_id": value["run_id"], "status": "awaiting_approval", "model_call_count": 4}
    def product(args):
        calls.append(args)
        root = Path(value["run_root"])
        root.mkdir()
        _write(root / "run_manifest.json", {"run_id": value["run_id"]})
        _write(root / "run_result.json", expected)
        print(json.dumps(expected))
        return 0
    monkeypatch.setattr(bridge.cli, "main", product)
    argv = ["--execution-config", str(profile), "--advance-task", value["run_id"],
            "--findings-allocation-config", str(profile.parent / "unused-revision.json")]
    assert bridge.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert calls[0][-1] == value["description"]
    assert calls[0][calls[0].index("--task-model-call-limit") + 1] == "9"
    assert bridge.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert len(calls) == 1


def test_normal_advance_reports_incomplete_records_without_restarting(profile, monkeypatch):
    value = initialize(profile)
    root = Path(value["run_root"])
    root.mkdir()
    _write(root / "run_manifest.json", {"run_id": value["run_id"]})
    result = bridge.advance_task(execution_config=str(profile), run_id=value["run_id"])
    assert result["status"] == "task_incomplete_inspect_before_retry"
    assert result["reason"] == "DSH_TASK_PROGRESS_INCOMPLETE"
    assert result["automatic_execution_started"] is False
