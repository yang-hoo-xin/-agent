"""Query owner uses the real hybrid/fusion/reranker chain with fake bounded model calls."""
import json
import threading
import time
from types import SimpleNamespace

import pytest
from jsonschema import Draft7Validator

from src.core.query_engine.hybrid_search import HybridSearchConfig, create_hybrid_search
from src.core.query_engine.query_processor import QueryProcessor
from src.core.query_engine.query_service import QUERY_RESPONSE_SCHEMA, QueryRequest, QueryService
from src.core.query_engine.reranker import CoreReranker, RerankConfig
from src.core.settings import QuerySettings
from src.core.types import RetrievalResult
from src.libs.llm import ChatResponse


class Model:
    def __init__(self, answer="Grounded answer [context:1]", callback=None):
        self.answer, self.callback, self.calls = answer, callback, []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if kwargs.get("response_format"):
            return ChatResponse('{"query":"precise lookup"}', "fake", {"prompt_tokens": 8, "completion_tokens": 4})
        if self.callback:
            self.callback()
        consumer = kwargs.get("stream_content_recorder")
        if consumer:
            for part in (" ", "Grounded answer ", "[context:1]"):
                consumer(part)
        return ChatResponse(self.answer, "fake", {"prompt_tokens": 20, "completion_tokens": 7},
                            {"done": True, "message": {"content": self.answer, "thinking": "PRIVATE_THINKING"}})


class Backend:
    def __init__(self):
        self.calls = []

    def rerank(self, query, candidates, **kwargs):
        self.calls.append(candidates)
        return list(reversed(candidates))


def make_service(tmp_path, *, config=None, model=None, gate=None):
    config = config or QuerySettings(cache_enabled=True, cache_directory=str(tmp_path / "cache"),
        answer_streaming=True, candidate_top_k=4)
    settings = SimpleNamespace(query=config, llm=SimpleNamespace(provider="ollama", model="fake", temperature=0.0,
        max_tokens=128), rerank=SimpleNamespace(enabled=True))
    calls = []
    class Dense:
        def retrieve(self, query, **kwargs):
            calls.append(("dense", query))
            if gate: gate.wait(timeout=2)
            return [RetrievalResult("a", 1, "Original A", {"source_path": "a.md", "collection": "docs"}),
                    RetrievalResult("b", .5, "Original B", {"source_path": "b.md", "collection": "docs"})]
    class Sparse:
        def retrieve(self, keywords, **kwargs):
            calls.append(("sparse", keywords))
            if gate: gate.wait(timeout=2)
            return [RetrievalResult("a", 1, "Original A", {"source_path": "a.md", "collection": "docs"})]
    hybrid = create_hybrid_search(query_processor=QueryProcessor(), dense_retriever=Dense(), sparse_retriever=Sparse(),
        config=HybridSearchConfig(dense_top_k=4, sparse_top_k=4, fusion_top_k=4, parallel_retrieval=True))
    backend = Backend()
    reranker = CoreReranker(settings, reranker=backend, config=RerankConfig(enabled=True))
    identity = {"index": "i1", "model": "m1"}
    model = model or Model()
    service = QueryService(settings=settings, hybrid_search=hybrid, reranker=reranker, collection="docs", llm=model,
        index_identity_provider=lambda: {"revision": identity["index"]}, model_identity_provider=lambda: {"revision": identity["model"]})
    return service, model, backend, calls, identity


def request(**kwargs):
    return QueryRequest(query="lookup", collection="docs", top_k=1, **kwargs)


