"""Real Arm A baseline: live ripgrep retrieval with reproducible run bindings."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.mod_agent.git import GitRepository
from src.mod_agent.knowledge.source_discovery import (
    DEFAULT_IGNORED_DIR_NAMES,
    DEFAULT_IGNORED_FILE_PATTERNS,
    iter_indexable_paths,
)
from src.mod_agent.knowledge.source_registry import DEFAULT_EXTENSIONS

from .agent_quality import (
    AgentQualityCase,
    AgentQualityEvaluator,
    AgentQualityReport,
    CaseObservation,
    RankedRetrievalResult,
    RetrievalObservation,
    RunManifest,
)
from .quality_policy import QualityGatePolicy
from .retrieval_regression import VersionedAgentQualityCases

ARM_A_PROVIDER_ID = "rg_live_read"
ARM_A_PROVIDER_VERSION = "1"
ARM_A_OBSERVATION_SCHEMA_VERSION = "arm_a_rg_live_read_v1"
FORMAL_RG_FLAGS = (
    "--no-config",
    "--hidden",
    "--no-ignore",
    "--no-follow",
    "--text",
    "--json",
    "--line-number",
    "--with-filename",
    "--sort",
    "path",
    "--fixed-strings",
    "--ignore-case",
)


@dataclass(frozen=True)
class CorpusFileEntry:
    relative_path: str
    file_sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class CanonicalCorpusSnapshot:
    files: tuple[CorpusFileEntry, ...]
    selection_policy: Mapping[str, Any]
    corpus_snapshot_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [item.to_dict() for item in self.files],
            "selection_policy": dict(self.selection_policy),
            "corpus_snapshot_sha256": self.corpus_snapshot_sha256,
        }


@dataclass(frozen=True)
class RgExecutableIdentity:
    absolute_path: str
    executable_sha256: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RgCommandTrace:
    trace_id: str
    case_id: str
    argv: tuple[str, ...]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str
    duration_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {**dict(self.__dict__), "argv": list(self.argv)}


@dataclass(frozen=True)
class OfficialArmAExecutionAttestation:
    run_id: str
    started_at: str
    finished_at: str
    repository_root: str
    branch: str
    worktree_path: str
    os: str
    architecture: str
    python_version: str
    normalized_environment: Mapping[str, str | None]
    rg_identity: RgExecutableIdentity
    command_traces: tuple[RgCommandTrace, ...]
    provider_config_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **dict(self.__dict__),
            "normalized_environment": dict(self.normalized_environment),
            "rg_identity": self.rg_identity.to_dict(),
            "command_traces": [trace.to_dict() for trace in self.command_traces],
        }


@dataclass(frozen=True)
class RunBindingSnapshot:
    repository_root: str
    repository_revision: str
    branch: str
    worktree_path: str
    worktree_diff_sha256: str
    evaluation_protocol_sha256: str
    corpus_snapshot: CanonicalCorpusSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            **dict(self.__dict__),
            "corpus_snapshot": self.corpus_snapshot.to_dict(),
            "corpus_manifest_sha256": self.corpus_snapshot.corpus_snapshot_sha256,
            "corpus_file_count": len(self.corpus_snapshot.files),
        }


@dataclass(frozen=True)
class CollectedRunManifest:
    manifest: RunManifest
    before: RunBindingSnapshot
    after: RunBindingSnapshot

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


@dataclass(frozen=True)
class ArmARunResult:
    report: AgentQualityReport
    collected_manifest: CollectedRunManifest
    execution_mode: str
    formal_run_eligible: bool
    execution_attestation: OfficialArmAExecutionAttestation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report.to_dict(),
            "run_binding_evidence": self.collected_manifest.to_dict(),
            "execution_mode": self.execution_mode,
            "formal_run_eligible": self.formal_run_eligible,
            "benchmark_scope": self.report.benchmark_scope,
            "claim_scope": self.report.claim_scope,
            "promotion_eligible": self.report.promotion_eligible,
            "execution_attestation": (
                self.execution_attestation.to_dict()
                if self.execution_attestation is not None
                else None
            ),
        }


class RunManifestCollector:
    """Collect repository, worktree, corpus, protocol, and policy identities."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        git_repository: GitRepository | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.is_dir():
            raise ValueError("workspace_root must be an existing directory")
        self.git_repository = git_repository or GitRepository(self.workspace_root)

    def capture(
        self,
        *,
        dataset: VersionedAgentQualityCases,
        quality_policy: QualityGatePolicy,
        search_patterns: Mapping[str, Sequence[str]],
        search_roots: Sequence[str],
        top_k: int,
        provider_config_sha256: str = "test-harness-unbound",
        protocol_document_sha256: str = "legacy-unbound",
    ) -> RunBindingSnapshot:
        _validate_search_protocol(dataset, search_patterns, search_roots, top_k)
        git_snapshot = self.git_repository.working_tree_snapshot()
        corpus = self.canonical_corpus_snapshot(search_roots)
        protocol = {
            "protocol_schema_version": "arm_a_protocol_v3",
            "dataset_schema_version": dataset.dataset_schema_version,
            "dataset_version": dataset.dataset_version,
            "dataset_sha256": dataset.dataset_sha256,
            "judgment_sha256": dataset.judgment_sha256,
            "quality_policy_sha256": quality_policy.policy_sha256,
            "provider_id": ARM_A_PROVIDER_ID,
            "provider_version": ARM_A_PROVIDER_VERSION,
            "observation_schema_version": ARM_A_OBSERVATION_SCHEMA_VERSION,
            "provider_config_sha256": provider_config_sha256,
            "protocol_document_sha256": protocol_document_sha256,
            "corpus_snapshot_sha256": corpus.corpus_snapshot_sha256,
            "top_k": top_k,
            "search_roots": list(search_roots),
            "search_patterns": {
                case_id: list(search_patterns[case_id])
                for case_id in sorted(search_patterns)
            },
        }
        return RunBindingSnapshot(
            repository_root=git_snapshot.repo_root,
            repository_revision=git_snapshot.base_revision,
            branch=git_snapshot.branch,
            worktree_path=str(self.workspace_root),
            worktree_diff_sha256=git_snapshot.diff_hash,
            evaluation_protocol_sha256=_sha256(protocol),
            corpus_snapshot=corpus,
        )

    def finalize(
        self,
        before: RunBindingSnapshot,
        *,
        dataset: VersionedAgentQualityCases,
        quality_policy: QualityGatePolicy,
        search_patterns: Mapping[str, Sequence[str]],
        search_roots: Sequence[str],
        top_k: int,
        provider_config_sha256: str = "test-harness-unbound",
        protocol_document_sha256: str = "legacy-unbound",
    ) -> CollectedRunManifest:
        after = self.capture(
            dataset=dataset,
            quality_policy=quality_policy,
            search_patterns=search_patterns,
            search_roots=search_roots,
            top_k=top_k,
            provider_config_sha256=provider_config_sha256,
            protocol_document_sha256=protocol_document_sha256,
        )
        status = "fresh" if before == after else "stale"
        manifest = RunManifest(
            repository_revision=before.repository_revision,
            worktree_diff_sha256=before.worktree_diff_sha256,
            corpus_manifest_sha256=before.corpus_snapshot.corpus_snapshot_sha256,
            evaluation_protocol_sha256=before.evaluation_protocol_sha256,
            provider_id=ARM_A_PROVIDER_ID,
            provider_version=ARM_A_PROVIDER_VERSION,
            evidence_status=status,
        )
        return CollectedRunManifest(manifest=manifest, before=before, after=after)

    def canonical_corpus_snapshot(
        self, search_roots: Sequence[str]
    ) -> CanonicalCorpusSnapshot:
        entries: list[CorpusFileEntry] = []
        for relative_root in search_roots:
            root = (self.workspace_root / relative_root).resolve()
            _require_within(root, self.workspace_root)
            if not root.is_dir():
                raise ValueError(f"search root does not exist: {relative_root}")
            paths = iter_indexable_paths(
                root=root,
                allowed_extensions=DEFAULT_EXTENSIONS,
                ignored_dir_names=DEFAULT_IGNORED_DIR_NAMES,
                ignored_file_patterns=DEFAULT_IGNORED_FILE_PATTERNS,
                include_generated_mods=False,
            )
            for path in paths:
                relative = path.relative_to(self.workspace_root).as_posix()
                if path.is_symlink():
                    raise ValueError(f"canonical corpus does not allow symlinks: {relative}")
                entries.append(
                    CorpusFileEntry(
                        relative_path=relative,
                        file_sha256=_file_sha256(path),
                        size_bytes=path.stat().st_size,
                    )
                )
        entries.sort(key=lambda item: item.relative_path)
        if len({item.relative_path for item in entries}) != len(entries):
            raise ValueError("search_roots overlap and produce duplicate corpus paths")
        policy = {
            "policy_schema_version": "canonical_corpus_policy_v1",
            "search_roots": list(search_roots),
            "allowed_extensions": sorted(DEFAULT_EXTENSIONS),
            "ignored_dir_names": sorted(DEFAULT_IGNORED_DIR_NAMES),
            "ignored_file_patterns": sorted(DEFAULT_IGNORED_FILE_PATTERNS),
            "hidden_policy": "walker_policy",
            "ignore_policy": "walker_policy",
            "binary_policy": "extension_allowlist_and_utf8_live_read",
            "symlink_policy": "reject",
        }
        content = {
            "files": [item.to_dict() for item in entries],
            "selection_policy": policy,
        }
        return CanonicalCorpusSnapshot(
            files=tuple(entries),
            selection_policy=policy,
            corpus_snapshot_sha256=_sha256(content),
        )


