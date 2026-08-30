from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
MOD_AGENT_ROOT = PROJECT_ROOT / "src" / "mod_agent"

FORBIDDEN_DEPENDENCY_PREFIXES = (
    "src.mod_agent.observability",
    "src.mod_agent.projections",
    "langfuse",
    "tests.conformance.historical_actual_replay",
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


def _imported_names(path: Path) -> set[str]:
    current_module = _module_name(path)
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
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


def test_current_mod_agent_tree_has_no_rejected_projection_dependency() -> None:
    violations: list[str] = []
    for path in sorted(MOD_AGENT_ROOT.rglob("*.py")):
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for imported in sorted(_imported_names(path)):
            if any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in FORBIDDEN_DEPENDENCY_PREFIXES
            ):
                violations.append(f"{relative_path}: {imported}")

    assert violations == []


def test_rejected_whole_commit_modules_are_absent_from_current_tree() -> None:
    present = [
        relative_path
        for relative_path in REJECTED_TREE_PATHS
        if (PROJECT_ROOT / relative_path).exists()
    ]

    assert present == []
