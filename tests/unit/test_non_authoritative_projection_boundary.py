from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
MOD_AGENT_ROOT = PROJECT_ROOT / "src" / "mod_agent"
PROJECTION_ROOT = PROJECT_ROOT / "src" / "non_authoritative_projection"

FORBIDDEN_CONTROL_DEPENDENCY_PREFIXES = (
    "src.non_authoritative_projection",
    "src.mod_agent.observability",
    "src.mod_agent.projections",
    "langfuse",
    "tests.conformance.historical_actual_replay",
)

ALLOWED_PROJECTION_DEPENDENCY_PREFIXES = (
    "__future__",
    "collections",
    "dataclasses",
    "hashlib",
    "json",
    "src.non_authoritative_projection",
    "typing",
)

REJECTED_TREE_PATHS = (
    "src/mod_agent/observability.py",
    "src/mod_agent/observability/execution_lineage.py",
    "tests/conformance/historical_actual_replay.py",
)


def _module_name(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).with_suffix("").as_posix().replace("/", ".")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _resolve_import_from(current_module: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = current_module.split(".")[:-1]
    parent_hops = node.level - 1
    if parent_hops > len(package):
        return ""
    anchor = package[: len(package) - parent_hops]
    if node.module:
        anchor.extend(node.module.split("."))
    return ".".join(anchor)


def _imported_names_from_tree(
    current_module: str,
    tree: ast.Module,
) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(current_module, node)
            if base:
                imported.add(base)
            imported.update(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
            )
    return imported


def _imported_names(path: Path) -> set[str]:
    return _imported_names_from_tree(_module_name(path), _tree(path))


def _imported_names_from_source(current_module: str, source: str) -> set[str]:
    return _imported_names_from_tree(current_module, ast.parse(source))


def _matches_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def test_complete_current_and_future_mod_agent_tree_has_no_reverse_projection_dependency() -> None:
    violations: list[str] = []
    for path in sorted(MOD_AGENT_ROOT.rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for imported in sorted(_imported_names(path)):
            if _matches_prefix(imported, FORBIDDEN_CONTROL_DEPENDENCY_PREFIXES):
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_reverse_dependency_guard_resolves_absolute_and_relative_imports_exactly() -> None:
    absolute = _imported_names_from_source(
        "src.mod_agent.future_control",
        "from src.non_authoritative_projection import ProjectionViewV1",
    )
    relative = _imported_names_from_source(
        "src.mod_agent.workflow.future_control",
        "from ...non_authoritative_projection import ProjectionViewV1",
    )
    existing_observability = _imported_names_from_source(
        "src.mod_agent.workflow.future_control",
        "from ...observability import logger",
    )

    assert any(
        _matches_prefix(name, FORBIDDEN_CONTROL_DEPENDENCY_PREFIXES)
        for name in absolute
    )
    assert any(
        _matches_prefix(name, FORBIDDEN_CONTROL_DEPENDENCY_PREFIXES)
        for name in relative
    )
    assert "src.observability" in existing_observability
    assert not any(
        _matches_prefix(name, FORBIDDEN_CONTROL_DEPENDENCY_PREFIXES)
        for name in existing_observability
    )


def test_projection_contract_package_has_only_stdlib_and_self_dependencies() -> None:
    violations: list[str] = []
    for path in sorted(PROJECTION_ROOT.rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for imported in sorted(_imported_names(path)):
            if not _matches_prefix(imported, ALLOWED_PROJECTION_DEPENDENCY_PREFIXES):
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_rejected_whole_commit_modules_are_absent_from_current_tree() -> None:
    present = [
        relative_path
        for relative_path in REJECTED_TREE_PATHS
        if (PROJECT_ROOT / relative_path).exists()
    ]

    assert present == []
