"""No-write admission for verification-only Build continuation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.mod_agent.artifacts import (
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    StaleArtifactError,
)


VERIFICATION_ONLY_INPUT_EXECUTION_MODE = "verification_only"
VERIFICATION_ONLY_HANDOFF_BLOCKER = (
    "VERIFICATION_ONLY_FRESH_LINEAGE_HANDOFF_UNSUPPORTED"
)


@dataclass(frozen=True)
class VerificationOnlyContinuationInput:
    """Bind one exact FeatureSpec and EvidencePack to a Build-only entry."""

    feature_spec_ref: ArtifactRef
    evidence_pack_ref: ArtifactRef


def preflight_verification_only_continuation(
    artifact_store: ArtifactStore,
    continuation: VerificationOnlyContinuationInput,
    *,
    run_id: str,
    request_id: str,
    user_request: str,
    target_mod: str | None,
) -> dict[str, Any]:
    """Validate a no-mutation Build continuation without performing writes."""

    blockers: list[dict[str, str]] = []
    feature_ref = continuation.feature_spec_ref
    evidence_ref = continuation.evidence_pack_ref
    feature_envelope: dict[str, Any] | None = None
    evidence_envelope: dict[str, Any] | None = None

    if not run_id:
        _block(blockers, "VERIFICATION_RUN_ID_MISSING", "run_id must be non-empty.")
    if not request_id:
        _block(
            blockers,
            "VERIFICATION_REQUEST_ID_MISSING",
            "request_id must be non-empty.",
        )
    if feature_ref.artifact_type != "feature_spec":
        _block(
            blockers,
            "VERIFICATION_FEATURE_SPEC_ROLE_INVALID",
            "The FeatureSpec reference has the wrong artifact_type.",
        )
    if evidence_ref.artifact_type != "evidence_pack":
        _block(
            blockers,
            "VERIFICATION_EVIDENCE_PACK_ROLE_INVALID",
            "The EvidencePack reference has the wrong artifact_type.",
        )
    if feature_ref.feature_id != evidence_ref.feature_id:
        _block(
            blockers,
            "VERIFICATION_FEATURE_ID_MISMATCH",
            "FeatureSpec and EvidencePack feature_id values disagree.",
        )

    if not blockers:
        try:
            feature_envelope = artifact_store.read_for_stage(
                feature_ref,
                consumer_stage="build",
            )
            evidence_envelope = artifact_store.read_for_stage(
                evidence_ref,
                consumer_stage="build",
            )
        except (ArtifactStoreError, StaleArtifactError) as exc:
            _block(
                blockers,
                "VERIFICATION_ARTIFACT_INVALID",
                f"Verification input failed ArtifactStore validation: {exc}",
            )
    if feature_envelope is not None:
        _validate_latest_ref(artifact_store, feature_ref, blockers)
    if evidence_envelope is not None:
        _validate_latest_ref(artifact_store, evidence_ref, blockers)

    source_report: dict[str, Any] = {
        "root": None,
        "read_only": None,
        "files": [],
        "all_files_verified": False,
    }
    if feature_envelope is not None and evidence_envelope is not None:
        feature_data = feature_envelope["data"]
        evidence_data = evidence_envelope["data"]
        _validate_feature_identity(
            blockers,
            feature_ref=feature_ref,
            feature_envelope=feature_envelope,
            user_request=user_request,
            target_mod=target_mod,
        )
        _validate_evidence_identity(
            blockers,
            feature_ref=feature_ref,
            evidence_ref=evidence_ref,
            evidence_envelope=evidence_envelope,
        )
        source_report = _validate_source_lineage(
            blockers,
            feature_data.get("source_lineage"),
        )
        if evidence_data.get("can_generate_patch") is not False:
            _block(
                blockers,
                "VERIFICATION_PATCH_DISPOSITION_INVALID",
                "Verification-only admission requires can_generate_patch=false.",
            )
        if evidence_data.get("authoritative_for_patch") is not False:
            _block(
                blockers,
                "VERIFICATION_PATCH_AUTHORITY_INVALID",
                "Verification-only admission requires authoritative_for_patch=false.",
            )
        if evidence_data.get("readiness") not in {"partial", "sufficient"}:
            _block(
                blockers,
                "VERIFICATION_EVIDENCE_READINESS_INVALID",
                "EvidencePack readiness does not support a verification continuation.",
            )
        payload_blockers = evidence_data.get("blockers")
        envelope_blockers = evidence_envelope.get("blockers")
        if payload_blockers != envelope_blockers:
            _block(
                blockers,
                "VERIFICATION_BLOCKER_PROVENANCE_MISMATCH",
                "EvidencePack payload and envelope blockers disagree.",
            )
        blocker_codes = {
            item.get("code")
            for item in payload_blockers or []
            if isinstance(item, Mapping)
        }
        if blocker_codes != {VERIFICATION_ONLY_HANDOFF_BLOCKER}:
            _block(
                blockers,
                "VERIFICATION_HANDOFF_DISPOSITION_INVALID",
                "EvidencePack does not contain only the reviewed "
                "verification-only handoff blocker.",
            )
        if evidence_data.get("trace_refs") != evidence_envelope.get("trace_refs"):
            _block(
                blockers,
                "VERIFICATION_TRACE_PROVENANCE_MISMATCH",
                "EvidencePack payload and envelope trace_refs disagree.",
            )

    projection: dict[str, Any] = {
        "mode": VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
        "status": "blocked" if blockers else "ready_for_build_authorization",
        "run_id": run_id,
        "request_id": request_id,
        "feature_id": feature_ref.feature_id,
        "feature_spec": _ref_projection(feature_ref),
        "evidence_pack": _ref_projection(evidence_ref),
        "source_lineage": source_report,
        "blockers": blockers,
        "writes_performed": False,
        "artifact_writes_performed": False,
        "build_invoked": False,
        "runtime_invoked": False,
    }
    projection["projection_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return projection


def verification_only_lineage_payload(
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the BuildResult lineage binding for one admitted preflight."""

    return {
        "preflight_hash": preflight["projection_hash"],
        "feature_spec": dict(preflight["feature_spec"]),
        "evidence_pack": dict(preflight["evidence_pack"]),
        "source_root": preflight["source_lineage"]["root"],
        "source_files": [
            {
                "relative_path": item["relative_path"],
                "sha256": item["expected_sha256"],
            }
            for item in preflight["source_lineage"]["files"]
        ],
    }


