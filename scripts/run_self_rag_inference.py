"""Prepare local Self-RAG inference; --execute explicitly loads the local GPU model.

为什么要有它：默认仅绑定配置和输入，单段实际推理与合成适配校准不能被描述为质量提升。
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace
from pathlib import Path

from scripts import run_patch_sft_training as shared
from src.mod_agent.evaluation import reflection_tokens, self_rag_adapter, self_rag_inference as inference


def projected_questions(path, *, input_kind, maximum):
    """Project only query and explicit calibration evidence; no answer/label input.

    为什么要有它：现有问题文件可带参考答案，生成输入必须只消费问题而不能泄漏判定材料。
    """
    raw = Path(path).read_text(encoding="utf-8")
    if input_kind == "test_set":
        from src.observability.evaluation.eval_runner import load_test_set
        cases = load_test_set(path)
        rows = [{"case_id": str(index), "question": row.query} for index, row in enumerate(cases)]
    elif input_kind == "synthetic_calibration":
        samples = [json.loads(line) for line in raw.splitlines() if line.strip()]
        rows = [{"case_id": row["sample_id"], "question": row["question"],
                 "calibration_contexts": [{"chunk_id": row["sample_id"] + "-evidence", "text": row["evidence"]}]
                    if row.get("evidence") else []} for row in samples]
    else:
        raise ValueError("SELF_RAG_INFERENCE_INPUT_KIND_INVALID")
    if not rows or len(rows) > maximum or len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("SELF_RAG_INFERENCE_QUESTION_BUDGET_INVALID")
    for row in rows:
        inference._text(row["question"])
    return rows


def run(args):
    if not 1 <= args.max_questions <= 20 or not 1 <= args.max_total_model_calls <= 60:
        raise ValueError("SELF_RAG_INFERENCE_BATCH_BUDGET_INVALID")
    if not 0 < args.max_total_seconds <= 7200:
        raise ValueError("SELF_RAG_INFERENCE_BATCH_TIME_INVALID")
    budget = inference.InferenceBudget(max_model_calls=args.max_model_calls, max_new_tokens=args.max_new_tokens,
        max_context_tokens=args.max_context_tokens, max_evidence_chars=args.max_evidence_chars,
        top_k=args.top_k, max_wall_seconds=args.max_wall_seconds)
    rows = projected_questions(args.questions, input_kind=args.input_kind, maximum=args.max_questions)
    if args.input_kind == "test_set" and not all((args.settings, args.collection, args.index_dir)):
        raise ValueError("SELF_RAG_EXPLICIT_EXISTING_BM25_CONFIGURATION_REQUIRED")
    config_ref, trained_ref = shared.file_ref(args.training_config), shared.file_ref(args.training_result)
    trained = json.loads(shared.read_exact(trained_ref))
    if not trained.get("training_performed") or not trained.get("adapter_reload_verified"):
        raise ValueError("SELF_RAG_TRAINED_ADAPTER_RECEIPT_REQUIRED")
    if trained.get("config_ref") != config_ref:
        raise ValueError("SELF_RAG_TRAINING_CONFIG_CHANGED")
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema_version": "self_rag_inference_plan_v1", "policy": args.policy,
        "training_config_ref": config_ref, "training_result_ref": trained_ref,
        "questions_ref": shared.file_ref(args.questions), "questions": rows, "input_kind": args.input_kind,
        "budget_per_question": asdict(budget), "max_total_model_calls": args.max_total_model_calls,
        "max_total_seconds": args.max_total_seconds, "label_origins": trained["label_origins"],
        "independent_quality_measured": False, "scope": "single_segment_greedy_not_paper_beam_search",
        "comparison_contract": "fixed/external_critic use unadapted training base; trained_tokens reloads its bound adapter",
        "sources": [shared.file_ref(path) for path in (__file__, inference.__file__, reflection_tokens.__file__, self_rag_adapter.__file__)],
        "retriever": {"origin": "existing_bm25_sparse_retriever" if args.input_kind == "test_set" else "supplied_synthetic_calibration_evidence",
            "settings_ref": shared.file_ref(args.settings) if args.settings else None,
            "collection": args.collection, "index_dir": args.index_dir,
            "index_ref": shared.file_ref(Path(args.index_dir) / (args.collection + "_bm25.json"))
                if args.input_kind == "test_set" else None}, "model_loaded": False}
    shared.save_once(root / "prepared.json", plan)
    if not args.execute:
        return {"status": "prepared_no_model_loaded", "prepared_ref": shared.file_ref(root / "prepared.json")}
    started = time.perf_counter()
    records, calls = [], 0
    try:
        decoder = inference.load_local_decoder(args.training_config, args.training_result, adapted=args.policy == "trained_tokens")
        load_seconds = time.perf_counter() - started
        retrieval = (inference.bm25_retriever(args.settings, collection=args.collection, index_dir=args.index_dir)
                     if args.input_kind == "test_set" else None)
        for index, row in enumerate(rows):
            seconds = args.max_total_seconds - (time.perf_counter() - started)
            if calls >= args.max_total_model_calls or seconds <= 0:
                result = {"status": "batch_budget_exhausted", "model_calls": 0, "answer": ""}
            else:
                retriever = retrieval or (lambda _query, k, selected=row: selected["calibration_contexts"][:k])
                result = inference.infer(row["question"], decoder=decoder, retriever=retriever, policy=args.policy,
                    critic=inference.existing_local_critic if args.policy == "external_critic" else None,
                    budget=replace(budget, max_model_calls=min(budget.max_model_calls, args.max_total_model_calls - calls),
                                   max_wall_seconds=min(budget.max_wall_seconds, seconds)))
                calls += result["model_calls"]
            result.update(case_id=row["case_id"], input_kind=args.input_kind, retriever_origin=plan["retriever"]["origin"])
            reference = shared.save_once(root / f"question-{index:03d}.json", result)
            records.append({"case_id": row["case_id"], "status": result["status"], "result_ref": reference})
        result = {"status": "observed_not_quality_scored", "prepared_ref": shared.file_ref(root / "prepared.json"),
            "records": records, "model_calls": calls, "model_load_seconds": load_seconds,
            "model_call_count_scope": "reserved_attempts_including_failed_or_unknown_transports",
            "elapsed_seconds": time.perf_counter() - started, "model_identity": decoder.identity,
            "independent_quality_measured": False, "training_performed": False,
            "time_budget_scope": "between_calls_and_generation_steps; loading_is_measured_not_interruptible"}
        shared.save_once(root / "result.json", result)
        return result
    except Exception as error:
        shared.save_once(root / "failure.json", {"status": "failed_without_retry", "type": type(error).__name__,
            "message": str(error), "model_calls_completed": calls, "elapsed_seconds": time.perf_counter() - started})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("training-config", "training-result", "questions", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--input-kind", choices=("test_set", "synthetic_calibration"), default="test_set")
    parser.add_argument("--policy", choices=("trained_tokens", "fixed_retrieval", "external_critic"), default="trained_tokens")
    parser.add_argument("--settings")
    parser.add_argument("--collection")
    parser.add_argument("--index-dir")
    parser.add_argument("--execute", action="store_true")
    for name, default in (("max-questions", 5), ("max-total-model-calls", 10), ("max-model-calls", 3),
                          ("max-new-tokens", 256), ("max-context-tokens", 4096), ("max-evidence-chars", 12000), ("top-k", 3)):
        parser.add_argument("--" + name, type=int, default=default)
    parser.add_argument("--max-wall-seconds", type=float, default=180)
    parser.add_argument("--max-total-seconds", type=float, default=600)
    args = parser.parse_args(argv)
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
