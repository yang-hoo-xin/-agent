"""Receipt-bound Actual packet preparation and single-attempt execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from src.mod_agent.entry_admission import (
    EntryAdmissionDependenciesV1,
    EntryAdmissionRequestV1,
    entry_request_from_preflight_packet,
    verify_entry_current_facts,
)
from src.mod_agent.local_entry import (
    CompiledArtifactInspectionProfile,
    RunLocalGameFolderBindingV1,
    run_local_request,
)
from src.mod_agent.model_admission import (
    read_ollama_model_identity,
    read_ollama_server_version,
    validate_ollama_context_window,
)
from src.mod_agent.preflight_preparation import (
    _load_actual_record,
    _load_preflight_record,
    _read_json_object,
    _verify_preflight_receipt,
)


ACTUAL_PACKET_FILENAME = "packet.json"
ACTUAL_SEAL_FILENAME = "ACTUAL_SEAL.json"
ACTUAL_RUN_FILENAME = "RUN.md"
ACTUAL_CONSUMPTION_FILENAME = "actual_consumption.json"
ACTUAL_JOURNAL_FILENAME = "actual_journal.json"
ACTUAL_SEALED_FILE_SET = (
    ACTUAL_PACKET_FILENAME,
    ACTUAL_SEAL_FILENAME,
    ACTUAL_RUN_FILENAME,
)
ACTUAL_SEAL_MATERIAL = (
    ACTUAL_PACKET_FILENAME,
)


class ActualRunError(RuntimeError):
    """One Actual preparation or execution gate failed closed."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.stage = stage
        self.diagnostics = dict(diagnostics or {})


def _fail(code: str, message: str, *, stage: str) -> ActualRunError:
    return ActualRunError(code, message, stage=stage)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Actual run {field} must be non-empty text.")
    return value


def _absolute_normalized_path(value: object, field: str) -> str:
    selected = Path(_required_text(value, field))
    if not selected.is_absolute() or ".." in selected.parts:
        raise ValueError(f"Actual run {field} must be an absolute normalized path.")
    resolved = str(selected.resolve())
    if os.path.normcase(str(selected)) != os.path.normcase(resolved):
        raise ValueError(f"Actual run {field} must already be normalized.")
    return str(selected)


def _exact_fields(value: Mapping[str, Any], expected: tuple[str, ...], name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f"Actual run {name} fields changed.")


