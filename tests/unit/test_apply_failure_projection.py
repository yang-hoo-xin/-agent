"""Default entry and persistent result keep observed Apply effects, without models."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.mod_agent import local_entry
from src.mod_agent.execution.patch_apply import attach_patch_apply_failure
from tests.unit import test_mod_agent_cli as public_fixture


@pytest.mark.parametrize("values,started,expected", [
    ([], 0, False), ([], 1, None), ([False], 1, False), ([None], 1, None),
    ([True, None], 2, True), ([False], 2, None), ([1], 1, None),
])
def test_product_summary_does_not_coerce_unknown_or_missing_apply_into_zero(values, started, expected):
    events = [SimpleNamespace(effect_role="isolated_apply", event_status="started") for _ in range(started)]
    assert local_entry._observed_product_write_status(
        [{"actual_write_performed": value} for value in values], events) is expected


@pytest.mark.parametrize("value,completion,paths", [(None, "unknown", []), (True, "partial", ["A.cs"])])
def test_failure_result_and_manifest_keep_executor_effects(tmp_path, value, completion, paths):
    manifest = tmp_path / "run_manifest.json"
    manifest.write_text(json.dumps({"run_id": "run", "request_id": "request"}), encoding="utf-8")
    error = OSError("filesystem operation failed")
    attach_patch_apply_failure(error, {"actual_write_performed": value, "real_patch_applied": False,
        "changed_files": paths, "write_completion": completion,
        "write_failure": {"operation": "replace", "file_observations": []}})
    failure = local_entry._persist_graph_terminal_failure(run_root=tmp_path, run_id="run", request_id="request",
        error=error, model_call_count=2)
    stored = json.loads(manifest.read_text(encoding="utf-8"))
    assert failure["actual_write_performed"] is stored["actual_write_performed"] is value
    assert failure["changed_files"] == stored["changed_files"] == paths
    assert failure["write_completion"] == stored["write_completion"] == completion
    raw = Path(stored["terminal_record"]["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == stored["terminal_record"]["sha256"]


@pytest.mark.parametrize("mode,expected", [("unconfirmed_replace", None), ("confirmed_unreadable", True)])
def test_public_request_keeps_apply_failure_state_and_skips_final_build(tmp_path, monkeypatch, capsys, mode, expected):
    """Original public fixture: model/compile doubles, actual source writes and Graph."""
    real_replace, real_read = os.replace, Path.read_bytes
    failed_target = []
    calls = []

    def replace(source, target):
        result = real_replace(source, target)
        if Path(source).name == "." + Path(target).name + ".v2-codegen.tmp":
            calls.append(str(target))
            failed_target.append(Path(target))
            if mode == "unconfirmed_replace":
                raise OSError("replace result uncertain")
        return result

    def read(path):
        if mode == "confirmed_unreadable" and path in failed_target:
            raise OSError("target cannot be read after replacement")
        return real_read(path)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr("socket.socket.connect", lambda *args, **kwargs: pytest.fail("No network/model calls."))
    original_main = public_fixture.main
    observed = []

    class Finished(Exception):
        pass

    def main(arguments):
        exit_code = original_main(arguments)
        observed.append((exit_code, json.loads(capsys.readouterr().out)))
        raise Finished

    monkeypatch.setattr(public_fixture, "main", main)
    with pytest.raises(Finished):
        public_fixture.test_cli_run_request_real_public_product_executor_compile_success(tmp_path, monkeypatch, capsys)
    exit_code, result = observed[0]
    assert exit_code == 1 and result["actual_write_performed"] is expected
    assert result["apply_write_details"][0]["actual_write_performed"] is expected
    assert len(calls) == 1 and "PRODUCT_TEST_CHANGE" in real_read(failed_target[0]).decode("utf-8")
    machine = result["product_execution_result"]
    assert machine["execution_disposition"] != "succeeded"
    assert any(item["code"] == "ISOLATED_APPLY_FAILED" for item in result["blockers"])
    assert not any(item["artifact_role"] in {"build_result", "workflow_checkpoint"} for item in machine["outputs"])
    manifest = json.loads((Path(result["run_root"]) / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["actual_write_performed"] is expected


def test_apply_receipt_persistence_failure_keeps_confirmed_target_effects(tmp_path):
    from src.mod_agent.workflow.graph import _run_isolated_apply
    from src.mod_agent.workflow.state import create_initial_state
    from tests.unit.test_partial_apply_failure import _RecordingStore

    class FailingStore(_RecordingStore):
        def write(self, **arguments):
            raise OSError("Apply receipt cannot be persisted")

    source = tmp_path / "A.cs"
    source.write_text("before", encoding="utf-8")
    payloads = {"patch_proposal": {"feature_id": "feature_partial"},
                "implementation_plan": {}, "proposal_review": {}, "dry_run_result": {}}
    store = FailingStore(tmp_path, payloads)
    state = create_initial_state(run_id="run", request_id="request", user_request="change value",
                                 confirmed_isolated_write=True)
    state.update(feature_id="feature_partial",
        artifacts={kind: str(tmp_path / (kind + ".json")) for kind in payloads},
        artifact_hashes={kind: "a" * 64 for kind in payloads})

    def apply(*args):
        source.write_text("after", encoding="utf-8")
        return {"actual_write_performed": True, "real_patch_applied": True, "changed_files": ["A.cs"]}

    with pytest.raises(OSError, match="receipt cannot be persisted") as caught:
        _run_isolated_apply(state, store, isolated_apply_factory=apply)
    assert source.read_text(encoding="utf-8") == "after"
    assert caught.value.patch_apply_failure["actual_write_performed"] is True
    assert caught.value.patch_apply_failure["changed_files"] == ["A.cs"]
    assert caught.value.patch_apply_failure["write_failure"]["operation"] == "result_persistence"


@pytest.mark.parametrize("mode", ["resume", "stdin"])
def test_approval_cli_exception_preserves_confirmed_files(tmp_path, monkeypatch, capsys, mode):
    import io
    from src.mod_agent import cli, reviewed_patch_continuation

    error = OSError("result persistence failed after target write")
    attach_patch_apply_failure(error, {"actual_write_performed": True, "real_patch_applied": False,
        "changed_files": ["A.cs"], "write_completion": "partial",
        "write_failure": {"operation": "result_persistence", "file_observations": []}})

    def fail(**kwargs):
        raise error

    if mode == "resume":
        decision = tmp_path / "decision.json"
        decision.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(reviewed_patch_continuation, "resume_deferred_approval", fail)
        monkeypatch.setattr(cli, "_load_reviewed_build_resume", lambda path: object())
        arguments = ["apply-patch", "--resume-approval", "--artifact-store-root", str(tmp_path),
            "--feature-id", "feature_partial", "--checkpoint-path", str(tmp_path / "checkpoint.json"),
            "--checkpoint-hash", "a" * 64, "--resume-payload", str(tmp_path / "resume.json"),
            "--human-semantic-decision", str(decision)]
    else:
        monkeypatch.setattr(reviewed_patch_continuation, "apply_reviewed_patch", fail)
        monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"displayed_binding": {}, "human_semantic_decision": {}})))
        arguments = ["apply-patch", "--confirm", "--human-decision-stdin", "--artifact-store-root", str(tmp_path),
            "--workspace-root", str(tmp_path), "--feature-id", "feature_partial", "--run-id", "run_partial",
            "--isolated-root", str(tmp_path / "isolated")]
    cli.main(arguments)
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked" and result["product_source_writes_performed"] is True
    assert result["apply_write_details"]["changed_files"] == ["A.cs"]
    assert result["apply_write_details"]["write_completion"] == "partial"
