from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from src.non_authoritative_projection.contracts import ProjectionContractError
from src.non_authoritative_projection.contracts_v2 import (
    OWNER_FACT_ADMISSION_V2,
    EdgeReporterV2,
    ExplicitEdgeV2,
    OwnerFactV2,
    ProjectionViewV2,
)


ASSET_ROOT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "non_authoritative_projection"
    / "v2_owner_migration"
)
MANIFEST_PATH = ASSET_ROOT / "manifest.json"
MANIFEST_SHA256 = "19ff08b4a590ba28846e869730fa0bf318946b5df1d87641e20bc5206c39d2d3"
GITATTRIBUTES_CANONICAL_BYTES = b"*.json -text\n*.txt -text\n"
GITATTRIBUTES_CANONICAL_SHA256 = (
    "eee31f63511ef7e43e7afe24a41003b895ad633fd32b01fbe82d0e5509544cd5"
)
MANIFEST_SCHEMA_VERSION = "non_authoritative_projection_v2_owner_asset_manifest_v1"
ASSET_SCOPE = "synthetic_unit_test_assets_only_not_historical_or_product_facts"
CANONICAL_FIXTURE_FORMAT = "projection_view_v2_canonical_utf8_plus_terminal_lf"
PAYLOAD_PATH = "shared_revision_payload.txt"
FIXTURE_IDS = (
    "same_revision_different_sequence",
    "cross_run_scope",
)
EXPECTED_ASSET_FILES = {
    ".gitattributes",
    "manifest.json",
    PAYLOAD_PATH,
    "same_revision_different_sequence.json",
    "cross_run_scope.json",
}
MANIFEST_FIELDS = (
    "schema_version",
    "asset_scope",
    "canonical_fixture_format",
    "payload",
    "fixtures",
)
PAYLOAD_FIELDS = ("path", "sha256", "byte_length")
FIXTURE_ENTRY_FIELDS = (
    "fixture_id",
    "fixture_path",
    "fixture_sha256",
    "canonical_projection_sha256",
)
CONTROL_STATE_FIELDS = frozenset(
    {
        "actual",
        "actual16",
        "allowed",
        "allowed_changes",
        "apply",
        "apply_authorized",
        "authority",
        "authority_effect",
        "case_id",
        "claim",
        "claim_impact",
        "corpus_id",
        "execution_disposition",
        "expected_boundary",
        "expected_calls",
        "expected_effects",
        "expected_owner",
        "expected_summary",
        "failure_chain",
        "failure_stage",
        "final_status",
        "first_failure",
        "first_failure_stage",
        "forbidden_changes",
        "fresh_actual_reason",
        "fresh_actual_status",
        "gate",
        "gate_status",
        "incident_relation",
        "invariant_class",
        "next_attempt_authorized",
        "pause",
        "platform_status",
        "product_claim",
        "promotion",
        "promotion_status",
        "projection_integrity",
        "queue",
        "queue_mutation",
        "ready",
        "recovery",
        "repair",
        "repair_required",
        "resume",
        "resume_authorized",
        "retry",
        "runtime",
        "should_pause",
        "should_retry",
        "status",
        "winner",
    }
)


