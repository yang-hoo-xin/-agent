"""CPU-only token masking, real tiny optimizer updates, and exact adapter reload."""
from __future__ import annotations

import json

import pytest

from src.mod_agent.evaluation.reflection_tokens import (
    ALL_TOKENS,
    PARAGRAPH_TOKENS,
    REFLECTION_TOKENS,
    reflection_example,
    register_reflection_tokens,
    tokenize_reflection_sample,
)
from src.mod_agent.evaluation.self_rag_adapter import (
    attach_reflection_adapter,
    changed_reflection_families,
    load_reflection_adapter,
    reflection_row_state,
    save_reflection_adapter,
)


@pytest.fixture(autouse=True)
def cpu_offline(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("No model download or provider request permitted"))


def _sample():
    return {"schema_version": "self_rag_reflection_sample_v1", "sample_id": "cpu-unit-only", "split": "train",
        "label_origin": "synthetic_calibration", "question": "Which color?", "evidence": "The color is blue.",
        "answer": "Blue.", "labels": {"retrieval": "retrieve", "relevance": "relevant",
                                      "support": "fully_supported", "utility": 5}}


def _tokenizer():
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import PreTrainedTokenizerFast

    vocabulary = {word: index for index, word in enumerate(
        ["[UNK]", "[EOS]", "[PAD]", "user", "assistant", ":", "question", "Which", "color", "The", "is", "blue", "Blue", ".", "?"])}
    engine = Tokenizer(WordLevel(vocabulary, unk_token="[UNK]"))
    engine.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=engine, unk_token="[UNK]", eos_token="[EOS]", pad_token="[PAD]")
    tokenizer.chat_template = "{% for message in messages %}{{message['role']}}: {{message['content']}}{{eos_token}}\n{% endfor %}{% if add_generation_prompt %}assistant: {% endif %}"
    return tokenizer


@pytest.mark.parametrize("decision", ["retrieve", "continue", "no_retrieval"])
def test_labels_are_supervised_but_prompt_and_retrieved_body_are_masked(decision):
    tokenizer = _tokenizer()
    tokens = register_reflection_tokens(tokenizer)
    sample = _sample()
    sample["labels"]["retrieval"] = decision
    if decision == "no_retrieval":
        sample["evidence"] = None
        sample["labels"].update(relevance=None, support=None)
    row, proof = tokenize_reflection_sample(sample, tokenizer, token_ids=tokens, max_sequence_length=128)
    assert all(label == -100 for label in row["labels"][:proof["prompt_tokens"]])
    assert tokens[REFLECTION_TOKENS["retrieval"][decision]] in row["labels"]
    assert tokens["[Utility:5]"] in row["labels"]
    if decision == "retrieve":
        start, end = (row["input_ids"].index(tokens[token]) for token in PARAGRAPH_TOKENS)
        assert end > start + 1 and all(value == -100 for value in row["labels"][start + 1:end])
        assert proof["retrieved_content_tokens_masked"] == end - start - 1
        assert tokens["[Relevant]"] in row["labels"] and tokens["[Fully supported]"] in row["labels"]
    else:
        assert proof["retrieved_content_tokens_masked"] == 0
    assert proof["supervised_eos_present"] and len(set(tokens.values())) == len(ALL_TOKENS)


@pytest.mark.parametrize("damage", ["patch_sample", "holdout", "missing_family", "utility_bool", "control_in_evidence", "no_retrieval_evidence"])
def test_non_self_rag_or_invalid_labels_do_not_become_training_targets(damage):
    sample = _sample()
    if damage == "patch_sample":
        sample["schema_version"] = "patch_sft_sample_v1"
    elif damage == "holdout":
        sample["split"] = "holdout"
    elif damage == "missing_family":
        sample["labels"].pop("support")
    elif damage == "utility_bool":
        sample["labels"]["utility"] = True
    elif damage == "control_in_evidence":
        sample["evidence"] += "[Fully supported]"
    else:
        sample["labels"]["retrieval"] = "no_retrieval"
    with pytest.raises(ValueError, match="SELF_RAG_"):
        reflection_example(sample)


