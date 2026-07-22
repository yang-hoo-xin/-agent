"""LLM boundary for evidence-bound exact-text patch generation."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.libs.llm import BaseLLM, ChatResponse, Message

_LITERAL_VALIDATION_MARKER_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")


class PatchGenerationError(RuntimeError):
    """Raised when model output cannot become a controlled patch proposal."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_content: str | None = None,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_content = diagnostic_content
        self.diagnostics = dict(diagnostics or {})


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
        required_validation_by_binding: Mapping[str, list[str] | tuple[str, ...]]
        | None = None,
        require_native_schema: bool = False,
        provider_request_recorder: Callable[[dict[str, Any]], None] | None = None,
        post_response_admission: Callable[[ChatResponse], None] | None = None,
    ) -> GeneratedPatch:
        allowed_bindings = {
            str(item["binding_id"])
            for item in binding_registry.get("edit_bindings") or []
            if isinstance(item, dict) and item.get("binding_id")
        }
        if not allowed_bindings:
            raise PatchGenerationError("No editable binding is available for generation.")

        evidence_by_id = {
            str(item["evidence_id"]): item
            for item in evidence_items
            if isinstance(item, dict) and item.get("evidence_id")
        }
        binding_contexts: dict[str, dict[str, Any]] = {}
        for binding in binding_registry.get("edit_bindings") or []:
            if not isinstance(binding, dict) or not binding.get("binding_id"):
                continue
            evidence = evidence_by_id.get(str(binding.get("evidence_id") or "")) or {}
            binding_contexts[str(binding["binding_id"])] = {
                field: binding.get(field) or evidence.get(evidence_field)
                for field, evidence_field in (
                    ("canonical_target_path", "source_path"),
                    ("declaring_type", "declaring_type"),
                    ("method_name", "method_name"),
                    ("parameter_types", "parameter_types"),
                    ("return_type", "return_type"),
                    ("method_kind", "method_kind"),
                )
            }

        required_validation = {
            str(binding_id): tuple(str(item) for item in values)
            for binding_id, values in (required_validation_by_binding or {}).items()
        }
        unknown_required_bindings = set(required_validation) - allowed_bindings
        if unknown_required_bindings:
            raise PatchGenerationError(
                "Required validation references an unknown edit binding id."
            )

        response_schema = _patch_response_schema(allowed_bindings)
        evidence_excerpts = tuple(
            excerpt
            for item in evidence_items
            if isinstance(item, dict)
            and isinstance((excerpt := item.get("excerpt")), str)
            and excerpt
        )
        required_output = {
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
        }
        output_contract = (
            {"required_output_schema": response_schema}
            if require_native_schema
            else {"required_output": required_output}
        )
        chat_kwargs: dict[str, Any] = {"temperature": 0.0}
        if require_native_schema:
            if provider_request_recorder is None:
                raise PatchGenerationError(
                    "Native patch schema requires a durable provider request recorder."
                )
            chat_kwargs.update(
                {
                    "response_format": response_schema,
                    "provider_request_recorder": provider_request_recorder,
                }
            )

        response = self.llm.chat(
            [
                Message(
                    role="system",
                    content=(
                        "Generate a minimal exact-text code patch from verified evidence. "
                        "Return strict JSON only. Never invent a file path, symbol, API, or "
                        "binding id. Each change must use one allowed edit_binding_id and an "
                        "exact_text_replace patch whose before_text is copied verbatim from "
                        "the evidence, including its exact line endings. Any "
                        "required_validation_by_binding entries are authoritative upstream "
                        "requirements and must all be copied into the matching change's "
                        "expected_validation list. Any "
                        "expected_validation entry formatted as an uppercase identifier is "
                        "a literal marker and must appear in after_text. Do not include "
                        "markdown fences."
                    ),
                ),
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "request": user_request,
                            "constraints": constraints,
                            "allowed_edit_binding_ids": sorted(allowed_bindings),
                            "edit_binding_contexts": binding_contexts,
                            "required_validation_by_binding": {
                                binding_id: list(values)
                                for binding_id, values in sorted(
                                    required_validation.items()
                                )
                            },
                            "evidence": evidence_items,
                            **output_contract,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            ],
            **chat_kwargs,
        )
        try:
            if post_response_admission is not None:
                post_response_admission(response)
            payload = _parse_json_object(response.content)
            raw_changes = payload.get("changes")
            if not isinstance(raw_changes, list) or not raw_changes:
                raise PatchGenerationError(
                    "Model output must contain a non-empty changes list."
                )
            changes = tuple(
                _validate_change(
                    item,
                    allowed_bindings=allowed_bindings,
                    evidence_excerpts=evidence_excerpts,
                    required_validation=required_validation,
                    binding_contexts=binding_contexts,
                    index=index,
                )
                for index, item in enumerate(raw_changes, start=1)
            )
        except Exception as exc:
            diagnostics = _response_diagnostics(response)
            if isinstance(exc, PatchGenerationError):
                diagnostics.update(exc.diagnostics)
                raise PatchGenerationError(
                    str(exc),
                    diagnostic_content=response.content,
                    diagnostics=diagnostics,
                ) from exc
            setattr(exc, "diagnostic_content", response.content)
            existing = getattr(exc, "diagnostics", None)
            if isinstance(existing, Mapping):
                diagnostics.update(existing)
            setattr(exc, "diagnostics", diagnostics)
            raise
        return GeneratedPatch(
            changes=changes,
            model=response.model,
            usage=response.usage,
            raw_text=response.content,
        )


