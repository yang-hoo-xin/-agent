"""Definition-only checks for the B1 frozen RAG case checkpoint."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest

from tests.tooling.archived_bm25_benchmark import load_archived_bm25_dataset
from tests.tooling.frozen_rag_case_definitions import (
    METRIC_DEFINITIONS,
    load_frozen_rag_case_definitions,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/evaluation/frozen_rag_case_definitions_v1.json"
ARCHIVED_SMOKE_FIXTURE = (
    ROOT / "tests/fixtures/evaluation/archived_bm25_benchmark_cases.json"
)
SOURCE_REVISION = "50b77a56fb759f391d0d3f91b0e6db03d0dd4cd2"
ARCHIVED_SMOKE_RAW_SHA256 = (
    "sha256:494d7e61240a23a716e4764f45e54bf9dc04f60dd47571bc882ed346be01ee51"
)
ARCHIVED_SMOKE_CASE_IDS = (
    "exact_measurement_states",
    "cross_file_custom_metric_discovery",
    "honest_denominator_accounting",
    "current_source_precedes_community",
    "retrieval_score_is_not_write_authority",
    "missing_per_change_semantic_owner",
    "unit_tests_do_not_prove_build_runtime",
    "reserved_wave1_b_scope",
)
HELD_OUT_CASE_IDS = (
    "held_out_semantic_assurance_v0_machine_boundary",
    "held_out_human_semantic_decision_exact_binding",
)


def _load() -> Any:
    return load_frozen_rag_case_definitions(FIXTURE, workspace_root=ROOT)


def _changed_fixture(tmp_path: Path, mutate: Any) -> Path:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutate(raw)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(raw), encoding="utf-8")
    return changed


def test_b1_definitions_are_five_new_pre_execution_cases() -> None:
    dataset = _load()

    assert dataset.dataset_schema_version == "frozen_rag_case_definitions_v1"
    assert dataset.dataset_id == "coding_agent_v0_b1_rag_case_definitions_v1"
    assert dataset.source_revision == SOURCE_REVISION
    assert dataset.top_k == 3
    assert len(dataset.corpus) == 7
    assert len(dataset.cases) == 5
    assert dataset.development_adjustment_case_ids == ()
    assert tuple(
        case.case_id for case in dataset.cases if case.split == "held_out"
    ) == HELD_OUT_CASE_IDS
    assert sum(case.split == "development" for case in dataset.cases) == 3
    assert dataset.case_governance.first_execution_status == "not_executed"
    assert (
        dataset.case_governance.prior_benchmark_adjustment_status
        == "not_participated"
    )
    assert dataset.case_governance.held_out_case_ids == HELD_OUT_CASE_IDS
    assert dataset.metric_definitions == METRIC_DEFINITIONS


def test_every_source_ref_hash_span_and_qrel_is_frozen() -> None:
    dataset = _load()
    corpus_by_id = {item.evidence_id: item for item in dataset.corpus}

    assert [item.source_ref for item in dataset.corpus] == [
        "src/mod_agent/proposal/models.py#L64-L125",
        "src/mod_agent/execution/patch_apply.py#L347-L395",
        "src/mod_agent/execution/patch_apply.py#L398-L469",
        "src/mod_agent/evidence/requirement_coverage_provider.py#L783-L803",
        "src/mod_agent/evidence/requirement_coverage.py#L480-L563",
        "src/mod_agent/planning/implementation_plan.py#L420-L464",
        "src/mod_agent/product_execution.py#L1633-L1744",
    ]
    assert all(item.source_sha256.startswith("sha256:") for item in dataset.corpus)
    for case in dataset.cases:
        assert case.expected_relevant_ids
        assert set(case.expected_relevant_ids) == set(case.relevance_reasons)
        assert set(case.expected_relevant_ids) <= set(corpus_by_id)


def test_fixture_contains_no_execution_or_score_payload() -> None:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    serialized = json.dumps(raw, sort_keys=True)

    assert "observations" not in raw
    assert "results" not in raw
    assert "retrieved_ids" not in serialized
    assert "metric_results" not in serialized
    assert '"score"' not in serialized
    assert '"value"' not in serialized


def test_existing_eight_case_archived_smoke_is_byte_identical_and_not_held_out() -> None:
    current_blob = subprocess.run(
        [
            "git",
            "show",
            "HEAD:tests/fixtures/evaluation/archived_bm25_benchmark_cases.json",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    archived_bytes = subprocess.run(
        [
            "git",
            "show",
            f"{SOURCE_REVISION}:tests/fixtures/evaluation/archived_bm25_benchmark_cases.json",
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    dataset = load_archived_bm25_dataset(
        ARCHIVED_SMOKE_FIXTURE,
        workspace_root=ROOT,
    )

    assert current_blob == archived_bytes
    assert "sha256:" + hashlib.sha256(current_blob).hexdigest() == (
        ARCHIVED_SMOKE_RAW_SHA256
    )
    assert tuple(case.case_id for case in dataset.cases) == ARCHIVED_SMOKE_CASE_IDS
    assert [case.split for case in dataset.cases] == ["development"] * 7 + [
        "reserved"
    ]
    assert all(case.split != "held_out" for case in dataset.cases)


def test_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"dataset_schema_version":"frozen_rag_case_definitions_v1",'
        '"dataset_schema_version":"frozen_rag_case_definitions_v1"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_frozen_rag_case_definitions(duplicate, workspace_root=ROOT)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda raw: raw["corpus"][0].__setitem__(
                "source_sha256", "sha256:" + "0" * 64
            ),
            "archived source SHA-256 mismatch",
        ),
        (
            lambda raw: raw["corpus"][0].__setitem__("end_line", 100000),
            "corpus span exceeds archived source",
        ),
    ],
)
def test_loader_rejects_hash_or_span_drift(
    tmp_path: Path,
    mutate: Any,
    message: str,
) -> None:
    changed = _changed_fixture(tmp_path, mutate)

    with pytest.raises(ValueError, match=message):
        load_frozen_rag_case_definitions(changed, workspace_root=ROOT)


def test_loader_rejects_schema_or_held_out_governance_drift(tmp_path: Path) -> None:
    mutations = [
        (
            lambda raw: raw.__setitem__("observations", []),
            "dataset fields must match exactly",
        ),
        (
            lambda raw: raw["case_governance"].__setitem__(
                "held_out_case_ids", [HELD_OUT_CASE_IDS[0]]
            ),
            "held_out_case_ids must exactly match",
        ),
        (
            lambda raw: raw.__setitem__(
                "development_adjustment_case_ids",
                ["development_coverage_v2_unresolved_gap_gate"],
            ),
            "must be empty before first execution",
        ),
    ]

    for index, (mutation, message) in enumerate(mutations):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        changed = _changed_fixture(case_dir, mutation)
        with pytest.raises(ValueError, match=message):
            load_frozen_rag_case_definitions(changed, workspace_root=ROOT)
