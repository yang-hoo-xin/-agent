"""Bare API member retrieval from real version-bound XML documentation."""
import hashlib

import pytest

from src.core.query_engine.query_processor import QueryProcessor
from src.core.query_engine.tokenization import tokenize_retrieval_text
from src.core.types import Chunk
from src.ingestion.embedding.sparse_encoder import SparseEncoder
from src.ingestion.storage.bm25_indexer import BM25Indexer

# Exact member from the supplied BepInEx.Core.xml, whose SHA-256 is
# 1a19ea693c0c2549d35b95b04e4a5f51b419a43a0fc4bfeb998349ecb80b5762.
CONFIG_RELOADED = '''        <member name="E:BepInEx.Configuration.ConfigFile.ConfigReloaded">
            <summary>
                An event that is fired every time the config is reloaded.
            </summary>
        </member>'''


def test_real_xml_sparse_index_roundtrip_retrieves_bare_member(tmp_path):
    assert hashlib.sha256(CONFIG_RELOADED.encode()).hexdigest() == (
        '1390adce1a42c56e33fd52ce0c530f83e6432b00c9a5b76c6fbfe6f2cdfceec6')
    negatives = [
        'https://BepInEx.Configuration.ConfigFile.ConfigReloaded',
        'docs/BepInEx.Configuration.ConfigFile.ConfigReloaded',
        r'C:\docs\BepInEx.Configuration.ConfigFile.ConfigReloaded',
        'BepInEx.Configuration.ConfigFile.ConfigReloaded',
        'version 6.0.0.665',
    ]
    chunks = [Chunk(id='api', text=CONFIG_RELOADED, metadata={'source_path': 'BepInEx.Core.xml'})]
    chunks.extend(Chunk(id=f'negative-{i}', text=text, metadata={'source_path': 'negative.txt'})
                  for i, text in enumerate(negatives))
    stats = SparseEncoder().encode(chunks)
    assert stats[0]['term_frequencies']['bepinex.configuration.configfile.configreloaded'] == 1
    assert stats[0]['term_frequencies']['configreloaded'] == 1
    BM25Indexer(index_dir=str(tmp_path)).build(stats, collection='xml')
    index = BM25Indexer(index_dir=str(tmp_path))
    index.load('xml')
    for query in ('ConfigReloaded', 'configreloaded', 'CONFIGRELOADED'):
        hits = index.query(QueryProcessor().process(query).keywords)
        assert [hit['chunk_id'] for hit in hits] == ['api']
        assert hits[0]['score'] > 0
    assert index.query(QueryProcessor().process('AbsentMember').keywords) == []


@pytest.mark.parametrize('source,short', [
    ('<member name="M:BepInEx.Logging.ManualLogSource.LogInfo(System.Object)">', 'LogInfo'),
    ("<see cref='F:BepInEx.Logging.LogLevel.Info' />", 'Info'),
    ('<member name="M:Example.Type.Method``1(System.String)">', 'Method'),
    ('<member name="E:example.type.member_changed">', 'member_changed'),
])
def test_explicit_xml_symbols_keep_case_and_normalize_only_when_requested(source, short):
    assert short in tokenize_retrieval_text(source)
    assert short.lower() in tokenize_retrieval_text(source, lowercase=True)


@pytest.mark.parametrize('source,short', [
    ('https://example.com/ConfigFile.ConfigReloaded', 'ConfigReloaded'),
    ('ConfigFile.ConfigReloaded@example.com', 'ConfigReloaded'),
    ('/docs/ConfigFile.ConfigReloaded', 'ConfigReloaded'),
    ('1.2.3.4', '4'),
    ('<member name="E:Example.ConfigReloaded/path">', 'ConfigReloaded'),
    ('<member name="E:Example.ConfigReloaded-file">', 'ConfigReloaded'),
    ('<a href="https://Example.ConfigReloaded">', 'ConfigReloaded'),
])
def test_non_symbols_do_not_gain_short_aliases(source, short):
    assert short not in tokenize_retrieval_text(source)


def test_shared_tokenizer_changes_invalidate_index_and_query_cache_identities(monkeypatch, tmp_path):
    from src.core import settings as settings_module
    from src.core.query_engine.query_service import query_implementation_identity
    from src.ingestion import identity

    real_resolve = settings_module.resolve_path
    changed = tmp_path / 'tokenization.py'
    changed.write_text('version one', encoding='utf-8')
    relative = 'src/core/query_engine/tokenization.py'
    def resolve(path):
        return changed if path == relative else real_resolve(path)
    monkeypatch.setattr(identity, 'resolve_path', resolve)
    monkeypatch.setattr(settings_module, 'resolve_path', resolve)
    settings = settings_module.load_settings('config/settings.yaml')
    before_ingest, before_digest = identity.ingestion_identity(settings)
    before_query = query_implementation_identity()
    assert before_ingest['implementation_sha256'][relative] == before_query[relative]
    assert before_query[relative] == hashlib.sha256(changed.read_bytes()).hexdigest()
    changed.write_text('version two', encoding='utf-8')
    assert identity.ingestion_identity(settings)[1] != before_digest
    assert query_implementation_identity() != before_query
