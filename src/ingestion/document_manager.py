"""Cross-store document lifecycle management.

This module provides a single entry-point for listing, inspecting, and
deleting documents across all four storage backends (ChromaDB, BM25,
ImageStorage, FileIntegrityChecker).

Design Principles:
- Coordinated: one call cascades into all relevant stores.
- Fail-safe: partial failures are reported but do not abort remaining stores.
- Read-only safe: list / stats / detail methods never mutate data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result data-classes
# ---------------------------------------------------------------------------

@dataclass
class DocumentInfo:
    """Summary information about an ingested document."""

    source_path: str
    source_hash: str
    collection: Optional[str] = None
    chunk_count: int = 0
    image_count: int = 0
    processed_at: Optional[str] = None


@dataclass
class DocumentDetail(DocumentInfo):
    """Extended document info including chunk IDs and image IDs."""

    chunk_ids: List[str] = field(default_factory=list)
    image_ids: List[str] = field(default_factory=list)


@dataclass
class DeleteResult:
    """Outcome of a delete_document operation."""

    success: bool
    chunks_deleted: int = 0
    bm25_removed: bool = False
    images_deleted: int = 0
    integrity_removed: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class CollectionStats:
    """Aggregate statistics for a collection."""

    collection: Optional[str] = None
    document_count: int = 0
    chunk_count: int = 0
    image_count: int = 0


# ---------------------------------------------------------------------------
# DocumentManager
# ---------------------------------------------------------------------------

class DocumentManager:
    """Coordinate document lifecycle across all storage backends.

    Args:
        chroma_store: ChromaStore instance (vector store).
        bm25_indexer: BM25Indexer instance (sparse index).
        image_storage: ImageStorage instance (image files + SQLite index).
        file_integrity: SQLiteIntegrityChecker instance (ingestion history).
    """

    def __init__(
        self,
        chroma_store: Any,
        bm25_indexer: Any,
        image_storage: Any,
        file_integrity: Any,
    ) -> None:
        self.chroma = chroma_store
        self.bm25 = bm25_indexer
        self.images = image_storage
        self.integrity = file_integrity

    # ------------------------------------------------------------------
    # list_documents
    # ------------------------------------------------------------------

    def list_documents(
        self, collection: Optional[str] = None
    ) -> List[DocumentInfo]:
        """Return a list of ingested documents.

        Combines information from the integrity checker (source_path,
        hash, processed_at) with counts from ChromaDB and ImageStorage.

        Args:
            collection: Optional collection filter.

        Returns:
            List of ``DocumentInfo`` objects.
        """
        records = self.integrity.list_processed(collection)

        docs: List[DocumentInfo] = []
        for rec in records:
            source_hash = rec["file_hash"]
            source_path = rec["file_path"]
            coll = rec.get("collection")

            # Count chunks in Chroma
            chunk_count = self._count_chunks(source_hash, coll)

            # Count images
            image_count = self._count_images(source_hash, coll)

            docs.append(
                DocumentInfo(
                    source_path=source_path,
                    source_hash=source_hash,
                    collection=coll,
                    chunk_count=chunk_count,
                    image_count=image_count,
                    processed_at=rec.get("processed_at"),
                )
            )

        return docs

    # ------------------------------------------------------------------
    # get_document_detail
    # ------------------------------------------------------------------

    def get_document_detail(self, doc_id: str, collection: Optional[str] = None) -> Optional[DocumentDetail]:
        """Get detailed information about a single document.

        *doc_id* is matched against the ``source_hash`` stored in the
        integrity checker.

        Args:
            doc_id: The document's source_hash.

        Returns:
            ``DocumentDetail`` with chunk/image IDs, or *None* if not found.
        """
        # Look up integrity record
        all_records = self.integrity.list_processed(collection)
        matches = [rec for rec in all_records if rec["file_hash"] == doc_id]
        if len(matches) > 1:
            raise ValueError("Document exists in multiple collections; select its collection.")
        record = matches[0] if matches else None

        if record is None:
            return None

        source_hash = record["file_hash"]

        # Collect chunk IDs from Chroma
        chunk_ids = self._get_chunk_ids(source_hash, record.get("collection"))

        # Collect image IDs
        image_ids = self._get_image_ids(source_hash, record.get("collection"))

        return DocumentDetail(
            source_path=record["file_path"],
            source_hash=source_hash,
            collection=record.get("collection"),
            chunk_count=len(chunk_ids),
            image_count=len(image_ids),
            processed_at=record.get("processed_at"),
            chunk_ids=chunk_ids,
            image_ids=image_ids,
        )

    # ------------------------------------------------------------------
    # delete_document
    # ------------------------------------------------------------------

    def delete_document(
        self,
        source_path: str,
        collection: str = "default",
        source_hash: Optional[str] = None,
    ) -> DeleteResult:
        """Delete a document from all storage backends.

        Coordinates deletion across ChromaDB, BM25, ImageStorage, and
        FileIntegrity.  Partial failures are captured in
        ``DeleteResult.errors`` but do not prevent remaining stores
        from being cleaned.

        The document is identified by its *source_hash*.  When the hash
        is not supplied the method tries to compute it from the file;
        if the file no longer exists it falls back to looking up the
        hash from the integrity records by path.

        Args:
            source_path: Original filesystem path of the document.
            collection: Collection the document belongs to.
            source_hash: Pre-computed SHA-256 hash.  When provided the
                method will not attempt to read the source file.

        Returns:
            ``DeleteResult`` summarising what was cleaned.
        """
        result = DeleteResult(success=True)

        # The injected vector backend is already bound to one collection. Never
        # delete through that handle on behalf of a different/unknown scope.
        if type(collection) is not str or getattr(self.chroma, "collection_name", None) != collection:
            result.success = False
            result.errors.append("ChromaDB collection does not match the selected deletion scope.")
            return result

        # Resolve hash – prefer caller-supplied, then file, then DB lookup
        if source_hash is None:
            try:
                source_hash = self.integrity.compute_sha256(source_path)
            except Exception as e:
                source_hash = self._hash_from_path(source_path, collection)
                if source_hash is None:
                    result.success = False
                    result.errors.append(f"Cannot identify document: {e}")
                    return result

        def failed(message: str) -> DeleteResult:
            result.success = False
            result.errors.append(message)
            try:
                self.integrity.mark_failed(source_hash, source_path, "; ".join(result.errors), collection=collection)
            except Exception as exc:
                result.errors.append(f"FileIntegrity failure-state write failed: {exc}")
            return result

        # Capture exact IDs before any deletion; a hash prefix cannot identify
        # BM25 postings because VectorUpserter generates different chunk IDs.
        try:
            chunk_ids = self.chroma.collection.get(where={"doc_hash": source_hash}, include=[])["ids"]
            if (not isinstance(chunk_ids, list) or not chunk_ids
                    or any(type(value) is not str or not value for value in chunk_ids)):
                raise ValueError("Exact document chunk IDs are unavailable; BM25 cleanup is unverified.")
        except Exception as exc:
            return failed(f"ChromaDB document identity lookup failed: {exc}")

        # Persist invalidation before the first mutation. A partial deletion is
        # never reusable as successful ingestion of this target collection.
        try:
            self.integrity.mark_failed(source_hash, source_path, "Document deletion in progress.", collection=collection)
        except Exception as exc:
            result.success = False
            result.errors.append(f"FileIntegrity deletion-state write failed: {exc}")
            return result

        # Sparse and image failures leave Chroma's exact IDs available for retry.
        try:
            result.bm25_removed = self.bm25.remove_chunks(chunk_ids, collection)
        except Exception as exc:
            return failed(f"BM25 remove failed: {exc}")

        try:
            images = self.images.list_images(collection=collection, doc_hash=source_hash)
            all_images = self.images.list_images()
            for img in images:
                path = img.get("file_path")
                shared_file = (isinstance(path, str) and any(
                    row.get("image_id") != img["image_id"]
                    and isinstance(row.get("file_path"), str)
                    and Path(row["file_path"]).resolve() == Path(path).resolve()
                    for row in all_images))
                if self.images.delete_image(img["image_id"], remove_file=not shared_file):
                    result.images_deleted += 1
                    all_images = [row for row in all_images if row.get("image_id") != img["image_id"]]
        except Exception as exc:
            return failed(f"ImageStorage delete failed: {exc}")

        # Chroma is last among data stores. If its own outcome is ambiguous,
        # keep failed history; do not call an empty-ID retry successful. A new
        # ingestion can reconstruct the target because should_skip is false.
        try:
            result.chunks_deleted = self.chroma.delete_by_metadata({"doc_hash": source_hash})
        except Exception as exc:
            return failed(f"ChromaDB delete failed: {exc}")

        try:
            result.integrity_removed = self.integrity.remove_record(source_hash, collection=collection)
        except Exception as exc:
            return failed(f"FileIntegrity remove failed: {exc}")
        return result

    # ------------------------------------------------------------------
    # get_collection_stats
    # ------------------------------------------------------------------

    def get_collection_stats(
        self, collection: Optional[str] = None
    ) -> CollectionStats:
        """Return aggregate statistics for a collection.

        Args:
            collection: Collection name.  When *None*, stats span
                all collections.

        Returns:
            ``CollectionStats`` dataclass.
        """
        docs = self.list_documents(collection)
        chunk_total = sum(d.chunk_count for d in docs)
        image_total = sum(d.image_count for d in docs)

        return CollectionStats(
            collection=collection,
            document_count=len(docs),
            chunk_count=chunk_total,
            image_count=image_total,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _count_chunks(self, source_hash: str, collection: Optional[str]) -> int:
        """Count chunks in Chroma that belong to *source_hash*."""
        try:
            results = self._vector_collection(collection).get(
                where={"doc_hash": source_hash}, include=[]
            )
            return len(results.get("ids", []))
        except Exception:
            return 0

    def _get_chunk_ids(self, source_hash: str, collection: Optional[str]) -> List[str]:
        """Return chunk IDs from Chroma matching *source_hash*."""
        try:
            results = self._vector_collection(collection).get(
                where={"doc_hash": source_hash}, include=[]
            )
            return results.get("ids", [])
        except Exception:
            return []

    def _vector_collection(self, collection: Optional[str]):
        bound = getattr(self.chroma, "collection_name", None)
        if collection is None:
            raise ValueError("Unscoped history does not identify a vector collection.")
        if isinstance(bound, str) and bound != collection:
            return self.chroma.client.get_collection(name=collection)
        return self.chroma.collection

    def _scoped_images(self, source_hash: str, collection: Optional[str]):
        images = self.images.list_images(collection=collection, doc_hash=source_hash)
        return images if collection is not None else [row for row in images if row.get("collection") is None]

    def _count_images(self, source_hash: str, collection: Optional[str]) -> int:
        """Count images belonging to *source_hash*."""
        try:
            return len(self._scoped_images(source_hash, collection))
        except Exception:
            return 0

    def _get_image_ids(self, source_hash: str, collection: Optional[str]) -> List[str]:
        """Return image IDs belonging to *source_hash*."""
        try:
            imgs = self._scoped_images(source_hash, collection)
            return [img["image_id"] for img in imgs]
        except Exception:
            return []

    def _hash_from_path(self, source_path: str, collection: str) -> Optional[str]:
        """Try to find a source_hash from integrity records by path."""
        try:
            for rec in self.integrity.list_processed(collection):
                if rec["file_path"] == source_path:
                    return rec["file_hash"]
        except Exception:
            pass
        return None
