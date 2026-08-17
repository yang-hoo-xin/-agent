"""Public same-invocation product executor for the existing StateGraph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactWriteResult
from src.mod_agent.domain import GTFOAdapter, UnsupportedDomainAdapter
from src.mod_agent.execution import ExactDiffApprovalRejectedError
from src.mod_agent.runtime import (
    GTFORuntimeAutomationError,
    build_gtfo_runtime_capability_report,
    build_gtfo_stagger_acceptance_report,
    profile_from_settings,
    stagger_profile_from_settings,
)
from src.mod_agent.product_execution import (
    PRODUCT_EXECUTION_DECLARATION,
    ProductBuildCompletionV1,
    ProductExecutionBlockerV1,
    ProductExecutionContractError,
    ProductExecutionEffectEventV1,
    ProductExecutionFactsV1,
    ProductExecutionGraphModeV1,
    ProductExecutionInputBindingV1,
    ProductExecutionOutputV1,
    ProductExecutionPreflightResultV1,
    ProductExecutionRequestV1,
    ProductExecutionResultV1,
    ProductExecutionStoreAttemptV1,
    ProductExecutionValidationDetailV1,
    ProductExecutionValidationFactsV1,
    ProductRuntimeCompletionV1,
    project_product_execution_result,
)
from src.mod_agent.workflow.graph import build_graph
from src.mod_agent.workflow.state import create_initial_state


SOURCE_DISCLOSURE_DATA_CLASSES = (
    "natural_language_request",
    "retrieved_local_source_excerpts",
    "run_local_api_member_metadata_facts",
    "binding_registry",
    "side_effect_boundaries",
)


class LocalEntryError(RuntimeError):
    """Raised when the active local product entry cannot proceed."""


class _ProductExecutionAdmissionError(ProductExecutionContractError):
    """A well-formed product request failed semantic admission."""


def _sanitized_endpoint_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    parsed = urlsplit(base_url)
    if not parsed.scheme or parsed.hostname is None:
        raise LocalEntryError("Configured LLM base_url is not a valid absolute URL.")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    try:
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError as exc:
        raise LocalEntryError("Configured LLM base_url has an invalid port.") from exc
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _verify_source_revision_binding(
    *,
    source: Path,
    snapshot: list[dict[str, Any]],
    snapshot_sha256: str,
    binding: Mapping[str, str] | None,
) -> None:
    if binding is None:
        return
    if binding.get("complete_snapshot_sha256") != snapshot_sha256:
        raise LocalEntryError(
            "Canonical source complete snapshot SHA256 does not match binding."
        )
    plugin_entry = next(
        (item for item in snapshot if item.get("path") == "Plugin.cs"), None
    )
    if plugin_entry is None:
        raise LocalEntryError("Canonical source binding requires Plugin.cs.")
    if binding.get("plugin_cs_sha256") != plugin_entry.get("sha256"):
        raise LocalEntryError(
            "Canonical source Plugin.cs SHA256 does not match binding."
        )
    if not binding.get("repository_head") or not binding.get("subtree_tree"):
        raise LocalEntryError(
            "Canonical source binding requires repository_head and subtree_tree."
        )


def _source_disclosure_record(
    *,
    provider: str,
    model: str,
    base_url: str | None,
    approved_at: str,
    approval_id: str | None = None,
    provider_adapter: str | None = None,
    destination_url: str | None = None,
) -> dict[str, Any]:
    return {
        "approved": True,
        "approved_at": approved_at,
        "approval_id": approval_id,
        "approval_actor_type": "local_cli_invoker",
        "consent_mechanism": "--allow-source-disclosure",
        "provider_adapter": provider_adapter,
        "destination": {
            "provider": provider,
            "model": model,
            "base_url": _sanitized_endpoint_url(base_url),
            "request_url": _sanitized_endpoint_url(destination_url),
        },
        "approved_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "requested_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "scope": "this_run_only",
    }


def _local_no_external_disclosure_record() -> dict[str, Any]:
    return {
        "occurred": False,
        "approved": False,
        "approved_at": None,
        "approval_id": None,
        "approval_actor_type": None,
        "consent_mechanism": None,
        "provider_adapter": None,
        "destination": None,
        "approved_data_classes": [],
        "requested_data_classes": [],
        "scope": "this_run_only",
        "reason": "local_model_execution",
    }


def _local_model_admission_record(
    *, model_identity: Mapping[str, Any], provider_adapter: str
) -> dict[str, Any]:
    base_url = str(model_identity["base_url"])
    return {
        "provider": "ollama",
        "model": str(model_identity["name"]),
        "model_digest": str(model_identity["digest"]),
        "provider_adapter": provider_adapter,
        "execution_locality": "local",
        "base_url": base_url,
        "destination": f"{base_url}/api/chat",
        "external_disclosure_occurred": False,
        "api_key_required": False,
        "api_key_read": False,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "machine_local",
    }


def _external_model_admission_record(
    source_disclosure: Mapping[str, Any],
) -> dict[str, Any]:
    destination = source_disclosure.get("destination")
    destination_data = destination if isinstance(destination, dict) else {}
    return {
        "provider": destination_data.get("provider"),
        "model": destination_data.get("model"),
        "model_digest": None,
        "provider_adapter": source_disclosure.get("provider_adapter"),
        "execution_locality": "external",
        "base_url": destination_data.get("base_url"),
        "destination": destination_data.get("request_url"),
        "external_disclosure_occurred": True,
        "api_key_required": True,
        "api_key_read": True,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "external_provider",
    }


def _runtime_admission_record(
    settings: Any,
    *,
    run_gtfo_runtime: bool,
    allow_game_launch: bool,
    runtime_plugin_destination: str | Path | None,
    allow_game_directory_write: bool,
    acceptance_criteria: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Bind one run's requested Runtime boundary before any mutable action."""

    runtime = getattr(settings, "runtime", None)
    gtfo = getattr(runtime, "gtfo", None)
    settings_enabled = bool(gtfo is not None and getattr(gtfo, "enabled", False))
    if allow_game_launch and not run_gtfo_runtime:
        raise LocalEntryError(
            "--allow-game-launch requires --run-gtfo-runtime for the same run."
        )
    if (runtime_plugin_destination is not None or allow_game_directory_write) and not run_gtfo_runtime:
        raise LocalEntryError(
            "Runtime plugin deployment requires --run-gtfo-runtime for the same run."
        )
    if not run_gtfo_runtime:
        return {
            "requested": False,
            "evidence_source": None,
            "allow_game_launch": False,
            "authorization_scope": None,
            "settings_enabled": settings_enabled,
            "profile": None,
            "capability_report": None,
            "plugin_deployment": {
                "requested": False,
                "destination_path": None,
                "allow_game_directory_write": False,
                "restore_after_runtime": False,
                "performed_by_run_request": False,
                "verified_deployed_artifact_hash": False,
            },
        }
    if not settings_enabled:
        raise LocalEntryError(
            "--run-gtfo-runtime requires runtime.gtfo.enabled=true in the selected settings file."
        )
    if runtime_plugin_destination is None:
        raise LocalEntryError(
            "--run-gtfo-runtime requires --runtime-plugin-destination so the physical DLL loaded by GTFO can be bound to this run's Build."
        )
    if not allow_game_directory_write:
        raise LocalEntryError(
            "--run-gtfo-runtime requires --allow-game-directory-write for run-scoped plugin deployment and restoration."
        )
    try:
        profile = profile_from_settings(settings)
        capability_report = build_gtfo_runtime_capability_report(
            profile,
            allow_game_launch=allow_game_launch,
            acceptance_criteria=acceptance_criteria,
        )
    except GTFORuntimeAutomationError as exc:
        raise LocalEntryError(f"GTFO Runtime admission failed: {exc}") from exc
    if capability_report["status"] != "ready":
        raise LocalEntryError(
            "GTFO Runtime admission blocked: "
            + "; ".join(str(item) for item in capability_report["blockers"])
        )
    destination_input = Path(runtime_plugin_destination)
    if not destination_input.is_absolute():
        raise LocalEntryError(
            "--runtime-plugin-destination must be an absolute .dll path."
        )
    destination = destination_input.resolve()
    working_directory = Path(profile.working_directory).resolve()
    try:
        destination.relative_to(working_directory)
    except ValueError as exc:
        raise LocalEntryError(
            "--runtime-plugin-destination must remain inside the configured runtime.gtfo.working_directory."
        ) from exc
    if destination.suffix.lower() != ".dll":
        raise LocalEntryError(
            "--runtime-plugin-destination must identify one .dll file."
        )
    if not destination.parent.is_dir():
        raise LocalEntryError(
            f"Runtime plugin destination directory does not exist: {destination.parent}"
        )
    if profile.terminate_after_capture is not True:
        raise LocalEntryError(
            "Run-scoped plugin deployment requires runtime.gtfo.terminate_after_capture=true before launch."
        )
    stagger_profile = stagger_profile_from_settings(settings)
    stagger_acceptance = None
    if stagger_profile is not None:
        if profile.operator_completion_required is not True:
            raise LocalEntryError(
                "Two-process stagger Runtime requires runtime.gtfo.operator_completion_required=true."
            )
        stagger_acceptance = build_gtfo_stagger_acceptance_report(
            stagger_profile,
            working_directory=profile.working_directory,
            acceptance_criteria=acceptance_criteria,
        )
        if stagger_acceptance["status"] != "ready":
            raise LocalEntryError(
                "GTFO stagger Runtime admission blocked: "
                + "; ".join(str(item) for item in stagger_acceptance["blockers"])
            )
    return {
        "requested": True,
        "evidence_source": "gtfo_real_runtime_automation",
        "capability_scope": "runtime_harness_preflight",
        "allow_game_launch": allow_game_launch,
        "authorization_scope": "this_run_only" if allow_game_launch else None,
        "settings_enabled": True,
        "profile": {
            "profile_id": profile.profile_id,
            "game_executable": profile.game_executable,
            "working_directory": profile.working_directory,
            "launch_args": list(profile.launch_args),
            "log_paths": list(profile.log_paths),
            "screenshot_directory": profile.screenshot_directory,
            "screenshot_timeout_seconds": profile.screenshot_timeout_seconds,
            "startup_markers": list(profile.startup_markers),
            "acceptance_markers": dict(profile.acceptance_markers),
            "timeout_seconds": profile.timeout_seconds,
            "poll_interval_seconds": profile.poll_interval_seconds,
            "output_limit_chars": profile.output_limit_chars,
            "terminate_after_capture": profile.terminate_after_capture,
            "operator_completion_required": profile.operator_completion_required,
            "operator_completion_timeout_seconds": profile.operator_completion_timeout_seconds,
        },
        "capability_report": capability_report,
        "stagger_acceptance": stagger_acceptance,
        "plugin_deployment": {
            "requested": True,
            "destination_path": str(destination),
            "allow_game_directory_write": True,
            "restore_after_runtime": True,
            "performed_by_run_request": True,
            "verified_deployed_artifact_hash": False,
            "destination_existed_at_admission": destination.is_file(),
            "destination_sha256_at_admission": (
                hashlib.sha256(destination.read_bytes()).hexdigest()
                if destination.is_file()
                else None
            ),
        },
    }


