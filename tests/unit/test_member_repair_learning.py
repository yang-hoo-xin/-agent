import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build.dependencies import _binary_tree_snapshot, _binary_tree_snapshot_sha256
from src.mod_agent.planning.member_repair_learning import (
    extract_member_repair,
    file_ref,
    import_candidate,
)
from src.mod_agent.planning.memory_dependency_context import dependency_memory_context
from src.mod_agent.planning.task_memory import TaskMemory


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return file_ref(path)


def inputs(tmp_path):
    run = tmp_path / "run"
    dependency = run / "build_dependencies/GameFolder"
    dependency.mkdir(parents=True)
    (dependency / "Library.dll").write_bytes(b"fixture dependency bytes")
    snapshot = _binary_tree_snapshot(dependency)
    digest = _binary_tree_snapshot_sha256(snapshot)
    binding = {"binding_version": "run_local_game_folder_binding_v1", "snapshot_sha256": digest, "file_count": 1}
    copy = {"isolated_copy": str(dependency), "copy_snapshot_sha256": digest, "source_snapshot_sha256": digest,
            "copy_file_count": 1, "source_file_count": 1, "build_uses_isolated_copy": True,
            "binding_version": "run_local_game_folder_binding_v1"}
    before, after = 'logger.Info("text");', 'logger.LogInfo("text");'
    source = run / "generated_mods/Example/Plugin.cs"
    source.parent.mkdir(parents=True)
    source.write_text(after, encoding="utf-8")
    assembly = run / "candidate.dll"
    assembly.write_bytes(b"unit test compiled assembly placeholder")
    reports = []
    for index, text in enumerate((before, after)):
        code_hash = hashlib.sha256(text.encode()).hexdigest()
        response = save(run / f"response{index}.json", {"changes": [{"edit_binding_id": "one", "after_text": text}]})
        report = {"status": "compilation_failed" if index == 0 else "passed", "all_required_files_compiled": True,
            "source_compilation_errors": [{"code": "CS1061", "file": "Plugin.cs", "source_sha256": code_hash,
                "message": "'ManualLogSource' does not contain a definition for 'Info'"}] if index == 0 else [],
            "materialized_code_identity": {"baseline_sha256": "baseline", "code_sha256": code_hash,
                                           "files": ["generated_mods/Example/Plugin.cs"]},
            "dependency_binding": binding, "dependency_copy": copy, "model_response_ref": response,
            "source_inputs_ref": save(run / f"inputs{index}.json", {"Plugin.cs": code_hash}),
            "built_artifact_ref": file_ref(assembly) if index == 1 else None}
        reports.append(report)
    journal = {"parent_product_run_id": "run", "factory_receipt": {"model_identity": {"digest": "d" * 64},
        "patch_agent_loop": {"behavior_evaluations": [{"materialized_code_identity": report["materialized_code_identity"],
            "model_response_sha256": report["model_response_ref"]["sha256"], "callback_invoked": True,
            "execution_origin": "executed"} for report in reports]}}}
    cases = []
    for index in range(3):
        request_ref = save(run / f"case{index}-request.json", {"assembly": file_ref(assembly)})
        stdout_ref = save(run / f"case{index}-stdout.json", {"status": "observed",
            "assembly_sha256": file_ref(assembly)["sha256"]})
        stderr = run / f"case{index}-stderr.log"
        stderr.write_text("", encoding="utf-8")
        cases.append({"case": str(index), "exit_code": 0, "checks": {"configuration": True, "logging": True},
                      "request_ref": request_ref, "stdout_ref": stdout_ref, "stderr_ref": file_ref(stderr)})
    save(run / "run_manifest.json", {"request": "Log a startup message"})
    return {"journal_ref": save(run / "a/cr/journal.json", journal),
        "failed_report_ref": save(run / "failed.json", reports[0]), "passed_report_ref": save(run / "passed.json", reports[1]),
        "recurrence_report_ref": save(run / "recurrence.json", reports[0]),
        "delivery_ref": save(run / "delivery.json", {"status": "delivered", "delivery_complete": True,
            "acceptance_passed": True, "evidence_refs": [file_ref(assembly)]}),
        "formal_checks_ref": save(run / "formal.json", {"status": "passed", "assembly_ref": file_ref(assembly), "cases": cases}),
        "dependency_relative_path": "Library.dll"}, copy


def test_automatic_candidate_and_version_bound_memory(tmp_path):
    selected, binding = inputs(tmp_path)
    candidate = extract_member_repair(**selected)
    assert candidate["member_substitution"] == {"receiver_type": "ManualLogSource", "receiver_expression": "logger",
                                                "failed_member": "Info", "passed_member": "LogInfo"}
    assert candidate["xml_member_presence_inferred"] is False
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    ref = save(tmp_path / "candidate.json", candidate)
    recorded = import_candidate(memory, candidate_ref=ref)
    assert import_candidate(memory, candidate_ref=ref) == recorded
    context, observation = dependency_memory_context(workspace_root=tmp_path / "run", binding=binding)
    context["model_digest"] = "d" * 64
    assert observation["status"] == "verified" and observation["files"][0]["path"].endswith("Library.dll")
    assert memory.retrieve("Log startup message", context)["relevant_lessons"]
    context["dependency_dll_sha256:Library.dll"] = "f" * 64
    assert not memory.retrieve("Log startup message", context)["relevant_lessons"]
    (tmp_path / "run/build_dependencies/GameFolder/Library.dll").write_bytes(b"changed")
    context, observation = dependency_memory_context(workspace_root=tmp_path / "run", binding=binding)
    assert context == {} and observation["status"] == "unavailable"


