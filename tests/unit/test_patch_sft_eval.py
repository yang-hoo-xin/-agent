"""SFT eval uses production continuation/transport with explicit offline fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts import prepare_patch_sft_data as data
from scripts import run_patch_sft_eval as evaluation
from src.mod_agent.external_patch import PATCH_FEEDBACK_DATA_CLASSES
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchProfileV1,
    _restore_patch_agent_context,
)
from tests.unit.test_external_patch import _consent, _profile
from tests.unit.test_patch_repair_cli import _message_jsons


def _visible_b0_binding_text(prompt, binding_id, values):
    """Read the literal B0 excerpt that the fixture actually supplied to the model."""
    binding = prompt["edit_binding_contexts"][binding_id]
    if "source_excerpt" in binding:
        return binding["source_excerpt"]
    observations = []
    for role, value in values:
        if not isinstance(value, dict):
            continue
        if (role == "tool" and value.get("binding_id") == binding_id
                and isinstance(value.get("excerpt"), str)):
            observations.append(value)
        supplied = value.get("observation")
        if (value.get("message_type") == "provided_source_observation"
                and isinstance(supplied, dict) and supplied.get("binding_id") == binding_id
                and isinstance(supplied.get("excerpt"), str)):
            observations.append(supplied)
    assert len(observations) == 1
    return observations[0]["excerpt"]


def _fake_execution(root, source, program, tools):
    root.mkdir(parents=True)
    path = root / "Subject.cs"
    path.write_text(source, encoding="utf-8", newline="\n")
    assembly = root / "fake.dll"
    assembly.write_bytes(b"synthetic execution record")
    failed = "if (!publish) return;" in source or "Published++;" in source and "if (publish) Published++;" not in source
    checks = [{"check": "publication_bound", "expected": True, "observed": not failed, "passed": not failed, "group": "new"},
              {"check": "preserve_enabled", "expected": True, "observed": True, "passed": True, "group": "preservation"}]
    compilation = data.save(root / "compilation.json", {"exit_code": 0, "stdout": "synthetic", "stderr": ""})
    record = {"status": "behavior_failed" if failed else "passed", "checks": checks,
        "failed_checks": [row["check"] for row in checks if not row["passed"]], "preservation_passed": True,
        "execution_origin": "actual_csharp_process", "source_ref": data.ref(path),
        "compilation_ref": compilation, "assembly_ref": data.ref(assembly), "fixture_only": True}
    return {**record, "report_ref": data.save(root / "behavior.json", record)}


def test_check_definition_allows_runtime_expected_values_but_not_identity_drift():
    first = [{"check": "dynamic", "group": "target", "expected": 1},
             {"check": "preserve", "group": "preservation", "expected": True}]
    second = [{"check": "dynamic", "group": "target", "expected": 2},
              {"check": "preserve", "group": "preservation", "expected": True}]
    assert evaluation._check_definition_signature(first) == evaluation._check_definition_signature(second)
    assert evaluation._check_definition_signature(first) != evaluation._check_definition_signature(list(reversed(second)))
    with pytest.raises(ValueError, match="DUPLICATE"):
        evaluation._check_definition_signature([first[0], first[0]])


def _fixture(tmp_path, monkeypatch):
    prefix = "public sealed class Subject\n{\n    public int Count, Total, Last, Published;\n    public void Apply(int sample, bool publish)\n    {\n"
    original = "        Count++; Total += sample; Last = sample; Published++;"
    definition = {"case_id": "offline-publication-fixture", "family_id": "offline_fixture", "split": "train",
        "request": "Honor publish without disabling sample state updates. Preserve enabled behavior.",
        "sources": {"B0": prefix + original + "\n    }\n}\n",
                    "C1": prefix + "        if (!publish) return;\n" + original + "\n    }\n}\n",
                    "C2": prefix + original.replace("Published++;", "if (publish) Published++;") + "\n    }\n}\n"}}
    monkeypatch.setattr(data, "execute_version", _fake_execution)
    sample, task = data.prepare_one(definition, tmp_path / "task", {}, "synthetic checker fixture, never compiled")
    manifest = data.save(tmp_path / "manifest.json", {"tasks": [task]})
    profile = LocalOllamaInitialPatchProfileV1(profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        base_url="http://127.0.0.1:11434", model="offline-sft", context_window=16384, output_budget=4096, timeout_seconds=30)
    profile_ref = data.save(tmp_path / "profile.json", profile.to_dict())
    return task, manifest, profile_ref, sample


def _install(monkeypatch):
    chats = []
    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "offline-sft", "model": "offline-sft",
                "digest": "a" * 64, "modified_at": "2026-09-08T00:00:00Z", "size": 1,
                "details": {"context_length": 32768}, "capabilities": ["completion", "tools"]}]}, request=request)
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        chats.append(payload)
        values = _message_jsons(payload)
        prompt = _restore_patch_agent_context(next(value for _, value in values if "required_change_units" in value))
        if len(chats) == 1:
            binding = prompt["required_change_units"][0]["edit_binding_id"]
            message = {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "inspect_plan_binding_source", "arguments": {"binding_id": binding}}}]}
        else:
            context = next(iter(prompt["edit_binding_contexts"].values()))
            after = _visible_b0_binding_text(prompt, context["binding_id"], values).replace(
                "Published++;", "if (publish) Published++;")
            message = {"role": "assistant", "content": json.dumps({"changes": [{"edit_binding_id": context["binding_id"],
                "rationale": "Synthetic response in an offline integration test.", "rollback_hint": "Restore original.", "after_text": after}]})}
        return httpx.Response(200, json={"model": "offline-sft", "message": message, "done": True,
            "done_reason": "stop", "prompt_eval_count": 200, "eval_count": 80}, request=request)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *_: (_ for _ in ()).throw(AssertionError("No real network")))
    monkeypatch.setattr(evaluation, "execute_version", _fake_execution)
    monkeypatch.setattr(evaluation, "toolchain", lambda: {})
    return chats


@pytest.mark.parametrize("mode", ["fixed_failure", "initial_patch"])
def test_preparation_and_shared_worker_transport_reach_review_and_dry_run_without_hidden_c2(tmp_path, monkeypatch, mode):
    task, manifest, profile, sample = _fixture(tmp_path, monkeypatch)
    chats = _install(monkeypatch)
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
        mode=mode, attempt_id="offline-"+mode, output_root=tmp_path / "attempt")
    assert not chats and prepared["model_calls"] == 0
    result = evaluation.execute_prepared(prepared["prepared_ref"])
    assert result["task_succeeded"] is True, result
    assert len(chats) == result["actual_model_calls_recorded"] == 2
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert result["execution_counts"]["apply"] == result["execution_counts"]["build"] == result["execution_counts"]["runtime"] == 0
    assert result["preservation_passed"] is True
    journal = json.loads(Path(result["attempt_ref"]["path"]).read_text(encoding="utf-8"))
    assert journal["execution_trace"]["mode"] == "local_only"
    first = json.dumps(chats[0])
    assert "hidden_oracle" not in first and "CheckApp" not in first
    assert "if (publish) Published++;" not in first
    teacher_c2 = json.loads(sample["completion"][0]["content"])["changes"][0]["after_text"]
    assert teacher_c2 not in [message.get("content") for message in chats[0]["messages"]]
    if mode == "initial_patch":
        assert result["initial_output_correct"] is True and result["repair_required"] is False
        assert "patch_repair_context" not in first
    else:
        assert result["effective_revision"] is True
        assert "patch_repair_context" in first
        parent = json.loads((tmp_path / "attempt/teacher-parent-receipt.json").read_text(encoding="utf-8"))
        assert parent["origin"] == "operator_authored_fixed_failure" and parent["provider_send_count"] == 0
        assert parent["historical_model_attempt_claimed"] is False


def test_duplicate_attempt_output_is_not_overwritten(tmp_path, monkeypatch):
    task, manifest, profile, _ = _fixture(tmp_path, monkeypatch)
    output = tmp_path / "attempt"
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
        mode="initial_patch", attempt_id="unique", output_root=output)
    original = Path(prepared["prepared_ref"]["path"]).read_bytes()
    with pytest.raises(FileExistsError):
        evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
            mode="initial_patch", attempt_id="unique", output_root=output)
    assert hashlib.sha256(original).hexdigest() == prepared["prepared_ref"]["sha256"]


def test_explicit_trace_configuration_reaches_real_worker_without_extra_model_calls(tmp_path, monkeypatch):
    from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration

    task, manifest, profile, _ = _fixture(tmp_path, monkeypatch)
    chats = _install(monkeypatch)
    class Sink:
        def __init__(self):
            self.rows = []
            self.shutdown_calls = 0
        def publish(self, row):
            self.rows.append(row)
        def shutdown(self, *, timeout_millis):
            self.shutdown_calls += 1
            return {"status": "offline_test", "remote_readback": "not_performed"}
    sink = Sink()
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
        mode="initial_patch", attempt_id="explicit-trace", output_root=tmp_path / "attempt")
    assert not sink.rows and not chats
    result = evaluation.execute_prepared(prepared["prepared_ref"],
        execution_trace_configuration=PatchExecutionTraceConfiguration(environment="offline-sft", sink=sink))
    assert result["task_succeeded"] and len(chats) == 2
    journal = json.loads(Path(result["attempt_ref"]["path"]).read_text(encoding="utf-8"))
    assert journal["execution_trace"]["mode"] == "metadata_only"
    assert journal["execution_trace"]["environment"] == "offline-sft"
    generation_ids = {row["id"] for row in sink.rows if row["name"] == "patch.generate" and row["kind"] == "generation"}
    assert len(generation_ids) == 2 and sink.shutdown_calls == 1


def test_prepare_rejects_export_before_sink_or_environment_access(monkeypatch):
    from src.observability.patch_langfuse import LangfuseHttpTransport

    def forbidden(*args, **kwargs):
        raise AssertionError("Preparation must not construct a sink or access export credentials.")
    monkeypatch.setattr(LangfuseHttpTransport, "from_environment", forbidden)
    monkeypatch.setattr(evaluation, "prepare_eval", forbidden)
    with pytest.raises(SystemExit) as raised:
        evaluation.main(["--langfuse-metadata"])
    assert raised.value.code == 2


@pytest.mark.parametrize("enabled", [False, True])
def test_cli_export_flag_passes_only_explicit_metadata_sink(tmp_path, monkeypatch, enabled):
    from src.observability import patch_live_langfuse
    from src.observability.patch_langfuse import LangfuseHttpTransport

    created, calls = [], []
    transport = object()
    def from_environment():
        created.append("transport")
        return transport
    def make_sink(value):
        assert value is transport
        created.append("sink")
        return object()
    monkeypatch.setattr(LangfuseHttpTransport, "from_environment", from_environment)
    monkeypatch.setattr(patch_live_langfuse, "PatchLiveLangfuseSink", make_sink)
    monkeypatch.setattr(evaluation, "execute_prepared", lambda ref, **kwargs: calls.append(kwargs) or {"test": True})
    arguments = ["--execute", "--prepared", str(tmp_path / "prepared.json"), "--prepared-sha256", "a" * 64]
    if enabled:
        arguments.append("--langfuse-metadata")
    assert evaluation.main(arguments) == 0
    assert created == (["transport", "sink"] if enabled else [])
    configuration = calls[0]["execution_trace_configuration"]
    assert (configuration is not None) is enabled
    if enabled:
        assert configuration.sink is not None


def _external_fixture(tmp_path, monkeypatch):
    task, manifest, _, sample = _fixture(tmp_path, monkeypatch)
    profile = _profile()
    profile_ref = data.save(tmp_path / "external-profile.json", profile.to_dict())
    return task, manifest, profile, profile_ref, sample


def _install_external(monkeypatch):
    calls, chats = [], []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            assert request.url.path == "/api/v1/models"
            return httpx.Response(200, json={"output": {"models": [{"model": "qwen3.6-plus"}]}}, request=request)
        assert request.url.path == "/compatible-mode/v1/chat/completions"
        payload = json.loads(request.content)
        chats.append(payload)
        values = _message_jsons(payload)
        prompt = _restore_patch_agent_context(next(value for _, value in values if "required_change_units" in value))
        context = next(iter(prompt["edit_binding_contexts"].values()))
        fixed_failure = any(value.get("message_type") == "patch_repair_context"
                            for _, value in values if isinstance(value, dict))
        if fixed_failure and len(chats) == 1:
            tool = next(row["function"] for row in payload["tools"]
                        if row["function"]["name"] == "inspect_plan_binding_source")
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "fixed-failure-source-read", "type": "function", "function": {
                    "name": tool["name"],
                    "arguments": json.dumps({"binding_id": context["binding_id"]}),
                }}]}
        else:
            if len(chats) == 2 and not fixed_failure:
                feedback = next(value for _, value in values
                                if value.get("message_type") == "patch_behavior_correction")
                assert feedback["validator_feedback"]["observations"]
            replacement = ("if (publish || sample != 0) Published++;"
                           if len(chats) == 1 else "if (publish) Published++;")
            content = json.dumps({"changes": [{"edit_binding_id": context["binding_id"],
                "rationale": "Offline fixture repair.", "rollback_hint": "Restore original.",
                "after_text": _visible_b0_binding_text(
                    prompt, context["binding_id"], values).replace("Published++;", replacement)}]})
            message = {"role": "assistant", "content": content}
        return httpx.Response(200, json={"id": f"offline-{len(chats)}", "model": "qwen3.6-plus",
            "choices": [{"message": message,
                         "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 80}}, request=request)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "offline-fixture-secret")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No real network or model is allowed.")
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("socket.socket.connect_ex", forbidden)
    monkeypatch.setattr(evaluation, "execute_version", _fake_execution)
    monkeypatch.setattr(evaluation, "toolchain", lambda: {})
    return calls, chats


def test_external_preparation_exposes_exact_disclosure_scope_without_credentials_or_network(tmp_path, monkeypatch):
    task, manifest, profile, profile_ref, _ = _external_fixture(tmp_path, monkeypatch)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Preparation must not read credentials or call a provider.")
    monkeypatch.setattr("src.mod_agent.external_patch.os.environ.get", forbidden)
    monkeypatch.setattr(httpx.Client, "get", forbidden)
    monkeypatch.setattr(httpx.Client, "post", forbidden)
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile_ref,
        mode="fixed_failure", attempt_id="external-prepare", output_root=tmp_path / "attempt")
    requirement = prepared["disclosure_requirements"]
    assert requirement["destination"]["model"] == profile.model
    assert requirement["destination"]["request_url"] == profile.base_url + "/chat/completions"
    assert set(PATCH_FEEDBACK_DATA_CLASSES) <= set(requirement["required_data_classes"])
    assert "approved" not in requirement and "approval_id" not in requirement
    expected = {path.relative_to(task["source_root"]).as_posix(): data.ref(path)["sha256"]
                for path in Path(task["source_root"]).rglob("*.cs")}
    assert prepared["source_files"] == expected and prepared["model_calls"] == 0
    assert prepared["cli_arguments"] is None


@pytest.mark.parametrize("mode", ["fixed_failure", "initial_patch"])
def test_external_eval_shared_worker_repairs_original_checks_and_reaches_review_dry_run(tmp_path, monkeypatch, mode):
    task, manifest, profile, profile_ref, sample = _external_fixture(tmp_path, monkeypatch)
    calls, chats = _install_external(monkeypatch)
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile_ref,
        mode=mode, attempt_id="external-" + mode, output_root=tmp_path / "attempt")
    consent_ref = data.save(tmp_path / "consent.json", _consent(profile))
    result = evaluation.execute_prepared(prepared["prepared_ref"], source_disclosure_ref=consent_ref)
    assert result["task_succeeded"] and result["effective_revision"] and result["preservation_passed"], result
    assert len(chats) == result["actual_model_calls_recorded"] == 2
    assert result["verification_summary"]["checks"] == 2
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert result["execution_counts"]["apply"] == result["execution_counts"]["build"] == result["execution_counts"]["runtime"] == 0
    journal = json.loads(Path(result["attempt_ref"]["path"]).read_text(encoding="utf-8"))
    factory = journal["factory_receipt"]
    assert factory["adapter"] == "ExternalQwenPatchAdapter"
    expected_evaluations = (["passed"] if mode == "fixed_failure"
                            else ["behavior_failed", "passed"])
    assert [row["status"] for row in factory["patch_agent_loop"]["behavior_evaluations"]] == expected_evaluations
    assert "hidden_oracle" not in json.dumps(chats) and "CheckApp" not in json.dumps(chats)
    teacher_c2 = json.loads(sample["completion"][0]["content"])["changes"][0]["after_text"]
    assert teacher_c2 not in [message.get("content") for message in chats[0]["messages"]]
    assert ("patch_repair_context" in json.dumps(chats[0])) is (mode == "fixed_failure")
    assert calls[0][0] == "GET"


@pytest.mark.parametrize("invalid", ["missing", "destination", "feedback", "source_changed"])
def test_external_eval_missing_consent_or_changed_scope_sends_nothing(tmp_path, monkeypatch, invalid):
    task, manifest, profile, profile_ref, _ = _external_fixture(tmp_path, monkeypatch)
    calls, _ = _install_external(monkeypatch)
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile_ref,
        mode="fixed_failure", attempt_id="external-rejected", output_root=tmp_path / "attempt")
    consent = _consent(profile, feedback=invalid != "feedback")
    if invalid == "destination":
        consent["destination"]["model"] = "different-exact-model"
    if invalid == "source_changed":
        (Path(task["source_root"]) / "Added.cs").write_text("// newly added source\n")
    consent_ref = None if invalid == "missing" else data.save(tmp_path / "consent.json", consent)
    if invalid == "missing":
        with pytest.raises(ValueError, match="SFT_EVAL_EXTERNAL_DISCLOSURE_REQUIRED"):
            evaluation.execute_prepared(prepared["prepared_ref"])
    else:
        result = evaluation.execute_prepared(prepared["prepared_ref"], source_disclosure_ref=consent_ref)
        assert not result["task_succeeded"] and result["first_failure"]
    assert not calls


def test_cli_passes_hash_bound_disclosure_only_for_execution(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(evaluation, "execute_prepared", lambda ref, **kwargs: calls.append(kwargs) or {})
    consent = tmp_path / "consent.json"
    args = ["--execute", "--prepared", str(tmp_path / "prepared.json"), "--prepared-sha256", "a" * 64,
            "--source-disclosure", str(consent), "--source-disclosure-sha256", "b" * 64]
    assert evaluation.main(args) == 0
    assert calls[0]["source_disclosure_ref"] == {"path": str(consent.resolve()), "sha256": "b" * 64}
    with pytest.raises(SystemExit):
        evaluation.main(args[:-2])
    with pytest.raises(SystemExit):
        evaluation.main(args[1:])
