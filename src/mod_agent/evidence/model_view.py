"""Small model projections of existing API evidence facts, without new authority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

API_EVIDENCE_GUIDANCE = (
    "For API evidence, source_authority describes the bound source: authoritative, supporting or lead. "
    "Missing authority is unknown. Supporting/reference APIs do not by themselves prove the current target contract. "
    "Use the assembly hash, MVID and method identity to distinguish versions; identical filenames are not identical APIs. "
    "Metadata or an interop wrapper does not prove game runtime behavior. These facts grant no edit permission."
)


def api_evidence_model_fields(item: Mapping[str, Any]) -> dict[str, Any]:
    """Retain the original values; do not infer freshness, signatures or semantics."""
    if item.get("source_type") != "decompiled_api":
        return {}
    return {key: item.get(key) for key in (
        "source_authority", "source_hash", "module_mvid", "metadata_token", "signature_blob",
    )}
