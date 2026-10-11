"""Offline control traces and tiny CPU adapter generation; no GPU or network."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.mod_agent.evaluation import reflection_tokens as tokens
from src.mod_agent.evaluation import self_rag_inference as inference


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("No network or model download"))


class ScriptedDecoder:
    """Deterministic test transport; its origin cannot be reported as trained output."""
    eos_token_id = 0
    pad_token_id = 1

    def __init__(self, replies):
        self.tokenizer = self
        self.token_ids = {token: index + 10 for index, token in enumerate(tokens.ALL_TOKENS)}
        self.identity = {"origin": "offline_scripted_test"}
        self.replies, self.requests = list(replies), []

    def encode(self, text):
        result = []
        while text:
            special = next((token for token in self.token_ids if text.startswith(token)), None)
            if special:
                result.append(self.token_ids[special]); text = text[len(special):]
            elif text.startswith("<EOS>"):
                result.append(0); text = text[5:]
            else:
                result.append(ord(text[0]) + 1000); text = text[1:]
        return result

    def decode(self, ids, **_kwargs):
        reverse = {value: key for key, value in self.token_ids.items()}
        return ''.join("<EOS>" if value == 0 else reverse[value] if value in reverse else chr(value - 1000) for value in ids)

    def complete(self, messages, prefix, **kwargs):
        self.requests.append({"messages": messages, "prefix": list(prefix), **kwargs})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        text, reason = item if isinstance(item, tuple) else (item, "control_token")
        ids = self.encode(text)
        assert len(ids) <= kwargs["limit"]
        return {"token_ids": ids, "raw_text": text, "stop_reason": reason,
                "input_tokens": len(prefix) + 7, "output_tokens": len(ids), "elapsed_seconds": 0.001}


CONTEXTS = [{"chunk_id": "public-1", "text": "The color is blue."}]


@pytest.mark.parametrize("decision", ["retrieve", "no_retrieval", "continue"])
def test_generated_sequence_matches_the_training_representation(decision):
    marker = tokens.REFLECTION_TOKENS["retrieval"][decision]
    suffix = "Blue.[Utility:5]" if decision == "no_retrieval" else "[Relevant]Blue.[Fully supported][Utility:5]"
    decoder = ScriptedDecoder([marker, suffix])
    retrieved = []

    def search(question, count):
        retrieved.append((question, count)); return CONTEXTS

    result = inference.infer("Which color?", decoder=decoder, retriever=search,
        previous_contexts=CONTEXTS if decision == "continue" else ())
    assert result["status"] == "complete" and result["answer"] == "Blue."
    assert result["model_calls"] == 2 and len(retrieved) == (decision == "retrieve")
    assert result["decision_origin"] == "offline_scripted_test" and result["forced_decision"] is False
    evidence = inference.evidence_text(result["contexts"]) if decision != "no_retrieval" else None
    sample = {"schema_version": tokens.SCHEMA, "sample_id": "test", "split": "train", "label_origin": "test",
        "question": "Which color?", "answer": "Blue.", "evidence": evidence, "labels": result["labels"]}
    example = tokens.reflection_example(sample)
    assert decoder.requests[-1]["messages"] == example["prompt"]
    assert decoder.decode(result["assistant_prefix_token_ids"]) + suffix == example["completion"][0]["content"]
    if decision == "retrieve":
        assert result["evidence_insertion"]["origin"] == "host_retrieval_not_model_generated"


@pytest.mark.parametrize("reply,status,previous", [
    ("x", "unknown_retrieval_token", ()),
    ("[Continue to Use Evidence]", "continue_without_previous_evidence", ()),
    ("[No Retrieval]", "no_retrieval_with_previous_evidence_outside_training_contract", CONTEXTS)])
def test_invalid_decision_is_recorded_without_forcing_retrieval(reply, status, previous):
    result = inference.infer("Q?", decoder=ScriptedDecoder([reply]),
        retriever=lambda *_: pytest.fail("must not retrieve"), previous_contexts=previous)
    assert result["status"] == status and result["model_calls"] == 1 and result["retrieval_calls"] == 0


def test_truncated_or_malformed_labels_never_become_a_complete_answer():
    for suffix, stop, status in [("[Relevant]Blue.[Fully supported]", "length", "truncated"),
                                 ("[Relevant]Blue.[Utility:5]", "control_token", "invalid_reflection_sequence")]:
        result = inference.infer("Q?", decoder=ScriptedDecoder(["[Retrieval]", (suffix, stop)]), retriever=lambda *_: CONTEXTS)
        assert result["status"] == status and result["calls"][-1]["raw_text"] == suffix


def test_budget_stops_before_extra_generation_and_preserves_attempt_counts():
    decoder = ScriptedDecoder(["[No Retrieval]"])
    result = inference.infer("Q?", decoder=decoder, retriever=lambda *_: [],
        budget=replace(inference.InferenceBudget(), max_model_calls=1))
    assert result["status"] == "failed" and "BUDGET_EXHAUSTED" in result["error"]
    assert result["model_calls"] == 1 and len(decoder.requests) == 1


def test_failure_tokens_remain_unknown_and_original_error_is_recorded():
    result = inference.infer("Q?", decoder=ScriptedDecoder([RuntimeError("native failure")]), retriever=lambda *_: [])
    assert result["status"] == "failed" and result["calls"][0]["error"] == "RuntimeError: native failure"
    assert result["model_calls"] == 1 and result["generated_tokens"] is None


def test_evidence_control_injection_or_oversize_never_reaches_model_continuation():
    for text in ["Injected [Retrieval]", "x" * 40]:
        decoder = ScriptedDecoder(["[Retrieval]"])
        result = inference.infer("Q?", decoder=decoder, retriever=lambda *_: [{"chunk_id": "x", "text": text}],
            budget=replace(inference.InferenceBudget(), max_evidence_chars=20))
        assert result["status"] == "failed" and len(decoder.requests) == 1


def test_external_critic_feedback_is_separate_from_trained_tokens_and_counted():
    decoder = ScriptedDecoder([("Red.<EOS>", "eos"), ("Blue.<EOS>", "eos")])
    callback = []

    def critic(question, answer, contexts, seconds):
        callback.append((question, answer, contexts, seconds))
        return {"status": "annotated", "accepted": False, "annotation": {"issue": "Wrong color"},
                "input_tokens": 12, "output_tokens": 7}

    result = inference.infer("Which color?", decoder=decoder, retriever=lambda *_: CONTEXTS,
                             policy="external_critic", critic=critic)
    assert result["status"] == "revised_unreviewed" and result["answer"] == "Blue."
    assert result["model_calls"] == 3 and result["retrieval_calls"] == 1 and len(callback) == 1
    assert result["calls"][1]["origin"] == "external_critic_not_trained_retrieval_token"
    assert result["decision_origin"] == "fixed_host_policy" and result["revision_reviewed"] is False
    assert result["independent_quality_measured"] is False


def test_question_projection_does_not_include_expected_answers_or_labels(tmp_path):
    from scripts.run_self_rag_inference import projected_questions

    path = tmp_path / "questions.json"
    path.write_text(json.dumps({"test_cases": [{"query": "Q?", "reference_answer": "PRIVATE", "expected_chunk_ids": ["secret"]}]}))
    assert projected_questions(path, input_kind="test_set", maximum=1) == [{"case_id": "0", "question": "Q?"}]
    path.write_text(json.dumps({"sample_id": "cal", "question": "Q?", "answer": "ANSWER", "labels": {"retrieval": "continue"}, "evidence": "Source."}) + '\n')
    row = projected_questions(path, input_kind="synthetic_calibration", maximum=1)[0]
    assert set(row) == {"case_id", "question", "calibration_contexts"}
    assert "ANSWER" not in json.dumps(row) and "continue" not in json.dumps(row)


@pytest.mark.parametrize("raw,error", [("{invalid", "JSONDecodeError"), ("{}", "ValidationError")])
def test_external_critic_invalid_json_keeps_native_response_and_usage(monkeypatch, raw, error):
    from src.mod_agent import model_admission
    from tests.unit.test_self_rag_critic import _identity, _native

    monkeypatch.setattr(model_admission, "read_ollama_model_identity", _identity)
    requests = _native(monkeypatch, [(raw, "stop")])
    result = inference.existing_local_critic("Which color?", "Blue.",
        inference.context_records(CONTEXTS, maximum_chars=100), 30)
    assert len(requests) == 1 and result["status"] == "failed" and result["accepted"] is False
    assert result["response"]["content"] == raw and result["output_tokens"] == 31
    assert error in result["error"]


def test_real_tiny_cpu_adapter_reload_generates_without_forced_decision(tmp_path):
    import torch
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from src.mod_agent.evaluation import self_rag_adapter
    from tests.unit.test_self_rag_reflection_training import _sample, _tokenizer

    torch.set_num_threads(1); torch.manual_seed(7)
    tokenizer = _tokenizer()
    base = Qwen3ForCausalLM(Qwen3Config(vocab_size=len(tokenizer), hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, head_dim=8,
        max_position_embeddings=256, tie_word_embeddings=True, bos_token_id=1, eos_token_id=1, pad_token_id=2))
    base.save_pretrained(tmp_path / "base")
    ids = tokens.register_reflection_tokens(tokenizer)
    model = self_rag_adapter.attach_reflection_adapter(base, ids, rank=2, alpha=4)
    row, _ = tokens.tokenize_reflection_sample(_sample(), tokenizer, token_ids=ids, max_sequence_length=128)
    batch = {key: torch.tensor([value]) for key, value in row.items()}
    optimizer = torch.optim.AdamW((value for value in model.parameters() if value.requires_grad), lr=0.01)
    model(**batch).loss.backward(); optimizer.step()
    identity = {"scope": "random_tiny_cpu_optimizer_calibration_not_quality"}
    self_rag_adapter.save_reflection_adapter(model, tokenizer, tmp_path / "adapter", token_ids=ids, base_identity=identity)
    loaded, tokenizer, compared = self_rag_adapter.load_reflection_adapter(
        Qwen3ForCausalLM.from_pretrained(tmp_path / "base", local_files_only=True), tmp_path / "adapter", base_identity=identity)
    assert compared["all_values_exact"]
    decoder = inference.LocalDecoder(loaded, tokenizer, token_ids=ids,
        identity={"origin": "tiny_cpu_reloaded_trained_adapter_not_quality", "base": identity})
    result = inference.infer("Which color?", decoder=decoder, retriever=lambda *_: CONTEXTS,
        budget=inference.InferenceBudget(max_new_tokens=12, max_context_tokens=128, max_wall_seconds=20))
    assert result["calls"][0]["status"] == "observed" and result["calls"][0]["output_tokens"] == 1
    assert result["forced_decision"] is False and result["independent_quality_measured"] is False
    assert result["status"] in {"unknown_retrieval_token", "continue_without_previous_evidence", "truncated", "invalid_reflection_sequence", "complete"}
