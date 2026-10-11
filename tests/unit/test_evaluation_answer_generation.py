"""Public evaluation entry checks with local data and intercepted provider HTTP."""

import json
import socket
from types import SimpleNamespace

import httpx
import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Evaluation checks must not connect to a real provider")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def golden(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps({"test_cases": [{
        "query": "How long is the cache retained?",
        "expected_chunk_ids": ["cache-policy"],
        "reference_answer": "REFERENCE_ONLY_DO_NOT_GENERATE",
    }]}), encoding="utf-8")
    return path


def render_panel():
    from src.observability.dashboard.pages.evaluation_panel import render

    render()


def test_manual_answer_is_not_prefilled_with_reference(monkeypatch, golden):
    from src.observability.dashboard.pages import evaluation_panel as panel

    monkeypatch.setattr(panel, "DEFAULT_GOLDEN_SET", golden)
    monkeypatch.setattr(panel, "_render_history", lambda: None)
    app = AppTest.from_function(render_panel).run()
    app.selectbox(key="eval_backend").select("ragas").run()
    assert not app.exception
    assert len(app.text_area) == 1
    assert app.text_area[0].value == ""


@pytest.mark.parametrize(("dense_enabled", "dense_provider", "expected_dense"), [
    (False, "disabled", False),
    (True, "vector_store", True),
])
def test_evaluation_entry_constructs_dense_retriever_only_for_vector_store_provider(
    monkeypatch, dense_enabled, dense_provider, expected_dense,
):
    from scripts import evaluate
    from src.core.query_engine import dense_retriever as dense_module
    from src.core.query_engine import hybrid_search as hybrid_module
    from src.core.query_engine import query_processor as query_module
    from src.core.query_engine import sparse_retriever as sparse_module
    from src.ingestion.storage import bm25_indexer as bm25_module
    from src.libs.embedding.embedding_factory import EmbeddingFactory
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory

    settings = SimpleNamespace(retrieval=SimpleNamespace(
        dense_enabled=dense_enabled,
        dense_provider=dense_provider,
    ))
    embeddings = []
    monkeypatch.setattr(VectorStoreFactory, "create", lambda *args, **kwargs: "store")
    monkeypatch.setattr(EmbeddingFactory, "create", lambda *args, **kwargs: embeddings.append("used") or "embedding")
    monkeypatch.setattr(dense_module, "create_dense_retriever", lambda **kwargs: ("dense", kwargs))
    sparse = SimpleNamespace(default_collection=None)
    monkeypatch.setattr(sparse_module, "create_sparse_retriever", lambda **kwargs: sparse)
    monkeypatch.setattr(hybrid_module, "create_hybrid_search", lambda **kwargs: kwargs)
    monkeypatch.setattr(query_module, "QueryProcessor", lambda: "processor")
    monkeypatch.setattr(bm25_module, "BM25Indexer", lambda index_dir: ("bm25", index_dir))

    result = evaluate._create_hybrid_search(settings, "collection")

    assert (result["dense_retriever"] is not None) is expected_dense
    assert embeddings == (["used"] if expected_dense else [])
    assert result["sparse_retriever"] is sparse
    assert sparse.default_collection == "collection"


