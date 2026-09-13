"""Run-request external assembly uses explicit profiles and fake transport only."""

import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import httpx
import pytest

from src.mod_agent import local_entry
from src.mod_agent.external_patch import (
    ExternalPatchError,
    RunRequestExternalAssembly,
    validate_run_request_external_profile,
)
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.product_executor import SOURCE_DISCLOSURE_DATA_CLASSES
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from src.mod_agent.request_patch_execution import RequestPatchExecution
from src.mod_agent.workflow.state import create_initial_state
from tests.unit.test_external_patch import _consent, _install, _profile
from tests.unit.test_fresh_planning_continuation import _source_hashes
from tests.unit.test_patch_repair_cli import _public_case


def test_missing_external_profile_stops_before_llm_or_source_access(tmp_path, monkeypatch):
    profile = _profile()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-secret")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", profile.base_url)
    monkeypatch.setattr(local_entry.LLMFactory, "create", lambda *_args, **_kwargs: pytest.fail("LLM constructed before profile admission"))
    monkeypatch.setattr(local_entry, "_source_snapshot", lambda *_args: pytest.fail("Source read before profile admission"))
    with pytest.raises(ExternalPatchError, match="EXTERNAL_PATCH_RUN_REQUEST_PROFILE_REQUIRED"):
        local_entry.run_local_request(description="Change the configured default.", target_project=tmp_path / "missing",
            workspace_base=tmp_path / "runs", settings_path="config/settings.yaml", confirm_isolated_write=True,
            allow_build=True, allow_source_disclosure=True, diff_approval_reader=lambda _value: "unused")


@pytest.mark.parametrize("field,value", [("model", "different-explicit-model"), ("base_url", "https://different.example/v1"),
                                        ("credential_env", "OTHER_EXPLICIT_KEY")])
def test_external_profile_must_match_current_run_inputs(field, value):
    profile = _profile()
    selected = {"model": profile.model, "base_url": profile.base_url, "credential_env": profile.credential_env}
    selected[field] = value
    with pytest.raises(ExternalPatchError, match="EXTERNAL_PATCH_RUN_REQUEST_PROFILE_MISMATCH"):
        validate_run_request_external_profile(profile, **selected)


def test_public_external_entry_assembles_shared_worker_before_any_upstream_send(tmp_path, monkeypatch):
    from src.core.settings import load_settings

    handler = _install(monkeypatch, direct=True)
    profile = _profile()
    settings = load_settings("config/settings.yaml")
    settings = replace(settings, llm=replace(settings.llm, provider="openai", model=profile.model,
                                             base_url=profile.base_url, max_tokens=profile.output_budget))
    monkeypatch.setattr(local_entry, "load_settings", lambda _path: settings)
    monkeypatch.setenv("DASHSCOPE_BASE_URL", profile.base_url)
    llm = SimpleNamespace(model=profile.model, base_url=profile.base_url,
                          chat=lambda *_args, **_kwargs: pytest.fail("Upstream called during assembly"))
    monkeypatch.setattr(local_entry.LLMFactory, "create", lambda *_args, **_kwargs: llm)
    source = tmp_path / "Example"
    source.mkdir()
    (source / "Example.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net7.0</TargetFramework></PropertyGroup></Project>')
    (source / "Plugin.cs").write_bytes(b"sealed class Plugin {}\n")
    def compile_double(build_profile):
        artifact = build_profile.working_directory / "bin/Debug/net7.0/Example.dll"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"explicit compiler double")
        return local_entry.NuGetIsolatedBuildExecution(restore_exit_code=0, build_exit_code=0,
            restore_stdout="", restore_stderr="", build_stdout="", build_stderr="", duration_ms=1)
    monkeypatch.setattr(local_entry, "_run_nuget_isolated_build", compile_double)
    captured = {}
    class AssemblyObservedError(Exception):
        pass
    def inspect(_preflight, adapters, _store, **_kwargs):
        captured["worker"] = adapters.patch_change_factory
        raise AssemblyObservedError
    monkeypatch.setattr(local_entry, "execute_product_execution", inspect)
    with pytest.raises(local_entry.LocalEntryError, match="AssemblyObservedError"):
        local_entry.run_local_request(description="Change the configured default.", target_project=source,
            workspace_base=tmp_path / "runs", settings_path="config/settings.yaml", confirm_isolated_write=True,
            allow_build=True, allow_source_disclosure=True, diff_approval_reader=lambda _value: "unused",
            external_patch_profile=profile)
    worker = captured["worker"]
    assert isinstance(worker, RequestPatchExecution)
    assert worker.profile == profile and worker.adapter_factory.__self__.profile == profile
    assert worker.adapter_factory.__self__.disclosure["approved_data_classes"] == list(SOURCE_DISCLOSURE_DATA_CLASSES)
    assert worker.adapter_factory.__self__.disclosure["approval_id"]
    assert handler.calls and not handler.wires


