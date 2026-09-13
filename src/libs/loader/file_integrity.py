"""File integrity checker for incremental ingestion.

This module provides SHA256-based file integrity tracking to enable incremental
ingestion. Files that have been successfully processed can be skipped on
subsequent ingestion runs.

Design Principles:
- Idempotent: Multiple ingestion runs of the same file are safe
- Persistent: SQLite-backed storage survives process restarts
- Concurrent: WAL mode enables concurrent read/write operations
- Graceful: Failed ingestions are tracked but don't block retries
"""

import hashlib
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileIntegrityChecker(ABC):
    """Abstract base class for file integrity checking.
    
    Implementations track which files have been successfully processed
    to enable incremental ingestion.
    """
    
    @abstractmethod
    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file.
        
        Args:
            file_path: Path to the file to hash.
            
        Returns:
            Hexadecimal SHA256 hash string (64 characters).
            
        Raises:
            FileNotFoundError: If file does not exist.
            IOError: If path is not a file or cannot be read.
        """
        pass
    
    @abstractmethod
    def should_skip(self, file_hash: str, collection: Optional[str] = None) -> bool:
        """Check if file should be skipped based on hash.
        
        Args:
            file_hash: SHA256 hash of the file.
            
        Returns:
            True if file has been successfully processed before, False otherwise.
        """
        pass
    
    @abstractmethod
    def mark_success(
        self, 
        file_hash: str, 
        file_path: str, 
        collection: Optional[str] = None
    ) -> None:
        """Mark file as successfully processed.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            collection: Optional collection/namespace identifier.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        pass
    
    @abstractmethod
    def mark_failed(
        self, 
        file_hash: str, 
        file_path: str, 
        error_msg: str,
        collection: Optional[str] = None
    ) -> None:
        """Mark file processing as failed.
        
        Failed files are tracked but not skipped on subsequent runs,
        allowing retries.
        
        Args:
            file_hash: SHA256 hash of the file.
            file_path: Original file path (for tracking).
            error_msg: Error message describing the failure.
            
        Raises:
            RuntimeError: If database operation fails.
        """
        pass

    @abstractmethod
    def remove_record(self, file_hash: str, collection: Optional[str] = None) -> bool:
        """Remove an ingestion record by its file hash.

        Args:
            file_hash: SHA256 hash identifying the record.

        Returns:
            True if a record was deleted, False if not found.
        """
        pass

    @abstractmethod
    def list_processed(
        self, collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List successfully processed files.

        Args:
            collection: Optional collection filter.  When *None* all
                successful records are returned.

        Returns:
            List of dicts with keys: file_hash, file_path, collection,
            processed_at, updated_at.
        """
        pass


class SQLiteIntegrityChecker(FileIntegrityChecker):
    """SQLite-backed file integrity checker.
    
    Stores ingestion history in a SQLite database with WAL mode for
    concurrent access.
    
    Database Schema:
        ingestion_history (
            file_hash TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL,  -- 'success' or 'failed'
            collection TEXT,
            error_msg TEXT,
            processed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    
    Args:
        db_path: Path to SQLite database file (will be created if needed).
    
    Raises:
        sqlite3.DatabaseError: If database file is corrupted.
    """
    
    def __init__(self, db_path: str):
        """Initialize checker and create database if needed.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._conn = None
        self._ensure_database()
    
    def close(self) -> None:
        """Close database connection if open."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __del__(self):
        """Cleanup: close connection on deletion."""
        self.close()
    
    def _ensure_database(self) -> None:
        """Atomically preserve legacy rows while making collection part of identity.

        NULL is the legacy unscoped identity, distinct from both an empty string
        and every named collection. No historical collection is invented.
        """
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            columns = conn.execute("PRAGMA table_info(ingestion_history)").fetchall()
            names = {"file_hash", "file_path", "status", "collection", "error_msg", "processed_at", "updated_at"}
            if columns and {row[1] for row in columns} != names:
                raise RuntimeError("Unsupported ingestion_history schema; existing data was preserved.")
            legacy = columns and [row[1] for row in columns if row[5]] == ["file_hash"]
            if legacy:
                conn.execute("ALTER TABLE ingestion_history RENAME TO ingestion_history_before_collection_scope")
            if not columns or legacy:
                conn.execute("""
                    CREATE TABLE ingestion_history (
                        file_hash TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        status TEXT NOT NULL,
                        collection TEXT,
                        error_msg TEXT,
                        processed_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
            if legacy:
                conn.execute("""
                    INSERT INTO ingestion_history
                        (file_hash, file_path, status, collection, error_msg, processed_at, updated_at)
                    SELECT file_hash, file_path, status, collection, error_msg, processed_at, updated_at
                    FROM ingestion_history_before_collection_scope
                """)
                conn.execute("DROP TABLE ingestion_history_before_collection_scope")
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_history_scope
                ON ingestion_history(file_hash, collection IS NULL, IFNULL(collection, ''))
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON ingestion_history(status)")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _validate_collection(collection: Optional[str]) -> None:
        if collection is not None and type(collection) is not str:
            raise TypeError("collection must be a string or None.")

    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA256 hash of file using chunked reading.
        
        Uses 64KB chunks to handle large files without loading entire
        file into memory.
        
        Args:
            file_path: Path to the file to hash.
            
        Returns:
            Hexadecimal SHA256 hash string (64 characters).
            
        Raises:
            FileNotFoundError: If file does not exist.
            IOError: If path is not a file or cannot be read.
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if not path.is_file():
            raise IOError(f"Path is not a file: {file_path}")
        
        # Compute hash using chunked reading
        sha256_hash = hashlib.sha256()
        
        try:
            with open(file_path, "rb") as f:
                # Read in 64KB chunks
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(chunk)
        except Exception as e:
            raise IOError(f"Failed to read file {file_path}: {e}")
        
        return sha256_hash.hexdigest()
    
    def should_skip(self, file_hash: str, collection: Optional[str] = None) -> bool:
        """Skip only a success for this exact collection; None is unscoped."""
        self._validate_collection(collection)
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT status FROM ingestion_history WHERE file_hash = ? AND collection IS ?",
                (file_hash, collection),
            ).fetchone()
        finally:
            conn.close()
        return row is not None and row[0] == "success"

    def mark_success(self, file_hash: str, file_path: str, collection: Optional[str] = None) -> None:
        """Mark success only in the supplied scope, retaining its first timestamp."""
        self._mark(file_hash, file_path, collection, status="success", error_msg=None)

    def mark_failed(self, file_hash: str, file_path: str, error_msg: str,
                    collection: Optional[str] = None) -> None:
        """A failed target ingestion never changes another collection's success."""
        self._mark(file_hash, file_path, collection, status="failed", error_msg=error_msg)

    def _mark(self, file_hash: str, file_path: str, collection: Optional[str],
              *, status: str, error_msg: Optional[str]) -> None:
        self._validate_collection(collection)
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT processed_at FROM ingestion_history WHERE file_hash = ? AND collection IS ?",
                (file_hash, collection),
            ).fetchone()
            if row is None:
                conn.execute("""
                    INSERT INTO ingestion_history
                    (file_hash, file_path, status, collection, error_msg, processed_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (file_hash, file_path, status, collection, error_msg, now, now))
            else:
                conn.execute("""
                    UPDATE ingestion_history SET file_path = ?, status = ?, error_msg = ?, updated_at = ?
                    WHERE file_hash = ? AND collection IS ?
                """, (file_path, status, error_msg, now, file_hash, collection))
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise RuntimeError(f"Failed to mark {status} for {file_path}: {exc}") from exc
        finally:
            conn.close()

    def remove_record(self, file_hash: str, collection: Optional[str] = None) -> bool:
        """Delete this exact scope only; omitted collection never means all."""
        self._validate_collection(collection)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM ingestion_history WHERE file_hash = ? AND collection IS ?",
                (file_hash, collection),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise RuntimeError(f"Failed to remove record {file_hash}: {exc}") from exc
        finally:
            conn.close()

    def list_processed(
        self, collection: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List successfully processed files.

        Args:
            collection: Optional collection filter.

        Returns:
            List of dicts with keys: file_hash, file_path, collection,
            processed_at, updated_at.
        """
        self._validate_collection(collection)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            query = (
                "SELECT file_hash, file_path, collection, processed_at, updated_at "
                "FROM ingestion_history WHERE status = 'success'"
            )
            params: list[str] = []
            if collection is not None:
                query += " AND collection = ?"
                params.append(collection)
            query += " ORDER BY processed_at ASC"

            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
