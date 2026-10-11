"""Synthetic receipts exercise real native parsing and the existing verifier admission."""
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent.saved_candidate_reverification import admit_saved_candidate, execute_saved_candidate
from src.mod_agent.saved_patch_admission import _hash
from tests.unit.test_saved_patch_admission import _ref, _save, _snapshot, saved_case


@pytest.fixture
def case(tmp_path):
    request, admitted, journal, _, _ = saved_case(tmp_path)
    values = asdict(request)
    for key in ("feature_spec_ref", "evidence_pack_ref", "implementation_plan_ref"):
        values[key] = getattr(request, key)
    request = SimpleNamespace(**values)
    workspace = Path(request.workspace_root)
    factory = journal["factory_receipt"]
    original_report = factory["patch_agent_loop"]["behavior_evaluations"][-1]
    failure = {**original_report, "status": "infrastructure_failed", "failure_owner": "environment",
        "owner_binding_ids": [], "observations": [{"check_id": "synthetic_environment", "observed": "unavailable"}]}
    failure.pop("report_ref", None)
    report_ref = _save(tmp_path / "failure.json", failure)
    factory["patch_agent_loop"]["behavior_evaluations"] = [{**failure, "report_ref": report_ref}]
    factory["status"] = "failed"
    text = Path(factory["model_response"]["path"]).read_bytes().decode("utf-8")
    factory["worker_turns"] = [{"status": "responded", "response_ref": _save(tmp_path / "turn.json", {
        "content": text, "model": factory["model_response"]["model"], "tool_calls": []})}]
    terminal = journal["terminal_result"]
    terminal.update(terminal_stage="generate_patch_proposal", patch_proposal_artifact=None,
        proposal_review_artifact=None, dry_run_artifact=None)
    terminal["execution_counts"].update(apply=0, build=0, runtime=0, dry_run=0)
    journal.update(proposal_admitted=False, terminal_result_sha256=_hash(terminal))
    budget = journal["shared_model_budget"]
    budget["policy"] = "task_total_only"
    budget["by_stage"] = {key: {"consumed": row["consumed"]} for key, row in budget["by_stage"].items()}
    parent = json.loads((workspace / "run_result.json").read_bytes())
    parent["model_call_budget"] = deepcopy(budget)
    from src.mod_agent.product_executor import source_snapshot
    from src.mod_agent.fresh_planning_continuation import _csharp_source_snapshot
    target = workspace / "generated_mods/SyntheticMod"
    parent["initial_isolated_source_snapshot"] = source_snapshot(target)
    admitted = replace(admitted, source_tree_snapshot=_csharp_source_snapshot(target))
    source_ref = _save(tmp_path / "candidate.json", journal)
    parent["patch_execution_receipts"] = [source_ref]
    parent_ref = _save(workspace / "run_result.json", parent)
    manifest = json.loads((workspace / "run_manifest.json").read_bytes())
    manifest["nuget_isolated_build_profile"] = {"working_directory": str(target)}
    manifest["terminal_record"] = parent_ref
    manifest_ref = _save(workspace / "run_manifest.json", manifest)
    request.candidate_reverification_selection = {"source_attempt_ref": source_ref,
        "parent_manifest_ref": manifest_ref, "parent_result_ref": parent_ref}
    evaluator = tmp_path / "synthetic_evaluator.py"
    evaluator.write_text('''import json, hashlib
from pathlib import Path
def build(output_root, status="passed", damage=None):
    root=Path(output_root)
    def evaluate(context):
        count=root/"calls.txt"
        count.write_text(str(int(count.read_text())+1) if count.exists() else "1")
        report={"status":status,"failure_owner":None if status=="passed" else "environment",
            "owner_binding_ids":[],"observations":[],"execution_origin":"executed",
            "generated_changes_sha256":context["generated_changes_sha256"],
            "source_snapshot_sha256":context["source_snapshot_sha256"],
            "materialized_code_identity":context["materialized_code_identity"],
            "model_response_sha256":context["model_response"]["output_sha256"]}
        if damage=="source":report["source_snapshot_sha256"]="0"*64
        if damage=="code":report["materialized_code_identity"]={"code_sha256":"0"*64}
        if damage=="origin":report["execution_origin"]="incomplete"
        path=root/"executed-report.json"
        path.write_text(json.dumps(report))
        report["report_ref"]={"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
        if damage=="hash":report["report_ref"]["sha256"]="0"*64
        return report
    return evaluate
''', encoding="utf-8")
    from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
    configuration = {"schema_version": "patch_worker_configuration_v1", "policy": asdict(PatchAgentLoopPolicy()),
        "enable_recovery_loop": True, "behavior_evaluator": {"factory_ref": _ref(evaluator),
            "factory_name": "build", "kwargs": {"output_root": str(tmp_path)}}}
    request.worker_configuration_ref = _save(tmp_path / "reverification.json", configuration)
    request.worker_profile_sha256 = _hash(factory["profile"])
    return request, admitted, journal