@pytest.mark.parametrize("role,has_failure,required_class", [
    ("planning_generated", True, "generated_patch"),
    ("planning_feedback", True, "verification_feedback"),
    ("evidence_query", True, "verification_feedback"),
    ("evidence_findings", True, "verification_feedback"),
    ("planning_feedback", False, None),
    ("evidence_query", False, None),
])
def test_product_upstream_checks_actual_feedback_disclosure_before_budget_and_send(
    tmp_path, monkeypatch, role, has_failure, required_class,
):
    """Use real run-request provider closures with deterministic send doubles."""
    from src.libs.llm import ChatResponse
    from src.libs.llm.agent_turn import AgentMessage, AgentTurnRequest
    from tests.unit.test_agent_turn_adapters import _format

    captured, sends = {}, []
    ordinary_adapters = local_entry.ProductExecutionAdaptersV1

    def assemble(**kwargs):
        adapters = ordinary_adapters(**kwargs)
        captured["adapters"] = adapters
        return adapters

    def planning_client(assembly):
        def complete(request):
            sends.append(request)
            return SimpleNamespace(provider="qwen_chat", model=assembly.profile.model, content="{}")

        return SimpleNamespace(provider="qwen_chat", model=assembly.profile.model, complete_turn=complete)

    def complete_json(**kwargs):
        sends.append(kwargs["payload"])
        return ChatResponse(model=_profile().model, content='{"queries":[]}'), {}

    monkeypatch.setattr(local_entry, "ProductExecutionAdaptersV1", assemble)
    monkeypatch.setattr(RunRequestExternalAssembly, "planning_client", planning_client)
    monkeypatch.setattr(local_entry, "request_requirement_coverage_model", complete_json)
    test_public_external_entry_assembles_shared_worker_before_any_upstream_send(tmp_path, monkeypatch)
    adapters = captured["adapters"]
    worker = adapters.patch_change_factory
    before = worker.budget_snapshot()
    observations = [{"check_id": "current_failure", "passed": False}] if has_failure else []

    def invoke():
        if role in {"planning_generated", "planning_feedback"}:
            payload = {"upstream_assessment": {
                "previous_response": "retained generated Patch" if role == "planning_generated" else None,
                "failure_report": {"observations": observations} if has_failure and role == "planning_feedback" else None,
            }}
            request = AgentTurnRequest(messages=(AgentMessage(role="system", content="Deterministic test."),
                AgentMessage(role="user", content=payload)), response_format=_format())
            return adapters.patch_upstream_planning_target_selection_factory.client.complete_turn(request)
        factory = adapters.patch_upstream_evidence_pack_factory
        feedback = {"observed_failure": observations}
        if role == "evidence_query":
            return factory.query_selector({}, {"requirements": [{"requirement_id": "requirement_001"}],
                "relations": []}, SimpleNamespace(items=()), feedback)
        return factory.semantic_provider.complete_json("requirement_findings", {"semantic_feedback": feedback}, {})

    if required_class is not None:
        with pytest.raises(local_entry.LocalEntryError, match=required_class):
            invoke()
        assert worker.budget_snapshot() == before and sends == []
    else:
        invoke()
        assert len(sends) == 1
        assert worker.budget_snapshot()["consumed"] == before["consumed"] + 1


@pytest.mark.parametrize("missing", ["authorization", "listing"])
def test_external_assembly_stops_before_generation_when_admission_is_missing(monkeypatch, missing):
    handler = _install(monkeypatch, direct=True, listed=missing != "listing")
    profile = _profile()
    consent = _consent(profile, feedback=False)
    if missing == "authorization":
        consent["approved"] = False
    with pytest.raises((ExternalPatchError, local_entry.LocalEntryError)):
        RunRequestExternalAssembly(profile=profile, source_disclosure=consent)
    assert not handler.wires
    if missing == "authorization":
        assert not handler.calls


