"""Completion-only data handling and installed training math, without GPU load."""
from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.run_patch_sft_training import (
    CompletionOnlyCollator,
    SFTParameters,
    _base_identity,
    file_ref,
    load_train_examples,
    tokenize_completion,
)


class CharacterTemplateTokenizer:
    eos_token_id = 3

    def apply_chat_template(self, messages, *, tools, tokenize, add_generation_prompt, enable_thinking):
        assert tokenize is False and enable_thinking is False
        body = json.dumps(tools) + "\n"
        for message in messages:
            body += message["role"] + ": " + message["content"] + "\x03\n"
        return body + ("assistant: " if add_generation_prompt else "")

    def __call__(self, text, *, add_special_tokens):
        assert add_special_tokens is False
        return {"input_ids": [ord(char) for char in text]}


def _example():
    return {"sample_id": "synthetic-train-one", "split": "train", "prompt": [
        {"role": "system", "content": "Preserve requirements and B0."},
        {"role": "user", "content": "B0 original; preserve existing state."},
        {"role": "assistant", "content": "C1 WRONG_PRIOR_CODE"},
        {"role": "tool", "content": "F1 measured compiler error"}],
        "completion": [{"role": "assistant", "content": "C2 valid synthetic completion"}],
        "tools": [], "loss_contract": {"completion_only_loss": True}}


def test_prior_assistant_and_tool_text_are_context_only_and_complete_target_is_supervised():
    example = _example()
    row, proof = tokenize_completion(example, CharacterTemplateTokenizer(), max_sequence_length=8192)
    boundary = proof["prompt_tokens"]
    assert all(label == -100 for label in row["labels"][:boundary])
    assert row["labels"][boundary:] == row["input_ids"][boundary:]
    assert "WRONG_PRIOR_CODE" in "".join(chr(value) for value in row["input_ids"][:boundary])
    assert "WRONG_PRIOR_CODE" not in "".join(chr(value) for value in row["labels"][boundary:])
    assert proof["supervised_eos_present"] and proof["input_truncated"] is False
    assert len(row["input_ids"]) == proof["total_tokens"]


def test_overlength_is_rejected_without_truncating_requirements_or_failure():
    with pytest.raises(ValueError, match="SFT_SEQUENCE_TOO_LONG_NO_TRUNCATION"):
        tokenize_completion(_example(), CharacterTemplateTokenizer(), max_sequence_length=20)


def test_mismatched_chat_prefix_is_rejected_instead_of_guessing_loss_boundary():
    class WrongPrefix(CharacterTemplateTokenizer):
        def apply_chat_template(self, *args, **kwargs):
            text = super().apply_chat_template(*args, **kwargs)
            return text + "changed-header" if kwargs["add_generation_prompt"] else text
    with pytest.raises(ValueError, match="SFT_CHAT_TEMPLATE_PREFIX_NOT_EXACT"):
        tokenize_completion(_example(), WrongPrefix(), max_sequence_length=8192)


@pytest.mark.parametrize("change", ["full_history", "two_targets", "tool_target"])
def test_non_completion_supervision_is_rejected(change):
    example = _example()
    if change == "full_history":
        example["loss_contract"]["completion_only_loss"] = False
    elif change == "two_targets":
        example["completion"].append(deepcopy(example["completion"][0]))
    else:
        example["completion"][0]["role"] = "tool"
    with pytest.raises(ValueError, match="SFT_COMPLETION_ONLY_EXAMPLE_REQUIRED"):
        tokenize_completion(example, CharacterTemplateTokenizer(), max_sequence_length=8192)


