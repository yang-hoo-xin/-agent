#!/usr/bin/env python
"""Evaluation script for RepoForge.

Runs batch evaluation against a golden test set and outputs a metrics report.

Usage:
    # Run with default settings (custom evaluator)
    python scripts/evaluate.py

    # Specify a custom golden test set
    python scripts/evaluate.py --test-set path/to/golden.json

    # Use a specific collection
    python scripts/evaluate.py --collection technical_docs

    # JSON output
    python scripts/evaluate.py --json

    # Generate answers through the configured provider, then evaluate them
    python -m scripts.evaluate --settings path/to/evaluation.yaml --answer-mode generated --json

Exit codes:
    0 - Complete measurement (does not imply correct answers)
    1 - Failed, partial, or unavailable measurement
    2 - Configuration error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform == "win32" and __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run RAG evaluation against a golden test set."
    )
    parser.add_argument("--settings", type=Path, help="Explicit application settings YAML for this evaluation.")
    parser.add_argument("--judge-settings", type=Path,
                        help="Separate evaluator settings YAML; retrieval and generation keep --settings.")
    parser.add_argument("--output", type=Path, help="Save the same report as JSON for Dashboard review.")
    parser.add_argument("--stop-on-failure", action="store_true",
                        help="Stop calls after the first failed case; retain unattempted cases in the denominator.")
    parser.add_argument(
        "--test-set",
        default="tests/fixtures/golden_test_set.json",
        help="Path to golden test set JSON file (default: tests/fixtures/golden_test_set.json)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Collection name to search within.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of chunks to retrieve per query (default: 10).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of formatted text.",
    )
    parser.add_argument(
        "--no-search",
        action="store_true",
        help="Skip retrieval; retrieval-dependent metrics remain unmeasured.",
    )
    parser.add_argument("--answer-mode", choices=("generated", "manual", "none"), default="none",
                        help="Use the configured LLM, supplied actual answers, or retrieval-only evaluation.")
    parser.add_argument("--answers-file", type=Path,
                        help="For manual mode: JSON array aligned with test cases; null means missing.")
    args = parser.parse_args(argv)
    if (args.answer_mode == "manual") != (args.answers_file is not None):
        parser.error("--answers-file is required exactly when --answer-mode=manual.")
    return args


def main(argv=None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    try:
        from src.core.settings import load_settings
        from src.libs.evaluator.evaluator_factory import EvaluatorFactory
        from src.observability.evaluation.answer_generation import (
            LLMAnswerGenerator,
            evaluation_run_metadata,
            load_answer_overrides,
        )
        from src.observability.evaluation.eval_runner import EvalRunner, load_test_set

        settings = load_settings(args.settings) if args.settings is not None else load_settings()
        judge_settings = load_settings(args.judge_settings) if args.judge_settings is not None else settings
        answers = (load_answer_overrides(args.answers_file, len(load_test_set(args.test_set)))
                   if args.answers_file is not None else None)
    except Exception as exc:
        print(f"❌ Configuration error: {exc}", file=sys.stderr)
        return 2

    # Create evaluator from config
    try:
        evaluator = EvaluatorFactory.create(judge_settings)
        evaluator_name = type(evaluator).__name__
    except Exception as exc:
        print(f"❌ Failed to create evaluator: {exc}", file=sys.stderr)
        return 2

    # Create HybridSearch (unless --no-search)
    hybrid_search = None
    query_service = None
    if not args.no_search:
        try:
            collection = args.collection or "default"
            hybrid_search = _create_hybrid_search(settings, collection)
            from src.core.query_engine.service_factory import create_query_service
            query_service = create_query_service(settings, collection, hybrid_search=hybrid_search)
            print(f"✅ HybridSearch initialized for collection: {collection}", file=sys.stderr)
        except Exception as exc:
            print(f"❌ Failed to initialize search: {exc}", file=sys.stderr)
            return 2

    # Create and run EvalRunner
    runner = EvalRunner(
        settings=settings,
        hybrid_search=hybrid_search,
        evaluator=evaluator,
        answer_generator=LLMAnswerGenerator(settings) if args.answer_mode == "generated" else None,
        answer_overrides=answers,
        synthetic_fallback=False,
        query_service=query_service,
    )

    try:
        print(f"\n🔍 Running evaluation with {evaluator_name}...", file=sys.stderr)
        print(f"📄 Test set: {args.test_set}", file=sys.stderr)
        print(f"🔢 Top-K: {args.top_k}; answer mode: {args.answer_mode}\n", file=sys.stderr)

        report = runner.run(
            test_set_path=args.test_set,
            top_k=args.top_k,
            collection=args.collection,
            stop_on_failure=args.stop_on_failure,
            comparison_arm="rag_off" if args.no_search else "rag_on",
            run_metadata=evaluation_run_metadata(
                settings, judge_settings, test_set_path=args.test_set, collection=args.collection,
                top_k=args.top_k, answer_mode=args.answer_mode,
                settings_path=args.settings, judge_settings_path=args.judge_settings,
            ),
        )
    except Exception as exc:
        print(f"❌ Evaluation failed: {exc}", file=sys.stderr)
        return 1

    # Output results
    if args.output is not None:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            print(f"Failed to save evaluation report: {exc}", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_report(report)

    return 0 if report.measurement_status == "complete" else 1


def _create_hybrid_search(settings, collection):
    """Build the shared existing retrieval stack; initialization failures remain visible."""
    from src.core.query_engine.service_factory import create_retrieval_stack
    return create_retrieval_stack(settings, collection)


def _print_report(report) -> None:
    """Print formatted evaluation report."""
    print("=" * 60)
    print("  EVALUATION REPORT")
    print("=" * 60)
    print(f"  Evaluator: {report.evaluator_name}")
    print(f"  Test Set:  {report.test_set_path}")
    print(f"  Queries:   {len(report.query_results)}")
    print(f"  Time:      {report.total_elapsed_ms:.0f} ms")
    print(f"  Measurement: {report.measurement_status} (measurement completeness, not answer correctness)")
    print()

    # Aggregate metrics
    print("─" * 60)
    print("  AGGREGATE METRICS")
    print("─" * 60)
    if report.aggregate_metrics:
        for metric, value in sorted(report.aggregate_metrics.items()):
            bar = "█" * int(value * 20) + "░" * (20 - int(value * 20))
            print(f"  {metric:<25s} {bar} {value:.4f}")
    else:
        print("  (no metrics computed)")
    for metric, counts in sorted(report.metric_measurements.items()):
        print(f"  {metric}: observed {counts['observed']}/{counts['total']}; "
              f"failed_to_measure={counts['failed_to_measure']}; "
              f"not_applicable={counts['not_applicable']}")
    print()

    # Per-query details
    print("─" * 60)
    print("  PER-QUERY RESULTS")
    print("─" * 60)
    for i, qr in enumerate(report.query_results, 1):
        print(f"\n  [{i}] {qr.query}")
        print(f"      Retrieved: {len(qr.retrieved_chunk_ids)} chunks")
        for label, measurement in (("retrieval", qr.retrieval_measurement),
                                   ("answer", qr.answer_measurement),
                                   ("evaluator", qr.evaluator_measurement)):
            print(f"      {label}: {measurement.status} ({measurement.mode})")
            if measurement.error_category:
                print(f"        {measurement.error_category}: {measurement.error_message}")
        print(f"      Answer: {qr.generated_answer!r}")
        print(f"      Reference (separate, not generated): {qr.reference_answer!r}")
        for metric, status in sorted(qr.metric_measurements.items()):
            print(f"      {metric} measurement: {status}")
        if qr.metrics:
            for metric, value in sorted(qr.metrics.items()):
                print(f"      {metric}: {value:.4f}")
        else:
            print("      (no metrics)")
        print(f"      Time: {qr.elapsed_ms:.0f} ms")

    print()
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
