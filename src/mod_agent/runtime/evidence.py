"""Runtime evidence payload builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


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
) -> dict[str, Any]:
    """Build an inconclusive fake runtime evidence payload."""

    return _build_runtime_payload(
        node_name="collect_runtime_evidence",
        feature_id=feature_id,
        execution_mode="fake",
        evidence_source="fake",
        startup_loaded=False,
        gameplay_behavior_verified=False,
        evidence_items=(),
        verification_status="inconclusive",
        raw_supplied_output=None,
        sources=(),
        non_goals_checked=(),
        limitations=(
            "Fake build output cannot prove runtime behavior.",
            "A real runtime, supplied output, or manual evidence artifact is required before claiming success.",
        ),
        message=(
            "Runtime evidence is inconclusive. No game process was launched and "
            "no real gameplay behavior was observed."
        ),
        input_execution_mode=input_execution_mode,
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
    )


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
) -> dict[str, Any]:
    items = tuple(evidence_items)
    _validate_verification(
        verification_status=verification_status,
        startup_loaded=startup_loaded,
        gameplay_behavior_verified=gameplay_behavior_verified,
        evidence_items=items,
    )
    claims_real_runtime_success = (
        verification_status == "verified"
        and execution_mode in {"manual", "supplied_output", "real"}
    )
    return {
        "node_name": node_name,
        "stage": "runtime_evidence",
        "message": message,
        "feature_id": feature_id,
        "execution_mode": execution_mode,
        "evidence_source": evidence_source,
        "startup_loaded": startup_loaded,
        "gameplay_behavior_verified": gameplay_behavior_verified,
        "evidence_items": [item.to_dict() for item in items],
        "verification_status": verification_status,
        "acceptance_status": _acceptance_status(verification_status),
        "runtime_status": verification_status,
        "raw_supplied_output": raw_supplied_output,
        "sources": list(sources),
        "non_goals_checked": [dict(item) for item in non_goals_checked],
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