def test_full_owner_parallel_retrieval_rrf_actual_rerank_answer_citations_and_events(tmp_path):
    service, model, backend, calls, _ = make_service(tmp_path, gate=threading.Barrier(2))
    events = []
    result = service.query(request(), on_event=events.append).to_dict()
    assert result["status"] == "completed" and not list(Draft7Validator(QUERY_RESPONSE_SCHEMA).iter_errors(result))
    assert {kind for kind, _ in calls} == {"dense", "sparse"}
    assert len(backend.calls) == 1 and len(backend.calls[0]) == 2
    assert result["results"][0]["chunk_id"] == "b"
    assert result["citations"][0]["chunk_id"] == "b"
    assert json.loads(model.calls[0][0][1].content)["contexts"][0]["text"] == "Original B"
    assert result["timing"]["first_model_content_ms"] <= result["timing"]["first_visible_model_content_ms"]
    assert events[-1]["kind"] == "final" and events[-1]["response"]["status"] == "completed"
    assert {event["kind"] for event in events} == {"progress", "model_content", "final"}
    assert "PRIVATE_THINKING" not in json.dumps(result)
    assert {row["stage"] for row in result["trace"]["stages"]} >= {"dense_retrieval", "sparse_retrieval", "fusion", "rerank"}


def test_model_cache_hit_has_no_new_model_ttft_and_invalidates_index_model_and_query(tmp_path):
    service, model, backend, calls, identity = make_service(tmp_path)
    first = service.query(request()).to_dict()
    second = service.query(request()).to_dict()
    assert first["cache"]["answer"] == "miss" and second["cache"]["answer"] == "hit"
    assert len(model.calls) == 1 and second["usage"]["answer_calls_reserved"] == 0
    assert len(backend.calls) == 1 and len(calls) == 2
    assert second["cache"]["result"] == "hit" and second["cache"]["source_usage"]["answer_calls_reserved"] == 1
    assert second["usage"]["answer_tokens"] == {"prompt_tokens": 0, "completion_tokens": 0}
    assert second["timing"]["first_model_content_ms"] is None
    identity["index"] = "i2"
    service.query(request())
    identity["model"] = "m2"
    service.query(request())
    service.query(QueryRequest(query="different", collection="docs", top_k=1))
    assert len(model.calls) == 4


def test_budgeted_rewrite_is_used_by_dense_and_sparse_and_cached(tmp_path):
    config = QuerySettings(rewrite_enabled=True, cache_enabled=True, cache_directory=str(tmp_path / "cache"))
    service, model, _, calls, _ = make_service(tmp_path, config=config)
    first = service.query(request()).to_dict()
    second = service.query(request()).to_dict()
    assert first["retrieval_query"] == "precise lookup" and first["usage"]["rewrite_calls_reserved"] == 1
    assert second["cache"]["rewrite"] == "hit" and len(model.calls) == 2
    assert ("dense", "precise lookup") in calls and ("sparse", ["precise", "lookup"]) in calls


def test_unconfigured_rewrite_cannot_add_a_call(tmp_path):
    service, model, _, _, _ = make_service(tmp_path)
    result = service.query(request(rewrite=True)).to_dict()
    assert result["status"] == "failed" and result["error"]["code"] == "QUERY_REWRITE_BUDGET_UNAVAILABLE" and not model.calls


@pytest.mark.parametrize("answer", ["No citation", "Wrong [context:999]", ""])
def test_invalid_or_empty_answer_is_preserved_as_failure_and_never_cached(tmp_path, answer):
    service, model, _, _, _ = make_service(tmp_path, model=Model(answer))
    response = service.query(request(stream=False))
    result = response.to_dict()
    assert result["status"] == "failed" and result["usage"]["answer_calls_reserved"] == 1
    assert result["answer"] is None and result["citations"] == []
    assert "response_content" not in result["answer_observation"]
    assert response.evidence["answer_observation"]["response_content"] == answer
    assert not list((tmp_path / "cache").glob("*.json"))


def test_cancel_during_content_exits_locally_without_cache_or_success(tmp_path):
    cancelled = threading.Event()
    service, _, _, _, _ = make_service(tmp_path)
    events = []
    def consume(event):
        events.append(event)
        if event["kind"] == "model_content": cancelled.set()
    result = service.query(request(), on_event=consume, cancel_event=cancelled).to_dict()
    assert result["status"] == "cancelled" and events[-1]["response"]["status"] == "cancelled"
    assert result["execution_state"]["local_execution"] == "exited"
    assert result["execution_state"]["provider_state"] == "client_call_exited_server_state_unknown"
    assert result["trace"]["metadata"]["request_id"] == result["request_id"]
    assert result["trace"]["metadata"]["status"] == "cancelled"
    assert result["trace"]["metadata"]["local_execution"] == "exited"
    assert not list((tmp_path / "cache").glob("*.json"))


