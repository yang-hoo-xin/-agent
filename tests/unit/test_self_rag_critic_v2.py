"""Exposed Critic failures: layout quotes, initial retrieval and core conclusions."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.mod_agent.evaluation import self_rag_critic as critic
from tests.unit.test_self_rag_critic import _annotation, _identity, _native, _records


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("No network authorized"))


def test_pdf_layout_quote_maps_to_original_context_without_rewriting_it():
    candidate = critic.candidates_from_records(*_records())[0]
    candidate["contexts"][0]["text"] = "The color\n  is blue."
    original = deepcopy(candidate)
    sample, reasons = critic.select_generator_sample(candidate, _annotation())
    assert sample is not None, reasons
    assert candidate == original
    match = critic.locate_quote(candidate["contexts"][0]["text"], "The color is blue.")
    assert match == {"start": 0, "end": 20, "raw_text": "The color\n  is blue.",
                     "match_kind": "layout_whitespace"}


def test_schema_rejects_no_retrieval_with_evidence_support():
    annotation = _annotation()
    annotation["labels"].update(retrieval="no_retrieval", relevance=None)
    assert not Draft202012Validator(critic.SCHEMA).is_valid(annotation)


def test_no_retrieval_accepts_verifiable_input_derivation_not_only_nonfactual():
    candidate = critic.candidates_from_records(*_records())[0]
    candidate.update(question="What is 7 + 5?", answer="7 + 5 = 12.", contexts=[],
                     source_constraint={"decision_stage": "before_retrieval", "mode": "self_contained"})
    annotation = _annotation()
    annotation.update(core_claim="7 + 5 = 12.", core_verdict="derivable_from_input", evidence_quotes=[])
    annotation["labels"].update(retrieval="no_retrieval", relevance=None, support=None)
    sample, reasons = critic.select_generator_sample(candidate, annotation)
    assert sample is not None, reasons
    assert sample["evidence"] is None and sample["labels"]["support"] is None


@pytest.mark.parametrize("quote", ["The color is red.", "The colour is blue.", "The color是 blue."])
def test_word_changes_are_not_layout_matches(quote):
    assert critic.locate_quote("The color\n  is blue.", quote) is None


def test_quotes_cannot_switch_context_or_join_across_contexts():
    candidate = critic.candidates_from_records(*_records())[0]
    annotation = _annotation()
    annotation["evidence_quotes"][0]["context_index"] = 2
    assert critic.select_generator_sample(candidate, annotation)[0] is None
    annotation["evidence_quotes"][0].update(context_index=1, quote="The color is blue. The number is seven.")
    assert critic.select_generator_sample(candidate, annotation)[0] is None


def _calibration_plan(tmp_path):
    answers, retrieval = _records(6)
    for index, (case_id, arm) in enumerate(critic._CALIBRATION):
        answers[index].update(case_id=case_id, arm=arm)
        retrieval[index].update(case_id=case_id, arm=arm)
    paths = []
    for name, rows in (("answers", answers), ("retrieval", retrieval)):
        path = tmp_path / (name + ".jsonl")
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding="utf-8")
        paths.append(path)
    generator = Path(critic.__file__).parents[2] / "observability/evaluation/answer_generation.py"
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps({"generator_source_sha256": critic.file_ref(generator)["sha256"]}), encoding="utf-8")
    prepared = critic.prepare(*paths, tmp_path / "prepared", calibration=True, generation_protocol_path=protocol)
    return Path(prepared["path"])


def test_calibration_expectations_stay_host_side_and_never_export_training(tmp_path, monkeypatch):
    prepared = _calibration_plan(tmp_path)
    plan = json.loads(prepared.read_bytes())
    replies = []
    for item in plan["candidates"]:
        expected = plan["calibration_expectations"][item["sample_id"]]
        annotation = _annotation()
        for key, value in expected.items():
            selected = value[0] if isinstance(value, list) else value
            if key == "support":
                annotation["labels"][key] = selected
            elif key == "maximum_utility":
                annotation["labels"]["utility"] = selected
            else:
                annotation[key] = selected
        if annotation["core_verdict"] == "contradicted":
            annotation["evidence_quotes"][0]["relation"] = "contradicts_core"
        replies.append(annotation)
    requests = _native(monkeypatch, replies)
    result = critic.execute(prepared, identity_reader=_identity)
    assert len(requests) == 6 and result["calibration"]["passed"] is True
    assert result["calibration"]["passed_count"] == 6
    assert result["selected_for_generator"] == 0
    assert Path(result["train_data_ref"]["path"]).read_bytes() == b""
    assert any(row["meets_generator_selection_policy"] for row in result["records"])
    for request, record in zip(requests, result["records"]):
        user = json.loads(json.loads(request)["messages"][1]["content"])
        assert set(user) == {"sample_id", "case_id", "arm", "question", "answer", "source_constraint", "contexts"}
        assert user["source_constraint"] == {"decision_stage": "before_retrieval", "mode": "supplied_contexts_only"}
        assert "expected" not in json.dumps(user)
        assert record["annotation_bindings"]["evidence_quotes"][0]["span"]["raw_text"] == "The color is blue."


def test_calibration_rejects_v1_style_false_positive_even_with_good_quote():
    candidate = critic.candidates_from_records(*_records())[0]
    annotation = _annotation()
    outcome = critic._calibration_check(annotation, critic._CALIBRATION[("holdout_06", "bm25")],
                                       critic.annotation_bindings(candidate, annotation), [])
    assert outcome["passed"] is False
    assert set(outcome["failed_checks"]) == {"support", "unsupported_factual_claims", "maximum_utility"}


def _observed_calibration(case_id, arm):
    path = Path(__file__).parents[1] / "fixtures/evaluation/self_rag_critic_calibration_v2_observed.json"
    frozen = json.loads(path.read_bytes())
    row = next(row for row in frozen["rows"]
               if (row["candidate"]["case_id"], row["candidate"]["arm"]) == (case_id, arm))
    for field in ("candidate", "annotation"):
        assert hashlib.sha256(critic.canonical(row[field])).hexdigest() == row[field + "_source_sha256"]
    return row["candidate"], row["annotation"]


def _check_observed(candidate, annotation):
    Draft202012Validator(critic.SCHEMA).validate(annotation)
    return critic._calibration_check(annotation,
        critic._CALIBRATION[(candidate["case_id"], candidate["arm"])],
        critic.annotation_bindings(candidate, annotation),
        critic.annotation_semantic_errors(candidate, annotation))


def test_observed_q8_hybrid_is_a_complete_supported_factual_answer_not_refusal():
    candidate, annotation = _observed_calibration("holdout_08", "hybrid")
    assert "media type `application/json`" in candidate["answer"]
    assert "The media type for JSON text is application/json." in candidate["contexts"][1]["text"]
    assert "has no effect on compliant recipients" in candidate["answer"]
    assert "Adding one really has no effect on compliant recipients." in candidate["contexts"][2]["text"]
    assert annotation["answer_kind"] == "factual" and annotation["completeness"] == "complete"
    assert _check_observed(candidate, annotation)["passed"] is True
    annotation["answer_kind"] = "refusal"
    assert "answer_kind" in _check_observed(candidate, annotation)["failed_checks"]


def test_observed_q8_bm25_still_fails_for_omitting_requested_media_type():
    candidate, annotation = _observed_calibration("holdout_08", "bm25")
    assert "What type does RFC 8259 register" in candidate["question"]
    assert "application/json" not in candidate["answer"]
    assert set(_check_observed(candidate, annotation)["failed_checks"]) == {"completeness", "maximum_utility"}


@pytest.mark.parametrize("arm,failures", [
    ("bm25", {"support", "unsupported_factual_claims", "maximum_utility", "original_text_binding"}),
    ("hybrid", {"maximum_utility", "original_text_binding"}),
])
def test_observed_q6_bad_answers_still_fail_without_misjudging_the_chosen_premise(arm, failures):
    candidate, annotation = _observed_calibration("holdout_06", arm)
    assert "JSON-text = ws value ws" in candidate["answer"]
    context = candidate["contexts"][0 if arm == "bm25" else 2]["text"]
    assert "A JSON value MUST be an object, array, number, or string" in context
    assert set(_check_observed(candidate, annotation)["failed_checks"]) == failures


@pytest.mark.parametrize("arm", ["bm25", "hybrid"])
def test_q6_whole_answer_failure_can_coexist_with_a_supported_exact_core(arm):
    candidate, _ = _observed_calibration("holdout_06", arm)
    # 为什么要有它：整答的排他性结论错误，不能迫使其中真实的语法前提也被标成矛盾。
    annotation = {"labels": {"retrieval": "retrieve", "relevance": "relevant",
        "support": "partially_supported", "utility": 2}, "answer_kind": "factual",
        "unsupported_factual_claims": True, "core_claim": "JSON-text = ws value ws",
        "core_verdict": "supported", "completeness": "incomplete",
        "issue": "The object/array-only conclusion conflicts with the grammar; RFC scalar examples are missing.",
        "evidence_quotes": [{"context_index": 1 if arm == "bm25" else 3,
            "quote": "JSON-text = ws value ws", "relation": "supports_core"}]}
    assert _check_observed(candidate, annotation)["passed"] is True
    annotation["labels"]["utility"] = 5
    assert "maximum_utility" in _check_observed(candidate, annotation)["failed_checks"]


def test_changed_calibration_expected_is_rejected_before_any_model_call(tmp_path, monkeypatch):
    prepared = _calibration_plan(tmp_path)
    plan = json.loads(prepared.read_bytes())
    plan["calibration_expectations"] = {}
    prepared.write_text(json.dumps(plan), encoding="utf-8")
    requests = _native(monkeypatch, [])
    with pytest.raises(ValueError, match="CALIBRATION_EXPECTATION_CHANGED"):
        critic.execute(prepared, identity_reader=_identity)
    assert requests == [] and not (prepared.parent / "execution").exists()


@pytest.mark.parametrize("field,value", [("purpose", "generator_candidates"),
                                         ("self_rag_split", "exposed_training_candidates")])
def test_calibration_single_field_cannot_switch_to_training(tmp_path, monkeypatch, field, value):
    prepared = _calibration_plan(tmp_path)
    plan = json.loads(prepared.read_bytes())
    plan[field] = value
    prepared.write_text(json.dumps(plan), encoding="utf-8")
    requests = _native(monkeypatch, [])
    with pytest.raises(ValueError, match="PLAN_PURPOSE_INCONSISTENT"):
        critic.execute(prepared, identity_reader=_identity)
    assert requests == [] and not (prepared.parent / "execution").exists()


def test_blank_core_is_not_an_auditable_answer_claim():
    candidate = critic.candidates_from_records(*_records())[0]
    annotation = _annotation()
    annotation["core_claim"] = " "
    assert critic.select_generator_sample(candidate, annotation)[0] is None
    assert critic.locate_quote("One two", " ") is None
    assert critic.locate_quote("One\n\t two", "\n\t ") is None


def test_v1_prepared_not_replayed_or_overwritten(tmp_path, monkeypatch):
    prepared = _calibration_plan(tmp_path)
    plan = json.loads(prepared.read_bytes())
    plan["schema_version"] = "self_rag_critic_preparation_v1"
    prepared.write_text(json.dumps(plan), encoding="utf-8")
    before = prepared.read_bytes()
    requests = _native(monkeypatch, [])
    with pytest.raises(ValueError, match="PREPARATION_CHANGED"):
        critic.execute(prepared, identity_reader=_identity)
    assert prepared.read_bytes() == before and requests == []


@pytest.mark.parametrize("damage", ["source_constrained_no_retrieval", "contradiction", "missing_part",
                                    "unrelated_quotes", "invented_core", "unsupported_flag"])
def test_core_or_completeness_failure_cannot_be_saved_by_a_matching_quote(damage):
    candidate = critic.candidates_from_records(*_records())[0]
    annotation = _annotation()
    if damage == "source_constrained_no_retrieval":
        annotation["labels"].update(retrieval="no_retrieval", relevance=None, support=None)
        annotation.update(evidence_quotes=[], core_verdict="derivable_from_input")
    elif damage == "contradiction":
        annotation["core_verdict"] = "contradicted"
    elif damage == "missing_part":
        annotation["completeness"] = "incomplete"
    elif damage == "unrelated_quotes":
        annotation["evidence_quotes"][0]["relation"] = "other"
    elif damage == "invented_core":
        annotation["core_claim"] = "The color is red."
    else:
        annotation["unsupported_factual_claims"] = True
    assert critic.select_generator_sample(candidate, annotation)[0] is None
