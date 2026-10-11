"""One preregistered real-process exit after durable Apply, before its CLI response.

Uses existing deterministic preparation and Build fixtures with real source writes,
Graph, approval and ArtifactStore. This is not arbitrary crash/power-loss recovery.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXIT_AFTER_DURABLE_APPLY = 73


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): digest(p) for p in root.rglob("*") if p.is_file()}


def archive_sandbox(sandbox, output):
    """Retain exact bytes in a ZIP to avoid deep Windows destination paths."""
    sandbox, output = Path(sandbox), Path(output)
    expected = inventory(sandbox)
    archive = output / "retained_sandbox.zip"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as bundle:
        for relative in sorted(expected):
            bundle.write(sandbox / relative, arcname=relative)
    with ZipFile(archive) as bundle:
        observed = {name: hashlib.sha256(bundle.read(name)).hexdigest() for name in bundle.namelist()}
    if observed != expected or inventory(sandbox) != expected:
        raise ValueError("Retained sandbox byte identity mismatch.")
    result = {"archive": archive.name, "archive_sha256": digest(archive),
              "file_count": len(expected), "every_file_sha256_verified": True,
              "original_sandbox_unchanged": True, "files": expected}
    save(output / "retained_sandbox_index.json", result)
    return result


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def loaded_sources():
    paths = set()
    for module in tuple(sys.modules.values()):
        raw = getattr(module, "__file__", None)
        if raw and str(raw).endswith(".py"):
            path = Path(raw).resolve()
            if path.is_relative_to(ROOT) and ".venv" not in path.parts:
                paths.add(path)
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def observe_effects(spec):
    from src.mod_agent.execution import ExactTextPatchApplier

    def record(event, **fields):
        with Path(spec["effect_log"]).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "pid": os.getpid(), **fields}) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    actual_apply = ExactTextPatchApplier.run
    actual_replace = os.replace

    def apply(self, *args, **kwargs):
        if kwargs.get("allow_write"):
            record("applier_allow_write_entered")
        return actual_apply(self, *args, **kwargs)

    def replace_file(source, destination):
        selected = Path(destination).resolve() == Path(spec["target"]).resolve()
        if selected:
            record("source_replace_entered", before_sha256=digest(destination))
        result = actual_replace(source, destination)
        if selected:
            record("source_replace_completed", after_sha256=digest(destination))
        return result

    ExactTextPatchApplier.run = apply
    os.replace = replace_file
    return record


def cli_arguments(spec):
    ref = spec["approval_checkpoint"]
    return ["apply-patch", "--resume-approval", "--artifact-store-root", spec["store_root"],
            "--feature-id", ref["feature_id"], "--checkpoint-path", ref["path"],
            "--checkpoint-hash", ref["artifact_hash"], "--resume-payload", spec["resume_path"],
            "--human-semantic-decision", spec["human_path"]]


def child(spec, mode):
    def no_network(*args, **kwargs):
        raise AssertionError("This preregistered scenario cannot use network providers.")

    socket.socket.connect = no_network
    import src.mod_agent.reviewed_patch_continuation as owner
    from src.mod_agent import cli
    from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
    from src.mod_agent.workflow.checkpointing import WorkflowCheckpointStore
    from src.mod_agent.workflow.interrupts import ResumePayload

    record = observe_effects(spec)
    output = Path(spec["output"])
    if mode == "apply_then_exit":
        real_resume = owner.resume_deferred_approval

        def interrupt_before_cli_response(**kwargs):
            result = real_resume(**kwargs)
            assert result["status"] == "applied_in_isolation", result
            store = ArtifactStore(spec["store_root"])
            # Persisted production receipts are checked before injecting response loss.
            # 为什么要有它：这个场景只验证已提交后的中断，不能把未落盘窗口混入恢复成功率。
            for name in ("resume_report", "isolated_apply_result", "workflow_checkpoint"):
                store.semantic_read_immutable(ArtifactRef(**result[name]))
            assert digest(spec["target"]) == spec["expected_after_sha256"]
            assert result["model_calls_performed"] == result["builds_performed"] == 0
            save(output / "injection_marker.json", {
                "pid": os.getpid(), "point": "owner_returned_after_durable_apply_before_cli_response",
                "verified_production_refs": {key: result[key] for key in
                    ("resume_report", "isolated_apply_result", "workflow_checkpoint")},
                "loaded_source_sha256": loaded_sources(),
                "observer_only_not_consumed_by_recovery": True,
            })
            record("exit_injected_after_durable_apply", exit_code=EXIT_AFTER_DURABLE_APPLY)
            os._exit(EXIT_AFTER_DURABLE_APPLY)

        owner.resume_deferred_approval = interrupt_before_cli_response
        cli.main(cli_arguments(spec))
        raise AssertionError("Fault injection was not reached.")

    # No object/response from the terminated child is passed into this process.
    # 为什么要有它：恢复必须从既有持久产物发现事实，不能靠父进程保存返回对象补齐缺失状态。
    store = ArtifactStore(spec["store_root"])
    before_query = inventory(store.root)
    feature_id = spec["approval_checkpoint"]["feature_id"]
    apply_refs = store.list_feature_artifact_revisions(feature_id, "isolated_apply_result")
    assert len(apply_refs) == 1
    applied = store.semantic_read_immutable(apply_refs[0])["data"]
    assert applied["actual_write_performed"] is True and applied["real_patch_applied"] is True
    assert applied["approved_diff_hash"] == spec["resume"]["diff_hash"]
    assert digest(spec["target"]) == spec["expected_after_sha256"]
    assert digest(spec["canonical"]) == spec["canonical_sha256"]
    candidates = []
    for ref in store.list_feature_artifact_revisions(feature_id, "workflow_checkpoint"):
        checkpoint = store.semantic_read_immutable(ref)["data"]
        if checkpoint["checkpoint_stage"] == "isolated_apply":
            assert checkpoint["run_id"] == spec["resume"]["run_id"]
            assert checkpoint["request_id"] == spec["resume"]["request_id"]
            assert checkpoint["state_snapshot"]["artifact_hashes"]["isolated_apply_result"] == apply_refs[0].artifact_hash
            candidates.append((ref, checkpoint))
    assert len(candidates) == 1
    checkpoint_ref, checkpoint = candidates[0]
    preflight = WorkflowCheckpointStore(store).preflight_resume(
        ArtifactRef(**spec["approval_checkpoint"]), resume_id=spec["resume"]["resume_id"])
    assert not preflight.allowed and preflight.blockers[0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert inventory(store.root) == before_query
    save(output / "reconstructed_before_resume.json", {
        "pid": os.getpid(), "read_only_store_unchanged": True,
        "apply_ref": asdict(apply_refs[0]), "following_checkpoint": asdict(checkpoint_ref),
        "target_sha256": digest(spec["target"]), "canonical_sha256": digest(spec["canonical"]),
        "prior_resume_blockers": list(preflight.blockers),
    })
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        retry_code = cli.main(cli_arguments(spec))
    retry = json.loads(captured.getvalue())
    assert retry_code == 2 and retry["status"] == "blocked"
    assert retry["blockers"][0]["code"] == "DOUBLE_RESUME_REJECTED"
    assert inventory(store.root) == before_query
    from tests.unit.test_reviewed_patch_continuation import _injected_build

    def controlled_build(*args):
        record("controlled_build_entered")
        return _injected_build(*args)

    resume = replace(ResumePayload(**spec["resume"]), resume_id="cross-process-recovered-build",
                     stage="isolated_apply", artifact_refs=tuple(checkpoint["artifact_refs"]))
    built = owner.continue_reviewed_patch(artifact_store_root=spec["store_root"],
        checkpoint_ref=checkpoint_ref, resume_payload=resume,
        allow_build=True, build_result_factory=controlled_build)
    assert built["status"] == "built", built
    assert built["builds_performed"] == 1 and built["product_source_writes_performed"] is False
    assert built["model_calls_performed"] == built["runtime_executions_performed"] == 0
    next_checkpoint = store.semantic_read_immutable(ArtifactRef(**built["workflow_checkpoint"]))["data"]
    assert next_checkpoint["checkpoint_stage"] == "build"
    assert len(store.list_feature_artifact_revisions(feature_id, "isolated_apply_result")) == 1
    assert digest(spec["target"]) == spec["expected_after_sha256"]
    assert digest(spec["canonical"]) == spec["canonical_sha256"]
    save(output / "recovery_result.json", {"pid": os.getpid(), "repeat_cli_exit_code": retry_code,
        "repeat_cli_result": retry, "continued_build": built, "loaded_source_sha256": loaded_sources()})
    print(json.dumps({"status": "recovered_to_controlled_build_checkpoint", "pid": os.getpid()}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", choices=("apply_then_exit", "recover"))
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args(argv)
    if args.child:
        return child(json.loads(args.spec.read_text(encoding="utf-8")), args.child)
    if args.output is None:
        parser.error("--output is required for the orchestrator")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    save(output / "preregistration.json", {"scenario_id": "PC01", "applicable_scenarios": 1,
        "injection": "os._exit(73) after production Apply, resume_report and subsequent isolated_apply checkpoint persist; before CLI gets owner response",
        "success_requires": ["first child exits 73 with no CLI response", "new process reconstructs exact persisted identities and source bytes read-only",
            "same approval CLI refuses replay", "original subsequent checkpoint reaches controlled Build and persists build checkpoint",
            "one physical target replacement and one Apply artifact across processes", "canonical source unchanged"],
        "real": ["separate Python processes", "abrupt os._exit", "production Graph and approval", "source replacement", "ArtifactStore persistence"],
        "controlled": ["deterministic preparation model responses", "synthetic DLL Build adapter"],
        "excluded": ["power loss", "termination during Apply or receipt writes", "concurrent processes", "real compiler", "game deployment/runtime"],
        "does_not_change_existing_18_scenario_denominator": True})
    from tests.unit.test_deferred_product_approval import _pending_case

    sandbox = Path(tempfile.mkdtemp(prefix="gov-cr-"))
    case, pending, resume, human = _pending_case(sandbox)
    save(output / "resume.json", resume.to_dict())
    save(output / "human.json", human)
    spec = {"output": str(output), "sandbox": str(sandbox), "store_root": str(case.store.root),
        "target": str(case.target), "canonical": str(case.canonical),
        "source_before_sha256": digest(case.target), "expected_after_sha256": hashlib.sha256(case.source_after).hexdigest(),
        "canonical_sha256": digest(case.canonical), "approval_checkpoint": asdict(pending.checkpoint_ref),
        "resume": resume.to_dict(), "resume_path": str(output / "resume.json"), "human_path": str(output / "human.json"),
        "effect_log": str(output / "effect_observations.jsonl")}
    save(output / "spec.json", spec)
    save(output / "source_before.json", loaded_sources())
    shutil.copy2(__file__, output / "executed_helper.py")
    processes = []
    for mode in ("apply_then_exit", "recover"):
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", mode, "--spec", str(output / "spec.json")]
        save(output / f"{mode}_command.json", {"argv": command, "cwd": str(ROOT)})
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
        (output / f"{mode}_stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / f"{mode}_stderr.txt").write_text(result.stderr, encoding="utf-8")
        processes.append({"mode": mode, "exit_code": result.returncode, "elapsed_seconds": time.perf_counter() - started})
        if result.returncode != (EXIT_AFTER_DURABLE_APPLY if mode == "apply_then_exit" else 0):
            break
    events = [json.loads(line) for line in Path(spec["effect_log"]).read_text(encoding="utf-8").splitlines()] if Path(spec["effect_log"]).exists() else []
    counts = {name: sum(row["event"] == name for row in events) for name in
              ("applier_allow_write_entered", "source_replace_entered", "source_replace_completed", "controlled_build_entered")}
    recovered = (output / "recovery_result.json").exists()
    marker = json.loads((output / "injection_marker.json").read_text(encoding="utf-8")) if (output / "injection_marker.json").exists() else None
    recovery = json.loads((output / "recovery_result.json").read_text(encoding="utf-8")) if recovered else None
    first_loaded = (marker or {}).get("loaded_source_sha256", {})
    next_loaded = (recovery or {}).get("loaded_source_sha256", {})
    loaded = {**first_loaded, **next_loaded}
    source_drift = sorted({name for name, expected in loaded.items() if digest(ROOT / name) != expected}
                         | {name for name in first_loaded.keys() & next_loaded.keys()
                            if first_loaded[name] != next_loaded[name]})
    passed = (len(processes) == 2 and processes[0]["exit_code"] == EXIT_AFTER_DURABLE_APPLY
              and processes[1]["exit_code"] == 0 and recovered and marker["pid"] != recovery["pid"]
              and all(value == 1 for value in counts.values()) and not source_drift
              and not (output / "apply_then_exit_stdout.txt").read_text(encoding="utf-8").strip())
    save(output / "summary.json", {"schema_version": "process_crash_scenario.v1", "scenario_id": "PC01",
        "status": "passed" if passed else "failed", "processes": processes, "effect_counts": counts,
        "recovery_success": {"numerator": int(passed), "denominator": 1},
        "recovery_terminal": "controlled_build_and_durable_build_checkpoint" if recovered else None,
        "duplicate_target_replacements": max(0, counts["source_replace_completed"] - 1),
        "loaded_source_drift_at_end": source_drift, "sandbox": str(sandbox),
        "scope": "one registered post-durability response-loss point, not arbitrary crash recovery"})
    # Archive evidence without rewriting absolute references or deep destination paths.
    # 为什么要有它：临时路径可能清理，Windows深路径复制会失败；压缩包保留原身份与字节，不改写历史。
    archive_sandbox(sandbox, output)
    print((output / "summary.json").read_text(encoding="utf-8"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
