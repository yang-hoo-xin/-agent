"""Runtime evidence payload builders."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


class RuntimeEvidenceError(ValueError):
    """Raised when runtime evidence would overclaim acceptance."""


@dataclass(frozen=True)
class RuntimeEvidenceItem:
    """One runtime evidence item from logs, screenshots, manual notes, or vision."""

    item_type: str
    source: str
    locator: str
    supports_acceptance: tuple[str, ...] = ()
    confidence: float = 0.0
    raw_excerpt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the artifact shape required by DEV_SPEC 15.3."""

        return {
            "type": self.item_type,
            "source": self.source,
            "locator": self.locator,
            "supports_acceptance": list(self.supports_acceptance),
            "confidence": self.confidence,
            "raw_excerpt": self.raw_excerpt,
        }


def build_fake_runtime_evidence_payload(
    *,
    feature_id: str,
    input_execution_mode: str | None,
    acceptance_criteria: Iterable[str] = (),
    runtime_verification_plan: Iterable[str] = (),
    run_id: str | None = None,
    build_artifact_ref: Mapping[str, Any] | None = None,
    build_artifact_hash: str | None = None,
    plugin_marker_binding: Mapping[str, Any] | None = None,
    screenshot_refs: Iterable[Mapping[str, Any]] = (),
    non_goal_preservation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build fake runtime evidence that explicitly evaluates the acceptance contract."""

    criteria = tuple(acceptance_criteria)
    evidence_items = (
        RuntimeEvidenceItem(
            item_type="fake_acceptance_fixture",
            source="fake_runtime_fixture",
            locator=f"feature:{feature_id}",
            supports_acceptance=criteria,
            confidence=1.0,
            raw_excerpt="Fake runtime fixture explicitly marks acceptance criteria as observed.",
        ),
    )

    return _build_runtime_payload(
        node_name="collect_runtime_evidence",
        feature_id=feature_id,
        execution_mode="fake",
        evidence_source="fake",
        startup_loaded=True,
        gameplay_behavior_verified=True,
        evidence_items=evidence_items,
        verification_status="verified",
        raw_supplied_output=None,
        sources=(),
        non_goals_checked=(),
        limitations=(
            "Fake runtime fixture verifies the acceptance contract for workflow testing only.",
            "A real runtime, supplied output, or manual evidence artifact is required before claiming real runtime success.",
        ),
        message=(
            "Fake runtime fixture explicitly verified the feature acceptance contract. "
            "No real game process was launched."
        ),
        input_execution_mode=input_execution_mode,
        acceptance_criteria=criteria,
        runtime_verification_plan=tuple(runtime_verification_plan),
        run_id=run_id,
        build_artifact_ref=build_artifact_ref,
        build_artifact_hash=build_artifact_hash,
        plugin_marker_binding=plugin_marker_binding,
        screenshot_refs=tuple(screenshot_refs),
        non_goal_preservation=non_goal_preservation,
    )


def build_supplied_runtime_evidence_payload(
    *,
    feature_id: str,
    raw_supplied_output: str,
    evidence_items: Iterable[RuntimeEvidenceItem] = (),
    startup_loaded: bool = False,
    gameplay_behavior_verified: bool = False,
    verification_status: str = "inconclusive",
    non_goals_checked: Iterable[Mapping[str, Any]] = (),
    limitations: Iterable[str] = (),
    acceptance_criteria: Iterable[str] = (),
    runtime_verification_plan: Iterable[str] = (),
    run_id: str | None = None,
    build_artifact_ref: Mapping[str, Any] | None = None,
    build_artifact_hash: str | None = None,
    plugin_marker_binding: Mapping[str, Any] | None = None,
    screenshot_refs: Iterable[Mapping[str, Any]] = (),
    non_goal_preservation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build runtime evidence from user-supplied logs or observations."""

    items = tuple(evidence_items)
    return _build_runtime_payload(
        node_name="record_supplied_runtime_evidence",
        feature_id=feature_id,
        execution_mode="supplied_output",
        evidence_source="supplied_output",
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        evidence_items=items,
        verification_status=verification_status,
        raw_supplied_output=raw_supplied_output,
        sources=_sources_from_items(items),
        non_goals_checked=tuple(non_goals_checked),
        limitations=tuple(limitations),
        message="Supplied runtime evidence was recorded without launching the game.",
        input_execution_mode=None,
        acceptance_criteria=tuple(acceptance_criteria),
        runtime_verification_plan=tuple(runtime_verification_plan),
        run_id=run_id,
        build_artifact_ref=build_artifact_ref,
        build_artifact_hash=build_artifact_hash,
        plugin_marker_binding=plugin_marker_binding,
        screenshot_refs=tuple(screenshot_refs),
        non_goal_preservation=non_goal_preservation,
    )


def build_real_runtime_evidence_payload(
    *,
    feature_id: str,
    input_execution_mode: str | None,
    evidence_items: Iterable[RuntimeEvidenceItem],
    startup_loaded: bool,
    gameplay_behavior_verified: bool,
    verification_status: str,
    raw_runtime_output: str | None = None,
    non_goals_checked: Iterable[Mapping[str, Any]] = (),
    limitations: Iterable[str] = (),
    acceptance_criteria: Iterable[str] = (),
    runtime_verification_plan: Iterable[str] = (),
    run_id: str | None = None,
    build_artifact_ref: Mapping[str, Any] | None = None,
    build_artifact_hash: str | None = None,
    plugin_marker_binding: Mapping[str, Any] | None = None,
    screenshot_refs: Iterable[Mapping[str, Any]] = (),
    non_goal_preservation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build runtime evidence from an explicitly executed runtime probe."""

    items = tuple(evidence_items)
    return _build_runtime_payload(
        node_name="collect_runtime_evidence",
        feature_id=feature_id,
        execution_mode="real",
        evidence_source="real_runtime_probe",
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        evidence_items=items,
        verification_status=verification_status,
        raw_supplied_output=raw_runtime_output,
        sources=_sources_from_items(items),
        non_goals_checked=tuple(non_goals_checked),
        limitations=tuple(limitations),
        message="Real runtime probe evidence was collected and evaluated.",
        input_execution_mode=input_execution_mode,
        acceptance_criteria=tuple(acceptance_criteria),
        runtime_verification_plan=tuple(runtime_verification_plan),
        run_id=run_id,
        build_artifact_ref=build_artifact_ref,
        build_artifact_hash=build_artifact_hash,
        plugin_marker_binding=plugin_marker_binding,
        screenshot_refs=tuple(screenshot_refs),
        non_goal_preservation=non_goal_preservation,
    )


def build_manual_runtime_evidence_payload(
    *,
    feature_id: str,
    evidence_items: Iterable[RuntimeEvidenceItem],
    startup_loaded: bool,
    gameplay_behavior_verified: bool,
    verification_status: str,
    non_goals_checked: Iterable[Mapping[str, Any]] = (),
    limitations: Iterable[str] = (),
    acceptance_criteria: Iterable[str] = (),
    runtime_verification_plan: Iterable[str] = (),
    run_id: str | None = None,
    build_artifact_ref: Mapping[str, Any] | None = None,
    build_artifact_hash: str | None = None,
    plugin_marker_binding: Mapping[str, Any] | None = None,
    screenshot_refs: Iterable[Mapping[str, Any]] = (),
    non_goal_preservation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build runtime evidence from explicit manual verification notes."""

    items = tuple(evidence_items)
    return _build_runtime_payload(
        node_name="record_manual_runtime_evidence",
        feature_id=feature_id,
        execution_mode="manual",
        evidence_source="manual_note",
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        evidence_items=items,
        verification_status=verification_status,
        raw_supplied_output=None,
        sources=_sources_from_items(items),
        non_goals_checked=tuple(non_goals_checked),
        limitations=tuple(limitations),
        message="Manual runtime evidence was recorded without automated runtime control.",
        input_execution_mode=None,
        acceptance_criteria=tuple(acceptance_criteria),
        runtime_verification_plan=tuple(runtime_verification_plan),
        run_id=run_id,
        build_artifact_ref=build_artifact_ref,
        build_artifact_hash=build_artifact_hash,
        plugin_marker_binding=plugin_marker_binding,
        screenshot_refs=tuple(screenshot_refs),
        non_goal_preservation=non_goal_preservation,
    )


def bind_runtime_evidence_context(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    build_artifact_ref: Any,
) -> dict[str, Any]:
    """Bind runtime evidence to the graph run and upstream build artifact."""

    bound = dict(payload)
    ref_payload = _artifact_ref_payload(build_artifact_ref)
    if not bound.get("run_id"):
        bound["run_id"] = run_id
    if bound.get("build_artifact_ref") is None:
        bound["build_artifact_ref"] = ref_payload
    if not bound.get("build_artifact_hash") and ref_payload is not None:
        bound["build_artifact_hash"] = ref_payload["artifact_hash"]
    bound.setdefault("plugin_marker_binding", {})
    bound.setdefault("screenshot_refs", [])
    bound.setdefault(
        "non_goal_preservation",
        _non_goal_preservation(bound.get("non_goals_checked") or ()),
    )
    return bound


def _build_runtime_payload(
    *,
    node_name: str,
    feature_id: str,
    execution_mode: str,
    evidence_source: str,
    startup_loaded: bool,
    gameplay_behavior_verified: bool,
    evidence_items: Iterable[RuntimeEvidenceItem],
    verification_status: str,
    raw_supplied_output: str | None,
    sources: Iterable[Mapping[str, Any]],
    non_goals_checked: Iterable[Mapping[str, Any]],
    limitations: Iterable[str],
    message: str,
    input_execution_mode: str | None,
    acceptance_criteria: Iterable[str],
    runtime_verification_plan: Iterable[str],
    run_id: str | None,
    build_artifact_ref: Mapping[str, Any] | None,
    build_artifact_hash: str | None,
    plugin_marker_binding: Mapping[str, Any] | None,
    screenshot_refs: Iterable[Mapping[str, Any]],
    non_goal_preservation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    items = tuple(evidence_items)
    marker_binding = dict(plugin_marker_binding or {})
    non_goals = tuple(non_goals_checked)
    _validate_verification(
        verification_status=verification_status,
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        evidence_items=items,
        acceptance_criteria=tuple(acceptance_criteria),
    )
    claims_real_runtime_success = (
        verification_status == "verified"
        and execution_mode in {"manual", "supplied_output", "real"}
    )
    criteria = tuple(acceptance_criteria)
    verification_plan = tuple(runtime_verification_plan)
    acceptance_verified = verification_status == "verified"
    return {
        "node_name": node_name,
        "stage": "runtime_evidence",
        "message": message,
        "feature_id": feature_id,
        "run_id": run_id,
        "build_artifact_ref": dict(build_artifact_ref) if build_artifact_ref else None,
        "build_artifact_hash": build_artifact_hash,
        "execution_mode": execution_mode,
        "evidence_source": evidence_source,
        "plugin_marker_binding": marker_binding,
        "screenshot_refs": [dict(item) for item in screenshot_refs],
        "startup_loaded": startup_loaded,
        "gameplay_behavior_verified": gameplay_behavior_verified,
        "evidence_items": [item.to_dict() for item in items],
        "verification_status": verification_status,
        "acceptance_status": _acceptance_status(verification_status),
        "acceptance_verified": acceptance_verified,
        "acceptance_contract": {
            "acceptance_criteria": list(criteria),
            "runtime_verification_plan": list(verification_plan),
        },
        "runtime_status": verification_status,
        "raw_supplied_output": raw_supplied_output,
        "sources": list(sources),
        "non_goals_checked": [dict(item) for item in non_goals],
        "non_goal_preservation": dict(
            non_goal_preservation or _non_goal_preservation(non_goals)
        ),
        "limitations": list(limitations),
        "real_runtime_performed": execution_mode == "real",
        "manual_evidence_required": verification_status != "verified",
        "claims_real_runtime_success": claims_real_runtime_success,
        "input_execution_mode": input_execution_mode,
    }


def _validate_verification(
    *,
    verification_status: str,
    startup_loaded: bool,
    gameplay_behavior_verified: bool,
    evidence_items: tuple[RuntimeEvidenceItem, ...],
    acceptance_criteria: tuple[str, ...],
) -> None:
    allowed = {"verified", "partial", "failed", "inconclusive"}
    if verification_status not in allowed:
        raise RuntimeEvidenceError(
            f"Unsupported verification_status: {verification_status}"
        )
    if verification_status != "verified":
        return
    has_acceptance_evidence = any(
        item.supports_acceptance and item.confidence > 0.0
        for item in evidence_items
    )
    supported_acceptance = {
        claim
        for item in evidence_items
        if item.confidence > 0.0
        for claim in item.supports_acceptance
    }
    if not startup_loaded:
        raise RuntimeEvidenceError("Verified runtime evidence requires startup_loaded")
    if not gameplay_behavior_verified:
        raise RuntimeEvidenceError(
            "Verified runtime evidence requires gameplay_behavior_verified"
        )
    if not has_acceptance_evidence:
        raise RuntimeEvidenceError(
            "Verified runtime evidence requires explicit acceptance evidence"
        )
    missing_acceptance = set(acceptance_criteria) - supported_acceptance
    if missing_acceptance:
        raise RuntimeEvidenceError(
            "Verified runtime evidence must support every acceptance criterion"
        )


def _acceptance_status(verification_status: str) -> str:
    if verification_status == "verified":
        return "accepted"
    return verification_status


def _sources_from_items(
    evidence_items: Iterable[RuntimeEvidenceItem],
) -> list[dict[str, Any]]:
    return [
        {
            "source_type": item.source,
            "claim": "; ".join(item.supports_acceptance),
            "confidence": item.confidence,
            "attachments": [item.locator] if item.locator else [],
        }
        for item in evidence_items
    ]


def _artifact_ref_payload(ref: Any) -> dict[str, str] | None:
    if ref is None:
        return None
    feature_id = getattr(ref, "feature_id", None)
    artifact_type = getattr(ref, "artifact_type", None)
    path = getattr(ref, "path", None)
    artifact_hash = getattr(ref, "artifact_hash", None)
    if not all(isinstance(item, str) for item in (feature_id, artifact_type, path, artifact_hash)):
        return None
    return {
        "feature_id": feature_id,
        "artifact_type": artifact_type,
        "path": path,
        "artifact_hash": artifact_hash,
    }


def _non_goal_preservation(
    non_goals_checked: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    checked = [dict(item) for item in non_goals_checked]
    violations = [
        item
        for item in checked
        if item.get("preserved") is False or item.get("status") == "violated"
    ]
    if violations:
        status = "violated"
    elif checked:
        status = "preserved"
    else:
        status = "not_checked"
    return {
        "status": status,
        "checked": checked,
        "violations": violations,
    }
