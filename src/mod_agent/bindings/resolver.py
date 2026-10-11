"""Resolve proposal and repair binding IDs against implementation_plan."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from src.mod_agent.evidence.requirement_coverage import (
    validated_requirement_coverage_view,
)


@dataclass(frozen=True)
class BindingValidationResult:
    """Validation result for binding registry consumers."""

    allowed: bool
    blockers: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ResolvedRepairTarget:
    """One diagnosis target resolved through current lineage and edit authority."""

    status: str
    feature_id: str
    run_id: str
    implementation_plan_revision: dict[str, Any]
    diagnosis_schema_version: str | None
    failure_class: str | None
    responsibility_anchors: dict[str, Any]
    evidence_refs: tuple[dict[str, Any], ...]
    binding_id: str | None = None
    canonical_target_path: str | None = None
    root_cause_status: str | None = None
    unresolved_root_causes: tuple[str, ...] = ()
    blockers: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "resolved_repair_target_v1",
            "status": self.status,
            "feature_id": self.feature_id,
            "run_id": self.run_id,
            "implementation_plan_revision": dict(
                self.implementation_plan_revision
            ),
            "diagnosis_schema_version": self.diagnosis_schema_version,
            "failure_class": self.failure_class,
            "responsibility_anchors": dict(self.responsibility_anchors),
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "binding_id": self.binding_id,
            "canonical_target_path": self.canonical_target_path,
            "root_cause_status": self.root_cause_status,
            "unresolved_root_causes": list(self.unresolved_root_causes),
            "blockers": [dict(item) for item in self.blockers],
        }


class BindingResolver:
    """Validate binding IDs without trusting copied proposal fields."""

    def __init__(
        self,
        *,
        binding_registry: dict[str, Any],
        evidence_pack: dict[str, Any] | None = None,
    ) -> None:
        self.binding_registry = binding_registry
        self.evidence_pack = evidence_pack or {}
        self.edit_bindings = {
            str(binding["binding_id"]): binding
            for binding in binding_registry.get("edit_bindings") or []
            if isinstance(binding, dict) and binding.get("binding_id")
        }
        self.supporting_bindings = {
            str(binding["binding_id"]): binding
            for binding in binding_registry.get("supporting_bindings") or []
            if isinstance(binding, dict) and binding.get("binding_id")
        }

    @classmethod
    def from_implementation_plan(
        cls,
        implementation_plan: dict[str, Any] | None,
        *,
        evidence_pack: dict[str, Any] | None = None,
    ) -> "BindingResolver":
        plan = implementation_plan if isinstance(implementation_plan, dict) else {}
        registry = plan.get("binding_registry")
        if not isinstance(registry, dict):
            registry = {
                "schema_version": "binding_registry_v1",
                "edit_bindings": [],
                "supporting_bindings": [],
            }
        return cls(binding_registry=registry, evidence_pack=evidence_pack)

    def validate_registry_against_evidence(self) -> BindingValidationResult:
        evidence_items = {
            str(item["evidence_id"]): item
            for item in self.evidence_pack.get("items") or []
            if isinstance(item, dict) and item.get("evidence_id")
        }
        blockers: list[dict[str, Any]] = []
        try:
            coverage_view = validated_requirement_coverage_view(
                self.evidence_pack
            )
        except ValueError as exc:
            blockers.append(
                {
                    "code": "REQUIREMENT_COVERAGE_INVALID",
                    "message": str(exc),
                }
            )
            coverage_view = None
        coverage_change_support_ids = (
            coverage_view.change_support_evidence_ids
            if coverage_view is not None
            else set()
            if "requirement_coverage" in self.evidence_pack
            else None
        )
        from src.mod_agent.evidence.compilation_candidate import compilation_candidate_scope

        try:
            candidate = compilation_candidate_scope(self.evidence_pack)
            if candidate is not None:
                coverage_change_support_ids = frozenset(candidate["evidence_ids"])
        except ValueError as exc:
            blockers.append({"code": "COMPILATION_CANDIDATE_SCOPE_INVALID", "message": str(exc)})
        for binding in self.edit_bindings.values():
            evidence_id = str(binding.get("evidence_id") or "")
            if (
                coverage_change_support_ids is not None
                and evidence_id not in coverage_change_support_ids
            ):
                blockers.append(
                    _blocker(
                        "EDIT_BINDING_OUTSIDE_REQUIREMENT_COVERAGE",
                        (
                            "Edit binding evidence_id is not in the complete "
                            "requirement-coverage change-support pool."
                        ),
                        binding,
                    )
                )
            item = evidence_items.get(evidence_id)
            if item is None:
                blockers.append(
                    _blocker(
                        "BINDING_EVIDENCE_MISSING",
                        "Edit binding evidence_id is not present in evidence_pack.",
                        binding,
                    )
                )
                continue
            if item.get("source_type") != "target_source":
                blockers.append(
                    _blocker(
                        "EDIT_BINDING_NOT_TARGET_SOURCE",
                        "Edit binding must resolve to target_source evidence.",
                        binding,
                    )
                )
            if (
                not isinstance(item.get("source_path"), str)
                or not item["source_path"]
                or _physical_source_revision_hash(item) is None
                or _exact_line_span(item.get("span")) is None
            ):
                blockers.append(
                    _blocker(
                        "BINDING_EVIDENCE_DRIFT",
                        (
                            "Edit binding evidence does not carry an exact "
                            "current source identity."
                        ),
                        binding,
                    )
                )
            checks = (
                ("canonical_target_path", "source_path", "path"),
                (
                    "source_hash",
                    "physical_source_revision",
                    "source_hash",
                ),
                ("target_symbol", "symbol", "symbol"),
                ("target_span", "span", "span"),
            )
            for binding_key, evidence_key, label in checks:
                evidence_value = (
                    _physical_source_revision_hash(item)
                    if evidence_key == "physical_source_revision"
                    else item.get(evidence_key)
                )
                if binding.get(binding_key) != evidence_value:
                    blockers.append(
                        _blocker(
                            "BINDING_EVIDENCE_DRIFT",
                            f"Edit binding {label} does not match evidence_pack.",
                            binding,
                        )
                    )
        for binding in self.supporting_bindings.values():
            evidence_id = str(binding.get("evidence_id") or "")
            item = evidence_items.get(evidence_id)
            if item is None:
                blockers.append(
                    _blocker(
                        "SUPPORTING_BINDING_EVIDENCE_MISSING",
                        "Supporting binding evidence_id is not present in evidence_pack.",
                        binding,
                    )
                )
                continue
            checks = (
                ("source_path", "source_path", "path"),
                ("target_symbol", "symbol", "symbol"),
                ("target_span", "span", "span"),
                ("source_type", "source_type", "source_type"),
                ("declaring_type", "declaring_type", "declaring_type"),
                ("method_name", "method_name", "method_name"),
                ("parameter_types", "parameter_types", "parameter_types"),
                ("return_type", "return_type", "return_type"),
                ("method_kind", "method_kind", "method_kind"),
            )
            for binding_key, evidence_key, label in checks:
                if _normalized_value(binding.get(binding_key)) != _normalized_value(
                    item.get(evidence_key)
                ):
                    blockers.append(
                        _blocker(
                            "SUPPORTING_BINDING_EVIDENCE_DRIFT",
                            f"Supporting binding {label} does not match evidence_pack.",
                            binding,
                        )
                    )
            if not _supporting_usage_matches_source_type(binding, item):
                blockers.append(
                    _blocker(
                        "SUPPORTING_BINDING_USAGE_MISMATCH",
                        "Supporting binding usage does not match evidence source_type.",
                        binding,
                    )
                )
        return BindingValidationResult(allowed=not blockers, blockers=tuple(blockers))

    def validate_proposal_changes(
        self,
        proposal: dict[str, Any],
    ) -> BindingValidationResult:
        blockers: list[dict[str, Any]] = []
        for change in proposal.get("diff_intent") or []:
            if not isinstance(change, dict):
                continue
            change_id = change.get("change_id")
            copied_fields = {
                key
                for key in (
                    "target_file",
                    "edit_target_path",
                    "evidence_source_path",
                    "target_symbol",
                    "source_span",
                )
                if key in change and change.get(key) is not None
            }
            if copied_fields:
                blockers.append(
                    {
                        "code": "PROPOSAL_COPIES_BINDING_FIELDS",
                        "message": (
                            "Proposal changes must reference binding IDs instead of "
                            "copying path, symbol, or span fields."
                        ),
                        "change_id": change_id,
                        "fields": sorted(copied_fields),
                    }
                )
            binding_id = change.get("edit_binding_id")
            if not binding_id:
                blockers.append(
                    {
                        "code": "EDIT_BINDING_ID_MISSING",
                        "message": "Change unit is missing edit_binding_id.",
                        "change_id": change_id,
                    }
                )
                continue
            if str(binding_id) not in self.edit_bindings:
                blockers.append(
                    {
                        "code": "EDIT_BINDING_UNKNOWN",
                        "message": "Change unit edit_binding_id is not in binding_registry.",
                        "change_id": change_id,
                        "binding_id": str(binding_id),
                    }
                )
            for support_id in change.get("supporting_binding_ids") or []:
                support_id = str(support_id)
                if support_id not in self.supporting_bindings and support_id not in self.edit_bindings:
                    blockers.append(
                        {
                            "code": "SUPPORTING_BINDING_UNKNOWN",
                            "message": (
                                "Change unit supporting_binding_ids contains an "
                                "unknown binding id."
                            ),
                            "change_id": change_id,
                            "binding_id": support_id,
                        }
                    )
            hook_target_binding_id = change.get("hook_target_binding_id")
            if hook_target_binding_id and str(hook_target_binding_id) not in self.supporting_bindings:
                blockers.append(
                    {
                        "code": "HOOK_TARGET_BINDING_UNKNOWN",
                        "message": (
                            "Change unit hook_target_binding_id is not in "
                            "binding_registry supporting_bindings."
                        ),
                        "change_id": change_id,
                        "binding_id": str(hook_target_binding_id),
                    }
                )
        return BindingValidationResult(allowed=not blockers, blockers=tuple(blockers))

    def validate_repair_subset(
        self,
        *,
        repair_plan: dict[str, Any],
        proposal: dict[str, Any],
    ) -> BindingValidationResult:
        allowed = {str(value) for value in repair_plan.get("allowed_edit_binding_ids") or []}
        blockers: list[dict[str, Any]] = []
        for change in proposal.get("diff_intent") or []:
            if not isinstance(change, dict):
                continue
            binding_id = change.get("edit_binding_id")
            if not binding_id or str(binding_id) not in allowed:
                blockers.append(
                    {
                        "code": "REPAIR_BINDING_OUT_OF_SCOPE",
                        "message": "Repair proposal binding id is outside repair_plan scope.",
                        "change_id": change.get("change_id"),
                        "binding_id": str(binding_id or ""),
                    }
                )
        return BindingValidationResult(allowed=not blockers, blockers=tuple(blockers))

    def display_files_for_edit_ids(self, binding_ids: list[str] | tuple[str, ...]) -> list[str]:
        paths: list[str] = []
        for binding_id in binding_ids:
            binding = self.edit_bindings.get(str(binding_id))
            if not binding:
                continue
            path = binding.get("canonical_target_path")
            if isinstance(path, str) and path not in paths:
                paths.append(path)
        return paths

    def resolve_edit_binding_for_path(
        self,
        raw_path: str,
        *,
        allowed_binding_ids: set[str] | None = None,
    ) -> tuple[str | None, str | None]:
        allowed = set(self.edit_bindings) if allowed_binding_ids is None else allowed_binding_ids
        normalized = _normalize_path(raw_path)
        matches = [
            binding_id
            for binding_id, binding in self.edit_bindings.items()
            if binding_id in allowed
            and _normalize_path(str(binding.get("canonical_target_path") or "")) == normalized
        ]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, "ambiguous"
        return None, "unresolved"

    def resolve_repair_target(
        self,
        *,
        diagnosis: Any,
        feature_id: str,
        run_id: str,
        implementation_plan_revision: dict[str, Any],
        allowed_binding_ids: set[str],
    ) -> ResolvedRepairTarget:
        """Resolve diagnosis anchors to exactly one current allowed edit binding."""

        diagnosis_value = diagnosis if isinstance(diagnosis, dict) else {}
        anchors = diagnosis_value.get("responsibility_anchors")
        anchor_value = anchors if isinstance(anchors, dict) else {}
        evidence_refs = tuple(
            dict(item)
            for item in diagnosis_value.get("evidence_refs", ())
            if isinstance(item, dict)
        )
        blockers: list[dict[str, Any]] = []
        if not feature_id or not run_id:
            blockers.append(
                _repair_target_blocker(
                    "REPAIR_TARGET_LINEAGE_INCOMPLETE",
                    "Current feature_id and run_id are required.",
                )
            )
        if (
            implementation_plan_revision.get("feature_id") != feature_id
            or not implementation_plan_revision.get("artifact_hash")
            or not implementation_plan_revision.get("path")
        ):
            blockers.append(
                _repair_target_blocker(
                    "IMPLEMENTATION_PLAN_REVISION_UNBOUND",
                    (
                        "The current implementation_plan revision is not bound "
                        "to this feature."
                    ),
                )
            )
        if (
            diagnosis_value.get("status") != "diagnosed"
            or diagnosis_value.get("feature_id") != feature_id
            or not anchor_value
            or not evidence_refs
        ):
            blockers.append(
                _repair_target_blocker(
                    "DIAGNOSIS_RESPONSIBILITY_ANCHORS_INVALID",
                    (
                        "Structured diagnosis is missing current feature identity, "
                        "responsibility anchors, or evidence refs."
                    ),
                )
            )

        target_symbol = anchor_value.get("symbol")
        matches = [
            binding_id
            for binding_id, binding in self.edit_bindings.items()
            if binding_id in allowed_binding_ids
            and isinstance(target_symbol, str)
            and binding.get("target_symbol") == target_symbol
        ]
        if not matches:
            blockers.append(
                _repair_target_blocker(
                    "REPAIR_TARGET_SYMBOL_UNRESOLVED",
                    (
                        "No current allowed edit binding has the diagnosed "
                        "responsibility symbol."
                    ),
                )
            )
        elif len(matches) > 1:
            blockers.append(
                _repair_target_blocker(
                    "REPAIR_TARGET_SYMBOL_AMBIGUOUS",
                    (
                        "More than one current allowed edit binding has the "
                        "diagnosed responsibility symbol."
                    ),
                )
            )

        binding_id = matches[0] if len(matches) == 1 else None
        binding = (
            self.edit_bindings.get(binding_id)
            if binding_id is not None
            else None
        )
        source_hash = anchor_value.get("source_hash")
        source_span = anchor_value.get("source_span")
        if not isinstance(source_hash, str) or not source_hash or not isinstance(
            source_span, dict
        ):
            blockers.append(
                _repair_target_blocker(
                    "DIAGNOSIS_SOURCE_IDENTITY_INCOMPLETE",
                    (
                        "Diagnosis does not bind the failure symbol to a current "
                        "source hash and exact span."
                    ),
                )
            )
        elif binding is not None and (
            binding.get("source_hash") != source_hash
            or not _span_contains(binding.get("target_span"), source_span)
        ):
            blockers.append(
                _repair_target_blocker(
                    "REPAIR_TARGET_SOURCE_OR_SPAN_DRIFT",
                    (
                        "The diagnosed current source identity does not match, "
                        "or the allowed edit binding does not cover the exact "
                        "failure span."
                    ),
                )
            )

        status = "resolved" if not blockers and binding is not None else "blocked"
        return ResolvedRepairTarget(
            status=status,
            feature_id=feature_id,
            run_id=run_id,
            implementation_plan_revision=dict(implementation_plan_revision),
            diagnosis_schema_version=(
                str(diagnosis_value["schema_version"])
                if isinstance(diagnosis_value.get("schema_version"), str)
                else None
            ),
            failure_class=(
                str(diagnosis_value["failure_class"])
                if isinstance(diagnosis_value.get("failure_class"), str)
                else None
            ),
            responsibility_anchors=dict(anchor_value),
            evidence_refs=evidence_refs,
            binding_id=binding_id if status == "resolved" else None,
            canonical_target_path=(
                str(binding["canonical_target_path"])
                if status == "resolved"
                and isinstance(binding.get("canonical_target_path"), str)
                else None
            ),
            root_cause_status=(
                str(diagnosis_value["root_cause_status"])
                if isinstance(diagnosis_value.get("root_cause_status"), str)
                else None
            ),
            unresolved_root_causes=tuple(
                str(item)
                for item in diagnosis_value.get("unresolved_root_causes", ())
                if isinstance(item, str)
            ),
            blockers=tuple(blockers),
        )


def _blocker(code: str, message: str, binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "binding_id": binding.get("binding_id"),
        "evidence_id": binding.get("evidence_id"),
    }


def _repair_target_blocker(code: str, message: str) -> dict[str, Any]:
    return {
        "stage": "binding_resolution",
        "code": code,
        "message": message,
    }


def _span_contains(container: Any, inner: dict[str, Any]) -> bool:
    if not isinstance(container, dict):
        return False
    container_start = container.get("start_line")
    container_end = container.get("end_line")
    inner_start = inner.get("start_line")
    inner_end = inner.get("end_line")
    if not all(
        isinstance(value, int)
        for value in (
            container_start,
            container_end,
            inner_start,
            inner_end,
        )
    ):
        return False
    return (
        container_start <= inner_start <= inner_end <= container_end
    )


def _normalize_path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/"))).strip("/")


def _normalized_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    return value


def _physical_source_revision_hash(item: dict[str, Any]) -> str | None:
    source_hash = item.get("source_hash")
    file_hash = item.get("file_hash")
    if source_hash not in (None, "") and (
        not isinstance(source_hash, str) or not source_hash
    ):
        return None
    if file_hash not in (None, "") and (
        not isinstance(file_hash, str) or not file_hash
    ):
        return None
    if source_hash and file_hash and source_hash != file_hash:
        return None
    selected = source_hash or file_hash
    return selected if isinstance(selected, str) and selected else None


def _exact_line_span(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    start_line = value.get("start_line")
    end_line = value.get("end_line")
    if (
        type(start_line) is not int
        or type(end_line) is not int
        or start_line < 1
        or end_line < start_line
    ):
        return None
    return start_line, end_line


def _supporting_usage_matches_source_type(
    binding: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    usage = binding.get("usage")
    source_type = item.get("source_type")
    if source_type == "target_source":
        return usage in {"edit_source_evidence", "hook_target_or_supporting_evidence"}
    if source_type == "decompiled_api":
        return usage in {"hook_target", "hook_target_or_supporting_evidence"}
    return usage == "hook_target_or_supporting_evidence"
