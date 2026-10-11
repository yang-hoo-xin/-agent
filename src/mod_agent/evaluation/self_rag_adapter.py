"""LoRA plus trainable reflection rows for the selected tied-embedding base model."""
from __future__ import annotations

import json
from pathlib import Path

from .reflection_tokens import ALL_TOKENS, REFLECTION_TOKENS, register_reflection_tokens


def attach_reflection_adapter(model, token_ids, *, rank, alpha, dropout=0.0):
    from peft import LoraConfig, get_peft_model

    if set(token_ids) != set(ALL_TOKENS) or not model.config.tie_word_embeddings:
        raise ValueError("SELF_RAG_EXACT_TOKENS_AND_TIED_EMBEDDINGS_REQUIRED")
    model.resize_token_embeddings(max(model.get_input_embeddings().num_embeddings, max(token_ids.values()) + 1),
                                  mean_resizing=False)
    model.tie_weights()
    config = LoraConfig(task_type="CAUSAL_LM", r=rank, lora_alpha=alpha, lora_dropout=dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none", trainable_token_indices=list(token_ids.values()), ensure_weight_tying=True)
    result = get_peft_model(model, config)
    reflection_row_state(result, token_ids, require_trainable=True)
    _expose_unbiased_head(result)
    return result


def _expose_unbiased_head(model):
    """TRL chunked NLL reads Linear.bias; PEFT's token wrapper omits that proxy.

    为什么要有它：只补当前无偏置输出层的真实元数据，保留分块损失和反思行梯度，不修改第三方库或计算。
    """
    head = model.get_output_embeddings()
    if head.token_adapter.get_base_layer().bias is not None:
        raise ValueError("SELF_RAG_UNBIASED_OUTPUT_HEAD_REQUIRED")
    head.bias = None


def reflection_row_state(model, token_ids, *, require_trainable=False):
    """Prove input and output actually share the selected trainable token rows."""
    try:
        embeddings = model.get_input_embeddings().token_adapter
        head = model.get_output_embeddings().token_adapter
        rows = embeddings.trainable_tokens_delta["default"]
        indexes = embeddings.token_indices["default"]
        if (rows is not head.trainable_tokens_delta["default"] or indexes != list(token_ids.values())
                or rows.shape[0] != len(token_ids) or (require_trainable and not rows.requires_grad)):
            raise ValueError("SELF_RAG_REFLECTION_ROWS_NOT_BOUND")
    except AttributeError as error:
        raise ValueError("SELF_RAG_REFLECTION_ROWS_NOT_TRAINED_BY_PLAIN_LORA") from error
    return {token: rows[index].detach().cpu().clone() for index, token in enumerate(token_ids)}


def changed_reflection_families(before, after):
    import torch

    changed = {family: [token for token in mapping.values() if not torch.equal(before[token], after[token])]
               for family, mapping in REFLECTION_TOKENS.items()}
    if any(not values for values in changed.values()):
        raise ValueError("SELF_RAG_REFLECTION_FAMILY_WEIGHTS_UNCHANGED")
    return changed


def save_reflection_adapter(model, tokenizer, directory, *, token_ids, base_identity):
    from scripts.run_patch_sft_training import file_ref, save_once, verify_saved_adapter

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    reflection_row_state(model, token_ids, require_trainable=True)
    model.save_pretrained(directory, safe_serialization=True, save_embedding_layers=False)
    tokenizer.save_pretrained(directory)
    comparison = verify_saved_adapter(model, directory)
    manifest = {"schema_version": "self_rag_token_adapter_v1", "base_identity": base_identity,
        "token_ids": token_ids, "tokenizer_size": len(tokenizer), "model_vocab_size": model.config.vocab_size,
        "tie_word_embeddings": True, "saved_files": [file_ref(path) for path in sorted(directory.iterdir()) if path.is_file()]}
    save_once(directory / "reflection_adapter.json", manifest)
    return comparison


def load_reflection_adapter(base_model, directory, *, base_identity, is_trainable=False):
    from peft import PeftModel
    from transformers import AutoTokenizer

    from scripts.run_patch_sft_training import read_exact, verify_saved_adapter

    directory = Path(directory)
    manifest = json.loads((directory / "reflection_adapter.json").read_text(encoding="utf-8"))
    if manifest["schema_version"] != "self_rag_token_adapter_v1" or manifest["base_identity"] != base_identity:
        raise ValueError("SELF_RAG_ADAPTER_BASE_IDENTITY_CHANGED")
    for reference in manifest["saved_files"]:
        if not Path(reference["path"]).resolve().is_relative_to(directory.resolve()):
            raise ValueError("SELF_RAG_ADAPTER_REFERENCE_OUTSIDE_DIRECTORY")
        read_exact(reference)
    tokenizer = AutoTokenizer.from_pretrained(directory, local_files_only=True, trust_remote_code=False)
    observed = register_reflection_tokens(tokenizer)
    if observed != manifest["token_ids"] or len(tokenizer) != manifest["tokenizer_size"]:
        raise ValueError("SELF_RAG_RELOADED_TOKEN_IDS_CHANGED")
    if not base_model.config.tie_word_embeddings:
        raise ValueError("SELF_RAG_TIED_EMBEDDINGS_REQUIRED")
    base_model.resize_token_embeddings(manifest["model_vocab_size"], mean_resizing=False)
    base_model.tie_weights()
    result = PeftModel.from_pretrained(base_model, directory, local_files_only=True, is_trainable=is_trainable)
    reflection_row_state(result, observed, require_trainable=is_trainable)
    _expose_unbiased_head(result)
    comparison = verify_saved_adapter(result, directory)
    return result, tokenizer, comparison