def test_training_loader_opens_only_explicit_training_ref_not_validation_or_holdout(tmp_path):
    path = tmp_path/"train.jsonl"
    path.write_text(json.dumps(_example())+"\n", encoding="utf-8")
    config = {"train_data_ref": file_ref(path), "train_sample_ids": ["synthetic-train-one"],
        "validation_data_ref": {"path": str(tmp_path/"must-not-open-validation"), "sha256": "0"*64},
        "holdout_data_ref": {"path": str(tmp_path/"must-not-open-holdout"), "sha256": "0"*64}}
    assert load_train_examples(config) == [_example()]
    config["train_sample_ids"] = ["another-task"]
    with pytest.raises(ValueError, match="SFT_TRAIN_SAMPLE_SET_MISMATCH"):
        load_train_examples(config)
    changed = _example()
    changed["split"] = "validation"
    path.write_text(json.dumps(changed), encoding="utf-8")
    config.update(train_data_ref=file_ref(path), train_sample_ids=[changed["sample_id"]])
    with pytest.raises(ValueError, match="SFT_NON_TRAIN_SAMPLE_FORBIDDEN"):
        load_train_examples(config)


def test_base_hash_drift_and_absent_trainable_weights_block_gpu_preparation(tmp_path):
    names = ("config.json", "tokenizer_config.json", "tokenizer.json")
    for name in names:
        (tmp_path/name).write_text("{}", encoding="utf-8")
    config = {"base": {"model_id": "owned-tiny-test", "revision": "f"*40,
        "directory": str(tmp_path), "file_refs": [file_ref(tmp_path/name) for name in names]}}
    assert _base_identity(config, require_weights=False)["weights_required_and_checked"] is False
    with pytest.raises(ValueError, match="SFT_COMPLETE_WEIGHT_IDENTITIES_REQUIRED"):
        _base_identity(config, require_weights=True)
    (tmp_path/"config.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="SFT_INPUT_BYTES_CHANGED"):
        _base_identity(config, require_weights=False)


def test_collator_never_shifts_or_relabels_prompt_and_refuses_larger_microbatch():
    torch = pytest.importorskip("torch")
    row, _ = tokenize_completion(_example(), CharacterTemplateTokenizer(), max_sequence_length=8192)
    collator = CompletionOnlyCollator()
    actual = collator([row])
    assert actual["labels"].tolist() == [row["labels"]] and actual["labels"].dtype == torch.long
    with pytest.raises(ValueError, match="SFT_MICROBATCH_MUST_BE_ONE"):
        collator([row, row])


def test_installed_chunked_nll_preserves_masked_causal_loss_and_gradients_on_tiny_cpu_model():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("trl")
    from transformers.models.qwen3.configuration_qwen3 import Qwen3Config
    from transformers.models.qwen3.modeling_qwen3 import Qwen3ForCausalLM
    from trl.trainer.sft_trainer import _patch_chunked_ce_lm_head
    torch.manual_seed(7)
    base = Qwen3ForCausalLM(Qwen3Config(vocab_size=32, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, head_dim=8,
        attention_dropout=0.0, use_cache=False)).eval()
    chunked = deepcopy(base)
    ids = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 8]])
    labels = ids.clone()
    labels[:, :5] = -100
    expected = base(input_ids=ids, labels=labels).loss
    expected.backward()
    _patch_chunked_ce_lm_head(chunked, chunk_size=2)
    result = chunked(input_ids=ids, labels=labels)
    result.loss.backward()
    assert torch.allclose(result.loss, expected, atol=1e-6)
    assert result.num_valid_tokens.item() == 3
    assert torch.allclose(chunked.lm_head.weight.grad, base.lm_head.weight.grad, atol=1e-6)


def test_real_local_tokenizer_masks_owned_long_revision_without_loading_gpu_weights():
    directory = os.environ.get("PATCH_SFT_TOKENIZER_DIR")
    example_path = os.environ.get("PATCH_SFT_PROBE_EXAMPLE")
    if not directory or not example_path:
        pytest.skip("Explicit local tokenizer and owned supervision example are required")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
    example = json.loads(Path(example_path).read_text(encoding="utf-8"))
    _, evidence = tokenize_completion(example, tokenizer, max_sequence_length=8192)
    assert evidence["prompt_tokens"] == 6264 and evidence["completion_tokens"] == 206
    assert evidence["prompt_all_masked"] and evidence["supervised_eos_present"] and not evidence["input_truncated"]


