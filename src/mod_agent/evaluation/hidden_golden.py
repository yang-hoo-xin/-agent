"""Expected-truth isolation for the two Hook Discovery calibration fixtures.

This module is deliberately not a discovery runner.  It binds the natural-language
request and allowlisted corpus before actual execution, then reads a frozen technical
annotation only after an EvidencePack has been committed and strictly rehydrated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evidence.models import EvidencePack

HIDDEN_GOLDEN_CALIBRATION_EVAL_VERSION = "hidden_golden_calibration_eval_v1"
_TECHNICAL_REVIEW_AUTHORITY = (
    "independently_model_reviewed_technical_calibration_annotation"
)
_JUDGMENT_FIELDS = (
    "required_evidence",
    "forbidden_evidence",
    "acceptable_hook_full_identities",
    "forbidden_hook_full_identities",
    "required_missing_evidence",
    "expected_sufficiency",
    "expected_control_action",
)
_FULL_IDENTITY_FIELDS = (
    "assembly_sha256",
    "module_mvid",
    "declaring_type",
    "method_name",
    "metadata_token",
    "signature_blob",
)


class HiddenGoldenCalibrationError(ValueError):
    """Raised when actual/expected isolation or identity binding is invalid."""


@dataclass(frozen=True)
class HiddenGoldenActualInput:
    """Manifest-bound input that is safe to expose to actual discovery."""

    case_identity: str
    request_text: str
    request_sha256: str
    declared_corpus_snapshot_sha256: str
    observed_corpus_snapshot_sha256: str | None
    source_allowlist: tuple[str, ...]
    excluded_source_classes: tuple[str, ...]


def load_hidden_golden_actual_input(
    case_root: str | Path,
    *,
    corpus_root: str | Path | None = None,
) -> HiddenGoldenActualInput:
    """Load only manifest/request facts; never open the annotation."""

    root = Path(case_root)
    manifest = _load_object(root / "corpus_manifest.json")
    case_identity = _required_string(manifest, "case_identity")
    request_spec = _required_object(manifest, "request")
    request_ref = _required_string(request_spec, "ref")
    request_ref_path = PurePosixPath(request_ref)
    if (
        request_ref_path.name != "request.txt"
        or request_ref_path.parent.name != root.name
    ):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_REF_INVALID")
    request_bytes = _canonical_request_bytes((root / "request.txt").read_bytes())
    request_sha256 = _sha256(request_bytes)
    if request_sha256 != _required_string(request_spec, "sha256"):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_HASH_MISMATCH")
    try:
        request_text = request_bytes.decode("utf-8").rstrip("\n")
    except UnicodeDecodeError as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_NOT_UTF8") from exc
    if not request_text.strip():
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_EMPTY")

    scope = _required_object(manifest, "actual_retrieval_scope")
    if scope.get("mode") != "allowlist_only":
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_SOURCE_SCOPE_NOT_ALLOWLIST")
    source_allowlist = _string_tuple(scope, "search_root_allowlist")
    excluded = _string_tuple(scope, "excluded_source_classes")
    if "technical_annotation" not in excluded or "prior_agent_or_rag_outputs" not in excluded:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_EXPECTED_EXCLUSION_MISSING")
    snapshot = _required_object(manifest, "canonical_corpus_snapshot")
    snapshot_allowlist = _string_tuple(snapshot, "search_root_allowlist")
    if snapshot_allowlist != source_allowlist:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_CORPUS_ALLOWLIST_MISMATCH")

    declared_snapshot = _required_string(snapshot, "corpus_snapshot_sha256")
    observed_snapshot: str | None = None
    if corpus_root is not None:
        from .arm_a import RunManifestCollector

        observed_snapshot = RunManifestCollector(corpus_root).canonical_corpus_snapshot(
            source_allowlist
        ).corpus_snapshot_sha256
        if observed_snapshot != declared_snapshot:
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_MISMATCH"
            )

    return HiddenGoldenActualInput(
        case_identity=case_identity,
        request_text=request_text,
        request_sha256=request_sha256,
        declared_corpus_snapshot_sha256=declared_snapshot,
        observed_corpus_snapshot_sha256=observed_snapshot,
        source_allowlist=source_allowlist,
        excluded_source_classes=excluded,
    )


def evaluate_committed_hidden_golden(
    *,
    store: ArtifactStore,
    actual_ref: ArtifactRef,
    actual_input: HiddenGoldenActualInput,
    annotation_path: str | Path,
) -> dict[str, Any]:
    """Compare one committed actual pack after strict rehydration.

    Reading the annotation occurs after Store read, Registry validation, strict
    semantic rehydration, and request binding.  The returned comparison grants no
    Data Readiness, product quality, promotion, or execution verdict.
    """

    if actual_ref.artifact_type != "evidence_pack":
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_REF_TYPE_INVALID")
    if actual_input.observed_corpus_snapshot_sha256 is None:
        raise HiddenGoldenCalibrationError(
            "HIDDEN_GOLDEN_CORPUS_SNAPSHOT_NOT_OBSERVED"
        )
    envelope = store.read(actual_ref)
    payload = envelope.get("data")
    if not isinstance(payload, dict):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_PAYLOAD_INVALID")
    if not EvidencePack.requires_strict_semantic_rehydrate(payload):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_NOT_SEMANTIC")
    try:
        pack = EvidencePack.from_artifact_payload(payload)
    except ValueError as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_REHYDRATE_FAILED") from exc
    if pack.query != actual_input.request_text:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_REQUEST_MISMATCH")
    actual_payload_sha256 = _canonical_sha256(payload)

    # Expected truth becomes visible only after actual is immutable and rebound.
    annotation = _load_object(Path(annotation_path))
    expected = _validated_expected(annotation, actual_input.case_identity)
    actual_sufficiency, actual_action = _actual_decision(pack)
    actual_identities = _actual_hook_identities(pack)
    acceptable_identities = _expected_identities(
        expected, "acceptable_hook_full_identities", "acceptance_scope"
    )
    forbidden_identities = _expected_identities(
        expected, "forbidden_hook_full_identities", "forbidden_scope"
    )
    actual_keys = {_identity_key(value) for value in actual_identities}
    acceptable_keys = {_identity_key(value) for value in acceptable_identities}
    forbidden_hits = sorted(actual_keys & {_identity_key(value) for value in forbidden_identities})

    return {
        "protocol_version": HIDDEN_GOLDEN_CALIBRATION_EVAL_VERSION,
        "protocol_role": "expected_truth_isolation_after_committed_actual",
        "case_identity": actual_input.case_identity,
        "calibration_scope": "calibration_development",
        "blind_or_held_out_claim": False,
        "promotion_claim": False,
        "actual": {
            "artifact_hash": actual_ref.artifact_hash,
            "payload_sha256": actual_payload_sha256,
            "request_sha256": actual_input.request_sha256,
            "corpus_snapshot_sha256": actual_input.observed_corpus_snapshot_sha256,
            "sufficiency": actual_sufficiency,
            "control_action": actual_action,
            "hook_full_identities": actual_identities,
        },
        "expected": {
            "frozen_judgment_hash": annotation["frozen_judgment_hash"],
            "technical_review_authority": annotation["technical_review_authority"],
            "sufficiency": expected["expected_sufficiency"],
            "control_action": expected["expected_control_action"],
            "acceptable_hook_full_identities": acceptable_identities,
            "forbidden_hook_full_identities": forbidden_identities,
        },
        "comparison": {
            "sufficiency_matches": actual_sufficiency
            == expected["expected_sufficiency"],
            "control_action_matches": actual_action
            == expected["expected_control_action"],
            "acceptable_hook_identity_set_matches": actual_keys == acceptable_keys,
            "forbidden_hook_identity_hits": [list(value) for value in forbidden_hits],
        },
        "unscored_expected_fields": [
            "required_evidence",
            "forbidden_evidence",
            "required_missing_evidence",
        ],
        "limitations": [
            "Narrative evidence requirements are not scored without registered actual relationship identities.",
            "This comparison does not re-run discovery or derive expected judgment from physical evidence.",
        ],
        "does_not_grant": [
            "golden_completion_verdict",
            "data_readiness_verdict",
            "product_quality_verdict",
            "promotion",
            "patch_apply_build_or_runtime_authority",
        ],
    }


def _validated_expected(
    annotation: Mapping[str, Any], case_identity: str
) -> dict[str, Any]:
    if annotation.get("case_identity") != case_identity:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_CASE_IDENTITY_MISMATCH")
    if annotation.get("technical_review_authority") != _TECHNICAL_REVIEW_AUTHORITY:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REVIEW_AUTHORITY_INVALID")
    if annotation.get("current_rag_actual_output_accessed") is not False:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_EXPECTED_ISOLATION_INVALID")
    if (
        annotation.get("judgment_hash_protocol")
        != "sha256_of_canonical_json_over_judgment_payload_only"
    ):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_HASH_PROTOCOL_INVALID")
    expected = annotation.get("judgment_payload")
    if not isinstance(expected, dict) or tuple(expected) != _JUDGMENT_FIELDS:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JUDGMENT_SHAPE_INVALID")
    calculated = _canonical_sha256(expected)
    if annotation.get("proposed_judgment_hash") != calculated:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_PROPOSED_HASH_MISMATCH")
    if annotation.get("frozen_judgment_hash") != calculated:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_FROZEN_HASH_MISMATCH")
    if expected.get("expected_sufficiency") not in {
        "sufficient",
        "insufficient",
        "contradictory",
    }:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_SUFFICIENCY_INVALID")
    if expected.get("expected_control_action") not in {"continue", "block"}:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTION_INVALID")
    return expected


def _actual_decision(pack: EvidencePack) -> tuple[str, str]:
    if pack.hook_discovery is not None:
        sufficiency = pack.hook_discovery["sufficiency"]["planning"]["status"]
        action = pack.hook_discovery["planning_action"]
        return str(sufficiency), str(action)
    if pack.agent_discovery is not None:
        return pack.readiness, "continue" if pack.can_generate_patch else "block"
    raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_ACTUAL_SEMANTICS_MISSING")


def _actual_hook_identities(pack: EvidencePack) -> list[dict[str, str]]:
    if pack.hook_discovery is None:
        return []
    result: list[dict[str, str]] = []
    for value in pack.hook_discovery["hook_identities"]:
        if not all(
            isinstance(value.get(field), str) and value.get(field)
            for field in (
                "source_content_hash",
                "module_mvid",
                "declaring_type",
                "method_name",
                "metadata_token",
                "signature_blob",
            )
        ):
            raise HiddenGoldenCalibrationError(
                "HIDDEN_GOLDEN_ACTUAL_FULL_IDENTITY_MISSING"
            )
        result.append(
            {
                "assembly_sha256": str(value["source_content_hash"]),
                "module_mvid": str(value["module_mvid"]),
                "declaring_type": str(value["declaring_type"]),
                "method_name": str(value["method_name"]),
                "metadata_token": str(value["metadata_token"]),
                "signature_blob": str(value["signature_blob"]),
            }
        )
    return sorted(result, key=_identity_key)


def _expected_identities(
    expected: Mapping[str, Any], field: str, scope_field: str
) -> list[dict[str, str]]:
    values = expected.get(field)
    if not isinstance(values, list):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_IDENTITY_LIST_INVALID")
    result: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {*_FULL_IDENTITY_FIELDS, scope_field}:
            raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_FULL_IDENTITY_INVALID")
        identity: dict[str, str] = {}
        for key in _FULL_IDENTITY_FIELDS:
            raw = value.get(key)
            if not isinstance(raw, str) or not raw:
                raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_FULL_IDENTITY_INVALID")
            identity[key] = raw
        result.append(identity)
    return sorted(result, key=_identity_key)


def _identity_key(value: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(value[field] for field in _FULL_IDENTITY_FIELDS)


def _canonical_request_bytes(raw: bytes) -> bytes:
    canonical = raw.replace(b"\r\n", b"\n")
    if b"\r" in canonical:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_REQUEST_LINE_ENDING_INVALID")
    return canonical


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JSON_READ_FAILED") from exc
    if not isinstance(value, dict):
        raise HiddenGoldenCalibrationError("HIDDEN_GOLDEN_JSON_OBJECT_REQUIRED")
    return value


def _required_object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    result = value.get(field)
    if not isinstance(result, dict):
        raise HiddenGoldenCalibrationError(f"HIDDEN_GOLDEN_{field.upper()}_INVALID")
    return result


def _required_string(value: Mapping[str, Any], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise HiddenGoldenCalibrationError(f"HIDDEN_GOLDEN_{field.upper()}_INVALID")
    return result


def _string_tuple(value: Mapping[str, Any], field: str) -> tuple[str, ...]:
    result = value.get(field)
    if not isinstance(result, list) or not all(
        isinstance(item, str) and item for item in result
    ):
        raise HiddenGoldenCalibrationError(f"HIDDEN_GOLDEN_{field.upper()}_INVALID")
    return tuple(result)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()
