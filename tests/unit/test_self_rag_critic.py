"""Critic preparation and real native transport serialization without model calls."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from src.mod_agent.evaluation import self_rag_critic as critic


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("No model/network execution authorized in these tests"))


def _records(count=1):
    answers, retrieval = [], []
    for index in range(count):
        contexts = [{"chunk_id": f"c{index}-{part}", "text": text} for part, text in enumerate(
            ("The color is blue.", "The number is seven.", "Unrelated public context."))]
        key = {"case_id": f"case-{index}", "arm": "bm25", "query": "What is the color?", "status": "observed"}
        answers.append({**key, "answer": "The color is blue. [context:1]", "context_ids": [row["chunk_id"] for row in contexts]})
        retrieval.append({**key, "results": contexts})
    return answers, retrieval


def _prepare(root, count=1):
    root.mkdir(parents=True, exist_ok=True)
    records = _records(count)
    paths = []
    for name, rows in zip(("answers", "retrieval"), records):
        path = root / (name + ".jsonl")
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding="utf-8")
        paths.append(path)
    prepared = critic.prepare(*paths, root / "prepared")
    return Path(prepared["path"]), records


def _annotation():
    return {"labels": {"retrieval": "retrieve", "relevance": "relevant", "support": "fully_supported", "utility": 5},
        "answer_kind": "factual", "unsupported_factual_claims": False, "core_claim": "The color is blue.",
        "core_verdict": "supported", "completeness": "complete", "issue": "",
        "evidence_quotes": [{"context_index": 1, "quote": "The color is blue.", "relation": "supports_core"}]}


def _identity(*_args):
    return {"name": critic.PROFILE["model"], "model": critic.PROFILE["model"],
        "digest": critic.PROFILE["digest"], "base_url": critic.PROFILE["base_url"],
        "details": {"context_length": 262144}, "capabilities": ["completion", "tools"]}


def _native(monkeypatch, replies):
    requests = []

    def handle(_transport, request):
        assert request.method == "POST" and str(request.url) == "http://127.0.0.1:11434/api/chat"
        requests.append(request.content)
        selected = replies[len(requests) - 1]
        if isinstance(selected, Exception):
            raise selected
        content, stop = selected if isinstance(selected, tuple) else (json.dumps(selected), "stop")
        return httpx.Response(200, request=request, json={"model": critic.PROFILE["model"],
            "message": {"role": "assistant", "content": content}, "done": True, "done_reason": stop,
            "prompt_eval_count": 17, "eval_count": 31})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return requests


def test_prepare_has_no_model_calls_and_keeps_original_answer_context_order(tmp_path, monkeypatch):
    monkeypatch.setattr(critic, "OllamaChatAgentAdapter", lambda **_: pytest.fail("Preparation created a client"))
    prepared, (answers, _) = _prepare(tmp_path, count=2)
    plan = json.loads(prepared.read_bytes())
    assert plan["model_calls_performed"] == 0 and plan["candidate_count"] == 2
    assert plan["unique_questions"] == 1 and plan["self_rag_holdout_eligible"] is False
    assert plan["profile"]["maximum_model_calls"] == 20 and plan["profile"]["max_output_tokens"] == 512
    request = json.loads(Path(plan["candidates"][0]["request_ref"]["path"]).read_bytes())
    assert request["messages"][1]["content"]["answer"] == answers[0]["answer"]
    assert [row["chunk_id"] for row in request["messages"][1]["content"]["contexts"]] == answers[0]["context_ids"]
    assert request["tools"] == [] and request["tool_choice"] == "none"


@pytest.mark.parametrize("damage", ["duplicate", "mismatched_context", "too_many"])
def test_bad_source_binding_or_more_than_twenty_is_rejected(damage):
    answers, retrieval = _records(21 if damage == "too_many" else 1)
    if damage == "duplicate":
        answers.append(deepcopy(answers[0]))
    elif damage == "mismatched_context":
        answers[0]["context_ids"].reverse()
    with pytest.raises(ValueError, match="SELF_RAG_CRITIC_"):
        critic.candidates_from_records(answers, retrieval)


@pytest.mark.parametrize("damage", ["unsupported", "partial", "low_utility", "irrelevant", "refusal", "unknown", "fake_quote", "no_retrieval_fact"])
def test_bad_or_unknown_answers_are_preserved_but_not_selected(damage):
    candidate = critic.candidates_from_records(*_records())[0]
    annotation = _annotation()
    if damage == "unsupported":
        annotation["unsupported_factual_claims"] = True
    elif damage == "partial":
        annotation["labels"]["support"] = "partially_supported"
    elif damage == "low_utility":
        annotation["labels"]["utility"] = 3
    elif damage == "irrelevant":
        annotation["labels"]["relevance"] = "irrelevant"
    elif damage == "refusal":
        annotation["answer_kind"] = "refusal"
    elif damage == "unknown":
        annotation["labels"]["utility"] = None
    elif damage == "fake_quote":
        annotation["evidence_quotes"][0]["quote"] = "The color is red."
    else:
        annotation["labels"].update(retrieval="no_retrieval", relevance=None, support=None)
    original = deepcopy((candidate, annotation))
    sample, reasons = critic.select_generator_sample(candidate, annotation)
    assert sample is None and reasons
    assert (candidate, annotation) == original


def test_native_wire_raw_output_rejections_usage_and_single_consumption_are_preserved(tmp_path, monkeypatch):
    prepared, (answers, _) = _prepare(tmp_path, count=2)
    rejected = _annotation()
    rejected.update(unsupported_factual_claims=True)
    requests = _native(monkeypatch, [_annotation(), rejected])
    result = critic.execute(prepared, identity_reader=_identity)
    assert len(requests) == result["model_calls_reserved"] == 2
    assert result["selected_for_generator"] == 1
    assert result["generation_transports_started"] == 2
    assert result["measured_usage"] == {"input_tokens": 34, "output_tokens": 62}
    assert result["annotation_label_counts"]["support"] == {"fully_supported": 2}
    assert result["selected_label_values"]["support"] == ["fully_supported"]
    for index, row in enumerate(result["records"]):
        assert row["ai_assessed"] is True and row["human_verified"] is False
        assert Path(row["provider_request_ref"]["path"]).read_bytes() == requests[index]
        native = json.loads(requests[index])
        assert native["options"]["num_predict"] == 512 and native["options"]["num_ctx"] == 32768
        raw = json.loads(Path(row["response_ref"]["path"]).read_bytes())
        assert Path(row["response_text_ref"]["path"]).read_text(encoding="utf-8") == raw["content"]
        assert row["measured_usage"] == {"input_tokens": 17, "output_tokens": 31}
        assert Path(row["annotation_ref"]["path"]).is_file()
    training = [json.loads(row) for row in Path(result["train_data_ref"]["path"]).read_text(encoding="utf-8").splitlines()]
    assert training[0]["answer"] == answers[0]["answer"] and training[0]["split"] == "train"
    assert training[0]["critic_annotation_ref"] == result["records"][0]["annotation_ref"]
    with pytest.raises(FileExistsError):
        critic.execute(prepared, identity_reader=_identity)
    assert len(requests) == 2


@pytest.mark.parametrize("failure", ["truncated", "duplicate_json", "transport", "identity_drift"])
def test_failed_annotation_never_becomes_a_training_row_and_never_retries(tmp_path, monkeypatch, failure):
    prepared, _ = _prepare(tmp_path)
    reply = _annotation()
    if failure == "truncated":
        reply = ('{"labels":', "length")
    elif failure == "duplicate_json":
        reply = ('{"labels":{},"labels":{}}', "stop")
    elif failure == "transport":
        reply = httpx.ReadTimeout("Controlled timeout")
    requests = _native(monkeypatch, [reply])
    reads = []

    def identity(*args):
        reads.append(args)
        value = _identity()
        if failure == "identity_drift" and len(reads) > 1:
            value["digest"] = "0" * 64
        return value

    result = critic.execute(prepared, identity_reader=identity)
    assert len(requests) == result["model_calls_reserved"] == 1
    assert result["selected_for_generator"] == 0
    row = result["records"][0]
    assert row["accepted_for_generator"] is False and row["status"] == "rejected_or_failed"
    if failure != "transport":
        assert Path(row["response_ref"]["path"]).exists()
        assert Path(row["response_text_ref"]["path"]).exists()
    assert Path(result["train_data_ref"]["path"]).read_bytes() == b""
    if failure == "transport":
        assert result["measured_usage"] is None


def test_changed_input_is_rejected_before_any_native_call(tmp_path, monkeypatch):
    prepared, _ = _prepare(tmp_path)
    (tmp_path / "answers.jsonl").write_text("changed", encoding="utf-8")
    requests = _native(monkeypatch, [])
    with pytest.raises(ValueError, match="SFT_INPUT_BYTES_CHANGED"):
        critic.execute(prepared, identity_reader=_identity)
    assert requests == []
