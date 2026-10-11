"""Recognize source-bound compiler failures that a code task can repair."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from .adapter import BuildErrorClassifier

_ERROR = re.compile(r"(?:^\s*(?:\d+>)?|:)\s*error(?:\s+([A-Za-z]+\d+))?\s*:", re.IGNORECASE)


def classify_source_compilation_failure(
    *, execution: Mapping[str, Any], output: str, project_root: Path,
    expected_sources: Mapping[str, str],
) -> tuple[dict[str, Any], ...]:
    """Return observed diagnostics only when every error binds to current source.

    为什么要有它：原工程的源码错误是修复输入；恢复依赖失败、工具故障或未知来源错误不能被冒充成可定位源码错误。
    """
    if execution.get("restore_exit_code") != 0 or execution.get("build_exit_code") in (None, 0):
        return ()
    root = project_root.resolve()
    classifier = BuildErrorClassifier()
    result: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = _ERROR.search(line)
        if match is None:
            continue
        code = (match.group(1) or "").upper()
        if not re.fullmatch(r"CS\d{4}", code):
            return ()
        _, parsed = classifier.classify(line)
        errors = [item for item in parsed if item.severity == "error"]
        if not errors:
            return ()
        for item in errors:
            if item.code != code or not item.file:
                return ()
            path = Path(item.file)
            path = (root / path).resolve() if not path.is_absolute() else path.resolve()
            if not path.is_relative_to(root):
                return ()
            relative = path.relative_to(root)
            if path.suffix.lower() != ".cs" or any(part.lower() in {"bin", "obj"} for part in relative.parts):
                return ()
            expected = expected_sources.get(relative.as_posix())
            if not expected or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return ()
            message = re.sub(r"\s*\[[^\r\n]+\.csproj\]\s*$", "", item.message)
            message = message.replace(str(root), ".").replace(root.as_posix(), ".")
            # 为什么要有它：模型需要错误内容，不需要编译器附带的宿主机目录。
            message = re.sub(r"(?:[A-Za-z]:[\\/]|/)(?:[^\s'\"<>:]+[\\/])+[^\s'\"<>:]*", "<local-path>", message)
            row = {**item.to_dict(), "file": relative.as_posix(),
                   "message": message, "source_sha256": expected}
            if row not in result:
                result.append(row)
    return tuple(result)


def baseline_failure_model_view(diagnostics, *, source_prefix: str, source_snapshot_sha256: str) -> dict[str, Any]:
    """A bounded observation of B0, never a new requirement or edit binding."""
    return {
        "observation_kind": "baseline_compilation_failure",
        "source_snapshot_sha256": source_snapshot_sha256,
        "diagnostic_count": len(diagnostics),
        "diagnostics": [{**{key: value for key, value in row.items() if key != "error_class"},
                         "file": f"{source_prefix}/{row['file']}",
                         "message": row["message"][:1000]} for row in diagnostics[:20]],
        "omitted_diagnostic_count": max(0, len(diagnostics) - 20),
        "interpretation": (
            "These are actual compiler observations of the initial source B0. "
            "The task can be to repair these defects: a compiler error in available source is an observed defect, "
            "not itself missing source/API evidence. The compiler's suggested causes are alternatives, not verified diagnoses. "
            "Assess whether the observed code and its uses suffice to plan a repair; the old source need not already compile. "
            "If material really is missing, name the unavailable implementation or API fact needed to decide the change, "
            "rather than restating the compiler error. Read current source before selecting edits. "
            "In Findings, unresolved_gaps lists only unavailable evidence needed BEFORE making a patch. "
            "Known defects, proposed fixes, requested new defaults and tests that must pass AFTER the patch are not unresolved_gaps. "
            "When these are the only remaining work, use unresolved_gaps=[]; select support and exact edit hints only if "
            "the supplied source actually establishes the relevant implementation and locations. "
            "They grant no edit permission, do not add user requirements, and do not describe later candidates. "
            "Later candidate verification determines whether a repair works."
        ),
    }


def validated_baseline_repair_observation(manifest: Mapping[str, Any], root: Path) -> dict[str, Any] | None:
    """Revalidate a failed baseline before continuing from its unchanged source B0.

    为什么要有它：保存续接与交付准入可复用原源码错误，但状态标签或陈旧 DLL 不能替代原始诊断与源码绑定。
    """
    from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256

    root = Path(root).resolve(strict=True)
    baseline = manifest["baseline_build"]
    observation = baseline.get("repair_observation")
    if observation is None:
        return None
    source = Path(manifest["target_source"]).resolve(strict=True)
    target = root / "generated_mods" / source.name
    snapshot = manifest["source_snapshot"]
    if (source_snapshot_sha256(snapshot) != manifest["source_snapshot_sha256"]
            or source_snapshot(source) != snapshot or source_snapshot(target) != snapshot):
        raise ValueError("INITIAL_FINDINGS_SOURCE_CHANGED")
    output = []
    for stream in ("stdout", "stderr"):
        path = Path(baseline[f"{stream}_path"]).resolve(strict=True)
        if path != root / f"baseline_build.{stream}.log":
            raise ValueError("INITIAL_FINDINGS_BASELINE_CHANGED")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != baseline.get(f"{stream}_sha256"):
            raise ValueError("INITIAL_FINDINGS_BASELINE_CHANGED")
        output.append(raw.decode("utf-8"))
    diagnostics = classify_source_compilation_failure(execution=baseline,
        output="\n".join(output), project_root=root / "baseline_source" / source.name,
        expected_sources={row["path"]: row["sha256"] for row in snapshot})
    if not diagnostics or list(diagnostics) != baseline.get("source_compilation_diagnostics"):
        raise ValueError("INITIAL_FINDINGS_BASELINE_CHANGED")
    expected = baseline_failure_model_view(diagnostics,
        source_prefix=target.relative_to(root).as_posix(),
        source_snapshot_sha256=manifest["source_snapshot_sha256"])
    # 为什么要有它：诊断事实须可重建；历史提示说明保持原字节，不能因本次改进措辞让旧任务无法续跑或偷换原模型输入。
    if not isinstance(observation.get("interpretation"), str) or not observation["interpretation"].strip():
        raise ValueError("INITIAL_FINDINGS_BASELINE_CHANGED")
    facts = deepcopy(observation)
    facts.pop("interpretation")
    expected.pop("interpretation")
    for index, row in enumerate(facts.get("diagnostics", [])):
        if "error_class" in row:
            if index >= len(diagnostics) or row.pop("error_class") != diagnostics[index]["error_class"]:
                raise ValueError("INITIAL_FINDINGS_BASELINE_CHANGED")
    if facts != expected:
        raise ValueError("INITIAL_FINDINGS_BASELINE_CHANGED")
    return deepcopy(observation)
