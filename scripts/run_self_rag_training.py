"""Train labelled Self-RAG generator targets with LoRA and reflection-token rows.

Default mode only tokenizes local data. GPU loading requires --mode probe/train.
为什么要有它：反思 token 的优化器更新、段落遮罩和重载必须单独验证，旧 Patch adapter 不是 Self-RAG。
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import time
from dataclasses import asdict
from pathlib import Path

from scripts import run_patch_sft_training as shared
from src.mod_agent.evaluation import reflection_tokens, self_rag_adapter


def _base(config, parameters, *, training):
    import torch
    from peft import prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise ValueError("SELF_RAG_CUDA_REQUIRED")
    torch.cuda.set_per_process_memory_fraction(parameters.max_cuda_memory_fraction)
    if parameters.compute_dtype == "bfloat16" and not torch.cuda.is_bf16_supported():
        raise ValueError("SELF_RAG_BFLOAT16_DEVICE_SUPPORT_REQUIRED")
    dtype = torch.bfloat16 if parameters.compute_dtype == "bfloat16" else torch.float16
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(config["base"]["directory"], local_files_only=True,
        trust_remote_code=False, dtype=dtype, quantization_config=quantization, device_map={"": 0},
        attn_implementation=shared.register_training_attention(parameters))
    model.config.use_cache = False
    return (prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False}) if training else model)


def _train(config, parameters, rows, tokenizer, token_ids, output, *, probe, base_identity):
    import torch
    from datasets import Dataset
    from transformers import TrainerCallback, set_seed
    from trl import SFTTrainer

    set_seed(parameters.seed)
    started = time.perf_counter()
    model = self_rag_adapter.attach_reflection_adapter(_base(config, parameters, training=True), token_ids,
        rank=parameters.lora_rank, alpha=parameters.lora_alpha, dropout=parameters.lora_dropout)
    args = shared._training_args(parameters, output, probe=probe)
    args.save_strategy = "no"  # The explicit final saver retains selected token rows, not full frozen embeddings.

    class BoundedLedger(TrainerCallback):
        def on_step_begin(self, args, state, control, **kwargs):
            if time.perf_counter() - started > parameters.max_wall_seconds:
                raise TimeoutError("SELF_RAG_WALL_BUDGET_EXCEEDED")

        def on_step_end(self, args, state, control, **kwargs):
            self.on_step_begin(args, state, control, **kwargs)

        def on_log(self, args, state, control, logs=None, **kwargs):
            with (output / "training-ledger.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"step": state.global_step, "epoch": state.epoch,
                    "metrics": {key: value for key, value in (logs or {}).items() if type(value) in (int, float, bool)}},
                    allow_nan=False) + "\n")

    trainer = SFTTrainer(model=model, args=args, train_dataset=Dataset.from_list(rows),
        processing_class=tokenizer, data_collator=shared.CompletionOnlyCollator(), callbacks=[BoundedLedger()])
    before = self_rag_adapter.reflection_row_state(model, token_ids, require_trainable=True)
    initial_adapter_hash = shared._adapter_state_hash(model)[0]
    shared.save_once(output / "effective-training-args.json", args.to_dict())
    trained = trainer.train()
    if trainer.state.global_step < 1 or not math.isfinite(trained.training_loss):
        raise ValueError("SELF_RAG_FINITE_OPTIMIZER_RESULT_REQUIRED")
    after = self_rag_adapter.reflection_row_state(model, token_ids, require_trainable=True)
    changed = self_rag_adapter.changed_reflection_families(before, after)
    final_hash = shared._adapter_state_hash(model)[0]
    adapter_path = output / "adapter"
    saved = self_rag_adapter.save_reflection_adapter(model, tokenizer, adapter_path,
        token_ids=token_ids, base_identity=base_identity)
    result = {"optimizer_steps": trainer.state.global_step, "training_seconds": time.perf_counter() - started,
        "training_loss": trained.training_loss, "initial_adapter_sha256": initial_adapter_hash,
        "final_adapter_sha256": final_hash, "changed_reflection_tokens_by_family": changed,
        "initial_reflection_rows_sha256": shared._tensor_state_hash(before)[0],
        "final_reflection_rows_sha256": shared._tensor_state_hash(after)[0], "saved_state_comparison": saved,
        "adapter_directory": str(adapter_path), "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
        "wall_budget_scope": "training_step_boundaries_not_a_process_watchdog"}
    shared.save_once(output / "trained-before-reload.json", result)
    del trainer, model, trained
    gc.collect()
    torch.cuda.empty_cache()
    reloaded, loaded_tokenizer, comparison = self_rag_adapter.load_reflection_adapter(
        _base(config, parameters, training=False), adapter_path, base_identity=base_identity)
    loaded_rows = self_rag_adapter.reflection_row_state(reloaded, token_ids)
    shared.compare_adapter_states(after, loaded_rows)
    if comparison["saved_state_sha256"] != final_hash:
        raise ValueError("SELF_RAG_SAVED_ADAPTER_DIFFERS_FROM_TRAINED_STATE")
    result.update(adapter_reload_verified=True, reflection_rows_reload_verified=True,
        token_ids_reload_verified=reflection_tokens.register_reflection_tokens(loaded_tokenizer) == token_ids,
        reload_comparison=comparison, reloaded_generation_performed=False)
    del reloaded
    gc.collect()
    torch.cuda.empty_cache()
    return result


def run(config_path, *, mode="tokenize"):
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[name] = "1"
    if mode not in ("tokenize", "probe", "train"):
        raise ValueError("SELF_RAG_MODE_INVALID")
    config_ref = shared.file_ref(config_path)
    config = json.loads(shared.read_exact(config_ref))
    owners = [__file__, reflection_tokens.__file__, self_rag_adapter.__file__, shared.__file__]
    if config.get("source_refs") != [shared.file_ref(path) for path in owners]:
        raise ValueError("SELF_RAG_TRAINING_SOURCES_CHANGED")
    parameters = shared.SFTParameters(**config.get("parameters", {}))
    base_identity = shared._base_identity(config, require_weights=mode != "tokenize")
    samples = shared.load_train_examples(config)
    output = Path(config["output_root"]).resolve() / mode
    output.mkdir(parents=True, exist_ok=False)
    try:
        tokenizer = shared._tokenizer(config)
        token_ids = reflection_tokens.register_reflection_tokens(tokenizer)
        rows, proofs = [], []
        for sample in samples:
            row, proof = reflection_tokens.tokenize_reflection_sample(sample, tokenizer,
                token_ids=token_ids, max_sequence_length=parameters.max_sequence_length)
            rows.append(row)
            proofs.append(proof)
        counts = {token: sum(proof["reflection_token_supervision"][token] for proof in proofs)
                  for token in reflection_tokens.ALL_TOKENS}
        if any(not any(counts[token] for token in family.values()) for family in reflection_tokens.REFLECTION_TOKENS.values()):
            raise ValueError("SELF_RAG_ALL_FOUR_FAMILIES_REQUIRE_SUPERVISION")
        mask_ref = shared.save_once(output / "loss-mask-evidence.json", {"samples": proofs,
            "reflection_token_counts": counts, "paragraph_bodies_masked": True, "no_truncation": True})
        receipt = {"mode": mode, "training_kind": "self_rag_generator_reflection_tokens",
            "config_ref": config_ref, "base": base_identity, "source_refs": config["source_refs"],
            "parameters": asdict(parameters), "train_data_ref": config["train_data_ref"],
            "sample_ids": config["train_sample_ids"], "token_ids": token_ids,
            "label_origins": sorted({sample["label_origin"] for sample in samples}),
            "loss_mask_ref": mask_ref, "package_versions": shared._versions(),
            "holdout_content_read": False, "critic_labels_generated": False,
            "retrieval_controller_implemented": False, "independent_quality_measured": False}
        if mode == "tokenize":
            receipt.update(training_performed=False, status="reflection_mask_verified_gpu_not_started")
        else:
            receipt.update(_train(config, parameters, rows, tokenizer, token_ids, output,
                                  probe=mode == "probe", base_identity=base_identity))
            receipt.update(training_performed=True, status="reflection_training_reloaded_pending_quality_evaluation")
        shared.save_once(output / "result.json", receipt)
        return receipt
    except Exception as error:
        shared.save_once(output / "failure.json", {"exception_type": type(error).__name__, "message": str(error),
            "status": "failed_without_retry", "mode": mode})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--mode", choices=("tokenize", "probe", "train"), default="tokenize")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.config, mode=args.mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