class RgLiveReadProvider:
    """Run ripgrep, then live-read and hash every returned source file."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        search_patterns: Mapping[str, Sequence[str]],
        corpus_snapshot: CanonicalCorpusSnapshot,
        rg_executable: str | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.search_patterns = {
            case_id: tuple(patterns) for case_id, patterns in search_patterns.items()
        }
        self.corpus_snapshot = corpus_snapshot
        discovered = rg_executable or shutil.which("rg")
        if not discovered:
            raise RuntimeError("ripgrep executable was not found")
        executable = Path(discovered).resolve()
        if not executable.is_file():
            raise RuntimeError("ripgrep executable is not a regular file")
        self.rg_executable = str(executable)
        self.normalized_environment = {"RIPGREP_CONFIG_PATH": None}
        self._subprocess_environment = dict(os.environ)
        self._subprocess_environment.pop("RIPGREP_CONFIG_PATH", None)
        version_result = subprocess.run(
            [self.rg_executable, "--version"],
            cwd=self.workspace_root,
            env=self._subprocess_environment,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            check=False,
        )
        version_line = version_result.stdout.splitlines()[0] if version_result.stdout else ""
        if version_result.returncode != 0 or not version_line.startswith("ripgrep "):
            raise RuntimeError("configured executable did not identify itself as ripgrep")
        self.executable_identity = RgExecutableIdentity(
            absolute_path=self.rg_executable,
            executable_sha256=_file_sha256(executable),
            version=version_line,
        )
        self.command_traces: list[RgCommandTrace] = []
        self.provider_config_sha256 = _sha256(
            {
                "provider_id": ARM_A_PROVIDER_ID,
                "provider_version": ARM_A_PROVIDER_VERSION,
                "workspace_root": str(self.workspace_root),
                "rg_identity": self.executable_identity.to_dict(),
                "flags": list(FORMAL_RG_FLAGS),
                "normalized_environment": self.normalized_environment,
                "corpus_snapshot_sha256": corpus_snapshot.corpus_snapshot_sha256,
                "search_patterns": {
                    case_id: list(self.search_patterns[case_id])
                    for case_id in sorted(self.search_patterns)
                },
            }
        )

    def __call__(self, case: AgentQualityCase, top_k: int) -> CaseObservation:
        patterns = self.search_patterns.get(case.case_id)
        if not patterns:
            raise ValueError(f"missing Arm A search patterns for case_id: {case.case_id}")
        started = time.perf_counter_ns()
        ranked: list[RankedRetrievalResult] = []
        seen: set[str] = set()
        command = [self.rg_executable, *FORMAL_RG_FLAGS]
        for pattern in patterns:
            command.extend(("--regexp", pattern))
        command.append("--")
        command.extend(item.relative_path for item in self.corpus_snapshot.files)
        result = subprocess.run(
            command,
            cwd=self.workspace_root,
            env=self._subprocess_environment,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            check=False,
        )
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        trace = RgCommandTrace(
            trace_id=f"rg:{case.case_id}:{len(self.command_traces) + 1}",
            case_id=case.case_id,
            argv=tuple(command),
            exit_code=result.returncode,
            stdout_sha256=_sha256_text(result.stdout),
            stderr_sha256=_sha256_text(result.stderr),
            duration_ms=elapsed_ms,
        )
        self.command_traces.append(trace)
        if result.returncode not in {0, 1}:
            raise RuntimeError(
                f"ripgrep failed with exit {result.returncode}: {result.stderr.strip()}"
            )
        for line in result.stdout.splitlines():
            event = json.loads(line)
            if event.get("type") != "match":
                continue
            data = event.get("data")
            if not isinstance(data, Mapping):
                continue
            path_value = data.get("path")
            if not isinstance(path_value, Mapping) or not isinstance(path_value.get("text"), str):
                continue
            path = (self.workspace_root / str(path_value["text"])).resolve()
            _require_within(path, self.workspace_root)
            relative = path.relative_to(self.workspace_root).as_posix()
            if relative not in {item.relative_path for item in self.corpus_snapshot.files}:
                raise RuntimeError(f"ripgrep returned a file outside canonical corpus: {relative}")
            result_id = f"file:{relative}"
            if result_id in seen:
                continue
            line_number = data.get("line_number")
            if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number <= 0:
                raise RuntimeError("ripgrep returned an invalid line number")
            live_bytes = path.read_bytes()
            live_lines = live_bytes.decode("utf-8", errors="strict").splitlines()
            if line_number > len(live_lines):
                raise RuntimeError(f"source changed before live read: {relative}")
            matched_text = live_lines[line_number - 1].strip()
            submatches = data.get("submatches")
            if not isinstance(submatches, list) or not submatches:
                raise RuntimeError("ripgrep match event lacks submatches")
            if not any(pattern.casefold() in matched_text.casefold() for pattern in patterns):
                raise RuntimeError(f"ripgrep match no longer exists during live read: {relative}")
            ranked.append(
                RankedRetrievalResult(
                    result_id=result_id,
                    relative_path=relative,
                    line_number=line_number,
                    matched_text=matched_text,
                    file_sha256="sha256:" + hashlib.sha256(live_bytes).hexdigest(),
                )
            )
            seen.add(result_id)
            if len(ranked) >= top_k:
                break
        return CaseObservation(
            retrieval=RetrievalObservation(
                retrieved_ids=tuple(item.result_id for item in ranked),
                ranked_results=tuple(ranked),
                latency_ms=elapsed_ms,
            )
        )


class ArmATestHarness:
    def __init__(self, evaluator: AgentQualityEvaluator | None = None) -> None:
        self.evaluator = evaluator or AgentQualityEvaluator()

    def run(
        self,
        *,
        dataset: VersionedAgentQualityCases,
        quality_policy: QualityGatePolicy,
        provider: RgLiveReadProvider,
        manifest_collector: RunManifestCollector,
        search_patterns: Mapping[str, Sequence[str]],
        search_roots: Sequence[str],
        top_k: int = 10,
    ) -> ArmARunResult:
        before = manifest_collector.capture(
            dataset=dataset,
            quality_policy=quality_policy,
            search_patterns=search_patterns,
            search_roots=search_roots,
            top_k=top_k,
        )
        observations = {case.case_id: provider(case, top_k) for case in dataset.cases}
        collected = manifest_collector.finalize(
            before,
            dataset=dataset,
            quality_policy=quality_policy,
            search_patterns=search_patterns,
            search_roots=search_roots,
            top_k=top_k,
        )
        if collected.manifest.evidence_status != "fresh":
            raise RuntimeError("Arm A inputs changed during retrieval; run is stale")
        report = _evaluate_report(
            evaluator=self.evaluator,
            dataset=dataset,
            quality_policy=quality_policy,
            observations=observations,
            collected=collected,
            top_k=top_k,
        )
        return ArmARunResult(
            report=report,
            collected_manifest=collected,
            execution_mode="test",
            formal_run_eligible=False,
        )


class OfficialArmARunner:
    """Own the formal provider and collector; observation injection is impossible."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        git_executable: str | tuple[str, ...] | None = None,
        rg_executable: str | None = None,
        evaluator: AgentQualityEvaluator | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.git_repository = GitRepository(
            self.workspace_root, git_executable=git_executable
        )
        self.rg_executable = rg_executable
        self.evaluator = evaluator or AgentQualityEvaluator()

    def run(
        self,
        *,
        run_id: str,
        dataset: VersionedAgentQualityCases,
        quality_policy: QualityGatePolicy,
        search_patterns: Mapping[str, Sequence[str]],
        search_roots: Sequence[str],
        top_k: int = 10,
        protocol_document_sha256: str = "legacy-unbound",
    ) -> ArmARunResult:
        if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9._-]+", run_id) is None:
            raise ValueError("run_id must contain only letters, digits, dot, underscore, or hyphen")
        if dataset.benchmark_scope == "held_out" and re.fullmatch(
            r"sha256:[0-9a-f]{64}", protocol_document_sha256
        ) is None:
            raise ValueError(
                "held-out formal runs require the complete protocol document SHA-256"
            )
        started_at = _utc_now()
        collector = RunManifestCollector(
            self.workspace_root, git_repository=self.git_repository
        )
        corpus_snapshot = collector.canonical_corpus_snapshot(search_roots)
        provider = RgLiveReadProvider(
            self.workspace_root,
            search_patterns=search_patterns,
            corpus_snapshot=corpus_snapshot,
            rg_executable=self.rg_executable,
        )
        before = collector.capture(
            dataset=dataset,
            quality_policy=quality_policy,
            search_patterns=search_patterns,
            search_roots=search_roots,
            top_k=top_k,
            provider_config_sha256=provider.provider_config_sha256,
            protocol_document_sha256=protocol_document_sha256,
        )
        if before.corpus_snapshot != corpus_snapshot:
            raise RuntimeError("provider corpus differs from captured canonical corpus")
        observations = {case.case_id: provider(case, top_k) for case in dataset.cases}
        _verify_returned_file_hashes(self.workspace_root, observations)
        collected = collector.finalize(
            before,
            dataset=dataset,
            quality_policy=quality_policy,
            search_patterns=search_patterns,
            search_roots=search_roots,
            top_k=top_k,
            provider_config_sha256=provider.provider_config_sha256,
            protocol_document_sha256=protocol_document_sha256,
        )
        if collected.manifest.evidence_status != "fresh":
            raise RuntimeError("Arm A inputs changed during retrieval; run is stale")
        _verify_returned_file_hashes(self.workspace_root, observations)
        report = _evaluate_report(
            evaluator=self.evaluator,
            dataset=dataset,
            quality_policy=quality_policy,
            observations=observations,
            collected=collected,
            top_k=top_k,
        )
        attestation = OfficialArmAExecutionAttestation(
            run_id=run_id,
            started_at=started_at,
            finished_at=_utc_now(),
            repository_root=before.repository_root,
            branch=before.branch,
            worktree_path=before.worktree_path,
            os=platform.platform(),
            architecture=platform.machine(),
            python_version=sys.version.split()[0],
            normalized_environment=provider.normalized_environment,
            rg_identity=provider.executable_identity,
            command_traces=tuple(provider.command_traces),
            provider_config_sha256=provider.provider_config_sha256,
        )
        return ArmARunResult(
            report=report,
            collected_manifest=collected,
            execution_mode="formal",
            formal_run_eligible=True,
            execution_attestation=attestation,
        )


