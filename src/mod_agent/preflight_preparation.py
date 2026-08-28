"""Deterministic, lineage-bound preparation of sealed Entry preflight packets."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from src.mod_agent.entry_admission import (
    EntryAdmissionRequestV1,
    EntryAdmissionResultV1,
)
from src.mod_agent.git.admission import GitExecutableIdentityV1, StrictGitAdmission
from src.mod_agent.model_admission import (
    read_ollama_model_identity,
    read_ollama_server_version,
    validate_ollama_context_window,
    validate_ollama_model_identity,
)
from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256


PACKET_FILENAME = "packet.json"
RUNNER_FILENAME = "sealed_entry_runner.py"
PREFLIGHT_FILENAME = "PREFLIGHT.json"
RUN_FILENAME = "RUN.md"
FRESH_PREFLIGHT_PROMPT_FILENAME = "FRESH_PREFLIGHT_PROMPT.md"
SEALED_FILE_SET = (
    PACKET_FILENAME,
    RUNNER_FILENAME,
    PREFLIGHT_FILENAME,
    RUN_FILENAME,
    FRESH_PREFLIGHT_PROMPT_FILENAME,
)
PAYLOAD_MANIFEST_MATERIAL = (PACKET_FILENAME, RUNNER_FILENAME)
DELIVERY_MANIFEST_MATERIAL = (
    PACKET_FILENAME,
    RUNNER_FILENAME,
    RUN_FILENAME,
    FRESH_PREFLIGHT_PROMPT_FILENAME,
)


class PreflightPreparationError(RuntimeError):
    """One fail-closed preparation boundary rejected before a usable seal."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str = "preparation",
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.stage = stage
        self.diagnostics = dict(diagnostics or {})


def _fail(
    code: str,
    message: str,
    *,
    stage: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> PreflightPreparationError:
    return PreflightPreparationError(
        code,
        message,
        stage=stage,
        diagnostics=diagnostics,
    )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Preflight preparation {field} must be non-empty text.")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Preflight preparation {field} must be a positive integer.")
    return value


def _hash_string(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _git_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is not None
    )


def _positive_finite_number(value: object, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"Preflight preparation {field} must be a positive finite number."
        )
    return float(value)


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _strict_posix_path(value: str, field: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise ValueError(f"Preflight preparation {field} must be a POSIX path.")
    selected = PurePosixPath(value)
    if selected.is_absolute() or any(part in {"", ".."} for part in selected.parts):
        raise ValueError(f"Preflight preparation {field} escapes the source repository.")
    if selected.as_posix() != value:
        raise ValueError(f"Preflight preparation {field} is not normalized.")
    return selected


def _resolve_existing_file(value: str, role: str) -> Path:
    selected = Path(value)
    if not selected.is_absolute() or ".." in selected.parts:
        raise _fail(
            "LINEAGE_PATH_INVALID",
            f"The explicit {role} path is not absolute and normalized.",
            stage="lineage",
            diagnostics={"role": role},
        )
    try:
        resolved = selected.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(
            "LINEAGE_FILE_MISSING",
            f"The explicit {role} file is missing.",
            stage="lineage",
            diagnostics={"role": role, "error_type": type(exc).__name__},
        ) from exc
    if not resolved.is_file():
        raise _fail(
            "LINEAGE_FILE_INVALID",
            f"The explicit {role} path is not a file.",
            stage="lineage",
            diagnostics={"role": role},
        )
    return resolved


def _resolve_existing_directory(value: object, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise _fail(
            "LINEAGE_REFERENCE_INVALID",
            f"The {role} reference is missing.",
            stage="lineage",
            diagnostics={"role": role},
        )
    selected = Path(value)
    if not selected.is_absolute() or ".." in selected.parts:
        raise _fail(
            "LINEAGE_PATH_INVALID",
            f"The {role} directory reference is invalid.",
            stage="lineage",
            diagnostics={"role": role},
        )
    try:
        resolved = selected.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(
            "LINEAGE_REFERENCE_UNVERIFIABLE",
            f"The {role} directory reference cannot be verified.",
            stage="lineage",
            diagnostics={"role": role, "error_type": type(exc).__name__},
        ) from exc
    if not resolved.is_dir():
        raise _fail(
            "LINEAGE_REFERENCE_INVALID",
            f"The {role} reference is not a directory.",
            stage="lineage",
            diagnostics={"role": role},
        )
    return resolved


def _read_json_object(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail(
            "LINEAGE_JSON_INVALID",
            f"The explicit {role} file is not valid UTF-8 JSON.",
            stage="lineage",
            diagnostics={"role": role, "error_type": type(exc).__name__},
        ) from exc
    if not isinstance(value, dict):
        raise _fail(
            "LINEAGE_SHAPE_UNKNOWN",
            f"The explicit {role} JSON shape is unknown.",
            stage="lineage",
            diagnostics={"role": role},
        )
    return value


def _resolve_json_reference(value: object, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise _fail(
            "LINEAGE_REFERENCE_INVALID",
            f"The {role} reference is missing.",
            stage="lineage",
            diagnostics={"role": role},
        )
    return _resolve_existing_file(value, role)


def _same_file_reference(value: object, expected: Path, role: str) -> None:
    selected = _resolve_json_reference(value, role)
    try:
        same = os.path.samefile(selected, expected)
    except OSError as exc:
        raise _fail(
            "LINEAGE_REFERENCE_UNVERIFIABLE",
            f"The {role} reference cannot be verified.",
            stage="lineage",
            diagnostics={"role": role, "error_type": type(exc).__name__},
        ) from exc
    if not same:
        raise _fail(
            "LINEAGE_REFERENCE_DRIFT",
            f"The {role} reference resolves to a different file.",
            stage="lineage",
            diagnostics={"role": role},
        )


@dataclass(frozen=True)
class RunIdentitiesV1:
    identity_series: str
    identity_sequence: int
    future_canary_number: int
    outer_run_id: str
    future_actual_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_series": self.identity_series,
            "identity_sequence": self.identity_sequence,
            "future_canary_number": self.future_canary_number,
            "outer_run_id": self.outer_run_id,
            "future_actual_id": self.future_actual_id,
        }


@dataclass(frozen=True)
class PreparedPreflightIdentitiesV1:
    identity_series: str
    identity_sequence: int
    future_canary_number: int
    outer_run_id: str
    future_actual_id: str
    preflight_attempt_id: str
    preflight_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_series": self.identity_series,
            "identity_sequence": self.identity_sequence,
            "future_canary_number": self.future_canary_number,
            "outer_run_id": self.outer_run_id,
            "future_actual_id": self.future_actual_id,
            "preflight_attempt_id": self.preflight_attempt_id,
            "preflight_id": self.preflight_id,
        }


def derive_run_identities(
    *,
    identity_series: str,
    identity_sequence: int,
) -> RunIdentitiesV1:
    """Derive the three coupled future identities from one series and sequence."""

    selected_series = _required_text(identity_series, "identity_series")
    selected_sequence = _positive_int(identity_sequence, "identity_sequence")
    if selected_sequence > 999:
        raise ValueError("Preflight preparation identity_sequence exceeds width 3.")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", selected_series) is None:
        raise ValueError("Preflight preparation identity_series format is invalid.")
    return RunIdentitiesV1(
        identity_series=selected_series,
        identity_sequence=selected_sequence,
        future_canary_number=selected_sequence,
        outer_run_id=f"{selected_series}_{selected_sequence:03d}",
        future_actual_id=f"actual_{selected_sequence}",
    )


@dataclass(frozen=True)
class DeterministicPostChangeConditionsV1:
    only_unaccounted: Literal[True]
    required_before_patch_policy: Literal[False]
    allowed_dispositions_exact: tuple[str, ...]
    all_other_omissions: Literal["fail_closed"]

    def __post_init__(self) -> None:
        if self.only_unaccounted is not True:
            raise ValueError(
                "Deterministic post-change only_unaccounted must be true."
            )
        if self.required_before_patch_policy is not False:
            raise ValueError(
                "Deterministic post-change required_before_patch_policy must be false."
            )
        if self.allowed_dispositions_exact != ("post_change",):
            raise ValueError(
                "Deterministic post-change dispositions must equal post_change."
            )
        if self.all_other_omissions != "fail_closed":
            raise ValueError(
                "Deterministic post-change omissions must equal fail_closed."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "only_unaccounted": self.only_unaccounted,
            "required_before_patch_policy": self.required_before_patch_policy,
            "allowed_dispositions_exact": list(self.allowed_dispositions_exact),
            "all_other_omissions": self.all_other_omissions,
        }


@dataclass(frozen=True)
class SelectedPreflightConfigurationV1:
    configuration_id: str
    route: str
    main_ollama_timeout_seconds: float
    timeout_owner: str
    repair_ollama_timeout_seconds: float | None
    repair_timeout_selection: str
    projection_contract_checkpoint: str
    model_projection_fields: tuple[str, ...]
    model_relations_authorized: Literal[False]
    deterministic_relation_completion: Literal[True]
    deterministic_relation_rule: Literal["one relation per requirement"]
    deterministic_post_change: DeterministicPostChangeConditionsV1
    initial_projection_attempts: Literal[1]
    maximum_correction_attempts_after_initial: Literal[1]
    provider_fallback: Literal[False]
    automatic_retry: Literal[False]
    external_disclosure: Literal[False]

    def __post_init__(self) -> None:
        for field_name in (
            "configuration_id",
            "route",
            "timeout_owner",
            "repair_timeout_selection",
            "projection_contract_checkpoint",
            "deterministic_relation_rule",
        ):
            selected_text = _required_text(getattr(self, field_name), field_name)
            if not selected_text.strip():
                raise ValueError(
                    f"Preflight preparation {field_name} must not be blank."
                )
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.configuration_id) is None:
            raise ValueError("Preflight preparation configuration_id format is invalid.")
        _positive_finite_number(
            self.main_ollama_timeout_seconds,
            "main_ollama_timeout_seconds",
        )
        if self.repair_ollama_timeout_seconds is not None:
            _positive_finite_number(
                self.repair_ollama_timeout_seconds,
                "repair_ollama_timeout_seconds",
            )
        if not _git_object_id(self.projection_contract_checkpoint):
            raise ValueError(
                "Preflight preparation projection_contract_checkpoint is invalid."
            )
        if (
            not isinstance(self.model_projection_fields, tuple)
            or not self.model_projection_fields
            or len(set(self.model_projection_fields))
            != len(self.model_projection_fields)
            or any(
                not isinstance(item, str) or not item or not item.strip()
                for item in self.model_projection_fields
            )
        ):
            raise ValueError(
                "Preflight preparation model_projection_fields are invalid."
            )
        if self.model_relations_authorized is not False:
            raise ValueError("Model relations authorization must remain false.")
        if self.deterministic_relation_completion is not True:
            raise ValueError("Deterministic relation completion must remain true.")
        if self.deterministic_relation_rule != "one relation per requirement":
            raise ValueError("Deterministic relation rule is invalid.")
        if not isinstance(
            self.deterministic_post_change,
            DeterministicPostChangeConditionsV1,
        ):
            raise ValueError("Deterministic post-change conditions are invalid.")
        if self.initial_projection_attempts != 1 or isinstance(
            self.initial_projection_attempts,
            bool,
        ):
            raise ValueError("Initial projection attempts must equal 1.")
        if self.maximum_correction_attempts_after_initial != 1 or isinstance(
            self.maximum_correction_attempts_after_initial,
            bool,
        ):
            raise ValueError("Maximum correction attempts must equal 1.")
        for field_name in (
            "provider_fallback",
            "automatic_retry",
            "external_disclosure",
        ):
            if getattr(self, field_name) is not False:
                raise ValueError(f"Selected configuration {field_name} must be false.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "route": self.route,
            "main_ollama_timeout_seconds": float(
                self.main_ollama_timeout_seconds
            ),
            "timeout_owner": self.timeout_owner,
            "repair_ollama_timeout_seconds": (
                None
                if self.repair_ollama_timeout_seconds is None
                else float(self.repair_ollama_timeout_seconds)
            ),
            "repair_timeout_selection": self.repair_timeout_selection,
            "projection_contract_checkpoint": self.projection_contract_checkpoint,
            "model_projection_fields": list(self.model_projection_fields),
            "model_relations_authorized": self.model_relations_authorized,
            "deterministic_relation_completion": (
                self.deterministic_relation_completion
            ),
            "deterministic_relation_rule": self.deterministic_relation_rule,
            "deterministic_post_change": self.deterministic_post_change.to_dict(),
            "initial_projection_attempts": self.initial_projection_attempts,
            "maximum_correction_attempts_after_initial": (
                self.maximum_correction_attempts_after_initial
            ),
            "provider_fallback": self.provider_fallback,
            "automatic_retry": self.automatic_retry,
            "external_disclosure": self.external_disclosure,
        }


@dataclass(frozen=True)
class RejectedPreflightIdentityReservationV1:
    packet_path: str
    receipt_path: str
    receipt_manifest_path: str

    def __post_init__(self) -> None:
        for field_name in ("packet_path", "receipt_path", "receipt_manifest_path"):
            _required_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class SealedPreflightPreparationRequestV1:
    contract_version: Literal["1"]
    packet_root: str
    packet_date: str
    task_id: str
    request_text: str
    identity_series: str
    identity_sequence: int
    selected_configuration: SelectedPreflightConfigurationV1
    platform_root: str
    allowed_dirty_paths: tuple[str, ...]
    source_root: str
    target_project: str
    project_file: str
    primary_source_paths: tuple[str, ...]
    git_executable: str
    ollama_base_url: str
    ollama_model: str
    ollama_context_window: int
    ollama_output_budget: int
    preflight_lineage_packet_paths: tuple[str, ...]
    predecessor_receipt_path: str
    predecessor_receipt_manifest_path: str
    actual_lineage_packet_paths: tuple[str, ...]
    rejected_preflight_identity_reservations: tuple[
        RejectedPreflightIdentityReservationV1, ...
    ]

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise ValueError("Preflight preparation request contract version is invalid.")
        for field_name in (
            "packet_root",
            "packet_date",
            "task_id",
            "request_text",
            "identity_series",
            "platform_root",
            "source_root",
            "target_project",
            "project_file",
            "git_executable",
            "ollama_base_url",
            "ollama_model",
            "predecessor_receipt_path",
            "predecessor_receipt_manifest_path",
        ):
            _required_text(getattr(self, field_name), field_name)
        try:
            parsed_date = date.fromisoformat(self.packet_date)
        except ValueError as exc:
            raise ValueError("Preflight preparation packet_date is invalid.") from exc
        if parsed_date.isoformat() != self.packet_date:
            raise ValueError("Preflight preparation packet_date is not normalized.")
        derive_run_identities(
            identity_series=self.identity_series,
            identity_sequence=self.identity_sequence,
        )
        if not isinstance(
            self.selected_configuration,
            SelectedPreflightConfigurationV1,
        ):
            raise ValueError("Preflight preparation selected_configuration is invalid.")
        for field_name in ("ollama_context_window", "ollama_output_budget"):
            _positive_int(getattr(self, field_name), field_name)
        if self.ollama_context_window <= self.ollama_output_budget:
            raise ValueError("Preflight preparation model context must exceed output budget.")
        for field_name in (
            "allowed_dirty_paths",
            "primary_source_paths",
            "preflight_lineage_packet_paths",
            "actual_lineage_packet_paths",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, tuple)
                or len(set(value)) != len(value)
                or any(not isinstance(item, str) or not item for item in value)
            ):
                raise ValueError(f"Preflight preparation {field_name} is invalid.")
        if not self.primary_source_paths:
            raise ValueError("Preflight preparation primary_source_paths is empty.")
        if not self.preflight_lineage_packet_paths:
            raise ValueError("Preflight preparation preflight lineage is empty.")
        if not self.actual_lineage_packet_paths:
            raise ValueError("Preflight preparation actual lineage is empty.")
        if (
            not isinstance(self.rejected_preflight_identity_reservations, tuple)
            or any(
                not isinstance(item, RejectedPreflightIdentityReservationV1)
                for item in self.rejected_preflight_identity_reservations
            )
            or len(
                {
                    (item.packet_path, item.receipt_path, item.receipt_manifest_path)
                    for item in self.rejected_preflight_identity_reservations
                }
            )
            != len(self.rejected_preflight_identity_reservations)
        ):
            raise ValueError(
                "Preflight preparation rejected identity reservations are invalid."
            )
        for selected in self.allowed_dirty_paths:
            _strict_posix_path(selected, "allowed_dirty_paths")
        _strict_posix_path(self.project_file, "project_file")
        for selected in self.primary_source_paths:
            _strict_posix_path(selected, "primary_source_paths")