@dataclass(frozen=True)
class ActualProductExecutionSelectionV1:
    contract_version: Literal["1"]
    workspace_base: str
    settings_path: str
    requested_completion_scope: Literal["compile_only"]
    repair_ollama_model: None = None
    completion_classification: tuple[tuple[str, bool], ...] = ()
    objective_verification_command: tuple[str, ...] | None = None
    game_folder_build_binding: Mapping[str, Any] | None = None
    compiled_artifact_inspection_profile: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise ValueError("Actual ProductExecution selection version is invalid.")
        _absolute_normalized_path(self.workspace_base, "workspace_base")
        _absolute_normalized_path(self.settings_path, "settings_path")
        if self.requested_completion_scope != "compile_only":
            raise ValueError("Actual runner v1 supports compile_only ProductExecution.")
        if self.repair_ollama_model is not None:
            raise ValueError("Actual runner v1 does not select a Repair model override.")
        keys: list[str] = []
        for item in self.completion_classification:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("Actual completion classification is invalid.")
            key, flag = item
            keys.append(_required_text(key, "completion_classification key"))
            if type(flag) is not bool:
                raise ValueError("Actual completion classification value must be bool.")
        if keys != sorted(keys, key=lambda item: item.encode("utf-8")) or len(
            keys
        ) != len(set(keys)):
            raise ValueError("Actual completion classification must be sorted and unique.")
        if self.objective_verification_command is not None and (
            not isinstance(self.objective_verification_command, tuple)
            or not self.objective_verification_command
            or any(
                not isinstance(item, str) or not item
                for item in self.objective_verification_command
            )
        ):
            raise ValueError("Actual objective verification command is invalid.")
        if self.game_folder_build_binding is not None:
            binding = dict(self.game_folder_build_binding)
            _exact_fields(
                binding,
                (
                    "binding_version",
                    "source_root",
                    "snapshot_sha256",
                    "file_count",
                    "property_name",
                ),
                "game_folder_build_binding",
            )
            if binding["binding_version"] != "run_local_game_folder_binding_v1":
                raise ValueError("Actual GameFolder binding version is invalid.")
            RunLocalGameFolderBindingV1(
                source_root=binding["source_root"],
                snapshot_sha256=binding["snapshot_sha256"],
                file_count=binding["file_count"],
                property_name=binding["property_name"],
            )
        if self.compiled_artifact_inspection_profile is not None:
            profile = dict(self.compiled_artifact_inspection_profile)
            _exact_fields(
                profile,
                (
                    "project_path",
                    "method_symbol",
                    "expected_guid",
                    "expected_name",
                    "expected_version",
                    "timeout_seconds",
                ),
                "compiled_artifact_inspection_profile",
            )
            _absolute_normalized_path(profile["project_path"], "inspection project_path")
            for name in (
                "method_symbol",
                "expected_guid",
                "expected_name",
                "expected_version",
            ):
                _required_text(profile[name], f"inspection {name}")
            if type(profile["timeout_seconds"]) is not int or profile["timeout_seconds"] <= 0:
                raise ValueError("Actual inspection timeout is invalid.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "workspace_base": self.workspace_base,
            "settings_path": self.settings_path,
            "requested_completion_scope": self.requested_completion_scope,
            "repair_ollama_model": self.repair_ollama_model,
            "completion_classification": [
                [key, value] for key, value in self.completion_classification
            ],
            "objective_verification_command": (
                None
                if self.objective_verification_command is None
                else list(self.objective_verification_command)
            ),
            "game_folder_build_binding": (
                None
                if self.game_folder_build_binding is None
                else dict(self.game_folder_build_binding)
            ),
            "compiled_artifact_inspection_profile": (
                None
                if self.compiled_artifact_inspection_profile is None
                else dict(self.compiled_artifact_inspection_profile)
            ),
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "ActualProductExecutionSelectionV1":
        _exact_fields(
            value,
            (
                "contract_version",
                "workspace_base",
                "settings_path",
                "requested_completion_scope",
                "repair_ollama_model",
                "completion_classification",
                "objective_verification_command",
                "game_folder_build_binding",
                "compiled_artifact_inspection_profile",
            ),
            "ActualProductExecutionSelectionV1",
        )
        selected = dict(value)
        selected["completion_classification"] = tuple(
            tuple(item) for item in value["completion_classification"]
        )
        command = value["objective_verification_command"]
        selected["objective_verification_command"] = (
            None if command is None else tuple(command)
        )
        return cls(**selected)


@dataclass(frozen=True)
class ActualRunPreparationRequestV1:
    contract_version: Literal["1"]
    accepted_preflight_packet_path: str
    accepted_preflight_packet_sha256: str
    accepted_preflight_manifest_sha256: str
    accepted_payload_manifest_sha256: str
    accepted_receipt_path: str
    accepted_receipt_sha256: str
    accepted_receipt_manifest_path: str
    accepted_receipt_manifest_sha256: str
    product_execution: ActualProductExecutionSelectionV1

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise ValueError("Actual preparation request version is invalid.")
        for name in (
            "accepted_preflight_packet_path",
            "accepted_receipt_path",
            "accepted_receipt_manifest_path",
        ):
            _absolute_normalized_path(getattr(self, name), name)
        for name in (
            "accepted_preflight_packet_sha256",
            "accepted_preflight_manifest_sha256",
            "accepted_payload_manifest_sha256",
            "accepted_receipt_sha256",
            "accepted_receipt_manifest_sha256",
        ):
            if re.fullmatch(r"[0-9a-f]{64}", _required_text(getattr(self, name), name)) is None:
                raise ValueError(f"Actual run {name} is invalid.")
        if not isinstance(self.product_execution, ActualProductExecutionSelectionV1):
            raise ValueError("Actual ProductExecution selection is invalid.")

    @property
    def packet_root(self) -> str:
        preflight = _load_preflight_record(self.accepted_preflight_packet_path)
        return _deterministic_actual_packet_root(preflight).as_posix()

    @property
    def actual_lineage_packet_paths(self) -> tuple[str, ...]:
        packet = _read_json_object(
            Path(self.accepted_preflight_packet_path),
            "accepted preflight packet",
        )
        return tuple(
            record["packet_path"]
            for record in _actual_lineage_from_preflight_packet(packet)
        )


@dataclass(frozen=True)
class ActualRunSpecV1:
    contract_version: Literal["1"]
    packet_root: str
    outer_run_id: str
    actual_attempt_id: str
    request: str
    platform: Mapping[str, Any]
    source: Mapping[str, Any]
    git_executable_identity: Mapping[str, Any]
    model: Mapping[str, Any]
    selected_configuration: Mapping[str, Any]
    accepted_preflight: Mapping[str, Any]
    actual_lineage: tuple[Mapping[str, Any], ...]
    product_execution: ActualProductExecutionSelectionV1

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise ValueError("Actual run specification version is invalid.")
        _absolute_normalized_path(self.packet_root, "packet_root")
        _required_text(self.outer_run_id, "outer_run_id")
        _required_text(self.actual_attempt_id, "actual_attempt_id")
        _required_text(self.request, "request")
        if re.fullmatch(r"(.+)_([0-9]{3})", self.outer_run_id) is None:
            raise ValueError("Actual outer run identity is invalid.")
        match = re.fullmatch(r"actual_([1-9][0-9]*)", self.actual_attempt_id)
        if match is None or int(match.group(1)) != int(self.outer_run_id.rsplit("_", 1)[1]):
            raise ValueError("Actual run identities are inconsistent.")
        for name in (
            "platform",
            "source",
            "git_executable_identity",
            "model",
            "selected_configuration",
            "accepted_preflight",
        ):
            if not isinstance(getattr(self, name), Mapping):
                raise ValueError(f"Actual run {name} is invalid.")
        if not isinstance(self.actual_lineage, tuple):
            raise ValueError("Actual run lineage is invalid.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "packet_root": self.packet_root,
            "outer_run_id": self.outer_run_id,
            "actual_attempt_id": self.actual_attempt_id,
            "request": self.request,
            "platform": dict(self.platform),
            "source": dict(self.source),
            "git_executable_identity": dict(self.git_executable_identity),
            "model": dict(self.model),
            "selected_configuration": dict(self.selected_configuration),
            "accepted_preflight": dict(self.accepted_preflight),
            "actual_lineage": [dict(item) for item in self.actual_lineage],
            "product_execution": self.product_execution.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActualRunSpecV1":
        _exact_fields(
            value,
            (
                "contract_version",
                "packet_root",
                "outer_run_id",
                "actual_attempt_id",
                "request",
                "platform",
                "source",
                "git_executable_identity",
                "model",
                "selected_configuration",
                "accepted_preflight",
                "actual_lineage",
                "product_execution",
            ),
            "ActualRunSpecV1",
        )
        selected = dict(value)
        for name in (
            "platform",
            "source",
            "git_executable_identity",
            "model",
            "selected_configuration",
            "accepted_preflight",
        ):
            selected[name] = dict(value[name])
        selected["actual_lineage"] = tuple(
            dict(item) for item in value["actual_lineage"]
        )
        selected["product_execution"] = ActualProductExecutionSelectionV1.from_dict(
            value["product_execution"]
        )
        return cls(**selected)


@dataclass(frozen=True)
class ActualExecutionDependenciesV1:
    model_identity_reader: Callable[[str, str], dict[str, Any]] = read_ollama_model_identity
    server_version_reader: Callable[[str], str] = read_ollama_server_version
    context_validator: Callable[..., int] = validate_ollama_context_window
    execution_owner: Callable[..., dict[str, Any]] = run_local_request
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActualRunPreparationResultV1:
    status: Literal["sealed"]
    packet_root: str
    outer_run_id: str
    actual_attempt_id: str
    packet_sha256: str
    seal_sha256: str
    sealed_files: tuple[str, ...]
    run_command_requiring_separate_authorization: str
    semantic_compatibility_boundary: Literal[
        "repository_v6_fixture_identity_and_receipt_lineage_only"
    ]
    actual_authorized: Literal[False] = False
    model_generation_calls: Literal[0] = 0
    ProductExecution_runs: Literal[0] = 0
    Builds: Literal[0] = 0
    Apply_runs: Literal[0] = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "packet_root": self.packet_root,
            "outer_run_id": self.outer_run_id,
            "actual_attempt_id": self.actual_attempt_id,
            "packet_sha256": self.packet_sha256,
            "seal_sha256": self.seal_sha256,
            "sealed_files": list(self.sealed_files),
            "run_command_requiring_separate_authorization": (
                self.run_command_requiring_separate_authorization
            ),
            "semantic_compatibility_boundary": self.semantic_compatibility_boundary,
            "actual_authorized": self.actual_authorized,
            "model_generation_calls": self.model_generation_calls,
            "ProductExecution_runs": self.ProductExecution_runs,
            "Builds": self.Builds,
            "Apply_runs": self.Apply_runs,
        }


@dataclass(frozen=True)
class ActualRunResultV1:
    status: Literal["terminal", "failed"]
    outer_run_id: str
    actual_attempt_id: str
    consumption_path: str
    journal_path: str
    journal_sha256: str
    terminal: Mapping[str, Any]
    execution_owner_calls: Literal[1] = 1
    automatic_retry: Literal[False] = False
    provider_fallback: Literal[False] = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "outer_run_id": self.outer_run_id,
            "actual_attempt_id": self.actual_attempt_id,
            "consumption_path": self.consumption_path,
            "journal_path": self.journal_path,
            "journal_sha256": self.journal_sha256,
            "terminal": dict(self.terminal),
            "execution_owner_calls": self.execution_owner_calls,
            "automatic_retry": self.automatic_retry,
            "provider_fallback": self.provider_fallback,
        }


