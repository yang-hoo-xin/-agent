from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]

CONTROL_MODULES = (
    "src/mod_agent/actual_execution.py",
    "src/mod_agent/entry_admission.py",
    "src/mod_agent/product_execution.py",
    "src/mod_agent/product_executor.py",
    "src/mod_agent/local_entry.py",
    "src/mod_agent/cli.py",
    "src/mod_agent/edit_authority_capabilities.py",
    "src/mod_agent/workflow/graph.py",
    "src/mod_agent/workflow/transitions.py",
    "src/mod_agent/workflow/checkpointing.py",
    "src/mod_agent/repair/planner.py",
    "src/mod_agent/proposal/reviewer.py",
)

FORBIDDEN_CONTROL_IMPORT_PREFIXES = (
    "src.mod_agent.observability",
    "src.mod_agent.projections",
    "langfuse",
    "tests.conformance.historical_actual_replay",
)

FORBIDDEN_SHADOW_SCHEMA_LITERALS = frozenset(
    {
        "execution_lineage_projection_v1",
        "failure_capsule_v1",
        "historical_actual_replay_manifest_v1",
        "historical_actual_replay_case_v1",
        "historical_actual_replay_summary_v1",
    }
)

FORBIDDEN_SHADOW_DECISION_LITERALS = frozenset(
    {
        "failure_chain",
        "producer_projection_admission_consumer",
        "claim_impact",
        "deterministic_replay_hints",
        "violated_invariant_or_boundary",
        "first_violated_invariant_or_boundary",
        "next_attempt_authorized",
        "resume_authorized",
        "apply_authorized",
        "fresh_actual_status",
        "fresh_actual_reason",
        "subsystem_conformance",
        "authority_effect",
        "queue_mutation",
    }
)


def _tree(relative_path: str) -> ast.Module:
    path = PROJECT_ROOT / relative_path
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            if base:
                imported.add(base)
            imported.update(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
            )
    return imported


def _string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_control_plane_does_not_depend_on_projection_or_telemetry() -> None:
    violations: list[str] = []
    for relative_path in CONTROL_MODULES:
        for imported in sorted(_imported_names(_tree(relative_path))):
            normalized = imported.lstrip(".")
            if any(
                normalized == prefix or normalized.startswith(prefix + ".")
                for prefix in FORBIDDEN_CONTROL_IMPORT_PREFIXES
            ):
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_production_code_does_not_import_test_replay_implementations() -> None:
    violations: list[str] = []
    for path in sorted((PROJECT_ROOT / "src").rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for imported in sorted(_imported_names(_tree(relative_path))):
            normalized = imported.lstrip(".")
            if normalized == "tests" or normalized.startswith("tests."):
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_control_plane_does_not_consume_rejected_shadow_schemas_or_decisions() -> None:
    forbidden = FORBIDDEN_SHADOW_SCHEMA_LITERALS | FORBIDDEN_SHADOW_DECISION_LITERALS
    violations: list[str] = []
    for relative_path in CONTROL_MODULES:
        selected = sorted(_string_literals(_tree(relative_path)) & forbidden)
        violations.extend(
            f"{relative_path}: {literal}"
            for literal in selected
        )

    assert violations == []


def test_boundary_does_not_forbid_current_owner_failure_fields() -> None:
    forbidden = FORBIDDEN_SHADOW_SCHEMA_LITERALS | FORBIDDEN_SHADOW_DECISION_LITERALS
    assert "first_failure_stage" not in forbidden
    assert "failure_stage" not in forbidden
    assert "platform_status" not in forbidden
    assert "execution_disposition" not in forbidden
