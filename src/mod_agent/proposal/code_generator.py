"""LLM boundary for evidence-bound exact-text patch generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.libs.llm import BaseLLM, Message


class PatchGenerationError(RuntimeError):
    """Raised when model output cannot become a controlled patch proposal."""


@dataclass(frozen=True)
class GeneratedPatch:
    changes: tuple[dict[str, Any], ...]
    model: str
    usage: dict[str, int] | None
    raw_text: str


class LLMExactPatchGenerator:
    """Generate exact replacements without allowing the model to select paths."""

    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm

    def generate(
        self,
        *,
        user_request: str,
        evidence_items: list[dict[str, Any]],
        binding_registry: dict[str, Any],
        constraints: list[str],
    ) -> GeneratedPatch:
        allowed_bindings = {
            str(item["binding_id"])
            for item in binding_registry.get("edit_bindings") or []
            if isinstance(item, dict) and item.get("binding_id")
        }
        if not allowed_bindings:
            raise PatchGenerationError("No editable binding is available for generation.")

        response = self.llm.chat(
            [
                Message(
                    role="system",
                    content=(
                        "Generate a minimal exact-text code patch from verified evidence. "
                        "Return strict JSON only. Never invent a file path, symbol, API, or "
                        "binding id. Each change must use one allowed edit_binding_id and an "
                        "exact_text_replace patch whose before_text is copied verbatim from "
                        "the evidence. Do not include markdown fences."
                    ),
                ),
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "request": user_request,
                            "constraints": constraints,
                            "allowed_edit_binding_ids": sorted(allowed_bindings),
                            "evidence": evidence_items,
                            "required_output": {
                                "changes": [
                                    {
                                        "change_id": "string",
                                        "change_type": "modify_behavior",
                                        "edit_binding_id": "allowed id",
                                        "operation": "exact_text_replace",
                                        "rationale": "string",
                                        "expected_validation": ["dotnet build"],
                                        "rollback_hint": "string",
                                        "patch": {
                                            "kind": "exact_text_replace",
                                            "before_text": "verbatim source text",
                                            "after_text": "replacement text",
                                            "expected_occurrences": 1,
                                        },
                                    }
                                ]
                            },
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ],
            temperature=0.0,
        )
        payload = _parse_json_object(response.content)
        raw_changes = payload.get("changes")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise PatchGenerationError("Model output must contain a non-empty changes list.")
        changes = tuple(
            _validate_change(item, allowed_bindings=allowed_bindings, index=index)
            for index, item in enumerate(raw_changes, start=1)
        )
        return GeneratedPatch(
            changes=changes,
            model=response.model,
            usage=response.usage,
            raw_text=response.content,
        )


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PatchGenerationError(f"Model output is not strict JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PatchGenerationError("Model output root must be an object.")
    return value


def _validate_change(
    raw: Any,
    *,
    allowed_bindings: set[str],
    index: int,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PatchGenerationError(f"Change {index} must be an object.")
    binding_id = str(raw.get("edit_binding_id") or "")
    if binding_id not in allowed_bindings:
        raise PatchGenerationError(f"Change {index} uses an unknown edit binding id.")
    if any(raw.get(key) is not None for key in ("target_file", "edit_target_path", "path")):
        raise PatchGenerationError(f"Change {index} must not copy or invent a path.")
    patch = raw.get("patch")
    if not isinstance(patch, dict) or patch.get("kind") != "exact_text_replace":
        raise PatchGenerationError(f"Change {index} requires an exact_text_replace patch.")
    before = patch.get("before_text")
    after = patch.get("after_text")
    if not isinstance(before, str) or not before:
        raise PatchGenerationError(f"Change {index} before_text must be non-empty.")
    if not isinstance(after, str) or not after or after == before:
        raise PatchGenerationError(f"Change {index} after_text must be a real replacement.")
    if patch.get("expected_occurrences") != 1:
        raise PatchGenerationError(f"Change {index} expected_occurrences must equal 1.")
    return {
        "change_id": str(raw.get("change_id") or f"change_{index:03d}"),
        "change_type": str(raw.get("change_type") or "modify_behavior"),
        "edit_binding_id": binding_id,
        "supporting_binding_ids": [],
        "operation": "exact_text_replace",
        "rationale": str(raw.get("rationale") or "Evidence-bound minimal change."),
        "risk_tags": ["medium"],
        "expected_validation": [
            str(item) for item in raw.get("expected_validation") or ["dotnet build"]
        ],
        "rollback_hint": str(raw.get("rollback_hint") or "Restore before_text."),
        "patch": {
            "kind": "exact_text_replace",
            "before_text": before,
            "after_text": after,
            "expected_occurrences": 1,
        },
    }