@dataclass(frozen=True)
class ProductExecutionAdaptersV1:
    """Ephemeral effect adapters; callables never enter product identity or result."""

    evidence_pack_factory: Callable[..., Any]
    patch_change_factory: Callable[..., Any]
    dry_run_factory: Callable[..., Any]
    isolated_apply_factory: Callable[..., Any]
    build_result_factory: Callable[..., Any]
    runtime_evidence_factory: Callable[..., Any] | None
    compiled_artifact_verifier: Callable[..., Any] | None
    source_change_verifier: Callable[..., Any] | None
    proposal_review_context_factory: Callable[..., Any] | None = None

    def validate_for(self, request: ProductExecutionRequestV1) -> None:
        required = (
            "evidence_pack_factory",
            "patch_change_factory",
            "dry_run_factory",
            "isolated_apply_factory",
            "build_result_factory",
        )
        for field in required:
            if not callable(getattr(self, field)):
                raise ProductExecutionContractError(
                    f"Product adapter {field} must be callable.",
                    side_effects_may_have_started=False,
                )
        for field in ("compiled_artifact_verifier", "source_change_verifier"):
            selected = getattr(self, field)
            if selected is not None and not callable(selected):
                raise ProductExecutionContractError(
                    f"Product adapter {field} must be callable or null.",
                    side_effects_may_have_started=False,
                )
        if self.proposal_review_context_factory is not None and not callable(
            self.proposal_review_context_factory
        ):
            raise ProductExecutionContractError(
                "Product adapter proposal_review_context_factory must be callable "
                "or null.",
                side_effects_may_have_started=False,
            )
        runtime_required = request.requested_completion_scope == "runtime_workflow"
        if runtime_required is not callable(self.runtime_evidence_factory):
            raise _ProductExecutionAdmissionError(
                "Product Runtime adapter topology disagrees with completion scope.",
                side_effects_may_have_started=False,
            )

    def topology(self) -> tuple[tuple[str, bool], ...]:
        return tuple(
            (field, callable(getattr(self, field)))
            for field in (
                "evidence_pack_factory",
                "patch_change_factory",
                "dry_run_factory",
                "isolated_apply_factory",
                "build_result_factory",
                "runtime_evidence_factory",
                "compiled_artifact_verifier",
                "source_change_verifier",
            )
        )


