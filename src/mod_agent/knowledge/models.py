"""Data contracts for the local Knowledge Base."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceRecord:
    """Registered source root that can contribute evidence."""

    source_id: str
    source_type: str
    root_path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexedFile:
    """Content hash state for one indexed source file."""

    file_id: str
    source_id: str
    source_path: str
    relative_path: str
    content_hash: str
    indexed_at: str


@dataclass(frozen=True)
class SymbolRecord:
    """Symbol-level evidence index entry."""

    symbol_id: str
    source_id: str
    source_path: str
    relative_path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    excerpt: str
    content_hash: str

    def to_evidence_item(self, *, retrieval_method: str = "symbol") -> dict[str, Any]:
        """Project a symbol into the Evidence Item shape used by Phase D."""

        return {
            "evidence_id": self.symbol_id,
            "source_type": self.source_id,
            "source_path": self.source_path,
            "symbol": self.name,
            "span": {
                "start_line": self.start_line,
                "end_line": self.end_line,
            },
            "retrieval_method": retrieval_method,
            "score": 1.0,
            "claim_supported": f"Symbol {self.name} exists in {self.relative_path}.",
            "excerpt": self.excerpt,
            "risk_notes": [],
        }
