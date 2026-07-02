"""Tests for guarded dashboard destructive operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from src.observability.dashboard.services.data_service import DataService


@dataclass
class _DeleteResult:
    success: bool
    chunks_deleted: int = 0
    bm25_removed: bool = False
    images_deleted: int = 0
    integrity_removed: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class _Decision:
    allowed: bool
    level: str = "confirmed_write"
    reason: str = "test permission decision"
    required_approval: str | None = None


class _AllowingPermissionModel:
    def decide(
        self,
        level: str,
        *,
        explicit_phase: str | None = None,
        human_approved: bool = False,
    ) -> _Decision:
        return _Decision(
            allowed=True,
            level=level,
            reason="test permission allowed",
            required_approval=None,
        )


class _FakeManager:
    def __init__(self) -> None:
        self.delete_calls: list[dict[str, Any]] = []

    def delete_document(
        self,
        source_path: str,
        collection: str,
        *,
        source_hash: str | None = None,
    ) -> _DeleteResult:
        self.delete_calls.append(
            {
                "source_path": source_path,
                "collection": collection,
                "source_hash": source_hash,
            }
        )
        return _DeleteResult(
            success=True,
            chunks_deleted=2,
            bm25_removed=True,
            images_deleted=1,
            integrity_removed=True,
        )


def test_delete_document_is_blocked_by_default_without_touching_stores() -> None:
    service = DataService()

    def fail_if_called(collection: str | None = None) -> None:
        raise AssertionError("_ensure_stores must not run for a blocked delete")

    service._ensure_stores = fail_if_called  # type: ignore[method-assign]

    result = service.delete_document(
        "sample.pdf",
        collection="default",
        source_hash="hash-1",
    )

    assert result.success is False
    assert result.chunks_deleted == 0
    assert result.images_deleted == 0
    assert result.operation_summary["operation"] == "delete_document"
    assert result.operation_summary["status"] == "blocked"
    assert result.operation_summary["permission_level"] == "confirmed_write"
    assert result.operation_summary["confirmed"] is False
    assert result.operation_summary["target"] == {
        "source_path": "sample.pdf",
        "collection": "default",
        "source_hash": "hash-1",
    }
    assert result.errors == ["delete_document requires explicit confirmation."]
    assert service.operation_audit == [result.operation_summary]


def test_reset_all_is_blocked_by_default_without_touching_stores() -> None:
    service = DataService()

    def fail_if_called() -> dict[str, Any]:
        raise AssertionError("_perform_reset_all must not run for a blocked reset")

    service._perform_reset_all = fail_if_called  # type: ignore[method-assign]

    result = service.reset_all()

    assert result["collections_deleted"] == 0
    assert result["bm25_cleared"] is False
    assert result["images_cleared"] is False
    assert result["integrity_cleared"] is False
    assert result["traces_cleared"] is False
    assert result["operation_summary"]["operation"] == "reset_all"
    assert result["operation_summary"]["status"] == "blocked"
    assert result["operation_summary"]["confirmed"] is False
    assert result["errors"] == ["reset_all requires explicit confirmation."]
    assert service.operation_audit == [result["operation_summary"]]


def test_confirmed_enabled_delete_records_operation_summary() -> None:
    service = DataService(
        permission_model=_AllowingPermissionModel(),
        destructive_operations_enabled=True,
    )
    manager = _FakeManager()
    service._manager = manager
    service._ensure_stores = lambda collection=None: None  # type: ignore[method-assign]

    result = service.delete_document(
        "sample.pdf",
        collection="default",
        source_hash="hash-1",
        confirmed=True,
    )

    assert manager.delete_calls == [
        {
            "source_path": "sample.pdf",
            "collection": "default",
            "source_hash": "hash-1",
        }
    ]
    assert result.success is True
    assert result.chunks_deleted == 2
    assert result.bm25_removed is True
    assert result.images_deleted == 1
    assert result.integrity_removed is True
    assert result.errors == []
    assert result.operation_summary["operation"] == "delete_document"
    assert result.operation_summary["status"] == "succeeded"
    assert result.operation_summary["confirmed"] is True
    assert result.operation_summary["allowed"] is True
    assert service.operation_audit == [result.operation_summary]


def test_confirmed_enabled_reset_records_operation_summary() -> None:
    service = DataService(
        permission_model=_AllowingPermissionModel(),
        destructive_operations_enabled=True,
    )

    def reset_summary() -> dict[str, Any]:
        return {
            "collections_deleted": 3,
            "bm25_cleared": True,
            "images_cleared": True,
            "integrity_cleared": True,
            "traces_cleared": True,
            "errors": [],
        }

    service._perform_reset_all = reset_summary  # type: ignore[method-assign]

    result = service.reset_all(confirmed=True)

    assert result["collections_deleted"] == 3
    assert result["errors"] == []
    assert result["operation_summary"]["operation"] == "reset_all"
    assert result["operation_summary"]["status"] == "succeeded"
    assert result["operation_summary"]["confirmed"] is True
    assert result["operation_summary"]["allowed"] is True
    assert service.operation_audit == [result["operation_summary"]]