@dataclass(frozen=True)
class _OwnerBoundRuntimeEvidenceFactoryV1:
    factory: Callable[..., Any]
    settings: Any
    allow_game_launch: bool
    runtime_plugin_destination: str | Path
    allow_game_directory_write: bool
    expected_runtime_admission: Mapping[str, Any]

    def validate_runtime_admission(self, observed: Mapping[str, Any]) -> None:
        expected = _runtime_admission_record(
            self.settings,
            run_gtfo_runtime=True,
            allow_game_launch=self.allow_game_launch,
            runtime_plugin_destination=self.runtime_plugin_destination,
            allow_game_directory_write=self.allow_game_directory_write,
        )
        if expected != dict(self.expected_runtime_admission) or observed != expected:
            raise LocalEntryError(
                "Runtime admission changed after its owner produced it."
            )

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.validate_runtime_admission(self.expected_runtime_admission)
        return self.factory(*args, **kwargs)


def _bind_owner_validated_runtime_evidence_factory(
    factory: Callable[..., Any],
    *,
    settings: Any,
    allow_game_launch: bool,
    runtime_plugin_destination: str | Path,
    allow_game_directory_write: bool,
    expected_runtime_admission: Mapping[str, Any],
) -> Callable[..., Any]:
    """Bind the Runtime effect to the same owner inputs used by run-request."""

    return _OwnerBoundRuntimeEvidenceFactoryV1(
        factory=factory,
        settings=settings,
        allow_game_launch=allow_game_launch,
        runtime_plugin_destination=runtime_plugin_destination,
        allow_game_directory_write=allow_game_directory_write,
        expected_runtime_admission=dict(expected_runtime_admission),
    )


