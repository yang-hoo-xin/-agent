"""Shared deterministic Evidence and requirement identity helpers."""

from __future__ import annotations

import hashlib
import json

REQUEST_RELATION_CONTRACT_VERSION = "request_relation_identity_v1"


def request_relation_identity(
    *,
    request_sha256: str,
    projection_sha256: str,
    relation_index: int,
) -> str:
    """Derive one stable request-side relation identity without expected facts."""

    payload = {
        "request_sha256": request_sha256,
        "projection_sha256": projection_sha256,
        "relation_index": relation_index,
        "schema_version": REQUEST_RELATION_CONTRACT_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"relation_{digest[:16]}"
