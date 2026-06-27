"""Knowledge base primitives for evidence-grounded code development."""

from .database import KnowledgeDatabase
from .indexer import IncrementalIndexer, IndexingReport
from .models import IndexedFile, SourceRecord, SymbolRecord
from .source_registry import SourceDefinition, SourceRegistry
from .symbol_indexer import SymbolIndexer

__all__ = [
    "IncrementalIndexer",
    "IndexedFile",
    "IndexingReport",
    "KnowledgeDatabase",
    "SourceDefinition",
    "SourceRecord",
    "SourceRegistry",
    "SymbolIndexer",
    "SymbolRecord",
]
