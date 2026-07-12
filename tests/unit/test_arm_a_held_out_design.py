"""Pre-result design checks for the frozen held-out Arm A benchmark."""

from __future__ import annotations

from scripts.audit_arm_a_benchmark_design import audit_design


def test_held_out_design_passes_internal_pre_run_audit() -> None:
    result = audit_design()

    assert result["review_status"] == "ready_for_external_pre_run_review"
    assert result["formal_arm_a_authorized"] is False
    assert all(check["status"] == "pass" for check in result["checks"])
    assert result["input_hashes"]["protocol_file_sha256"].startswith("sha256:")
    assert result["input_hashes"]["dataset_canonical_sha256"].startswith("sha256:")
