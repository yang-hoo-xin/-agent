"""Focused integrity checks for the bounded directional retrieval pilot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.run_retrieval_directional_pilot import (
    _load_object,
    _recommend,
    _validate_cases,
)

CASES = Path("evaluation/directional/v2_ret_directional_001_cases_v1.json")
RESULT = Path(
    "evaluation/directional/results/"
    "v2_ret_directional_001_v2_"
    "1e0ded1a0d1ff91cbcc6fbd7876330c4927736b394924036805528a5cd87ffb4.json"
)


def test_frozen_directional_cases_remain_small_and_valid() -> None:
    raw = _load_object(CASES)
    _validate_cases(raw, Path(".").resolve())

    assert len(raw["code_cases"]) == 8
    assert len(raw["community_cases"]) == 4
    assert raw["community_corpus"]["kind"] == "synthetic_plumbing_only"


def test_valid_raw_result_hash_and_dataset_binding_are_stable() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))

    assert hashlib.sha256(RESULT.read_bytes()).hexdigest() in RESULT.name
    assert payload["dataset_file_sha256"] == (
        "sha256:" + hashlib.sha256(CASES.read_bytes()).hexdigest()
    )
    assert payload["workspace_binding"]["inputs_fresh_at_completion"] is True


def test_missing_authentic_d_data_selects_insufficient_evidence() -> None:
    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    decision = _recommend(
        payload["arm_a"]["cases"],
        payload["arm_b"]["cases"],
        payload["arm_d"]["cases"],
        payload["arm_d"]["evidence_grade"],
    )

    assert decision["choice"] == "insufficient_evidence_retain_rg_no_expansion"
    assert decision["community_direction_status"] == (
        "unknown_no_authentic_traceable_corpus"
    )