def _entry_dependencies(
    request: EntryAdmissionRequestV1,
    dependencies: ActualExecutionDependenciesV1,
) -> EntryAdmissionDependenciesV1:
    return EntryAdmissionDependenciesV1(
        git_admission=request.strict_git_admission(),
        model_identity_reader=dependencies.model_identity_reader,
        server_version_reader=dependencies.server_version_reader,
        context_validator=dependencies.context_validator,
    )


def _verify_current_facts(
    request: EntryAdmissionRequestV1,
    packet: Mapping[str, Any],
    dependencies: ActualExecutionDependenciesV1,
) -> None:
    gates = verify_entry_current_facts(
        request,
        dependencies=_entry_dependencies(request, dependencies),
    )
    platform_gate = next(item for item in gates if item["gate"] == "platform")
    dirty_records = platform_gate["facts"]["dirty_records"]
    expected_dirty = packet["platform"].get("allowed_dirty_path_sha256_at_seal")

    def dirty_drift() -> ActualRunError:
        return _fail(
            "ACTUAL_PLATFORM_DIRTY_BYTES_DRIFT",
            "Allowed dirty platform bytes changed after preflight.",
            stage="current_facts",
        )

    if not isinstance(dirty_records, list) or not isinstance(
        expected_dirty, Mapping
    ):
        raise dirty_drift()
    observed_paths: list[str] = []
    for item in dirty_records:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"path", "status"}
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or not isinstance(item.get("status"), str)
            or not item["status"]
        ):
            raise dirty_drift()
        observed_paths.append(item["path"])
    if len(observed_paths) != len(set(observed_paths)) or set(
        observed_paths
    ) != set(expected_dirty):
        raise dirty_drift()

    try:
        platform_root = Path(packet["platform"]["repository_root"]).resolve(
            strict=True
        )
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise dirty_drift() from exc
    for path_text in sorted(expected_dirty):
        digest = expected_dirty[path_text]
        if (
            not isinstance(path_text, str)
            or not path_text
            or "\\" in path_text
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise dirty_drift()
        relative = PurePosixPath(path_text)
        if (
            relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.as_posix() != path_text
        ):
            raise dirty_drift()
        try:
            selected = (platform_root / Path(*relative.parts)).resolve(strict=True)
            selected.relative_to(platform_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise dirty_drift() from exc
        if not selected.is_file() or _file_sha256(selected) != digest:
            raise dirty_drift()


def _validated_preflight(
    *,
    packet_path: str,
    expected_packet_sha256: str,
    expected_preflight_manifest_sha256: str,
    expected_payload_manifest_sha256: str,
    receipt_path: str,
    expected_receipt_sha256: str,
    receipt_manifest_path: str,
    expected_receipt_manifest_sha256: str,
) -> tuple[Any, dict[str, Any], str, str]:
    try:
        preflight = _load_preflight_record(packet_path)
        receipt_sha256, receipt_manifest_sha256 = _verify_preflight_receipt(
            preflight,
            receipt_path_value=receipt_path,
            receipt_manifest_path_value=receipt_manifest_path,
            require_ready=True,
        )
        packet = _read_json_object(preflight.packet_path, "accepted preflight packet")
        if (
            preflight.packet_sha256 != expected_packet_sha256
            or preflight.preflight_sha256 != expected_preflight_manifest_sha256
            or preflight.payload_manifest_sha256 != expected_payload_manifest_sha256
            or receipt_sha256 != expected_receipt_sha256
            or receipt_manifest_sha256 != expected_receipt_manifest_sha256
        ):
            raise ValueError("accepted preflight review hashes drifted")
    except Exception as exc:
        if isinstance(exc, ActualRunError):
            raise
        raise _fail(
            "ACTUAL_ACCEPTED_PREFLIGHT_INVALID",
            "Accepted preflight packet and receipt could not be verified.",
            stage="accepted_preflight",
        ) from exc
    return preflight, packet, receipt_sha256, receipt_manifest_sha256


def _lineage_records(paths: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for value in paths:
        try:
            record = _load_actual_record(value)
        except Exception as exc:
            raise _fail(
                "ACTUAL_LINEAGE_INVALID",
                "An explicit actual lineage packet could not be verified.",
                stage="lineage",
            ) from exc
        records.append(
            {
                "packet_path": record.packet_path.as_posix(),
                "packet_sha256": record.packet_sha256,
                "outer_run_id": record.outer_run_id,
                "actual_attempt_id": record.actual_id,
                "accepted_preflight_attempt_id": record.accepted_preflight_attempt_id,
                "accepted_preflight_id": record.accepted_preflight_id,
            }
        )
    return tuple(records)


def _actual_lineage_from_preflight_packet(
    packet: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    lineage = packet.get("identity_lineage")
    sources = lineage.get("unused_check_sources") if isinstance(lineage, Mapping) else None
    if not isinstance(sources, list):
        raise _fail(
            "ACTUAL_PREFLIGHT_LINEAGE_MISSING",
            "Accepted preflight packet lacks its sealed actual lineage sources.",
            stage="lineage",
        )
    paths: list[str] = []
    expected_hashes: dict[str, str] = {}
    for item in sources:
        if not isinstance(item, Mapping) or item.get("role") != "actual_packet":
            continue
        path = item.get("path")
        digest = item.get("sha256")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or path in expected_hashes
        ):
            raise _fail(
                "ACTUAL_PREFLIGHT_LINEAGE_INVALID",
                "Accepted preflight actual lineage source is invalid.",
                stage="lineage",
            )
        paths.append(path)
        expected_hashes[path] = digest
    records = _lineage_records(tuple(paths))
    if any(
        record["packet_sha256"] != expected_hashes[record["packet_path"]]
        for record in records
    ):
        raise _fail(
            "ACTUAL_PREFLIGHT_LINEAGE_HASH_DRIFT",
            "Accepted preflight actual lineage differs from its sealed hashes.",
            stage="lineage",
        )
    return records


def _deterministic_actual_packet_root(preflight: Any) -> Path:
    parent = preflight.packet_path.parent.parent.resolve(strict=True)
    leaf = f"actual_{preflight.outer_run_id}_{preflight.future_actual_id}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", leaf) is None:
        raise _fail(
            "ACTUAL_PACKET_ROOT_IDENTITY_INVALID",
            "Accepted future identity cannot form the deterministic Actual root.",
            stage="identity",
        )
    return parent / leaf


def _derive_spec(
    request: ActualRunPreparationRequestV1,
    *,
    dependencies: ActualExecutionDependenciesV1,
) -> ActualRunSpecV1:
    preflight, packet, receipt_sha256, receipt_manifest_sha256 = _validated_preflight(
        packet_path=request.accepted_preflight_packet_path,
        expected_packet_sha256=request.accepted_preflight_packet_sha256,
        expected_preflight_manifest_sha256=(
            request.accepted_preflight_manifest_sha256
        ),
        expected_payload_manifest_sha256=request.accepted_payload_manifest_sha256,
        receipt_path=request.accepted_receipt_path,
        expected_receipt_sha256=request.accepted_receipt_sha256,
        receipt_manifest_path=request.accepted_receipt_manifest_path,
        expected_receipt_manifest_sha256=(
            request.accepted_receipt_manifest_sha256
        ),
    )
    entry_request = entry_request_from_preflight_packet(
        packet,
        payload_manifest_sha256=preflight.payload_manifest_sha256,
    )
    try:
        _verify_current_facts(entry_request, packet, dependencies)
    except Exception as exc:
        if isinstance(exc, ActualRunError):
            raise
        raise _fail(
            "ACTUAL_CURRENT_FACT_ADMISSION_FAILED",
            "Platform, source, or model identity drifted before Actual preparation.",
            stage="current_facts",
        ) from exc
    lineage = _actual_lineage_from_preflight_packet(packet)
    if any(
        item["outer_run_id"] == preflight.outer_run_id
        or item["actual_attempt_id"] == preflight.future_actual_id
        for item in lineage
    ):
        raise _fail(
            "ACTUAL_IDENTITY_ALREADY_CONSUMED",
            "The accepted preflight future Actual identity is already present in lineage.",
            stage="identity",
        )
    model = packet["model_identity"]
    selected_configuration = packet["selected_configuration"]
    if selected_configuration.get("provider_fallback") is not False or selected_configuration.get(
        "automatic_retry"
    ) is not False or selected_configuration.get("external_disclosure") is not False:
        raise _fail(
            "ACTUAL_EXECUTION_POLICY_DRIFT",
            "The accepted preflight does not preserve the no-fallback/no-retry/local boundary.",
            stage="selected_configuration",
        )
    return ActualRunSpecV1(
        contract_version="1",
        packet_root=_deterministic_actual_packet_root(preflight).as_posix(),
        outer_run_id=preflight.outer_run_id,
        actual_attempt_id=preflight.future_actual_id,
        request=packet["request"],
        platform={
            "repository_root": packet["platform"]["repository_root"],
            "branch": packet["platform"]["branch"],
            "HEAD": packet["platform"]["current_checkpoint"],
            "allowed_dirty_paths": list(packet["platform"]["allowed_dirty_paths"]),
            "allowed_dirty_path_sha256": dict(
                packet["platform"]["allowed_dirty_path_sha256_at_seal"]
            ),
        },
        source={
            "declared_root": packet["source_identity"]["declared_root"],
            "canonical_root": packet["source_identity"]["canonical_root"],
            "target_project": packet["source_identity"]["target_project"],
            "snapshot_sha256": packet["source_identity"]["snapshot_sha256"],
            "source_revision_binding": dict(
                packet["source_identity"]["source_revision_binding"]
            ),
        },
        git_executable_identity=dict(packet["git_executable_identity"]),
        model={
            "provider": model["provider"],
            "base_url": model["base_url"],
            "model": model["model"],
            "digest": model["digest"],
            "quantization_level": model.get("quantization_level"),
            "server_version": model["server_version"],
            "context_limit": model["context_limit"],
            "configured_context": model["configured_num_ctx"],
            "output_budget": model["output_budget"],
            "local_only": model["local_only"],
        },
        selected_configuration=dict(selected_configuration),
        accepted_preflight={
            "packet_path": preflight.packet_path.as_posix(),
            "packet_sha256": preflight.packet_sha256,
            "preflight_manifest_path": preflight.preflight_path.as_posix(),
            "preflight_manifest_sha256": preflight.preflight_sha256,
            "payload_manifest_sha256": preflight.payload_manifest_sha256,
            "preflight_attempt_id": preflight.attempt_id,
            "preflight_id": preflight.preflight_id,
            "receipt_path": Path(request.accepted_receipt_path).resolve().as_posix(),
            "receipt_sha256": receipt_sha256,
            "receipt_manifest_path": Path(
                request.accepted_receipt_manifest_path
            ).resolve().as_posix(),
            "receipt_manifest_sha256": receipt_manifest_sha256,
            "receipt_status": "ready",
            "receipt_actual_authorized": False,
        },
        actual_lineage=lineage,
        product_execution=request.product_execution,
    )


def _run_command(
    packet_root: Path,
    *,
    packet_sha256: str,
    seal_sha256: str,
) -> str:
    return (
        "python -B -m src.main execute-sealed-actual "
        f"--packet-root '{packet_root}' "
        f"--expected-packet-sha256 {packet_sha256} "
        f"--expected-seal-sha256 {seal_sha256} "
        "--authorize-actual-execution"
    )


def _materialize(root: Path, files: Mapping[str, bytes]) -> None:
    try:
        root.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise _fail(
            "ACTUAL_PACKET_ROOT_ALREADY_EXISTS",
            "Actual packet root already exists and will not be overwritten.",
            stage="seal",
        ) from exc
    try:
        for name in ACTUAL_SEALED_FILE_SET:
            with (root / name).open("xb") as handle:
                handle.write(files[name])
        if {item.name for item in root.iterdir()} != set(ACTUAL_SEALED_FILE_SET):
            raise OSError("Actual sealed file set changed.")
    except Exception as exc:
        shutil.rmtree(root)
        raise _fail(
            "ACTUAL_PACKET_SEAL_WRITE_FAILED",
            "Actual packet seal could not be completed.",
            stage="seal",
        ) from exc


def prepare_sealed_actual_run(
    request: ActualRunPreparationRequestV1,
    *,
    dependencies: ActualExecutionDependenciesV1 | None = None,
) -> ActualRunPreparationResultV1:
    """Compile and seal an Actual spec without granting or starting execution."""

    selected_dependencies = dependencies or ActualExecutionDependenciesV1()
    spec = _derive_spec(request, dependencies=selected_dependencies)
    root = Path(spec.packet_root)
    if root.exists():
        raise _fail(
            "ACTUAL_PACKET_ROOT_ALREADY_EXISTS",
            "Actual packet root already exists and will not be overwritten.",
            stage="output_root",
        )
    try:
        parent = root.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(
            "ACTUAL_PACKET_PARENT_INVALID",
            "Actual packet parent must be an existing directory.",
            stage="output_root",
        ) from exc
    if not parent.is_dir():
        raise _fail(
            "ACTUAL_PACKET_PARENT_INVALID",
            "Actual packet parent must be an existing directory.",
            stage="output_root",
        )
    accepted = spec.accepted_preflight
    preflight_root = Path(accepted["packet_path"]).parent.resolve(strict=True)
    preflight_output_root = Path(accepted["receipt_path"]).parent.resolve(strict=True)
    packet_bytes = _json_bytes(
        {
            "packet_version": "p2_receipt_bound_actual_packet_v7",
            "outer_run_id": spec.outer_run_id,
            "actual_attempt_id": spec.actual_attempt_id,
            "accepted_entry_receipt": {
                "preflight_packet_root_text": str(preflight_root),
                "preflight_packet_root_canonical_text": preflight_root.as_posix(),
                "preflight_output_root_text": str(preflight_output_root),
                "preflight_output_root_canonical_text": preflight_output_root.as_posix(),
                "preflight_attempt_id": accepted["preflight_attempt_id"],
                "preflight_id": accepted["preflight_id"],
                "payload_manifest_sha256": accepted["payload_manifest_sha256"],
                "receipt_path": accepted["receipt_path"],
                "receipt_sha256": accepted["receipt_sha256"],
                "receipt_manifest_path": accepted["receipt_manifest_path"],
                "receipt_manifest_sha256": accepted["receipt_manifest_sha256"],
                "receipt_status": "ready",
                "receipt_actual_authorized": False,
                "macro_review": "accepted_for_execution_packet_preparation_only",
            },
            "seal_status": {
                "packet_prepared": True,
                "packet_sealed": True,
                "execution_root_created": False,
                "model_calls": 0,
                "ProductExecution_runs": 0,
                "Builds": 0,
                "Runtime_runs": 0,
            },
            "actual_run_spec": spec.to_dict(),
            "preparation_only": True,
            "actual_authorized": False,
            "execution_owner": "src.mod_agent.local_entry.run_local_request",
            "feature_spec_identity_owner": (
                "src.mod_agent.evidence.identity.feature_spec_payload_sha256"
            ),
        }
    )
    material = {
        ACTUAL_PACKET_FILENAME: hashlib.sha256(packet_bytes).hexdigest(),
    }
    seal_bytes = _json_bytes(
        {
            "seal_version": "sealed_actual_run_v1",
            "packet_sealed": True,
            "preparation_only": True,
            "actual_authorized": False,
            "spec_sha256": _canonical_sha256(spec.to_dict()),
            "files": material,
            "manifest_material": list(ACTUAL_SEAL_MATERIAL),
            "manifest_sha256": _canonical_sha256(material),
        }
    )
    seal_sha256 = hashlib.sha256(seal_bytes).hexdigest()
    command = _run_command(
        root,
        packet_sha256=material[ACTUAL_PACKET_FILENAME],
        seal_sha256=seal_sha256,
    )
    run_bytes = (
        "# Sealed Actual Run\n\n"
        "Status: prepared only; execution requires a later explicit user authorization.\n\n"
        "The receipt remains non-authorizing. When separately authorized, run:\n\n"
        f"```powershell\n{command}\n```\n"
    ).encode("utf-8")
    files = {
        ACTUAL_PACKET_FILENAME: packet_bytes,
        ACTUAL_SEAL_FILENAME: seal_bytes,
        ACTUAL_RUN_FILENAME: run_bytes,
    }
    _materialize(root, files)
    return ActualRunPreparationResultV1(
        status="sealed",
        packet_root=root.as_posix(),
        outer_run_id=spec.outer_run_id,
        actual_attempt_id=spec.actual_attempt_id,
        packet_sha256=material[ACTUAL_PACKET_FILENAME],
        seal_sha256=seal_sha256,
        sealed_files=ACTUAL_SEALED_FILE_SET,
        run_command_requiring_separate_authorization=command,
        semantic_compatibility_boundary=(
            "repository_v6_fixture_identity_and_receipt_lineage_only"
        ),
    )


def _load_sealed_spec(root_value: str | Path) -> ActualRunSpecV1:
    try:
        root = Path(root_value).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("not a directory")
        allowed = set(ACTUAL_SEALED_FILE_SET) | {
            ACTUAL_CONSUMPTION_FILENAME,
            ACTUAL_JOURNAL_FILENAME,
        }
        if any(path.name not in allowed for path in root.iterdir()):
            raise ValueError("unexpected actual packet file")
        seal_path = root / ACTUAL_SEAL_FILENAME
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        _exact_fields(
            seal,
            (
                "actual_authorized",
                "files",
                "manifest_material",
                "manifest_sha256",
                "packet_sealed",
                "preparation_only",
                "seal_version",
                "spec_sha256",
            ),
            "seal",
        )
        if (
            seal["seal_version"] != "sealed_actual_run_v1"
            or seal["packet_sealed"] is not True
            or seal["preparation_only"] is not True
            or seal["actual_authorized"] is not False
            or seal["manifest_material"] != list(ACTUAL_SEAL_MATERIAL)
        ):
            raise ValueError("actual seal semantic drift")
        if seal_path.read_bytes() != _json_bytes(seal):
            raise ValueError("actual seal canonical bytes drift")
        observed = {name: _file_sha256(root / name) for name in ACTUAL_SEAL_MATERIAL}
        if observed != seal["files"] or _canonical_sha256(observed) != seal[
            "manifest_sha256"
        ]:
            raise ValueError("actual seal file drift")
        packet = json.loads((root / ACTUAL_PACKET_FILENAME).read_text(encoding="utf-8"))
        _exact_fields(
            packet,
            (
                "accepted_entry_receipt",
                "actual_authorized",
                "actual_attempt_id",
                "actual_run_spec",
                "execution_owner",
                "feature_spec_identity_owner",
                "outer_run_id",
                "packet_version",
                "preparation_only",
                "seal_status",
            ),
            "packet",
        )
        if (
            packet["packet_version"] != "p2_receipt_bound_actual_packet_v7"
            or packet["preparation_only"] is not True
            or packet["actual_authorized"] is not False
            or packet["outer_run_id"] != packet["actual_run_spec"].get("outer_run_id")
            or packet["actual_attempt_id"]
            != packet["actual_run_spec"].get("actual_attempt_id")
            or packet["seal_status"].get("packet_sealed") is not True
            or packet["execution_owner"]
            != "src.mod_agent.local_entry.run_local_request"
            or packet["feature_spec_identity_owner"]
            != "src.mod_agent.evidence.identity.feature_spec_payload_sha256"
        ):
            raise ValueError("actual packet semantic drift")
        spec = ActualRunSpecV1.from_dict(packet["actual_run_spec"])
        if Path(spec.packet_root).resolve(strict=True) != root or _canonical_sha256(
            spec.to_dict()
        ) != seal["spec_sha256"]:
            raise ValueError("actual spec identity drift")
        return spec
    except ActualRunError:
        raise
    except Exception as exc:
        raise _fail(
            "ACTUAL_PACKET_SEAL_INVALID",
            "Actual packet, spec, or seal could not be verified.",
            stage="seal",
        ) from exc


def _request_from_spec(spec: ActualRunSpecV1) -> ActualRunPreparationRequestV1:
    accepted = spec.accepted_preflight
    return ActualRunPreparationRequestV1(
        contract_version="1",
        accepted_preflight_packet_path=accepted["packet_path"],
        accepted_preflight_packet_sha256=accepted["packet_sha256"],
        accepted_preflight_manifest_sha256=accepted["preflight_manifest_sha256"],
        accepted_payload_manifest_sha256=accepted["payload_manifest_sha256"],
        accepted_receipt_path=accepted["receipt_path"],
        accepted_receipt_sha256=accepted["receipt_sha256"],
        accepted_receipt_manifest_path=accepted["receipt_manifest_path"],
        accepted_receipt_manifest_sha256=accepted["receipt_manifest_sha256"],
        product_execution=spec.product_execution,
    )


def _execution_arguments(
    spec: ActualRunSpecV1,
    diff_approval_reader: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    selection = spec.product_execution
    game_binding = selection.game_folder_build_binding
    inspection = selection.compiled_artifact_inspection_profile
    return {
        "description": spec.request,
        "target_project": spec.source["target_project"],
        "workspace_base": selection.workspace_base,
        "settings_path": selection.settings_path,
        "confirm_isolated_write": True,
        "allow_build": True,
        "allow_source_disclosure": False,
        "run_gtfo_runtime": False,
        "allow_game_launch": False,
        "runtime_plugin_destination": None,
        "allow_game_directory_write": False,
        "diff_approval_reader": diff_approval_reader,
        "source_revision_binding": dict(spec.source["source_revision_binding"]),
        "source_git_admission": _entry_request_from_spec(spec).strict_git_admission(),
        "game_folder_build_binding": (
            None
            if game_binding is None
            else RunLocalGameFolderBindingV1(
                source_root=game_binding["source_root"],
                snapshot_sha256=game_binding["snapshot_sha256"],
                file_count=game_binding["file_count"],
                property_name=game_binding["property_name"],
            )
        ),
        "compiled_artifact_inspection_profile": (
            None
            if inspection is None
            else CompiledArtifactInspectionProfile(
                project_path=Path(inspection["project_path"]),
                method_symbol=inspection["method_symbol"],
                expected_guid=inspection["expected_guid"],
                expected_name=inspection["expected_name"],
                expected_version=inspection["expected_version"],
                timeout_seconds=inspection["timeout_seconds"],
            )
        ),
        "completion_classification": dict(selection.completion_classification),
        "local_ollama": True,
        "ollama_base_url": spec.model["base_url"],
        "ollama_model": spec.model["model"],
        "ollama_timeout_seconds": spec.selected_configuration[
            "main_ollama_timeout_seconds"
        ],
        "repair_ollama_model": selection.repair_ollama_model,
        "repair_ollama_timeout_seconds": spec.selected_configuration[
            "repair_ollama_timeout_seconds"
        ],
        "ollama_max_output_tokens": spec.model["output_budget"],
        "ollama_context_window": spec.model["configured_context"],
        "objective_verification_command": selection.objective_verification_command,
        "run_id": spec.outer_run_id,
        "request_id": spec.actual_attempt_id,
    }


def _entry_request_from_spec(spec: ActualRunSpecV1) -> EntryAdmissionRequestV1:
    accepted = spec.accepted_preflight
    packet = _read_json_object(
        Path(accepted["packet_path"]), "accepted preflight packet"
    )
    return entry_request_from_preflight_packet(
        packet,
        payload_manifest_sha256=accepted["payload_manifest_sha256"],
    )


def _terminal_projection(
    result: Mapping[str, Any],
) -> tuple[int | None, bool, str | None, dict[str, Any]]:
    reported_model_calls = result.get("model_call_count")
    accounting_complete = (
        type(reported_model_calls) is int and reported_model_calls >= 0
    )
    model_calls = reported_model_calls if accounting_complete else None
    audit = result.get("local_model_input_audit")
    model_role = (
        audit.get("model_role")
        if isinstance(audit, Mapping) and isinstance(audit.get("model_role"), str)
        else None
    )
    product = result.get("product_execution_result")
    if not isinstance(product, Mapping):
        return model_calls, accounting_complete, model_role, {
            "platform_status": None,
            "execution_disposition": None,
            "failure_stage": None,
            "terminal_node": result.get("current_stage"),
        }
    return model_calls, accounting_complete, model_role, {
        "platform_status": product.get("platform_status"),
        "execution_disposition": product.get("execution_disposition"),
        "failure_stage": product.get("failure_stage"),
        "terminal_node": product.get("terminal_node"),
    }


def execute_sealed_actual_run(
    packet_root: str | Path,
    *,
    expected_packet_sha256: str,
    expected_seal_sha256: str,
    actual_execution_authorized: bool,
    diff_approval_reader: Callable[[dict[str, Any]], str],
    dependencies: ActualExecutionDependenciesV1 | None = None,
) -> ActualRunResultV1:
    """Consume one authorized Actual identity and call run_local_request once."""

    if actual_execution_authorized is not True:
        raise _fail(
            "ACTUAL_EXECUTION_AUTHORIZATION_REQUIRED",
            "Actual execution requires a separate explicit user authorization.",
            stage="authorization",
        )
    if not callable(diff_approval_reader):
        raise _fail(
            "ACTUAL_DIFF_APPROVAL_READER_REQUIRED",
            "Actual execution requires the interactive exact diff reader.",
            stage="authorization",
        )
    if (
        re.fullmatch(r"[0-9a-f]{64}", expected_packet_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_seal_sha256) is None
    ):
        raise _fail(
            "ACTUAL_REVIEW_HASH_INVALID",
            "Actual execution requires exact reviewed packet and seal hashes.",
            stage="authorization",
        )
    try:
        reviewed_root = Path(packet_root).resolve(strict=True)
        if (
            _file_sha256(reviewed_root / ACTUAL_PACKET_FILENAME)
            != expected_packet_sha256
            or _file_sha256(reviewed_root / ACTUAL_SEAL_FILENAME)
            != expected_seal_sha256
        ):
            raise ValueError("reviewed hash drift")
    except Exception as exc:
        raise _fail(
            "ACTUAL_REVIEW_HASH_DRIFT",
            "Actual packet or seal differs from the separately reviewed hashes.",
            stage="authorization",
        ) from exc
    selected_dependencies = dependencies or ActualExecutionDependenciesV1()
    spec = _load_sealed_spec(packet_root)
    root = Path(spec.packet_root).resolve(strict=True)
    consumption_path = root / ACTUAL_CONSUMPTION_FILENAME
    journal_path = root / ACTUAL_JOURNAL_FILENAME
    if consumption_path.exists():
        raise _fail(
            "ACTUAL_IDENTITY_ALREADY_CONSUMED",
            "Actual identity was consumed before an earlier execution attempt.",
            stage="consumption",
        )
    if journal_path.exists():
        raise _fail(
            "ACTUAL_JOURNAL_ALREADY_EXISTS",
            "Actual terminal journal path already exists before execution.",
            stage="journal",
        )
    expected = _derive_spec(
        _request_from_spec(spec),
        dependencies=selected_dependencies,
    )
    if expected != spec:
        raise _fail(
            "ACTUAL_SPEC_REVALIDATION_DRIFT",
            "Receipt, manifest, lineage, platform, source, or model binding drifted.",
            stage="revalidation",
        )
    consumption = {
        "consumption_version": "actual_identity_consumption_v1",
        "outer_run_id": spec.outer_run_id,
        "actual_attempt_id": spec.actual_attempt_id,
        "spec_sha256": _canonical_sha256(spec.to_dict()),
        "status": "consumed_before_execution",
    }
    try:
        journal_handle = journal_path.open("xb")
    except FileExistsError as exc:
        raise _fail(
            "ACTUAL_JOURNAL_ALREADY_EXISTS",
            "Actual terminal journal path was concurrently claimed.",
            stage="journal",
        ) from exc
    journal_handle.write(
        _json_bytes(
            {
                "journal_version": "actual_run_journal_reservation_v1",
                "outer_run_id": spec.outer_run_id,
                "actual_attempt_id": spec.actual_attempt_id,
                "status": "reserved_before_execution",
                "terminal_summary_complete": False,
            }
        )
    )
    journal_handle.flush()
    try:
        with consumption_path.open("xb") as handle:
            handle.write(_json_bytes(consumption))
    except FileExistsError as exc:
        journal_handle.close()
        journal_path.unlink()
        raise _fail(
            "ACTUAL_IDENTITY_ALREADY_CONSUMED",
            "Actual identity was concurrently consumed by another execution.",
            stage="consumption",
        ) from exc
    started = selected_dependencies.clock().astimezone(timezone.utc).isoformat()
    try:
        owner_result = selected_dependencies.execution_owner(
            **_execution_arguments(spec, diff_approval_reader)
        )
        (
            model_calls,
            model_call_accounting_complete,
            model_role,
            terminal,
        ) = _terminal_projection(owner_result)
        status: Literal["terminal", "failed"] = "terminal"
    except Exception as exc:
        model_calls = None
        model_call_accounting_complete = False
        model_role = None
        terminal = {
            "status": "owner_exception",
            "exception_type": type(exc).__name__,
        }
        status = "failed"
    finished = selected_dependencies.clock().astimezone(timezone.utc).isoformat()
    journal = {
        "journal_version": "actual_run_journal_v1",
        "outer_run_id": spec.outer_run_id,
        "actual_attempt_id": spec.actual_attempt_id,
        "accepted_receipt_sha256": spec.accepted_preflight["receipt_sha256"],
        "accepted_receipt_manifest_sha256": spec.accepted_preflight[
            "receipt_manifest_sha256"
        ],
        "execution_owner": "src.mod_agent.local_entry.run_local_request",
        "execution_owner_calls": 1,
        "started_at": started,
        "finished_at": finished,
        "model_calls": model_calls,
        "model_call_accounting_complete": model_call_accounting_complete,
        "last_observed_model_role": model_role,
        "stage": terminal.get("terminal_node") or terminal.get("status"),
        "automatic_retry": False,
        "provider_fallback": False,
        "terminal": terminal,
        "raw_prompt_persisted": False,
        "raw_reasoning_persisted": False,
        "source_text_persisted": False,
        "terminal_summary_complete": True,
    }
    journal_handle.seek(0)
    journal_handle.truncate()
    journal_handle.write(_json_bytes(journal))
    journal_handle.flush()
    journal_handle.close()
    return ActualRunResultV1(
        status=status,
        outer_run_id=spec.outer_run_id,
        actual_attempt_id=spec.actual_attempt_id,
        consumption_path=consumption_path.as_posix(),
        journal_path=journal_path.as_posix(),
        journal_sha256=_file_sha256(journal_path),
        terminal=terminal,
    )
