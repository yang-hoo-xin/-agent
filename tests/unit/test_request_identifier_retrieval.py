"""Original code identifiers survive coarse model retrieval categories."""
import hashlib
import json

import pytest

from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider, _request_source_identifiers
from src.mod_agent.evidence.requirement_coverage_provider import RequirementCoverageEvidenceProvider
from src.mod_agent.planning.clarified_request import product_description


QUERIES = (
    {"query_id": "q1", "query": "configuration", "requirement_id": "r1"},
    {"query_id": "q2", "query": "runtime diagnostics", "requirement_id": "r2"},
)


def _sources(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "Options.cs").write_text(
        "public static class TuningAPI\n{\n"
        "    // Options source\n"
        "    public static float SetValue(float value)\n    {\n        return value;\n    }\n}\n",
        encoding="utf-8")
    for name in ("FirstCaller", "SecondCaller"):
        (source / f"{name}.cs").write_text(
            f"class {name}\n{{\n" + "\n".join(
                f"    public float Read{i}() => TuningAPI.SetValue(1); // configuration runtime diagnostics"
                for i in range(20)) + "\n}\n", encoding="utf-8")
    return source


@pytest.mark.parametrize("user_query", [
    "修复 TuningAPI.SetValue 的边界行为。",
    "Change TuningAPI to reject invalid values.",
    "Change SetValue() to reject invalid values.",
    "Change Options.cs to reject invalid values.",
])
def test_original_identifier_survives_coarse_queries_and_caller_frequency(tmp_path, user_query):
    source = _sources(tmp_path)
    provider = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192)
    baseline = provider.collect_query_set(queries=QUERIES, search_root="src", max_items=2)
    assert all(not item.source_path.endswith("Options.cs") for item in baseline.items)
    actual = provider.collect_query_set(queries=QUERIES, search_root="src", max_items=2,
                                        source_identity_query=user_query)
    selected = actual.items[0]
    assert selected.source_path == "src/Options.cs"
    assert selected.excerpt == (source / "Options.cs").read_bytes().decode("utf-8")
    assert selected.source_hash == hashlib.sha256((source / "Options.cs").read_bytes()).hexdigest()
    assert len(actual.items) <= 2
    assert actual.can_generate_patch is False
    assert actual.readiness == "insufficient"
    assert actual.requirement_coverage is None
    assert [row["query_id"] for row in actual.budget_summary["per_query_execution"]] == ["q1", "q2"]
    receipts = actual.budget_summary["request_identifier_queries"]
    assert all(row["origin"] == "user_request_identifier" and "requirement_id" not in row for row in receipts)
    assert selected.evidence_id in {value for row in receipts for value in row["evidence_ids"]}


def test_ordinary_language_does_not_create_identifier_queries():
    assert _request_source_identifiers("Change the configuration and preserve runtime diagnostics.") == ()
    assert _request_source_identifiers("Preserve API and UI behavior.") == ()
    assert _request_source_identifiers("修改 TuningAPI.SetValue；Options.cs；set_value()") == (
        "TuningAPI", "SetValue", "Options.cs", "set_value")
    assert len(_request_source_identifiers(" ".join(f"SomeType{i}" for i in range(20)))) == 8


def test_absent_identifier_has_no_inferred_source_or_support(tmp_path):
    _sources(tmp_path)
    actual = RgLiveEvidenceProvider(tmp_path).collect_query_set(
        queries=QUERIES, search_root="src", max_items=2,
        source_identity_query="Change MissingType.MissingMethod().")
    assert all(row["retrieval_status"] == "no_matches" and row["evidence_ids"] == []
               for row in actual.budget_summary["request_identifier_queries"])
    assert actual.can_generate_patch is False


def test_normal_requirement_provider_passes_original_request_before_findings(tmp_path):
    _sources(tmp_path)
    request = "修复 TuningAPI.SetValue 的边界行为。"
    feature = {
        "feature_id": "feature_original_identifier", "user_request": request,
        "target_behavior": "Correct configuration behavior.", "non_goals": [],
        "acceptance_criteria": [], "evidence_requirements": [], "runtime_verification_plan": [],
    }
    projection = {
        "requirements": [{"role": "change", "text": "Correct configuration behavior.",
            "input_obligation_indexes": [1, 2], "query_leads": ["configuration", "runtime diagnostics"]}],
        "relations": [{"parent_requirement_indexes": [1], "meaning": "Current behavior."}],
        "input_dispositions": [],
    }
    captured = []
    def findings(materialized, retrieved):
        captured.append((materialized, retrieved))
        return {"findings": []}
    actual = RequirementCoverageEvidenceProvider(
        RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192),
        projection_factory=lambda _: projection, findings_factory=findings,
    ).collect(query=request, search_root="src", feature_data=feature)
    materialized, retrieved = captured[0]
    assert [row["query"] for row in materialized["queries"]] == ["configuration", "runtime diagnostics"]
    assert retrieved.items[0].source_path == "src/Options.cs"
    assert actual.can_generate_patch is False


def _clarified_request(original, answer):
    return product_description([
        {"role": "original_user_request", "content": original},
        {"role": "assistant_clarification_context", "content": "选择AssistantOnly.cs还是AlternativeAPI？"},
        {"role": "user_answer_or_correction", "content": answer}],
        {"action": "new_project", "target_id": "", "project_name": "SelectedOnlyName", "clarification": ""})


def test_clarified_metadata_and_assistant_names_do_not_consume_identifier_slots():
    request = _clarified_request("修复 TuningAPI.SetValue。", "也检查 Options.cs 和 set_value()。")
    assert _request_source_identifiers(request) == ("TuningAPI", "SetValue", "Options.cs", "set_value")


def test_metadata_spelling_literally_written_by_user_remains_a_source_hint():
    request = _clarified_request("修改 original_user_request 与 execution_start。", "再检查 conversation_turns()。")
    assert _request_source_identifiers(request) == ("original_user_request", "execution_start", "conversation_turns")


def test_clarified_identifier_receipt_keeps_complete_original_request_hash(tmp_path):
    _sources(tmp_path)
    request = _clarified_request("修复 TuningAPI.SetValue。", "检查 Options.cs。")
    actual = RgLiveEvidenceProvider(tmp_path, small_file_max_bytes=8192).collect_query_set(
        queries=QUERIES, search_root="src", max_items=2, source_identity_query=request)
    receipts = actual.budget_summary["request_identifier_queries"]
    assert {row["query"] for row in receipts} == {"TuningAPI", "SetValue", "Options.cs"}
    assert all(row["request_sha256"] == hashlib.sha256(request.encode("utf-8")).hexdigest() for row in receipts)
    assert actual.items[0].source_path == "src/Options.cs" and actual.can_generate_patch is False


def test_malformed_known_clarification_wrapper_fails_before_hint_extraction():
    document = json.loads(_clarified_request("TuningAPI", "Options.cs"))
    document["conversation_turns"][1]["role"] = "user_answer_or_correction"
    with pytest.raises(ValueError, match="CLARIFIED_PRODUCT_REQUEST_TURNS_INVALID"):
        _request_source_identifiers(json.dumps(document))
