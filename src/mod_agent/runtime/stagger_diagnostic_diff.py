"""Deterministic no-write exact diff for the Stagger HUD diagnostic Plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..artifacts import ArtifactRef, ArtifactStore
from ..execution.patch_apply import ExactTextPatchApplier, PatchApplyError


_AUTHORITY_CONTRACT = "edit_authority_stagger_hud_parent_diagnostic_plan_v2"
_DIAGNOSTIC_SCOPE_SCHEMA = (
    "stagger_hud_parent_diagnostic_execution_authority_v2"
)
_DIAGNOSTIC_TEST_SCHEMA = "stagger_hud_parent_diagnostic_test_plan_v1"
_SOURCE_PATH = "Patches/HitFeedbackBehaviorPatch.cs"
_PLUGIN_PATH = "Plugin.cs"
_SELECTED_BINDING_IDS = (
    "edit_binding_007",
    "edit_binding_008",
    "edit_binding_009",
    "edit_binding_010",
)
_SELECTED_CHANGE_IDS = (
    "chg_007",
    "chg_008",
    "chg_009",
    "chg_010",
)
_EXPECTED_OPERATIONS = {
    "edit_binding_007": (
        "insert_observation_only_hud_parent_selection_state_after_"
        "existing_assignment"
    ),
    "edit_binding_008": (
        "insert_observation_only_hud_parent_use_state_before_existing_"
        "cast_and_guard"
    ),
    "edit_binding_009": (
        "insert_bounded_observation_state_after_existing_hud_parent_field"
    ),
    "edit_binding_010": (
        "insert_observation_identity_helpers_before_existing_hud_parent_"
        "resolver"
    ),
}
_ALLOWED_ACTIONS = (
    "create_observation_evidence_pack_revision",
    "create_diagnostic_only_implementation_plan_revision",
    "create_exact_bounded_observation_bindings",
)
_FORBIDDEN_ACTIONS = (
    "create_binding_resolution_revision",
    "invoke_repair_planner",
    "modify_source",
    "build",
    "launch_process",
    "write_game_directory",
)
_STATE_LINE = "        private static Transform? _lastHudParent;"
_STATE_AFTER = """        private static Transform? _lastHudParent;
        private static long _staggerDiagnosticEventSequence;
        private static int _staggerDiagnosticSelectionRecordCount;
        private static int _staggerDiagnosticUseRecordCount;
        private static string _staggerDiagnosticLastSelectionDedupKey = string.Empty;
        private static string _staggerDiagnosticLastUseDedupKey = string.Empty;
        private static long _staggerDiagnosticLastAssignmentEventSequence;
        private static long _staggerDiagnosticLastAssignmentUtcTicks;
        private static int _staggerDiagnosticLastAssignmentHitSequence;
        private static string _staggerDiagnosticLastCrosshairNativePointer = "unavailable";
        private static int _staggerDiagnosticLastCrosshairManagedWrapperIdentity;
        private static int? _staggerDiagnosticLastHudParentUnityInstanceId;
        private static string _staggerDiagnosticLastAssignmentSource = "none";
        private static bool _staggerDiagnosticLastCrosshairInstanceChanged;"""
_SELECTION_LINE = (
    "                _lastHudParent = TryGetLayerHudParent(__instance);"
)
_SELECTION_AFTER = """                _lastHudParent = TryGetLayerHudParent(__instance);
                RecordStaggerHudParentSelection(__instance, _lastHudParent, _hitSequence);"""
_USE_BLOCK = """                RectTransform? canvasRect = _lastHudParent as RectTransform;
                if (canvasRect == null)
                {
                    reason = "missing_canvas_rect_for_stagger_x";
                    return false;
                }"""
_USE_AFTER = """                RecordStaggerHudParentUse(_lastHudParent, _hitSequence);
                RectTransform? canvasRect = _lastHudParent as RectTransform;
                if (canvasRect == null)
                {
                    reason = "missing_canvas_rect_for_stagger_x";
                    return false;
                }"""
_HELPER_LINE = (
    "        private static Transform? "
    "TryGetLayerHudParent(CrosshairGuiLayer? layer)"
)
_HELPER_AFTER = r"""        private static void RecordStaggerHudParentSelection(
            CrosshairGuiLayer? layer,
            Transform? selected,
            int hitSequenceSnapshot)
        {
            if (!IsStaggerHudParentDiagnosticEnabled())
            {
                return;
            }

            try
            {
                long eventSequence = System.Threading.Interlocked.Increment(
                    ref _staggerDiagnosticEventSequence);
                long utcTicks = DateTime.UtcNow.Ticks;
                Transform? canvasTrans = null;
                Transform? root = null;
                string observationError = "none";
                try
                {
                    if (!ReferenceEquals(layer, null))
                    {
                        canvasTrans = layer.CanvasTrans;
                        root = layer.Root;
                    }
                }
                catch (Exception ex)
                {
                    observationError = SafeName(ex.GetType().Name);
                }

                string crosshairNativePointer = GetStaggerCrosshairNativePointer(
                    layer,
                    out string crosshairIdentityError);
                int crosshairManagedIdentity = ReferenceEquals(layer, null)
                    ? 0
                    : System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(layer);
                int? selectedInstanceId = GetStaggerUnityInstanceId(
                    selected,
                    out string selectedIdentityError);
                int? canvasInstanceId = GetStaggerUnityInstanceId(
                    canvasTrans,
                    out string canvasIdentityError);
                int? rootInstanceId = GetStaggerUnityInstanceId(
                    root,
                    out string rootIdentityError);
                string selectedSource = ResolveStaggerHudParentSource(
                    selectedInstanceId,
                    canvasInstanceId,
                    rootInstanceId,
                    observationError);
                bool assignmentSeen =
                    _staggerDiagnosticLastAssignmentEventSequence > 0;
                bool crosshairInstanceChanged = assignmentSeen
                    && (
                        _staggerDiagnosticLastCrosshairNativePointer
                            != crosshairNativePointer
                        || _staggerDiagnosticLastCrosshairManagedWrapperIdentity
                            != crosshairManagedIdentity
                    );

                _staggerDiagnosticLastAssignmentEventSequence = eventSequence;
                _staggerDiagnosticLastAssignmentUtcTicks = utcTicks;
                _staggerDiagnosticLastAssignmentHitSequence =
                    hitSequenceSnapshot;
                _staggerDiagnosticLastCrosshairNativePointer =
                    crosshairNativePointer;
                _staggerDiagnosticLastCrosshairManagedWrapperIdentity =
                    crosshairManagedIdentity;
                _staggerDiagnosticLastHudParentUnityInstanceId =
                    selectedInstanceId;
                _staggerDiagnosticLastAssignmentSource = selectedSource;
                _staggerDiagnosticLastCrosshairInstanceChanged =
                    crosshairInstanceChanged;

                string dedupKey =
                    $"selection|{crosshairNativePointer}|"
                    + $"{FormatStaggerDiagnosticId(selectedInstanceId)}|"
                    + $"{FormatStaggerDiagnosticId(selectedInstanceId)}|"
                    + $"{hitSequenceSnapshot}";
                if (
                    _staggerDiagnosticSelectionRecordCount >= 8
                    || _staggerDiagnosticLastSelectionDedupKey == dedupKey
                )
                {
                    return;
                }

                _staggerDiagnosticLastSelectionDedupKey = dedupKey;
                _staggerDiagnosticSelectionRecordCount++;
                Log.LogInfo(
                    $"[GTFO_MOD_AGENT] feature_id={Plugin.FEATURE_ID} "
                    + "signal=STAGGER_HUD_PARENT_DIAGNOSTIC "
                    + $"phase=selection event_sequence={eventSequence} "
                    + $"utc_ticks={utcTicks} "
                    + $"hit_sequence_snapshot={hitSequenceSnapshot} "
                    + $"assignment_source={selectedSource} "
                    + "crosshair_instance_changed="
                    + $"{FormatStaggerDiagnosticBool(crosshairInstanceChanged)} "
                    + $"selection_observation_error={observationError} "
                    + "CrosshairGuiLayer.reference_null="
                    + $"{FormatStaggerDiagnosticBool(ReferenceEquals(layer, null))} "
                    + "CrosshairGuiLayer.unity_null=not_applicable "
                    + "CrosshairGuiLayer.native_pointer="
                    + $"{crosshairNativePointer} "
                    + "CrosshairGuiLayer.managed_wrapper_identity="
                    + $"{crosshairManagedIdentity} "
                    + "CrosshairGuiLayer.unity_instance_id=not_applicable "
                    + "CrosshairGuiLayer.runtime_type="
                    + $"{GetStaggerRuntimeType(layer)} "
                    + "CrosshairGuiLayer.rect_transform_compatible=not_applicable "
                    + "CrosshairGuiLayer.identity_read_error="
                    + $"{crosshairIdentityError} "
                    + DescribeStaggerUnityObject(
                        "CanvasTrans",
                        canvasTrans,
                        canvasInstanceId,
                        canvasIdentityError)
                    + " "
                    + DescribeStaggerUnityObject(
                        "Root",
                        root,
                        rootInstanceId,
                        rootIdentityError)
                    + " "
                    + DescribeStaggerUnityObject(
                        "selected",
                        selected,
                        selectedInstanceId,
                        selectedIdentityError));
            }
            catch (Exception ex)
            {
                TryLogStaggerHudParentDiagnosticError(
                    "selection",
                    ex);
            }
        }

        private static void RecordStaggerHudParentUse(
            Transform? currentHudParent,
            int hitSequenceSnapshot)
        {
            if (!IsStaggerHudParentDiagnosticEnabled())
            {
                return;
            }

            try
            {
                long eventSequence = System.Threading.Interlocked.Increment(
                    ref _staggerDiagnosticEventSequence);
                long utcTicks = DateTime.UtcNow.Ticks;
                int? currentInstanceId = GetStaggerUnityInstanceId(
                    currentHudParent,
                    out string currentIdentityError);
                bool assignmentSeen =
                    _staggerDiagnosticLastAssignmentEventSequence > 0;
                bool hudParentIdentityChanged = assignmentSeen
                    && _staggerDiagnosticLastHudParentUnityInstanceId
                        != currentInstanceId;
                string dedupKey =
                    $"stagger_use|"
                    + $"{_staggerDiagnosticLastCrosshairNativePointer}|"
                    + $"{FormatStaggerDiagnosticId(_staggerDiagnosticLastHudParentUnityInstanceId)}|"
                    + $"{FormatStaggerDiagnosticId(currentInstanceId)}|"
                    + $"{hitSequenceSnapshot}";
                if (
                    _staggerDiagnosticUseRecordCount >= 8
                    || _staggerDiagnosticLastUseDedupKey == dedupKey
                )
                {
                    return;
                }

                _staggerDiagnosticLastUseDedupKey = dedupKey;
                _staggerDiagnosticUseRecordCount++;
                Log.LogInfo(
                    $"[GTFO_MOD_AGENT] feature_id={Plugin.FEATURE_ID} "
                    + "signal=STAGGER_HUD_PARENT_DIAGNOSTIC "
                    + $"phase=stagger_use event_sequence={eventSequence} "
                    + $"utc_ticks={utcTicks} "
                    + $"hit_sequence_snapshot={hitSequenceSnapshot} "
                    + "last_assignment_event_sequence="
                    + $"{_staggerDiagnosticLastAssignmentEventSequence} "
                    + "last_assignment_utc_ticks="
                    + $"{_staggerDiagnosticLastAssignmentUtcTicks} "
                    + "last_assignment_hit_sequence="
                    + $"{_staggerDiagnosticLastAssignmentHitSequence} "
                    + "assignment_seen="
                    + $"{FormatStaggerDiagnosticBool(assignmentSeen)} "
                    + "crosshair_instance_changed="
                    + $"{FormatStaggerDiagnosticBool(_staggerDiagnosticLastCrosshairInstanceChanged)} "
                    + "hud_parent_identity_changed="
                    + $"{FormatStaggerDiagnosticBool(hudParentIdentityChanged)} "
                    + "stored_CrosshairGuiLayer.reference_null="
                    + $"{FormatStaggerDiagnosticBool(!assignmentSeen)} "
                    + "stored_CrosshairGuiLayer.unity_null=not_applicable "
                    + "stored_CrosshairGuiLayer.native_pointer="
                    + $"{_staggerDiagnosticLastCrosshairNativePointer} "
                    + "stored_CrosshairGuiLayer.managed_wrapper_identity="
                    + $"{_staggerDiagnosticLastCrosshairManagedWrapperIdentity} "
                    + "stored_CrosshairGuiLayer.unity_instance_id=not_applicable "
                    + "stored_CrosshairGuiLayer.runtime_type="
                    + "CrosshairGuiLayer "
                    + "stored_CrosshairGuiLayer.rect_transform_compatible="
                    + "not_applicable "
                    + "stored_CrosshairGuiLayer.identity_read_error="
                    + $"{(assignmentSeen ? "none" : "assignment_not_seen")} "
                    + DescribeStaggerUnityObject(
                        "_lastHudParent",
                        currentHudParent,
                        currentInstanceId,
                        currentIdentityError)
                    + " "
                    + "last_assigned_HUD_parent.reference_null="
                    + $"{FormatStaggerDiagnosticBool(!assignmentSeen)} "
                    + "last_assigned_HUD_parent.unity_null="
                    + "see_selection_event "
                    + "last_assigned_HUD_parent.native_pointer=not_authorized "
                    + "last_assigned_HUD_parent.managed_wrapper_identity="
                    + "see_selection_event "
                    + "last_assigned_HUD_parent.unity_instance_id="
                    + $"{FormatStaggerDiagnosticId(_staggerDiagnosticLastHudParentUnityInstanceId)} "
                    + "last_assigned_HUD_parent.runtime_type="
                    + "see_selection_event "
                    + "last_assigned_HUD_parent.rect_transform_compatible="
                    + "see_selection_event "
                    + "last_assigned_HUD_parent.identity_read_error="
                    + $"{(assignmentSeen ? "none" : "assignment_not_seen")} "
                    + "last_assignment_source="
                    + $"{_staggerDiagnosticLastAssignmentSource}");
            }
            catch (Exception ex)
            {
                TryLogStaggerHudParentDiagnosticError(
                    "stagger_use",
                    ex);
            }
        }

        private static bool IsStaggerHudParentDiagnosticEnabled()
        {
            try
            {
                return Plugin.EnableDiagnosticLogging != null
                    && Plugin.EnableDiagnosticLogging.Value;
            }
            catch
            {
                return false;
            }
        }

        private static string GetStaggerCrosshairNativePointer(
            CrosshairGuiLayer? layer,
            out string identityReadError)
        {
            identityReadError = "none";
            if (ReferenceEquals(layer, null))
            {
                return "reference_null";
            }

            try
            {
                return layer.Pointer.ToString();
            }
            catch (Exception ex)
            {
                identityReadError = SafeName(ex.GetType().Name);
                return "unavailable";
            }
        }

        private static int? GetStaggerUnityInstanceId(
            Transform? value,
            out string identityReadError)
        {
            identityReadError = "none";
            if (ReferenceEquals(value, null))
            {
                return null;
            }

            try
            {
                return value.GetInstanceID();
            }
            catch (Exception ex)
            {
                identityReadError = SafeName(ex.GetType().Name);
                return null;
            }
        }

        private static string ResolveStaggerHudParentSource(
            int? selectedInstanceId,
            int? canvasInstanceId,
            int? rootInstanceId,
            string observationError)
        {
            if (observationError != "none")
            {
                return "observation_exception";
            }

            if (!selectedInstanceId.HasValue)
            {
                return "none";
            }

            if (
                canvasInstanceId.HasValue
                && selectedInstanceId.Value == canvasInstanceId.Value
            )
            {
                return "CanvasTrans";
            }

            if (
                rootInstanceId.HasValue
                && selectedInstanceId.Value == rootInstanceId.Value
            )
            {
                return "Root";
            }

            return "observation_exception";
        }

        private static string DescribeStaggerUnityObject(
            string prefix,
            Transform? value,
            int? instanceId,
            string identityReadError)
        {
            bool referenceNull = ReferenceEquals(value, null);
            bool unityNull = referenceNull;
            string runtimeType = "unavailable";
            int managedWrapperIdentity = 0;
            try
            {
                if (!referenceNull)
                {
                    unityNull = value == null;
                    runtimeType = value.GetType().FullName ?? "unknown";
                    managedWrapperIdentity =
                        System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(
                            value);
                }
            }
            catch (Exception ex)
            {
                identityReadError = SafeName(ex.GetType().Name);
            }

            return $"{prefix}.reference_null="
                + $"{FormatStaggerDiagnosticBool(referenceNull)} "
                + $"{prefix}.unity_null="
                + $"{FormatStaggerDiagnosticBool(unityNull)} "
                + $"{prefix}.native_pointer=not_authorized "
                + $"{prefix}.managed_wrapper_identity="
                + $"{managedWrapperIdentity} "
                + $"{prefix}.unity_instance_id="
                + $"{FormatStaggerDiagnosticId(instanceId)} "
                + $"{prefix}.runtime_type={SafeName(runtimeType)} "
                + $"{prefix}.rect_transform_compatible="
                + $"{FormatStaggerDiagnosticBool(value is RectTransform)} "
                + $"{prefix}.identity_read_error={identityReadError}";
        }

        private static string GetStaggerRuntimeType(
            CrosshairGuiLayer? layer)
        {
            if (ReferenceEquals(layer, null))
            {
                return "unavailable";
            }

            try
            {
                return SafeName(layer.GetType().FullName ?? "unknown");
            }
            catch
            {
                return "unavailable";
            }
        }

        private static string FormatStaggerDiagnosticId(int? value)
        {
            return value.HasValue ? value.Value.ToString() : "unavailable";
        }

        private static string FormatStaggerDiagnosticBool(bool value)
        {
            return value ? "true" : "false";
        }

        private static void TryLogStaggerHudParentDiagnosticError(
            string phase,
            Exception error)
        {
            try
            {
                Log.LogWarning(
                    $"[GTFO_MOD_AGENT] feature_id={Plugin.FEATURE_ID} "
                    + "signal=STAGGER_HUD_PARENT_DIAGNOSTIC "
                    + $"phase={phase} identity_read_error="
                    + $"{SafeName(error.GetType().Name)}");
            }
            catch
            {
            }
        }

        private static Transform? TryGetLayerHudParent(CrosshairGuiLayer? layer)"""


class StaggerDiagnosticDiffPreflightError(ValueError):
    """Raised when the approved diagnostic Plan cannot produce an exact diff."""


def preflight_stagger_hud_parent_diagnostic_exact_diff(
    *,
    artifact_store_root: str | Path,
    feature_id: str,
    run_id: str,
    edit_authority_approval_path: str | Path,
    edit_authority_approval_hash: str,
    evidence_pack_path: str | Path,
    evidence_pack_hash: str,
    implementation_plan_path: str | Path,
    implementation_plan_hash: str,
    source_root: str | Path,
) -> dict[str, Any]:
    """Generate the approved four-change diagnostic diff without writing."""

    if not feature_id or not run_id:
        raise StaggerDiagnosticDiffPreflightError(
            "feature_id and run_id must be non-empty."
        )
    store = ArtifactStore(artifact_store_root)
    refs = {
        "edit_authority_approval": _artifact_ref(
            feature_id,
            "edit_authority_approval",
            edit_authority_approval_path,
            edit_authority_approval_hash,
        ),
        "evidence_pack": _artifact_ref(
            feature_id,
            "evidence_pack",
            evidence_pack_path,
            evidence_pack_hash,
        ),
        "implementation_plan": _artifact_ref(
            feature_id,
            "implementation_plan",
            implementation_plan_path,
            implementation_plan_hash,
        ),
    }
    envelopes = {
        role: store.read(ref)
        for role, ref in refs.items()
    }
    _require_current_exact_revisions(store, refs.values())
    stale = {
        role: list(view.stale_reasons)
        for role, view in (
            (role, store.check_exact_revision_freshness(ref))
            for role, ref in refs.items()
        )
        if not view.is_fresh
    }
    if stale:
        raise StaggerDiagnosticDiffPreflightError(
            f"Diagnostic exact-diff inputs are stale: {stale}"
        )

    approval = _artifact_data(envelopes["edit_authority_approval"])
    evidence = _artifact_data(envelopes["evidence_pack"])
    plan = _artifact_data(envelopes["implementation_plan"])
    _validate_authority_and_plan(
        feature_id=feature_id,
        run_id=run_id,
        refs=refs,
        envelopes=envelopes,
        approval=approval,
        evidence=evidence,
        plan=plan,
    )
    root = Path(source_root).resolve()
    source_path = (root / _SOURCE_PATH).resolve()
    plugin_path = (root / _PLUGIN_PATH).resolve()
    try:
        source_path.relative_to(root)
        plugin_path.relative_to(root)
    except ValueError as exc:
        raise StaggerDiagnosticDiffPreflightError(
            "Diagnostic source path escapes source_root."
        ) from exc
    if not source_path.is_file() or not plugin_path.is_file():
        raise StaggerDiagnosticDiffPreflightError(
            "Diagnostic source or Plugin config source is missing."
        )
    source_before = source_path.read_bytes()
    plugin_before = plugin_path.read_bytes()
    source_hash = hashlib.sha256(source_before).hexdigest().upper()
    plugin_hash = hashlib.sha256(plugin_before).hexdigest().upper()
    _validate_live_sources_and_dependencies(
        source_root=root,
        source_hash=source_hash,
        plugin_hash=plugin_hash,
        evidence=evidence,
        plan=plan,
    )

    proposal = _build_diagnostic_proposal(
        feature_id=feature_id,
        run_id=run_id,
        approval_ref=refs["edit_authority_approval"],
        evidence_ref=refs["evidence_pack"],
        plan_ref=refs["implementation_plan"],
        source_hash=source_hash,
    )
    review = {
        "decision": "approve_dry_run",
        "allowed_next_stage": "dry_run_apply",
        "review_mode": "deterministic_stagger_diagnostic_v2",
        "source_write_authorized": False,
    }
    try:
        result = ExactTextPatchApplier().run(
            workspace_root=root,
            proposal=proposal,
            implementation_plan=plan,
            review=review,
            allow_write=False,
        )
    except PatchApplyError as exc:
        raise StaggerDiagnosticDiffPreflightError(str(exc)) from exc
    if source_path.read_bytes() != source_before:
        raise StaggerDiagnosticDiffPreflightError(
            "No-write exact-diff generation changed the target source."
        )
    if plugin_path.read_bytes() != plugin_before:
        raise StaggerDiagnosticDiffPreflightError(
            "No-write exact-diff generation changed Plugin.cs."
        )
    if result["changed_files"] != [_SOURCE_PATH]:
        raise StaggerDiagnosticDiffPreflightError(
            "Diagnostic exact diff changed an unexpected file set."
        )
    if result["diff_stats"]["change_units"] != 4:
        raise StaggerDiagnosticDiffPreflightError(
            "Diagnostic exact diff does not contain four change units."
        )

    return {
        "status": "READY_FOR_STAGGER_HUD_PARENT_DIAGNOSTIC_DIFF_APPROVAL",
        "command": "preflight-stagger-hud-parent-diagnostic-exact-diff",
        "feature_id": feature_id,
        "run_id": run_id,
        "proposal_id": proposal["proposal_id"],
        "edit_authority_approval_revision": _revision(
            refs["edit_authority_approval"]
        ),
        "evidence_pack_revision": _revision(refs["evidence_pack"]),
        "implementation_plan_revision": _revision(
            refs["implementation_plan"]
        ),
        "selected_binding_ids": list(_SELECTED_BINDING_IDS),
        "selected_change_ids": list(_SELECTED_CHANGE_IDS),
        "source_before_sha256": source_hash,
        "source_after_sha256": result["changes"][-1]["after_sha256"].upper(),
        "diff_hash": result["diff_hash"],
        "unified_diff_sha256": result["unified_diff_sha256"],
        "unified_diff_bytes": result["unified_diff_bytes"],
        "diff_stats": result["diff_stats"],
        "static_checks": result["static_checks"],
        "unified_diff": result["unified_diff"],
        "approval_required": True,
        "writes_performed": False,
        "artifact_writes_performed": False,
        "source_patch_allowed": False,
        "source_modified": False,
        "build_performed": False,
        "process_launched": False,
        "game_directory_written": False,
    }


def _validate_authority_and_plan(
    *,
    feature_id: str,
    run_id: str,
    refs: dict[str, ArtifactRef],
    envelopes: dict[str, dict[str, Any]],
    approval: dict[str, Any],
    evidence: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    if (
        approval.get("feature_id") != feature_id
        or approval.get("run_id") != run_id
        or approval.get("status") != "approved"
        or approval.get("decision") != "approve"
        or approval.get("authority_source") != "edit_authority_request"
        or approval.get("authority_contract_version") != _AUTHORITY_CONTRACT
        or approval.get("repair_planner_allowed") is not False
        or approval.get("source_patch_allowed") is not False
        or approval.get("allowed_actions") != list(_ALLOWED_ACTIONS)
        or approval.get("forbidden_actions") != list(_FORBIDDEN_ACTIONS)
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "EditAuthorityApproval does not match the diagnostic v2 boundary."
        )
    request_hash = approval.get("request_hash")
    if (
        not isinstance(request_hash, str)
        or not request_hash.startswith("sha256:")
        or len(request_hash) != 71
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "EditAuthorityApproval request hash is invalid."
        )
    approval_hash = refs["edit_authority_approval"].artifact_hash
    evidence_hash = refs["evidence_pack"].artifact_hash
    if not _has_upstream(
        envelopes["evidence_pack"],
        "edit_authority_approval",
        approval_hash,
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "EvidencePack is not bound to the current Approval."
        )
    if (
        plan.get("feature_id") != feature_id
        or not _has_upstream(
            envelopes["implementation_plan"],
            "edit_authority_approval",
            approval_hash,
        )
        or not _has_upstream(
            envelopes["implementation_plan"],
            "evidence_pack",
            evidence_hash,
        )
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "ImplementationPlan lineage does not bind current Approval and EvidencePack."
        )
    scope = plan.get("diagnostic_scope")
    test_plan = plan.get("test_plan")
    if (
        not isinstance(scope, dict)
        or scope.get("schema_version") != _DIAGNOSTIC_SCOPE_SCHEMA
        or scope.get("root_cause_status") != "unresolved"
        or scope.get("observation_only") is not True
        or scope.get("product_acceptance_allowed") is not False
        or scope.get("repair_planner_allowed") is not False
        or scope.get("source_patch_allowed") is not False
        or scope.get("selected_binding_ids")
        != list(_SELECTED_BINDING_IDS)
        or scope.get("selected_change_ids") != list(_SELECTED_CHANGE_IDS)
        or scope.get("new_plan_contains_only_selected_bindings") is not True
        or scope.get("new_plan_contains_only_selected_changes") is not True
        or scope.get("edit_authority_approval_revision")
        != _revision(refs["edit_authority_approval"])
        or not isinstance(test_plan, dict)
        or test_plan.get("schema_version") != _DIAGNOSTIC_TEST_SCHEMA
        or test_plan.get("product_acceptance_allowed") is not False
        or test_plan.get("repair_planner_allowed") is not False
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "ImplementationPlan diagnostic scope or test boundary is invalid."
        )
    registry = plan.get("binding_registry")
    bindings = (
        registry.get("edit_bindings")
        if isinstance(registry, dict)
        else None
    )
    changes = plan.get("proposed_changes")
    if not isinstance(bindings, list) or not isinstance(changes, list):
        raise StaggerDiagnosticDiffPreflightError(
            "ImplementationPlan bindings or changes are invalid."
        )
    if (
        [item.get("binding_id") for item in bindings]
        != list(_SELECTED_BINDING_IDS)
        or [item.get("change_id") for item in changes]
        != list(_SELECTED_CHANGE_IDS)
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "ImplementationPlan contains work outside the selected diagnostic scope."
        )
    for binding, change, binding_id, change_id in zip(
        bindings,
        changes,
        _SELECTED_BINDING_IDS,
        _SELECTED_CHANGE_IDS,
        strict=True,
    ):
        if (
            binding.get("canonical_target_path") != _SOURCE_PATH
            or binding.get("repair_planner_allowed") is not False
            or binding.get("source_patch_allowed") is not False
            or change.get("edit_binding_id") != binding_id
            or change.get("change_id") != change_id
            or change.get("operation") != _EXPECTED_OPERATIONS[binding_id]
        ):
            raise StaggerDiagnosticDiffPreflightError(
                f"{binding_id}/{change_id} exceeds the approved diagnostic scope."
            )
    evidence_items = {
        str(item.get("evidence_id")): item
        for item in evidence.get("items", ())
        if isinstance(item, dict) and item.get("evidence_id")
    }
    for binding_id in _SELECTED_BINDING_IDS:
        evidence_id = "stagger_observation_scope_" + binding_id
        item = evidence_items.get(evidence_id)
        binding = next(
            value
            for value in bindings
            if value.get("binding_id") == binding_id
        )
        if (
            not isinstance(item, dict)
            or item.get("source_path") != binding.get(
                "canonical_target_path"
            )
            or item.get("source_hash") != binding.get("source_hash")
            or item.get("symbol") != binding.get("target_symbol")
            or item.get("span") != binding.get("target_span")
        ):
            raise StaggerDiagnosticDiffPreflightError(
                f"{binding_id} does not match its EvidencePack item."
            )


def _validate_live_sources_and_dependencies(
    *,
    source_root: Path,
    source_hash: str,
    plugin_hash: str,
    evidence: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    bindings = plan["binding_registry"]["edit_bindings"]
    if any(binding.get("source_hash") != source_hash for binding in bindings):
        raise StaggerDiagnosticDiffPreflightError(
            "Current Stagger source hash does not match all selected bindings."
        )
    items = {
        str(item.get("evidence_id")): item
        for item in evidence.get("items", ())
        if isinstance(item, dict) and item.get("evidence_id")
    }
    config_item = items.get("stagger_diagnostic_config_gate")
    identity_item = items.get("stagger_diagnostic_identity_api")
    if (
        not isinstance(config_item, dict)
        or config_item.get("source_path") != _PLUGIN_PATH
        or config_item.get("source_hash") != plugin_hash
        or Path(str(config_item.get("source_ref"))).resolve()
        != (source_root / _PLUGIN_PATH).resolve()
    ):
        raise StaggerDiagnosticDiffPreflightError(
            "Current Plugin diagnostic config source does not match EvidencePack."
        )
    plugin_text = (source_root / _PLUGIN_PATH).read_text(encoding="utf-8")
    required_config_fragments = (
        "public static ConfigEntry<bool> EnableDiagnosticLogging",
        '"General"',
        '"EnableDiagnosticLogging"',
        "false",
    )
    if any(fragment not in plugin_text for fragment in required_config_fragments):
        raise StaggerDiagnosticDiffPreflightError(
            "Current Plugin source no longer exposes the approved diagnostic gate."
        )
    assemblies = (
        identity_item.get("dependency_assemblies")
        if isinstance(identity_item, dict)
        else None
    )
    if not isinstance(assemblies, list) or len(assemblies) != 3:
        raise StaggerDiagnosticDiffPreflightError(
            "Diagnostic identity dependency evidence is incomplete."
        )
    observed_roles: set[str] = set()
    for assembly in assemblies:
        if not isinstance(assembly, dict):
            raise StaggerDiagnosticDiffPreflightError(
                "Diagnostic identity dependency entry is invalid."
            )
        role = assembly.get("role")
        path_value = assembly.get("path")
        expected_hash = assembly.get("sha256")
        if (
            not isinstance(role, str)
            or role in observed_roles
            or not isinstance(path_value, str)
            or not isinstance(expected_hash, str)
        ):
            raise StaggerDiagnosticDiffPreflightError(
                "Diagnostic identity dependency identity is invalid."
            )
        dependency_path = Path(path_value).resolve()
        if not dependency_path.is_file():
            raise StaggerDiagnosticDiffPreflightError(
                f"Diagnostic identity dependency is missing: {role}"
            )
        actual_hash = hashlib.sha256(
            dependency_path.read_bytes()
        ).hexdigest().upper()
        if actual_hash != expected_hash:
            raise StaggerDiagnosticDiffPreflightError(
                f"Diagnostic identity dependency changed: {role}"
            )
        observed_roles.add(role)
    if observed_roles != {
        "unity_core_module",
        "modules_asm",
        "il2cpp_interop_runtime",
    }:
        raise StaggerDiagnosticDiffPreflightError(
            "Diagnostic identity dependency roles are incomplete."
        )


def _build_diagnostic_proposal(
    *,
    feature_id: str,
    run_id: str,
    approval_ref: ArtifactRef,
    evidence_ref: ArtifactRef,
    plan_ref: ArtifactRef,
    source_hash: str,
) -> dict[str, Any]:
    diff_intent = [
        _change(
            "chg_007",
            "edit_binding_007",
            _SELECTION_LINE,
            _SELECTION_AFTER,
            match_mode="bound_span_exact",
        ),
        _change(
            "chg_008",
            "edit_binding_008",
            _USE_BLOCK,
            _USE_AFTER,
        ),
        _change(
            "chg_009",
            "edit_binding_009",
            _STATE_LINE,
            _STATE_AFTER,
        ),
        _change(
            "chg_010",
            "edit_binding_010",
            _HELPER_LINE,
            _HELPER_AFTER,
        ),
    ]
    identity = {
        "schema_version": "stagger_hud_parent_diagnostic_exact_diff_v1",
        "feature_id": feature_id,
        "run_id": run_id,
        "approval_revision": _revision(approval_ref),
        "evidence_pack_revision": _revision(evidence_ref),
        "implementation_plan_revision": _revision(plan_ref),
        "source_sha256": source_hash,
        "selected_binding_ids": list(_SELECTED_BINDING_IDS),
        "selected_change_ids": list(_SELECTED_CHANGE_IDS),
        "diff_intent": diff_intent,
    }
    proposal_id = "stagger_hud_parent_diagnostic_" + hashlib.sha256(
        _canonical_json(identity)
    ).hexdigest()[:32]
    return {
        "proposal_id": proposal_id,
        "feature_id": feature_id,
        "run_id": run_id,
        "summary": (
            "Add bounded observation-only HUD parent diagnostics without "
            "changing the existing selection, cast, guard, or product result."
        ),
        "diff_intent": diff_intent,
        "context_pack": {
            "artifact_hashes": {
                "edit_authority_approval": approval_ref.artifact_hash,
                "evidence_pack": evidence_ref.artifact_hash,
                "implementation_plan": plan_ref.artifact_hash,
            },
            "allowed_edit_binding_ids": list(_SELECTED_BINDING_IDS),
            "source_snapshot_sha256": source_hash,
        },
        "risk_notes": [
            "Observation logging is disabled by default.",
            "This diff does not confirm a Runtime root cause.",
            "This diff does not authorize source write, Build, or GTFO launch.",
        ],
    }


def _change(
    change_id: str,
    binding_id: str,
    before_text: str,
    after_text: str,
    *,
    match_mode: str = "unique",
) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "kind": "exact_text_replace",
        "before_text": before_text,
        "after_text": after_text,
        "expected_occurrences": 1,
    }
    if match_mode != "unique":
        patch["match_mode"] = match_mode
    return {
        "change_id": change_id,
        "edit_binding_id": binding_id,
        "supporting_binding_ids": [],
        "patch": patch,
    }


def _artifact_ref(
    feature_id: str,
    artifact_type: str,
    path: str | Path,
    artifact_hash: str,
) -> ArtifactRef:
    return ArtifactRef(
        feature_id=feature_id,
        artifact_type=artifact_type,
        path=str(Path(path).resolve()),
        artifact_hash=artifact_hash,
    )


def _artifact_data(envelope: dict[str, Any]) -> dict[str, Any]:
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise StaggerDiagnosticDiffPreflightError(
            "Artifact data must be an object."
        )
    return data


def _require_current_exact_revisions(
    store: ArtifactStore,
    refs: Any,
) -> None:
    selected = tuple(refs)
    latest = {
        ref.artifact_type: ref
        for ref in store.list_feature_artifacts(selected[0].feature_id)
    }
    for ref in selected:
        current = latest.get(ref.artifact_type)
        registered = {
            (str(Path(item.path).resolve()), item.artifact_hash)
            for item in store.list_feature_artifact_revisions(
                ref.feature_id,
                ref.artifact_type,
            )
        }
        if (
            current is None
            or current.artifact_hash != ref.artifact_hash
            or (str(Path(ref.path).resolve()), ref.artifact_hash)
            not in registered
        ):
            raise StaggerDiagnosticDiffPreflightError(
                f"{ref.artifact_type} is no longer the current exact revision."
            )


def _has_upstream(
    envelope: dict[str, Any],
    artifact_type: str,
    artifact_hash: str,
) -> bool:
    inputs = envelope.get("inputs")
    upstreams = (
        inputs.get("upstream_artifacts")
        if isinstance(inputs, dict)
        else None
    )
    return isinstance(upstreams, list) and any(
        isinstance(item, dict)
        and item.get("artifact_type") == artifact_type
        and item.get("artifact_hash") == artifact_hash
        for item in upstreams
    )


def _revision(ref: ArtifactRef) -> dict[str, str]:
    return {
        "feature_id": ref.feature_id,
        "path": ref.path,
        "artifact_hash": ref.artifact_hash,
    }


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