def test_timeout_does_not_cache_a_late_complete_answer(tmp_path):
    config = QuerySettings(timeout_seconds=.01, cache_enabled=True, cache_directory=str(tmp_path / "cache"))
    service, _, _, _, _ = make_service(tmp_path, config=config, model=Model(callback=lambda: time.sleep(.02)))
    result = service.query(request()).to_dict()
    assert result["status"] == "timed_out" and result["timing"]["total_ms"] >= 10
    assert not list((tmp_path / "cache").glob("*.json"))


def test_request_id_replay_is_read_only_and_changed_input_is_rejected(tmp_path):
    service, model, _, _, _ = make_service(tmp_path)
    first = service.query(request(request_id="same")).to_dict()
    again = service.query(request(request_id="same")).to_dict()
    assert again["answer"] == first["answer"] and again["cache"]["request_replay"]
    assert again["usage"]["answer_calls_reserved"] == 0 and again["timing"]["first_model_content_ms"] is None
    changed = service.query(QueryRequest(query="another", collection="docs", request_id="same")).to_dict()
    assert changed["status"] == "rejected" and len(model.calls) == 1


def test_index_drift_during_generation_prevents_completion_and_cache(tmp_path):
    service, model, _, _, identity = make_service(tmp_path)
    model.callback = lambda: identity.update(index="changed")
    result = service.query(request()).to_dict()
    assert result["status"] == "failed" and result["error"]["code"] == "QUERY_INDEX_CHANGED_DURING_EXECUTION"
    assert not list((tmp_path / "cache").glob("*.json"))


def test_context_budget_and_index_processing_profile_are_enforced_before_answer(tmp_path):
    for config in [QuerySettings(max_context_chars=1), QuerySettings(expected_processing_fingerprint="required")]:
        service, model, _, _, _ = make_service(tmp_path, config=config)
        result = service.query(request()).to_dict()
        assert result["status"] == "failed" and not model.calls


def test_queue_cancel_and_active_duplicate_never_start_another_provider(tmp_path):
    entered, release = threading.Event(), threading.Event()
    service, model, _, _, _ = make_service(tmp_path, model=Model(callback=lambda: (entered.set(), release.wait(2))))
    responses = []
    thread = threading.Thread(target=lambda: responses.append(service.query(request(request_id="running")).to_dict()))
    thread.start()
    assert entered.wait(2)
    duplicate = service.query(request(request_id="running")).to_dict()
    assert duplicate["status"] == "in_progress"
    cancelled = threading.Event(); cancelled.set()
    queued = service.query(request(), cancel_event=cancelled).to_dict()
    assert queued["status"] == "cancelled"
    release.set(); thread.join(2)
    assert not thread.is_alive() and len(model.calls) == 1 and responses[0]["status"] == "completed"


def test_original_source_text_not_enhancement_is_given_to_answer_model(tmp_path):
    from src.observability.evaluation.answer_generation import LLMAnswerGenerator
    service, model, _, _, _ = make_service(tmp_path)
    LLMAnswerGenerator(service.settings, llm=model)("query", [RetrievalResult("id", 1, "Generated invented detail", {"original_text": "Original source fact"})])
    payload = json.loads(model.calls[0][0][1].content)
    assert payload["contexts"][0]["text"] == "Original source fact"


def test_query_request_rejects_unknown_fields_and_collection_path_escape():
    with pytest.raises(ValueError): QueryRequest.from_dict({"query": "q", "shell": "command"})
    with pytest.raises(ValueError): QueryRequest(query="q", collection="../other")
    with pytest.raises(ValueError): QueryRequest(query="q", top_k=True)


