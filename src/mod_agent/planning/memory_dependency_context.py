"""Read current run-bound dependency identities for optional experience applicability."""
from pathlib import Path
from time import perf_counter

from src.mod_agent.build.dependencies import _binary_tree_snapshot, _binary_tree_snapshot_sha256


def dependency_memory_context(*, workspace_root, binding):
    started = perf_counter()
    if binding is None:
        return {}, {"status": "not_configured", "model_calls": 0}
    try:
        root = (Path(workspace_root).resolve() / "build_dependencies" / "GameFolder").resolve(strict=True)
        if (binding.get("binding_version") != "run_local_game_folder_binding_v1"
                or binding.get("build_uses_isolated_copy") is not True
                or Path(binding["isolated_copy"]).resolve(strict=True) != root):
            raise ValueError("MEMORY_DEPENDENCY_SCOPE_INVALID")
        rows = _binary_tree_snapshot(root)
        digest = _binary_tree_snapshot_sha256(rows)
        if (digest != binding["copy_snapshot_sha256"] or digest != binding["source_snapshot_sha256"]
                or len(rows) != binding["copy_file_count"] or len(rows) != binding["source_file_count"]):
            raise ValueError("MEMORY_DEPENDENCY_COPY_CHANGED")
        files = [{"path": str(root / row["path"]), "relative_path": row["path"], "sha256": row["sha256"]}
                 for row in rows if row["path"].lower().endswith(".dll")]
        return {"dependency_dll_sha256:" + row["relative_path"]: row["sha256"] for row in files}, {
            "status": "verified", "files": files, "snapshot_sha256": digest,
            "elapsed_ms": (perf_counter() - started) * 1000, "model_calls": 0}
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        # 为什么要有它：无法核对当前依赖时应排除经验，不把历史内容当成当前API或额外执行权限。
        return {}, {"status": "unavailable", "error_type": type(error).__name__,
                    "elapsed_ms": (perf_counter() - started) * 1000, "model_calls": 0}
