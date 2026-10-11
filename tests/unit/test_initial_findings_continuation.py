"""Initial Findings rejection must survive a failed correction reservation."""

import io
import json
from pathlib import Path

import httpx
import pytest

from scripts import dsh_run_request as bridge
from src.mod_agent.initial_findings_continuation import (
    admit_initial_findings_continuation,
    prepare_initial_findings_continuation,
)
from tests.unit.test_dsh_run_request import (
    _call,
    _install_execution_boundaries,
)
from tests.unit.test_dsh_run_request import (
    execution_config as _execution_config_fixture,
)

execution_config = _execution_config_fixture


def _provider_backend(root):
    import hashlib
    ollama = root / "ollama.exe"
    server = root / "llama-server.exe"
    ollama.write_bytes(b"controlled ollama binary")
    server.write_bytes(b"controlled llama server binary")
    return {"ollama_version": "test", "llama_server_version": "test",
            "llama_cpp_commit": "test-commit", "binary_refs": [
                {"role": "ollama", "path": str(ollama),
                 "sha256": hashlib.sha256(ollama.read_bytes()).hexdigest()},
                {"role": "llama_server", "path": str(server),
                 "sha256": hashlib.sha256(server.read_bytes()).hexdigest()}]}


def _install_source_failure_baseline(monkeypatch, builds):
    from src.mod_agent import local_entry

    def build(profile):
        builds.append(profile)
        return local_entry.NuGetIsolatedBuildExecution(
            restore_exit_code=0, build_exit_code=1, restore_stdout="restore ok", restore_stderr="",
            build_stdout=f"{profile.working_directory / 'Plugin.cs'}(1,1): error CS0103: "
                "The name 'MissingValue' does not exist in the current context", build_stderr="", duration_ms=1)

    monkeypatch.setattr(local_entry, "_run_nuget_isolated_build", build)


def _failed_run(execution_config, monkeypatch, capsys, *, harness=None, baseline_failure=False):
    config = json.loads(execution_config.read_text())
    config["arguments"] += ["--run-id", "findings_task", "--request-id", "findings_request"]
    config["arguments"][config["arguments"].index("--task-model-call-limit") + 1] = "11"
    execution_config.write_text(json.dumps(config))
    setup = _install_execution_boundaries(execution_config.parent, monkeypatch)
    if baseline_failure:
        _install_source_failure_baseline(monkeypatch, setup[2])
    limits = execution_config.parent / "limits.json"
    values = {"requirement_projection": 1, "requirement_findings": 1, "planning": 1, "initial_patch": 4, "repair": 4}
    limits.write_text(json.dumps(values))
    original = httpx.HTTPTransport.handle_request
    if harness is not None:
        harness.update(transport=original, baseline_calls=setup[2])
    posts = []

    def transport(client, request):
        response = original(client, request)
        if request.method == "POST":
            posts.append(request)
            body = response.json()
            content = json.loads(body["message"]["content"])
            if "findings" in content:
                row = next(row for row in content["findings"] if row.get("edit_target_evidence_ids"))
                row["unresolved_gaps"] = ["Current input API evidence remains unresolved."]
                body["message"]["content"] = json.dumps(content)
                return httpx.Response(200, request=request, json=body)
        return response

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    # Preserve the actual legacy wire contract independently of the new default.
    from src.mod_agent.evidence import StructuredModelRequirementCoverageProvider
    original_init = StructuredModelRequirementCoverageProvider.__init__
    def legacy_init(self, complete_json, **kwargs):
        original_init(self, complete_json, findings_contract_version="1")
    with monkeypatch.context() as historical:
        historical.setattr(StructuredModelRequirementCoverageProvider, "__init__", legacy_init)
        assert _call(execution_config, "make Load record deterministic product diagnostics", monkeypatch) == 2
    result = json.loads(capsys.readouterr().out)
    return result, posts