class ProductExecutionInputBindingResolverV1:
    """Validate wrapper integrity without copying delegated record schemas."""

    def validate(
        self,
        request: ProductExecutionRequestV1,
        adapters: ProductExecutionAdaptersV1,
    ) -> None:
        if not isinstance(request, ProductExecutionRequestV1):
            raise ProductExecutionContractError(
                "Product request must be ProductExecutionRequestV1.",
                side_effects_may_have_started=False,
            )
        bindings = {
            item.binding_kind: ProductExecutionInputBindingV1.from_dict(
                item.to_dict()
            ).canonical_payload
            for item in request.input_bindings
        }
        try:
            source_snapshot_value = source_snapshot(Path(request.source_root))
            _verify_source_revision_binding(
                source=Path(request.source_root),
                snapshot=source_snapshot_value,
                snapshot_sha256=source_snapshot_sha256(source_snapshot_value),
                binding=bindings["source_revision_binding"],
            )

            disclosure = bindings["source_disclosure"]
            model = bindings["model_admission"]
            if not isinstance(disclosure, Mapping) or not isinstance(model, Mapping):
                raise LocalEntryError(
                    "Product disclosure/model bindings must be owner-produced records."
                )
            if disclosure.get("occurred") is False:
                expected_disclosure = _local_no_external_disclosure_record()
            else:
                destination = disclosure.get("destination")
                if not isinstance(destination, Mapping):
                    raise LocalEntryError(
                        "External source disclosure destination is missing."
                    )
                expected_disclosure = _source_disclosure_record(
                    provider=str(destination.get("provider") or ""),
                    model=str(destination.get("model") or ""),
                    base_url=destination.get("base_url"),
                    approved_at=str(disclosure.get("approved_at") or ""),
                    approval_id=disclosure.get("approval_id"),
                    provider_adapter=disclosure.get("provider_adapter"),
                    destination_url=destination.get("request_url"),
                )
            if disclosure != expected_disclosure:
                raise LocalEntryError(
                    "Source disclosure record changed after its owner produced it."
                )

            if model.get("execution_locality") == "local":
                expected_model = _local_model_admission_record(
                    model_identity={
                        "name": model.get("model"),
                        "digest": model.get("model_digest"),
                        "base_url": model.get("base_url"),
                    },
                    provider_adapter=str(model.get("provider_adapter") or ""),
                )
            else:
                expected_model = _external_model_admission_record(disclosure)
            if model != expected_model:
                raise LocalEntryError(
                    "Model admission record changed after its owner produced it."
                )

            runtime = bindings["runtime_admission"]
            if not isinstance(runtime, Mapping):
                raise LocalEntryError(
                    "Runtime admission binding must be an owner-produced record."
                )
            runtime_requested = request.requested_completion_scope == "runtime_workflow"
            if runtime_requested:
                validator = getattr(
                    adapters.runtime_evidence_factory,
                    "validate_runtime_admission",
                    None,
                )
                if runtime.get("requested") is not True or not callable(validator):
                    raise LocalEntryError(
                        "Runtime admission disagrees with product Runtime scope."
                    )
                validator(runtime)
            else:
                if runtime.get("requested") is not False or adapters.runtime_evidence_factory is not None:
                    raise LocalEntryError(
                        "No-Runtime admission disagrees with compile-only scope."
                    )
        except (KeyError, TypeError, ValueError, LocalEntryError) as exc:
            raise _ProductExecutionAdmissionError(
                str(exc) or type(exc).__name__,
                side_effects_may_have_started=False,
            ) from exc


class ProductExecutionPresentationError(RuntimeError):
    """Presentation failed after the product machine result was frozen."""

    def __init__(
        self,
        *,
        product_execution_result: ProductExecutionResultV1,
        failure_class: str,
        failure_message: str,
        sink: str,
    ) -> None:
        super().__init__(failure_message)
        self.product_execution_result = product_execution_result
        self.failure_class = failure_class
        self.failure_message = failure_message
        self.sink = sink


class _ProductStoreStopped(RuntimeError):
    pass