@dataclass(frozen=True)
class PreflightPreparationDependenciesV1:
    model_identity_reader: Callable[[str, str], dict[str, Any]] = (
        read_ollama_model_identity
    )
    server_version_reader: Callable[[str], str] = read_ollama_server_version
    context_validator: Callable[..., int] = validate_ollama_context_window


@dataclass(frozen=True)
class SealedPreflightPreparationResultV1:
    status: Literal["sealed"]
    packet_root: str
    identities: PreparedPreflightIdentitiesV1
    predecessor_preflight_id: str
    lineage_sources: tuple[dict[str, Any], ...]
    sealed_files: tuple[str, ...]
    packet_sha256: str
    preflight_sha256: str
    payload_manifest_sha256: str
    delivery_manifest_sha256: str
    authorized_run_command: str
    audit_summary: tuple[str, ...]
    actual_authorized: Literal[False] = False
    canary_authorized: Literal[False] = False
    model_generation_calls: Literal[0] = 0
    ProductExecution_runs: Literal[0] = 0
    Builds: Literal[0] = 0
    Runtime_runs: Literal[0] = 0
    Apply_runs: Literal[0] = 0
    execution_root_created: Literal[False] = False
    apply_workspace_created: Literal[False] = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "packet_root": self.packet_root,
            "identities": self.identities.to_dict(),
            "predecessor_preflight_id": self.predecessor_preflight_id,
            "lineage_sources": [dict(item) for item in self.lineage_sources],
            "sealed_files": list(self.sealed_files),
            "packet_sha256": self.packet_sha256,
            "preflight_sha256": self.preflight_sha256,
            "payload_manifest_sha256": self.payload_manifest_sha256,
            "delivery_manifest_sha256": self.delivery_manifest_sha256,
            "authorized_run_command": self.authorized_run_command,
            "audit_summary": list(self.audit_summary),
            "actual_authorized": self.actual_authorized,
            "canary_authorized": self.canary_authorized,
            "model_generation_calls": self.model_generation_calls,
            "ProductExecution_runs": self.ProductExecution_runs,
            "Builds": self.Builds,
            "Runtime_runs": self.Runtime_runs,
            "Apply_runs": self.Apply_runs,
            "execution_root_created": self.execution_root_created,
            "apply_workspace_created": self.apply_workspace_created,
        }


@dataclass(frozen=True)
class _PreflightLineageRecord:
    packet_path: Path
    packet_sha256: str
    preflight_path: Path
    preflight_sha256: str
    payload_manifest_sha256: str
    outer_run_id: str
    identity_series: str
    identity_sequence: int
    attempt_id: str
    attempt_number: int
    preflight_id: str
    preflight_number: int
    future_canary_number: int
    future_actual_id: str
    receipt_path: Path
    receipt_manifest_path: Path


@dataclass(frozen=True)
class _ActualLineageRecord:
    packet_path: Path
    packet_sha256: str
    outer_run_id: str
    identity_series: str
    identity_sequence: int
    actual_id: str
    accepted_preflight_attempt_id: str
    accepted_preflight_id: str
    accepted_preflight_root: Path
    accepted_preflight_output_root: Path
    accepted_payload_manifest_sha256: str
    accepted_receipt_path: Path
    accepted_receipt_sha256: str
    accepted_receipt_manifest_path: Path
    accepted_receipt_manifest_sha256: str


@dataclass(frozen=True)
class _RejectedPreflightReservationRecord:
    preflight: _PreflightLineageRecord
    receipt_sha256: str
    receipt_manifest_sha256: str


