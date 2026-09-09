"""Working views are generated from final combined bytes, not individual model claims."""
import hashlib

from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.proposal.working_view import build_materialized_patch_view
from tests.unit.test_repair_submission_validation import _materialized


def test_view_is_current_implementation_and_diff_without_writing_baseline(tmp_path):
    before = "class Subject {\n    public int Apply() => 1;\n}\n"
    after = "class Subject {\n    public int Apply() => 2;\n}\n"
    materialized, _, _ = _materialized(tmp_path, before, after)
    view = build_materialized_patch_view(materialized, context_radius_lines=2)
    assert view["code_sha256"] == materialized.code_sha256
    source = view["files"][0]
    assert source["complete"] is True
    assert source["hunks"] == [{"start_line": 1, "end_line": 3, "text": after}]
    assert "-    public int Apply() => 1;" in source["unified_diff"]
    assert "+    public int Apply() => 2;" in source["unified_diff"]
    assert (tmp_path / "Subject.cs").read_bytes() == before.encode()


def test_current_coordinates_shift_and_multiple_changes_compose(tmp_path):
    before = "head\nA();\n" + "\n".join(f"unchanged_{i}" for i in range(20)) + "\nB();\ntail\n"
    path = tmp_path / "Subject.cs"
    path.write_text(before, encoding="utf-8", newline="")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    bindings = [{"binding_id": key, "canonical_target_path": "Subject.cs", "source_hash": digest,
        "target_span": {"start_line": line, "end_line": line}}
        for key, line in (("edit_a", 2), ("edit_b", 23))]
    changes = [{"change_id": key, "edit_binding_id": key, "patch": {"kind": "exact_text_replace",
        "before_text": old, "after_text": new, "expected_occurrences": 1}}
        for key, old, new in (("edit_a", "A();", "A1();\nA2();"), ("edit_b", "B();", "B2();"))]
    materialized = materialize_exact_text_patch(workspace_root=tmp_path, diff_intent=changes,
        implementation_plan={"binding_registry": {"edit_bindings": bindings}})
    view = build_materialized_patch_view(materialized, context_radius_lines=1)
    source = view["files"][0]
    assert source["complete"] is False
    assert len(source["hunks"]) == 2
    assert source["hunks"][1]["start_line"] == 23
    assert "B2();" in source["hunks"][1]["text"]
    assert "A1();\nA2();" in source["hunks"][0]["text"]
    assert source["raw_bytes_sha256"] == hashlib.sha256(materialized.files["Subject.cs"]).hexdigest()
    assert path.read_bytes() == before.encode()


def test_bom_hash_is_raw_and_crlf_text_is_preserved(tmp_path):
    before = "\ufeffclass Subject { public int Apply() => 1; }\r\n"
    after = "\ufeffclass Subject { public int Apply() => 2; }\r\n"
    materialized, _, _ = _materialized(tmp_path, before, after)
    source = build_materialized_patch_view(materialized, context_radius_lines=1)["files"][0]
    assert source["hunks"][0]["text"] == after.removeprefix("\ufeff")
    assert source["raw_bytes_sha256"] == hashlib.sha256(after.encode()).hexdigest()


def test_diff_display_keeps_lines_separate_without_final_newline(tmp_path):
    before = "class Subject { public int Apply() => 1; }"
    after = "class Subject { public int Apply() => 2; }"
    materialized, _, _ = _materialized(tmp_path, before, after)
    source = build_materialized_patch_view(materialized, context_radius_lines=1)["files"][0]
    assert source["hunks"][0]["text"] == after
    assert f"-{before}\n+{after}\n" in source["unified_diff"]
