"""Actual execution isolation tests for the two calibration adapters."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.mod_agent.evidence.calibration import (
    ActualExecutionIsolationError,
    PHASE_1_DIAGNOSTIC_COMPARISON_STATUS,
    calibration_summary,
    run_better_hit_feedback_calibration,
    run_wall_crawler_calibration,
)
from src.mod_agent.evidence.models import EvidencePack


class _UnusedModel:
    def complete(self, messages: tuple[dict[str, object], ...]) -> str:
        raise AssertionError("Incomplete dependency injection must stop before model use.")


def _r8_root(tmp_path: Path) -> Path:
    root = tmp_path / "r8"
    modules = root / "Assets" / "Scripts" / "Modules-ASM"
    datablocks = root / "Datablocks"
    modules.mkdir(parents=True)
    datablocks.mkdir(parents=True)
    (modules / "EnemySignals.cs").write_text(
        "public class EnemySignals {\n"
        "    public void NotifyReaction() {}\n"
        "    public void MoveOnSurface() {}\n"
        "}\n",
        encoding="utf-8",
    )
    (datablocks / "layout.json").write_text(
        '{"area": "maintenance", "movement": "ground"}\n',
        encoding="utf-8",
    )
    return root


def test_actual_adapter_api_rejects_answer_bearing_inputs() -> None:
    forbidden_parameters = {
        "hook_symbols",
        "hook_target",
        "expected_evidence",
        "expected_missing_evidence",
        "required_missing_evidence",
        "expected_sufficiency",
        "expected_control_action",
        "golden",
        "annotation",
        "prior_output",
        "prior_rag_output",
    }
    for adapter in (
        run_better_hit_feedback_calibration,
        run_wall_crawler_calibration,
    ):
        parameters = set(inspect.signature(adapter).parameters)
        assert parameters.isdisjoint(forbidden_parameters)


def test_actual_adapters_contain_no_case_answer_injection() -> None:
    source = Path(inspect.getsourcefile(run_better_hit_feedback_calibration) or "")
    text = source.read_text(encoding="utf-8")
    forbidden_fragments = (
        "_BHF_SYMBOLS",
        "_WC_SYMBOLS",
        "ES_Hitreact",
        "ES_PathMove",
        "hook_symbols=",
        "hook_target",
        "_missing_requirement",
        '"request_type"',
        '"evidence_requirements"',
        '"search_terms"',
        '"expected_sufficiency"',
        '"expected_control_action"',
        "annotation.json",
        "historical_reference",
        "prior_rag_output",
    )
    assert all(fragment not in text for fragment in forbidden_fragments)


@pytest.mark.parametrize(
    ("runner", "request_text", "allowed_relative_roots"),
    (
        (
            run_better_hit_feedback_calibration,
            "Show a brief marker when an enemy reaction occurs.",
            (("Assets", "Scripts", "Modules-ASM"),),
        ),
        (
            run_wall_crawler_calibration,
            "Allow configured enemies to move over walls while retaining normal movement.",
            (("Assets", "Scripts", "Modules-ASM"), ("Datablocks",)),
        ),
    ),
)
def test_actual_read_boundary_only_reads_registered_r8_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: object,
    request_text: str,
    allowed_relative_roots: tuple[tuple[str, ...], ...],
) -> None:
    root = _r8_root(tmp_path)
    allowed_roots = tuple(
        root.joinpath(*relative_parts).resolve()
        for relative_parts in allowed_relative_roots
    )
    original = Path.read_text
    reads: list[Path] = []

    def recording_read_text(path: Path, *args: object, **kwargs: object) -> str:
        resolved = path.resolve()
        reads.append(resolved)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)
    pack = runner(r8_root=root, request=request_text)  # type: ignore[operator]

    assert reads
    assert all(
        any(path == allowed or allowed in path.parents for allowed in allowed_roots)
        for path in reads
    )
    assert pack.hook_discovery is None
    assert pack.can_generate_patch is False


def test_phase_1_summary_marks_diagnostic_as_noncomparable() -> None:
    summary = json.loads(
        calibration_summary(
            EvidencePack.empty(query="phase one diagnostic", reason="no match")
        )
    )

    assert (
        summary["comparison_status"]
        == PHASE_1_DIAGNOSTIC_COMPARISON_STATUS
    )
    assert summary["manifest_bound_comparable"] is False


def test_actual_adapter_fails_closed_on_missing_source_root(tmp_path: Path) -> None:
    with pytest.raises(ActualExecutionIsolationError, match="r8_modules_source"):
        run_better_hit_feedback_calibration(
            r8_root=tmp_path / "missing",
            request="Observe a gameplay reaction.",
        )


def test_phase_2_calibration_dependencies_are_all_or_none(tmp_path: Path) -> None:
    root = _r8_root(tmp_path)
    with pytest.raises(ActualExecutionIsolationError, match="requires model"):
        run_better_hit_feedback_calibration(
            r8_root=root,
            request="Observe a gameplay reaction.",
            model=_UnusedModel(),
        )
