"""Turn a structured Runtime diagnosis into an edit-authority result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .resolver import BindingResolver, ResolvedRepairTarget


_BINDING_GAP_CODES = frozenset(
    {
        "REPAIR_TARGET_SYMBOL_UNRESOLVED",
        "REPAIR_TARGET_SYMBOL_AMBIGUOUS",
        "DIAGNOSIS_SOURCE_IDENTITY_INCOMPLETE",
        "REPAIR_TARGET_SOURCE_OR_SPAN_DRIFT",
    }
)


@dataclass(frozen=True)
class RuntimeBindingResolution:
    """A resolved repair target or a blocked edit-authority gap."""

    feature_id: str
    run_id: str
    result_type: str
    runtime_evidence_revision: dict[str, Any]
    implementation_plan_revision: dict[str, Any]
    patch_proposal_revision: dict[str, Any]
    allowed_edit_binding_ids: tuple[str, ...]
    resolved_repair_target: dict[str, Any] | None
    binding_gap: dict[str, Any] | None
    binding_proposal_request: dict[str, Any] | None
    blockers: tuple[dict[str, Any], ...]

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)

    def to_artifact_payload(self) -> dict[str, Any]:
        return {
            "node_name": "resolve_runtime_binding",
            "stage": "binding_resolution",
            "message": (
                "Runtime diagnosis resolved to one current allowed edit binding."
                if self.result_type == "resolved_repair_target"
                else (
                    "Runtime diagnosis exposed an edit-authority binding gap."
                    if self.result_type == "binding_gap"
                    else "Runtime diagnosis could not enter binding-gap handling."
                )
            ),
            "feature_id": self.feature_id,
            "run_id": self.run_id,
            "result_type": self.result_type,
            "runtime_evidence_revision": dict(
                self.runtime_evidence_revision
            ),
            "implementation_plan_revision": dict(
                self.implementation_plan_revision
            ),
            "patch_proposal_revision": dict(self.patch_proposal_revision),
            "allowed_edit_binding_ids": list(
                self.allowed_edit_binding_ids
            ),
            "resolved_repair_target": (
                dict(self.resolved_repair_target)
                if self.resolved_repair_target is not None
                else None
            ),
            "binding_gap": (
                dict(self.binding_gap)
                if self.binding_gap is not None
                else None
            ),
            "binding_proposal_request": (
                dict(self.binding_proposal_request)
                if self.binding_proposal_request is not None
                else None
            ),
            "blockers": [dict(item) for item in self.blockers],
        }


def resolve_runtime_diagnosis_binding(
    *,
    diagnosis: Any,
    feature_id: str,
    run_id: str,
    runtime_evidence_revision: dict[str, Any],
    implementation_plan_revision: dict[str, Any],
    patch_proposal_revision: dict[str, Any],
    implementation_plan: dict[str, Any],
    allowed_edit_binding_ids: set[str],
) -> RuntimeBindingResolution:
    """Resolve authority strictly, reporting a gap without expanding it."""

    invalid_revision_types = [
        artifact_type
        for artifact_type, revision in (
            ("runtime_evidence", runtime_evidence_revision),
            ("implementation_plan", implementation_plan_revision),
            ("patch_proposal", patch_proposal_revision),
        )
        if not _revision_is_bound_to_feature(
            revision,
            feature_id=feature_id,
        )
    ]
    if not feature_id or not run_id or invalid_revision_types:
        blocker = {
            "stage": "binding_resolution",
            "code": "BINDING_RESOLUTION_LINEAGE_INVALID",
            "message": (
                "Runtime binding resolution requires current feature/run "
                "identity and bound RuntimeEvidence, ImplementationPlan, and "
                "PatchProposal revisions."
            ),
            "invalid_revision_types": invalid_revision_types,
        }
        return RuntimeBindingResolution(
            feature_id=feature_id,
            run_id=run_id,
            result_type="binding_resolution_blocked",
            runtime_evidence_revision=dict(runtime_evidence_revision),
            implementation_plan_revision=dict(
                implementation_plan_revision
            ),
            patch_proposal_revision=dict(patch_proposal_revision),
            allowed_edit_binding_ids=tuple(
                sorted(allowed_edit_binding_ids)
            ),
            resolved_repair_target=None,
            binding_gap=None,
            binding_proposal_request=None,
            blockers=(blocker,),
        )

    resolved = BindingResolver.from_implementation_plan(
        implementation_plan
    ).resolve_repair_target(
        diagnosis=diagnosis,
        feature_id=feature_id,
        run_id=run_id,
        implementation_plan_revision=implementation_plan_revision,
        allowed_binding_ids=allowed_edit_binding_ids,
    )
    if resolved.status == "resolved":
        return RuntimeBindingResolution(
            feature_id=feature_id,
            run_id=run_id,
            result_type="resolved_repair_target",
            runtime_evidence_revision=dict(runtime_evidence_revision),
            implementation_plan_revision=dict(
                implementation_plan_revision
            ),
            patch_proposal_revision=dict(patch_proposal_revision),
            allowed_edit_binding_ids=tuple(
                sorted(allowed_edit_binding_ids)
            ),
            resolved_repair_target=resolved.to_dict(),
            binding_gap=None,
            binding_proposal_request=None,
            blockers=(),
        )

    resolution_codes = {
        str(item.get("code"))
        for item in resolved.blockers
        if isinstance(item.get("code"), str)
    }
    is_binding_gap = bool(resolution_codes) and resolution_codes.issubset(
        _BINDING_GAP_CODES
    )
    if not is_binding_gap:
        blocker = {
            "stage": "binding_resolution",
            "code": "BINDING_RESOLUTION_INPUT_INVALID",
            "message": (
                "Runtime diagnosis or lineage is invalid; edit-authority "
                "discovery was not requested."
            ),
            "resolution_blockers": [
                dict(item) for item in resolved.blockers
            ],
        }
        return RuntimeBindingResolution(
            feature_id=feature_id,
            run_id=run_id,
            result_type="binding_resolution_blocked",
            runtime_evidence_revision=dict(runtime_evidence_revision),
            implementation_plan_revision=dict(
                implementation_plan_revision
            ),
            patch_proposal_revision=dict(patch_proposal_revision),
            allowed_edit_binding_ids=tuple(
                sorted(allowed_edit_binding_ids)
            ),
            resolved_repair_target=None,
            binding_gap=None,
            binding_proposal_request=None,
            blockers=(blocker,),
        )

    anchors = (
        dict(diagnosis.get("responsibility_anchors") or {})
        if isinstance(diagnosis, dict)
        else {}
    )
    evidence_refs = (
        [
            dict(item)
            for item in diagnosis.get("evidence_refs", ())
            if isinstance(item, dict)
        ]
        if isinstance(diagnosis, dict)
        else []
    )
    existing_bindings, missing_allowed_ids = _allowed_binding_views(
        implementation_plan,
        allowed_edit_binding_ids,
    )
    gap = {
        "schema_version": "binding_gap_v1",
        "gap": True,
        "reason": (
            "The diagnosed failure responsibility is not covered by exactly "
            "one current allowed edit binding."
        ),
        "gap_reasons": _binding_gap_reasons(
            resolved_target=resolved,
            diagnosis=diagnosis,
            implementation_plan=implementation_plan,
            allowed_edit_binding_ids=allowed_edit_binding_ids,
        ),
        "responsibility_anchors": anchors,
        "evidence_refs": evidence_refs,
        "existing_allowed_bindings": existing_bindings,
        "missing_allowed_binding_ids": missing_allowed_ids,
        "resolution_blockers": [
            dict(item) for item in resolved.blockers
        ],
    }
    proposal_request = {
        "schema_version": "binding_proposal_request_v1",
        "status": "requested",
        "requested_action": (
            "discover_current_source_and_submit_new_binding_proposal"
        ),
        "responsibility_anchors": anchors,
        "evidence_refs": evidence_refs,
        "required_source_identity": {
            "canonical_target_path": "required",
            "target_symbol": "required",
            "source_hash": "required",
            "target_span": "required",
        },
        "required_plan_lineage": dict(implementation_plan_revision),
        "approval_required": True,
        "registry_mutation_allowed": False,
        "repair_allowed": False,
        "authority_boundary": (
            "This request does not grant edit authority. A reviewed new "
            "implementation_plan revision must register the binding before "
            "repair planning can continue."
        ),
        "prohibited_resolution_methods": [
            "fuzzy_symbol_match",
            "source_hash_relaxation",
            "span_relaxation",
            "path_inference",
        ],
    }
    blocker = {
        "stage": "binding_resolution",
        "code": "BINDING_GAP",
        "message": (
            "A structured Runtime diagnosis exists, but no unique current "
            "allowed edit binding covers its responsibility."
        ),
        "resolution_blockers": [
            dict(item) for item in resolved.blockers
        ],
    }
    return RuntimeBindingResolution(
        feature_id=feature_id,
        run_id=run_id,
        result_type="binding_gap",
        runtime_evidence_revision=dict(runtime_evidence_revision),
        implementation_plan_revision=dict(implementation_plan_revision),
        patch_proposal_revision=dict(patch_proposal_revision),
        allowed_edit_binding_ids=tuple(sorted(allowed_edit_binding_ids)),
        resolved_repair_target=None,
        binding_gap=gap,
        binding_proposal_request=proposal_request,
        blockers=(blocker,),
    )


def _revision_is_bound_to_feature(
    revision: Any,
    *,
    feature_id: str,
) -> bool:
    return (
        isinstance(revision, dict)
        and revision.get("feature_id") == feature_id
        and isinstance(revision.get("path"), str)
        and bool(revision["path"])
        and isinstance(revision.get("artifact_hash"), str)
        and bool(revision["artifact_hash"])
    )


def _binding_gap_reasons(
    *,
    resolved_target: ResolvedRepairTarget,
    diagnosis: Any,
    implementation_plan: dict[str, Any],
    allowed_edit_binding_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    blocker_codes = {
        str(item.get("code"))
        for item in resolved_target.blockers
        if isinstance(item.get("code"), str)
    }
    if "REPAIR_TARGET_SYMBOL_UNRESOLVED" in blocker_codes:
        reasons.append("missing_symbol_binding")
    if "REPAIR_TARGET_SYMBOL_AMBIGUOUS" in blocker_codes:
        reasons.append("ambiguous_symbol_binding")
    if "DIAGNOSIS_SOURCE_IDENTITY_INCOMPLETE" in blocker_codes:
        reasons.append("diagnosis_source_identity_incomplete")
    if "REPAIR_TARGET_SOURCE_OR_SPAN_DRIFT" in blocker_codes:
        anchors = (
            diagnosis.get("responsibility_anchors")
            if isinstance(diagnosis, dict)
            else None
        )
        anchor_value = anchors if isinstance(anchors, dict) else {}
        exact_symbol_bindings = _allowed_bindings_for_symbol(
            implementation_plan,
            allowed_edit_binding_ids=allowed_edit_binding_ids,
            target_symbol=anchor_value.get("symbol"),
        )
        if len(exact_symbol_bindings) == 1:
            binding = exact_symbol_bindings[0]
            if binding.get("source_hash") != anchor_value.get("source_hash"):
                reasons.append("source_hash_mismatch")
            source_span = anchor_value.get("source_span")
            if not _span_contains(
                binding.get("target_span"),
                source_span,
            ):
                reasons.append("failure_span_outside_edit_scope")
    return reasons


def _allowed_bindings_for_symbol(
    implementation_plan: dict[str, Any],
    *,
    allowed_edit_binding_ids: set[str],
    target_symbol: Any,
) -> list[dict[str, Any]]:
    registry = implementation_plan.get("binding_registry")
    bindings = (
        registry.get("edit_bindings", ())
        if isinstance(registry, dict)
        else ()
    )
    return [
        binding
        for binding in bindings
        if isinstance(binding, dict)
        and binding.get("binding_id") in allowed_edit_binding_ids
        and isinstance(target_symbol, str)
        and binding.get("target_symbol") == target_symbol
    ]


def _span_contains(container: Any, inner: Any) -> bool:
    if not isinstance(container, dict) or not isinstance(inner, dict):
        return False
    values = (
        container.get("start_line"),
        container.get("end_line"),
        inner.get("start_line"),
        inner.get("end_line"),
    )
    if not all(isinstance(value, int) for value in values):
        return False
    container_start, container_end, inner_start, inner_end = values
    return (
        container_start <= inner_start <= inner_end <= container_end
    )


def _allowed_binding_views(
    implementation_plan: dict[str, Any],
    allowed_edit_binding_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    registry = implementation_plan.get("binding_registry")
    bindings = (
        registry.get("edit_bindings", ())
        if isinstance(registry, dict)
        else ()
    )
    views: list[dict[str, Any]] = []
    found_ids: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        binding_id = binding.get("binding_id")
        if (
            not isinstance(binding_id, str)
            or binding_id not in allowed_edit_binding_ids
        ):
            continue
        found_ids.add(binding_id)
        views.append(
            {
                "binding_id": binding_id,
                "canonical_target_path": binding.get(
                    "canonical_target_path"
                ),
                "target_symbol": binding.get("target_symbol"),
                "target_span": binding.get("target_span"),
                "source_hash": binding.get("source_hash"),
                "evidence_id": binding.get("evidence_id"),
            }
        )
    views.sort(key=lambda item: str(item["binding_id"]))
    return views, sorted(allowed_edit_binding_ids - found_ids)