def validate_verification_only_build_result(
    build_payload: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Validate that BuildProfile consumed an isolated copy of admitted source."""

    blockers: list[dict[str, str]] = []
    profile = build_payload.get("build_profile")
    if not isinstance(profile, Mapping):
        _block(
            blockers,
            "VERIFICATION_BUILD_PROFILE_MISSING",
            "BuildResult does not preserve its BuildProfile.",
        )
        return blockers
    working_value = profile.get("working_directory")
    if not isinstance(working_value, str) or not Path(working_value).is_absolute():
        _block(
            blockers,
            "VERIFICATION_BUILD_WORKING_DIRECTORY_INVALID",
            "BuildProfile working_directory must be an absolute path.",
        )
        return blockers
    working_directory = Path(working_value).resolve()
    source_root = Path(str(preflight["source_lineage"]["root"])).resolve()
    try:
        working_directory.relative_to(source_root)
    except ValueError:
        pass
    else:
        _block(
            blockers,
            "VERIFICATION_BUILD_SOURCE_NOT_ISOLATED",
            "BuildProfile working_directory must not be the reviewed source root or its child.",
        )
    if not working_directory.is_dir():
        _block(
            blockers,
            "VERIFICATION_BUILD_WORKING_DIRECTORY_MISSING",
            "BuildProfile working_directory does not exist.",
        )
        return blockers
    if profile.get("command") != build_payload.get("command"):
        _block(
            blockers,
            "VERIFICATION_BUILD_COMMAND_MISMATCH",
            "BuildProfile command does not match BuildResult command.",
        )
    if profile.get("expected_artifacts") != build_payload.get("expected_artifacts"):
        _block(
            blockers,
            "VERIFICATION_BUILD_ARTIFACT_SCOPE_MISMATCH",
            "BuildProfile expected_artifacts do not match BuildResult.",
        )
    for source_file in preflight["source_lineage"]["files"]:
        relative_path = source_file["relative_path"]
        expected_hash = source_file["expected_sha256"]
        copied_path = (working_directory / relative_path).resolve()
        try:
            copied_path.relative_to(working_directory)
        except ValueError:
            _block(
                blockers,
                "VERIFICATION_BUILD_SOURCE_PATH_ESCAPE",
                f"Build source path escapes working_directory: {relative_path}",
            )
            continue
        if not copied_path.is_file():
            _block(
                blockers,
                "VERIFICATION_BUILD_SOURCE_FILE_MISSING",
                f"Build working copy is missing source file: {relative_path}",
            )
            continue
        actual_hash = hashlib.sha256(copied_path.read_bytes()).hexdigest().upper()
        if actual_hash != str(expected_hash).upper():
            _block(
                blockers,
                "VERIFICATION_BUILD_SOURCE_HASH_MISMATCH",
                f"Build working copy source hash changed: {relative_path}",
            )
    return blockers


def verification_only_lineage_matches(
    build_payload: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> bool:
    """Return whether persisted BuildResult lineage matches the current preflight."""

    return build_payload.get("verification_only_lineage") == (
        verification_only_lineage_payload(preflight)
    )


def _validate_feature_identity(
    blockers: list[dict[str, str]],
    *,
    feature_ref: ArtifactRef,
    feature_envelope: Mapping[str, Any],
    user_request: str,
    target_mod: str | None,
) -> None:
    data = feature_envelope["data"]
    if feature_envelope.get("status") != "success":
        _block(
            blockers,
            "VERIFICATION_FEATURE_SPEC_STATUS_INVALID",
            "FeatureSpec status must be success.",
        )
    if data.get("feature_id") != feature_ref.feature_id:
        _block(
            blockers,
            "VERIFICATION_FEATURE_SPEC_IDENTITY_MISMATCH",
            "FeatureSpec payload feature_id does not match its Artifact reference.",
        )
    if data.get("user_request") != user_request:
        _block(
            blockers,
            "VERIFICATION_USER_REQUEST_MISMATCH",
            "Graph user_request does not match the exact FeatureSpec.",
        )
    if data.get("target_mod") != target_mod:
        _block(
            blockers,
            "VERIFICATION_TARGET_MOD_MISMATCH",
            "Graph target_mod does not match the exact FeatureSpec.",
        )


def _validate_evidence_identity(
    blockers: list[dict[str, str]],
    *,
    feature_ref: ArtifactRef,
    evidence_ref: ArtifactRef,
    evidence_envelope: Mapping[str, Any],
) -> None:
    if evidence_envelope.get("status") != "blocked":
        _block(
            blockers,
            "VERIFICATION_EVIDENCE_STATUS_INVALID",
            "EvidencePack status must preserve the reviewed blocked disposition.",
        )
    upstreams = evidence_envelope.get("inputs", {}).get("upstream_artifacts")
    expected = {
        "artifact_type": "feature_spec",
        "path": feature_ref.path,
        "artifact_hash": feature_ref.artifact_hash,
        "require_latest": True,
    }
    if not isinstance(upstreams, list) or upstreams != [expected]:
        _block(
            blockers,
            "VERIFICATION_EVIDENCE_LINEAGE_MISMATCH",
            "EvidencePack does not bind only the exact latest FeatureSpec.",
        )
    if evidence_envelope.get("feature_id") != evidence_ref.feature_id:
        _block(
            blockers,
            "VERIFICATION_EVIDENCE_IDENTITY_MISMATCH",
            "EvidencePack envelope feature_id does not match its Artifact reference.",
        )


def _validate_source_lineage(
    blockers: list[dict[str, str]],
    source_lineage: object,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "root": None,
        "read_only": None,
        "files": [],
        "all_files_verified": False,
    }
    if not isinstance(source_lineage, Mapping):
        _block(
            blockers,
            "VERIFICATION_SOURCE_LINEAGE_MISSING",
            "FeatureSpec source_lineage is missing.",
        )
        return report
    root_value = source_lineage.get("root")
    files = source_lineage.get("files")
    read_only = source_lineage.get("read_only")
    report["root"] = root_value
    report["read_only"] = read_only
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        _block(
            blockers,
            "VERIFICATION_SOURCE_ROOT_INVALID",
            "FeatureSpec source_lineage.root must be an absolute path.",
        )
        return report
    root = Path(root_value).resolve()
    if not root.is_dir():
        _block(
            blockers,
            "VERIFICATION_SOURCE_ROOT_MISSING",
            "FeatureSpec source_lineage.root does not exist as a directory.",
        )
        return report
    if read_only is not True:
        _block(
            blockers,
            "VERIFICATION_SOURCE_NOT_READ_ONLY",
            "Verification-only source_lineage must be marked read_only=true.",
        )
    if not isinstance(files, Mapping) or not files:
        _block(
            blockers,
            "VERIFICATION_SOURCE_FILES_MISSING",
            "FeatureSpec source_lineage.files must be a non-empty mapping.",
        )
        return report
    all_verified = True
    for relative_path, expected_hash in sorted(files.items()):
        file_report = {
            "relative_path": relative_path,
            "expected_sha256": expected_hash,
            "actual_sha256": None,
            "verified": False,
        }
        report["files"].append(file_report)
        if (
            not isinstance(relative_path, str)
            or not isinstance(expected_hash, str)
            or re.fullmatch(r"[0-9A-Fa-f]{64}", expected_hash) is None
        ):
            all_verified = False
            _block(
                blockers,
                "VERIFICATION_SOURCE_FILE_IDENTITY_INVALID",
                "FeatureSpec source file path or SHA256 is invalid.",
            )
            continue
        path = (root / Path(relative_path)).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            all_verified = False
            _block(
                blockers,
                "VERIFICATION_SOURCE_PATH_ESCAPE",
                f"Source path escapes source_lineage.root: {relative_path}",
            )
            continue
        if not path.is_file():
            all_verified = False
            _block(
                blockers,
                "VERIFICATION_SOURCE_FILE_MISSING",
                f"Source file is missing: {relative_path}",
            )
            continue
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        file_report["actual_sha256"] = actual_hash
        file_report["verified"] = actual_hash == expected_hash.upper()
        if not file_report["verified"]:
            all_verified = False
            _block(
                blockers,
                "VERIFICATION_SOURCE_HASH_MISMATCH",
                f"Source file SHA256 changed: {relative_path}",
            )
    report["all_files_verified"] = all_verified
    return report


def _ref_projection(ref: ArtifactRef) -> dict[str, str]:
    return {
        "feature_id": ref.feature_id,
        "artifact_type": ref.artifact_type,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _validate_latest_ref(
    artifact_store: ArtifactStore,
    ref: ArtifactRef,
    blockers: list[dict[str, str]],
) -> None:
    try:
        latest = [
            item
            for item in artifact_store.list_feature_artifacts(ref.feature_id)
            if item.artifact_type == ref.artifact_type
        ]
    except ArtifactStoreError as exc:
        _block(
            blockers,
            "VERIFICATION_LATEST_POINTER_INVALID",
            f"Latest Artifact pointer validation failed: {exc}",
        )
        return
    if len(latest) != 1 or latest[0].artifact_hash != ref.artifact_hash:
        _block(
            blockers,
            "VERIFICATION_INPUT_NOT_LATEST",
            f"Exact {ref.artifact_type} is not the current latest revision.",
        )


def _block(
    blockers: list[dict[str, str]],
    code: str,
    message: str,
) -> None:
    blockers.append({"code": code, "message": message})
