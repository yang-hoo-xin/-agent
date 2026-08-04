"""Neutral canonical serialization and hashing for approved actions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_action_json(value: Any) -> bytes:
    """Serialize one action projection using the frozen compact JSON contract."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Action identity contains a non-canonical JSON value.") from exc


def hash_action_identity(
    identity: Mapping[str, Any],
    *,
    expected_hash_domain: str,
) -> str:
    """Hash one identity after verifying its domain-separated contract."""

    if identity.get("hash_domain") != expected_hash_domain:
        raise ValueError("Action identity hash domain changed.")
    return "sha256:" + hashlib.sha256(canonical_action_json(identity)).hexdigest()


def hash_canonical_value(value: Any) -> str:
    """Hash a non-authority canonical projection such as a delta or payload."""

    return "sha256:" + hashlib.sha256(canonical_action_json(value)).hexdigest()