@pytest.mark.parametrize("change", ["failed_hash", "unrelated_code", "not_passed", "formal_failed", "wrong_order", "different_dependency"])
def test_unbound_or_nonisolated_claims_are_rejected(tmp_path, change):
    selected, _ = inputs(tmp_path)
    if change == "failed_hash":
        Path(selected["failed_report_ref"]["path"]).write_text("{}")
    elif change == "unrelated_code":
        report = json.loads(Path(selected["passed_report_ref"]["path"]).read_text())
        response = json.loads(Path(report["model_response_ref"]["path"]).read_text())
        response["changes"][0]["after_text"] += " additional();"
        report["model_response_ref"] = save(Path(report["model_response_ref"]["path"]), response)
        selected["passed_report_ref"] = save(Path(selected["passed_report_ref"]["path"]), report)
    else:
        key = {"not_passed": "passed_report_ref", "formal_failed": "formal_checks_ref", "wrong_order": "journal_ref",
               "different_dependency": "recurrence_report_ref"}[change]
        value = json.loads(Path(selected[key]["path"]).read_text())
        if change == "not_passed":
            value["status"] = "failed"
        elif change == "formal_failed":
            value["cases"][0]["checks"]["logging"] = False
        elif change == "wrong_order":
            value["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"].reverse()
        else:
            value["dependency_binding"]["snapshot_sha256"] = "0" * 64
        selected[key] = save(Path(selected[key]["path"]), value)
    with pytest.raises(ValueError):
        extract_member_repair(**selected)


def test_candidate_tampering_cannot_be_imported_as_automatic_experience(tmp_path):
    selected, _ = inputs(tmp_path)
    candidate = extract_member_repair(**selected)
    candidate["member_substitution"]["passed_member"] = "InventedAPI"
    ref = save(tmp_path / "candidate.json", candidate)
    with pytest.raises(ValueError, match="NOT_REPRODUCIBLE"):
        import_candidate(TaskMemory(ArtifactStore(tmp_path / "memory")), candidate_ref=ref)


def test_transfer_oracle_does_not_accept_wrong_level_or_default():
    from src.mod_agent.domain.logging_transfer_evaluator import assess_logging_transfer
    case = {"entries": {"General.Enabled": False, "General.Message": "Ready"},
            "logs": [{"level": "Warning", "message": "Startup disabled"}]}
    defaults = {"General.Enabled": True, "General.Message": "Ready"}
    observation = {"status": "observed", "plugin_load_calls": 1, "plugin_instance_constructor_skipped": True,
        "injected_base_properties": ["Config", "Log"], "assembly_sha256": "a" * 64,
        "log_capture": "real_bepinex_global_listener_including_injected_base_log_source",
        "entries": [{"section": "General", "key": key, "value": case["entries"]["General." + key],
                     "default_value": defaults["General." + key], "value_type": kind}
                    for key, kind in (("Enabled", "System.Boolean"), ("Message", "System.String"))],
        "logs": case["logs"]}
    def assess():
        return assess_logging_transfer(observation, case=case, defaults=defaults, assembly_sha256="a" * 64)
    assert all(assess().values())
    observation["logs"] = [{"level": "Info", "message": "Startup disabled"}]
    assert assess()["logging"] is False
    observation["entries"][0]["default_value"] = False
    assert assess()["configuration"] is False


def test_planning_owner_adds_only_verified_dependency_context(tmp_path):
    from src.mod_agent.planning.model_selection import ModelPlanningTargetSelector
    selected, binding = inputs(tmp_path)
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    import_candidate(memory, candidate_ref=save(tmp_path / "candidate.json", extract_member_repair(**selected)))
    selector = ModelPlanningTargetSelector(client=SimpleNamespace(model="fixture", provider="fixture"),
        workspace_root=tmp_path / "run", receipt_path=tmp_path / "receipt.json", task_memory=memory,
        dependency_binding=binding, model_identity={"digest": "d" * 64})
    feature = {"target_mod": "DifferentMod", "user_request": "Log a startup message"}
    assert selector._prepare_task_memory(feature, []) is not None
    assert selector._task_memory_receipt["dependency_observation"]["status"] == "verified"
    (tmp_path / "run/build_dependencies/GameFolder/Library.dll").write_bytes(b"different DLL")
    assert selector._prepare_task_memory(feature, []) is None
    assert selector._task_memory_receipt["dependency_observation"]["status"] == "unavailable"