def _patch_response_schema(allowed_bindings: set[str]) -> dict[str, Any]:
    """Return the single schema used by the local prompt and native format."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["changes"],
        "properties": {
            "changes": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "change_id",
                        "change_type",
                        "edit_binding_id",
                        "operation",
                        "rationale",
                        "expected_validation",
                        "rollback_hint",
                        "patch",
                    ],
                    "properties": {
                        "change_id": {"type": "string", "minLength": 1},
                        "change_type": {"const": "modify_behavior"},
                        "edit_binding_id": {
                            "type": "string",
                            "enum": sorted(allowed_bindings),
                        },
                        "operation": {"const": "exact_text_replace"},
                        "rationale": {"type": "string", "minLength": 1},
                        "expected_validation": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "rollback_hint": {"type": "string", "minLength": 1},
                        "patch": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "kind",
                                "before_text",
                                "after_text",
                                "expected_occurrences",
                            ],
                            "properties": {
                                "kind": {"const": "exact_text_replace"},
                                "before_text": {"type": "string", "minLength": 1},
                                "after_text": {"type": "string", "minLength": 1},
                                "expected_occurrences": {"const": 1},
                            },
                        },
                    },
                },
            }
        },
    }


def _response_diagnostics(response: ChatResponse) -> dict[str, Any]:
    raw = response.raw_response if isinstance(response.raw_response, Mapping) else {}
    return {
        "failure_boundary": "deterministic_patch_validation",
        "response_model": response.model,
        "done": raw.get("done"),
        "done_reason": raw.get("done_reason"),
        "usage": dict(response.usage) if response.usage is not None else None,
    }


def _parse_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PatchGenerationError(
            f"Model output is not strict JSON: {exc}",
            diagnostics={
                "failure_boundary": "deterministic_patch_validation",
                "failure_classification": "malformed_structured_output",
                "json_error_line": exc.lineno,
                "json_error_column": exc.colno,
                "json_error_character_index": exc.pos,
            },
        ) from exc
    if not isinstance(value, dict):
        raise PatchGenerationError("Model output root must be an object.")
    return value


def _validate_change(
    raw: Any,
    *,
    allowed_bindings: set[str],
    evidence_excerpts: tuple[str, ...],
    required_validation: Mapping[str, tuple[str, ...]],
    binding_contexts: Mapping[str, Mapping[str, Any]],
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
    if not any(before in excerpt for excerpt in evidence_excerpts):
        raise PatchGenerationError(
            f"Change {index} before_text is not verbatim current evidence.",
            diagnostics={
                "failure_boundary": "deterministic_patch_validation",
                "failure_classification": "before_text_not_verbatim_evidence",
            },
        )
    if not isinstance(after, str) or not after or after == before:
        raise PatchGenerationError(f"Change {index} after_text must be a real replacement.")
    _validate_bound_language_semantics(
        after=after,
        binding_id=binding_id,
        binding_contexts=binding_contexts,
        index=index,
    )
    if patch.get("expected_occurrences") != 1:
        raise PatchGenerationError(f"Change {index} expected_occurrences must equal 1.")
    expected_validation = [
        str(item) for item in raw.get("expected_validation") or ["dotnet build"]
    ]
    missing_upstream_validation = [
        item
        for item in required_validation.get(binding_id, ())
        if item not in expected_validation
    ]
    if missing_upstream_validation:
        raise PatchGenerationError(
            f"Change {index} omits upstream validation requirement(s): "
            + ", ".join(missing_upstream_validation),
            diagnostics={
                "failure_boundary": "deterministic_patch_validation",
                "failure_classification": "upstream_validation_omitted",
                "missing_upstream_validation": missing_upstream_validation,
            },
        )
    missing_markers = [
        marker
        for marker in expected_validation
        if _LITERAL_VALIDATION_MARKER_RE.fullmatch(marker) and marker not in after
    ]
    if missing_markers:
        raise PatchGenerationError(
            f"Change {index} after_text is missing declared validation marker(s): "
            + ", ".join(missing_markers),
            diagnostics={
                "failure_boundary": "deterministic_patch_validation",
                "failure_classification": "declared_validation_marker_missing",
                "missing_validation_markers": missing_markers,
            },
        )
    return {
        "change_id": str(raw.get("change_id") or f"change_{index:03d}"),
        "change_type": str(raw.get("change_type") or "modify_behavior"),
        "edit_binding_id": binding_id,
        "supporting_binding_ids": [],
        "operation": "exact_text_replace",
        "rationale": str(raw.get("rationale") or "Evidence-bound minimal change."),
        "risk_tags": ["medium"],
        "expected_validation": expected_validation,
        "rollback_hint": str(raw.get("rollback_hint") or "Restore before_text."),
        "patch": {
            "kind": "exact_text_replace",
            "before_text": before,
            "after_text": after,
            "expected_occurrences": 1,
        },
    }


def _validate_bound_language_semantics(
    *,
    after: str,
    binding_id: str,
    binding_contexts: Mapping[str, Mapping[str, Any]],
    index: int,
) -> None:
    context = binding_contexts.get(binding_id) or {}
    source_path = context.get("canonical_target_path")
    return_type = context.get("return_type")
    if not isinstance(source_path, str) or not source_path.lower().endswith(".cs"):
        return
    if return_type != "void":
        return
    code_only = _strip_csharp_non_code(after)
    invalid_returns = [
        match.group(1).strip()
        for match in re.finditer(r"\breturn\b\s*([^;]*);", code_only)
        if match.group(1).strip()
    ]
    if invalid_returns:
        raise PatchGenerationError(
            f"Change {index} returns a value from bound void method.",
            diagnostics={
                "failure_boundary": "deterministic_patch_validation",
                "failure_classification": "csharp_return_value_in_void_method",
                "binding_id": binding_id,
                "method_name": context.get("method_name"),
                "return_type": return_type,
            },
        )


def _strip_csharp_non_code(value: str) -> str:
    """Replace C# comments and string/character contents while preserving layout."""

    selected: list[str] = []
    index = 0
    state = "code"
    while index < len(value):
        current = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""
        if state == "code":
            if current == "/" and following == "/":
                selected.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                selected.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if current == '"':
                selected.append(" ")
                index += 1
                state = "verbatim_string" if index >= 2 and value[index - 2] == "@" else "string"
                continue
            if current == "'":
                selected.append(" ")
                index += 1
                state = "character"
                continue
            selected.append(current)
            index += 1
            continue
        if state == "line_comment":
            selected.append(current if current in "\r\n" else " ")
            index += 1
            if current == "\n":
                state = "code"
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                selected.extend("  ")
                index += 2
                state = "code"
            else:
                selected.append(current if current in "\r\n" else " ")
                index += 1
            continue
        if state == "verbatim_string":
            if current == '"' and following == '"':
                selected.extend("  ")
                index += 2
            elif current == '"':
                selected.append(" ")
                index += 1
                state = "code"
            else:
                selected.append(current if current in "\r\n" else " ")
                index += 1
            continue
        if current == "\\":
            selected.append(" ")
            if following:
                selected.append(" ")
                index += 2
            else:
                index += 1
            continue
        if (state == "string" and current == '"') or (
            state == "character" and current == "'"
        ):
            selected.append(" ")
            index += 1
            state = "code"
            continue
        selected.append(current if current in "\r\n" else " ")
        index += 1
    return "".join(selected)
