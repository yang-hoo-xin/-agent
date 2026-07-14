"""Bounded local entry point for evidence-only GTFO request runs."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .artifacts import ArtifactRef, ArtifactStore
from .evidence import (
    BoundILInspectionRunner,
    GTFOR8EvidenceProvider,
    R8ILInspectionRunner,
)
from .workflow import build_graph, create_initial_state

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_R8_IL_INSPECTOR = (
    _PROJECT_ROOT
    / "scripts"
    / "r8_il_inspector"
    / "bin"
    / "Debug"
    / "net7.0"
    / "r8_il_inspector.dll"
)

CURRENT_INTEROP_SYMBOLS = (
    "ES_PathMove.CommonFixedUpdate",
    "ES_PathMove.UpdateRotation",
    "ES_PathMoveBase.UpdateRotation",
    "Enemies.EnemyLocomotion.ForceNode",
    "Enemies.EnemyAgent.set_Position",
    "ES_PathMove.set_m_moveDir",
    "ES_PathMove.set_m_targetPosition",
    "Agents.Agent.set_TargetLookDir",
    "Enemies.EnemyCourseNavigation.set_FlyerGraphTraversalData",
)
ENEMY_ANIMATION_FIX_SYMBOLS = (
    "EnemyAnimationFix.Patches.EnemyMovementPatches.StartUpdatePosition",
    "EnemyAnimationFix.Patches.EnemyMovementPatches.UpdatePosition",
    "EnemyAnimationFix.Patches.EnemyMovementPatches.Post_FlyerTraversal",
    "EnemyAnimationFix.Patches.EnemyTargetPatches.PathfindingFix",
)
STUCK_ENEMY_FIX_SYMBOLS = (
    "StuckEnemyFix.Plugin+StuckWatcher.FixedUpdate",
    "StuckEnemyFix.Plugin+StuckEnemyFixPatches.Postfix",
)


class EvidenceOnlyError(ValueError):
    """Raised before or during a bounded evidence-only run."""


def run_gtfo_r8_evidence_only(
    *,
    description: str,
    evidence_root: str | Path,
    artifact_root: str | Path = "artifacts/evidence_only",
    target_mod: str = "WallCrawler",
    assembly_path: str | Path | None = None,
    current_interop_path: str | Path | None = None,
    enemy_animation_fix_path: str | Path | None = None,
    stuck_enemy_fix_path: str | Path | None = None,
    il_inspector_path: str | Path = _DEFAULT_R8_IL_INSPECTOR,
) -> dict[str, object]:
    """Run one real supplied-file read and stop before implementation planning."""

    request = description.strip()
    if not request:
        raise EvidenceOnlyError("evidence-request requires a non-empty request.")
    resolved_artifact_root = _resolve_artifact_root(artifact_root)
    provider = GTFOR8EvidenceProvider(evidence_root)
    il_report = (
        R8ILInspectionRunner(il_inspector_path).inspect(assembly_path)
        if assembly_path is not None
        else None
    )
    current_interop_report = (
        BoundILInspectionRunner(
            il_inspector_path,
            symbols=CURRENT_INTEROP_SYMBOLS,
        ).inspect(current_interop_path)
        if current_interop_path is not None
        else None
    )
    reference_mod_reports: dict[str, dict[str, object]] = {}
    if enemy_animation_fix_path is not None:
        reference_mod_reports[
            "plugins/Dinorush-EnemyAnimationFix/EnemyAnimationFix.dll"
        ] = BoundILInspectionRunner(
            il_inspector_path,
            symbols=ENEMY_ANIMATION_FIX_SYMBOLS,
        ).inspect(enemy_animation_fix_path)
    if stuck_enemy_fix_path is not None:
        reference_mod_reports[
            "plugins/hirnukuono-StuckEnemyFix/StuckEnemyFix.dll"
        ] = BoundILInspectionRunner(
            il_inspector_path,
            symbols=STUCK_ENEMY_FIX_SYMBOLS,
        ).inspect(stuck_enemy_fix_path)
    store = ArtifactStore(resolved_artifact_root)
    run_id = f"evidence_{uuid4().hex}"
    graph = build_graph(
        store,
        evidence_pack_factory=lambda state, feature: provider.collect(
            query=str(feature.get("target_behavior") or state["user_request"]),
            il_report=il_report,
            current_interop_report=current_interop_report,
            reference_mod_reports=reference_mod_reports,
        ),
        use_default_proposal_git_binding=False,
        stop_after_evidence=True,
    )
    state = create_initial_state(
        run_id=run_id,
        request_id=f"request_{uuid4().hex}",
        user_request=request,
        target_domain="gtfo",
        target_mod=target_mod,
    )
    result = graph.invoke(state)
    if "evidence_pack" not in result["artifacts"]:
        raise EvidenceOnlyError("Workflow stopped before producing evidence_pack.")
    forbidden_artifacts = sorted(
        artifact_type
        for artifact_type in (
            "implementation_plan",
            "patch_proposal",
            "proposal_review",
            "dry_run_result",
            "isolated_apply_result",
            "build_result",
            "runtime_evidence",
        )
        if artifact_type in result["artifacts"]
    )
    if forbidden_artifacts:
        raise EvidenceOnlyError(
            "Evidence-only run crossed its stop boundary: " + ", ".join(forbidden_artifacts)
        )
    evidence_ref = ArtifactRef(
        feature_id=result["feature_id"] or result["request_id"],
        artifact_type="evidence_pack",
        path=result["artifacts"]["evidence_pack"],
        artifact_hash=result["artifact_hashes"]["evidence_pack"],
    )
    evidence_pack = store.read(evidence_ref)["data"]
    return {
        "status": "needs_more_evidence",
        "command": "evidence-request",
        "execution_mode": "evidence_only",
        "run_id": run_id,
        "feature_id": result["feature_id"],
        "current_stage": result["current_stage"],
        "stopped_before": "implementation_plan",
        "control_artifact_writes_performed": True,
        "target_source_writes_performed": False,
        "evidence_root": str(Path(evidence_root).resolve()),
        "assembly_path": (
            str(Path(assembly_path).resolve()) if assembly_path is not None else None
        ),
        "il_inspection_performed": il_report is not None,
        "current_interop_inspection_performed": current_interop_report is not None,
        "reference_mod_inspections_performed": sorted(reference_mod_reports),
        "artifact_root": str(resolved_artifact_root),
        "artifacts": dict(result["artifacts"]),
        "artifact_hashes": dict(result["artifact_hashes"]),
        "forbidden_artifacts_present": forbidden_artifacts,
        "blockers": list(result["blockers"]),
        "evidence_pack": evidence_pack,
    }


def _resolve_artifact_root(artifact_root: str | Path) -> Path:
    root = Path(artifact_root)
    resolved = root.resolve() if root.is_absolute() else (_PROJECT_ROOT / root).resolve()
    try:
        resolved.relative_to(_PROJECT_ROOT)
    except ValueError as exc:
        raise EvidenceOnlyError(
            "evidence-request artifact_root must stay inside the project root."
        ) from exc
    return resolved