def _evaluate_report(
    *,
    evaluator: AgentQualityEvaluator,
    dataset: VersionedAgentQualityCases,
    quality_policy: QualityGatePolicy,
    observations: Mapping[str, CaseObservation],
    collected: CollectedRunManifest,
    top_k: int,
) -> AgentQualityReport:
    envelope = {
            "observation_schema_version": ARM_A_OBSERVATION_SCHEMA_VERSION,
            "dataset_version": dataset.dataset_version,
            "dataset_sha256": dataset.dataset_sha256,
            "observations": {
                case_id: {
                    "retrieval": {
                        **dict(observation.retrieval.__dict__),
                        "ranked_results": [
                            dict(item.__dict__)
                            for item in observation.retrieval.ranked_results
                        ],
                    }
                }
                for case_id, observation in observations.items()
            },
        }
    return evaluator.evaluate(
            dataset_schema_version=dataset.dataset_schema_version,
            dataset_version=dataset.dataset_version,
            dataset_kind=dataset.dataset_kind,
            dataset_quality_gate_eligible=dataset.quality_gate_eligible,
            dataset_sha256=dataset.dataset_sha256,
            judgment_sha256=dataset.judgment_sha256,
            arm_id="arm_a_rg_live_read",
            cases=dataset.cases,
            observations=observations,
            run_manifest=collected.manifest,
            observation_schema_version=ARM_A_OBSERVATION_SCHEMA_VERSION,
            observation_envelope_sha256=_sha256(envelope),
            top_k=top_k,
            quality_policy=quality_policy,
            benchmark_scope=dataset.benchmark_scope,
            claim_scope=dataset.claim_scope,
            promotion_eligible=dataset.promotion_eligible,
        )