def test_tiny_cpu_optimizer_trains_tied_reflection_rows_and_reloads_exactly(tmp_path):
    import torch
    from transformers import Qwen3Config, Qwen3ForCausalLM

    torch.set_num_threads(1)
    torch.manual_seed(11)
    tokenizer = _tokenizer()
    base = Qwen3ForCausalLM(Qwen3Config(vocab_size=len(tokenizer), hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, head_dim=8,
        max_position_embeddings=128, tie_word_embeddings=True, bos_token_id=1, eos_token_id=1, pad_token_id=2))
    original_embeddings = base.get_input_embeddings().weight.detach().clone()
    base.save_pretrained(tmp_path / "base")
    tokens = register_reflection_tokens(tokenizer)
    with pytest.raises(ValueError, match="SELF_RAG_REFLECTION_ROWS_NOT_TRAINED_BY_PLAIN_LORA"):
        reflection_row_state(base, tokens, require_trainable=True)
    model = attach_reflection_adapter(base, tokens, rank=2, alpha=4)
    before = reflection_row_state(model, tokens, require_trainable=True)
    with pytest.raises(ValueError, match="FAMILY_WEIGHTS_UNCHANGED"):
        changed_reflection_families(before, before)
    row, _ = tokenize_reflection_sample(_sample(), tokenizer, token_ids=tokens, max_sequence_length=128)
    batch = {key: torch.tensor([value]) for key, value in row.items()}
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=0.01, weight_decay=0)
    loss = model(**batch).loss
    assert torch.isfinite(loss)
    loss.backward()
    rows = model.get_input_embeddings().token_adapter.trainable_tokens_delta["default"]
    assert rows.grad is not None and torch.isfinite(rows.grad).all() and rows.grad.abs().sum() > 0
    optimizer.step()
    after = reflection_row_state(model, tokens, require_trainable=True)
    assert set(changed_reflection_families(before, after)) == set(REFLECTION_TOKENS)
    frozen = model.get_input_embeddings().token_adapter.base_layer.weight[:len(original_embeddings)].detach()
    assert torch.equal(frozen, original_embeddings)
    identity = {"scope": "random_tiny_CPU_unit_only", "seed": 11}
    save_reflection_adapter(model, tokenizer, tmp_path / "adapter", token_ids=tokens, base_identity=identity)
    model.eval()
    with torch.no_grad():
        expected_logits = model(input_ids=batch["input_ids"]).logits
    fresh = Qwen3ForCausalLM.from_pretrained(tmp_path / "base", local_files_only=True)
    reloaded, saved_tokenizer, comparison = load_reflection_adapter(fresh, tmp_path / "adapter", base_identity=identity)
    reloaded.eval()
    assert register_reflection_tokens(saved_tokenizer) == tokens and comparison["all_values_exact"]
    restored = reflection_row_state(reloaded, tokens)
    assert all(torch.equal(after[token], restored[token]) for token in tokens)
    with torch.no_grad():
        assert torch.equal(expected_logits, reloaded(input_ids=batch["input_ids"]).logits)
    manifest = tmp_path / "adapter/reflection_adapter.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["token_ids"]["[Retrieval]"] += 1
    manifest.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="RELOADED_TOKEN_IDS_CHANGED"):
        load_reflection_adapter(Qwen3ForCausalLM.from_pretrained(tmp_path / "base", local_files_only=True),
                                tmp_path / "adapter", base_identity=identity)


def test_installed_completion_trainer_updates_reflection_rows_on_cpu(tmp_path):
    import torch
    from datasets import Dataset
    from transformers import Qwen3Config, Qwen3ForCausalLM
    from trl import SFTConfig, SFTTrainer

    from scripts.run_patch_sft_training import CompletionOnlyCollator

    torch.set_num_threads(1)
    tokenizer = _tokenizer()
    base = Qwen3ForCausalLM(Qwen3Config(vocab_size=len(tokenizer), hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, head_dim=8,
        max_position_embeddings=128, tie_word_embeddings=True, eos_token_id=1, pad_token_id=2))
    tokens = register_reflection_tokens(tokenizer)
    model = attach_reflection_adapter(base, tokens, rank=2, alpha=4)
    row, _ = tokenize_reflection_sample(_sample(), tokenizer, token_ids=tokens, max_sequence_length=128)
    args = SFTConfig(output_dir=str(tmp_path / "trainer"), use_cpu=True, bf16=False, fp16=False,
        gradient_checkpointing=False, max_steps=1, per_device_train_batch_size=1, learning_rate=0.01,
        weight_decay=0, optim="adamw_torch", save_strategy="no", report_to="none", dataloader_pin_memory=False,
        remove_unused_columns=False, max_length=None, packing=False, padding_free=False,
        completion_only_loss=True, assistant_only_loss=False, loss_type="chunked_nll",
        dataset_kwargs={"skip_prepare_dataset": True})
    trainer = SFTTrainer(model=model, args=args, train_dataset=Dataset.from_list([row]),
        processing_class=tokenizer, data_collator=CompletionOnlyCollator())
    before = reflection_row_state(model, tokens, require_trainable=True)
    result = trainer.train()
    assert trainer.state.global_step == 1 and result.training_loss > 0
    assert set(changed_reflection_families(before, reflection_row_state(model, tokens))) == set(REFLECTION_TOKENS)