class _ProductStoreRecorder:
    """Convert one Graph invocation's writes to authoritative C5 attempts."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store
        self.attempts: list[ProductExecutionStoreAttemptV1] = []
        self.outputs: list[ProductExecutionOutputV1] = []
        self.effect_events: list[ProductExecutionEffectEventV1] = []
        self._repair_attempt = 0
        self._role_owner = {
            role: node for node, role in PRODUCT_EXECUTION_DECLARATION.node_store_roles
        }
        self._phase_by_node = PRODUCT_EXECUTION_DECLARATION.phase_by_node

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    @property
    def current_repair_attempt(self) -> int:
        return self._repair_attempt

    def _record(self, result: ArtifactWriteResult, *, payload: Mapping[str, Any]) -> None:
        role = result.artifact_type
        node = self._role_owner.get(role)
        if node is None:
            raise ProductExecutionContractError(
                f"Product Graph attempted undeclared Store role {role}.",
                side_effects_may_have_started=True,
            )
        attempt_number = self._repair_attempt
        if role == "repair_plan":
            payload_attempt = payload.get("retry_count")
            attempt_number = (
                payload_attempt
                if type(payload_attempt) is int
                else self._repair_attempt + 1
            )
        attempt = ProductExecutionStoreAttemptV1(
            contract_version="1",
            sequence=len(self.attempts),
            phase=self._phase_by_node[node],
            repair_attempt=attempt_number,
            node_name=node,
            artifact_role=role,
            store_result=result,
        )
        self.attempts.append(attempt)
        if result.outcome == "committed":
            if result.artifact_ref is None:
                raise ProductExecutionContractError(
                    "Committed Store result is missing ArtifactRef.",
                    side_effects_may_have_started=True,
                )
            self.outputs.append(
                ProductExecutionOutputV1(
                    contract_version="1",
                    sequence=attempt.sequence,
                    phase=attempt.phase,
                    repair_attempt=attempt.repair_attempt,
                    node_name=attempt.node_name,
                    artifact_role=attempt.artifact_role,
                    artifact_ref=result.artifact_ref,
                )
            )
            if role == "repair_plan":
                self._repair_attempt = attempt_number
        else:
            raise _ProductStoreStopped(
                f"{role} did not commit: {result.outcome}"
            )

    def write(self, **kwargs: Any) -> ArtifactRef:
        result = self._store.write_with_result(**kwargs)
        self._record(result, payload=kwargs["payload"])
        if result.artifact_ref is None:
            raise ProductExecutionContractError(
                "Committed product Store result is missing ArtifactRef.",
                side_effects_may_have_started=True,
            )
        return result.artifact_ref

    def write_with_result(self, **kwargs: Any) -> ArtifactWriteResult:
        result = self._store.write_with_result(**kwargs)
        self._record(result, payload=kwargs["payload"])
        return result

    def wrap_effect(
        self,
        *,
        effect_role: str,
        node_name: str,
        factory: Callable[..., Any] | None,
    ) -> Callable[..., Any] | None:
        if factory is None:
            return None

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            phase = self._phase_by_node[node_name]
            start_sequence = len(self.effect_events)
            self.effect_events.append(
                ProductExecutionEffectEventV1(
                    contract_version="1",
                    sequence=start_sequence,
                    phase=phase,
                    repair_attempt=self._repair_attempt,
                    effect_role=effect_role,
                    event_status="started",
                    failure_class=None,
                    failure_message=None,
                )
            )
            try:
                result = factory(*args, **kwargs)
            except ExactDiffApprovalRejectedError:
                # The approval reader rejected before isolated apply began. It is
                # a domain decision, not an effect start/failure fact.
                if effect_role == "isolated_apply":
                    self.effect_events.pop()
                raise
            except Exception as exc:
                self.effect_events.append(
                    ProductExecutionEffectEventV1(
                        contract_version="1",
                        sequence=len(self.effect_events),
                        phase=phase,
                        repair_attempt=self._repair_attempt,
                        effect_role=effect_role,
                        event_status="failed",
                        failure_class=type(exc).__name__,
                        failure_message=str(exc) or type(exc).__name__,
                    )
                )
                raise
            self.effect_events.append(
                ProductExecutionEffectEventV1(
                    contract_version="1",
                    sequence=len(self.effect_events),
                    phase=phase,
                    repair_attempt=self._repair_attempt,
                    effect_role=effect_role,
                    event_status="completed",
                    failure_class=None,
                    failure_message=None,
                )
            )
            return result

        return wrapped


def source_snapshot(root: Path) -> list[dict[str, Any]]:
    """Return the deterministic source snapshot used by the product boundary."""

    selected_root = root.resolve()
    result: list[dict[str, Any]] = []
    for path in sorted(selected_root.rglob("*")):
        if not path.is_file() or any(part in {"bin", "obj"} for part in path.parts):
            continue
        result.append(
            {
                "path": path.relative_to(selected_root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    return result


def source_snapshot_sha256(snapshot: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def preflight_product_execution(
    request: ProductExecutionRequestV1,
    adapters: ProductExecutionAdaptersV1,
    artifact_store: ArtifactStore,
) -> ProductExecutionPreflightResultV1:
    """Perform a no-Graph, no-Store, no-effect product admission check."""

    resolver = ProductExecutionInputBindingResolverV1()
    try:
        adapters.validate_for(request)
        resolver.validate(request, adapters)
    except _ProductExecutionAdmissionError as exc:
        return ProductExecutionPreflightResultV1(
            contract_version="1",
            preflight_status="blocked",
            request=request,
            failure_stage="admission",
            blockers=(
                ProductExecutionBlockerV1(
                    contract_version="1",
                    owner="platform",
                    stage="admission",
                    code="PRODUCT_INPUT_BINDING_ADMISSION_FAILED",
                    message=exc.reason,
                    source_node="product_preflight",
                ),
            ),
        )
    blockers: list[ProductExecutionBlockerV1] = []
    checks = (
        (
            Path(request.artifact_store_root).resolve() == artifact_store.root,
            "PRODUCT_STORE_ROOT_MISMATCH",
            "ArtifactStore root changed after product request construction.",
        ),
        (
            Path(request.source_root).is_dir(),
            "PRODUCT_SOURCE_ROOT_MISSING",
            "Canonical source root is missing.",
        ),
        (
            Path(request.isolated_target_root).is_dir(),
            "PRODUCT_ISOLATED_ROOT_MISSING",
            "Isolated target root is missing.",
        ),
    )
    for passed, code, message in checks:
        if not passed:
            blockers.append(
                ProductExecutionBlockerV1(
                    contract_version="1",
                    owner="platform",
                    stage="execution_constraint",
                    code=code,
                    message=message,
                    source_node="product_preflight",
                )
            )
    if not blockers:
        current_source_hash = source_snapshot_sha256(
            source_snapshot(Path(request.source_root))
        )
        current_isolated_hash = source_snapshot_sha256(
            source_snapshot(Path(request.isolated_target_root))
        )
        if current_source_hash != request.source_snapshot_sha256:
            blockers.append(
                ProductExecutionBlockerV1(
                    contract_version="1",
                    owner="platform",
                    stage="execution_constraint",
                    code="PRODUCT_SOURCE_SNAPSHOT_DRIFT",
                    message="Canonical source snapshot changed before Graph START.",
                    source_node="product_preflight",
                )
            )
        if current_isolated_hash != request.isolated_source_snapshot_sha256:
            blockers.append(
                ProductExecutionBlockerV1(
                    contract_version="1",
                    owner="platform",
                    stage="execution_constraint",
                    code="PRODUCT_ISOLATED_SNAPSHOT_DRIFT",
                    message="Isolated source snapshot changed before Graph START.",
                    source_node="product_preflight",
                )
            )
    return ProductExecutionPreflightResultV1(
        contract_version="1",
        preflight_status="blocked" if blockers else "ready",
        request=request,
        failure_stage="execution_constraint" if blockers else None,
        blockers=tuple(blockers),
    )


def _platform_blocker(stage: str, code: str, message: str, node: str) -> ProductExecutionBlockerV1:
    return ProductExecutionBlockerV1(
        contract_version="1",
        owner="platform",
        stage=stage,
        code=code,
        message=message,
        source_node=node,
    )


def _domain_blockers(state: Mapping[str, Any]) -> tuple[ProductExecutionBlockerV1, ...]:
    selected: list[ProductExecutionBlockerV1] = []
    for raw in state.get("blockers") or ():
        if not isinstance(raw, Mapping):
            continue
        selected.append(
            ProductExecutionBlockerV1(
                contract_version="1",
                owner="domain",
                stage=str(raw.get("stage") or state.get("current_stage") or "blocked"),
                code=str(raw.get("code") or raw.get("reason") or "PRODUCT_DOMAIN_BLOCKED"),
                message=str(raw.get("message") or raw.get("reason") or "Product Graph selected a blocked terminal."),
                source_node="blocked",
            )
        )
    if not selected:
        selected.append(
            ProductExecutionBlockerV1(
                contract_version="1",
                owner="domain",
                stage="blocked",
                code="PRODUCT_DOMAIN_BLOCKED",
                message="Product Graph selected a blocked terminal.",
                source_node="blocked",
            )
        )
    return tuple(selected)


def _output_by_role(
    outputs: tuple[ProductExecutionOutputV1, ...], role: str
) -> ProductExecutionOutputV1 | None:
    matches = [item for item in outputs if item.artifact_role == role]
    return matches[-1] if matches else None


def _read_payload(
    store: ArtifactStore,
    output: ProductExecutionOutputV1 | None,
) -> dict[str, Any] | None:
    if output is None:
        return None
    return store.read(output.artifact_ref)["data"]


def _build_completion(
    request: ProductExecutionRequestV1,
    store: ArtifactStore,
    outputs: tuple[ProductExecutionOutputV1, ...],
) -> ProductBuildCompletionV1:
    build_output = _output_by_role(outputs, "build_result")
    checkpoint_output = _output_by_role(outputs, "workflow_checkpoint")
    if build_output is None:
        return ProductBuildCompletionV1(
            contract_version="1",
            build_result_ref=None,
            workflow_checkpoint_ref=None,
            build_status="not_reached",
            claims_real_build_success=None,
        )
    try:
        payload = _read_payload(store, build_output)
    except Exception:
        return ProductBuildCompletionV1(
            contract_version="1",
            build_result_ref=build_output.artifact_ref,
            workflow_checkpoint_ref=(checkpoint_output.artifact_ref if checkpoint_output else None),
            build_status="unavailable",
            claims_real_build_success=None,
        )
    claim = payload.get("claims_real_build_success")
    status = payload.get("status")
    exact_status = "success" if status == "success" and claim is True else (
        "blocked" if status == "blocked" else "failed"
    )
    return ProductBuildCompletionV1(
        contract_version="1",
        build_result_ref=build_output.artifact_ref,
        workflow_checkpoint_ref=(checkpoint_output.artifact_ref if checkpoint_output else None),
        build_status=exact_status,
        claims_real_build_success=(claim if type(claim) is bool else None),
    )


def _runtime_completion(
    store: ArtifactStore,
    outputs: tuple[ProductExecutionOutputV1, ...],
) -> ProductRuntimeCompletionV1:
    by_role = {role: _output_by_role(outputs, role) for role in (
        "build_result", "runtime_evidence", "eval_report", "workflow_summary", "blocked_report"
    )}
    payloads: dict[str, dict[str, Any] | None] = {}
    for role, output in by_role.items():
        try:
            payloads[role] = _read_payload(store, output)
        except Exception:
            payloads[role] = None
    build = payloads["build_result"]
    runtime = payloads["runtime_evidence"]
    evaluation = payloads["eval_report"]
    summary = payloads["workflow_summary"]
    build_status = (
        "not_reached" if by_role["build_result"] is None else
        "unavailable" if build is None else
        "success" if build.get("claims_real_build_success") is True else
        "blocked" if build.get("status") == "blocked" else "failed"
    )
    runtime_status = (
        "not_reached" if by_role["runtime_evidence"] is None else
        "unavailable" if runtime is None else
        "accepted" if runtime.get("acceptance_verified") is True else
        "blocked" if runtime.get("verification_status") == "blocked" else "not_accepted"
    )
    eval_verdict = (
        "not_reached" if by_role["eval_report"] is None else
        "unavailable" if evaluation is None else
        evaluation.get("verdict") if evaluation.get("verdict") in {"accepted", "blocked", "inconclusive"} else "inconclusive"
    )
    final_status = (
        "blocked" if by_role["blocked_report"] is not None else
        "not_reached" if by_role["workflow_summary"] is None else
        "unavailable" if summary is None else
        summary.get("final_status") if summary.get("final_status") in {"accepted", "blocked", "inconclusive"} else "inconclusive"
    )
    return ProductRuntimeCompletionV1(
        contract_version="1",
        build_result_ref=by_role["build_result"].artifact_ref if by_role["build_result"] else None,
        runtime_evidence_ref=by_role["runtime_evidence"].artifact_ref if by_role["runtime_evidence"] else None,
        eval_report_ref=by_role["eval_report"].artifact_ref if by_role["eval_report"] else None,
        workflow_summary_ref=by_role["workflow_summary"].artifact_ref if by_role["workflow_summary"] else None,
        blocked_report_ref=by_role["blocked_report"].artifact_ref if by_role["blocked_report"] else None,
        build_status=build_status,
        runtime_status=runtime_status,
        eval_verdict=eval_verdict,
        final_status=final_status,
    )


def validate_product_execution_outputs(
    *,
    request: ProductExecutionRequestV1,
    store: ArtifactStore,
    outputs: tuple[ProductExecutionOutputV1, ...],
    adapters: ProductExecutionAdaptersV1,
    initial_isolated_snapshot: list[dict[str, Any]],
    successful_terminal: bool,
) -> ProductExecutionValidationFactsV1:
    statuses = {kind: "not_applicable" for kind in (
        "output_readback", "canonical_source", "compiled_artifact", "source_change", "completion_classification"
    )}
    payloads: dict[str, Any] = {kind: None for kind in statuses}
    failure: Exception | None = None
    ordered = tuple(statuses)
    try:
        if outputs:
            payloads["output_readback"] = [store.read(item.artifact_ref) for item in outputs]
            statuses["output_readback"] = "passed"
        if not successful_terminal:
            return ProductExecutionValidationFactsV1(
                contract_version="1",
                output_readback_status=statuses["output_readback"],
                canonical_source_status="not_applicable",
                compiled_artifact_status="not_applicable",
                source_change_status="not_applicable",
                completion_classification_status="not_applicable",
                failure_class=None,
                failure_message=None,
                details=tuple(
                    ProductExecutionValidationDetailV1(
                        contract_version="1",
                        detail_kind=kind,
                        payload=payloads[kind],
                    )
                    for kind in ordered
                ),
            )
        canonical = source_snapshot(Path(request.source_root))
        canonical_hash = source_snapshot_sha256(canonical)
        if canonical_hash != request.source_snapshot_sha256:
            raise RuntimeError("Canonical source changed during product execution.")
        statuses["canonical_source"] = "passed"
        payloads["canonical_source"] = {"source_snapshot_sha256": canonical_hash}
        build_output = _output_by_role(outputs, "build_result")
        build_payload = _read_payload(store, build_output)
        build_succeeded = bool(build_payload and build_payload.get("claims_real_build_success") is True)
        if build_succeeded and adapters.compiled_artifact_verifier is not None:
            verified = [
                item for item in build_payload.get("verified_artifacts") or ()
                if isinstance(item, Mapping) and item.get("path")
            ]
            if len(verified) != 1:
                raise RuntimeError("Successful Build lacks one exact verified artifact.")
            payloads["compiled_artifact"] = adapters.compiled_artifact_verifier(
                Path(request.isolated_target_root) / str(verified[0]["path"]),
                "final_build",
            )
            statuses["compiled_artifact"] = "passed"
        if build_succeeded and adapters.source_change_verifier is not None:
            final_isolated = source_snapshot(Path(request.isolated_target_root))
            source_change = adapters.source_change_verifier(
                initial_isolated_snapshot,
                final_isolated,
            )
            payloads["source_change"] = {
                **dict(source_change),
                "initial_snapshot": initial_isolated_snapshot,
                "final_snapshot": final_isolated,
            }
            statuses["source_change"] = "passed"
        if request.completion_classification:
            if not build_succeeded:
                raise RuntimeError("Completion classification requires a successful Build.")
            if statuses["compiled_artifact"] != "passed" or statuses["source_change"] != "passed":
                raise RuntimeError("Completion classification requires both fixed verifiers.")
            payloads["completion_classification"] = dict(request.completion_classification)
            statuses["completion_classification"] = "passed"
    except Exception as exc:
        failure = exc
        failed_kind = next(
            kind for kind in ordered
            if statuses[kind] == "not_applicable" and (
                kind == "output_readback" and bool(outputs)
                or kind == "canonical_source"
                or kind == "compiled_artifact" and adapters.compiled_artifact_verifier is not None
                or kind == "source_change" and adapters.source_change_verifier is not None
                or kind == "completion_classification" and bool(request.completion_classification)
            )
        )
        statuses[failed_kind] = "failed"
    return ProductExecutionValidationFactsV1(
        contract_version="1",
        output_readback_status=statuses["output_readback"],
        canonical_source_status=statuses["canonical_source"],
        compiled_artifact_status=statuses["compiled_artifact"],
        source_change_status=statuses["source_change"],
        completion_classification_status=statuses["completion_classification"],
        failure_class=type(failure).__name__ if failure else None,
        failure_message=(str(failure) or type(failure).__name__) if failure else None,
        details=tuple(
            ProductExecutionValidationDetailV1(
                contract_version="1", detail_kind=kind, payload=payloads[kind]
            )
            for kind in ordered
        ),
    )


def execute_product_execution(
    preflight: ProductExecutionPreflightResultV1,
    adapters: ProductExecutionAdaptersV1,
    artifact_store: ArtifactStore,
) -> ProductExecutionResultV1:
    """Execute the existing StateGraph exactly once and freeze one machine result."""

    if not isinstance(preflight, ProductExecutionPreflightResultV1) or preflight.preflight_status != "ready":
        raise ProductExecutionContractError(
            "Product execute requires a ready ProductExecutionPreflightResultV1.",
            side_effects_may_have_started=False,
        )
    request = preflight.request
    repeated = preflight_product_execution(request, adapters, artifact_store)
    if repeated.preflight_status != "ready" or repeated.request.to_dict() != request.to_dict():
        raise ProductExecutionContractError(
            "Product execution admission changed before Graph START.",
            side_effects_may_have_started=False,
        )
    initial_isolated_snapshot = source_snapshot(Path(request.isolated_target_root))
    recorder = _ProductStoreRecorder(artifact_store)
    wrapped = ProductExecutionAdaptersV1(
        evidence_pack_factory=recorder.wrap_effect(effect_role="evidence_retrieval", node_name="retrieve_evidence", factory=adapters.evidence_pack_factory),
        patch_change_factory=recorder.wrap_effect(effect_role="patch_generation", node_name="generate_patch_proposal", factory=adapters.patch_change_factory),
        dry_run_factory=recorder.wrap_effect(effect_role="dry_run", node_name="dry_run_apply", factory=adapters.dry_run_factory),
        isolated_apply_factory=recorder.wrap_effect(effect_role="isolated_apply", node_name="isolated_apply", factory=adapters.isolated_apply_factory),
        build_result_factory=recorder.wrap_effect(effect_role="build", node_name="build", factory=adapters.build_result_factory),
        runtime_evidence_factory=recorder.wrap_effect(effect_role="runtime", node_name="collect_runtime_evidence", factory=adapters.runtime_evidence_factory),
        compiled_artifact_verifier=adapters.compiled_artifact_verifier,
        source_change_verifier=adapters.source_change_verifier,
        proposal_review_context_factory=adapters.proposal_review_context_factory,
    )
    graph = build_graph(
        recorder,
        evidence_pack_factory=wrapped.evidence_pack_factory,
        patch_change_factory=wrapped.patch_change_factory,
        proposal_review_context_factory=wrapped.proposal_review_context_factory,
        dry_run_factory=wrapped.dry_run_factory,
        isolated_apply_factory=wrapped.isolated_apply_factory,
        build_result_factory=wrapped.build_result_factory,
        runtime_evidence_factory=wrapped.runtime_evidence_factory,
        domain_review_policy=(
            GTFOAdapter()
            if request.target_domain == "gtfo"
            else UnsupportedDomainAdapter()
        ).identify_project(request.isolated_workspace_root).review_policy(),
        use_default_proposal_git_binding=False,
        product_execution_mode=ProductExecutionGraphModeV1(
            contract_version="1", request=request
        ),
    )
    state = create_initial_state(
        run_id=request.run_id,
        request_id=request.request_id,
        user_request=request.user_request,
        target_domain=request.target_domain,
        target_mod=request.target_mod,
        confirmed_isolated_write=True,
    )
    graph_result: Mapping[str, Any] = state
    platform_blockers: tuple[ProductExecutionBlockerV1, ...] = ()
    failure_stage: str | None = None
    try:
        graph_result = graph.invoke(state)
    except _ProductStoreStopped:
        last = recorder.attempts[-1]
        failure_stage = f"{last.artifact_role}_store"
        platform_blockers = (
            _platform_blocker(
                failure_stage,
                "PRODUCT_STORE_NOT_COMMITTED",
                last.store_result.failure_message or "Product Store attempt did not commit.",
                last.node_name,
            ),
        )
    except ProductExecutionContractError:
        raise
    except Exception as exc:
        node = getattr(exc, "_mod_agent_graph_node", None)
        if node not in PRODUCT_EXECUTION_DECLARATION.phase_by_node:
            raise ProductExecutionContractError(
                "Graph exception lacks its exact current-node fact.",
                side_effects_may_have_started=bool(
                    recorder.outputs or recorder.effect_events
                ),
            ) from exc
        failure_stage = f"{node}_execution"
        platform_blockers = (
            _platform_blocker(
                failure_stage,
                "PRODUCT_NODE_EXECUTION_FAILED",
                f"{type(exc).__name__}: {exc}",
                node,
            ),
        )
    attempts = tuple(recorder.attempts)
    outputs = tuple(recorder.outputs)
    terminal = (
        graph_result.get("current_stage")
        if graph_result.get("current_stage") in {"build", "done", "blocked"}
        and failure_stage is None
        else None
    )
    validation = validate_product_execution_outputs(
        request=request,
        store=artifact_store,
        outputs=outputs,
        adapters=adapters,
        initial_isolated_snapshot=initial_isolated_snapshot,
        successful_terminal=terminal in {"build", "done"},
    )
    blockers = (
        _domain_blockers(graph_result)
        if terminal == "blocked" and not platform_blockers
        else platform_blockers
    )
    if validation.failed and not platform_blockers:
        blockers = (
            _platform_blocker(
                "post_execution_validation",
                "PRODUCT_POST_EXECUTION_VALIDATION_FAILED",
                validation.failure_message or "Product output validation failed.",
                terminal or "product_executor",
            ),
        )
    variant = (
        _build_completion(request, artifact_store, outputs)
        if request.requested_completion_scope == "compile_only"
        else _runtime_completion(artifact_store, outputs)
    )
    return project_product_execution_result(
        ProductExecutionFactsV1(
            request=request,
            feature_id=(
                graph_result.get("feature_id")
                or (outputs[-1].artifact_ref.feature_id if outputs else None)
            ),
            terminal_node=terminal,
            store_attempts=attempts,
            outputs=outputs,
            effect_events=tuple(recorder.effect_events),
            validation_facts=validation,
            blockers=blockers,
            variant_result=variant,
            failure_stage=failure_stage,
        )
    )