@dataclass(frozen=True)
class _LineageAdmission:
    predecessor: _PreflightLineageRecord
    preflight_records: tuple[_PreflightLineageRecord, ...]
    actual_records: tuple[_ActualLineageRecord, ...]
    reservation_records: tuple[_RejectedPreflightReservationRecord, ...]
    predecessor_receipt_sha256: str
    predecessor_receipt_manifest_sha256: str
    sources: tuple[dict[str, Any], ...]


def _parse_run_identity_components(
    outer_run_id: object,
    actual_id: object,
) -> tuple[str, int, int]:
    if not isinstance(outer_run_id, str) or not isinstance(actual_id, str):
        raise _fail(
            "LINEAGE_RUN_IDENTITY_SHAPE_INVALID",
            "The historical outer or actual identity is not text.",
            stage="lineage",
        )
    match = re.fullmatch(r"(.+)_([0-9]{3})", outer_run_id)
    actual_match = re.fullmatch(r"actual_([1-9][0-9]*)", actual_id)
    if match is None or actual_match is None:
        raise _fail(
            "LINEAGE_RUN_IDENTITY_FORMAT_INVALID",
            "The historical outer or actual identity format is invalid.",
            stage="lineage",
        )
    outer_number = int(match.group(2))
    actual_number = int(actual_match.group(1))
    return match.group(1), outer_number, actual_number


def _parse_run_identity(outer_run_id: object, actual_id: object) -> tuple[str, int]:
    series, outer_number, actual_number = _parse_run_identity_components(
        outer_run_id,
        actual_id,
    )
    if outer_number != actual_number:
        raise _fail(
            "LINEAGE_RUN_IDENTITY_MISMATCH",
            "Historical outer and actual identities encode different sequences.",
            stage="lineage",
            diagnostics={
                "outer_run_id": outer_run_id,
                "actual_id": actual_id,
            },
        )
    return series, outer_number


def _parse_preflight_identity(
    attempt_id: object,
    preflight_id: object,
) -> tuple[int, int]:
    if not isinstance(attempt_id, str) or not isinstance(preflight_id, str):
        raise _fail(
            "LINEAGE_PREFLIGHT_IDENTITY_SHAPE_INVALID",
            "The historical preflight identity is not text.",
            stage="lineage",
        )
    attempt_match = re.fullmatch(r"preflight_([1-9][0-9]*)", attempt_id)
    identity_match = re.fullmatch(r"entry_preflight_([0-9]{3})_[A-Za-z0-9_.-]+", preflight_id)
    if attempt_match is None or identity_match is None:
        raise _fail(
            "LINEAGE_PREFLIGHT_IDENTITY_FORMAT_INVALID",
            "The historical preflight identity format is invalid.",
            stage="lineage",
        )
    attempt_number = int(attempt_match.group(1))
    preflight_number = int(identity_match.group(1))
    if preflight_number != attempt_number + 1:
        raise _fail(
            "LINEAGE_PREFLIGHT_IDENTITY_MISMATCH",
            "Historical preflight attempt and identity encode different allocations.",
            stage="lineage",
        )
    return attempt_number, preflight_number


def _load_preflight_record(
    value: str,
    *,
    require_consistent_future_identity: bool = True,
) -> _PreflightLineageRecord:
    packet_path = _resolve_existing_file(value, "preflight packet")
    packet = _read_json_object(packet_path, "preflight packet")
    if packet.get("packet_version") != "p2_thin_entry_admission_packet_v6":
        raise _fail(
            "LINEAGE_PREFLIGHT_PACKET_VERSION_UNKNOWN",
            "The historical preflight packet version is not supported.",
            stage="lineage",
        )
    delivery = packet.get("delivery")
    if not isinstance(delivery, Mapping):
        raise _fail(
            "LINEAGE_SHAPE_UNKNOWN",
            "The historical preflight delivery shape is unknown.",
            stage="lineage",
        )
    packet_root_text = _resolve_existing_directory(
        delivery.get("packet_root_text"),
        "historical packet root text",
    )
    packet_root_canonical = _resolve_existing_directory(
        delivery.get("packet_root_canonical_text"),
        "historical packet root canonical",
    )
    if (
        not os.path.samefile(packet_root_text, packet_root_canonical)
        or not os.path.samefile(packet_root_canonical, packet_path.parent)
    ):
        raise _fail(
            "LINEAGE_PACKET_ROOT_DRIFT",
            "The historical packet root does not bind the explicit packet file.",
            stage="lineage",
        )
    future_sections = [
        packet.get(name)
        for name in ("product_execution_selection", "future_execution_binding")
        if isinstance(packet.get(name), Mapping)
    ]
    if len(future_sections) != 1:
        raise _fail(
            "LINEAGE_FUTURE_IDENTITY_SHAPE_UNKNOWN",
            "The historical future identity section is missing or ambiguous.",
            stage="lineage",
        )
    future = future_sections[0]
    canary = future.get("future_canary_number")
    actual_id = future.get("future_attempt_id")
    if isinstance(canary, bool) or not isinstance(canary, int) or canary <= 0:
        raise _fail(
            "LINEAGE_CANARY_IDENTITY_INVALID",
            "The historical future canary identity is invalid.",
            stage="lineage",
        )
    series, sequence, actual_sequence = _parse_run_identity_components(
        packet.get("outer_run_id"),
        actual_id,
    )
    if require_consistent_future_identity and (
        canary != sequence or actual_sequence != sequence
    ):
        raise _fail(
            "LINEAGE_RUN_IDENTITY_MISMATCH",
            "Historical canary, outer, and actual identities encode different sequences.",
            stage="lineage",
            diagnostics={
                "outer_run_id": packet.get("outer_run_id"),
                "future_canary_number": canary,
                "future_actual_id": actual_id,
            },
        )
    permissions = packet.get("permissions")
    if (
        not isinstance(permissions, Mapping)
        or permissions.get("canary_authorized") is not False
        or permissions.get("actual_authorized") is not False
    ):
        raise _fail(
            "LINEAGE_AUTHORITY_BOUNDARY_INVALID",
            "The historical preflight packet does not preserve the zero-authority boundary.",
            stage="lineage",
        )
    attempt_id = packet.get("attempt_id")
    preflight_id = packet.get("preflight_id")
    attempt_number, preflight_number = _parse_preflight_identity(
        attempt_id,
        preflight_id,
    )
    preflight_path = packet_path.parent / PREFLIGHT_FILENAME
    if not preflight_path.is_file():
        raise _fail(
            "LINEAGE_PREFLIGHT_MANIFEST_MISSING",
            "The historical packet lacks its sibling PREFLIGHT.json seal.",
            stage="lineage",
        )
    preflight = _read_json_object(preflight_path, "preflight seal")
    if preflight.get("packet_sealed") is not True:
        raise _fail(
            "LINEAGE_PREFLIGHT_NOT_SEALED",
            "The historical PREFLIGHT.json does not record a sealed packet.",
            stage="lineage",
        )
    files_value = preflight.get("files")
    if not isinstance(files_value, Mapping):
        raise _fail(
            "LINEAGE_PREFLIGHT_MANIFEST_SHAPE_UNKNOWN",
            "The historical preflight file manifest shape is unknown.",
            stage="lineage",
        )
    observed_payload: dict[str, str] = {}
    for filename in PAYLOAD_MANIFEST_MATERIAL:
        selected = packet_path.parent / filename
        if not selected.is_file():
            raise _fail(
                "LINEAGE_PAYLOAD_FILE_MISSING",
                "A historical payload file is missing.",
                stage="lineage",
                diagnostics={"filename": filename},
            )
        record = files_value.get(filename)
        observed_hash = _file_sha256(selected)
        if (
            not isinstance(record, Mapping)
            or record.get("sha256") != observed_hash
            or record.get("bytes") != selected.stat().st_size
        ):
            raise _fail(
                "LINEAGE_PAYLOAD_FILE_DRIFT",
                "A historical payload file no longer matches its seal.",
                stage="lineage",
                diagnostics={"filename": filename},
            )
        observed_payload[filename] = observed_hash
    payload_manifest = _canonical_json_sha256(observed_payload)
    if (
        preflight.get("payload_manifest_material")
        != list(PAYLOAD_MANIFEST_MATERIAL)
        or preflight.get("payload_manifest_sha256") != payload_manifest
    ):
        raise _fail(
            "LINEAGE_PAYLOAD_MANIFEST_DRIFT",
            "The historical payload manifest cannot be independently verified.",
            stage="lineage",
        )
    receipt_path = _resolve_json_reference(
        delivery.get("expected_receipt_path"),
        "historical expected receipt",
    )
    receipt_manifest_path = _resolve_json_reference(
        delivery.get("expected_receipt_manifest_path"),
        "historical expected receipt manifest",
    )
    return _PreflightLineageRecord(
        packet_path=packet_path,
        packet_sha256=_file_sha256(packet_path),
        preflight_path=preflight_path.resolve(strict=True),
        preflight_sha256=_file_sha256(preflight_path),
        payload_manifest_sha256=payload_manifest,
        outer_run_id=packet["outer_run_id"],
        identity_series=series,
        identity_sequence=sequence,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        preflight_id=preflight_id,
        preflight_number=preflight_number,
        future_canary_number=canary,
        future_actual_id=actual_id,
        receipt_path=receipt_path,
        receipt_manifest_path=receipt_manifest_path,
    )


