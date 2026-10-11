"""Shared normal-entry construction for query CLI, MCP and evaluation."""
from src.core.query_engine.result_cache import fingerprint
from src.core.query_engine.query_service import QueryRequest, QueryService
from src.core.settings import QuerySettings, resolve_path, resolve_storage_path, require_storage_path


def create_retrieval_stack(settings, collection):
    from src.core.query_engine.dense_retriever import create_dense_retriever
    from src.core.query_engine.hybrid_search import create_hybrid_search
    from src.core.query_engine.query_processor import QueryProcessor
    from src.core.query_engine.sparse_retriever import create_sparse_retriever
    from src.ingestion.storage.bm25_indexer import BM25Indexer
    from src.libs.embedding.embedding_factory import EmbeddingFactory
    from src.libs.vector_store.vector_store_factory import VectorStoreFactory

    QueryRequest(query="validate collection", collection=collection)
    vector_store = VectorStoreFactory.create(settings, collection_name=collection)
    enabled, provider = settings.retrieval.dense_enabled, settings.retrieval.dense_provider
    if enabled and provider != "vector_store" or not enabled and provider != "disabled":
        raise ValueError("Evaluation dense retrieval requires consistent vector_store/disabled configuration.")
    dense = create_dense_retriever(settings=settings, embedding_client=EmbeddingFactory.create(settings),
                                   vector_store=vector_store) if enabled else None
    sparse = create_sparse_retriever(settings=settings, bm25_indexer=BM25Indexer(index_dir=str(resolve_storage_path(settings, "db", "bm25", collection))),
                                     vector_store=vector_store)
    sparse.default_collection = collection
    return create_hybrid_search(settings=settings, query_processor=QueryProcessor(), dense_retriever=dense, sparse_retriever=sparse)


def index_identity(settings, collection, *, vector_store=None):
    import hashlib
    # 为什么要有它：Sparse也按BM25命中ID从向量存储读取正文和metadata；任一来源变化都必须使完整结果缓存失效。
    roots = [resolve_storage_path(settings, "db", "bm25", collection)]
    if settings.retrieval.dense_enabled:
        roots.append(require_storage_path(settings, settings.vector_store.persist_directory))
        sparse_content = None
    else:
        sparse_content = _sparse_content_identity(settings, collection, vector_store=vector_store)
        if sparse_content is None:
            return None
    files = []
    for root in roots:
        if not root.is_dir():
            return None
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files.append({"root": str(root), "path": path.relative_to(root).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not files:
        return None
    identity = {"collection": collection, "files_sha256": fingerprint(files), "file_count": len(files)}
    if sparse_content is not None:
        identity['sparse_content'] = sparse_content
    return identity


def _sparse_content_identity(settings, collection, *, vector_store=None):
    # 为什么要有它：Chroma正常跨进程初始化会改变SQLite物理字节；稀疏结果绑定公开读取到的正文与metadata，而不是文件维护状态。
    if settings.vector_store.provider.lower() != 'chroma':
        return None
    root = require_storage_path(settings, settings.vector_store.persist_directory)
    if not root.is_dir() or not (root/'chroma.sqlite3').is_file():
        return None
    if vector_store is not None:
        if vector_store.persist_directory != root or vector_store.collection_name != collection:
            raise ValueError('QUERY_INDEX_STORE_BINDING_MISMATCH')
        selected = vector_store.collection
    else:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from chromadb.errors import NotFoundError
        client = chromadb.PersistentClient(path=str(root),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True))
        try:
            selected = client.get_collection(collection)
        except NotFoundError:
            return None
    # 当前每次身份检查全量读取该collection正文与metadata并哈希；这是正确性成本，不预先宣称性能收益。
    rows = selected.get(include=['documents', 'metadatas'])
    records = sorted(({'id': identifier, 'document': rows['documents'][index],
                       'metadata': rows['metadatas'][index]}
                      for index, identifier in enumerate(rows['ids'])), key=lambda row: row['id'])
    return {'provider': 'chroma', 'root': str(root), 'collection_id': str(selected.id),
            'record_count': len(records), 'content_sha256': fingerprint(records)}


def create_query_service(settings, collection="default", *, hybrid_search=None, reranker=None,
                         index_identity_provider=None, model_identity_provider=None, llm=None, trace_collector=None):
    from src.core.query_engine.reranker import create_core_reranker
    from src.core.query_engine.result_cache import QueryResultCache
    from src.core.trace import TraceCollector
    config = getattr(settings, "query", None) or QuerySettings()
    if model_identity_provider is None:
        def model_identity_provider():
            if not config.model_revision:
                return None
            return {"provider": settings.llm.provider, "model": settings.llm.model, "revision": config.model_revision,
                    "revision_origin": "caller_configured", "temperature": settings.llm.temperature,
                    "max_tokens": settings.llm.max_tokens, "context_window": config.context_window}
    stack = hybrid_search or create_retrieval_stack(settings, collection)
    vector_store = getattr(getattr(stack, 'sparse_retriever', None), 'vector_store', None)
    # 为什么要有它：正常入口已经构造了真实store，身份检查复用它，避免重复初始化Chroma客户端。
    return QueryService(settings=settings, hybrid_search=stack,
        reranker=reranker or create_core_reranker(settings=settings), collection=collection, llm=llm,
        index_identity_provider=index_identity_provider or (lambda: index_identity(settings, collection, vector_store=vector_store)),
        model_identity_provider=model_identity_provider,
        cache=QueryResultCache(query_cache_path(settings, config)) if config.cache_enabled else None,
        trace_collector=trace_collector or (TraceCollector(resolve_path(settings.observability.trace_file))
                                          if settings.observability.trace_enabled else None))


def query_cache_path(settings, config):
    return (resolve_storage_path(settings, "cache", "query") if config.cache_directory == "data/cache/query"
            else require_storage_path(settings, config.cache_directory))
