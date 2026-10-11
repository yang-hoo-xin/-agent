"""Compilation and formal checks must describe the same binary content.

为什么要有它：其他 DLL 的通过记录不能替代当前编译产物的行为证据，同字节交付副本仍应可复用。
"""

import json
from pathlib import Path

import pytest

from src.mod_agent.planning.member_repair_learning import extract_member_repair, file_ref
from tests.unit.test_member_repair_learning import inputs, save


def _formal_delivery_copy(tmp_path, *, same_bytes):
    selected, _ = inputs(tmp_path)
    passed = json.loads(Path(selected["passed_report_ref"]["path"]).read_text(encoding="utf-8"))
    compiled = Path(passed["built_artifact_ref"]["path"])
    delivered = tmp_path / "run" / "delivered-copy.dll"
    delivered.write_bytes(compiled.read_bytes() if same_bytes else b"different binary with unrelated passing checks")
    delivered_ref = file_ref(delivered)
    assert delivered_ref["path"] != passed["built_artifact_ref"]["path"]
    assert (delivered_ref["sha256"] == passed["built_artifact_ref"]["sha256"]) is same_bytes

    formal_path = Path(selected["formal_checks_ref"]["path"])
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    formal["assembly_ref"] = delivered_ref
    selected["formal_checks_ref"] = save(formal_path, formal)
    delivery_path = Path(selected["delivery_ref"]["path"])
    delivery = json.loads(delivery_path.read_text(encoding="utf-8"))
    delivery["evidence_refs"] = [delivered_ref]
    selected["delivery_ref"] = save(delivery_path, delivery)
    return selected


def test_formal_checks_for_different_binary_cannot_back_compilation_success(tmp_path):
    selected = _formal_delivery_copy(tmp_path, same_bytes=False)
    with pytest.raises(ValueError):
        extract_member_repair(**selected)


def test_formal_checks_for_byte_identical_copy_can_back_compilation_success(tmp_path):
    selected = _formal_delivery_copy(tmp_path, same_bytes=True)
    candidate = extract_member_repair(**selected)
    assert candidate["status"] == "candidate_pending_transfer"
    assert candidate["passed_compilation"] == "passed"
    assert candidate["member_substitution"]["passed_member"] == "LogInfo"


@pytest.mark.parametrize("mismatched_record", ["request", "stdout"])
def test_formal_case_for_different_binary_cannot_back_matching_top_level_dll(tmp_path, mismatched_record):
    selected, _ = inputs(tmp_path)
    unrelated = tmp_path / "run" / "unrelated.dll"
    unrelated.write_bytes(b"different binary in the original probe record")
    unrelated_ref = file_ref(unrelated)
    formal_path = Path(selected["formal_checks_ref"]["path"])
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    assert unrelated_ref["sha256"] != formal["assembly_ref"]["sha256"]
    record_key = mismatched_record + "_ref"
    record_path = Path(formal["cases"][0][record_key]["path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if mismatched_record == "request":
        record["assembly"] = unrelated_ref
    else:
        record["assembly_sha256"] = unrelated_ref["sha256"]
    formal["cases"][0][record_key] = save(record_path, record)
    selected["formal_checks_ref"] = save(formal_path, formal)
    with pytest.raises(ValueError):
        extract_member_repair(**selected)