def test_default_parameters_are_bounded_without_asserting_training_feasibility():
    params = SFTParameters()
    assert params.epochs == 3 and params.gradient_accumulation_steps == 1 and params.max_sequence_length == 8192
    with pytest.raises(ValueError, match="SFT_PARAMETER_INVALID"):
        SFTParameters(epochs=100)


def test_installed_trainer_consumes_exact_masks_trains_lora_and_reloads_on_tiny_cpu_model(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("trl")
    from datasets import Dataset
    from peft import LoraConfig, PeftModel, get_peft_model
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from transformers import PreTrainedTokenizerFast
    from transformers.models.qwen3.configuration_qwen3 import Qwen3Config
    from transformers.models.qwen3.modeling_qwen3 import Qwen3ForCausalLM
    from trl import SFTTrainer

    from scripts.run_patch_sft_training import _adapter_state_hash, _training_args
    torch.manual_seed(7)
    config = Qwen3Config(vocab_size=32, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, head_dim=8,
        attention_dropout=0.0, use_cache=False)
    base = Qwen3ForCausalLM(config)
    saved_base = deepcopy(base.state_dict())
    model = get_peft_model(base, LoraConfig(task_type="CAUSAL_LM", r=2, lora_alpha=4,
        lora_dropout=0, target_modules=["q_proj", "v_proj"]))
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=Tokenizer(WordLevel(
        {"<pad>": 0, "<eos>": 1, "<unk>": 2, **{str(i): i for i in range(3, 32)}}, unk_token="<unk>")),
        pad_token="<pad>", eos_token="<eos>", unk_token="<unk>")
    arguments = _training_args(SFTParameters(), tmp_path, probe=True)
    arguments.use_cpu = True  # This test validates the real interface, not GPU memory feasibility.
    arguments.bf16 = False
    arguments.fp16 = False
    arguments.gradient_checkpointing = False
    arguments.disable_tqdm = True
    data = {"input_ids": [2, 3, 4, 5, 6, 7, 1], "attention_mask": [1]*7, "labels": [-100]*4+[6, 7, 1]}
    before, _ = _adapter_state_hash(model)
    trainer = SFTTrainer(model=model, args=arguments, train_dataset=Dataset.from_list([data]),
        processing_class=tokenizer, data_collator=CompletionOnlyCollator())
    result = trainer.train()
    after, _ = _adapter_state_hash(model)
    assert before != after and trainer.state.global_step == 1 and math.isfinite(result.training_loss)
    target = tmp_path/"adapter"
    trainer.save_model(str(target))
    original = Qwen3ForCausalLM(config)
    original.load_state_dict(saved_base)
    reloaded = PeftModel.from_pretrained(original, str(target), local_files_only=True, is_trainable=False)
    assert _adapter_state_hash(reloaded)[0] == after


