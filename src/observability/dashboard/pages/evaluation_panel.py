"""Evaluation Panel page – run evaluations and view metrics.

Layout:
1. Configuration section: select evaluator backend, golden test set, top_k
2. Run button with progress indicator
3. Results section: aggregate metrics, per-query detail table
4. Optional: historical evaluation results comparison
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

logger = logging.getLogger(__name__)

# Default golden test set location
DEFAULT_GOLDEN_SET = Path("tests/fixtures/golden_test_set.json")
# Evaluation results history file
EVAL_HISTORY_PATH = Path("logs/eval_history.jsonl")


def render() -> None:
    """Render the Evaluation Panel page."""
    st.header("📏 Evaluation Panel")
    st.markdown(
        "Run evaluation against a **golden test set** to measure retrieval "
        "and generation quality. Results include per-query details and "
        "aggregate metrics."
    )

    # ── Configuration Section ──────────────────────────────────────
    st.subheader("⚙️ Configuration")

    col1, col2, col3 = st.columns(3)

    with col1:
        backend = st.selectbox(
            "Evaluator Backend",
            options=["custom", "ragas", "composite"],
            index=0,
            key="eval_backend",
            help="Select which evaluator backend to use.",
        )

    # Show info/warning based on selected backend
    if backend in ("custom", "composite"):
        st.info(
            "ℹ️ **Custom Evaluator** 尚未完成数据集准备，当前仅为预留接口。"
            "Custom Evaluator 需要在 Golden Test Set 中填写 `expected_chunk_ids` "
            "作为 ground truth 才能计算 hit_rate / MRR 指标。"
            "目前建议使用 **ragas** 后端进行评估。",
            icon="🚧",
        )

    with col2:
        top_k = st.number_input(
            "Top-K",
            min_value=1,
            max_value=50,
            value=10,
            key="eval_top_k",
            help="Number of chunks to retrieve per query.",
        )

    with col3:
        collection = st.text_input(
            "Collection (optional)",
            value="",
            key="eval_collection",
            help="Limit retrieval to a specific collection.",
        )

    # Golden test set file selection
    golden_path_str = st.text_input(
        "Golden Test Set Path",
        value=str(DEFAULT_GOLDEN_SET),
        key="eval_golden_path",
        help="Path to the golden_test_set.json file.",
    )
    golden_path = Path(golden_path_str)
    settings_path = st.text_input(
        "Retrieval and Answer Settings Path (optional)", key="eval_settings_path",
        help="Explicit settings YAML; blank uses the application default.",
    ).strip()
    judge_settings_path = st.text_input(
        "Judge Settings Path (optional)", key="eval_judge_settings_path",
        help="Separate evaluator model and embedding settings; blank reuses retrieval settings.",
    ).strip()

    # Validate golden set exists
    if not golden_path.exists():
        st.warning(
            f"⚠️ **Golden test set not found:** `{golden_path}`. "
            "Create a JSON file with test queries and expected results. "
            "See `tests/fixtures/golden_test_set.json` for the format."
        )

    # ── Answer provenance ──────────────────────────────────────────
    user_answers: Dict[int, str] = {}
    answer_mode = "none"
    if backend in ("ragas", "composite") and golden_path.exists():
        st.divider()
        st.subheader("回答来源")
        answer_mode = st.radio(
            "Answer source", options=["manual", "generated", "none"], key="eval_answer_mode",
            format_func=lambda value: {"manual": "手填实际系统答案", "generated": "使用配置中的模型生成",
                                       "none": "不提供答案（只测可用的检索指标）"}[value],
        )
        st.caption(
            "模型生成使用当前 llm 配置，输入为问题与本次检索上下文。"
            "手填项必须是实际系统答案；参考答案单独展示，不会自动充当系统答案或送入生成器。"
            "未提供答案的用例不计算答案质量指标。"
        )
        try:
            _test_cases = _load_golden_queries(golden_path)
            dataset_identity = hashlib.sha256(golden_path.read_bytes()).hexdigest()[:16]
            for tc_idx, tc in enumerate(_test_cases):
                q_preview = tc["query"][:60] + ("…" if len(tc["query"]) > 60 else "")
                if answer_mode == "manual":
                    user_ans = st.text_area(
                        f"Q{tc_idx + 1}: {q_preview}", value="", height=80,
                        key=f"eval_actual_answer_{dataset_identity}_{tc_idx}",
                        placeholder="请输入该问题对应的实际系统回答…",
                        help=f"Query: {tc['query']}\n填写实际输出，不填写期望答案。",
                    )
                    if user_ans.strip():
                        user_answers[tc_idx] = user_ans
                if tc.get("reference_answer") is not None:
                    with st.expander(f"Q{tc_idx + 1} 参考答案（非系统输出）"):
                        st.text(tc["reference_answer"])
            if answer_mode == "manual" and len(user_answers) < len(_test_cases):
                st.warning(f"已填写 {len(user_answers)}/{len(_test_cases)} 个实际答案。缺失项保持未测量。")
        except Exception as exc:
            st.warning(f"无法加载测试用例预览: {exc}")

    # ── Run Evaluation ─────────────────────────────────────────────
    st.divider()
    stop_on_failure = st.checkbox("Stop calls after the first failed case", value=True,
                                  key="eval_stop_on_failure")

    run_clicked = st.button(
        "▶️  Run Evaluation",
        type="primary",
        key="eval_run_btn",
        disabled=not golden_path.exists(),
    )

    if run_clicked:
        _run_evaluation(
            backend=backend,
            golden_path=golden_path,
            top_k=int(top_k),
            collection=collection.strip() or None,
            user_answers=user_answers if user_answers else None,
            answer_mode=answer_mode,
            settings_path=Path(settings_path) if settings_path else None,
            judge_settings_path=Path(judge_settings_path) if judge_settings_path else None,
            stop_on_failure=stop_on_failure,
        )

    st.divider()
    st.subheader("Review a saved CLI report")
    report_path = st.text_input("Saved Evaluation Report Path", key="eval_report_path")
    if st.button("View Report", key="eval_view_report", disabled=not report_path.strip()):
        try:
            saved_report = json.loads(Path(report_path.strip()).read_text(encoding="utf-8"))
            if not isinstance(saved_report, dict) or not isinstance(saved_report.get("query_results"), list):
                raise ValueError("Expected an evaluation report with query_results.")
            st.info("显示已保存的运行结果；本次查看没有重新检索、生成或评分。")
            _render_aggregate_metrics(saved_report)
            _render_query_details(saved_report)
        except (OSError, ValueError, TypeError) as exc:
            st.error(f"无法读取评测报告: {exc}")

    # ── Historical Results ─────────────────────────────────────────
    st.divider()
    _render_history()


def _run_evaluation(
    backend: str,
    golden_path: Path,
    top_k: int,
    collection: Optional[str],
    user_answers: Optional[Dict[int, str]] = None,
    answer_mode: str = "manual",
    settings_path: Path | None = None,
    judge_settings_path: Path | None = None,
    stop_on_failure: bool = False,
) -> None:
    """Execute an evaluation run and display results.

    Attempts to load the evaluator, run the golden test set, and
    display aggregate + per-query metrics.  Falls back to a graceful
    error message on failure.
    """
    with st.spinner("Loading evaluator and running evaluation…"):
        try:
            report_dict = _execute_evaluation(
                backend=backend,
                golden_path=golden_path,
                top_k=top_k,
                collection=collection,
                user_answers=user_answers,
                answer_mode=answer_mode,
                settings_path=settings_path,
                judge_settings_path=judge_settings_path,
                stop_on_failure=stop_on_failure,
            )
        except Exception as exc:
            st.error(f"❌ Evaluation failed: {exc}")
            logger.exception("Evaluation failed")
            return

    # ── Display results ────────────────────────────────────────────
    if report_dict["measurement_status"] == "complete":
        st.success("测量完成。分数表示评测结果，不代表所有回答正确。")
    else:
        st.warning(f"测量状态：{report_dict['measurement_status']}。请检查缺失项、失败原因与实际分母。")

    _render_aggregate_metrics(report_dict)
    _render_query_details(report_dict)

    # Save to history
    _save_to_history(report_dict)


def _execute_evaluation(
    backend: str,
    golden_path: Path,
    top_k: int,
    collection: Optional[str],
    user_answers: Optional[Dict[int, str]] = None,
    answer_mode: str = "manual",
    settings_path: Path | None = None,
    judge_settings_path: Path | None = None,
    stop_on_failure: bool = False,
) -> Dict[str, Any]:
    """Run the evaluation pipeline and return the report dict.

    This function imports heavy dependencies lazily to keep the
    dashboard responsive when the page is not used.
    """
    from dataclasses import replace as dc_replace

    from src.core.settings import load_settings
    from src.libs.evaluator.evaluator_factory import EvaluatorFactory
    from src.observability.evaluation.answer_generation import (
        LLMAnswerGenerator,
        evaluation_run_metadata,
    )
    from src.observability.evaluation.eval_runner import EvalRunner

    if answer_mode not in ("manual", "generated", "none"):
        raise ValueError("Unknown answer source.")
    if user_answers and answer_mode != "manual":
        raise ValueError("Actual answer overrides require manual mode.")

    settings = load_settings(settings_path) if settings_path is not None else load_settings()
    judge_settings = load_settings(judge_settings_path) if judge_settings_path is not None else settings

    # The UI's composite option explicitly means these two existing backends.
    # EvaluationSettings has no backends field; use the original constructor's
    # explicit composition seam and keep each child's supported metric names.
    from src.libs.evaluator.custom_evaluator import CustomEvaluator
    from src.observability.evaluation.ragas_evaluator import SUPPORTED_METRICS

    def selected_settings(provider, supported):
        metrics = [metric for metric in judge_settings.evaluation.metrics if metric in supported]
        return dc_replace(judge_settings, evaluation=dc_replace(
            judge_settings.evaluation, enabled=True, provider=provider, metrics=metrics))

    custom_settings = selected_settings("custom", CustomEvaluator.SUPPORTED_METRICS)
    ragas_settings = selected_settings("ragas", SUPPORTED_METRICS)
    if backend == "composite":
        evaluator = EvaluatorFactory.create(
            dc_replace(judge_settings, evaluation=dc_replace(judge_settings.evaluation, enabled=True, provider=backend)),
            evaluators=[EvaluatorFactory.create(custom_settings), EvaluatorFactory.create(ragas_settings)],
        )
    else:
        evaluator = EvaluatorFactory.create(ragas_settings if backend == "ragas" else custom_settings)

    # A public evaluation needs an initialized retriever; do not silently
    # replace an initialization failure with an empty context evaluation.
    target_collection = collection or "default"
    hybrid_search = _try_create_hybrid_search(settings, target_collection)
    if hybrid_search is None:
        raise RuntimeError("检索初始化失败；本次未生成答案或执行评分。请检查索引与检索配置。")

    # Create reranker if enabled
    reranker = None
    try:
        from src.core.query_engine.reranker import create_core_reranker
        reranker = create_core_reranker(settings=settings)
        if not reranker.is_enabled:
            reranker = None
    except Exception as exc:
        logger.warning("Could not create reranker: %s", exc)

    # Build answer_override map: index → user-provided answer text
    # EvalRunner preserves the explicitly selected answer source.
    runner = EvalRunner(
        settings=settings,
        hybrid_search=hybrid_search,
        evaluator=evaluator,
        answer_overrides=user_answers,
        answer_generator=LLMAnswerGenerator(settings) if answer_mode == "generated" else None,
        synthetic_fallback=False,
        reranker=reranker,
    )

    report = runner.run(
        test_set_path=golden_path,
        top_k=top_k,
        collection=collection,
        stop_on_failure=stop_on_failure,
        run_metadata=evaluation_run_metadata(
            settings, judge_settings, test_set_path=golden_path, collection=collection,
            top_k=top_k, answer_mode=answer_mode,
            settings_path=settings_path, judge_settings_path=judge_settings_path,
        ),
    )

    return report.to_dict()


def _try_create_hybrid_search(settings: Any, collection: str = "default") -> Any:
    """Attempt to create a HybridSearch instance.

    Returns None if required dependencies are not available
    (e.g., no indexed data).
    """
    try:
        from src.core.query_engine.dense_retriever import create_dense_retriever
        from src.core.query_engine.hybrid_search import create_hybrid_search
        from src.core.query_engine.query_processor import QueryProcessor
        from src.core.query_engine.sparse_retriever import create_sparse_retriever
        from src.ingestion.storage.bm25_indexer import BM25Indexer
        from src.libs.embedding.embedding_factory import EmbeddingFactory
        from src.libs.vector_store.vector_store_factory import VectorStoreFactory

        vector_store = VectorStoreFactory.create(
            settings, collection_name=collection,
        )
        embedding_client = EmbeddingFactory.create(settings)
        dense_retriever = create_dense_retriever(
            settings=settings,
            embedding_client=embedding_client,
            vector_store=vector_store,
        )
        bm25_indexer = BM25Indexer(index_dir=f"data/db/bm25/{collection}")
        sparse_retriever = create_sparse_retriever(
            settings=settings,
            bm25_indexer=bm25_indexer,
            vector_store=vector_store,
        )
        sparse_retriever.default_collection = collection

        query_processor = QueryProcessor()
        return create_hybrid_search(
            settings=settings,
            query_processor=query_processor,
            dense_retriever=dense_retriever,
            sparse_retriever=sparse_retriever,
        )
    except Exception as exc:
        logger.warning("Could not create HybridSearch: %s", exc)
        return None


def _render_aggregate_metrics(report: Dict[str, Any]) -> None:
    """Display aggregate metrics as metric cards."""
    st.subheader("📊 Aggregate Metrics")
    if report.get("run_metadata"):
        with st.expander("Run identity and configuration"):
            st.json(report["run_metadata"])

    agg = report.get("aggregate_metrics", {})

    if not agg:
        st.info("No aggregate metrics available.")
    else:
        cols = st.columns(min(len(agg), 4))
        for idx, (name, value) in enumerate(sorted(agg.items())):
            with cols[idx % len(cols)]:
                st.metric(label=name.replace("_", " ").title(), value=f"{value:.4f}")

    counts = report.get("metric_measurements", {})
    if counts:
        st.dataframe([{"metric": metric, **values} for metric, values in sorted(counts.items())],
                     use_container_width=True)
        st.caption("均值仅使用 observed/scored 项；total 是全部用例，failed_to_measure 与 not_applicable 不计为零分。")

    st.caption(
        f"Evaluator: **{report.get('evaluator_name', '—')}** · "
        f"Measurement: **{report.get('measurement_status', 'unknown')}** · "
        f"Queries: **{report.get('query_count', 0)}** · "
        f"Total time: **{report.get('total_elapsed_ms', 0):.0f} ms**"
    )


def _render_query_details(report: Dict[str, Any]) -> None:
    """Display per-query evaluation results in an expandable table."""
    st.subheader("🔍 Per-Query Details")

    query_results = report.get("query_results", [])
    if not query_results:
        st.info("No per-query results available.")
        return

    for idx, qr in enumerate(query_results):
        query = qr.get("query", "—")
        elapsed = qr.get("elapsed_ms", 0)
        metrics = qr.get("metrics", {})

        # Build metric summary for the expander label
        metric_summary = " · ".join(
            f"{k}: {v:.3f}" for k, v in sorted(metrics.items())
        )
        if not metric_summary:
            metric_summary = "no metrics"

        with st.expander(
            f"**Q{idx + 1}**: {query[:80]} — {elapsed:.0f} ms — {metric_summary}",
            expanded=False,
        ):
            st.json({key: qr.get(key) for key in ("retrieval_measurement", "answer_measurement",
                                                 "evaluator_measurement", "metric_measurements")})
            # Metrics
            if metrics:
                mcols = st.columns(min(len(metrics), 4))
                for midx, (mname, mval) in enumerate(sorted(metrics.items())):
                    with mcols[midx % len(mcols)]:
                        st.metric(mname, f"{mval:.4f}")

            # Retrieved chunks
            chunks = qr.get("retrieved_chunk_ids", [])
            if chunks:
                st.markdown(f"**Retrieved Chunks** ({len(chunks)}):")
                st.code(", ".join(chunks[:20]), language=None)
            for context in qr.get("retrieved_contexts", []):
                st.json(context)

            # Generated answer
            answer = qr.get("generated_answer")
            if answer:
                mode = (qr.get("answer_measurement") or {}).get("mode")
                st.markdown("**用户提供的实际答案：**" if mode == "answer_override" else "**模型生成答案：**")
                st.text(answer)
            if qr.get("reference_answer") is not None:
                st.markdown("**参考答案（非系统输出）：**")
                st.text(qr["reference_answer"])


def _render_history() -> None:
    """Display historical evaluation results for comparison."""
    st.subheader("📈 Evaluation History")

    history = _load_history()
    if not history:
        st.info(
            "**No evaluation history yet.** "
            "Configure the evaluator above and click \"Run Evaluation\" to start. "
            "Results will be saved here for comparison across runs."
        )
        return

    # Show recent runs as a table
    rows = []
    for entry in history[-10:]:  # last 10 runs
        rows.append(
            {
                "Timestamp": entry.get("timestamp", "—"),
                "Evaluator": entry.get("evaluator_name", "—"),
                "Queries": entry.get("query_count", 0),
                "Measurement": entry.get("measurement_status", "unknown"),
                "Time (ms)": round(entry.get("total_elapsed_ms", 0)),
                **{
                    k: round(v, 4)
                    for k, v in entry.get("aggregate_metrics", {}).items()
                },
                **{f"{k} observed/total": f"{v['observed']}/{v['total']}"
                   for k, v in entry.get("metric_measurements", {}).items()},
            }
        )

    st.dataframe(rows, use_container_width=True)


def _save_to_history(report: Dict[str, Any]) -> None:
    """Append an evaluation report to the history file."""
    try:
        EVAL_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            **report,
        }
        with EVAL_HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("Failed to save evaluation history: %s", exc)


def _load_history() -> List[Dict[str, Any]]:
    """Load evaluation history from JSONL file."""
    if not EVAL_HISTORY_PATH.exists():
        return []

    entries: List[Dict[str, Any]] = []
    try:
        with EVAL_HISTORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        logger.warning("Failed to load evaluation history: %s", exc)

    return entries


def _load_golden_queries(golden_path: Path) -> List[Dict[str, Any]]:
    """Load test cases from golden test set for display in the UI.

    Returns list of dicts with at least 'query' and optionally
    'reference_answer' keys.
    """
    with golden_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("test_cases", [])