class FixtureAssetError(ValueError):
    """Raised when an owner-local test asset is malformed."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for key, value in pairs:
        if key in selected:
            raise FixtureAssetError(f"Duplicate JSON key: {key}")
        selected[key] = value
    return selected


def _reject_non_json_constant(value: str) -> None:
    raise FixtureAssetError(f"Non-JSON numeric constant: {value}")


def _load_json_object(raw: bytes) -> dict[str, Any]:
    try:
        selected = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise FixtureAssetError("Fixture must be UTF-8 JSON.") from exc
    if type(selected) is not dict:
        raise FixtureAssetError("Fixture root must be an exact JSON object.")
    return selected


def _require_exact_fields(
    value: object,
    fields: tuple[str, ...],
    name: str,
) -> dict[str, Any]:
    if type(value) is not dict or tuple(value) != fields:
        raise FixtureAssetError(f"{name} fields or field order changed.")
    return value


def _require_sha256(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FixtureAssetError(f"{name} must be a lowercase SHA-256 value.")
    return value


def _parse_manifest(value: object) -> dict[str, Any]:
    manifest = _require_exact_fields(value, MANIFEST_FIELDS, "manifest")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise FixtureAssetError("Manifest schema version changed.")
    if manifest["asset_scope"] != ASSET_SCOPE:
        raise FixtureAssetError("Manifest asset scope changed.")
    if manifest["canonical_fixture_format"] != CANONICAL_FIXTURE_FORMAT:
        raise FixtureAssetError("Manifest canonical fixture format changed.")

    payload = _require_exact_fields(manifest["payload"], PAYLOAD_FIELDS, "payload")
    if payload["path"] != PAYLOAD_PATH:
        raise FixtureAssetError("Manifest payload path changed.")
    _require_sha256(payload["sha256"], "payload.sha256")
    if type(payload["byte_length"]) is not int or payload["byte_length"] < 0:
        raise FixtureAssetError("payload.byte_length must be an exact integer >= 0.")

    fixtures = manifest["fixtures"]
    if type(fixtures) is not list:
        raise FixtureAssetError("manifest.fixtures must be an exact array.")
    parsed_entries: list[dict[str, Any]] = []
    for entry in fixtures:
        selected = _require_exact_fields(
            entry,
            FIXTURE_ENTRY_FIELDS,
            "fixture entry",
        )
        if type(selected["fixture_id"]) is not str:
            raise FixtureAssetError("fixture_id must be an exact string.")
        if type(selected["fixture_path"]) is not str:
            raise FixtureAssetError("fixture_path must be an exact string.")
        if Path(selected["fixture_path"]).name != selected["fixture_path"]:
            raise FixtureAssetError("fixture_path must remain inside the asset root.")
        _require_sha256(selected["fixture_sha256"], "fixture_sha256")
        _require_sha256(
            selected["canonical_projection_sha256"],
            "canonical_projection_sha256",
        )
        parsed_entries.append(selected)
    if tuple(entry["fixture_id"] for entry in parsed_entries) != FIXTURE_IDS:
        raise FixtureAssetError("Manifest fixture identities or order changed.")
    if len({entry["fixture_path"] for entry in parsed_entries}) != len(
        parsed_entries
    ):
        raise FixtureAssetError("Manifest contains a duplicate fixture path.")
    return manifest


def _load_manifest() -> dict[str, Any]:
    raw = MANIFEST_PATH.read_bytes()
    if _sha256(raw) != MANIFEST_SHA256:
        raise FixtureAssetError("Manifest raw bytes changed.")
    return _parse_manifest(_load_json_object(raw))


def _fixture_entry(
    manifest: dict[str, Any],
    fixture_id: str,
) -> dict[str, Any]:
    entries = [
        entry for entry in manifest["fixtures"] if entry["fixture_id"] == fixture_id
    ]
    if len(entries) != 1:
        raise FixtureAssetError("Fixture identity must resolve exactly once.")
    return entries[0]


def _load_view(fixture_id: str) -> ProjectionViewV2:
    manifest = _load_manifest()
    entry = _fixture_entry(manifest, fixture_id)
    raw = (ASSET_ROOT / entry["fixture_path"]).read_bytes()
    if _sha256(raw) != entry["fixture_sha256"]:
        raise FixtureAssetError("Fixture raw bytes do not match the manifest.")
    view = ProjectionViewV2.from_dict(_load_json_object(raw))
    if raw != view.canonical_bytes() + b"\n":
        raise FixtureAssetError("Fixture bytes are not canonical V2 bytes plus LF.")
    if view.canonical_sha256() != entry["canonical_projection_sha256"]:
        raise FixtureAssetError("Fixture canonical hash does not match the manifest.")
    return view


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def _product_facts(view: ProjectionViewV2) -> tuple[OwnerFactV2, ...]:
    return tuple(
        fact for fact in view.facts if fact.ref.owner == "product_execution"
    )


def _artifact_fact(view: ProjectionViewV2) -> OwnerFactV2:
    selected = tuple(fact for fact in view.facts if fact.ref.owner == "artifact_store")
    assert len(selected) == 1
    return selected[0]


def _product_fact_with_scope(
    template: OwnerFactV2,
    *,
    run_id: str,
    request_id: str,
) -> OwnerFactV2:
    serialized = template.to_dict()
    serialized["fact"]["run_id"] = run_id
    serialized["fact"]["request_id"] = request_id
    return OwnerFactV2.from_dict(serialized)


def test_owner_asset_manifest_raw_and_canonical_hashes_are_content_bound() -> None:
    manifest_raw = MANIFEST_PATH.read_bytes()
    manifest = _load_manifest()

    assert _sha256(manifest_raw) == MANIFEST_SHA256
    assert _load_manifest() == manifest
    manifest_roundtrip = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    assert manifest_roundtrip == manifest_raw
    assert _sha256(manifest_roundtrip) == MANIFEST_SHA256
    assert {path.name for path in ASSET_ROOT.iterdir()} == EXPECTED_ASSET_FILES

    attributes_raw = (ASSET_ROOT / ".gitattributes").read_bytes()
    assert attributes_raw in {
        GITATTRIBUTES_CANONICAL_BYTES,
        GITATTRIBUTES_CANONICAL_BYTES.replace(b"\n", b"\r\n"),
    }
    attributes_canonical = attributes_raw.replace(b"\r\n", b"\n")
    assert attributes_canonical == GITATTRIBUTES_CANONICAL_BYTES
    assert _sha256(attributes_canonical) == GITATTRIBUTES_CANONICAL_SHA256

    payload_raw = (ASSET_ROOT / manifest["payload"]["path"]).read_bytes()
    assert len(payload_raw) == manifest["payload"]["byte_length"]
    assert _sha256(payload_raw) == manifest["payload"]["sha256"]
    assert payload_raw.decode("utf-8").encode("utf-8") == payload_raw
    assert payload_raw == (
        b"Synthetic bytes for non-authoritative Projection V2 owner-local "
        b"unit-test assets only; not historical evidence or a product fact.\n"
    )

    assert OWNER_FACT_ADMISSION_V2 == (
        (
            "artifact_store",
            "artifact_revision_v1",
            "1.0",
            "unavailable",
            "unavailable",
        ),
        (
            "product_execution",
            "product_execution_output_v1",
            "1.0",
            "product_execution_result",
            "required",
        ),
    )
    admitted_pairs = {(row[0], row[1]) for row in OWNER_FACT_ADMISSION_V2}
    expected_payload_path = (
        (ASSET_ROOT / manifest["payload"]["path"])
        .relative_to(Path(__file__).resolve().parents[2])
        .as_posix()
    )
    for fixture_id in FIXTURE_IDS:
        entry = _fixture_entry(manifest, fixture_id)
        raw = (ASSET_ROOT / entry["fixture_path"]).read_bytes()
        view = _load_view(fixture_id)
        assert _sha256(raw) == entry["fixture_sha256"]
        assert raw == view.canonical_bytes() + b"\n"
        assert view.canonical_sha256() == entry["canonical_projection_sha256"]
        roundtripped = ProjectionViewV2.from_dict(view.to_dict())
        assert roundtripped == view
        assert roundtripped.canonical_bytes() == view.canonical_bytes()
        assert (
            roundtripped.canonical_sha256()
            == entry["canonical_projection_sha256"]
        )
        assert view.diagnostics == ()
        assert {edge.relation for edge in view.edges} == {"references"}
        assert {
            (ref.owner, ref.fact_type)
            for edge in view.edges
            for ref in (edge.source, edge.target, edge.reporter.fact)
        }.issubset(admitted_pairs)
        assert {
            (fact.ref.owner, fact.ref.fact_type) for fact in view.facts
        }.issubset(admitted_pairs)
        assert {
            fact.ref.artifact_ref.path for fact in view.facts
        } == {expected_payload_path}
        assert {
            fact.ref.artifact_ref.artifact_hash for fact in view.facts
        } == {manifest["payload"]["sha256"]}
        assert {
            fact.payload_sha256 for fact in view.facts
        } == {manifest["payload"]["sha256"]}
        assert {fact.payload_schema_version for fact in view.facts} == {"1.0"}
        assert {
            edge.reporter.payload_sha256 for edge in view.edges
        } == {manifest["payload"]["sha256"]}
        assert _all_keys(view.to_dict()).isdisjoint(CONTROL_STATE_FIELDS)
    assert _all_keys(manifest).isdisjoint(CONTROL_STATE_FIELDS)


def test_same_revision_different_sequence_retains_two_owner_occurrences() -> None:
    view = _load_view("same_revision_different_sequence")
    product_facts = _product_facts(view)
    revision = _artifact_fact(view)

    assert len(product_facts) == 2
    assert {fact.ref.run_id for fact in product_facts} == {
        "run_v2_owner_asset_same_revision_001"
    }
    assert {fact.ref.request_id for fact in product_facts} == {
        "request_v2_owner_asset_same_revision_001"
    }
    assert {fact.ref.owner_sequence for fact in product_facts} == {4, 5}
    assert len({fact.ref for fact in product_facts}) == 2
    assert {
        fact.ref.artifact_ref for fact in product_facts
    } == {revision.ref.artifact_ref}
    assert {edge.source for edge in view.edges} == {
        fact.ref for fact in product_facts
    }
    assert {edge.target for edge in view.edges} == {revision.ref}
    assert all(edge.reporter.fact == edge.source for edge in view.edges)
    assert all(
        edge.reporter.owner_sequence == edge.source.owner_sequence
        for edge in view.edges
    )


def test_equal_sequence_is_distinct_across_exact_run_and_request_scope() -> None:
    view = _load_view("cross_run_scope")
    product_facts = _product_facts(view)
    revision = _artifact_fact(view)

    assert len(product_facts) == 2
    assert {fact.ref.owner_sequence for fact in product_facts} == {4}
    assert {
        (fact.ref.run_id, fact.ref.request_id) for fact in product_facts
    } == {
        ("run_v2_owner_asset_scope_001", "request_v2_owner_asset_scope_001"),
        ("run_v2_owner_asset_scope_002", "request_v2_owner_asset_scope_002"),
    }
    assert len({fact.ref for fact in product_facts}) == 2
    assert {
        fact.ref.artifact_ref for fact in product_facts
    } == {revision.ref.artifact_ref}
    assert {edge.source for edge in view.edges} == {
        fact.ref for fact in product_facts
    }
    assert {edge.target for edge in view.edges} == {revision.ref}

    template = product_facts[0]
    same_run = " run_v2_owner_asset_memory_shared_001 "
    same_run_facts = (
        _product_fact_with_scope(
            template,
            run_id=same_run,
            request_id="request_v2_owner_asset_memory_001",
        ),
        _product_fact_with_scope(
            template,
            run_id=same_run,
            request_id="request_v2_owner_asset_memory_002",
        ),
    )
    same_run_view = ProjectionViewV2.rebuild((revision, *same_run_facts), ())
    same_run_product_facts = _product_facts(same_run_view)
    assert {fact.ref.run_id for fact in same_run_product_facts} == {same_run}
    assert {fact.ref.request_id for fact in same_run_product_facts} == {
        "request_v2_owner_asset_memory_001",
        "request_v2_owner_asset_memory_002",
    }
    assert {fact.ref.owner_sequence for fact in same_run_product_facts} == {4}
    assert {
        fact.ref.artifact_ref for fact in same_run_product_facts
    } == {revision.ref.artifact_ref}
    assert len({fact.ref for fact in same_run_product_facts}) == 2

    same_request = " request_v2_owner_asset_memory_shared_001 "
    same_request_facts = (
        _product_fact_with_scope(
            template,
            run_id="run_v2_owner_asset_memory_001",
            request_id=same_request,
        ),
        _product_fact_with_scope(
            template,
            run_id="run_v2_owner_asset_memory_002",
            request_id=same_request,
        ),
    )
    same_request_view = ProjectionViewV2.rebuild(
        (revision, *same_request_facts),
        (),
    )
    same_request_product_facts = _product_facts(same_request_view)
    assert {fact.ref.run_id for fact in same_request_product_facts} == {
        "run_v2_owner_asset_memory_001",
        "run_v2_owner_asset_memory_002",
    }
    assert {
        fact.ref.request_id for fact in same_request_product_facts
    } == {same_request}
    assert {fact.ref.owner_sequence for fact in same_request_product_facts} == {4}
    assert {
        fact.ref.artifact_ref for fact in same_request_product_facts
    } == {revision.ref.artifact_ref}
    assert len({fact.ref for fact in same_request_product_facts}) == 2

    for scoped_view in (same_run_view, same_request_view):
        roundtripped = ProjectionViewV2.from_dict(scoped_view.to_dict())
        assert roundtripped == scoped_view
        assert roundtripped.canonical_bytes() == scoped_view.canonical_bytes()


def test_raw_json_loader_rejects_duplicate_keys_before_v2_parsing() -> None:
    raw = (
        ASSET_ROOT / "same_revision_different_sequence.json"
    ).read_bytes()
    duplicated = raw.replace(
        b'{"schema_version":"2"',
        b'{"schema_version":"2","schema_version":"2"',
        1,
    )

    with pytest.raises(FixtureAssetError, match="Duplicate JSON key"):
        _load_json_object(duplicated)


def test_manifest_rejects_unknown_reordered_and_duplicate_entries() -> None:
    manifest = _load_manifest()

    unknown = copy.deepcopy(manifest)
    unknown["status"] = "not_admitted"
    with pytest.raises(FixtureAssetError, match="fields or field order"):
        _parse_manifest(unknown)

    reordered = {
        "asset_scope": manifest["asset_scope"],
        "schema_version": manifest["schema_version"],
        "canonical_fixture_format": manifest["canonical_fixture_format"],
        "payload": manifest["payload"],
        "fixtures": manifest["fixtures"],
    }
    with pytest.raises(FixtureAssetError, match="fields or field order"):
        _parse_manifest(reordered)

    duplicate = copy.deepcopy(manifest)
    duplicate["fixtures"].append(copy.deepcopy(duplicate["fixtures"][0]))
    with pytest.raises(FixtureAssetError, match="identities or order"):
        _parse_manifest(duplicate)


def test_v2_fixture_rejects_unknown_reordered_and_noncanonical_fields() -> None:
    serialized = _load_view("same_revision_different_sequence").to_dict()

    unknown = copy.deepcopy(serialized)
    unknown["facts"][0]["fact"]["artifact_ref"]["unknown"] = None
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV2.from_dict(unknown)

    reordered = copy.deepcopy(serialized)
    fact = reordered["facts"][1]["fact"]
    reordered["facts"][1]["fact"] = {
        "fact_type": fact["fact_type"],
        "owner": fact["owner"],
        "run_id": fact["run_id"],
        "request_id": fact["request_id"],
        "owner_sequence": fact["owner_sequence"],
        "artifact_ref": fact["artifact_ref"],
    }
    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV2.from_dict(reordered)

    noncanonical_facts = copy.deepcopy(serialized)
    noncanonical_facts["facts"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV2.from_dict(noncanonical_facts)

    noncanonical_edges = copy.deepcopy(serialized)
    noncanonical_edges["edges"].reverse()
    with pytest.raises(ProjectionContractError, match="serialization order"):
        ProjectionViewV2.from_dict(noncanonical_edges)


def test_v2_fixture_rejects_duplicate_identity_edge_and_diagnostic() -> None:
    view = _load_view("same_revision_different_sequence")

    duplicate_fact = view.to_dict()
    duplicate_fact["facts"].append(copy.deepcopy(duplicate_fact["facts"][0]))
    with pytest.raises(ProjectionContractError, match="duplicate complete fact identity"):
        ProjectionViewV2.from_dict(duplicate_fact)

    duplicate_edge = view.to_dict()
    duplicate_edge["edges"].append(copy.deepcopy(duplicate_edge["edges"][0]))
    with pytest.raises(ProjectionContractError, match="duplicate edge"):
        ProjectionViewV2.from_dict(duplicate_edge)

    mismatch_edge = copy.deepcopy(view.to_dict()["edges"][0])
    mismatch_edge["reporter"]["owner_sequence"] += 1
    mismatch = ProjectionViewV2.rebuild(
        view.facts,
        (ExplicitEdgeV2.from_dict(mismatch_edge),),
    )
    assert [item.code for item in mismatch.diagnostics] == [
        "reporter_owner_sequence_mismatch"
    ]
    duplicate_diagnostic = mismatch.to_dict()
    duplicate_diagnostic["diagnostics"].append(
        copy.deepcopy(duplicate_diagnostic["diagnostics"][0])
    )
    with pytest.raises(ProjectionContractError, match="duplicate diagnostic"):
        ProjectionViewV2.from_dict(duplicate_diagnostic)


def test_v2_fixture_rejects_one_scope_sequence_bound_to_two_artifacts() -> None:
    serialized = _load_view("same_revision_different_sequence").to_dict()
    drifted = copy.deepcopy(serialized["facts"][1])
    drifted["fact"]["artifact_ref"]["path"] = (
        "tests/fixtures/non_authoritative_projection/v2_owner_migration/"
        "drifted_payload.txt"
    )
    drifted["fact"]["artifact_ref"]["artifact_hash"] = "0" * 64
    drifted["payload_sha256"] = "0" * 64
    serialized["facts"].append(drifted)

    with pytest.raises(
        ProjectionContractError,
        match="maps to multiple Artifact identities",
    ):
        ProjectionViewV2.from_dict(serialized)


def test_artifact_store_revision_cannot_report_or_source_an_edge() -> None:
    view = _load_view("same_revision_different_sequence")
    edge = view.to_dict()["edges"][0]
    revision_ref = copy.deepcopy(edge["target"])

    reporter = copy.deepcopy(edge["reporter"])
    reporter["fact"] = revision_ref
    with pytest.raises(ProjectionContractError, match="cannot report without"):
        EdgeReporterV2.from_dict(reporter)

    artifact_source = copy.deepcopy(edge)
    artifact_source["source"] = revision_ref
    with pytest.raises(
        ProjectionContractError,
        match="must equal its source endpoint",
    ):
        ExplicitEdgeV2.from_dict(artifact_source)


@pytest.mark.parametrize("control_field", sorted(CONTROL_STATE_FIELDS))
def test_v2_fixture_rejects_control_state_fields(control_field: str) -> None:
    serialized = _load_view("cross_run_scope").to_dict()
    serialized[control_field] = None

    with pytest.raises(ProjectionContractError, match="fields or field order"):
        ProjectionViewV2.from_dict(serialized)
