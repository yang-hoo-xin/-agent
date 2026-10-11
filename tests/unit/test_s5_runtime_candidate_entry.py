import importlib.util
import json
import time
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "artifacts/eval_driven_20261005/benchmark10/S5/host/runtime-driver-v1/run_candidate.py"
spec = importlib.util.spec_from_file_location("s5_candidate_owner", MODULE_PATH)
owner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return owner.ref(path)


@pytest.fixture
def context_factory(tmp_path):
    def create(origin="formal_build"):
        run = tmp_path / "run"
        run.mkdir()
        source = run / "compiled-source"
        source.mkdir()
        cs = source / "Plugin.cs"
        cs.write_text("candidate source")
        project = source / "LivePanel.csproj"
        project.write_text("project")
        dll = source / "bin/Debug/net6.0/LivePanel.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"built candidate")
        assembly = owner.ref(dll)
        files = [{"path": p.name, "sha256": owner.ref(p)["sha256"]} for p in (cs, project)]
        original = tmp_path / "original"
        original.mkdir()
        (original / "Plugin.cs").write_text("original source")
        bundle = write_json(tmp_path / "bundle.json", {"task_id": "S5", "source_root": str(original), "source_snapshot": [{"path": "Plugin.cs", "sha256": owner.ref(original / "Plugin.cs")["sha256"]}]})
        if origin == "formal_build":
            build_data = {"artifact_type": "build_result", "data": {"status": "success", "exit_code": 0, "real_build_performed": True,
                "execution_mode": "local", "input_execution_mode": "isolated_apply", "build_profile": {"working_directory": str(source)},
                "verified_artifacts": [{"resolved_path": str(dll), "sha256": assembly["sha256"]}]}}
        else:
            build_data = {"exit_code": 0, "argv": ["dotnet", "build", str(project)]}
        build = write_json(tmp_path / "build.json", build_data)
        evidence = [build]
        if origin == "public_checker":
            evidence.append(write_json(tmp_path / "managed.json", {"status": "passed", "assembly_ref": assembly,
                "checks": [{"passed": True, "check_id": str(i)} for i in range(51)]}))
        binding = write_json(tmp_path / "binding.json", {"schema": "s5-runtime-subject-build-binding.v1", "origin": origin,
            "assembly_ref": assembly, "source_checks": [{"source_ref": owner.ref(p), "compiled_source_ref": owner.ref(p)} for p in (cs, project)],
            "build_evidence_refs": evidence})
        receipt = write_json(tmp_path / "source-receipt.json", {"schema": "s5-candidate-source-receipt.v1", "assembly_ref": assembly,
            "source_root": str(source), "source_files": files, "build_result_ref": build, "candidate_build_binding_ref": binding})
        observer = tmp_path / "observer.dll"
        observer.write_bytes(b"observer")
        observer_build = write_json(tmp_path / "observer-build.json", {"schema": "s5-runtime-observer-build.v3", "exit_code": 0, "observer_assembly_ref": owner.ref(observer)})
        manifest = write_json(tmp_path / "actions.json", {"schema": "s5-runtime-host-actions.v3"})
        auth = write_json(tmp_path / "auth.json", {"game_root": str(owner.GAME), "origin": "user message", "human_messages": ["你直接在我正常游戏环境里运行"]})
        context = {"schema": "s5-candidate-runtime-context.v1", "run_root": str(run), "output_root": str(run / "runtime-output"),
            "candidate_assembly_ref": assembly, "candidate_source_receipt_ref": receipt, "candidate_build_binding_ref": binding,
            "original_bundle_ref": bundle, "observer_build_ref": observer_build, "action_manifest_ref": manifest,
            "authorization_ref": auth, "deadline": {"epoch_seconds": time.time() + 590, "monotonic_seconds": time.monotonic() + 590}}
        return context, write_json(tmp_path / "context.json", context)
    return create


@pytest.mark.parametrize("origin", ["formal_build", "public_checker"])
def test_accepts_actual_build_origins_and_source_checks(context_factory, origin):
    context, ref = context_factory(origin)
    returned = owner.validate_context(ref)
    assert returned[2] == context["candidate_assembly_ref"]
    assert returned[1].remaining() < 590


def test_shared_deadline_takes_earlier_clock_and_never_resets(monkeypatch):
    monkeypatch.setattr(owner.time, "time", lambda: 1000)
    monkeypatch.setattr(owner.time, "monotonic", lambda: 100)
    budget = owner.SharedDeadline({"epoch_seconds": 1100, "monotonic_seconds": 180})
    assert budget.remaining() == 80
    monkeypatch.setattr(owner.time, "time", lambda: 1080)
    assert budget.remaining() == 20
    with pytest.raises(TimeoutError):
        budget.require(20)


def test_insufficient_remaining_budget_rejected(context_factory):
    context, ref = context_factory()
    context["deadline"] = {"epoch_seconds": time.time() + 70, "monotonic_seconds": time.monotonic() + 70}
    ref = write_json(Path(ref["path"]), context)
    with pytest.raises(TimeoutError):
        owner.validate_context(ref)