def _validate_search_protocol(
    dataset: VersionedAgentQualityCases,
    search_patterns: Mapping[str, Sequence[str]],
    search_roots: Sequence[str],
    top_k: int,
) -> None:
    case_ids = {case.case_id for case in dataset.cases}
    if set(search_patterns) != case_ids:
        raise ValueError("search_patterns must exactly cover dataset case IDs")
    for case_id, patterns in search_patterns.items():
        if not patterns or any(not isinstance(pattern, str) or not pattern for pattern in patterns):
            raise ValueError(f"search patterns must be non-empty strings: {case_id}")
    if not search_roots or any(not isinstance(root, str) or not root for root in search_roots):
        raise ValueError("search_roots must contain non-empty relative paths")
    for root in search_roots:
        if Path(root).is_absolute() or ".." in Path(root).parts:
            raise ValueError("search_roots must be workspace-relative")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify_returned_file_hashes(
    workspace_root: Path,
    observations: Mapping[str, CaseObservation],
) -> None:
    for case_id, observation in observations.items():
        for result in observation.retrieval.ranked_results:
            path = (workspace_root / result.relative_path).resolve()
            _require_within(path, workspace_root)
            if not path.is_file():
                raise RuntimeError(
                    f"returned file disappeared before finalization: {case_id}:{result.relative_path}"
                )
            if _file_sha256(path) != result.file_sha256:
                raise RuntimeError(
                    f"returned file changed before finalization: {case_id}:{result.relative_path}"
                )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace root: {path}") from exc
