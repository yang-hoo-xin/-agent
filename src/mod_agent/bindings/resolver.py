"""Resolve proposal and repair binding IDs against implementation_plan."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True)
class BindingValidationResult:
    """Validation result for binding registry consumers."""

    allowed: bool
    blockers: tuple[dict[str, Any], ...] = ()


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
        for binding in self.edit_bindings.values():
            evidence_id = str(binding.get("evidence_id") or "")
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
            checks = (
                ("canonical_target_path", "source_path", "path"),
                ("target_symbol", "symbol", "symbol"),
                ("target_span", "span", "span"),
            )
            for binding_key, evidence_key, label in checks:
                if binding.get(binding_key) != item.get(evidence_key):
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
            )
            for binding_key, evidence_key, label in checks:
                if binding.get(binding_key) != item.get(evidence_key):
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


def _blocker(code: str, message: str, binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "binding_id": binding.get("binding_id"),
        "evidence_id": binding.get("evidence_id"),
    }


def _normalize_path(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/"))).strip("/")


def _supporting_usage_matches_source_type(
    binding: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    usage = binding.get("usage")
    source_type = item.get("source_type")
    if source_type == "target_source":
        return usage in {"edit_source_evidence", "hook_target_or_supporting_evidence"}
    return usage == "hook_target_or_supporting_evidence"
