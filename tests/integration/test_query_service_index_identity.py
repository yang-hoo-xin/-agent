"""Real BM25, Chroma, QueryService and Redis cache; no provider/model calls."""
import hashlib
import os
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

redis = pytest.importorskip('redis')
pytest.importorskip('chromadb')

from src.core.query_engine.service_factory import index_identity  # noqa: E402
from src.core.settings import load_settings  # noqa: E402
from src.ingestion.storage.bm25_indexer import BM25Indexer  # noqa: E402
from src.libs.vector_store.chroma_store import ChromaStore  # noqa: E402
from src.service_layer.backends import run_query  # noqa: E402


@pytest.fixture
def corpus(tmp_path):
    url = os.environ.get('SERVICE_TEST_REDIS_URL')
    if not url:
        pytest.skip('Real Redis URL is required; no fake cache fallback')
    client = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
    client.ping()
    namespace = 'query-identity-test-' + uuid4().hex
    config = yaml.safe_load(Path('config/settings.yaml').read_text(encoding='utf-8'))
    config['storage_root'] = str(tmp_path)
    config['vector_store']['persist_directory'] = str(tmp_path/'db/chroma')
    config['retrieval'].update(dense_enabled=False, dense_provider='disabled')
    config['rerank'].update(enabled=False, provider='none')
    config['observability']['trace_enabled'] = False
    config['query'] = {'cache_enabled': True, 'rewrite_enabled': False}
    settings_path = tmp_path/'settings.yaml'
    settings_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    settings = load_settings(settings_path)
    store = ChromaStore(settings, collection_name='documents')
    store.upsert([{'id': 'one', 'vector': [1.0, 0.0],
        'metadata': {'text': 'alpha original content', 'source_path': 'before.md', 'collection': 'documents'}}])
    bm25 = tmp_path/'db/bm25/documents'
    BM25Indexer(index_dir=str(bm25)).build([
        {'chunk_id': 'one', 'term_frequencies': {'alpha': 1}, 'doc_length': 3}], collection='documents')
    payload = {'query': 'alpha', 'collection': 'documents', 'top_k': 1,
        'answer': False, 'rewrite': False, 'rerank': False,
        '_settings_sha256': hashlib.sha256(settings_path.read_bytes()).hexdigest()}
    service_config = SimpleNamespace(settings_path=settings_path, namespace=namespace, query_cache_ttl=60)
    child_code = '''import json,os,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
import redis
from src.service_layer.backends import run_query
config=SimpleNamespace(settings_path=Path(sys.argv[2]),namespace=sys.argv[3],query_cache_ttl=60)
client=redis.Redis.from_url(os.environ['SERVICE_TEST_REDIS_URL'],socket_timeout=3,socket_connect_timeout=3)
try:
 print(json.dumps(run_query(json.loads(sys.argv[4]),config,job_id=sys.argv[5],timeout_seconds=20,redis_client=client)))
finally:
 client.close()
'''
    def query(process_mode):
        if process_mode == 'inprocess':
            return run_query(payload, service_config, job_id=uuid4().hex, timeout_seconds=20, redis_client=client)
        # 为什么要有它：每个服务作业有独立进程，不能由Chroma进程内client缓存掩盖初始化导致的身份漂移。
        process = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', child_code,
            str(Path.cwd()), str(settings_path), namespace, json.dumps(payload), uuid4().hex],
            capture_output=True, timeout=30)
        assert process.returncode == 0, process.stderr.decode('utf-8', 'replace')
        return json.loads(process.stdout)
    try:
        yield settings, store, bm25, query
    finally:
        # 为什么要有它：只删除本例的随机缓存命名空间，不能清空共享Redis。
        keys = list(client.scan_iter(match=namespace+':query-cache:*'))
        if keys:
            client.delete(*keys)
        client.close()


@pytest.mark.parametrize('change', ['document', 'metadata'])
@pytest.mark.parametrize('process_mode', ['inprocess', 'subprocess'])
def test_sparse_result_cache_tracks_chroma_without_bm25_rebuild(corpus, change, process_mode):
    settings, chroma, bm25, query_entry = corpus
    def query():
        return query_entry(process_mode)
    before_bm25 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in bm25.rglob('*') if p.is_file()}
    first = query()
    assert first['status'] == 'completed', first.get('error')
    assert first['results'][0]['text'] == 'alpha original content'
    assert first['cache']['result'] == 'miss'
    identity = index_identity(settings, 'documents')
    for _ in range(2):
        repeated = query()
        assert repeated['status'] == 'completed', repeated.get('error')
        assert repeated['cache']['result'] == 'hit'
        assert index_identity(settings, 'documents') == identity
    unrelated = ChromaStore(settings, collection_name='unrelated')
    unrelated.upsert([{'id': 'other', 'vector': [0.0, 1.0], 'metadata': {'text': 'unrelated changed text'}}])
    assert index_identity(settings, 'documents') == identity
    assert query()['cache']['result'] == 'hit'
    if change == 'document':
        chroma.collection.update(ids=['one'], documents=['alpha updated content'], embeddings=[[1.0, 0.0]])
    else:
        chroma.collection.update(ids=['one'], metadatas=[{'source_path': 'after.md'}])
    assert before_bm25 == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in bm25.rglob('*') if p.is_file()}
    # 为什么要有它：Sparse分数来自BM25，但正文和来源来自Chroma；仅更新后者也必须淘汰完整结果缓存。
    updated = query()
    assert updated['status'] == 'completed', updated.get('error')
    if change == 'document':
        assert updated['results'][0]['text'] == 'alpha updated content'
    else:
        assert updated['results'][0]['metadata']['source_path'] == 'after.md'
    assert updated['cache']['result'] == 'miss'
    assert index_identity(settings, 'documents') != identity
    assert query()['cache']['result'] == 'hit'
