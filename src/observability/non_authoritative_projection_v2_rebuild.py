"""Strict serialized boundary for pure Projection V2 rebuilds.

Raw fact and edge collections may be unordered because ``ProjectionViewV2``
owns their canonical ordering.  A complete serialized View follows a separate
strict-read path so malformed or non-canonical View bytes are never repaired by
rebuilding them.

This module accepts strict JSON bytes or trusted pure-data mappings.  Mapping
inputs are not a sandbox for hostile objects: callers must not supply mappings
whose accessors execute capabilities.  The module has no owner, workflow,
storage, file, process, network, or execution dependency.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, TypeAlias

from src.non_authoritative_projection.contracts_v2 import (
    ExplicitEdgeV2,
    OwnerFactV2,
    ProjectionContractError,
    ProjectionViewV2,
)


SerializedCollectionV2: TypeAlias = tuple[Mapping[str, object], ...] | bytes
SerializedViewV2: TypeAlias = Mapping[str, object] | bytes

__all__ = (
    "SerializedCollectionV2",
    "SerializedViewV2",
    "load_canonical_projection_view_v2",
    "rebuild_projection_view_v2",
)


def _reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise ProjectionContractError(
                f"Projection V2 JSON contains a duplicate key: {key}."
            )
        value[key] = item
    return value


def _reject_nonstandard_constant(token: str) -> None:
    raise ProjectionContractError(
        f"Projection V2 JSON contains a non-standard numeric constant: {token}."
    )


def _decode_json_bytes(value: bytes, name: str) -> Any:
    if type(value) is not bytes:
        raise ProjectionContractError(f"{name} must be exact bytes.")
    try:
        text = value.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except ProjectionContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectionContractError(f"{name} is not strict UTF-8 JSON.") from exc


def _mapping_collection(
    value: SerializedCollectionV2,
    name: str,
) -> tuple[Mapping[str, Any], ...]:
    if type(value) is bytes:
        decoded = _decode_json_bytes(value, name)
        if type(decoded) is not list:
            raise ProjectionContractError(f"{name} JSON must be an exact array.")
        items = tuple(decoded)
    elif type(value) is tuple:
        items = value
    else:
        raise ProjectionContractError(
            f"{name} must be an exact tuple of mappings or exact JSON bytes."
        )

    if any(not isinstance(item, Mapping) for item in items):
        raise ProjectionContractError(f"{name} items must be mappings.")
    return tuple(items)


def rebuild_projection_view_v2(
    facts: SerializedCollectionV2,
    edges: SerializedCollectionV2,
) -> ProjectionViewV2:
    """Build one deterministic View from serialized facts and edges only.

    Tuple inputs contain trusted pure-data mappings and are read without
    mutation.  Bytes inputs must each contain one JSON array.  Diagnostics are
    never accepted from callers; the frozen V2 contract derives them from the
    complete supplied facts and edges.
    """

    fact_values = _mapping_collection(facts, "Projection V2 facts")
    edge_values = _mapping_collection(edges, "Projection V2 edges")
    typed_facts = tuple(OwnerFactV2.from_dict(item) for item in fact_values)
    typed_edges = tuple(ExplicitEdgeV2.from_dict(item) for item in edge_values)
    try:
        return ProjectionViewV2.rebuild(typed_facts, typed_edges)
    except ProjectionContractError:
        raise
    except UnicodeError as exc:
        raise ProjectionContractError(
            "Projection V2 serialized text is not canonical UTF-8."
        ) from exc


def load_canonical_projection_view_v2(value: SerializedViewV2) -> ProjectionViewV2:
    """Strictly read an already serialized canonical Projection V2 View.

    Trusted pure-data Mapping inputs retain the V2 contract's exact structural
    checks.  Bytes inputs additionally have to equal the View's canonical
    bytes, rejecting whitespace, encoding, escaping, or other byte-level
    normalization drift.
    """

    original_bytes: bytes | None = None
    if type(value) is bytes:
        original_bytes = value
        decoded = _decode_json_bytes(value, "Projection V2 View")
        if not isinstance(decoded, Mapping):
            raise ProjectionContractError(
                "Projection V2 View JSON must be an exact object."
            )
        mapping: Mapping[str, Any] = decoded
    elif isinstance(value, Mapping):
        mapping = value
    else:
        raise ProjectionContractError(
            "Projection V2 View must be a mapping or exact JSON bytes."
        )

    try:
        view = ProjectionViewV2.from_dict(mapping)
        if original_bytes is not None:
            canonical_bytes = view.canonical_bytes()
    except ProjectionContractError:
        raise
    except UnicodeError as exc:
        raise ProjectionContractError(
            "Projection V2 View text is not canonical UTF-8."
        ) from exc
    if original_bytes is not None:
        if original_bytes != canonical_bytes:
            raise ProjectionContractError(
                "Projection V2 View bytes are non-canonical."
            )
    return view