@pytest.mark.parametrize(("dense_enabled", "dense_provider"), [
    (True, "disabled"),
    (False, "vector_store"),
])
def test_evaluation_entry_rejects_inconsistent_dense_provider(
    monkeypatch, dense_enabled, dense_provider,
):
    from scripts import evaluate
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory

    settings = SimpleNamespace(retrieval=SimpleNamespace(
        dense_enabled=dense_enabled,
        dense_provider=dense_provider,
    ))
    monkeypatch.setattr(VectorStoreFactory, "create", lambda *args, **kwargs: "store")

    with pytest.raises(ValueError, match="dense retrieval"):
        evaluate._create_hybrid_search(settings, "collection")


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """Real BM25/HybridSearch and Ollama adapter; only storage/HTTP/judge are doubles."""
    from scripts import evaluate
    from src.core import settings as settings_module
    from src.core.query_engine.hybrid_search import HybridSearchConfig, create_hybrid_search
    from src.core.query_engine.query_processor import QueryProcessor
    from src.core.query_engine.sparse_retriever import SparseRetriever
    from src.core.settings import (
        EmbeddingSettings,
        EvaluationSettings,
        LLMSettings,
        ObservabilitySettings,
        RerankSettings,
        RetrievalSettings,
        Settings,
        VectorStoreSettings,
    )
    from src.ingestion.storage.bm25_indexer import BM25Indexer
    from src.observability.dashboard.pages import evaluation_panel as panel
    from src.observability.evaluation import ragas_evaluator

    settings = Settings(
        llm=LLMSettings("ollama", "evaluation-test", 0.0, 128, base_url="http://127.0.0.1:11435"),
        embedding=EmbeddingSettings("unused", "unused", 3),
        vector_store=VectorStoreSettings("unused", str(tmp_path), "default"),
        retrieval=RetrievalSettings(1, 1, 1, 60),
        rerank=RerankSettings(False, "none", "unused", 1),
        evaluation=EvaluationSettings(True, "ragas", ["faithfulness"]),
        observability=ObservabilitySettings("WARNING", False, str(tmp_path / "trace"), False),
    )
    context = "The cache policy retains cache entries for exactly 37 minutes."
    index = BM25Indexer(index_dir=str(tmp_path / "bm25"))
    index.build([{"chunk_id": "cache-policy", "term_frequencies": {"cache": 2, "retained": 1},
                  "doc_length": 10}])
    fetched = []

    class Store:
        def get_by_ids(self, ids, trace=None):
            fetched.append(ids)
            assert ids == ["cache-policy"]
            return [{"id": "cache-policy", "text": context, "metadata": {}}]

    search = create_hybrid_search(
        settings=settings, query_processor=QueryProcessor(),
        sparse_retriever=SparseRetriever(bm25_indexer=index, vector_store=Store()),
        config=HybridSearchConfig(enable_dense=False, parallel_retrieval=False),
    )
    monkeypatch.setattr(settings_module, "load_settings", lambda: settings)
    monkeypatch.setattr(evaluate, "_create_hybrid_search", lambda *_: search)
    monkeypatch.setattr(panel, "_try_create_hybrid_search", lambda *_: search)
    monkeypatch.setattr(panel, "EVAL_HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(ragas_evaluator, "_import_ragas", lambda: None)
    state = SimpleNamespace(context=context, response="  Cache lives for 37 minutes.  ",
                            provider_error=False, judge_error=False, requests=[], judged=[],
                            fetched=fetched, search=search, settings=settings, panel=panel,
                            cli=evaluate)

    def transport(_transport, request):
        assert str(request.url) == "http://127.0.0.1:11435/api/chat"
        state.requests.append(json.loads(request.content))
        if state.provider_error:
            raise httpx.ReadTimeout("controlled provider timeout", request=request)
        return httpx.Response(200, request=request, json={
            "model": "evaluation-test", "message": {"role": "assistant", "content": state.response},
            "done": True, "prompt_eval_count": 15, "eval_count": 8,
        })

    def judge(_self, query, contexts, answer):
        state.judged.append({"query": query, "contexts": contexts, "answer": answer})
        if state.judge_error:
            raise RuntimeError("controlled judge failure")
        return {"faithfulness": 0.0}  # A genuine measured zero must still be complete.

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    monkeypatch.setattr(ragas_evaluator.RagasEvaluator, "_run_ragas", judge)
    return state


def assert_generation_lineage(state, report):
    assert state.fetched == [["cache-policy"]]
    assert len(state.requests) == len(state.judged) == 1
    request = state.requests[0]
    assert "[context:N]" in request["messages"][0]["content"]
    supplied = json.loads(request["messages"][1]["content"])
    assert supplied == {
        "query": "How long is the cache retained?",
        "contexts": [{
            "context_number": 1,
            "chunk_id": "cache-policy",
            "text": state.context,
        }],
    }
    assert "REFERENCE_ONLY_DO_NOT_GENERATE" not in json.dumps(request)
    assert state.judged[0] == {
        "query": supplied["query"],
        "contexts": [state.context],
        "answer": state.response,
    }
    query = report["query_results"][0]
    assert query["generated_answer"] == state.response
    assert query["reference_answer"] == "REFERENCE_ONLY_DO_NOT_GENERATE"
    assert query["answer_measurement"] == {
        "status": "observed", "mode": "answer_generator", "error_category": None, "error_message": None,
    }
    assert report["measurement_status"] == "complete"
    assert report["aggregate_metrics"] == {"faithfulness": 0.0}
    assert report["metric_measurements"]["faithfulness"]["observed"] == 1


def test_cli_generated_answer_reaches_judge_from_real_local_retrieval(pipeline, golden, capsys):
    assert pipeline.cli.main(["--test-set", str(golden), "--answer-mode", "generated", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert_generation_lineage(pipeline, report)


@pytest.mark.parametrize("outcome", ["answer", "empty", "timeout"])
def test_generated_report_retains_native_answer_cost_and_failed_attempt(pipeline, golden, capsys, outcome):
    pipeline.provider_error = outcome == "timeout"
    pipeline.response = "" if outcome == "empty" else "Observed answer"
    status = pipeline.cli.main([
        "--test-set", str(golden), "--answer-mode", "generated", "--json", "--stop-on-failure",
    ])
    report = json.loads(capsys.readouterr().out)
    row = report["query_results"][0]
    observation = row["answer_observation"]
    assert observation["invocation_id"]
    assert observation["elapsed_ms"] >= 0
    assert observation["started_at"] <= observation["finished_at"]
    assert observation["chat_invoked"] is True
    assert len(pipeline.requests) == 1
    assert status == (0 if outcome == "answer" else 1)
    if outcome == "timeout":
        assert observation["usage"] is None
        assert observation["raw_response"] is None
        assert observation["error"]["type"] == "OllamaLLMError"
        assert observation["chat_response_received"] is False
    else:
        assert observation["usage"]["prompt_tokens"] == 15
        assert observation["usage"]["completion_tokens"] == 8
        assert observation["response_model"] == "evaluation-test"
        assert observation["response_content"] == pipeline.response
        assert observation["raw_response"]["message"]["content"] == pipeline.response
        assert observation["chat_response_received"] is True
        assert observation["error"] is None


def test_cli_generated_rag_off_uses_same_generator_without_context_or_reference(
    pipeline, golden, capsys,
):
    status = pipeline.cli.main([
        "--test-set", str(golden), "--answer-mode", "generated", "--no-search", "--json",
    ])
    report = json.loads(capsys.readouterr().out)
    assert status == 1  # This fixture declares only faithfulness, which is N/A without context.
    assert report["comparison_arm"] == "rag_off"
    assert pipeline.fetched == []
    assert len(pipeline.requests) == 1
    assert "no retrieved evidence was supplied" in pipeline.requests[0]["messages"][0]["content"]
    supplied = json.loads(pipeline.requests[0]["messages"][1]["content"])
    assert supplied == {"query": "How long is the cache retained?", "contexts": []}
    assert "REFERENCE_ONLY_DO_NOT_GENERATE" not in json.dumps(pipeline.requests[0])
    result = report["query_results"][0]
    assert result["answer_measurement"]["status"] == "observed"
    assert result["retrieval_measurement"] == {
        "status": "not_applicable", "mode": "not_configured",
        "error_category": None, "error_message": None,
    }
    assert result["metric_measurements"]["faithfulness"] == "not_applicable"
    assert pipeline.judged == []


@pytest.mark.parametrize("entry", ["cli", "dashboard"])
def test_public_entry_separates_judge_settings(pipeline, monkeypatch, golden, tmp_path, capsys, entry):
    from dataclasses import replace

    from src.core import settings as settings_module
    from src.libs.evaluator.evaluator_factory import EvaluatorFactory

    answer_path, judge_path = tmp_path / "answer.yaml", tmp_path / "judge.yaml"
    answer_path.write_text("answer-config", encoding="utf-8")
    judge_path.write_text("judge-config", encoding="utf-8")
    judge_settings = replace(pipeline.settings, llm=replace(
        pipeline.settings.llm, model="separate-judge", api_key="NEVER_REPORT_THIS_KEY"))
    monkeypatch.setattr(settings_module, "load_settings", lambda path: {
        answer_path: pipeline.settings, judge_path: judge_settings,
    }[path])
    original_create = EvaluatorFactory.create
    used_settings = []

    def create(settings, **kwargs):
        used_settings.append(settings)
        return original_create(settings, **kwargs)

    monkeypatch.setattr(EvaluatorFactory, "create", create)
    output_path = tmp_path / "report.json"
    if entry == "cli":
        assert pipeline.cli.main([
            "--settings", str(answer_path), "--judge-settings", str(judge_path),
            "--test-set", str(golden), "--answer-mode", "generated", "--json",
            "--output", str(output_path),
        ]) == 0
        report = json.loads(capsys.readouterr().out)
        assert json.loads(output_path.read_text(encoding="utf-8")) == report
    else:
        monkeypatch.setattr(pipeline.panel, "DEFAULT_GOLDEN_SET", golden)
        app = AppTest.from_function(render_panel).run()
        app.selectbox(key="eval_backend").select("ragas").run()
        app.text_input(key="eval_settings_path").set_value(str(answer_path))
        app.text_input(key="eval_judge_settings_path").set_value(str(judge_path))
        app.radio(key="eval_answer_mode").set_value("generated").run()
        app.button(key="eval_run_btn").click().run()
        assert not app.exception
        report = pipeline.panel._load_history()[0]
    assert used_settings[0].llm.model == "separate-judge"
    assert_generation_lineage(pipeline, report)
    assert report["run_metadata"]["answer_model"]["model"] == "evaluation-test"
    assert report["run_metadata"]["judge_model"]["model"] == "separate-judge"
    assert report["run_metadata"]["judge_model"]["server_revision"] == "unknown"
    assert "NEVER_REPORT_THIS_KEY" not in json.dumps(report)
    assert report["run_metadata"]["test_set"]["sha256"]


def test_dashboard_reviews_same_cli_report_without_new_calls(pipeline, golden, tmp_path, capsys):
    output_path = tmp_path / "report.json"
    assert pipeline.cli.main([
        "--test-set", str(golden), "--answer-mode", "generated", "--json", "--output", str(output_path),
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    app = AppTest.from_function(render_panel).run()
    app.text_input(key="eval_report_path").set_value(str(output_path)).run()
    app.button(key="eval_view_report").click().run()
    assert not app.exception
    assert len(pipeline.requests) == len(pipeline.judged) == 1
    assert any(report["run_metadata"]["run_id"] in item.value for item in app.json)
    assert any(pipeline.context in item.value for item in app.json)
    assert any("没有重新检索" in item.value for item in app.info)


@pytest.mark.parametrize("provider_error", [True, False])
def test_cli_stop_on_failure_preserves_unattempted_denominator(pipeline, golden, capsys, provider_error):
    cases = json.loads(golden.read_text(encoding="utf-8"))
    cases["test_cases"].append(dict(cases["test_cases"][0]))
    golden.write_text(json.dumps(cases), encoding="utf-8")
    pipeline.provider_error = provider_error
    status = pipeline.cli.main([
        "--test-set", str(golden), "--answer-mode", "generated", "--stop-on-failure", "--json",
    ])
    report = json.loads(capsys.readouterr().out)
    counts = report["metric_measurements"]["faithfulness"]
    assert counts["total"] == 2
    assert len(pipeline.requests) == (1 if provider_error else 2)
    assert status == (1 if provider_error else 0)
    if provider_error:
        assert counts["failed_to_measure"] == 2
        assert report["query_results"][1]["answer_measurement"]["mode"] == "run_stopped"
        assert report["aggregate_metrics"] == {}
    else:
        assert counts["observed"] == 2
        assert report["aggregate_metrics"] == {"faithfulness": 0.0}


def test_dashboard_generated_answer_runs_through_public_button(pipeline, monkeypatch, golden):
    monkeypatch.setattr(pipeline.panel, "DEFAULT_GOLDEN_SET", golden)
    app = AppTest.from_function(render_panel).run()
    app.selectbox(key="eval_backend").select("ragas").run()
    app.radio(key="eval_answer_mode").set_value("generated").run()
    app.button(key="eval_run_btn").click().run()
    assert not app.exception
    assert_generation_lineage(pipeline, pipeline.panel._load_history()[0])
    assert any("测量完成" in item.value for item in app.success)
    assert any("observed/scored" in item.value for item in app.caption)
    assert any("answer_generator" in item.value for item in app.json)


@pytest.mark.parametrize("entry", ["cli", "dashboard"])
@pytest.mark.parametrize("failure", ["provider", "judge", "empty_answer"])
def test_generation_and_judge_failures_stay_unmeasured(pipeline, golden, capsys, entry, failure):
    pipeline.provider_error = failure == "provider"
    pipeline.judge_error = failure == "judge"
    if failure == "empty_answer":
        pipeline.response = "  "
    if entry == "cli":
        assert pipeline.cli.main(["--test-set", str(golden), "--answer-mode", "generated", "--json"]) == 1
        report = json.loads(capsys.readouterr().out)
    else:
        report = pipeline.panel._execute_evaluation("ragas", golden, 1, None, answer_mode="generated")
    assert report["measurement_status"] == "unmeasured"
    assert report["aggregate_metrics"] == {}
    assert report["metric_measurements"]["faithfulness"]["failed_to_measure"] == 1
    assert len(pipeline.judged) == (1 if failure == "judge" else 0)


def test_manual_cli_answers_are_distinct_and_never_generate(pipeline, golden, tmp_path, capsys):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps(["Actual separately supplied answer"]), encoding="utf-8")
    assert pipeline.cli.main(["--test-set", str(golden), "--answer-mode", "manual",
                              "--answers-file", str(answers), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert pipeline.requests == []
    assert pipeline.judged[0]["answer"] == "Actual separately supplied answer"
    assert report["query_results"][0]["answer_measurement"]["mode"] == "answer_override"
    assert report["query_results"][0]["reference_answer"] == "REFERENCE_ONLY_DO_NOT_GENERATE"


def test_missing_manual_answers_do_not_use_reference_or_context(pipeline, monkeypatch, golden):
    monkeypatch.setattr(pipeline.panel, "DEFAULT_GOLDEN_SET", golden)
    app = AppTest.from_function(render_panel).run()
    app.selectbox(key="eval_backend").select("ragas").run()
    app.button(key="eval_run_btn").click().run()
    assert not app.exception
    report = pipeline.panel._load_history()[0]
    assert report["query_results"][0]["generated_answer"] is None
    assert report["metric_measurements"]["faithfulness"]["not_applicable"] == 1
    assert report["measurement_status"] == "unmeasured"
    assert pipeline.requests == pipeline.judged == []
    assert not app.success
    assert any("unmeasured" in item.value for item in app.warning)


def test_retrieval_initialization_error_does_not_start_generation(pipeline, monkeypatch, golden, capsys):
    def failed(*args):
        raise RuntimeError("controlled index initialization failure")

    monkeypatch.setattr(pipeline.cli, "_create_hybrid_search", failed)
    assert pipeline.cli.main(["--test-set", str(golden), "--answer-mode", "generated", "--json"]) == 2
    assert "controlled index initialization failure" in capsys.readouterr().err
    monkeypatch.setattr(pipeline.panel, "_try_create_hybrid_search", lambda *_: None)
    with pytest.raises(RuntimeError, match="检索初始化失败"):
        pipeline.panel._execute_evaluation("ragas", golden, 1, None, answer_mode="generated")
    assert pipeline.requests == pipeline.judged == []


def test_manual_dashboard_answer_uses_actual_input(pipeline, monkeypatch, golden):
    monkeypatch.setattr(pipeline.panel, "DEFAULT_GOLDEN_SET", golden)
    app = AppTest.from_function(render_panel).run()
    app.selectbox(key="eval_backend").select("composite").run()
    app.text_area[0].set_value("Actual UI answer").run()
    app.button(key="eval_run_btn").click().run()
    assert not app.exception
    report = pipeline.panel._load_history()[0]
    assert report["query_results"][0]["generated_answer"] == "Actual UI answer"
    assert report["query_results"][0]["answer_measurement"]["mode"] == "answer_override"
    assert pipeline.requests == []
    assert pipeline.judged[0]["answer"] == "Actual UI answer"


@pytest.mark.parametrize("entry", ["cli", "dashboard"])
def test_partial_measurement_shows_denominator_and_failure(pipeline, monkeypatch, golden, capsys, entry):
    values = json.loads(golden.read_text(encoding="utf-8"))
    values["test_cases"].append(dict(values["test_cases"][0]))
    golden.write_text(json.dumps(values), encoding="utf-8")
    original = httpx.HTTPTransport.handle_request

    def transport(self, request):
        pipeline.provider_error = bool(pipeline.requests)
        return original(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    if entry == "cli":
        assert pipeline.cli.main(["--test-set", str(golden), "--answer-mode", "generated"]) == 1
        text = capsys.readouterr().out
        assert "Measurement: partial" in text
        assert "observed 1/2; failed_to_measure=1; not_applicable=0" in text
        assert "answer: failed_to_measure (answer_generator)" in text
        assert "Reference (separate, not generated)" in text
    else:
        monkeypatch.setattr(pipeline.panel, "DEFAULT_GOLDEN_SET", golden)
        app = AppTest.from_function(render_panel).run()
        app.selectbox(key="eval_backend").select("ragas").run()
        app.radio(key="eval_answer_mode").set_value("generated").run()
        app.button(key="eval_run_btn").click().run()
        assert not app.exception
        assert not app.success
        assert any("partial" in item.value for item in app.warning)
        counts = app.dataframe[0].value.iloc[0].to_dict()
        assert counts["total"] == 2 and counts["observed"] == 1 and counts["failed_to_measure"] == 1
        report = pipeline.panel._load_history()[0]
        assert report["aggregate_metrics"] == {"faithfulness": 0.0}


@pytest.mark.parametrize("values", [["too", "many"], [""], [42], {"0": "answer"}])
def test_cli_rejects_misaligned_or_invalid_actual_answers(pipeline, golden, tmp_path, capsys, values):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    assert pipeline.cli.main(["--test-set", str(golden), "--answer-mode", "manual",
                              "--answers-file", str(path), "--json"]) == 2
    assert "Configuration error" in capsys.readouterr().err
    assert pipeline.requests == pipeline.judged == []
