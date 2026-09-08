"""Public CLI seams with retained unit artifacts and an injected compiler only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.mod_agent import cli
from src.mod_agent.build.adapter import BuildProfile
from tests.unit.test_dsh_review_run import case as retained_case
from tests.unit.test_reviewed_patch_continuation import _build_continuation_case


@pytest.fixture
def ready_build(tmp_path, monkeypatch):
    case = retained_case.__wrapped__(tmp_path)
    return _build_continuation_case(case, tmp_path, monkeypatch)


def _build_argv(ready_build, tmp_path):
    inputs, applied, args, _before = ready_build
    payload_path = tmp_path / "build-resume.json"
    payload_path.write_text(json.dumps(args["resume_payload"].to_dict()), encoding="utf-8")
    profile = BuildProfile(profile_id="injected-cli-compiler", build_system="unit",
        working_directory=applied["isolated_workspace"], command=("injected-cli-compiler",),
        timeout_seconds=3, expected_artifacts=("bin/cli-built.dll",))
    profile_path = tmp_path / "build-profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()), encoding="utf-8")
    reference = args["checkpoint_ref"]
    argv = ["apply-patch", "--continue-build", "--allow-build",
        "--artifact-store-root", str(inputs.store.root), "--feature-id", reference.feature_id,
        "--checkpoint-path", reference.path, "--checkpoint-hash", reference.artifact_hash,
        "--resume-payload", str(payload_path), "--build-profile", str(profile_path)]
    return argv, profile, profile_path


def test_public_apply_command_exposes_explicit_build_continuation(ready_build, tmp_path):
    argv, profile, _path = _build_argv(ready_build, tmp_path)
    parsed = cli.build_parser().parse_args(argv)
    assert parsed.continue_build is True and parsed.allow_build is True
    assert parsed.human_decision_stdin is False
    assert parsed.build_profile.endswith("build-profile.json")
    assert profile.command == ("injected-cli-compiler",)


def _install_compiler(monkeypatch):
    import src.mod_agent.build.adapter as build_owner
    from src.mod_agent.build.adapter import BuildCommandResult

    calls = []

    def injected_compiler(profile, *, environment):
        calls.append((profile, environment))
        assert isinstance(environment, dict)
        destination = Path(profile.working_directory)
        for relative in profile.expected_artifacts:
            output = destination / relative
            assert not output.exists()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"unit compiler emitted artifact")
        return BuildCommandResult(exit_code=0, stdout="unit compiler success")

    monkeypatch.setattr(build_owner, "run_build_profile_command", injected_compiler)
    return calls


def test_public_build_continuation_uses_real_backend_and_bound_profile(ready_build, tmp_path, monkeypatch, capsys):
    inputs, applied, _args, before = ready_build
    argv, profile, _profile_path = _build_argv(ready_build, tmp_path)
    calls = _install_compiler(monkeypatch)

    assert cli.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "built" and result["builds_performed"] == 1
    assert result["isolated_workspace"] == applied["isolated_workspace"]
    assert result["runtime_executions_performed"] == result["model_calls_performed"] == 0
    assert calls[0][0].to_dict() == profile.to_dict()
    assert len(calls) == 1
    from tests.unit.test_dsh_review_run import _snapshot

    assert _snapshot(inputs.workspace) == before
    assert cli.main(argv) == 2
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["status"] == "blocked" and len(calls) == 1


def test_build_continuation_requires_authorization_before_compiler(ready_build, tmp_path, monkeypatch, capsys):
    argv, _profile, _path = _build_argv(ready_build, tmp_path)
    calls = _install_compiler(monkeypatch)
    argv.remove("--allow-build")
    assert cli.main(argv) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["reason"] == "REVIEWED_BUILD_EXPLICIT_CONFIGURATION_REQUIRED"
    assert calls == []


@pytest.mark.parametrize("invalid,reason", [
    ("workspace", "REVIEWED_BUILD_PROFILE_WORKSPACE_MISMATCH"),
    ("old_output", "REVIEWED_BUILD_PREEXISTING_OUTPUT_REJECTED"),
    ("outside_output", "REVIEWED_BUILD_EXPECTED_ARTIFACT_PATH_INVALID"),
    ("command", "REVIEWED_BUILD_PROFILE_COMMAND_INVALID"),
])
def test_build_profile_rejects_wrong_workspace_old_output_and_invalid_command(ready_build, tmp_path, monkeypatch, capsys, invalid, reason):
    _inputs, applied, _args, _before = ready_build
    argv, profile, path = _build_argv(ready_build, tmp_path)
    calls = _install_compiler(monkeypatch)
    value = profile.to_dict()
    if invalid == "workspace":
        value["working_directory"] = str(tmp_path)
    elif invalid == "old_output":
        old = Path(applied["isolated_workspace"]) / "bin" / "cli-built.dll"
        old.parent.mkdir()
        old.write_bytes(b"not a new Build")
    elif invalid == "outside_output":
        value["expected_artifacts"] = ["../old.dll"]
    else:
        value["command"] = "injected-cli-compiler"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert cli.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == reason
    assert calls == []


def test_default_apply_still_pauses_before_build(ready_build, tmp_path, monkeypatch):
    argv, _profile, _path = _build_argv(ready_build, tmp_path)
    parsed = cli.build_parser().parse_args(["apply-patch", "--confirm", "--human-decision-stdin"])
    assert parsed.continue_build is False and parsed.allow_build is False
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*argv, "--human-decision-stdin"])


def _run_request_capture(monkeypatch):
    seen = []

    def capture(**arguments):
        seen.append(arguments)
        raise cli.LocalEntryError("UNIT_STOP_BEFORE_PRODUCT_EXECUTION")

    monkeypatch.setattr(cli, "run_local_request", capture)
    return seen


def test_run_request_passes_worker_budgets_and_same_trace_configuration(tmp_path, monkeypatch, capsys):
    from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration
    from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration

    worker_path = tmp_path / "worker.json"
    worker_path.write_text(json.dumps({"schema_version": "patch_worker_configuration_v1", "policy": {},
        "enable_recovery_loop": False, "behavior_evaluator": None}), encoding="utf-8")
    limits = {"requirement_projection": 2, "requirement_findings": 3, "planning": 1, "initial_patch": 4, "repair": 2}
    limits_path = tmp_path / "stage-limits.json"
    limits_path.write_text(json.dumps(limits), encoding="utf-8")
    seen = _run_request_capture(monkeypatch)
    assert cli.main(["run-request", "Preserve saved configuration", "--target-project", str(tmp_path),
        "--patch-worker-config", str(worker_path), "--task-model-call-limit", "12",
        "--stage-model-call-limits", str(limits_path), "--trace-environment", "unit-review"]) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "UNIT_STOP_BEFORE_PRODUCT_EXECUTION"
    arguments = seen[0]
    assert isinstance(arguments["patch_worker_configuration"], PatchWorkerConfiguration)
    assert arguments["patch_worker_configuration"].reference["path"] == str(worker_path.resolve())
    assert arguments["task_model_call_limit"] == 12 and arguments["stage_model_call_limits"] == limits
    assert isinstance(arguments["execution_trace_configuration"], PatchExecutionTraceConfiguration)
    assert arguments["execution_trace_configuration"].environment == "unit-review"
    assert arguments["execution_trace_configuration"].sink is None
    assert arguments["local_ollama"] is False and arguments["ollama_model"] is None
    assert arguments["api_key_env"] == "DASHSCOPE_API_KEY"


def test_run_request_without_new_options_preserves_default_selection(tmp_path, monkeypatch, capsys):
    seen = _run_request_capture(monkeypatch)
    assert cli.main(["run-request", "A real request", "--target-project", str(tmp_path)]) == 2
    capsys.readouterr()
    assert seen[0]["patch_worker_configuration"] is None
    assert seen[0]["task_model_call_limit"] is None and seen[0]["stage_model_call_limits"] is None
    assert seen[0]["execution_trace_configuration"].environment == "local"
    assert seen[0]["execution_trace_configuration"].sink is None


def test_explicit_metadata_flag_uses_the_existing_trace_sink(tmp_path, monkeypatch, capsys):
    from src.observability.patch_langfuse import LangfuseHttpTransport
    from src.observability.patch_live_langfuse import PatchLiveLangfuseSink

    transport = object()
    sink = object()
    selected = []
    monkeypatch.setattr(LangfuseHttpTransport, "from_environment", lambda: transport)
    monkeypatch.setattr(PatchLiveLangfuseSink, "__new__", lambda cls, value: selected.append(value) or sink)
    seen = _run_request_capture(monkeypatch)
    assert cli.main(["run-request", "A real request", "--target-project", str(tmp_path),
        "--trace-environment", "unit-trace", "--langfuse-metadata"]) == 2
    capsys.readouterr()
    assert selected == [transport]
    assert seen[0]["execution_trace_configuration"].sink is sink
    assert seen[0]["execution_trace_configuration"].environment == "unit-trace"


@pytest.mark.parametrize("field", ["task", "stage", "duplicate"])
def test_invalid_budget_file_or_value_stops_before_product_entry(tmp_path, monkeypatch, capsys, field):
    seen = _run_request_capture(monkeypatch)
    argv = ["run-request", "A real request", "--target-project", str(tmp_path)]
    if field == "task":
        argv += ["--task-model-call-limit", "0"]
    else:
        path = tmp_path / "limits.json"
        path.write_text('{"planning":1,"planning":2}' if field == "duplicate" else '{"planning":true}', encoding="utf-8")
        argv += ["--stage-model-call-limits", str(path)]
    assert cli.main(argv) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert seen == []


def test_shared_process_runner_preserves_original_process_semantics(tmp_path):
    from types import SimpleNamespace

    from src.mod_agent.build.adapter import run_build_profile_command

    profile = BuildProfile(profile_id="unit", build_system="unit", working_directory=str(tmp_path),
        command=("unit-command", "--arg"), timeout_seconds=7)
    environment = {"TASK_MARKER": "explicit"}
    seen = []

    def process(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=3, stdout="compiler output", stderr="compiler failure")

    result = run_build_profile_command(profile, environment=environment, command_runner=process)
    assert result.exit_code == 3 and result.stdout == "compiler output" and result.stderr == "compiler failure"
    assert result.duration_ms >= 0
    assert seen == [(profile.command, {"cwd": str(tmp_path), "capture_output": True, "text": True,
        "encoding": "utf-8", "errors": "replace", "timeout": 7, "check": False, "env": environment})]