def test_public_entry_retains_first_rejection_when_correction_budget_is_empty(execution_config, monkeypatch, capsys):
    result, posts = _failed_run(execution_config, monkeypatch, capsys)
    manifest = json.loads((Path(result["run_root"]) / "run_manifest.json").read_text(encoding="utf-8"))
    span = next(row for row in manifest["execution_observations"].values()
                if row["name"] == "requirements.coverage")
    audit = span["attributes"]["requirement_findings_attempt_audit"]
    assert audit[0]["error_code"] == "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID"
    assert audit[0]["diagnostic"]["unresolved_gaps"] == ["Current input API evidence remains unresolved."]
    assert audit[1]["error_code"] == "PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED"
    assert audit[1]["correction_payload_prepared"] is True
    assert audit[1]["call_boundary"]["reservation_succeeded"] is False
    assert audit[1]["call_boundary"]["model_request_invoked"] is False
    assert audit[1]["call_boundary"]["budget"]["consumed"] == 2
    assert len(posts) == result["model_call_count"] == 2


def test_same_task_preparation_replays_exact_inputs_and_keeps_original_budget(execution_config, monkeypatch, capsys):
    result, posts = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(result["run_root"])
    before = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("Preparation invoked HTTP"))
    assert bridge.main(["--execution-config", str(execution_config), "--prepare-findings-continuation", result["run_id"]]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["status"] == "prepared_blocked"
    assert prepared["budget"] == result["model_call_budget"]
    assert prepared["continuation_input"]["request_id"] == "findings_request"
    assert prepared["model_calls_performed"] == 0 and prepared["model_invocation_authorized"] is False
    assert prepared["cause_chain"]["historical_trace_audit"][1]["call_boundary"]["model_request_invoked"] is False
    next_turn = prepared["continuation_input"]["next_turn"]
    assert next_turn["payload"]["message_type"] == "product_requirement_findings_correction"
    assert next_turn["payload"]["error_code"] == "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID"
    assert json.loads(next_turn["model_request"]["messages"][1]["content"]) == next_turn["payload"]
    with pytest.raises(ValueError, match="PRODUCT_STAGE_MODEL_CALL_BUDGET_EXHAUSTED"):
        admit_initial_findings_continuation(prepared, run_root=root, run_id=result["run_id"], execution_config=execution_config)
    assert {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert len(posts) == 2


@pytest.mark.parametrize("damage", ["source", "response", "model", "stage_limit", "packet"])
def test_prepared_continuation_rejects_drift_and_cannot_refund_calls(execution_config, monkeypatch, capsys, damage):
    result, _ = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(result["run_root"])
    arguments = {"run_root": root, "run_id": result["run_id"], "execution_config": execution_config}
    prepared = prepare_initial_findings_continuation(**arguments)
    if damage == "source":
        (root / "generated_mods/Example/Plugin.cs").write_text("changed")
    elif damage == "response":
        reference = prepared["continuation_input"]["parent_refs"][-1]
        Path(reference["path"]).write_text("{}")
    elif damage == "model":
        path = root / "run_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["local_model_identity"]["digest"] = "0" * 64
        path.write_text(json.dumps(manifest))
    elif damage == "stage_limit":
        limits = execution_config.parent / "limits.json"
        value = json.loads(limits.read_text())
        value["requirement_findings"] = 2
        limits.write_text(json.dumps(value))
    else:
        prepared["continuation_input"]["budget"]["consumed"] = 0
    with pytest.raises((ValueError, RuntimeError)) as caught:
        admit_initial_findings_continuation(prepared, **arguments)
    assert str(caught.value).startswith("INITIAL_FINDINGS_")


def test_correction_failure_without_transport_facts_stays_unknown(tmp_path):
    from copy import deepcopy

    from src.mod_agent.evidence import StructuredModelRequirementCoverageProvider
    from tests.unit.test_requirement_coverage import _materialized_and_retrieved, _positive_findings
    feature, materialized, retrieved = _materialized_and_retrieved(tmp_path)
    invalid = deepcopy(_positive_findings(materialized, retrieved))
    invalid["findings"] = invalid["findings"][:2]
    invalid["findings"][0]["unresolved_gaps"] = ["Unresolved current evidence."]
    def complete(role, *_):
        if role == "requirement_findings":
            return invalid
        raise RuntimeError("Provider failed with no transport facts")
    provider = StructuredModelRequirementCoverageProvider(complete, findings_contract_version="1")
    with pytest.raises(RuntimeError):
        provider.findings(materialized_projection=materialized, retrieved_pack=retrieved, request=feature["user_request"])
    assert provider.findings_attempt_audit[0]["error_code"] == "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID"
    assert provider.findings_attempt_audit[1]["correction_payload_prepared"] is True
    assert "call_boundary" not in provider.findings_attempt_audit[1]


@pytest.mark.parametrize("contract_version", ["1", "3"])
@pytest.mark.parametrize("outcome", ["support", "invalid", "missing"])
@pytest.mark.parametrize("baseline_failure", [False, True])
def test_approved_stage_instance_continues_original_graph_without_baseline_or_projection(execution_config, monkeypatch, capsys, outcome, contract_version, baseline_failure):
    from src.mod_agent.initial_findings_continuation import (
        execute_initial_findings_continuation,
        preview_initial_findings_execution,
    )
    from tests.unit.test_mod_agent_cli import _formal_coverage_model_response
    harness = {}
    previous, _ = _failed_run(execution_config, monkeypatch, capsys, harness=harness,
        baseline_failure=baseline_failure)
    root = Path(previous["run_root"])
    baseline = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))["baseline_build"]
    if baseline_failure:
        assert not Path(baseline["artifact_path"]).exists()
    historical = {str(path): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    allocations = execution_config.parent / "continuation-allocation.json"
    findings_limit = 3 if contract_version == "3" else 2
    allocations.write_text(json.dumps({"stage_model_call_limits": {"requirement_projection": 1,
        "requirement_findings": findings_limit, "planning": 1, "initial_patch": 5 - findings_limit, "repair": 4}, "max_execution_seconds": 1800,
        **({"findings_contract_version": "3", "provider_backend": _provider_backend(execution_config.parent)}
           if contract_version == "3" else {})}))
    arguments = {"run_root": root, "run_id": previous["run_id"], "execution_config": execution_config, "allocation_config": allocations}
    reviewed = preview_initial_findings_execution(**arguments)
    assert reviewed["effective_budget"]["consumed"] == 2 and reviewed["effective_budget"]["maximum"] == 11
    roles = []
    def transport(client, request):
        if request.method == "POST":
            native = json.loads(request.content)
            contexts = []
            for message in native["messages"]:
                try:
                    value = json.loads(message["content"])
                    if isinstance(value, dict):
                        contexts.append(value)
                except (ValueError, TypeError):
                    pass
            correction = next((value for value in contexts if value.get("message_type") == "product_requirement_findings_correction"), None)
            if correction is not None:
                if baseline_failure:
                    assert correction["baseline_compilation_failure"] == baseline["repair_observation"]
                assert correction.get("findings_contract_version", "1") == contract_version
                if contract_version == "3":
                    assert correction["previous_findings"]["findings"][0]["unresolved_gaps"]
                    assert correction["rejection_diagnostic"]["validator_rejection"]["diagnostic"]["violated_rules"]
                roles.append("correction")
                content = _formal_coverage_model_response({**correction, "message_type": "product_requirement_findings"})
                if outcome == "invalid":
                    next(row for row in content["findings"] if row["edit_target_evidence_ids"])["unresolved_gaps"] = ["Still unresolved."]
                elif outcome == "missing":
                    for row in content["findings"]:
                        row.update(relationship="missing", evidence_ids=[], edit_target_evidence_ids=[], unresolved_gaps=["Current API remains unverified."])
                return httpx.Response(200, request=request, json={"model": native["model"],
                    "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
                    "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
            reassessment = next((value for value in contexts if value.get("message_type") == "initial_findings_evidence_queries"), None)
            if reassessment is not None:
                roles.append("reassessment_queries")
                content = {"queries": [{"query": "Load",
                    "requirement_id": reassessment["requirements"][0]["requirement_id"],
                    "gap_ids": [reassessment["gap_investigation_targets"][0]["gap_id"]],
                    "current_fact_needed": "Existing source ownership.",
                    "modification_impact": "Planning needs a bound current fact.",
                    "authorized_source": "target_source",
                    "metadata_queries": []}]}
                return httpx.Response(200, request=request, json={"model": native["model"],
                    "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
                    "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
            assert not any(value.get("message_type") == "product_requirement_projection" for value in contexts)
            roles.append("planning_or_patch")
        return harness["transport"](client, request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    decision = {"decision": "approve", "reviewer": "synthetic-test-approval", "scope_hash": reviewed["scope_hash"]}
    monkeypatch.setattr(bridge.sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(decision).encode())))
    code = bridge.main(["--execution-config", str(execution_config), "--execute-findings-continuation", previous["run_id"],
                        "--findings-allocation-config", str(allocations), "--decision-stdin"])
    result = json.loads(capsys.readouterr().out)
    if outcome == "support":
        assert code == 0 and result["status"] == "awaiting_approval", result
        assert result["model_call_count"] == 5 and result["model_call_budget"]["remaining"] == 6
        assert result["current_invocation_model_call_count"] == 3
        assert roles == ["correction", "planning_or_patch", "planning_or_patch"]
        assert result["workflow_checkpoint"]
    elif outcome == "invalid":
        assert code == 2 and result["model_call_count"] == 3, result
        expected_code = "REQUIREMENT_COVERAGE_EDIT_TARGET_SELECTION_INVALID"
        assert any(expected_code in row["message"] for row in result["blockers"])
        assert roles == ["correction"]
    else:
        if contract_version == "1":
            assert code == 2 and result["model_call_count"] == 3, result
            assert roles == ["correction"]
            assert any("PRODUCT_STAGE_MODEL_CALL_BUDGET_EXHAUSTED" in row["message"] for row in result["blockers"])
        else:
            assert code == 0 and result["status"] == "awaiting_approval", result
            assert result["model_call_count"] == 7 and result["model_call_budget"]["remaining"] == 4
            assert roles == ["correction", "reassessment_queries", "planning_or_patch",
                             "planning_or_patch", "planning_or_patch"]
            assert result["model_call_budget"]["by_stage"]["requirement_findings"]["consumed"] == 3
            assert result["model_call_budget"]["by_stage"]["repair"]["consumed"] == 1
    assert result["run_id"] == previous["run_id"] and result["request_id"] == "findings_request"
    assert result["baseline_builds_performed"] == result["projection_model_calls_performed"] == 0
    assert result["findings_contract"]["selected_version"] == contract_version
    assert len(harness["baseline_calls"]) == 1
    assert result["actual_write_performed"] is False
    if baseline_failure and outcome != "invalid":
        evidence = json.loads(Path(result["artifacts"]["evidence_pack"]).read_text(encoding="utf-8"))["data"]
        assert evidence["budget_summary"]["baseline_compilation_failure"] == baseline["repair_observation"]
    assert all(Path(path).read_bytes() == raw for path, raw in historical.items())
    again = execute_initial_findings_continuation(**arguments, decision={"decision": "approve",
        "reviewer": "synthetic-test-approval", "scope_hash": reviewed["scope_hash"]})
    assert again["read_only"] is True and len(roles) == result["current_invocation_model_call_count"]
    inspected = bridge.inspect_run(execution_config=str(execution_config), run_id=previous["run_id"])
    assert inspected["original_result"]["model_call_count"] == 2
    assert inspected["result"]["model_call_count"] == result["model_call_count"]


@pytest.mark.parametrize("damage", ["stdout_hash", "stderr_hash", "non_source_error", "diagnostics",
                                    "observation", "baseline_source", "restore"])
def test_failed_baseline_continuation_rechecks_original_compiler_evidence(
    execution_config, monkeypatch, capsys, damage,
):
    import hashlib
    from src.mod_agent.build.baseline_repair import validated_baseline_repair_observation

    previous, posts = _failed_run(execution_config, monkeypatch, capsys, baseline_failure=True)
    root = Path(previous["run_root"])
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    baseline = manifest["baseline_build"]
    assert validated_baseline_repair_observation(manifest, root) == baseline["repair_observation"]
    if damage in {"stdout_hash", "stderr_hash", "non_source_error"}:
        stream = "stderr" if damage == "stderr_hash" else "stdout"
        path = Path(baseline[f"{stream}_path"])
        path.write_text("build: error MSB1001: unknown switch", encoding="utf-8")
        if damage == "non_source_error":
            baseline[f"{stream}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif damage == "diagnostics":
        baseline["source_compilation_diagnostics"][0]["code"] = "CS0000"
    elif damage == "observation":
        baseline["repair_observation"]["diagnostics"][0]["file"] = "Elsewhere.cs"
    elif damage == "baseline_source":
        (root / "baseline_source/Example/Plugin.cs").write_text("changed", encoding="utf-8")
    else:
        baseline["restore_exit_code"] = 1
    with pytest.raises(ValueError, match="INITIAL_FINDINGS_BASELINE_CHANGED"):
        validated_baseline_repair_observation(manifest, root)
    assert len(posts) == 2


@pytest.mark.parametrize("failure", ["no_approval", "changed_allocation", "changed_settings", "changed_source", "expanded_total", "no_stage_room"])
def test_execution_admission_cannot_reset_or_bypass_original_task(execution_config, monkeypatch, capsys, failure):
    from src.mod_agent.initial_findings_continuation import (
        execute_initial_findings_continuation,
        preview_initial_findings_execution,
    )
    previous, _ = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(previous["run_root"])
    allocation = execution_config.parent / "allocation.json"
    value = {"stage_model_call_limits": {"requirement_projection": 1, "requirement_findings": 2,
             "planning": 1, "initial_patch": 3, "repair": 4}, "max_execution_seconds": 1800}
    allocation.write_text(json.dumps(value))
    arguments = {"run_root": root, "run_id": previous["run_id"], "execution_config": execution_config, "allocation_config": allocation}
    preview = preview_initial_findings_execution(**arguments)
    decision = {"decision": "approve", "reviewer": "unit", "scope_hash": preview["scope_hash"]}
    if failure == "no_approval":
        decision = None
    elif failure == "changed_allocation":
        value["max_execution_seconds"] = 1200
        allocation.write_text(json.dumps(value))
    elif failure == "changed_settings":
        # Bind an alternate local settings instance without modifying the repository settings.
        document = json.loads(execution_config.read_text())
        settings = execution_config.parent / "changed-settings.yaml"
        settings.write_text("runtime: {}")
        document["arguments"][document["arguments"].index("--settings") + 1] = str(settings)
        execution_config.write_text(json.dumps(document))
    elif failure == "changed_source":
        (root / "generated_mods/Example/Plugin.cs").write_text("changed")
    elif failure == "expanded_total":
        value["stage_model_call_limits"]["repair"] = 5
        allocation.write_text(json.dumps(value))
    else:
        value["stage_model_call_limits"].update(requirement_findings=1, initial_patch=4)
        allocation.write_text(json.dumps(value))
        decision["scope_hash"] = preview_initial_findings_execution(**arguments)["scope_hash"]
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("Invalid admission reached HTTP"))
    with pytest.raises((ValueError, RuntimeError)):
        execute_initial_findings_continuation(**arguments, decision=decision)
    assert not (root / "continuations" / "initial_findings.json").exists()
    assert json.loads((root / "run_result.json").read_text(encoding="utf-8"))["model_call_count"] == 2


def test_revised_correction_binds_new_input_without_rewriting_history_or_inheriting_approval(execution_config, monkeypatch, capsys):
    from src.mod_agent.initial_findings_continuation import (
        execute_initial_findings_continuation,
        preview_initial_findings_execution,
    )
    previous, _ = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(previous["run_root"])
    old_bytes = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    allocation = execution_config.parent / 'revision.json'
    document = {"stage_model_call_limits": {"requirement_projection": 1, "requirement_findings": 3,
        "planning": 1, "initial_patch": 2, "repair": 4}, "max_execution_seconds": 1800}
    allocation.write_text(json.dumps(document))
    args = dict(run_root=root, run_id=previous['run_id'], execution_config=execution_config, allocation_config=allocation)
    old = preview_initial_findings_execution(**args)
    document['findings_contract_version'] = '3'
    document['provider_backend'] = _provider_backend(execution_config.parent)
    allocation.write_text(json.dumps(document))
    revised = preview_initial_findings_execution(**args)
    contract = revised['continuation_input']['correction_contract']
    assert contract['historical_version'] == '1' and contract['selected_version'] == '3'
    assert contract['revision_requires_new_approval'] is True
    assert contract['historical_turn']['payload'] == old['continuation_input']['next_turn']['payload']
    assert contract['historical_turn']['schema'] == old['continuation_input']['next_turn']['schema']
    assert contract['historical_turn_sha256'] != contract['selected_turn_sha256']
    assert revised['scope_hash'] != old['scope_hash']
    assert revised['budget'] == old['budget'] == previous['model_call_budget']
    assert revised['execution_scope']['model_call_preflight']['admitted'] is True
    assert revised['execution_scope']['model_call_preflight']['required_by_stage'] == {
        'requirement_findings': 2, 'repair': 1}
    assert revised['execution_scope']['model_call_preflight']['minimum_stage_limits'] == {
        'requirement_findings': 3, 'repair': 1}
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', lambda *_: pytest.fail('Stale approval reached network'))
    backend_path = Path(document['provider_backend']['binary_refs'][0]['path'])
    backend_bytes = backend_path.read_bytes()
    backend_path.write_bytes(b'changed backend')
    with pytest.raises(ValueError, match='INITIAL_FINDINGS_PROVIDER_BACKEND_CHANGED'):
        execute_initial_findings_continuation(**args, decision={'decision':'approve','reviewer':'test',
            'scope_hash':revised['scope_hash']})
    backend_path.write_bytes(backend_bytes)
    with pytest.raises(ValueError, match='INITIAL_FINDINGS_EXACT_CONTINUATION_APPROVAL_REQUIRED'):
        execute_initial_findings_continuation(**args, decision={'decision':'approve','reviewer':'test','scope_hash':old['scope_hash']})
    assert all(path.read_bytes() == raw for path, raw in old_bytes.items())
    assert not (root / 'continuations/initial_findings.json').exists()


def test_reassessment_revision_contract_appends_second_history_instance(tmp_path):
    from src.mod_agent.initial_findings_continuation import _reassessment_revision_claim_names

    continuation = tmp_path / "continuations"
    continuation.mkdir()
    assert _reassessment_revision_claim_names(tmp_path) == (
        "initial_findings-reassessment.json",
        "initial_findings-reassessment-v2.json",
        1,
    )
    (continuation / "initial_findings-reassessment-v2.json").write_text("{}", encoding="utf-8")
    assert _reassessment_revision_claim_names(tmp_path) == (
        "initial_findings-reassessment-v2.json",
        "initial_findings-reassessment-v3.json",
        2,
    )
    (continuation / "initial_findings-reassessment-v4.json").write_text("{}", encoding="utf-8")
    assert _reassessment_revision_claim_names(tmp_path) == (
        "initial_findings-reassessment-v4.json",
        "initial_findings-reassessment-v5.json",
        3,
    )
    (continuation / "initial_findings-reassessment-v5.json").write_text("{}", encoding="utf-8")
    assert _reassessment_revision_claim_names(tmp_path) == (
        "initial_findings-reassessment-v5.json",
        "initial_findings-reassessment-v6.json",
        4,
    )


def test_first_query_provider_preflight_freezes_before_http_with_bounded_output(
    execution_config, monkeypatch,
):
    from src.mod_agent.initial_findings_continuation import _preview_first_query_provider_request

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda *_: pytest.fail("Read-only provider preflight reached HTTP"))
    packet = {
        "model_limits": {"timeout_seconds": 600},
        "next_turn": {"query_model_contract": {
            "role": "initial_findings_queries",
            "payload": {"message_type": "initial_findings_evidence_queries", "feature": {
                "target_mod": "Example"}, "requirements": [], "relations": [],
                "source_observations": [], "coverage_feedback": {},
                "search_root": "generated_mods/Example", "instruction": "Return bounded queries."},
            "schema": {"type": "object", "additionalProperties": False,
                "required": ["queries"], "properties": {"queries": {"type": "array",
                    "maxItems": 3, "items": {"type": "object"}}}},
        }},
    }

    preview = _preview_first_query_provider_request(
        packet, execution_config=execution_config)

    assert preview["status"] == "admitted"
    assert preview["output_budget"] == 768
    assert preview["model_calls_performed"] == 0
    assert preview["http_transport_started"] is False
    assert preview["provider_request"]["context_admission"]["admitted"] is True


@pytest.mark.parametrize("historical_planning_policy", [None, "planning_basis_v1"])
def test_v3_continues_recorded_v2_failure_from_three_calls_without_refund(
        execution_config, monkeypatch, capsys, historical_planning_policy):
    import hashlib
    from copy import deepcopy

    from src.mod_agent.initial_findings_continuation import (
        execute_initial_findings_continuation,
        prepare_initial_findings_continuation,
        preview_initial_findings_execution,
    )
    from tests.unit.test_mod_agent_cli import _formal_coverage_model_response

    harness = {}
    original, _ = _failed_run(execution_config, monkeypatch, capsys, harness=harness)
    root = Path(original["run_root"])
    original_bytes = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    from src.mod_agent.evidence.requirement_coverage_provider import StructuredModelRequirementCoverageProvider
    original_init = StructuredModelRequirementCoverageProvider.__init__
    def historical_init(self, complete_json, **kwargs):
        if kwargs.get("findings_contract_version") == "2":
            kwargs.setdefault("findings_planning_basis_policy", historical_planning_policy)
        original_init(self, complete_json, **kwargs)
    with monkeypatch.context() as historical:
        historical.setattr(StructuredModelRequirementCoverageProvider, "__init__", historical_init)
        v2 = prepare_initial_findings_continuation(run_root=root, run_id=original["run_id"],
            execution_config=execution_config, correction_contract_version="2")
    segment = root / "continuations" / "v2-recorded-fixture"
    bodies = segment / "model_trace_bodies"
    bodies.mkdir(parents=True)
    request_path = bodies / "v2.request.json"
    response_path = bodies / "v2.response.txt"
    request_path.write_text(json.dumps(v2["continuation_input"]["next_turn"]["model_request"]), encoding="utf-8")
    raw = {"findings": [
        {"relation_index": 1, "relationship": "support", "unresolved_gaps": ["Current API unknown."]},
        {"relation_index": 1, "relationship": "support", "unresolved_gaps": ["Current API unknown."]}]}
    response_path.write_text(json.dumps(raw), encoding="utf-8")
    def ref(path):
        return {"path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    budget = deepcopy(original["model_call_budget"])
    budget.update(consumed=3, remaining=8)
    budget["by_stage"]["requirement_findings"].update(maximum=3, consumed=2, remaining=1)
    budget["by_stage"]["initial_patch"].update(maximum=2, remaining=2)
    manifest = {"run_id": original["run_id"], "request_id": "findings_request",
        "model_call_budget": budget, "execution_observations": {
            "generation": {"name": "requirements.findings", "attributes": {
                "model_role": "requirement_findings_correction", "response_complete": True,
                "local_detail_refs": {"request": ref(request_path), "response": ref(response_path)}}},
            "coverage": {"name": "requirements.coverage", "attributes": {
                "requirement_findings_attempt_audit": [{"attempt_index": 2, "status": "failed",
                    "error_code": "REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID",
                    "diagnostic": {"json_path": "$.findings[0].evidence_ids"}}]}}}}
    (segment / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = {"status": "partial", "run_id": original["run_id"], "request_id": "findings_request",
        "continuation_root": str(segment), "scope_hash": "2" * 64, "model_call_budget": budget,
        "model_call_count": 3, "current_invocation_model_call_count": 1,
        "actual_write_performed": False, "canonical_source_unchanged": True,
        "findings_contract": {"selected_version": "2"},
        "blockers": [{"message": "RequirementFindingsAdmissionError: REQUIREMENT_COVERAGE_FINDINGS_SCHEMA_INVALID"}],
        "product_execution_result": {"failure_stage": "retrieve_evidence_execution"}}
    result_path = segment / "run_result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    original_result = root / "run_result.json"
    claim = {"run_id": original["run_id"], "request_id": "findings_request", "scope_hash": "2" * 64,
        "parent_result_ref": ref(original_result), "result_path": str(result_path),
        "model_call_budget": budget, "status": "recorded"}
    (root / "continuations" / "initial_findings.json").write_text(json.dumps(claim), encoding="utf-8")

    allocation = execution_config.parent / "v3-allocation.json"
    allocation.write_text(json.dumps({"stage_model_call_limits": {"requirement_projection": 1,
        "requirement_findings": 4, "planning": 1, "initial_patch": 1, "repair": 4},
        "max_execution_seconds": 1800, "findings_contract_version": "3",
        "provider_backend": _provider_backend(execution_config.parent)}))
    args = {"run_root": root, "run_id": original["run_id"],
            "execution_config": execution_config, "allocation_config": allocation}
    reviewed = preview_initial_findings_execution(**args)
    assert reviewed["budget"]["consumed"] == 3 and reviewed["effective_budget"]["remaining"] == 8
    assert reviewed["continuation_input"]["correction_contract"]["historical_version"] == "2"
    assert reviewed["continuation_input"]["correction_contract"]["selected_version"] == "3"
    assert reviewed["continuation_input"]["execution_parent_result_ref"] == ref(result_path)
    assert "oneOf" not in reviewed["continuation_input"]["next_turn"]["schema"]["properties"]["findings"]["items"]
    roles = []
    def transport(client, request):
        if request.method == "POST":
            native = json.loads(request.content)
            payloads = []
            for message in native["messages"]:
                try:
                    value = json.loads(message["content"])
                    if isinstance(value, dict):
                        payloads.append(value)
                except (TypeError, ValueError):
                    pass
            correction = next((value for value in payloads
                               if value.get("message_type") == "product_requirement_findings_correction"), None)
            if correction is not None:
                roles.append("correction_v3")
                content = _formal_coverage_model_response(
                    {**correction, "message_type": "product_requirement_findings"})
                return httpx.Response(200, request=request, json={"model": native["model"],
                    "message": {"role": "assistant", "content": json.dumps(content)}, "done": True,
                    "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20})
            roles.append("planning_or_patch")
        return harness["transport"](client, request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    decision = {"decision": "approve", "reviewer": "controlled-v3",
                "scope_hash": reviewed["scope_hash"]}
    completed = execute_initial_findings_continuation(**args, decision=decision)
    assert completed["status"] == "awaiting_approval" and completed["model_call_count"] == 6
    assert completed["prior_model_call_count"] == 3 and completed["current_invocation_model_call_count"] == 3
    assert roles == ["correction_v3", "planning_or_patch", "planning_or_patch"]
    assert (root / "continuations" / "initial_findings.json").read_text(encoding="utf-8") == json.dumps(claim)
    assert all(path.read_bytes() == value for path, value in original_bytes.items())
    latest = bridge.inspect_run(execution_config=str(execution_config), run_id=original["run_id"])
    assert latest["original_result"]["model_call_count"] == 2
    assert latest["result"]["model_call_count"] == 6