def _verify_preflight_receipt(
    preflight: _PreflightLineageRecord,
    *,
    receipt_path_value: str,
    receipt_manifest_path_value: str,
    require_ready: bool,
) -> tuple[str, str]:
    receipt_path = _resolve_existing_file(
        receipt_path_value,
        "historical preflight receipt",
    )
    receipt_manifest_path = _resolve_existing_file(
        receipt_manifest_path_value,
        "historical preflight receipt manifest",
    )
    if not os.path.samefile(receipt_path, preflight.receipt_path) or not os.path.samefile(
        receipt_manifest_path,
        preflight.receipt_manifest_path,
    ):
        raise _fail(
            "LINEAGE_PREDECESSOR_RECEIPT_REFERENCE_DRIFT",
            "The explicit predecessor receipt paths differ from the packet references.",
            stage="lineage",
        )
    manifest = _read_json_object(receipt_manifest_path, "predecessor receipt manifest")
    if set(manifest) != {
        "actual_authorized",
        "manifest_version",
        "payload_manifest_sha256",
        "receipt_path",
        "receipt_sha256",
    }:
        raise _fail(
            "LINEAGE_RECEIPT_MANIFEST_SHAPE_UNKNOWN",
            "The predecessor receipt manifest shape is unknown.",
            stage="lineage",
        )
    receipt_sha256 = _file_sha256(receipt_path)
    if (
        manifest.get("actual_authorized") is not False
        or manifest.get("manifest_version") != "sealed_entry_admission_manifest_v1"
        or manifest.get("payload_manifest_sha256")
        != preflight.payload_manifest_sha256
        or manifest.get("receipt_sha256") != receipt_sha256
    ):
        raise _fail(
            "LINEAGE_RECEIPT_MANIFEST_DRIFT",
            "The predecessor receipt manifest cannot be verified.",
            stage="lineage",
        )
    _same_file_reference(
        manifest.get("receipt_path"),
        receipt_path,
        "predecessor receipt manifest receipt",
    )
    receipt = _read_json_object(receipt_path, "predecessor receipt")
    if set(receipt) != {
        "actual_authorized",
        "output_root_text",
        "packet_root_text",
        "receipt_version",
        "request_identity",
        "result",
    }:
        raise _fail(
            "LINEAGE_RECEIPT_SHAPE_UNKNOWN",
            "The predecessor receipt shape is unknown.",
            stage="lineage",
        )
    expected_request_identity = {
        "attempt_id": preflight.attempt_id,
        "outer_run_id": preflight.outer_run_id,
        "payload_manifest_sha256": preflight.payload_manifest_sha256,
    }
    if (
        receipt.get("actual_authorized") is not False
        or receipt.get("receipt_version") != "sealed_entry_admission_receipt_v1"
        or receipt.get("request_identity") != expected_request_identity
    ):
        raise _fail(
            "LINEAGE_RECEIPT_IDENTITY_DRIFT",
            "The predecessor receipt identity does not match its sealed packet.",
            stage="lineage",
        )
    receipt_packet_root = _resolve_existing_directory(
        receipt.get("packet_root_text"),
        "predecessor receipt packet root",
    )
    receipt_output_root = _resolve_existing_directory(
        receipt.get("output_root_text"),
        "predecessor receipt output root",
    )
    if (
        not os.path.samefile(receipt_packet_root, preflight.packet_path.parent)
        or not os.path.samefile(receipt_output_root, receipt_path.parent)
    ):
        raise _fail(
            "LINEAGE_RECEIPT_ROOT_DRIFT",
            "The predecessor receipt root references drifted from its sealed files.",
            stage="lineage",
        )
    result_value = receipt.get("result")
    if not isinstance(result_value, Mapping):
        raise _fail(
            "LINEAGE_RECEIPT_RESULT_SHAPE_UNKNOWN",
            "The predecessor receipt result shape is unknown.",
            stage="lineage",
        )
    try:
        result = EntryAdmissionResultV1.from_dict(result_value)
    except (TypeError, ValueError) as exc:
        raise _fail(
            "LINEAGE_RECEIPT_RESULT_INVALID",
            "The predecessor Entry Admission result is invalid.",
            stage="lineage",
            diagnostics={"error_type": type(exc).__name__},
        ) from exc
    if (
        (require_ready and result.status != "ready")
        or result.outer_run_id != preflight.outer_run_id
        or result.attempt_id != preflight.attempt_id
        or result.payload_manifest_sha256 != preflight.payload_manifest_sha256
        or result.packet_root_text != receipt.get("packet_root_text")
        or result.output_root_text != receipt.get("output_root_text")
    ):
        raise _fail(
            "LINEAGE_RECEIPT_RESULT_INVALID_FOR_USE",
            "The historical receipt result is invalid for its lineage role.",
            stage="lineage",
        )
    return receipt_sha256, _file_sha256(receipt_manifest_path)


def _load_rejected_preflight_reservation(
    value: RejectedPreflightIdentityReservationV1,
) -> _RejectedPreflightReservationRecord:
    preflight = _load_preflight_record(
        value.packet_path,
        require_consistent_future_identity=False,
    )
    receipt_sha256, receipt_manifest_sha256 = _verify_preflight_receipt(
        preflight,
        receipt_path_value=value.receipt_path,
        receipt_manifest_path_value=value.receipt_manifest_path,
        require_ready=False,
    )
    return _RejectedPreflightReservationRecord(
        preflight=preflight,
        receipt_sha256=receipt_sha256,
        receipt_manifest_sha256=receipt_manifest_sha256,
    )


def _load_actual_record(value: str) -> _ActualLineageRecord:
    packet_path = _resolve_existing_file(value, "actual lineage packet")
    packet = _read_json_object(packet_path, "actual lineage packet")
    packet_version = packet.get("packet_version")
    if packet_version not in {
        "p2_receipt_bound_actual_packet_v6",
        "p2_receipt_bound_actual_packet_v7",
    }:
        raise _fail(
            "LINEAGE_ACTUAL_PACKET_VERSION_UNKNOWN",
            "The historical actual packet version is not supported.",
            stage="lineage",
        )
    if packet_version == "p2_receipt_bound_actual_packet_v7":
        seal_path = packet_path.parent / "ACTUAL_SEAL.json"
        if not seal_path.is_file():
            raise _fail(
                "LINEAGE_ACTUAL_SEAL_MISSING",
                "The stable Actual packet lacks ACTUAL_SEAL.json.",
                stage="lineage",
            )
        seal = _read_json_object(seal_path, "actual lineage seal")
        material = ("packet.json",)
        files = seal.get("files")
        if (
            seal.get("seal_version") != "sealed_actual_run_v1"
            or seal.get("packet_sealed") is not True
            or seal.get("manifest_material") != list(material)
            or not isinstance(files, Mapping)
        ):
            raise _fail(
                "LINEAGE_ACTUAL_SEAL_INVALID",
                "The stable Actual seal shape or status is invalid.",
                stage="lineage",
            )
        observed: dict[str, str] = {}
        for filename in material:
            selected = packet_path.parent / filename
            if not selected.is_file():
                raise _fail(
                    "LINEAGE_ACTUAL_SEAL_FILE_MISSING",
                    "A stable Actual sealed file is missing.",
                    stage="lineage",
                    diagnostics={"filename": filename},
                )
            observed[filename] = _file_sha256(selected)
        if files != observed or seal.get("manifest_sha256") != _canonical_json_sha256(
            observed
        ):
            raise _fail(
                "LINEAGE_ACTUAL_SEAL_DRIFT",
                "The stable Actual packet no longer matches its seal.",
                stage="lineage",
            )
    seal_status = packet.get("seal_status")
    if not isinstance(seal_status, Mapping) or seal_status.get("packet_sealed") is not True:
        raise _fail(
            "LINEAGE_ACTUAL_PACKET_NOT_SEALED",
            "The historical actual packet is not sealed.",
            stage="lineage",
        )
    actual_id = packet.get("actual_attempt_id")
    series, sequence = _parse_run_identity(packet.get("outer_run_id"), actual_id)
    accepted = packet.get("accepted_entry_receipt")
    if not isinstance(accepted, Mapping):
        raise _fail(
            "LINEAGE_ACTUAL_RECEIPT_BINDING_UNKNOWN",
            "The historical actual packet lacks its accepted Entry receipt binding.",
            stage="lineage",
        )
    accepted_attempt = accepted.get("preflight_attempt_id")
    accepted_preflight_id = accepted.get("preflight_id")
    _parse_preflight_identity(accepted_attempt, accepted_preflight_id)
    payload_manifest = accepted.get("payload_manifest_sha256")
    receipt_sha256 = accepted.get("receipt_sha256")
    receipt_manifest_sha256 = accepted.get("receipt_manifest_sha256")
    if not all(
        _hash_string(item)
        for item in (payload_manifest, receipt_sha256, receipt_manifest_sha256)
    ):
        raise _fail(
            "LINEAGE_ACTUAL_HASH_BINDING_INVALID",
            "The historical actual packet has an invalid receipt hash binding.",
            stage="lineage",
        )
    if (
        accepted.get("receipt_status") != "ready"
        or accepted.get("receipt_actual_authorized") is not False
    ):
        raise _fail(
            "LINEAGE_ACTUAL_RECEIPT_STATUS_INVALID",
            "The historical actual packet is not bound to a ready no-authority receipt.",
            stage="lineage",
        )
    preflight_root_text = _resolve_existing_directory(
        accepted.get("preflight_packet_root_text"),
        "actual accepted preflight packet root text",
    )
    preflight_root_canonical = _resolve_existing_directory(
        accepted.get("preflight_packet_root_canonical_text"),
        "actual accepted preflight packet root canonical",
    )
    if not os.path.samefile(preflight_root_text, preflight_root_canonical):
        raise _fail(
            "LINEAGE_ACTUAL_PREFLIGHT_ROOT_DRIFT",
            "The historical actual packet binds different preflight roots.",
            stage="lineage",
        )
    output_root_text = _resolve_existing_directory(
        accepted.get("preflight_output_root_text"),
        "actual accepted preflight output root text",
    )
    output_root_canonical = _resolve_existing_directory(
        accepted.get("preflight_output_root_canonical_text"),
        "actual accepted preflight output root canonical",
    )
    if not os.path.samefile(output_root_text, output_root_canonical):
        raise _fail(
            "LINEAGE_ACTUAL_PREFLIGHT_OUTPUT_ROOT_DRIFT",
            "The historical actual packet binds different preflight output roots.",
            stage="lineage",
        )
    receipt_path = _resolve_json_reference(
        accepted.get("receipt_path"),
        "actual accepted receipt",
    )
    receipt_manifest_path = _resolve_json_reference(
        accepted.get("receipt_manifest_path"),
        "actual accepted receipt manifest",
    )
    if _file_sha256(receipt_path) != receipt_sha256:
        raise _fail(
            "LINEAGE_ACTUAL_RECEIPT_HASH_DRIFT",
            "The historical actual receipt hash no longer matches.",
            stage="lineage",
        )
    if _file_sha256(receipt_manifest_path) != receipt_manifest_sha256:
        raise _fail(
            "LINEAGE_ACTUAL_RECEIPT_MANIFEST_HASH_DRIFT",
            "The historical actual receipt manifest hash no longer matches.",
            stage="lineage",
        )
    return _ActualLineageRecord(
        packet_path=packet_path,
        packet_sha256=_file_sha256(packet_path),
        outer_run_id=packet["outer_run_id"],
        identity_series=series,
        identity_sequence=sequence,
        actual_id=actual_id,
        accepted_preflight_attempt_id=accepted_attempt,
        accepted_preflight_id=accepted_preflight_id,
        accepted_preflight_root=preflight_root_canonical,
        accepted_preflight_output_root=output_root_canonical,
        accepted_payload_manifest_sha256=payload_manifest,
        accepted_receipt_path=receipt_path,
        accepted_receipt_sha256=receipt_sha256,
        accepted_receipt_manifest_path=receipt_manifest_path,
        accepted_receipt_manifest_sha256=receipt_manifest_sha256,
    )