def test_candidate_source_drift_rejected(context_factory):
    context, ref = context_factory()
    receipt = owner.read_json_ref(context["candidate_source_receipt_ref"])
    (Path(receipt["source_root"]) / "Plugin.cs").write_text("changed after build")
    with pytest.raises(AssertionError, match="DRIFT"):
        owner.validate_context(ref)


def test_other_verified_dll_cannot_satisfy_formal_build(context_factory):
    context, ref = context_factory()
    receipt = owner.read_json_ref(context["candidate_source_receipt_ref"])
    build = owner.read_json_ref(receipt["build_result_ref"])
    build["data"]["verified_artifacts"][0]["sha256"] = "0" * 64
    changed = write_json(Path(receipt["build_result_ref"]["path"]), build)
    binding = owner.read_json_ref(context["candidate_build_binding_ref"])
    binding["build_evidence_refs"] = [changed]
    context["candidate_build_binding_ref"] = write_json(Path(context["candidate_build_binding_ref"]["path"]), binding)
    receipt.update(build_result_ref=changed, candidate_build_binding_ref=context["candidate_build_binding_ref"])
    context["candidate_source_receipt_ref"] = write_json(Path(context["candidate_source_receipt_ref"]["path"]), receipt)
    ref = write_json(Path(ref["path"]), context)
    with pytest.raises(ValueError, match="ASSEMBLY_MISMATCH"):
        owner.validate_context(ref)


def test_normal_quit_requires_real_same_process_evidence(tmp_path):
    process = write_json(tmp_path / "process.json", {"owner_pid": 42, "exited": True})
    value = {"schema": "s5-runtime-normal-quit.v1", "session_id": "s5-current", "owner_pid": 42,
        "requested_unix_ms": 1, "exited_unix_ms": 2, "method": "window_close", "exit_observed": True,
        "forced_termination": False, "process_evidence_ref": process}
    path = tmp_path / "quit.json"
    write_json(path, value)
    assert owner.normal_quit_reference(path, session="s5-current", pid=42) == owner.ref(path)
    value["forced_termination"] = True
    write_json(path, value)
    with pytest.raises(ValueError, match="INVALID"):
        owner.normal_quit_reference(path, session="s5-current", pid=42)


def test_gui_eligibility_requires_each_real_window(tmp_path):
    rows = [{"kind": "action_window_finished", "session_id": "current", "action_id": name,
             "gui_completed_since_request": 4, "chain_ticks_since_request": 2}
            for name in ("ordinary_save_1", "ordinary_save_2", "ordinary_save_3", "replace_repeat_0", "replace_repeat_1")]
    path = tmp_path / "logs.txt"
    def save():
        path.write_text("\n".join("S5_RUNTIME_V1 " + json.dumps(x) for x in rows))
        return [{"ref": owner.ref(path)}]
    assert owner.gui_windows_complete(save(), "current")
    rows[-1]["gui_completed_since_request"] = 0
    assert not owner.gui_windows_complete(save(), "current")


def test_runner_exception_restores_owned_files_and_outer_acceptance_empty(context_factory, tmp_path, monkeypatch):
    game = tmp_path / "fake-game"
    (game / "BepInEx/plugins").mkdir(parents=True)
    (game / "BepInEx/config").mkdir()
    (game / "GTFO.exe").write_bytes(b"not executable")
    cfg = game / "BepInEx/config/benchmark.gtfo.livepanel.cfg"
    cfg.write_bytes(b"original")
    control = game / "BepInEx/config/benchmark.s5.runtimeobserver.control.json"
    control.write_bytes(b"old-control")
    monkeypatch.setattr(owner, "GAME", game)
    monkeypatch.setattr(owner, "_existing_gtfo_processes", lambda: [])
    class Process:
        code = None
        def poll(self):
            return self.code
        def terminate(self):
            self.code = 1
        def kill(self):
            self.code = 1
        def wait(self, timeout=None):
            return self.code
    process = Process()
    monkeypatch.setattr(owner, "_launch_gtfo_process", lambda *args, **kwargs: owner.GTFOProcessHandle(42, process))
    class Runner:
        def run(self, **kwargs):
            assert kwargs["acceptance_criteria"] == ()
            assert kwargs["profile"].acceptance_markers == {}
            kwargs["process_launcher"](kwargs["profile"])
            raise RuntimeError("offline injected runner failure")
    monkeypatch.setattr(owner, "GTFORealRuntimeAutomationRunner", Runner)
    context, ref = context_factory()
    with pytest.raises(RuntimeError, match="injected"):
        owner.execute_context(ref)
    out = Path(context["output_root"])
    result = json.loads((out / "result.json").read_bytes())
    assert not result["runtime_acceptance_eligible"]
    assert not result["normal_exit"]
    assert result["restoration_complete"] is True
    assert cfg.read_bytes() == b"original" and control.read_bytes() == b"old-control"
    assert not (game / "BepInEx/plugins/CodexBenchmarkS5").exists()
    assert json.loads((out / "preimage-subject-config.json").read_bytes())["before_exists"] is True
    assert process.poll() is not None