@pytest.mark.parametrize("dtype_name", ["float32", "bfloat16"])
def test_registered_training_attention_is_native_efficient_only_and_gradient_equivalent(monkeypatch, dtype_name):
    if os.environ.get("PATCH_SFT_SMALL_GPU_CHECKS") != "1":
        pytest.skip("Explicit small-tensor GPU diagnostic selection is required")
    from types import SimpleNamespace

    import torch
    import torch.nn.functional as functional
    from torch.nn.attention import SDPBackend, sdpa_kernel
    from transformers import AttentionInterface, AttentionMaskInterface

    from scripts.run_patch_sft_training import register_training_attention
    torch.manual_seed(2026)
    dtype = getattr(torch, dtype_name)
    q = torch.randn(1, 16, 64, 128, device="cuda", dtype=dtype, requires_grad=True)
    k = torch.randn(1, 8, 64, 128, device="cuda", dtype=dtype, requires_grad=True)
    v = torch.randn_like(k, requires_grad=True)
    weight = torch.randn_like(q)
    with sdpa_kernel([SDPBackend.MATH]):
        expected = functional.scaled_dot_product_attention(q, k, v, is_causal=True, enable_gqa=True)
    gradients = torch.autograd.grad((expected.float()*weight.float()).sum(), (q, k, v))
    original_attention, original_mask = AttentionInterface()["sdpa"], AttentionMaskInterface()["sdpa"]
    key = register_training_attention(SFTParameters(attention_backend="patch_sft_repeat_kv_efficient_v1"))
    assert AttentionInterface()["sdpa"] is original_attention and AttentionMaskInterface()["sdpa"] is original_mask
    assert AttentionMaskInterface()[key] is original_mask
    selected = []
    original_sdpa = functional.scaled_dot_product_attention
    def observed(*args, **kwargs):
        selected.append({"math": torch.backends.cuda.math_sdp_enabled(), "efficient": torch.backends.cuda.mem_efficient_sdp_enabled(),
            "flash": torch.backends.cuda.flash_sdp_enabled(), "cudnn": torch.backends.cuda.cudnn_sdp_enabled(), "gqa": kwargs["enable_gqa"]})
        return original_sdpa(*args, **kwargs)
    monkeypatch.setattr(functional, "scaled_dot_product_attention", observed)
    output, attention_weights = AttentionInterface()[key](SimpleNamespace(is_causal=True), q, k, v, None)
    actual = output.transpose(1, 2)
    actual_gradients = torch.autograd.grad((actual.float()*weight.float()).sum(), (q, k, v))
    assert attention_weights is None
    assert selected == [{"math": False, "efficient": True, "flash": False, "cudnn": False, "gqa": False}]
    tolerance = {"rtol": 1e-4, "atol": 1e-5} if dtype_name == "float32" else {"rtol": 0.03, "atol": 0.02}
    torch.testing.assert_close(actual, expected, **tolerance)
    for actual_gradient, expected_gradient in zip(actual_gradients, gradients, strict=True):
        torch.testing.assert_close(actual_gradient, expected_gradient, **tolerance)


@pytest.mark.parametrize("dtype_name", ["float16", "bfloat16"])
def test_reload_accepts_only_exact_lossless_adapter_upcast(dtype_name):
    import torch

    from scripts.run_patch_sft_training import compare_adapter_states
    saved = {"lora_A.weight": torch.tensor([0.125, -0.5, 1.0], dtype=getattr(torch, dtype_name))}
    loaded = {key: value.float() for key, value in saved.items()}
    result = compare_adapter_states(saved, loaded)
    assert result["all_values_exact"] and not result["byte_identity_equal"]
    assert result["dtype_transitions"] == {"torch." + dtype_name + "->torch.float32": 1}
    assert result["saved_state_sha256"] != result["loaded_state_sha256"]


@pytest.mark.parametrize("change", ["delete", "add", "shape", "value", "downcast", "nan"])
def test_reload_rejects_changed_adapter_even_when_dtype_conversion_is_allowed(change):
    import torch

    from scripts.run_patch_sft_training import compare_adapter_states
    saved = {"lora_A.weight": torch.tensor([0.125, -0.5, 1.0], dtype=torch.bfloat16)}
    loaded = {key: value.float() for key, value in saved.items()}
    if change == "delete":
        loaded = {}
    elif change == "add":
        loaded["extra"] = torch.tensor([0.0])
    elif change == "shape":
        loaded["lora_A.weight"] = loaded["lora_A.weight"].unsqueeze(0)
    elif change == "value":
        loaded["lora_A.weight"][0] += 1e-6  # No numerical tolerance may hide a changed weight.
    elif change == "downcast":
        saved["lora_A.weight"] = saved["lora_A.weight"].float()
        loaded["lora_A.weight"] = loaded["lora_A.weight"].to(torch.bfloat16)
    else:
        loaded["lora_A.weight"][0] = float("nan")
    with pytest.raises(ValueError, match="SFT_ADAPTER_RELOAD_"):
        compare_adapter_states(saved, loaded)