def _admit_lineage(
    request: SealedPreflightPreparationRequestV1,
    run_identities: RunIdentitiesV1,
) -> _LineageAdmission:
    preflight_records = tuple(
        _load_preflight_record(value)
        for value in request.preflight_lineage_packet_paths
    )
    predecessor = preflight_records[-1]
    receipt_sha256, receipt_manifest_sha256 = _verify_preflight_receipt(
        predecessor,
        receipt_path_value=request.predecessor_receipt_path,
        receipt_manifest_path_value=request.predecessor_receipt_manifest_path,
        require_ready=True,
    )
    actual_records = tuple(
        _load_actual_record(value) for value in request.actual_lineage_packet_paths
    )
    reservation_records = tuple(
        _load_rejected_preflight_reservation(value)
        for value in request.rejected_preflight_identity_reservations
    )
    if any(record.identity_series != run_identities.identity_series for record in actual_records):
        raise _fail(
            "LINEAGE_SERIES_DRIFT",
            "An actual lineage packet belongs to a different run identity series.",
            stage="lineage",
        )
    if any(
        record.identity_series != run_identities.identity_series
        for record in preflight_records
    ):
        raise _fail(
            "LINEAGE_SERIES_DRIFT",
            "A preflight lineage packet belongs to a different run identity series.",
            stage="lineage",
        )
    preflight_keys = {
        (record.attempt_id, record.preflight_id): record
        for record in preflight_records
    }
    if len(preflight_keys) != len(preflight_records):
        raise _fail(
            "LINEAGE_PREFLIGHT_IDENTITY_DUPLICATE",
            "The explicit preflight lineage repeats an identity.",
            stage="lineage",
        )
    actual_keys = {(record.outer_run_id, record.actual_id) for record in actual_records}
    if len(actual_keys) != len(actual_records):
        raise _fail(
            "LINEAGE_ACTUAL_IDENTITY_DUPLICATE",
            "The explicit actual lineage repeats an identity.",
            stage="lineage",
        )
    used_preflight_attempts = {record.attempt_id for record in preflight_records}
    used_preflight_ids = {record.preflight_id for record in preflight_records}
    used_preflight_attempts.update(
        record.accepted_preflight_attempt_id for record in actual_records
    )
    used_preflight_ids.update(record.accepted_preflight_id for record in actual_records)
    for reservation in reservation_records:
        record = reservation.preflight
        if (
            record.attempt_id in used_preflight_attempts
            or record.preflight_id in used_preflight_ids
        ):
            raise _fail(
                "LINEAGE_RESERVED_PREFLIGHT_IDENTITY_DUPLICATE",
                "A rejected preflight reservation repeats a used preflight identity.",
                stage="lineage",
            )
        used_preflight_attempts.add(record.attempt_id)
        used_preflight_ids.add(record.preflight_id)
    for actual in actual_records:
        matching = preflight_keys.get(
            (
                actual.accepted_preflight_attempt_id,
                actual.accepted_preflight_id,
            )
        )
        if matching is None:
            raise _fail(
                "LINEAGE_ACTUAL_PREFLIGHT_REFERENCE_UNKNOWN",
                "An actual packet refers to a preflight identity outside the explicit lineage.",
                stage="lineage",
            )
        if (
            matching.future_actual_id != actual.actual_id
            or matching.outer_run_id != actual.outer_run_id
            or matching.payload_manifest_sha256
            != actual.accepted_payload_manifest_sha256
            or not os.path.samefile(
                matching.packet_path.parent,
                actual.accepted_preflight_root,
            )
            or not os.path.samefile(
                matching.receipt_path.parent,
                actual.accepted_preflight_output_root,
            )
            or not os.path.samefile(matching.receipt_path, actual.accepted_receipt_path)
            or matching is predecessor
            and actual.accepted_receipt_sha256 != receipt_sha256
            or matching is predecessor
            and actual.accepted_receipt_manifest_sha256 != receipt_manifest_sha256
        ):
            raise _fail(
                "LINEAGE_ACTUAL_PREFLIGHT_BINDING_CONTRADICTORY",
                "An actual packet contradicts its explicit preflight and receipt lineage.",
                stage="lineage",
            )
    predecessor_actuals = [
        record
        for record in actual_records
        if record.outer_run_id == predecessor.outer_run_id
        and record.actual_id == predecessor.future_actual_id
        and record.accepted_preflight_attempt_id == predecessor.attempt_id
        and record.accepted_preflight_id == predecessor.preflight_id
    ]
    if len(predecessor_actuals) != 1:
        raise _fail(
            "LINEAGE_PREDECESSOR_NOT_CONSUMED_ONCE",
            "The predecessor preflight is not bound to exactly one frozen actual packet.",
            stage="lineage",
        )
    if (
        predecessor.attempt_number
        != max(record.attempt_number for record in preflight_records)
        or predecessor.identity_sequence
        != max(record.identity_sequence for record in actual_records)
    ):
        raise _fail(
            "LINEAGE_PREDECESSOR_NOT_LATEST",
            "The final explicit preflight packet is not the latest frozen lineage item.",
            stage="lineage",
        )
    next_sequence = max(record.identity_sequence for record in actual_records) + 1
    if run_identities.identity_sequence != next_sequence:
        raise _fail(
            "LINEAGE_SEQUENCE_NOT_NEXT",
            "The requested canonical sequence is not the next value in explicit lineage.",
            stage="lineage",
            diagnostics={
                "requested_sequence": run_identities.identity_sequence,
                "required_sequence": next_sequence,
            },
        )
    next_attempt = (
        max(
            [record.attempt_number for record in preflight_records]
            + [record.preflight.attempt_number for record in reservation_records]
        )
        + 1
    )
    used = {
        "outer_run_id": run_identities.outer_run_id
        in {record.outer_run_id for record in (*preflight_records, *actual_records)},
        "future_actual_id": run_identities.future_actual_id
        in {
            *[record.future_actual_id for record in preflight_records],
            *[record.actual_id for record in actual_records],
        },
        "preflight_attempt_id": f"preflight_{next_attempt}"
        in {
            *[record.attempt_id for record in preflight_records],
            *[record.accepted_preflight_attempt_id for record in actual_records],
            *[
                record.preflight.attempt_id
                for record in reservation_records
            ],
        },
    }
    used_names = [name for name, present in used.items() if present]
    if used_names:
        raise _fail(
            "LINEAGE_IDENTITY_ALREADY_USED",
            "A derived identity is already present in the explicit lineage.",
            stage="lineage",
            diagnostics={"used_identities": used_names},
        )
    sources: list[dict[str, Any]] = []
    for record in preflight_records:
        sources.extend(
            (
                {
                    "role": "preflight_packet",
                    "path": record.packet_path.as_posix(),
                    "sha256": record.packet_sha256,
                },
                {
                    "role": "preflight_seal",
                    "path": record.preflight_path.as_posix(),
                    "sha256": record.preflight_sha256,
                },
            )
        )
    sources.extend(
        (
            {
                "role": "predecessor_receipt",
                "path": predecessor.receipt_path.as_posix(),
                "sha256": receipt_sha256,
            },
            {
                "role": "predecessor_receipt_manifest",
                "path": predecessor.receipt_manifest_path.as_posix(),
                "sha256": receipt_manifest_sha256,
            },
        )
    )
    for record in actual_records:
        sources.append(
            {
                "role": "actual_packet",
                "path": record.packet_path.as_posix(),
                "sha256": record.packet_sha256,
            }
        )
    for reservation in reservation_records:
        record = reservation.preflight
        sources.extend(
            (
                {
                    "role": "rejected_preflight_reservation_packet",
                    "path": record.packet_path.as_posix(),
                    "sha256": record.packet_sha256,
                },
                {
                    "role": "rejected_preflight_reservation_seal",
                    "path": record.preflight_path.as_posix(),
                    "sha256": record.preflight_sha256,
                },
                {
                    "role": "rejected_preflight_reservation_receipt",
                    "path": record.receipt_path.as_posix(),
                    "sha256": reservation.receipt_sha256,
                },
                {
                    "role": "rejected_preflight_reservation_receipt_manifest",
                    "path": record.receipt_manifest_path.as_posix(),
                    "sha256": reservation.receipt_manifest_sha256,
                },
            )
        )
    return _LineageAdmission(
        predecessor=predecessor,
        preflight_records=preflight_records,
        actual_records=actual_records,
        reservation_records=reservation_records,
        predecessor_receipt_sha256=receipt_sha256,
        predecessor_receipt_manifest_sha256=receipt_manifest_sha256,
        sources=tuple(sources),
    )


def _validate_packet_root(value: str) -> Path:
    selected = Path(value)
    if not selected.is_absolute() or ".." in selected.parts:
        raise _fail(
            "PACKET_ROOT_INVALID",
            "The new packet root must be absolute and normalized.",
            stage="output_root",
        )
    if selected.exists():
        raise _fail(
            "PACKET_ROOT_ALREADY_EXISTS",
            "The new packet root already exists and will not be overwritten.",
            stage="output_root",
        )
    try:
        parent = selected.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(
            "PACKET_ROOT_PARENT_MISSING",
            "The new packet root parent must already exist.",
            stage="output_root",
            diagnostics={"error_type": type(exc).__name__},
        ) from exc
    if not parent.is_dir() or parent.is_symlink():
        raise _fail(
            "PACKET_ROOT_PARENT_INVALID",
            "The new packet root parent must be a physical directory.",
            stage="output_root",
        )
    return parent / selected.name


