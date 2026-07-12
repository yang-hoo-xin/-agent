"""Tests for the real Arm A rg/live-read baseline and run bindings."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.run_arm_a_baseline import _write_run_ledger
from src.mod_agent.evaluation import (
    AgentQualityCase,
    ArmATestHarness,
    OfficialArmARunner,
    QualityGatePolicy,
    RankedRetrievalResult,
    RetrievalObservation,
    RgLiveReadProvider,
    RunManifestCollector,
    VersionedAgentQualityCases,
)
from src.mod_agent.evaluation.arm_a import _verify_returned_file_hashes
from src.mod_agent.git import GitWorkingTreeSnapshot


def _dataset() -> VersionedAgentQualityCases:
    case = AgentQualityCase(
        case_id="find_policy",
        stratum="exact_code_lookup",
        query="Find the policy class.",
        expected_relevant_ids=("file:src/policy.py",),
        expected_hook_ids=(),
        expected_target_files=(),
        forbidden_files=(),
        expected_readiness="blocked",
        expected_control_action="block",
        task_success_eligible=False,
        expected_task_success=None,
    )
    return VersionedAgentQualityCases(
        dataset_schema_version="1",
        dataset_version="arm_a_test_v1",
        dataset_kind="benchmark",
        quality_gate_eligible=True,
        dataset_sha256="sha256:dataset",
        judgment_sha256="sha256:judgment",
        cases=(case,),
        benchmark_scope="smoke",
        claim_scope="execution_plumbing_only",
        promotion_eligible=False,
    )


def _policy() -> QualityGatePolicy:
    names = ("recall_at_k", "precision_at_k", "precision_at_returned", "mrr_at_k")
    return QualityGatePolicy(
        policy_schema_version="quality_gate_policy_v1",
        policy_id="arm_a_test",
        required_metric_names=names,
        thresholds={
            "recall_at_k": 1.0,
            "precision_at_k": 0.1,
            "precision_at_returned": 1.0,
            "mrr_at_k": 1.0,
        },
    )


class _FakeGitRepository:
    def __init__(self, snapshots: list[GitWorkingTreeSnapshot]) -> None:
        self.snapshots = snapshots

    def working_tree_snapshot(self) -> GitWorkingTreeSnapshot:
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


def _snapshot(diff_hash: str = "sha256:diff") -> GitWorkingTreeSnapshot:
    return GitWorkingTreeSnapshot(
        repo_root="repo",
        base_revision="abc123",
        branch="test",
        is_dirty=False,
        status_entries=(),
        diff_hash=diff_hash,
        dirty_tree_policy={"status": "clean", "blocks_proposal_binding": False, "blockers": []},
    )


def _workspace(tmp_path: Path) -> Path:
    source = tmp_path / "src" / "policy.py"
    source.parent.mkdir()
    source.write_text("class QualityGatePolicy:\n    pass\n", encoding="utf-8")
    return tmp_path


def test_ranked_results_must_bind_retrieved_ids() -> None:
    result = RankedRetrievalResult(
        result_id="file:src/policy.py",
        relative_path="src/policy.py",
        line_number=1,
        matched_text="class QualityGatePolicy:",
        file_sha256="sha256:" + "0" * 64,
    )
    with pytest.raises(ValueError, match="exactly match"):
        RetrievalObservation(retrieved_ids=("file:other.py",), ranked_results=(result,))


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is required")
def test_arm_a_runs_real_rg_and_live_read_with_fresh_bindings(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    patterns = {"find_policy": ("class QualityGatePolicy",)}
    roots = ("src",)
    fake_git = _FakeGitRepository([_snapshot(), _snapshot()])
    collector = RunManifestCollector(workspace, git_repository=fake_git)  # type: ignore[arg-type]
    snapshot = collector.canonical_corpus_snapshot(roots)
    provider = RgLiveReadProvider(
        workspace,
        search_patterns=patterns,
        corpus_snapshot=snapshot,
    )

    result = ArmATestHarness().run(
        dataset=_dataset(),
        quality_policy=_policy(),
        provider=provider,
        manifest_collector=collector,
        search_patterns=patterns,
        search_roots=roots,
        top_k=10,
    )

    assert result.report.quality_gate_status == "pass"
    assert result.report.aggregate_metrics["recall_at_k"] == 1.0
    ranked = result.report.raw_observations["find_policy"]["retrieval"]["ranked_results"]
    assert ranked[0]["relative_path"] == "src/policy.py"
    assert ranked[0]["file_sha256"].startswith("sha256:")
    assert result.collected_manifest.before == result.collected_manifest.after
    assert result.execution_mode == "test"
    assert result.formal_run_eligible is False
    assert result.report.promotion_eligible is False


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is required")
def test_arm_a_rejects_inputs_that_change_during_run(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    patterns = {"find_policy": ("class QualityGatePolicy",)}
    roots = ("src",)
    fake_git = _FakeGitRepository([_snapshot(), replace(_snapshot(), diff_hash="sha256:changed")])
    collector = RunManifestCollector(workspace, git_repository=fake_git)  # type: ignore[arg-type]
    snapshot = collector.canonical_corpus_snapshot(roots)
    provider = RgLiveReadProvider(
        workspace, search_patterns=patterns, corpus_snapshot=snapshot
    )

    with pytest.raises(RuntimeError, match="stale"):
        ArmATestHarness().run(
            dataset=_dataset(),
            quality_policy=_policy(),
            provider=provider,
            manifest_collector=collector,
            search_patterns=patterns,
            search_roots=roots,
            top_k=10,
        )


def test_protocol_hash_binds_quality_policy_and_search_patterns(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    collector = RunManifestCollector(
        workspace,
        git_repository=_FakeGitRepository([_snapshot()]),  # type: ignore[arg-type]
    )
    common = {
        "dataset": _dataset(),
        "search_roots": ("src",),
        "top_k": 10,
    }
    first = collector.capture(
        quality_policy=_policy(),
        search_patterns={"find_policy": ("class QualityGatePolicy",)},
        **common,
    )
    second = collector.capture(
        quality_policy=replace(
            _policy(),
            policy_id="arm_a_test_v2",
        ),
        search_patterns={"find_policy": ("QualityGatePolicy",)},
        **common,
    )
    assert first.evaluation_protocol_sha256 != second.evaluation_protocol_sha256


def test_protocol_hash_binds_complete_preregistered_document(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    collector = RunManifestCollector(
        workspace,
        git_repository=_FakeGitRepository([_snapshot()]),  # type: ignore[arg-type]
    )
    common = {
        "dataset": _dataset(),
        "quality_policy": _policy(),
        "search_patterns": {"find_policy": ("class QualityGatePolicy",)},
        "search_roots": ("src",),
        "top_k": 10,
    }
    first = collector.capture(
        protocol_document_sha256="sha256:" + "1" * 64,
        **common,
    )
    second = collector.capture(
        protocol_document_sha256="sha256:" + "2" * 64,
        **common,
    )
    assert first.evaluation_protocol_sha256 != second.evaluation_protocol_sha256


def test_official_runner_does_not_accept_injected_provider(tmp_path: Path) -> None:
    runner = OfficialArmARunner(tmp_path, rg_executable=sys.executable)
    with pytest.raises(TypeError, match="provider"):
        runner.run(  # type: ignore[call-arg]
            run_id="formal-test",
            dataset=_dataset(),
            quality_policy=_policy(),
            search_patterns={"find_policy": ("class QualityGatePolicy",)},
            search_roots=("src",),
            top_k=10,
            provider=lambda _case, _k: None,
        )


def test_held_out_official_run_requires_complete_protocol_document_hash(
    tmp_path: Path,
) -> None:
    runner = OfficialArmARunner(tmp_path, rg_executable=sys.executable)
    with pytest.raises(ValueError, match="complete protocol document SHA-256"):
        runner.run(
            run_id="held-out-test",
            dataset=replace(
                _dataset(), benchmark_scope="held_out", promotion_eligible=True
            ),
            quality_policy=_policy(),
            search_patterns={"find_policy": ("class QualityGatePolicy",)},
            search_roots=("src",),
            top_k=10,
        )


def test_non_ripgrep_executable_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    collector = RunManifestCollector(
        workspace,
        git_repository=_FakeGitRepository([_snapshot()]),  # type: ignore[arg-type]
    )
    snapshot = collector.canonical_corpus_snapshot(("src",))
    with pytest.raises(RuntimeError, match="identify itself as ripgrep"):
        RgLiveReadProvider(
            workspace,
            search_patterns={"find_policy": ("class QualityGatePolicy",)},
            corpus_snapshot=snapshot,
            rg_executable=sys.executable,
        )


@pytest.mark.skipif(shutil.which("rg") is None, reason="ripgrep is required")
def test_rg_searches_only_canonical_snapshot_and_ignores_environment_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "src" / "target.toml").write_text(
        "class OutsideCanonicalCorpus = true\n", encoding="utf-8"
    )
    malicious = workspace / "malicious.rgconfig"
    malicious.write_text("--glob=*.toml\n", encoding="utf-8")
    monkeypatch.setenv("RIPGREP_CONFIG_PATH", str(malicious))
    collector = RunManifestCollector(
        workspace,
        git_repository=_FakeGitRepository([_snapshot()]),  # type: ignore[arg-type]
    )
    snapshot = collector.canonical_corpus_snapshot(("src",))
    assert all(not item.relative_path.endswith(".toml") for item in snapshot.files)
    provider = RgLiveReadProvider(
        workspace,
        search_patterns={"find_policy": ("OutsideCanonicalCorpus",)},
        corpus_snapshot=snapshot,
    )
    observation = provider(_dataset().cases[0], 10)
    assert observation.retrieval.retrieved_ids == ()
    assert provider.normalized_environment == {"RIPGREP_CONFIG_PATH": None}
    assert "--no-config" in provider.command_traces[0].argv
    assert tuple(item.relative_path for item in snapshot.files) == tuple(
        arg for arg in provider.command_traces[0].argv if arg.endswith(".py")
    )


def test_final_rehash_rejects_returned_file_mutation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source = workspace / "src" / "policy.py"
    original_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    result = RankedRetrievalResult(
        result_id="file:src/policy.py",
        relative_path="src/policy.py",
        line_number=1,
        matched_text="class QualityGatePolicy:",
        file_sha256=original_hash,
    )
    observation = RetrievalObservation(
        retrieved_ids=(result.result_id,), ranked_results=(result,)
    )
    source.write_text("class Changed:\n    pass\n", encoding="utf-8")
    from src.mod_agent.evaluation import CaseObservation

    with pytest.raises(RuntimeError, match="changed before finalization"):
        _verify_returned_file_hashes(
            workspace, {"find_policy": CaseObservation(retrieval=observation)}
        )


def test_run_ledger_hashes_exact_persisted_bytes_and_is_exclusive(tmp_path: Path) -> None:
    entry = _write_run_ledger(
        payload={"message": "真实运行", "value": 1},
        output_dir=tmp_path,
        run_id="ledger-test",
        metadata={"formal_run_eligible": True},
    )
    result_path = Path(entry["result_path"])
    assert result_path.is_file()
    assert "sha256:" + hashlib.sha256(result_path.read_bytes()).hexdigest() == entry[
        "result_sha256"
    ]
    assert json.loads((tmp_path / "index" / "ledger-test.json").read_text("utf-8"))[
        "result_sha256"
    ] == entry["result_sha256"]
    with pytest.raises(FileExistsError):
        _write_run_ledger(
            payload={"message": "真实运行", "value": 1},
            output_dir=tmp_path,
            run_id="ledger-test",
            metadata={"formal_run_eligible": True},
        )
