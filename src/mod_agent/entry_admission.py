"""Thin sealed-entry admission before run_local_request and ProductExecution."""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.mod_agent.git.admission import (
    GitAdmissionError,
    GitExecutableIdentityV1,
    StrictGitAdmission,
)
from src.mod_agent.model_admission import (
    ModelAdmissionError,
    read_ollama_model_identity,
    read_ollama_server_version,
    validate_ollama_context_window,
)

ENTRY_RECEIPT_FILENAME = "entry_admission_receipt.json"
ENTRY_RECEIPT_MANIFEST_FILENAME = "entry_admission_receipt_manifest.json"


def _hash_string(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _git_object_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is not None


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Entry admission {field} must be non-empty text.")
    return value


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


@dataclass(frozen=True)
class EntryAdmissionRequestV1:
    contract_version: Literal["1"]
    outer_run_id: str
    attempt_id: str
    payload_manifest_sha256: str
    packet_root_text: str
    packet_root_canonical_text: str
    output_root_text: str
    output_root_canonical_text: str
    platform_root: str
    platform_checkpoint: str
    platform_branch: str
    allowed_dirty_paths: tuple[str, ...]
    source_declared_root: str
    source_canonical_root: str
    target_project: str
    source_revision_binding: dict[str, Any]
    git_executable_identity: GitExecutableIdentityV1
    ollama_base_url: str
    ollama_model: str
    ollama_digest: str
    ollama_server_version: str
    ollama_context_window: int
    ollama_output_budget: int

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise ValueError("Entry admission request contract version is invalid.")
        for field in (
            "outer_run_id",
            "attempt_id",
            "packet_root_text",
            "packet_root_canonical_text",
            "output_root_text",
            "output_root_canonical_text",
            "platform_root",
            "platform_branch",
            "source_declared_root",
            "source_canonical_root",
            "target_project",
            "ollama_base_url",
            "ollama_model",
            "ollama_server_version",
        ):
            _required_text(getattr(self, field), field)
        if not _hash_string(self.payload_manifest_sha256):
            raise ValueError("Entry payload manifest SHA256 is invalid.")
        if not _git_object_id(self.platform_checkpoint):
            raise ValueError("Entry platform checkpoint is invalid.")
        if not _hash_string(self.ollama_digest):
            raise ValueError("Entry Ollama digest is invalid.")
        if (
            not isinstance(self.allowed_dirty_paths, tuple)
            or len(set(self.allowed_dirty_paths)) != len(self.allowed_dirty_paths)
            or any(not isinstance(item, str) or not item for item in self.allowed_dirty_paths)
        ):
            raise ValueError("Entry allowed dirty paths are invalid.")
        if not isinstance(self.source_revision_binding, dict):
            raise ValueError("Entry source revision binding is invalid.")
        for field in ("ollama_context_window", "ollama_output_budget"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"Entry {field} is invalid.")
        if self.ollama_context_window <= self.ollama_output_budget:
            raise ValueError("Entry Ollama context must exceed output budget.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "outer_run_id": self.outer_run_id,
            "attempt_id": self.attempt_id,
            "payload_manifest_sha256": self.payload_manifest_sha256,
            "packet_root_text": self.packet_root_text,
            "packet_root_canonical_text": self.packet_root_canonical_text,
            "output_root_text": self.output_root_text,
            "output_root_canonical_text": self.output_root_canonical_text,
            "platform_root": self.platform_root,
            "platform_checkpoint": self.platform_checkpoint,
            "platform_branch": self.platform_branch,
            "allowed_dirty_paths": list(self.allowed_dirty_paths),
            "source_declared_root": self.source_declared_root,
            "source_canonical_root": self.source_canonical_root,
            "target_project": self.target_project,
            "source_revision_binding": dict(self.source_revision_binding),
            "git_executable_identity": self.git_executable_identity.to_dict(),
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "ollama_digest": self.ollama_digest,
            "ollama_server_version": self.ollama_server_version,
            "ollama_context_window": self.ollama_context_window,
            "ollama_output_budget": self.ollama_output_budget,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EntryAdmissionRequestV1:
        expected = {
            "contract_version",
            "outer_run_id",
            "attempt_id",
            "payload_manifest_sha256",
            "packet_root_text",
            "packet_root_canonical_text",
            "output_root_text",
            "output_root_canonical_text",
            "platform_root",
            "platform_checkpoint",
            "platform_branch",
            "allowed_dirty_paths",
            "source_declared_root",
            "source_canonical_root",
            "target_project",
            "source_revision_binding",
            "git_executable_identity",
            "ollama_base_url",
            "ollama_model",
            "ollama_digest",
            "ollama_server_version",
            "ollama_context_window",
            "ollama_output_budget",
        }
        if set(value) != expected:
            raise ValueError("Entry admission request shape is invalid.")
        return cls(
            contract_version=value["contract_version"],
            outer_run_id=value["outer_run_id"],
            attempt_id=value["attempt_id"],
            payload_manifest_sha256=value["payload_manifest_sha256"],
            packet_root_text=value["packet_root_text"],
            packet_root_canonical_text=value["packet_root_canonical_text"],
            output_root_text=value["output_root_text"],
            output_root_canonical_text=value["output_root_canonical_text"],
            platform_root=value["platform_root"],
            platform_checkpoint=value["platform_checkpoint"],
            platform_branch=value["platform_branch"],
            allowed_dirty_paths=tuple(value["allowed_dirty_paths"]),
            source_declared_root=value["source_declared_root"],
            source_canonical_root=value["source_canonical_root"],
            target_project=value["target_project"],
            source_revision_binding=dict(value["source_revision_binding"]),
            git_executable_identity=GitExecutableIdentityV1.from_dict(
                value["git_executable_identity"]
            ),
            ollama_base_url=value["ollama_base_url"],
            ollama_model=value["ollama_model"],
            ollama_digest=value["ollama_digest"],
            ollama_server_version=value["ollama_server_version"],
            ollama_context_window=value["ollama_context_window"],
            ollama_output_budget=value["ollama_output_budget"],
        )

    def strict_git_admission(self) -> StrictGitAdmission:
        return StrictGitAdmission(
            executable_identity=self.git_executable_identity,
            source_declared_root=self.source_declared_root,
            source_canonical_root=self.source_canonical_root,
        )


def entry_request_from_preflight_packet(
    packet: Mapping[str, Any],
    *,
    payload_manifest_sha256: str,
) -> EntryAdmissionRequestV1:
    """Project one sealed preflight packet through the Entry request contract."""

    platform = packet["platform"]
    delivery = packet["delivery"]
    source = packet["source_identity"]
    model = packet["model_identity"]
    return EntryAdmissionRequestV1(
        contract_version="1",
        outer_run_id=packet["outer_run_id"],
        attempt_id=packet["attempt_id"],
        payload_manifest_sha256=payload_manifest_sha256,
        packet_root_text=delivery["packet_root_text"],
        packet_root_canonical_text=delivery["packet_root_canonical_text"],
        output_root_text=delivery["fresh_preflight_root_text"],
        output_root_canonical_text=delivery["fresh_preflight_root_canonical_text"],
        platform_root=platform["repository_root"],
        platform_checkpoint=platform["current_checkpoint"],
        platform_branch=platform["branch"],
        allowed_dirty_paths=tuple(platform["allowed_dirty_paths"]),
        source_declared_root=source["declared_root"],
        source_canonical_root=source["canonical_root"],
        target_project=source["target_project"],
        source_revision_binding=dict(source["source_revision_binding"]),
        git_executable_identity=GitExecutableIdentityV1.from_dict(
            packet["git_executable_identity"]
        ),
        ollama_base_url=model["base_url"],
        ollama_model=model["model"],
        ollama_digest=model["digest"],
        ollama_server_version=model["server_version"],
        ollama_context_window=model["configured_num_ctx"],
        ollama_output_budget=model["num_predict"],
    )


@dataclass(frozen=True)
class EntryAdmissionBlockerV1:
    stage: str
    code: str
    message: str
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "diagnostics": dict(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EntryAdmissionBlockerV1:
        if set(value) != {"stage", "code", "message", "diagnostics"}:
            raise ValueError("Entry admission blocker shape is invalid.")
        return cls(
            stage=_required_text(value["stage"], "blocker.stage"),
            code=_required_text(value["code"], "blocker.code"),
            message=_required_text(value["message"], "blocker.message"),
            diagnostics=dict(value["diagnostics"]),
        )


@dataclass(frozen=True)
class EntryAdmissionResultV1:
    contract_version: Literal["1"]
    status: Literal["ready", "blocked"]
    outer_run_id: str
    attempt_id: str
    payload_manifest_sha256: str
    packet_root_text: str
    output_root_text: str
    first_failure_stage: str | None
    first_failure_code: str | None
    first_failure_message: str | None
    blockers: tuple[EntryAdmissionBlockerV1, ...]
    gate_receipts: tuple[dict[str, Any], ...]
    attempt_consumed: Literal[False] = False
    model_calls: Literal[0] = 0
    ProductExecution_runs: Literal[0] = 0
    Builds: Literal[0] = 0
    execution_root_created: Literal[False] = False
    actual_authorized: Literal[False] = False

    def __post_init__(self) -> None:
        if self.contract_version != "1":
            raise ValueError("Entry admission result contract version is invalid.")
        if self.status == "ready":
            if (
                self.first_failure_stage is not None
                or self.first_failure_code is not None
                or self.first_failure_message is not None
                or self.blockers
            ):
                raise ValueError("Ready entry admission cannot carry failure facts.")
        elif self.status == "blocked":
            if (
                not self.first_failure_stage
                or not self.first_failure_code
                or not self.first_failure_message
                or not self.blockers
            ):
                raise ValueError("Blocked entry admission lacks first failure facts.")
        else:
            raise ValueError("Entry admission result status is invalid.")
        if (
            self.attempt_consumed is not False
            or self.model_calls != 0
            or self.ProductExecution_runs != 0
            or self.Builds != 0
            or self.execution_root_created is not False
            or self.actual_authorized is not False
        ):
            raise ValueError("Entry admission result crossed its no-effect boundary.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "status": self.status,
            "outer_run_id": self.outer_run_id,
            "attempt_id": self.attempt_id,
            "payload_manifest_sha256": self.payload_manifest_sha256,
            "packet_root_text": self.packet_root_text,
            "output_root_text": self.output_root_text,
            "first_failure_stage": self.first_failure_stage,
            "first_failure_code": self.first_failure_code,
            "first_failure_message": self.first_failure_message,
            "blockers": [item.to_dict() for item in self.blockers],
            "gate_receipts": [dict(item) for item in self.gate_receipts],
            "attempt_consumed": self.attempt_consumed,
            "model_calls": self.model_calls,
            "ProductExecution_runs": self.ProductExecution_runs,
            "Builds": self.Builds,
            "execution_root_created": self.execution_root_created,
            "actual_authorized": self.actual_authorized,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EntryAdmissionResultV1:
        expected = {
            "contract_version",
            "status",
            "outer_run_id",
            "attempt_id",
            "payload_manifest_sha256",
            "packet_root_text",
            "output_root_text",
            "first_failure_stage",
            "first_failure_code",
            "first_failure_message",
            "blockers",
            "gate_receipts",
            "attempt_consumed",
            "model_calls",
            "ProductExecution_runs",
            "Builds",
            "execution_root_created",
            "actual_authorized",
        }
        if set(value) != expected:
            raise ValueError("Entry admission result shape is invalid.")
        return cls(
            contract_version=value["contract_version"],
            status=value["status"],
            outer_run_id=value["outer_run_id"],
            attempt_id=value["attempt_id"],
            payload_manifest_sha256=value["payload_manifest_sha256"],
            packet_root_text=value["packet_root_text"],
            output_root_text=value["output_root_text"],
            first_failure_stage=value["first_failure_stage"],
            first_failure_code=value["first_failure_code"],
            first_failure_message=value["first_failure_message"],
            blockers=tuple(
                EntryAdmissionBlockerV1.from_dict(item) for item in value["blockers"]
            ),
            gate_receipts=tuple(dict(item) for item in value["gate_receipts"]),
            attempt_consumed=value["attempt_consumed"],
            model_calls=value["model_calls"],
            ProductExecution_runs=value["ProductExecution_runs"],
            Builds=value["Builds"],
            execution_root_created=value["execution_root_created"],
            actual_authorized=value["actual_authorized"],
        )


@dataclass(frozen=True)
class EntryAdmissionDependenciesV1:
    git_admission: StrictGitAdmission
    model_identity_reader: Callable[[str, str], dict[str, Any]] = (
        read_ollama_model_identity
    )
    server_version_reader: Callable[[str], str] = read_ollama_server_version
    context_validator: Callable[..., int] = validate_ollama_context_window


@dataclass(frozen=True)
class EntryAdmissionRunV1:
    result: EntryAdmissionResultV1
    receipt_path: str | None
    receipt_sha256: str | None
    receipt_manifest_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.to_dict(),
            "receipt_path": self.receipt_path,
            "receipt_sha256": self.receipt_sha256,
            "receipt_manifest_path": self.receipt_manifest_path,
        }


def _windows_leaf_identity(value: str) -> str:
    return unicodedata.normalize("NFC", ntpath.normcase(value))


def _validate_output_root(request: EntryAdmissionRequestV1) -> Path:
    packet_text = Path(request.packet_root_text)
    packet_canonical = Path(request.packet_root_canonical_text)
    output_text = Path(request.output_root_text)
    output_canonical = Path(request.output_root_canonical_text)
    for path in (packet_text, packet_canonical, output_text, output_canonical):
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("ENTRY_OUTPUT_ROOT_NOT_ABSOLUTE_OR_CONTAINED")
    if any(
        path.is_symlink()
        for path in (
            packet_text,
            packet_canonical,
            output_text.parent,
            output_canonical.parent,
        )
    ):
        raise ValueError("ENTRY_OUTPUT_ROOT_SYMLINK_FORBIDDEN")
    selected_packet = packet_text.resolve(strict=True)
    canonical_packet = packet_canonical.resolve(strict=True)
    if selected_packet != canonical_packet or not os.path.samefile(
        selected_packet, canonical_packet
    ):
        raise ValueError("ENTRY_PACKET_ROOT_PHYSICAL_IDENTITY_DRIFT")
    text_parent = output_text.parent.resolve(strict=True)
    canonical_parent = output_canonical.parent.resolve(strict=True)
    if (
        text_parent != selected_packet
        or canonical_parent != canonical_packet
        or not os.path.samefile(text_parent, canonical_parent)
    ):
        raise ValueError("ENTRY_OUTPUT_ROOT_PARENT_DRIFT")
    if _windows_leaf_identity(output_text.name) != _windows_leaf_identity(
        output_canonical.name
    ):
        raise ValueError("ENTRY_OUTPUT_ROOT_LEAF_DRIFT")
    selected = selected_packet / output_canonical.name
    if selected.exists():
        raise ValueError("ENTRY_OUTPUT_ROOT_ALREADY_EXISTS")
    return selected


def _blocked(
    request: EntryAdmissionRequestV1,
    *,
    stage: str,
    code: str,
    message: str,
    diagnostics: Mapping[str, Any] | None,
    gates: Sequence[Mapping[str, Any]],
) -> EntryAdmissionResultV1:
    blocker = EntryAdmissionBlockerV1(
        stage=stage,
        code=code,
        message=message,
        diagnostics=dict(diagnostics or {}),
    )
    return EntryAdmissionResultV1(
        contract_version="1",
        status="blocked",
        outer_run_id=request.outer_run_id,
        attempt_id=request.attempt_id,
        payload_manifest_sha256=request.payload_manifest_sha256,
        packet_root_text=request.packet_root_text,
        output_root_text=request.output_root_text,
        first_failure_stage=stage,
        first_failure_code=code,
        first_failure_message=message,
        blockers=(blocker,),
        gate_receipts=tuple(dict(item) for item in gates),
    )


def _write_receipt(
    request: EntryAdmissionRequestV1,
    result: EntryAdmissionResultV1,
    output_root: Path,
) -> EntryAdmissionRunV1:
    output_root.mkdir(parents=False, exist_ok=False)
    receipt_payload = {
        "receipt_version": "sealed_entry_admission_receipt_v1",
        "request_identity": {
            "outer_run_id": request.outer_run_id,
            "attempt_id": request.attempt_id,
            "payload_manifest_sha256": request.payload_manifest_sha256,
        },
        "packet_root_text": request.packet_root_text,
        "output_root_text": request.output_root_text,
        "result": result.to_dict(),
        "actual_authorized": False,
    }
    receipt_path = output_root / ENTRY_RECEIPT_FILENAME
    receipt_path.write_text(
        json.dumps(receipt_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    receipt_sha256 = _file_sha256(receipt_path)
    manifest_path = output_root / ENTRY_RECEIPT_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": "sealed_entry_admission_manifest_v1",
                "receipt_path": str(receipt_path),
                "receipt_sha256": receipt_sha256,
                "payload_manifest_sha256": request.payload_manifest_sha256,
                "actual_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return EntryAdmissionRunV1(
        result=result,
        receipt_path=str(receipt_path),
        receipt_sha256=receipt_sha256,
        receipt_manifest_path=str(manifest_path),
    )


def verify_entry_current_facts(
    request: EntryAdmissionRequestV1,
    *,
    dependencies: EntryAdmissionDependenciesV1 | None = None,
) -> tuple[dict[str, Any], ...]:
    """Revalidate the sealed platform, source, and model facts without writing."""

    selected_dependencies = dependencies or EntryAdmissionDependenciesV1(
        git_admission=request.strict_git_admission()
    )
    if selected_dependencies.git_admission != request.strict_git_admission():
        raise GitAdmissionError(
            "ENTRY_GIT_ADMISSION_IDENTITY_DRIFT",
            "Entry Git admission dependency drifted from request identity.",
        )
    platform = selected_dependencies.git_admission.verify_platform(
        repository=Path(request.platform_root),
        expected_head=request.platform_checkpoint,
        expected_branch=request.platform_branch,
        allowed_dirty_paths=request.allowed_dirty_paths,
    )
    gates: list[dict[str, Any]] = [
        {"gate": "platform", "decision": "passed", "facts": platform}
    ]

    from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256

    target_project = Path(request.target_project).resolve(strict=True)
    snapshot = source_snapshot(target_project)
    source = selected_dependencies.git_admission.verify_source_revision_binding(
        source=target_project,
        snapshot=snapshot,
        snapshot_sha256=source_snapshot_sha256(snapshot),
        binding=request.source_revision_binding,
    )
    gates.append({"gate": "source", "decision": "passed", "facts": source})

    identity = selected_dependencies.model_identity_reader(
        request.ollama_base_url, request.ollama_model
    )
    if identity.get("digest") != request.ollama_digest:
        raise ModelAdmissionError("OLLAMA_MODEL_DIGEST_DRIFT")
    version = selected_dependencies.server_version_reader(request.ollama_base_url)
    if version != request.ollama_server_version:
        raise ModelAdmissionError("OLLAMA_SERVER_VERSION_DRIFT")
    context_limit = selected_dependencies.context_validator(
        identity,
        requested_context_window=request.ollama_context_window,
    )
    gates.append(
        {
            "gate": "model",
            "decision": "passed",
            "facts": {
                "model": request.ollama_model,
                "digest": request.ollama_digest,
                "server_version": version,
                "context_limit": context_limit,
                "configured_context": request.ollama_context_window,
                "output_budget": request.ollama_output_budget,
                "generation_calls": 0,
            },
        }
    )
    return tuple(gates)


def admit_sealed_entry(
    request: EntryAdmissionRequestV1,
    *,
    dependencies: EntryAdmissionDependenciesV1 | None = None,
    write_receipt: bool = True,
) -> EntryAdmissionRunV1:
    """Return one total ready/blocked entry outcome without ProductExecution."""

    gates: list[dict[str, Any]] = []
    try:
        output_root = _validate_output_root(request)
    except Exception as exc:
        result = _blocked(
            request,
            stage="output_root",
            code=str(exc) or "ENTRY_OUTPUT_ROOT_INVALID",
            message="Entry output root physical identity is invalid.",
            diagnostics={"error_type": type(exc).__name__},
            gates=gates,
        )
        return EntryAdmissionRunV1(result, None, None, None)

    try:
        gates.extend(
            verify_entry_current_facts(request, dependencies=dependencies)
        )
    except GitAdmissionError as exc:
        result = _blocked(
            request,
            stage="git_admission",
            code=exc.code,
            message=str(exc),
            diagnostics=exc.diagnostics,
            gates=gates,
        )
    except ModelAdmissionError as exc:
        result = _blocked(
            request,
            stage="model_admission",
            code=str(exc),
            message="Read-only local model admission failed.",
            diagnostics={"error_type": type(exc).__name__},
            gates=gates,
        )
    except Exception as exc:
        result = _blocked(
            request,
            stage="entry_admission",
            code=f"ENTRY_ADMISSION_{type(exc).__name__.upper()}",
            message=str(exc) or type(exc).__name__,
            diagnostics={"error_type": type(exc).__name__},
            gates=gates,
        )
    else:
        result = EntryAdmissionResultV1(
            contract_version="1",
            status="ready",
            outer_run_id=request.outer_run_id,
            attempt_id=request.attempt_id,
            payload_manifest_sha256=request.payload_manifest_sha256,
            packet_root_text=request.packet_root_text,
            output_root_text=request.output_root_text,
            first_failure_stage=None,
            first_failure_code=None,
            first_failure_message=None,
            blockers=(),
            gate_receipts=tuple(gates),
        )
    if not write_receipt:
        return EntryAdmissionRunV1(result, None, None, None)
    try:
        return _write_receipt(request, result, output_root)
    except Exception as exc:
        receipt_result = _blocked(
            request,
            stage="receipt",
            code=f"ENTRY_RECEIPT_{type(exc).__name__.upper()}",
            message="Entry admission receipt could not be materialized.",
            diagnostics={"error_type": type(exc).__name__},
            gates=result.gate_receipts,
        )
        return EntryAdmissionRunV1(receipt_result, None, None, None)


def verify_entry_admission_receipt(
    request: EntryAdmissionRequestV1,
    *,
    receipt_path: str | Path,
    expected_sha256: str,
) -> EntryAdmissionResultV1:
    if not _hash_string(expected_sha256):
        raise ValueError("Entry receipt SHA256 is invalid.")
    output_root = Path(request.output_root_canonical_text).resolve(strict=True)
    selected = Path(receipt_path).resolve(strict=True)
    if selected.parent != output_root or not os.path.samefile(selected.parent, output_root):
        raise ValueError("Entry receipt physical path drifted.")
    if (
        _windows_leaf_identity(selected.name)
        != _windows_leaf_identity(ENTRY_RECEIPT_FILENAME)
        or _file_sha256(selected) != expected_sha256
    ):
        raise ValueError("Entry receipt identity drifted.")
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if set(payload) != {
        "receipt_version",
        "request_identity",
        "packet_root_text",
        "output_root_text",
        "result",
        "actual_authorized",
    }:
        raise ValueError("Entry receipt shape is invalid.")
    if (
        payload["receipt_version"] != "sealed_entry_admission_receipt_v1"
        or payload["actual_authorized"] is not False
        or payload["packet_root_text"] != request.packet_root_text
        or payload["output_root_text"] != request.output_root_text
        or payload["request_identity"]
        != {
            "outer_run_id": request.outer_run_id,
            "attempt_id": request.attempt_id,
            "payload_manifest_sha256": request.payload_manifest_sha256,
        }
    ):
        raise ValueError("Entry receipt semantic binding failed.")
    return EntryAdmissionResultV1.from_dict(payload["result"])
