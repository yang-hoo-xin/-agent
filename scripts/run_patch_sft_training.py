"""Local completion-only QLoRA SFT over explicitly selected owned train data.

The default mode only tokenizes and proves the loss mask. `probe` and `train`
load the GPU explicitly. No model request, network upload, DPO, product worker
change or holdout data read is performed. Validation selection is separate.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_ref(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def read_exact(ref):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("SFT_EXACT_REFERENCE_REQUIRED")
    path = Path(ref["path"])
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ValueError("SFT_LOCAL_ABSOLUTE_REFERENCE_REQUIRED")
    raw = path.read_bytes()
    if sha(raw) != ref["sha256"]:
        raise ValueError("SFT_INPUT_BYTES_CHANGED")
    return raw


def save_once(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(canonical(value))
    return file_ref(path)


@dataclass(frozen=True)
class SFTParameters:
    epochs: int = 3
    learning_rate: float = 0.0002
    lora_rank: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.0
    gradient_accumulation_steps: int = 1
    max_sequence_length: int = 8192
    seed: int = 42
    compute_dtype: str = "bfloat16"
    max_cuda_memory_fraction: float = 0.82
    max_wall_seconds: int = 900
    attention_backend: str = "sdpa"

    def __post_init__(self):
        for key, lower, upper in (("epochs", 1, 10), ("lora_rank", 1, 64), ("lora_alpha", 1, 256),
                                  ("gradient_accumulation_steps", 1, 64), ("max_sequence_length", 128, 32768)):
            value = getattr(self, key)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("SFT_PARAMETER_INVALID:" + key)
        if (type(self.seed) is not int or type(self.learning_rate) not in (int, float)
                or not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= 0.01
                or type(self.lora_dropout) not in (int, float) or not 0 <= self.lora_dropout < 1
                or self.compute_dtype not in ("bfloat16", "float16")
                or type(self.max_cuda_memory_fraction) not in (int, float) or not 0.25 <= self.max_cuda_memory_fraction <= 0.95
                or type(self.max_wall_seconds) is not int or not 1 <= self.max_wall_seconds <= 7200):
            raise ValueError("SFT_PARAMETERS_INVALID")
        if self.attention_backend not in ("sdpa", "patch_sft_repeat_kv_efficient_v1"):
            raise ValueError("SFT_ATTENTION_BACKEND_INVALID")


def repeat_kv_efficient_attention(module, query, key, value, attention_mask, dropout=0.0,
                                  scaling=None, is_causal=None, position_bias=None, **kwargs):
    """Equivalent dense GQA via native efficient SDPA, with no math fallback.

    This selected training backend covers full-sequence, dropout-free Qwen3
    attention. It is registered under its own name, never replacing HF `sdpa`.
    """
    import torch.nn.functional as functional
    from torch.nn.attention import SDPBackend, sdpa_kernel
    from transformers.integrations.sdpa_attention import repeat_kv
    if dropout != 0 or position_bias is not None or kwargs.get("output_attentions"):
        raise ValueError("SFT_EFFICIENT_BACKEND_UNSUPPORTED_ATTENTION_OPTIONS")
    if query.shape[1] % key.shape[1] or key.shape[1] != value.shape[1]:
        raise ValueError("SFT_EFFICIENT_BACKEND_HEAD_SHAPE_INVALID")
    groups = query.shape[1] // key.shape[1]
    if groups > 1:
        key, value = repeat_kv(key, groups), repeat_kv(value, groups)
    causal = getattr(module, "is_causal", True) if is_causal is None else is_causal
    causal = bool(query.shape[2] > 1 and attention_mask is None and causal)
    with sdpa_kernel([SDPBackend.EFFICIENT_ATTENTION]):
        output = functional.scaled_dot_product_attention(query, key, value, attn_mask=attention_mask,
            dropout_p=0.0, is_causal=causal, scale=scaling, enable_gqa=False)
    return output.transpose(1, 2).contiguous(), None


def register_training_attention(parameters):
    if parameters.attention_backend == "patch_sft_repeat_kv_efficient_v1":
        from transformers import AttentionInterface, AttentionMaskInterface
        AttentionInterface.register(parameters.attention_backend, repeat_kv_efficient_attention)
        AttentionMaskInterface.register(parameters.attention_backend, AttentionMaskInterface()["sdpa"])
    return parameters.attention_backend


def tokenize_completion(example, tokenizer, *, max_sequence_length):
    """Mask the complete prompt, including every earlier assistant/tool message."""
    prompt, completion = example.get("prompt"), example.get("completion")
    if (not isinstance(prompt, list) or not prompt or not isinstance(completion, list) or len(completion) != 1
            or completion[0].get("role") != "assistant" or not isinstance(completion[0].get("content"), str)
            or not completion[0]["content"] or example.get("loss_contract", {}).get("completion_only_loss") is not True):
        raise ValueError("SFT_COMPLETION_ONLY_EXAMPLE_REQUIRED")
    if any(not isinstance(row, dict) or row.get("role") not in ("system", "user", "assistant", "tool") for row in prompt):
        raise ValueError("SFT_PROMPT_MESSAGES_INVALID")
    tools = example.get("tools", [])
    prefix = tokenizer.apply_chat_template(prompt, tools=tools, tokenize=False,
        add_generation_prompt=True, enable_thinking=False)
    full = tokenizer.apply_chat_template(prompt + completion, tools=tools, tokenize=False,
        add_generation_prompt=False, enable_thinking=False)
    if not full.startswith(prefix):
        raise ValueError("SFT_CHAT_TEMPLATE_PREFIX_NOT_EXACT")
    prompt_ids = tokenizer(prefix, add_special_tokens=False)["input_ids"]
    input_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if not prompt_ids or input_ids[:len(prompt_ids)] != prompt_ids:
        raise ValueError("SFT_TOKEN_BOUNDARY_NOT_EXACT")
    if len(input_ids) > max_sequence_length:
        raise ValueError("SFT_SEQUENCE_TOO_LONG_NO_TRUNCATION")
    if len(input_ids) <= len(prompt_ids):
        raise ValueError("SFT_EMPTY_COMPLETION_LABELS")
    labels = [-100] * len(prompt_ids) + input_ids[len(prompt_ids):]
    if not all(value == -100 for value in labels[:len(prompt_ids)]):
        raise ValueError("SFT_PROMPT_LABEL_LEAK")
    if labels[len(prompt_ids):] != input_ids[len(prompt_ids):]:
        raise ValueError("SFT_COMPLETION_LABELS_CHANGED")
    evidence = {"sample_id": example["sample_id"], "prompt_tokens": len(prompt_ids),
        "completion_tokens": len(input_ids) - len(prompt_ids), "total_tokens": len(input_ids),
        "input_ids_sha256": sha(canonical(input_ids)), "labels_sha256": sha(canonical(labels)),
        "prompt_json_sha256": sha(canonical(prompt)), "completion_json_sha256": sha(canonical(completion)),
        "tools_sha256": sha(canonical(tools)), "prompt_all_masked": True, "completion_only": True,
        "text_prefix_exact": True, "token_prefix_exact": True, "input_truncated": False,
        "supervised_eos_present": tokenizer.eos_token_id in labels[len(prompt_ids):]}
    return {"input_ids": input_ids, "attention_mask": [1] * len(input_ids), "labels": labels}, evidence


class CompletionOnlyCollator:
    """Microbatch one keeps the unmodified full token sequence and exact labels."""
    def __call__(self, features):
        import torch
        if len(features) != 1:
            raise ValueError("SFT_MICROBATCH_MUST_BE_ONE")
        row = features[0]
        if not (len(row["input_ids"]) == len(row["attention_mask"]) == len(row["labels"])):
            raise ValueError("SFT_TOKEN_ARRAY_LENGTH_MISMATCH")
        return {key: torch.tensor([row[key]], dtype=torch.long) for key in ("input_ids", "attention_mask", "labels")}


def load_train_examples(config):
    """Open only train_data_ref, never validation/holdout paths or oracle files."""
    raw = read_exact(config["train_data_ref"])
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    expected = config["train_sample_ids"]
    if (not isinstance(expected, list) or not expected or len(expected) != len(set(expected))
            or len(rows) != len(expected) or {row.get("sample_id") for row in rows} != set(expected)):
        raise ValueError("SFT_TRAIN_SAMPLE_SET_MISMATCH")
    if any(row.get("split", "train") != "train" for row in rows):
        raise ValueError("SFT_NON_TRAIN_SAMPLE_FORBIDDEN")
    return rows


def _base_identity(config, *, require_weights):
    base = config["base"]
    directory = Path(base["directory"]).resolve(strict=True)
    if not directory.is_dir() or not base.get("model_id") or not base.get("revision"):
        raise ValueError("SFT_EXPLICIT_LOCAL_BASE_REQUIRED")
    refs = base["file_refs"]
    if not isinstance(refs, list) or not refs:
        raise ValueError("SFT_BASE_FILE_IDENTITIES_REQUIRED")
    names = set()
    for ref in refs:
        selected = Path(ref["path"]).resolve(strict=True)
        if not selected.is_relative_to(directory):
            raise ValueError("SFT_BASE_REFERENCE_OUTSIDE_SNAPSHOT")
        if set(ref) != {"path", "sha256"} or file_ref(selected)["sha256"] != ref["sha256"]:
            raise ValueError("SFT_INPUT_BYTES_CHANGED")
        names.add(selected.name)
    if not {"config.json", "tokenizer_config.json", "tokenizer.json"} <= names:
        raise ValueError("SFT_TOKENIZER_CONFIG_IDENTITIES_MISSING")
    if require_weights:
        weight_names = {path.name for path in directory.glob("*.safetensors")}
        if not weight_names or not weight_names <= names:
            raise ValueError("SFT_COMPLETE_WEIGHT_IDENTITIES_REQUIRED")
        index = directory / "model.safetensors.index.json"
        if index.exists() and (index.name not in names or not set(json.loads(index.read_text())['weight_map'].values()) <= weight_names):
            raise ValueError("SFT_WEIGHT_SHARDS_INCOMPLETE")
    return {"model_id": base["model_id"], "revision": base["revision"], "directory": str(directory),
        "file_refs": refs, "weights_required_and_checked": require_weights}


def _tokenizer(config):
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(config["base"]["directory"], local_files_only=True, trust_remote_code=False)


def _versions():
    return {name: importlib.metadata.version(name) for name in
        ("torch", "transformers", "peft", "trl", "accelerate", "datasets", "bitsandbytes", "safetensors")}


def _gpu_model(config, parameters):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig
    if not torch.cuda.is_available():
        raise ValueError("SFT_CUDA_REQUIRED")
    torch.cuda.set_per_process_memory_fraction(parameters.max_cuda_memory_fraction)
    if parameters.compute_dtype == "bfloat16" and not torch.cuda.is_bf16_supported():
        raise ValueError("SFT_BFLOAT16_DEVICE_SUPPORT_REQUIRED")
    dtype = torch.bfloat16 if parameters.compute_dtype == "bfloat16" else torch.float16
    attention = register_training_attention(parameters)
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(config["base"]["directory"], local_files_only=True,
        trust_remote_code=False, dtype=dtype, quantization_config=quantization, device_map={"": 0}, attn_implementation=attention)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False})
    targets = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    found = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    if not set(targets) <= found:
        raise ValueError("SFT_SELECTED_LORA_TARGETS_UNAVAILABLE")
    lora = LoraConfig(task_type="CAUSAL_LM", r=parameters.lora_rank, lora_alpha=parameters.lora_alpha,
        lora_dropout=parameters.lora_dropout, target_modules=targets, bias="none",
        base_model_name_or_path=config["base"]["model_id"], revision=config["base"]["revision"])
    return get_peft_model(model, lora), quantization


def _tensor_state_hash(tensors):
    import torch
    digest = hashlib.sha256()
    for key, tensor in sorted(tensors.items()):
        cpu = tensor.detach().cpu().contiguous()
        digest.update(canonical({"name": key, "shape": list(cpu.shape), "dtype": str(cpu.dtype)}))
        digest.update(cpu.view(torch.uint8).numpy().tobytes())
    return digest.hexdigest(), len(tensors)


def _adapter_state_hash(model):
    from peft import get_peft_model_state_dict
    return _tensor_state_hash(get_peft_model_state_dict(model))


def compare_adapter_states(saved, loaded):
    """Exact value comparison; only FP16/BF16 to FP32 lossless upcast is allowed."""
    import torch
    if set(saved) != set(loaded):
        raise ValueError("SFT_ADAPTER_RELOAD_KEYS_DIFFER")
    transitions = {}
    exact_dtype = 0
    for key in sorted(saved):
        expected, observed = saved[key].detach().cpu(), loaded[key].detach().cpu()
        if expected.shape != observed.shape:
            raise ValueError("SFT_ADAPTER_RELOAD_SHAPE_DIFFERS")
        if not torch.isfinite(expected).all() or not torch.isfinite(observed).all():
            raise ValueError("SFT_ADAPTER_RELOAD_NONFINITE")
        if expected.dtype == observed.dtype:
            comparison = expected
            exact_dtype += 1
        elif expected.dtype in (torch.float16, torch.bfloat16) and observed.dtype == torch.float32:
            comparison = expected.float()
        else:
            raise ValueError("SFT_ADAPTER_RELOAD_UNSUPPORTED_DTYPE_CHANGE")
        if not torch.equal(observed, comparison):
            raise ValueError("SFT_ADAPTER_RELOAD_VALUES_DIFFER")
        transition = str(expected.dtype) + "->" + str(observed.dtype)
        transitions[transition] = transitions.get(transition, 0) + 1
    return {"comparison_basis": "same_keys_shapes_exact_values_allow_only_lossless_fp16_bf16_to_fp32",
        "all_values_exact": True, "tensor_count": len(saved), "exact_dtype_tensors": exact_dtype,
        "dtype_transitions": transitions, "byte_identity_equal": exact_dtype == len(saved),
        "saved_state_sha256": _tensor_state_hash(saved)[0], "loaded_state_sha256": _tensor_state_hash(loaded)[0]}


def verify_saved_adapter(model, adapter_directory):
    from peft import get_peft_model_state_dict
    from safetensors.torch import load_file
    path = Path(adapter_directory)/"adapter_model.safetensors"
    result = compare_adapter_states(load_file(str(path), device="cpu"), get_peft_model_state_dict(model))
    return {**result, "saved_adapter_file_ref": file_ref(path)}


def _training_args(parameters, output, *, probe):
    from trl import SFTConfig
    # Explicit labels plus TRL's installed chunked NLL preserve the full input;
    # only ignored-position vocabulary projections are omitted, not input tokens.
    return SFTConfig(output_dir=str(output/"checkpoints"), per_device_train_batch_size=1,
        gradient_accumulation_steps=1 if probe else parameters.gradient_accumulation_steps,
        num_train_epochs=1 if probe else parameters.epochs, max_steps=1 if probe else -1,
        learning_rate=parameters.learning_rate, lr_scheduler_type="constant", warmup_steps=0,
        optim="adamw_torch", weight_decay=0, max_grad_norm=1.0,
        bf16=parameters.compute_dtype == "bfloat16", fp16=parameters.compute_dtype == "float16",
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        use_cache=False, report_to="none", push_to_hub=False, seed=parameters.seed, data_seed=parameters.seed,
        logging_steps=1, logging_strategy="steps", logging_first_step=True, logging_nan_inf_filter=False,
        save_strategy="steps" if probe else "epoch", save_steps=1, save_total_limit=None, save_only_model=True,
        eval_strategy="no", load_best_model_at_end=False, dataloader_num_workers=0, dataloader_pin_memory=False,
        remove_unused_columns=False, max_length=None, packing=False, padding_free=False,
        completion_only_loss=True, assistant_only_loss=False, loss_type="chunked_nll",
        dataset_kwargs={"skip_prepare_dataset": True})


def _train(config, parameters, tokenized, output, *, probe):
    import torch
    from datasets import Dataset
    from transformers import TrainerCallback, set_seed
    from trl import SFTTrainer
    set_seed(parameters.seed)
    gpu_work_started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    model, quantization = _gpu_model(config, parameters)
    tokenizer = _tokenizer(config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    if not 0 < trainable < total:
        raise ValueError("SFT_ONLY_ADAPTER_PARAMETERS_MUST_TRAIN")

    class Ledger(TrainerCallback):
        def on_step_begin(self, args, state, control, **kwargs):
            if time.perf_counter() - gpu_work_started > parameters.max_wall_seconds:
                raise TimeoutError("SFT_WALL_BUDGET_EXCEEDED")

        def on_step_end(self, args, state, control, **kwargs):
            if time.perf_counter() - gpu_work_started > parameters.max_wall_seconds:
                raise TimeoutError("SFT_WALL_BUDGET_EXCEEDED")

        def on_log(self, args, state, control, logs=None, **kwargs):
            event = {"event": "trainer_log", "step": state.global_step, "epoch": state.epoch,
                "metrics": {key: value for key, value in (logs or {}).items() if type(value) in (int, float, bool)},
                "time_unix": time.time()}
            with (output/"training-ledger.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, allow_nan=False) + "\n")
                stream.flush()

    args = _training_args(parameters, output, probe=probe)
    save_once(output/"effective-sft-config.json", args.to_dict())
    trainer = SFTTrainer(model=model, args=args, train_dataset=Dataset.from_list(tokenized),
        processing_class=tokenizer, data_collator=CompletionOnlyCollator(), callbacks=[Ledger()])
    initial_hash, _ = _adapter_state_hash(model)  # After TRL's QLoRA BF16 cast; dtype setup is not an optimizer change.
    started = time.perf_counter()
    trained = trainer.train()
    adapter = output/"adapter"
    trainer.save_model(str(adapter))
    trainer.save_state()
    final_hash, tensors = _adapter_state_hash(model)
    if initial_hash == final_hash:
        raise ValueError("SFT_ADAPTER_WEIGHTS_DID_NOT_CHANGE")
    result = {"optimizer_steps": trainer.state.global_step, "training_seconds": time.perf_counter()-started,
        "train_loss": trained.training_loss, "trainable_parameters": trainable, "total_parameters": total,
        "initial_adapter_state_sha256": initial_hash, "final_adapter_state_sha256": final_hash,
        "adapter_initialization_stage": "after_trainer_dtype_setup_before_optimizer",
        "adapter_tensor_count": tensors, "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
        "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(), "adapter_path": str(adapter),
        "cuda_allocator_limit_bytes": int(torch.cuda.get_device_properties(0).total_memory * parameters.max_cuda_memory_fraction),
        "cuda_limit_scope": "pytorch_caching_allocator_other_driver_or_library_allocations_not_capped",
        "wall_limit_scope": "trainer_step_boundaries_external_process_watchdog_required_for_hard_total_deadline",
        "attention_backend": parameters.attention_backend,
        "attention_math_fallback_allowed": False if parameters.attention_backend == "patch_sft_repeat_kv_efficient_v1" else None,
        "checkpoint_paths": [str(path) for path in sorted((output/"checkpoints").glob("checkpoint-*"))]}
    result["saved_files_before_reload"] = [file_ref(path) for path in sorted(adapter.rglob("*")) if path.is_file()]
    save_once(output/"trained-before-reload.json", result)
    del trainer, model, trained
    gc.collect()
    torch.cuda.empty_cache()
    from peft import PeftModel
    from transformers import AutoModelForCausalLM
    dtype = torch.bfloat16 if parameters.compute_dtype == "bfloat16" else torch.float16
    base = AutoModelForCausalLM.from_pretrained(config["base"]["directory"], local_files_only=True,
        trust_remote_code=False, dtype=dtype, quantization_config=quantization, device_map={"": 0},
        attn_implementation=register_training_attention(parameters))
    reloaded = PeftModel.from_pretrained(base, str(adapter), local_files_only=True, is_trainable=False)
    comparison = verify_saved_adapter(reloaded, adapter)
    if comparison["saved_state_sha256"] != final_hash:
        raise ValueError("SFT_SAVED_ADAPTER_DIFFERS_FROM_TRAINED_STATE")
    result.update(reload_adapter_state_sha256=comparison["loaded_state_sha256"], adapter_reload_verified=True,
        adapter_reload_comparison=comparison,
        saved_files=[file_ref(path) for path in sorted(adapter.rglob("*")) if path.is_file()],
        reloaded_generation_performed=False, validation_selection_completed=False)
    del reloaded, base
    gc.collect()
    torch.cuda.empty_cache()
    return result


def run(config_path, *, mode="tokenize"):
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[key] = "1"
    config_ref = file_ref(config_path)
    config = json.loads(read_exact(config_ref))
    if config.get("source_script_ref") != file_ref(__file__):
        raise ValueError("SFT_SCRIPT_BYTES_CHANGED_OR_UNBOUND")
    if mode not in ("tokenize", "probe", "train"):
        raise ValueError("SFT_MODE_INVALID")
    parameters = SFTParameters(**config.get("parameters", {}))
    if config.get("dataset_manifest_ref") is not None:
        read_exact(config["dataset_manifest_ref"])  # Identity only; no held-out data file is opened.
    base_identity = _base_identity(config, require_weights=mode != "tokenize")
    output = Path(config["output_root"]).resolve()/mode
    if output.exists():
        raise ValueError("SFT_OUTPUT_ALREADY_EXISTS")
    output.mkdir(parents=True)
    try:
        tokenizer = _tokenizer(config)
        if mode == "probe":
            examples = [json.loads(read_exact(config["probe_sample_ref"]))]
            input_ref = config["probe_sample_ref"]
        else:
            examples = load_train_examples(config)
            input_ref = config["train_data_ref"]
        tokenized, evidence = [], []
        for example in examples:
            row, proof = tokenize_completion(example, tokenizer, max_sequence_length=parameters.max_sequence_length)
            tokenized.append(row)
            evidence.append(proof)
        with (output/"tokenized-inputs.jsonl").open("x", encoding="utf-8") as stream:
            for example, row in zip(examples, tokenized, strict=True):
                stream.write(json.dumps({"sample_id": example["sample_id"], **row})+"\n")
        mask_ref = save_once(output/"loss-mask-evidence.json", {"samples": evidence, "no_truncation": True,
            "all_prior_assistant_messages_masked": True, "only_completion_loss": True,
            "chat_template_sha256": sha(str(tokenizer.chat_template).encode())})
        receipt = {"mode": mode, "config_ref": config_ref, "base": base_identity, "parameters": asdict(parameters),
            "source_script_ref": file_ref(__file__), "dataset_ref": input_ref, "sample_ids": [row["sample_id"] for row in examples],
            "dataset_manifest_ref": config.get("dataset_manifest_ref"),
            "loss_mask_ref": mask_ref, "training_count": len(examples) if mode == "train" else 0,
            "validation_content_read": False, "holdout_content_read": False, "network_uploads": 0,
            "product_model_calls": 0, "DPO_performed": False, "package_versions": _versions()}
        if mode == "tokenize":
            receipt.update(status="token_mask_verified_gpu_not_started", training_performed=False)
        else:
            receipt.update(_train(config, parameters, tokenized, output, probe=mode == "probe"))
            receipt.update(status="resource_probe_passed" if mode == "probe" else "trained_awaiting_validation_selection",
                training_performed=True, resource_probe_is_training_set=False,
                validation_policy="Choose using separately executed validation task results; no train-loss model selection or holdout access.")
        save_once(output/"result.json", receipt)
        return receipt
    except Exception as exc:
        save_once(output/"failure.json", {"status": "failed_no_automatic_retry", "mode": mode,
            "config_ref": config_ref, "exception_type": type(exc).__name__, "message": str(exc)[:1500],
            "holdout_content_read": False})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=("tokenize", "probe", "train"), default="tokenize")
    args = parser.parse_args(argv)
    result = run(args.config, mode=args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    main()