def _rewrite_journal(case):
    request, _, journal = case
    selection = request.candidate_reverification_selection
    selection["source_attempt_ref"] = _save(Path(selection["source_attempt_ref"]["path"]), journal)
    parent = json.loads(Path(selection["parent_result_ref"]["path"]).read_bytes())
    parent["patch_execution_receipts"] = [selection["source_attempt_ref"]]
    selection["parent_result_ref"] = _save(Path(selection["parent_result_ref"]["path"]), parent)
    manifest = json.loads(Path(selection["parent_manifest_ref"]["path"]).read_bytes())
    manifest["terminal_record"] = selection["parent_result_ref"]
    selection["parent_manifest_ref"] = _save(Path(selection["parent_manifest_ref"]["path"]), manifest)


def test_admission_is_read_only_and_inherits_task_total_budget(case, tmp_path, monkeypatch):
    from src.mod_agent.patch_worker_configuration import _LazyBehaviorEvaluator
    request, admitted, journal = case
    before = _snapshot(tmp_path)
    monkeypatch.setattr(_LazyBehaviorEvaluator, "_construct", lambda *a: pytest.fail("pure admission constructs no evaluator"))
    result = admit_saved_candidate(request, admitted)
    assert result["inherited_model_budget"] == journal["shared_model_budget"]
    assert result["inherited_model_budget"]["policy"] == "task_total_only"
    assert result["changes"][0]["generation"]["new_model_calls"] == 0
    assert result["changes"][0]["generation"]["response_origin"] == "verified_prior_response"
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("damage", ["response", "source", "failure_status", "failure_code", "budget", "profile", "terminal", "selected"])
def test_admission_rejects_changed_identity(case, damage):
    request, admitted, journal = case
    if damage == "response":
        Path(journal["factory_receipt"]["model_response"]["path"]).write_text("{}")
    elif damage == "source":
        path = Path(request.workspace_root) / admitted.source_validation["files"][0]["source_path"]
        path.write_bytes(path.read_bytes() + b"\n// drift")
    elif damage == "failure_status":
        journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][-1]["status"] = "passed"
    elif damage == "failure_code":
        journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"][-1]["materialized_code_identity"]["code_sha256"] = "0"*64
    elif damage == "budget":
        journal["shared_model_budget"]["consumed"] += 1
    elif damage == "profile":
        request.worker_profile_sha256 = "0"*64
    elif damage == "terminal":
        journal["terminal_result"]["execution_counts"]["apply"] = 1
        journal["terminal_result_sha256"] = _hash(journal["terminal_result"])
    elif damage == "selected":
        journal["selected_artifacts"]["implementation_plan"]["artifact_hash"] = "0"*64
    _rewrite_journal(case)
    with pytest.raises(ValueError):
        admit_saved_candidate(request, admitted)


@pytest.mark.parametrize("damage", [None, "source", "hash", "origin", "failed", "code"])
def test_execution_uses_existing_verifier_admission_and_records_failure(case, tmp_path, monkeypatch, damage):
    from src.mod_agent.local_entry import LocalOllamaInitialPatchAdapter
    from src.mod_agent.errors import LocalEntryError
    request, admitted, _ = case
    configuration = json.loads(Path(request.worker_configuration_ref["path"]).read_bytes())
    if damage == "failed":
        configuration["behavior_evaluator"]["kwargs"]["status"] = "infrastructure_failed"
    elif damage:
        configuration["behavior_evaluator"]["kwargs"]["damage"] = damage
    request.worker_configuration_ref = _save(Path(request.worker_configuration_ref["path"]), configuration)
    monkeypatch.setattr(LocalOllamaInitialPatchAdapter, "__call__", lambda *a: pytest.fail("no model factory invocation"))
    events = []
    if damage:
        with pytest.raises((ValueError, LocalEntryError)):
            execute_saved_candidate(request, admitted, events.append)
        assert events[-1]["factory_receipt"]["status"] == "reverification_failed"
    else:
        result = execute_saved_candidate(request, admitted, events.append)
        assert result["model_calls_performed"] == 0
        assert result["verifier_executions_performed"] == 1
        assert result["worker_receipt"]["status"] == "reverification_passed"
        assert result["changes"][0]["generation"]["patch_agent_loop"]["behavior_evaluation_refs"][0]["status"] == "passed"
    assert (tmp_path / "calls.txt").read_text() == "1"
    assert all(event["model_call_count"] == 0 for event in events)
