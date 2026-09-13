"""Real temporary target writes with injected filesystem failures; no model/Build.

The Graph test uses its production nodes/edges with an in-memory recording Store;
it proves failure fact propagation and routing, not Artifact admission or delivery.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import src.mod_agent.execution.patch_apply as owner
from src.mod_agent.artifacts import ArtifactRef


@pytest.fixture
def two_files(tmp_path):
    root = tmp_path / "targets"
    root.mkdir()
    paths = [root / "A.cs", root / "B.cs"]
    before = {path.name: f"public static class {path.stem} {{ public static int Value => 1; }}\n".encode()
              for path in paths}
    after = {name: raw.replace(b"=> 1", b"=> 2") for name, raw in before.items()}
    for path in paths:
        path.write_bytes(before[path.name])
    plan = {"binding_registry": {"edit_bindings": [
        {"binding_id": f"edit_{path.stem}", "canonical_target_path": path.name,
         "source_hash": hashlib.sha256(before[path.name]).hexdigest(),
         "target_span": {"start_line": 1, "end_line": 1}}
        for path in paths]}}
    proposal = {"feature_id": "feature_partial", "proposal_id": "proposal_partial", "diff_intent": [
        {"change_id": f"change_{path.stem}", "edit_binding_id": f"edit_{path.stem}",
         "patch": {"kind": "exact_text_replace", "before_text": "=> 1", "after_text": "=> 2",
                   "expected_occurrences": 1}} for path in paths]}
    review = {"decision": "approve_dry_run", "allowed_next_stage": "dry_run_apply"}
    applier = owner.ExactTextPatchApplier()
    args = dict(workspace_root=root, proposal=proposal, implementation_plan=plan, review=review)
    dry = applier.run(**args, allow_write=False)
    assert {path.name: path.read_bytes() for path in paths} == before
    return dict(root=root, paths=paths, before=before, after=after, args=args, dry=dry, applier=applier)


def _inject_replace(monkeypatch, case, *, name, after_replace):
    original_replace = owner.os.replace
    error = OSError("injected target replacement failure")
    calls = []
    def replace(source, destination):
        target = Path(destination)
        if target in case["paths"]:
            calls.append(target.name)
            if target.name == name:
                if after_replace:
                    original_replace(source, destination)
                raise error
        return original_replace(source, destination)
    monkeypatch.setattr(owner.os, "replace", replace)
    return error, calls


def _apply(case):
    return case["applier"].run(**case["args"], allow_write=True, approved_diff_hash=case["dry"]["diff_hash"])


def _observations(details, case):
    assert isinstance(details["write_failure"]["operation"], str) and details["write_failure"]["operation"]
    rows = {row["path"]: row for row in details["write_failure"]["file_observations"]}
    assert set(rows) == {"A.cs", "B.cs"}
    for name, row in rows.items():
        assert row["before_sha256"] == hashlib.sha256(case["before"][name]).hexdigest()
        assert row["expected_after_sha256"] == hashlib.sha256(case["after"][name]).hexdigest()
    return rows


@pytest.mark.parametrize("after_replace", [False, True], ids=["before_effect", "after_effect"])
def test_second_replace_failure_records_confirmed_first_file_without_retry(two_files, monkeypatch, after_replace):
    error, calls = _inject_replace(monkeypatch, two_files, name="B.cs", after_replace=after_replace)
    with pytest.raises(OSError) as caught:
        _apply(two_files)
    assert caught.value is error
    details = error.patch_apply_failure
    assert details["actual_write_performed"] is True
    assert details["real_patch_applied"] is False
    assert details["changed_files"] == ["A.cs"] and details["write_completion"] == "partial"
    rows = _observations(details, two_files)
    assert rows["A.cs"]["replacement_status"] == "confirmed" and rows["A.cs"]["target_state"] == "expected"
    assert rows["B.cs"]["replacement_status"] == "uncertain"
    assert rows["B.cs"]["target_state"] == ("expected" if after_replace else "baseline")
    assert rows["B.cs"]["observed_sha256"] == hashlib.sha256(
        (two_files["after"] if after_replace else two_files["before"])["B.cs"]).hexdigest()
    assert calls == ["A.cs", "B.cs"]
    assert (two_files["root"] / "A.cs").read_bytes() == two_files["after"]["A.cs"]
    assert (two_files["root"] / "B.cs").read_bytes() == (two_files["after"] if after_replace else two_files["before"])["B.cs"]


def test_replace_that_changes_first_target_then_raises_remains_unknown(two_files, monkeypatch):
    error, calls = _inject_replace(monkeypatch, two_files, name="A.cs", after_replace=True)
    with pytest.raises(OSError) as caught:
        _apply(two_files)
    assert caught.value is error
    details = error.patch_apply_failure
    assert details["actual_write_performed"] is None
    assert details["real_patch_applied"] is False and details["changed_files"] == []
    assert details["write_completion"] == "unknown"
    rows = _observations(details, two_files)
    assert rows["A.cs"]["replacement_status"] == "uncertain" and rows["A.cs"]["target_state"] == "expected"
    assert rows["B.cs"]["replacement_status"] == "not_attempted" and rows["B.cs"]["target_state"] == "baseline"
    assert calls == ["A.cs"]


def test_target_readback_failure_keeps_returned_replacements_but_not_complete_claim(two_files, monkeypatch):
    original_replace, original_read = owner.os.replace, Path.read_bytes
    confirmed = []
    error = OSError("injected target readback failure")
    def replace(source, destination):
        result = original_replace(source, destination)
        if Path(destination) in two_files["paths"]:
            confirmed.append(Path(destination).name)
        return result
    def read(path):
        if path == two_files["root"] / "B.cs" and "B.cs" in confirmed:
            raise error
        return original_read(path)
    monkeypatch.setattr(owner.os, "replace", replace)
    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(OSError) as caught:
        _apply(two_files)
    assert caught.value is error
    details = error.patch_apply_failure
    assert details["actual_write_performed"] is True and details["real_patch_applied"] is False
    assert details["changed_files"] == ["A.cs", "B.cs"] and details["write_completion"] == "partial"
    rows = _observations(details, two_files)
    assert rows["B.cs"]["replacement_status"] == "confirmed"
    assert rows["B.cs"]["target_state"] == "unreadable" and rows["B.cs"]["observed_sha256"] is None
    assert confirmed == ["A.cs", "B.cs"]
    assert original_read(two_files["root"] / "B.cs") == two_files["after"]["B.cs"]


def test_temporary_write_failure_before_first_replace_confirms_no_target_write(two_files, monkeypatch):
    original_write = Path.write_bytes
    temporary = (two_files["root"] / "A.cs").with_name(".A.cs.v2-codegen.tmp")
    error = OSError("injected temporary write failure")
    def write(path, content):
        if path == temporary:
            raise error
        return original_write(path, content)
    monkeypatch.setattr(Path, "write_bytes", write)
    monkeypatch.setattr(owner.os, "replace", lambda *args: pytest.fail("No replace before temporary file exists."))
    with pytest.raises(OSError) as caught:
        _apply(two_files)
    assert caught.value is error
    details = error.patch_apply_failure
    assert details["actual_write_performed"] is False and details["changed_files"] == []
    assert details["real_patch_applied"] is False and details["write_completion"] == "not_started"
    assert all(row["replacement_status"] == "not_attempted" and row["target_state"] == "baseline"
               for row in _observations(details, two_files).values())
    assert {path.name: path.read_bytes() for path in two_files["paths"]} == two_files["before"]


def test_complete_apply_keeps_the_existing_success_contract(two_files):
    result = _apply(two_files)
    assert result["actual_write_performed"] is True and result["real_patch_applied"] is True
    assert result["changed_files"] == ["A.cs", "B.cs"]
    assert result["approved_diff_hash"] == two_files["dry"]["diff_hash"]
    assert {path.name: path.read_bytes() for path in two_files["paths"]} == two_files["after"]


class _RecordingStore:
    """Records the node's real output; deliberately does not model Store admission."""
    def __init__(self, root, payloads):
        from src.mod_agent.artifacts.registry import ArtifactTypeRegistry
        self.root, self.payloads, self.writes = root, deepcopy(payloads), []
        self.registry = ArtifactTypeRegistry()
    def read(self, reference):
        return {"data": deepcopy(self.payloads[reference.artifact_type])}
    def write(self, **arguments):
        self.writes.append(deepcopy(arguments))
        kind = arguments["artifact_type"]
        self.payloads[kind] = deepcopy(arguments["payload"])
        return ArtifactRef(feature_id=arguments["feature_id"], artifact_type=kind,
            path=str(self.root / (kind + ".json")), artifact_hash=hashlib.sha256(
                json.dumps(arguments["payload"], sort_keys=True).encode()).hexdigest())