def _read_current_facts(
    request: SealedPreflightPreparationRequestV1,
    dependencies: PreflightPreparationDependenciesV1,
) -> dict[str, Any]:
    try:
        platform_root = Path(request.platform_root).resolve(strict=True)
        source_root = Path(request.source_root).resolve(strict=True)
        target_project = Path(request.target_project).resolve(strict=True)
        git_identity = GitExecutableIdentityV1.read(request.git_executable)
        admission = StrictGitAdmission(
            executable_identity=git_identity,
            source_declared_root=request.source_root,
            source_canonical_root=source_root.as_posix(),
        )
        platform_head = admission.platform_text(platform_root, "rev-parse", "HEAD")
        platform_branch = admission.platform_text(
            platform_root,
            "branch",
            "--show-current",
        )
        platform_facts = admission.verify_platform(
            repository=platform_root,
            expected_head=platform_head,
            expected_branch=platform_branch,
            allowed_dirty_paths=request.allowed_dirty_paths,
        )
        observed_dirty_paths = {
            str(record["path"]) for record in platform_facts["dirty_records"]
        }
        if observed_dirty_paths != set(request.allowed_dirty_paths):
            raise ValueError(
                "Preflight preparation allowed dirty paths do not exactly match "
                "the current platform status."
            )
        project_root_path = target_project.relative_to(source_root)
        project_root = (
            "." if not project_root_path.parts else project_root_path.as_posix()
        )
        snapshot = source_snapshot(target_project)
        snapshot_hash = source_snapshot_sha256(snapshot)
        snapshot_by_path = {item["path"]: item for item in snapshot}
        project_file = _strict_posix_path(request.project_file, "project_file")
        primary_sources: list[dict[str, str]] = []
        for value in request.primary_source_paths:
            selected = _strict_posix_path(value, "primary_source_paths")
            selected_path = (source_root / Path(*selected.parts)).resolve(strict=True)
            relative = selected_path.relative_to(target_project).as_posix()
            entry = snapshot_by_path.get(relative)
            if entry is None:
                raise ValueError(
                    "Preflight preparation primary source is absent from snapshot."
                )
            primary_sources.append(
                {"path": selected.as_posix(), "sha256": str(entry["sha256"])}
            )
        repository_tree = admission.source_text(
            source_root,
            "rev-parse",
            "HEAD^{tree}",
        )
        project_tree = (
            repository_tree
            if project_root == "."
            else admission.source_text(
                source_root,
                "rev-parse",
                f"HEAD:{project_root}",
            )
        )
        source_binding = {
            "binding_version": "product_source_revision_binding_v2",
            "complete_snapshot_sha256": snapshot_hash,
            "repository_head": admission.source_text(
                source_root,
                "rev-parse",
                "HEAD",
            ),
            "repository_tree": repository_tree,
            "project_root": project_root,
            "project_file": project_file.as_posix(),
            "project_tree": project_tree,
            "primary_sources": primary_sources,
        }
        source_facts = admission.verify_source_revision_binding(
            source=target_project,
            snapshot=snapshot,
            snapshot_sha256=snapshot_hash,
            binding=source_binding,
        )
        model_identity = dependencies.model_identity_reader(
            request.ollama_base_url,
            request.ollama_model,
        )
        validate_ollama_model_identity(
            model_identity,
            expected_base_url=request.ollama_base_url,
            expected_model=request.ollama_model,
        )
        model_digest = model_identity.get("digest")
        if not _hash_string(model_digest):
            raise ValueError("Preflight preparation model digest is invalid.")
        model_details = model_identity.get("details")
        quantization_level = (
            model_details.get("quantization_level")
            if isinstance(model_details, Mapping)
            else None
        )
        if quantization_level is not None and (
            not isinstance(quantization_level, str) or not quantization_level
        ):
            raise ValueError("Preflight preparation model quantization is invalid.")
        server_version = dependencies.server_version_reader(request.ollama_base_url)
        if not isinstance(server_version, str) or not server_version:
            raise ValueError("Preflight preparation model server version is invalid.")
        context_limit = dependencies.context_validator(
            model_identity,
            requested_context_window=request.ollama_context_window,
        )
        if (
            isinstance(context_limit, bool)
            or not isinstance(context_limit, int)
            or context_limit <= 0
        ):
            raise ValueError("Preflight preparation model context limit is invalid.")
    except PreflightPreparationError:
        raise
    except Exception as exc:
        raise _fail(
            "CURRENT_FACT_ADMISSION_FAILED",
            "Current platform, source, Git, or model identity admission failed.",
            stage="current_facts",
            diagnostics={
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        ) from exc
    dirty_hashes: dict[str, str] = {}
    for record in platform_facts["dirty_records"]:
        path_text = record["path"]
        selected = (platform_root / Path(*PurePosixPath(path_text).parts)).resolve(
            strict=True
        )
        try:
            selected.relative_to(platform_root)
        except ValueError as exc:
            raise _fail(
                "PLATFORM_DIRTY_PATH_ESCAPE",
                "An allowed dirty path escapes the platform repository.",
                stage="current_facts",
            ) from exc
        if not selected.is_file():
            raise _fail(
                "PLATFORM_DIRTY_PATH_NOT_FILE",
                "An allowed dirty path is not a file.",
                stage="current_facts",
            )
        dirty_hashes[path_text] = _file_sha256(selected)
    return {
        "platform_root": platform_root,
        "platform_head": platform_head,
        "platform_branch": platform_branch,
        "platform_facts": platform_facts,
        "allowed_dirty_hashes": dirty_hashes,
        "source_root": source_root,
        "target_project": target_project,
        "snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "source_binding": source_binding,
        "source_facts": source_facts,
        "git_identity": git_identity,
        "model_identity": model_identity,
        "model_digest": model_digest,
        "quantization_level": quantization_level,
        "server_version": server_version,
        "context_limit": context_limit,
    }


def _runner_source() -> str:
    return '''from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_packet(packet_root: Path, expected_payload_manifest: str) -> dict[str, Any]:
    selected_root = packet_root.resolve(strict=True)
    preflight = json.loads(
        (selected_root / "PREFLIGHT.json").read_text(encoding="utf-8")
    )
    files = {
        "packet.json": _sha256(selected_root / "packet.json"),
        "sealed_entry_runner.py": _sha256(selected_root / "sealed_entry_runner.py"),
    }
    payload_manifest = _canonical_sha256(files)
    if payload_manifest != expected_payload_manifest:
        raise RuntimeError("PACKET_PAYLOAD_MANIFEST_ARGUMENT_DRIFT")
    if payload_manifest != preflight.get("payload_manifest_sha256"):
        raise RuntimeError("PACKET_PAYLOAD_MANIFEST_PREFLIGHT_DRIFT")
    for name, observed in files.items():
        if observed != (preflight.get("files", {}).get(name) or {}).get("sha256"):
            raise RuntimeError(f"PACKET_FILE_HASH_DRIFT:{name}")
    packet = json.loads((selected_root / "packet.json").read_text(encoding="utf-8"))
    if packet.get("packet_version") != "p2_thin_entry_admission_packet_v6":
        raise RuntimeError("PACKET_VERSION_DRIFT")
    delivery = packet.get("delivery") or {}
    if Path(delivery.get("packet_root_canonical_text", "")).resolve(strict=True) != selected_root:
        raise RuntimeError("PACKET_ROOT_DRIFT")
    future = packet.get("future_execution_binding") or {}
    match = re.fullmatch(r"(.+)_([0-9]{3})", str(packet.get("outer_run_id", "")))
    if match is None:
        raise RuntimeError("PACKET_OUTER_RUN_ID_INVALID")
    sequence = int(match.group(2))
    if (
        future.get("future_canary_number") != sequence
        or future.get("future_attempt_id") != f"actual_{sequence}"
    ):
        raise RuntimeError("PACKET_FUTURE_IDENTITY_DRIFT")
    return packet


def _unauthorized(packet: dict[str, Any], mode: str) -> int:
    code = "CANARY_NOT_AUTHORIZED" if mode == "canary" else "ACTUAL_NOT_AUTHORIZED"
    future = packet["future_execution_binding"]
    print(
        json.dumps(
            {
                "status": "blocked",
                "code": code,
                "mode": mode,
                "outer_run_id": packet["outer_run_id"],
                "attempt_id": packet["attempt_id"],
                "future_canary_number": future["future_canary_number"],
                "future_attempt_id": future["future_attempt_id"],
                "attempt_consumed": False,
                "execution_root_created": False,
                "model_calls": 0,
                "generation_calls": 0,
                "ProductExecution_runs": 0,
                "Builds": 0,
                "Runtime_runs": 0,
                "Apply_runs": 0,
                "actual_authorized": False,
                "canary_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("preflight-only", "canary", "actual"),
        required=True,
    )
    parser.add_argument("--packet-root", required=True)
    parser.add_argument("--payload-manifest-sha256", required=True)
    args = parser.parse_args()
    packet = _load_packet(Path(args.packet_root), args.payload_manifest_sha256)
    if args.mode in {"canary", "actual"}:
        return _unauthorized(packet, args.mode)
    from src.mod_agent.entry_admission import (
        EntryAdmissionDependenciesV1,
        admit_sealed_entry,
        entry_request_from_preflight_packet,
    )

    request = entry_request_from_preflight_packet(
        packet,
        payload_manifest_sha256=args.payload_manifest_sha256,
    )

    run = admit_sealed_entry(
        request,
        dependencies=EntryAdmissionDependenciesV1(
            git_admission=request.strict_git_admission()
        ),
        write_receipt=True,
    )
    print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if run.result.status == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_command(
    *,
    platform_root: Path,
    packet_root: Path,
    payload_manifest_sha256: str,
) -> str:
    return (
        "$env:PYTHONDONTWRITEBYTECODE='1'; "
        f"$env:PYTHONPATH={_powershell_quote(str(platform_root))}; "
        f"& {_powershell_quote(sys.executable)} -B "
        f"{_powershell_quote(str(packet_root / RUNNER_FILENAME))} "
        "--mode preflight-only "
        f"--packet-root {_powershell_quote(str(packet_root))} "
        f"--payload-manifest-sha256 {payload_manifest_sha256}"
    )


def _materialize_seal(packet_root: Path, files_to_write: Mapping[str, bytes]) -> None:
    created = False
    try:
        packet_root.mkdir(parents=False, exist_ok=False)
        created = True
    except FileExistsError as exc:
        raise _fail(
            "PACKET_ROOT_ALREADY_EXISTS",
            "The new packet root already exists and will not be overwritten.",
            stage="seal",
        ) from exc
    except OSError as exc:
        raise _fail(
            "PACKET_ROOT_CREATE_FAILED",
            "The new packet root could not be atomically claimed.",
            stage="seal",
            diagnostics={"error_type": type(exc).__name__},
        ) from exc
    try:
        for filename in SEALED_FILE_SET:
            selected = packet_root / filename
            with selected.open("xb") as handle:
                handle.write(files_to_write[filename])
        if {path.name for path in packet_root.iterdir()} != set(SEALED_FILE_SET):
            raise OSError("sealed file set drifted")
        if any(
            (packet_root / filename).read_bytes() != files_to_write[filename]
            for filename in SEALED_FILE_SET
        ):
            raise OSError("sealed file bytes drifted")
    except Exception as exc:
        if created:
            shutil.rmtree(packet_root)
        raise _fail(
            "PACKET_SEAL_WRITE_FAILED",
            "The five-file packet seal could not be completed and was removed.",
            stage="seal",
            diagnostics={"error_type": type(exc).__name__},
        ) from exc


def prepare_sealed_entry_preflight(
    request: SealedPreflightPreparationRequestV1,
    *,
    dependencies: PreflightPreparationDependenciesV1 | None = None,
) -> SealedPreflightPreparationResultV1:
    """Prepare one five-file, preflight-only seal without executing Entry Admission."""

    packet_root = _validate_packet_root(request.packet_root)
    run_identities = derive_run_identities(
        identity_series=request.identity_series,
        identity_sequence=request.identity_sequence,
    )
    try:
        lineage = _admit_lineage(request, run_identities)
    except PreflightPreparationError:
        raise
    except Exception as exc:
        raise _fail(
            "LINEAGE_ADMISSION_FAILED",
            "The explicit finite lineage could not be verified.",
            stage="lineage",
            diagnostics={"error_type": type(exc).__name__},
        ) from exc
    selected_dependencies = dependencies or PreflightPreparationDependenciesV1()
    current = _read_current_facts(request, selected_dependencies)
    if (
        request.selected_configuration.projection_contract_checkpoint
        != current["platform_head"]
    ):
        raise _fail(
            "PROJECTION_CONTRACT_CHECKPOINT_DRIFT",
            "Projection contract checkpoint must equal the current platform checkpoint.",
            stage="selected_configuration",
        )
    next_attempt_number = (
        max(
            [record.attempt_number for record in lineage.preflight_records]
            + [
                record.preflight.attempt_number
                for record in lineage.reservation_records
            ]
        )
        + 1
    )
    next_preflight_number = (
        max(
            [record.preflight_number for record in lineage.preflight_records]
            + [
                record.preflight.preflight_number
                for record in lineage.reservation_records
            ]
        )
        + 1
    )
    if next_preflight_number > 999:
        raise _fail(
            "PREFLIGHT_IDENTITY_SPACE_EXHAUSTED",
            "The three-digit preflight identity space is exhausted.",
            stage="identity_allocation",
        )
    preflight_attempt_id = f"preflight_{next_attempt_number}"
    preflight_id = (
        "entry_preflight_"
        f"{next_preflight_number:03d}_"
        f"{request.selected_configuration.configuration_id}_at_"
        f"{current['platform_head'][:8]}"
    )
    used_preflight_ids = {
        *[record.preflight_id for record in lineage.preflight_records],
        *[record.accepted_preflight_id for record in lineage.actual_records],
        *[
            record.preflight.preflight_id
            for record in lineage.reservation_records
        ],
    }
    if preflight_id in used_preflight_ids:
        raise _fail(
            "LINEAGE_PREFLIGHT_IDENTITY_ALREADY_USED",
            "The derived preflight identity is already present in explicit lineage.",
            stage="lineage",
        )
    identities = PreparedPreflightIdentitiesV1(
        **run_identities.to_dict(),
        preflight_attempt_id=preflight_attempt_id,
        preflight_id=preflight_id,
    )
    output_root = packet_root / f"fresh_preflight_root_{preflight_attempt_id}"
    entry_request_fields = [field.name for field in fields(EntryAdmissionRequestV1)]
    selected_configuration = {
        **request.selected_configuration.to_dict(),
        "configuration_source": "typed_input_and_current_platform_checkpoint",
        "model": request.ollama_model,
        "model_digest": current["model_digest"],
        "configured_num_ctx": request.ollama_context_window,
        "output_budget": request.ollama_output_budget,
        "canary_authorized": False,
    }
    rejected_reservations = [
        {
            "packet_path": record.preflight.packet_path.as_posix(),
            "packet_sha256": record.preflight.packet_sha256,
            "preflight_manifest_sha256": record.preflight.preflight_sha256,
            "receipt_sha256": record.receipt_sha256,
            "receipt_manifest_sha256": record.receipt_manifest_sha256,
            "attempt_id": record.preflight.attempt_id,
            "preflight_id": record.preflight.preflight_id,
            "future_run_identity_consumed": False,
        }
        for record in lineage.reservation_records
    ]
    packet = {
        "packet_version": "p2_thin_entry_admission_packet_v6",
        "preparation_owner": (
            "src.mod_agent.preflight_preparation.prepare_sealed_entry_preflight"
        ),
        "packet_date": request.packet_date,
        "task_id": request.task_id,
        "seal_revision": (
            f"{request.selected_configuration.configuration_id}_at_"
            f"{current['platform_head'][:8]}"
        ),
        "outer_run_id": identities.outer_run_id,
        "attempt_id": identities.preflight_attempt_id,
        "preflight_id": identities.preflight_id,
        "request": request.request_text,
        "identity_allocation": identities.to_dict(),
        "platform": {
            "repository_root": current["platform_root"].as_posix(),
            "branch": current["platform_branch"],
            "current_checkpoint": current["platform_head"],
            "allowed_dirty_paths": list(request.allowed_dirty_paths),
            "allowed_dirty_path_sha256_at_seal": current["allowed_dirty_hashes"],
        },
        "delivery": {
            "packet_root_text": str(packet_root),
            "packet_root_canonical_text": packet_root.as_posix(),
            "fresh_preflight_root_text": str(output_root),
            "fresh_preflight_root_canonical_text": output_root.as_posix(),
            "expected_receipt_path": (
                output_root / "entry_admission_receipt.json"
            ).as_posix(),
            "expected_receipt_manifest_path": (
                output_root / "entry_admission_receipt_manifest.json"
            ).as_posix(),
            "execution_root": None,
        },
        "source_identity": {
            "declared_root": request.source_root,
            "canonical_root": current["source_root"].as_posix(),
            "target_project": current["target_project"].as_posix(),
            "snapshot_sha256": current["snapshot_hash"],
            "snapshot_file_count": len(current["snapshot"]),
            "snapshot_files": current["snapshot"],
            "source_revision_binding": current["source_binding"],
        },
        "git_executable_identity": current["git_identity"].to_dict(),
        "model_identity": {
            "provider": "ollama",
            "base_url": request.ollama_base_url,
            "model": request.ollama_model,
            "digest": current["model_digest"],
            "quantization_level": current["quantization_level"],
            "server_version": current["server_version"],
            "context_limit": current["context_limit"],
            "configured_num_ctx": request.ollama_context_window,
            "num_predict": request.ollama_output_budget,
            "output_budget": request.ollama_output_budget,
            "local_only": True,
            "external_disclosure": False,
            "generation_authorized": False,
            "generation_calls": 0,
        },
        "selected_configuration": selected_configuration,
        "future_execution_binding": {
            "status": "preserved_as_non_authorizing_future_identity",
            "future_canary_number": identities.future_canary_number,
            "future_attempt_id": identities.future_actual_id,
            "attempt_consumed": False,
            "actual_authorized": False,
            "canary_authorized": False,
            "execution_root": None,
        },
        "identity_lineage": {
            "boundary": "explicit_finite_paths_only",
            "predecessor_packet_path": lineage.predecessor.packet_path.as_posix(),
            "predecessor_packet_sha256": lineage.predecessor.packet_sha256,
            "predecessor_payload_manifest_sha256": (
                lineage.predecessor.payload_manifest_sha256
            ),
            "predecessor_attempt_id": lineage.predecessor.attempt_id,
            "predecessor_preflight_id": lineage.predecessor.preflight_id,
            "predecessor_receipt_sha256": lineage.predecessor_receipt_sha256,
            "predecessor_receipt_manifest_sha256": (
                lineage.predecessor_receipt_manifest_sha256
            ),
            "rejected_preflight_identity_reservations": rejected_reservations,
            "rejected_reservation_policy": (
                "reserve_preflight_attempt_and_identity_only_without_consuming_"
                "future_run_identity"
            ),
            "unused_check_sources": [dict(item) for item in lineage.sources],
            "unused_checks": {
                "outer_run_id": "unused",
                "future_actual_id": "unused",
                "preflight_attempt_id": "unused",
                "preflight_id": "unused",
            },
        },
        "preflight_budget": {
            "outer_attempt_consumed": False,
            "model_calls": 0,
            "generation_calls": 0,
            "ProductExecution_runs": 0,
            "Builds": 0,
            "Runtime_runs": 0,
            "Apply_runs": 0,
            "execution_root_created": False,
            "apply_workspace_created": False,
        },
        "permissions": {
            "fresh_preflight_authorized": True,
            "canary_authorized": False,
            "actual_authorized": False,
            "local_model_identity_read": True,
            "local_model_generation": False,
            "external_source_disclosure": False,
            "platform_repository_write": False,
            "source_write": False,
            "ProductExecution": False,
            "Build": False,
            "Runtime": False,
            "Apply": False,
            "apply_workspace_creation": False,
            "diff_approval": False,
        },
        "delegation": {
            "entry_owner": "src.mod_agent.entry_admission.admit_sealed_entry",
            "request_contract": (
                "src.mod_agent.entry_admission.EntryAdmissionRequestV1"
            ),
            "request_contract_version": "1",
            "git_owner": "src.mod_agent.git.admission.StrictGitAdmission",
            "source_snapshot_owner": "src.mod_agent.product_executor.source_snapshot",
            "model_owner": "src.mod_agent.model_admission",
            "request_contract_fields": entry_request_fields,
            "runner_owns_git_parser": False,
            "runner_owns_model_admission": False,
            "runner_owns_receipt_state_machine": False,
            "runner_owns_retry": False,
        },
    }
    packet_bytes = _json_bytes(packet)
    runner_bytes = _runner_source().encode("utf-8")
    payload_files = {
        PACKET_FILENAME: hashlib.sha256(packet_bytes).hexdigest(),
        RUNNER_FILENAME: hashlib.sha256(runner_bytes).hexdigest(),
    }
    payload_manifest_sha256 = _canonical_json_sha256(payload_files)
    authorized_run_command = _build_command(
        platform_root=current["platform_root"],
        packet_root=packet_root,
        payload_manifest_sha256=payload_manifest_sha256,
    )
    run_text = (
        f"# Sealed Entry Preflight {preflight_attempt_id}\n\n"
        "Status: sealed for one preflight-only Entry Admission command; not executed.\n\n"
        f"Derived future identities: canary {identities.future_canary_number}, "
        f"`{identities.outer_run_id}`, `{identities.future_actual_id}`.\n\n"
        "Run only after separate review:\n\n"
        "```powershell\n"
        f"{authorized_run_command}\n"
        "```\n\n"
        "This command does not authorize model generation, ProductExecution, Build, "
        "Runtime, Apply, an Apply workspace, a canary, or an actual run.\n"
    )
    prompt_text = (
        f"# Fresh Entry Preflight Prompt: {preflight_attempt_id}\n\n"
        f"The sealed packet derives canary {identities.future_canary_number}, "
        f"`{identities.outer_run_id}`, and `{identities.future_actual_id}` from the "
        "single canonical sequence. Its explicit finite lineage has been hash-checked.\n\n"
        "If separately authorized, invoke exactly this preflight-only command once:\n\n"
        "```powershell\n"
        f"{authorized_run_command}\n"
        "```\n\n"
        "Freeze the first Entry Admission outcome. Do not retry, generate, enter "
        "ProductExecution, Build, Runtime, Apply, create an Apply workspace, or create "
        "a canary/actual task. Receipt review grants no later authority.\n"
    )
    run_bytes = run_text.encode("utf-8")
    prompt_bytes = prompt_text.encode("utf-8")
    delivery_files = {
        **payload_files,
        RUN_FILENAME: hashlib.sha256(run_bytes).hexdigest(),
        FRESH_PREFLIGHT_PROMPT_FILENAME: hashlib.sha256(prompt_bytes).hexdigest(),
    }
    delivery_manifest_sha256 = _canonical_json_sha256(delivery_files)
    preflight = {
        "preflight_version": "sealed_entry_preparation_v1",
        "status": "sealed_ready_for_preflight_only",
        "packet_sealed": True,
        "preflight_executed_at_seal": False,
        "canary_executed": False,
        "actual_executed": False,
        "identities": identities.to_dict(),
        "predecessor": {
            "attempt_id": lineage.predecessor.attempt_id,
            "preflight_id": lineage.predecessor.preflight_id,
            "packet_sha256": lineage.predecessor.packet_sha256,
            "receipt_sha256": lineage.predecessor_receipt_sha256,
            "receipt_manifest_sha256": (
                lineage.predecessor_receipt_manifest_sha256
            ),
        },
        "unused_identity_check": {
            "boundary": "explicit_finite_paths_only",
            "sources": [dict(item) for item in lineage.sources],
            "rejected_preflight_identity_reservations": rejected_reservations,
            "rejected_reservations_consume_future_run_identity": False,
            "outer_run_id": "unused",
            "future_actual_id": "unused",
            "preflight_attempt_id": "unused",
            "preflight_id": "unused",
        },
        "platform_identity_at_seal": {
            "root": current["platform_root"].as_posix(),
            "branch": current["platform_branch"],
            "HEAD": current["platform_head"],
            "allowed_dirty_paths": list(request.allowed_dirty_paths),
            "allowed_dirty_path_sha256": current["allowed_dirty_hashes"],
        },
        "source_identity_at_seal": {
            **current["source_facts"],
            "snapshot_file_count": len(current["snapshot"]),
        },
        "model_identity_at_seal": {
            "base_url": request.ollama_base_url,
            "model": request.ollama_model,
            "digest": current["model_digest"],
            "quantization_level": current["quantization_level"],
            "server_version": current["server_version"],
            "context_limit": current["context_limit"],
            "configured_context": request.ollama_context_window,
            "output_budget": request.ollama_output_budget,
            "generation_calls": 0,
        },
        "selected_configuration": selected_configuration,
        "entry_contract": {
            "request": "EntryAdmissionRequestV1",
            "request_contract_version": "1",
            "request_fields": entry_request_fields,
            "owner": "src.mod_agent.entry_admission.admit_sealed_entry",
            "strict_Git_owner": "src.mod_agent.git.admission.StrictGitAdmission",
            "shared_model_owner": "src.mod_agent.model_admission",
        },
        "fresh_preflight": {
            "authorized": True,
            "executed_at_seal": False,
            "outer_run_id": identities.outer_run_id,
            "attempt_id": identities.preflight_attempt_id,
            "preflight_id": identities.preflight_id,
            "authorized_run_command": authorized_run_command,
            "expected_receipt_path": (
                output_root / "entry_admission_receipt.json"
            ).as_posix(),
            "expected_receipt_manifest_path": (
                output_root / "entry_admission_receipt_manifest.json"
            ).as_posix(),
            "receipt_does_not_authorize_canary_or_actual": True,
        },
        "future_execution": {
            "canary_number": identities.future_canary_number,
            "outer_run_id": identities.outer_run_id,
            "attempt_id": identities.future_actual_id,
            "attempt_consumed": False,
            "canary_authorized": False,
            "actual_authorized": False,
            "runner_canary_mode": "structured_block_only",
            "runner_actual_mode": "structured_block_only",
            "model_generation": False,
            "ProductExecution": False,
            "Build": False,
            "Runtime": False,
            "Apply": False,
            "apply_workspace_creation": False,
            "execution_root": None,
        },
        "zero_authority_boundary": {
            "model_generation_calls": 0,
            "ProductExecution_runs": 0,
            "Builds": 0,
            "Runtime_runs": 0,
            "Apply_runs": 0,
            "execution_root_created": False,
            "apply_workspace_created": False,
            "canary_authorized": False,
            "actual_authorized": False,
        },
        "files": {
            name: {
                "sha256": digest,
                "bytes": {
                    PACKET_FILENAME: len(packet_bytes),
                    RUNNER_FILENAME: len(runner_bytes),
                    RUN_FILENAME: len(run_bytes),
                    FRESH_PREFLIGHT_PROMPT_FILENAME: len(prompt_bytes),
                }[name],
            }
            for name, digest in delivery_files.items()
        },
        "minimal_preflight_file_set": list(SEALED_FILE_SET),
        "payload_manifest_material": list(PAYLOAD_MANIFEST_MATERIAL),
        "payload_manifest_sha256": payload_manifest_sha256,
        "delivery_manifest_material": list(DELIVERY_MANIFEST_MATERIAL),
        "delivery_manifest_sha256": delivery_manifest_sha256,
    }
    preflight_bytes = _json_bytes(preflight)
    packet_sha256 = payload_files[PACKET_FILENAME]
    preflight_sha256 = hashlib.sha256(preflight_bytes).hexdigest()
    files_to_write = {
        PACKET_FILENAME: packet_bytes,
        RUNNER_FILENAME: runner_bytes,
        PREFLIGHT_FILENAME: preflight_bytes,
        RUN_FILENAME: run_bytes,
        FRESH_PREFLIGHT_PROMPT_FILENAME: prompt_bytes,
    }
    _materialize_seal(packet_root, files_to_write)
    audit_summary = (
        (
            f"Derived canary {identities.future_canary_number}, outer run "
            f"{identities.outer_run_id}, and future actual {identities.future_actual_id} "
            f"from series {identities.identity_series} sequence "
            f"{identities.identity_sequence}."
        ),
        (
            f"Advanced valid predecessor {lineage.predecessor.preflight_id} beyond "
            f"{len(lineage.reservation_records)} executed rejected preflight "
            f"reservation(s) to {identities.preflight_id} and attempt "
            f"{identities.preflight_attempt_id}."
        ),
        (
            f"Sealed typed route {request.selected_configuration.route}, main timeout "
            f"{float(request.selected_configuration.main_ollama_timeout_seconds)}, "
            "and the deterministic projection contract into packet payload bytes."
        ),
        (
            "Checked identity non-use only against the explicitly supplied, hash-bound "
            f"lineage sources ({len(lineage.sources)} files)."
        ),
        (
            f"Sealed packet SHA256 {packet_sha256}, "
            f"payload manifest {payload_manifest_sha256}, and delivery manifest "
            f"{delivery_manifest_sha256}."
        ),
        (
            "Granted no model generation, ProductExecution, Build, Runtime, Apply, "
            "Apply workspace, canary, or actual authority."
        ),
    )
    return SealedPreflightPreparationResultV1(
        status="sealed",
        packet_root=packet_root.as_posix(),
        identities=identities,
        predecessor_preflight_id=lineage.predecessor.preflight_id,
        lineage_sources=lineage.sources,
        sealed_files=SEALED_FILE_SET,
        packet_sha256=packet_sha256,
        preflight_sha256=preflight_sha256,
        payload_manifest_sha256=payload_manifest_sha256,
        delivery_manifest_sha256=delivery_manifest_sha256,
        authorized_run_command=authorized_run_command,
        audit_summary=audit_summary,
    )
