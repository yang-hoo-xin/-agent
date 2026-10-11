"""Synthetic execution bindings plus re-assessment of retained real failure logs."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.mod_agent.domain import observer_runtime_evaluator as module
from src.mod_agent.domain.full_project_compilation import _ref, _save
from src.mod_agent.model_qualification import read_bound_json
from src.mod_agent.runtime import isolated_candidate


ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "artifacts/eval_driven_20261005/benchmark10/S1/runtime-observer-v2/Observer.cs"
EXPECTED = {"schema": "s1-runtime-observer.v2", "observer_version": "0.2.0", "min_elapsed_seconds": 2., "min_samples": 10, "alpha": .75}


def records(config, *, found=True):
    owner = config["owner_config"]
    yield {"kind": "loaded", "schema": EXPECTED["schema"], "observer_version": "0.2.0",
           "subject_path": owner["protected_file_refs"][0]["path"], "executable": owner["game_executable_ref"]["path"]}
    yield {"kind": "started", "frame": 1}
    for index in range(31):
        yield {"kind": "frame", "frame": index + 1, "observed_frame_sequence": index + 1, "elapsed": index / 10.,
               "readout_sample": True, "panel_found": found, "panel_status": "observed" if found else "unknown:no_behaviour",
               "visible": True if found else None, "readout_status": "observed" if found else "unknown",
               "readout": f"FPS: {60 + index}" if found else None, "alpha": .75 if found else None}


def runtime_receipt(tmp_path, config, assembly, rows):
    tmp_path.mkdir()
    raw = "[Info : Frame Pulse] Frame Pulse loaded\n[Info : BepInEx] Loading [S1 Runtime Observer 0.2.0]\n"
    raw += "\n".join("[Info :S1 Runtime Observer] " + module.PREFIX + json.dumps(row) for row in rows)
    log = tmp_path / "current.log"
    log.write_text(raw, encoding="utf-8")
    log_ref = _ref(log)
    source = str(Path(config["owner_config"]["game_root"]) / "BepInEx/LogOutput.log")
    window = {"path": source, "status": "passed", "run_local_sha256": log_ref["sha256"],
              "baseline_size_bytes": 0, "baseline_content_sha256": "initial-log", "baseline_captured_at_ns": 1, "run_local_start_byte": 0}
    process = {"pid": 42, "exited": True, "observed_live": True}
    runner = {"runtime_trust_binding": {"checks": {
        "runtime_process_identity": {"status": "passed", "pid": 42, "launched": True, "liveness_observed": True},
        "current_run_logs": {"status": "passed", "collected_after_process_start": True, "process_pid": 42, "source_windows": [window]}}}}
    prior = config["owner_config"]["expected_prior_plugin_ref"]
    deployment = {"source_path": assembly["path"], "source_sha256": assembly["sha256"], "destination_sha256_after_copy": assembly["sha256"],
                  "destination_path": prior["path"], "destination_sha256_before": prior["sha256"]}
    return {"status": "collected", "candidate_ref": assembly, "protected_files_unchanged": True, "process": process,
        "runner_ref": _save(tmp_path / "runner.json", runner), "log_windows_ref": _save(tmp_path / "windows.json", [window]),
        "deployment_ref": _save(tmp_path / "deployment.json", deployment),
        "restoration_ref": _save(tmp_path / "restore.json", {"restored": True, "process": process}),
        "current_run_logs": [{"source_path": source, "ref": log_ref, "source_window": window}]}


def setup(tmp_path, monkeypatch, *, found=True, source_change=None):
    source = tmp_path / "source"
    source.mkdir()
    observer = source / "Observer.cs"
    original_text = ORIGINAL.read_text(encoding="utf-8")
    observer.write_text(source_change(original_text) if source_change else original_text, encoding="utf-8")
    assembly = source / "S1RuntimeObserver.dll"
    assembly.write_bytes(b"synthetic compiler output; never executed")
    game = tmp_path / "game"
    game.mkdir()
    for name in ("GTFO.exe", "FramePulse.dll", "prior-observer.dll"):
        (game / name).write_bytes(name.encode())
    config = {"schema": "observer-runtime-evaluator.v1", "original_source_ref": _ref(ORIGINAL), "source_filename": "Observer.cs", "expected": EXPECTED,
              "owner_config": {"game_root": str(game), "game_executable_ref": _ref(game / "GTFO.exe"),
                   "expected_prior_plugin_ref": _ref(game / "prior-observer.dll"), "protected_file_refs": [_ref(game / "FramePulse.dll")]}}
    model = tmp_path / "response.txt"
    model.write_text("synthetic raw response")
    context = {"model_response": {"path": str(model), "output_sha256": _ref(model)["sha256"]},
               "materialized_code_identity": {"code_sha256": "identity"}, "implementation_plan_ref": {"plan": "synthetic"},
               "generated_changes": [{"edit_binding_id": "lookup-binding"}], "generated_changes_sha256": "changes", "source_snapshot_sha256": "source"}
    compilation_record = {"status": "passed", "execution_origin": "executed", "all_required_files_compiled": True,
        "materialized_code_identity": context["materialized_code_identity"], "implementation_plan_ref": context["implementation_plan_ref"],
        "model_response_ref": _ref(model), "built_artifact_ref": _ref(assembly), "dependency_binding": None, "dependency_copy": None,
        "isolated_source_root": str(source), "source_inputs_ref": _save(tmp_path / "inputs.json", {"Observer.cs": _ref(observer)["sha256"]}),
        "compile_inputs": [{"path": "Observer.cs", "sha256": _ref(observer)["sha256"]}]}
    compiled = {**compilation_record, "report_ref": _save(tmp_path / "compilation.json", compilation_record)}
    feedback = {"status": "passed", "validation_results": {"full_compilation": {"changed": compiled}}}
    feedback["report_ref"] = _save(tmp_path / "feedback.json", feedback)
    class Compilation:
        def verification_identity(self):
            return {"validator_sha256": "validator", "inputs_sha256": "input", "environment_sha256": "environment"}
        def __call__(self, context):
            return feedback
    evaluator = module.ObserverRuntimeEvaluator(compilation=Compilation(), output_root=tmp_path / "evaluation",
                                                 runtime_configuration_ref=_save(tmp_path / "config.json", config))
    calls = []
    def run(**kwargs):
        calls.append(kwargs)
        return runtime_receipt(tmp_path / ("runtime-" + str(len(calls))), config, kwargs["candidate_ref"], list(records(config, found=found)))
    monkeypatch.setattr(isolated_candidate, "run_isolated_runtime_candidate", run)
    return evaluator, context, calls, compiled, config


def test_bound_runtime_failure_reaches_existing_patch_feedback(tmp_path, monkeypatch):
    evaluator, context, calls, compiled, _ = setup(tmp_path, monkeypatch, found=False)
    report = evaluator(context)
    assert report["status"] == "behavior_failed"
    assert report["failure_owner"] == "patch_implementation"
    assert report["owner_binding_ids"] == ["lookup-binding"]
    assert report["model_response_sha256"] == context["model_response"]["output_sha256"]
    assert report["validation_results"]["runtime"]["status"] == "executed"
    assert len(calls) == 1
    assert report["observations"][0]["observed"]["panel_statuses"] == ["unknown:no_behaviour"]
    details = read_bound_json(report["verification_ref"])
    assert details["built_artifact_ref"] == compiled["built_artifact_ref"]
    assert details["candidate_source_refs"][0]["path"].endswith("Observer.cs")
    assert "GetComponents" not in json.dumps(report)


def test_positive_is_scoped_and_not_complete_readonly_or_keyboard_acceptance(tmp_path, monkeypatch):
    evaluator, context, _, _, _ = setup(tmp_path, monkeypatch)
    report = evaluator(context)
    assert report["status"] == "passed"
    assert report["validation_results"]["runtime"]["uncovered"] == module.UNCOVERED
    assert "not_complete_readonly" in report["verification_scope"]


@pytest.mark.parametrize("change", [
    lambda s: s.replace('panel_found=panelStatus=="observed"', 'panel_found=true'),
    lambda s: s.replace("nextDiscovery=elapsed+0.5;", 'nextDiscovery=elapsed+0.5;\n                Observer.Emit(new {kind="frame",panel_found=true});'),
    lambda s: s.replace("var matches=", "visible=true; var matches="),
])
def test_changed_logging_or_suspicious_lookup_needs_review_not_success(tmp_path, monkeypatch, change):
    evaluator, context, calls, _, _ = setup(tmp_path, monkeypatch, source_change=change)
    report = evaluator(context)
    assert report["status"] == "infrastructure_failed"
    assert report["failure_owner"] == "validator" and report["owner_binding_ids"] == []
    assert report["validation_results"]["runtime"]["status"] == "not_executed"
    assert not calls


@pytest.mark.parametrize("damage", ["hash", "pid", "restoration", "markers_only", "stale_window", "wrong_assembly", "nonincreasing", "missing_load", "missing_frames"])
def test_fake_or_unbound_success_is_infrastructure_failure(tmp_path, monkeypatch, damage):
    evaluator, _, _, compiled, config = setup(tmp_path, monkeypatch)
    rows = list(records(config))
    if damage == "markers_only":
        rows = [{"kind": "frame", "panel_found": True}]
    if damage == "nonincreasing":
        for row in rows:
            if row.get("kind") == "frame":
                row["frame"] = 1
    if damage == "missing_load":
        rows = rows[1:]
    if damage == "missing_frames":
        rows = rows[:2]
    result = runtime_receipt(tmp_path / "receipt", config, compiled["built_artifact_ref"], rows)
    if damage == "hash":
        result["current_run_logs"][0]["ref"]["sha256"] = "bad"
    if damage == "pid":
        result["process"]["pid"] = 900
    if damage == "restoration":
        result["restoration_ref"] = _save(tmp_path / "bad-restore.json", {"restored": False})
    if damage == "stale_window":
        result["current_run_logs"][0]["source_window"]["baseline_captured_at_ns"] = 0
    if damage == "wrong_assembly":
        result["candidate_ref"] = {"path": "unrelated.dll", "sha256": "wrong"}
    _, status, owner = evaluator.assess_runtime_result(result, compiled["built_artifact_ref"], {"path": "test"})
    assert (status, owner) == ("infrastructure_failed", "validator")


@pytest.mark.parametrize("field,value,check", [("alpha", .25, "alpha_preserved"), ("readout", "constant", "readout_changes"),
                                                   ("panel_status", "unknown:no_behaviour", "bound_panel_observed")])
def test_real_field_failures_are_patch_owned(tmp_path, monkeypatch, field, value, check):
    evaluator, _, _, compiled, config = setup(tmp_path, monkeypatch)
    rows = list(records(config))
    for row in rows:
        if row.get("kind") == "frame":
            row[field] = value
    result = runtime_receipt(tmp_path / "receipt", config, compiled["built_artifact_ref"], rows)
    checks, status, owner = evaluator.assess_runtime_result(result, compiled["built_artifact_ref"], {"path": "test"})
    assert (status, owner) == ("behavior_failed", "patch_implementation")
    assert next(row for row in checks if row["check_id"] == "observer." + check)["passed"] is False


def test_original_real_failure_log_remains_failure_without_running_game():
    log = ORIGINAL.parent / "qualification-v2/BepInEx.log"
    rows, errors = module.parse_observer_log(log.read_bytes())
    checks, observed = module.assess_observer_rows(rows, EXPECTED)
    assert errors == 0 and checks["plugin_loaded"] and checks["actual_lateupdate"]
    assert checks["bound_panel_observed"] is False
    assert observed["panel_statuses"] == ["unknown:no_behaviour"]
    assert observed["known_panel_samples"] == 0


def test_source_drift_after_runtime_is_rejected(tmp_path, monkeypatch):
    evaluator, context, _, compiled, config = setup(tmp_path, monkeypatch)
    def run(**kwargs):
        receipt = runtime_receipt(tmp_path / "receipt", config, kwargs["candidate_ref"], list(records(config)))
        Path(compiled["isolated_source_root"], "Observer.cs").write_text("changed while running")
        return receipt
    monkeypatch.setattr(isolated_candidate, "run_isolated_runtime_candidate", run)
    with pytest.raises(ValueError, match="VALIDATION_INPUT_CHANGED"):
        evaluator(context)


def test_source_not_in_actual_compile_manifest_is_rejected(tmp_path, monkeypatch):
    evaluator, _, _, compiled, _ = setup(tmp_path, monkeypatch)
    compiled["compile_inputs"] = []
    with pytest.raises(ValueError, match="CANDIDATE_SOURCE_NOT_COMPILED"):
        evaluator.candidate_source_refs(compiled)


def test_existing_assembly_uses_same_runtime_protocol_and_bound_source(tmp_path, monkeypatch):
    from src.mod_agent.build.dependencies import _binary_tree_snapshot, _binary_tree_snapshot_sha256
    evaluator, _, calls, compiled, _ = setup(tmp_path, monkeypatch, found=False)
    dependency_root = tmp_path / "dependencies"
    dependency_root.mkdir()
    (dependency_root / "dependency.dll").write_bytes(b"synthetic dependency")
    result = evaluator.verify_existing_assembly(candidate_source_ref=_ref(Path(compiled["isolated_source_root"], "Observer.cs")),
        compilation_report_ref=compiled["report_ref"],
        assembly_ref=compiled["built_artifact_ref"], dependency_root=dependency_root,
        expected_dependency_snapshot_sha256=_binary_tree_snapshot_sha256(_binary_tree_snapshot(dependency_root)))
    assert result["status"] == "behavior_failed" and result["compilation_performed"] is False and result["model_calls"] == 0
    assert len(calls) == 1


@pytest.mark.parametrize("mismatch", ["source", "assembly"])
def test_existing_assembly_rejects_independently_hashed_mismatched_inputs(tmp_path, monkeypatch, mismatch):
    evaluator, _, calls, compiled, _ = setup(tmp_path, monkeypatch)
    source_ref = _ref(Path(compiled["isolated_source_root"], "Observer.cs"))
    assembly_ref = compiled["built_artifact_ref"]
    unrelated = tmp_path / ("unrelated.cs" if mismatch == "source" else "unrelated.dll")
    unrelated.write_text("independent, correctly hashed but unrelated artifact")
    if mismatch == "source":
        source_ref = _ref(unrelated)
    else:
        assembly_ref = _ref(unrelated)
    with pytest.raises(ValueError, match="EXISTING_.*COMPILE_BINDING"):
        evaluator.verify_existing_assembly(candidate_source_ref=source_ref, compilation_report_ref=compiled["report_ref"],
            assembly_ref=assembly_ref, dependency_root=tmp_path, expected_dependency_snapshot_sha256="unused")
    assert not calls