@pytest.mark.parametrize("first_unknown", [False, True], ids=["partial", "unknown"])
def test_production_graph_failure_facts_block_build_and_do_not_retry(two_files, monkeypatch, first_unknown):
    from src.mod_agent.workflow.graph import build_graph
    from src.mod_agent.workflow.state import create_initial_state
    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
    payloads = {"patch_proposal": two_files["args"]["proposal"],
        "implementation_plan": two_files["args"]["implementation_plan"],
        "proposal_review": two_files["args"]["review"], "dry_run_result": two_files["dry"]}
    store = _RecordingStore(two_files["root"], payloads)
    state = create_initial_state(run_id="partial-run", request_id="partial-request", user_request="change both values",
                                 confirmed_isolated_write=True)
    state.update(feature_id="feature_partial", current_stage="dry_run_apply",
        artifacts={kind: str(store.root / (kind + ".json")) for kind in payloads},
        artifact_hashes={kind: "a" * 64 for kind in payloads})
    error, calls = _inject_replace(monkeypatch, two_files,
        name="A.cs" if first_unknown else "B.cs", after_replace=first_unknown)
    def apply(proposal, implementation, review):
        assert proposal == two_files["args"]["proposal"] and implementation == two_files["args"]["implementation_plan"]
        assert review == two_files["args"]["review"]
        return _apply(two_files)
    graph = build_graph(store, isolated_apply_factory=apply,
        build_result_factory=lambda *args: pytest.fail("Failed Apply must not enter Build."),
        checkpointer=WorkflowCheckpointStore.langgraph_memory_checkpointer())
    config = {"configurable": {"thread_id": "partial-run"}}
    restored = graph.update_state(config, state, as_node="dry_run_apply")
    finished = graph.invoke(None, restored)
    written = next(item for item in store.writes if item["artifact_type"] == "isolated_apply_result")
    assert written["status"] == "failed"
    assert written["payload"]["actual_write_performed"] is (None if first_unknown else True)
    assert written["payload"]["real_patch_applied"] is False
    assert written["payload"]["changed_files"] == ([] if first_unknown else ["A.cs"])
    assert written["payload"]["write_completion"] == ("unknown" if first_unknown else "partial")
    assert written["payload"]["write_failure"] == error.patch_apply_failure["write_failure"]
    assert any(blocker["code"] == "ISOLATED_APPLY_FAILED" for blocker in finished["blockers"])
    assert calls == (["A.cs"] if first_unknown else ["A.cs", "B.cs"])
    assert not any(item["artifact_type"] in {"build_result", "workflow_checkpoint"} for item in store.writes)


def test_unannotated_apply_exception_has_unknown_not_zero_effect():
    error = OSError("unmeasured adapter failure")
    details = owner.patch_apply_failure_details(error)
    assert details["actual_write_performed"] is None
    assert details["real_patch_applied"] is False and details["changed_files"] == []
    assert details["write_completion"] == "unknown"