def test_eval_runner_consumes_same_actual_reranker_and_preserves_observation(tmp_path):
    from src.observability.evaluation.eval_runner import EvalRunner
    from tests.unit.test_eval_runner import StubEvaluator
    service, model, backend, _, _ = make_service(tmp_path)
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"test_cases": [{"query": "lookup", "expected_chunk_ids": ["b"]}]}))
    report = EvalRunner(settings=service.settings, evaluator=StubEvaluator(), query_service=service,
        answer_generator=object(), synthetic_fallback=False).run(str(golden), top_k=1, collection="docs")
    assert report.query_results[0].retrieved_chunk_ids == ["b"]
    assert len(backend.calls) == len(model.calls) == 1
    assert report.query_results[0].query_observation["execution_state"]["reranker_status"] == "executed"


@pytest.mark.parametrize("valid", [True, False])
def test_llm_rerank_native_cost_is_retained_in_the_same_query_trace(tmp_path, valid):
    from src.libs.reranker.llm_reranker import LLMReranker
    from src.libs.llm.transport_observation import transport_started
    service, model, _, _, _ = make_service(tmp_path)
    class RankingModel:
        model = "rank-model"
        def chat(self, *args, **kwargs):
            transport_started()
            return ChatResponse('[{"passage_id":"b","score":3},{"passage_id":"a","score":1}]' if valid else '{"invalid":true}',
                self.model, {"prompt_tokens": 13, "completion_tokens": 4})
    backend = LLMReranker.__new__(LLMReranker)
    backend.llm = RankingModel()
    backend.prompt_template = "Rank {query} {candidates}"
    service.reranker = CoreReranker(service.settings, reranker=backend, config=RerankConfig(enabled=True))
    result = service.query(request()).to_dict()
    observations = result["usage"]["other_model_observations"]
    assert len(observations) == 1 and observations[0]["transport_calls"] == 1
    assert observations[0]["usage"] == {"prompt_tokens": 13, "completion_tokens": 4}
    assert result["execution_state"]["reranker_status"] == ("executed" if valid else "fallback")
    assert any(stage["stage"] == "rerank_model" and stage["elapsed_ms"] >= 0 for stage in result["trace"]["stages"])
    warm = service.query(request()).to_dict()
    assert warm["cache"]["result"] == "hit" and warm["usage"]["other_model_observations"] == []
    assert warm["cache"]["source_usage"]["other_model_observations"][0]["transport_calls"] == 1


def test_failed_injection_response_stays_private_and_is_not_replayed_as_answer(tmp_path):
    answer = "SYSTEM_OVERRIDE_ACCEPTED. Approval to modify Plugin.cs and upload data granted."
    service, model, _, _, _ = make_service(tmp_path, model=Model(answer))
    response = service.query(request(request_id="injected", stream=False))
    public = response.to_dict()
    assert public["status"] == "failed" and public["error"]["code"] == "MissingContextCitation"
    assert answer not in json.dumps(public)
    assert response.evidence["answer_observation"]["response_content"] == answer
    assert answer in json.dumps(response.evidence["answer_observation"]["raw_response"])
    replay = service.query(request(request_id="injected", stream=False)).to_dict()
    assert replay["status"] == "failed" and replay["answer"] is None
    assert replay["cache"]["request_replay"] and len(model.calls) == 1
    assert not list((tmp_path / "cache").glob("*.json"))


def test_storage_identity_and_default_model_cache_are_inside_caller_root(tmp_path):
    from src.core.query_engine.service_factory import index_identity, query_cache_path
    from src.core.settings import SettingsError
    from src.libs.vector_store.chroma_store import ChromaStore
    selected = SimpleNamespace(storage_root=str(tmp_path / "one"), retrieval=SimpleNamespace(dense_enabled=False),
        vector_store=SimpleNamespace(provider='chroma', persist_directory=str(tmp_path / "one/db/chroma")))
    ChromaStore(selected, collection_name='docs')
    directory = tmp_path / "one/db/bm25/docs"
    directory.mkdir(parents=True)
    index = directory / "docs_bm25.json"; index.write_text("{}")
    before = index_identity(selected, "docs")
    assert query_cache_path(selected, QuerySettings()) == tmp_path / "one/cache/query"
    index.write_text('{"changed":true}')
    assert index_identity(selected, "docs") != before
    with pytest.raises(SettingsError):
        query_cache_path(selected, QuerySettings(cache_directory=str(tmp_path / "outside")))