def test_production_assembly_uses_external_adapter_inside_original_request_worker(tmp_path, monkeypatch):
    policy = PatchAgentLoopPolicy(max_total_model_turns=5, max_tool_rounds=3,
        require_source_inspection=False, finalize_after_first_observation=False,
        allow_upstream_request=True, enable_supporting_reads=True, allow_batched_reads=True)
    case = _public_case(tmp_path, selected_policy=asdict(policy))
    handler = _install(monkeypatch, direct=True)
    profile = _profile()
    assembly = RunRequestExternalAssembly(profile=profile, source_disclosure=_consent(profile, feedback=False))
    request = case.request
    state = create_initial_state(run_id="external_product", request_id="external_request",
        user_request=case.inputs.feature_payload["user_request"], target_mod=case.inputs.feature_payload["target_mod"])
    state["feature_id"] = request.feature_spec_ref.feature_id
    for ref in (request.feature_spec_ref, request.evidence_pack_ref, request.implementation_plan_ref):
        state["artifacts"][ref.artifact_type], state["artifact_hashes"][ref.artifact_type] = ref.path, ref.artifact_hash
    state["current_stage"] = "implementation_plan"
    calls = []
    config = PatchWorkerConfiguration.load(case.config_path)
    execution = RequestPatchExecution(artifact_store=case.inputs.store, workspace_root=case.inputs.workspace,
        profile=profile, identity_reader=lambda *_args: pytest.fail("External worker used Ollama identity"),
        policy=policy, reserve_model_call=calls.append,
        budget_snapshot=lambda: {"remaining": 5 - len(calls), "by_stage": {"initial_patch": {"remaining": 5 - len(calls)}}},
        behavior_evaluator=config.behavior_evaluator(), adapter_factory=assembly.make_worker)
    before = _source_hashes(case.inputs.workspace)
    changes = execution(state, case.inputs.store.read(request.implementation_plan_ref)["data"],
                        case.inputs.store.read(request.evidence_pack_ref)["data"])
    assert changes and calls == ["initial_patch"] and len(handler.wires) == 1
    assert execution.receipts[0]["adapter"] == "ExternalQwenPatchAdapter"
    assert execution.receipts[0]["profile"]["execution_locality"] == "external"
    assert execution.receipts[0]["source_disclosure"]["approved_data_classes"] == list(SOURCE_DISCLOSURE_DATA_CLASSES)
    assert _source_hashes(case.inputs.workspace) == before


@pytest.mark.parametrize("wrong_model", [False, True])
def test_external_planning_uses_qwen_protocol_and_checks_actual_response_identity(monkeypatch, wrong_model):
    from src.libs.llm.agent_turn import AgentMessage, AgentTurnRequest
    from tests.unit.test_agent_turn_adapters import _format

    profile = _profile()
    requests = []
    monkeypatch.setenv(profile.credential_env, "unit-test-secret")
    def handle(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"output": {"models": [{"model": profile.model}]}}, request=request)
        payload = json.loads(request.content)
        assert str(request.url) == profile.base_url + "/chat/completions"
        assert payload["model"] == profile.model and payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"model": "wrong-model" if wrong_model else profile.model,
            "choices": [{"message": {"role": "assistant", "content": '{"selected":"fixture"}'}, "finish_reason": "stop"}]}, request=request)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *_args: pytest.fail("Real network forbidden"))
    assembly = RunRequestExternalAssembly(profile=profile, source_disclosure=_consent(profile, feedback=False))
    request = AgentTurnRequest(messages=(AgentMessage(role="user", content="fixture planning request"),), response_format=_format())
    if wrong_model:
        with pytest.raises(ExternalPatchError, match="EXTERNAL_PATCH_RESPONSE_MODEL_MISMATCH"):
            assembly.planning_client().complete_turn(request)
    else:
        assert assembly.planning_client().complete_turn(request).model == profile.model
    assert [request.method for request in requests] == ["GET", "POST"]
