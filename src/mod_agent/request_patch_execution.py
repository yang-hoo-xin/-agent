"""Product Graph assembly of the existing Patch worker and its original journal.

This factory does not run a Graph or another public entry. The calling product
executor retains routing, approval, application, build and runtime ownership.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.patch_execution_trace import PatchExecutionTraceConfiguration
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, normalize_upstream_effects


def _validate_applied_source_chain(workspace_root, changes, original_bindings, expected_binding_ids):
    """Check each ordered per-file Apply hash chain against its final live bytes."""
    from src.mod_agent.fresh_planning_continuation import _is_sha256
    from src.mod_agent.local_entry import LocalEntryError

    def require(condition, message):
        if not condition:
            raise LocalEntryError("PRODUCT_PATCH_REPAIR_IDENTITY_INVALID: " + message)

    root = Path(workspace_root).resolve()
    applied_ids = [change["edit_binding_id"] for change in changes]
    require(len(applied_ids) == len(set(applied_ids)) and set(applied_ids) == expected_binding_ids,
            "Original Apply changed different bindings from its Proposal.")
    final_hashes = {}
    for change in changes:
        binding = original_bindings[change["edit_binding_id"]]
        require(change["path"] == binding["canonical_target_path"],
                "Original Apply source path differs from its Plan binding.")
        path = (root / change["path"]).resolve()
        require(path.is_relative_to(root) and path.is_file(), "Applied source is outside this workspace or missing.")
        before, after = change["before_sha256"], change["after_sha256"]
        require(_is_sha256(before) and _is_sha256(after), "Apply chain hashes are invalid.")
        expected_before = final_hashes.get(path, binding.get("source_hash"))
        require(before == expected_before, "Apply before/after chain is discontinuous for its bound file.")
        final_hashes[path] = after
    for path, final_hash in final_hashes.items():
        require(hashlib.sha256(path.read_bytes()).hexdigest() == final_hash,
                "Current source differs from the code written for the failed Build.")


def admit_product_repair_context(*, artifact_store, workspace_root, state,
                                 implementation, evidence_pack, worker_receipts):
    """Read the Repair owner's exact failure lineage without rebinding or writing.

    Applied repairs require the Graph to publish current Evidence/Plan revisions
    before this function is called. Original response bytes remain diagnostic
    history; they never replace the current Plan's baseline or edit authority.
    """
    from src.libs.llm import ChatResponse
    from src.mod_agent.fresh_planning_continuation import (
        _artifact_ref_dict,
        _canonical_sha256,
        _read_hashed_repair_file,
        _read_selected_exact_revision,
        _validate_selected_plan,
        _validate_source_items,
    )
    from src.mod_agent.local_entry import (
        LocalEntryError,
        _external_evidence_items,
        _patch_generation_obligation_projection,
    )
    from src.mod_agent.proposal.code_generator import LLMExactPatchGenerator
    from src.mod_agent.proposal.patch_agent_loop import PlanBoundSourceInspector

    def require(condition, message):
        if not condition:
            raise LocalEntryError("PRODUCT_PATCH_REPAIR_IDENTITY_INVALID: " + message)

    def selected(kind):
        return ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
            path=state["artifacts"][kind], artifact_hash=state["artifact_hashes"][kind])

    def read(ref):
        require(ref.feature_id == state["feature_id"], "Repair Artifact belongs to another feature.")
        return _read_selected_exact_revision(artifact_store, ref, consumer_stage=None)

    def upstream(envelope, kind):
        rows = [row for row in envelope["inputs"]["upstream_artifacts"] if row["artifact_type"] == kind]
        require(len(rows) == 1, "Expected one exact " + kind + " upstream.")
        row = rows[0]
        return ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
                           path=row["path"], artifact_hash=row["artifact_hash"])

    current_plan_ref, current_evidence_ref = selected("implementation_plan"), selected("evidence_pack")
    require(read(current_plan_ref)["data"] == implementation, "Current Plan input changed.")
    require(read(current_evidence_ref)["data"] == evidence_pack, "Current Evidence input changed.")
    _validate_selected_plan(implementation, evidence_pack, feature_id=state["feature_id"])
    _validate_source_items(evidence_pack, Path(workspace_root))
    repair_ref = selected("repair_plan")
    repair_envelope = read(repair_ref)
    repair = repair_envelope["data"]
    require(repair_envelope["status"] == "success" and not repair.get("blockers")
            and repair.get("allowed_next_stage") == "generate_patch_proposal"
            and repair.get("retry_count") == state.get("retry_count"), "Repair owner has not admitted this revision.")
    failure_source = repair["failure_source"]
    source = repair["source_proposal"]
    if failure_source == "behavior_report":
        parent_ref = ArtifactRef(**source)
    else:
        parent_ref = ArtifactRef(feature_id=state["feature_id"], artifact_type="patch_proposal",
                                path=source["ref"], artifact_hash=source["hash"])
    require(upstream(repair_envelope, "patch_proposal") == parent_ref,
            "Repair does not reference its declared original Proposal.")
    parent = read(parent_ref)
    review_ref = selected("proposal_review")
    review = read(review_ref)
    require(parent["status"] == "success" and upstream(review, "patch_proposal") == parent_ref,
            "Original Review does not belong to the failed Proposal.")
    require(review["data"].get("allowed_next_stage") == "dry_run_apply",
            "Repair requires its original passed Review.")
    old_plan_ref, old_evidence_ref = upstream(parent, "implementation_plan"), upstream(parent, "evidence_pack")
    old_plan, old_evidence = read(old_plan_ref)["data"], read(old_evidence_ref)["data"]
    feature = read(selected("feature_spec"))["data"]
    changes = parent["data"]["diff_intent"]
    response_hashes = {change.get("generation", {}).get("model_response_sha256") for change in changes}
    require(len(response_hashes) == 1 and None not in response_hashes, "Original response identity is incomplete.")
    response_hash = next(iter(response_hashes))
    matched = [receipt for receipt in worker_receipts
               if receipt.get("model_response", {}).get("output_sha256") == response_hash]
    existing = repair.get("repair_context") or {}
    if not matched and failure_source == "behavior_report":
        retained = json.loads(_read_hashed_repair_file(existing["parent_attempt_ref"]))
        matched = [retained["factory_receipt"]]
    require(len(matched) == 1, "Original executed worker response is missing or ambiguous.")
    response = matched[0]["model_response"]
    require(response["output_sha256"] == response_hash, "Original response digest differs from Proposal.")
    response_ref = {"path": response["path"], "sha256": response_hash}
    previous_response = _read_hashed_repair_file(response_ref).decode("utf-8")
    obligations = _patch_generation_obligation_projection(
        feature_spec=feature, implementation=old_plan, planned_changes=old_plan["proposed_changes"])
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(
        user_request=feature["user_request"], evidence_items=_external_evidence_items(old_evidence["items"]),
        binding_registry=old_plan["binding_registry"], constraints=obligations["side_effect_boundaries"],
        target_behavior=obligations["target_behavior"], acceptance_criteria=obligations["acceptance_criteria"],
        runtime_verification_plan=obligations["runtime_verification_plan"],
        required_change_units=obligations["required_change_units"],
        required_validation_by_binding={item["edit_binding_id"]: item["expected_validation"]
                                        for item in obligations["required_change_units"]})
    generated = generator.materialize_prepared_native(
        prepared, ChatResponse(content=previous_response, model=response["model"]))
    original_by_binding = {change["edit_binding_id"]: change for change in changes}
    require(len(original_by_binding) == len(changes) == len(generated.changes), "Original binding coverage changed.")
    for change in generated.changes:
        require(original_by_binding.get(change["edit_binding_id"], {}).get("patch") == change["patch"],
                "Retained response code differs from the original Proposal.")

    inspector = PlanBoundSourceInspector(workspace_root=workspace_root,
        implementation_plan=implementation, policy=PatchAgentLoopPolicy(), evidence_pack=evidence_pack)
    allowed = list(inspector.available_binding_ids)
    require(set(allowed).issubset(set(repair["allowed_edit_binding_ids"])), "Current Plan expands the Repair owner's bindings.")
    context = {
        "schema_version": "patch_repair_context_v1", "failure_source": failure_source,
        "parent_proposal": _artifact_ref_dict(parent_ref), "parent_review": _artifact_ref_dict(review_ref),
        "parent_response_ref": response_ref, "failed_response_ref": response_ref,
        "previous_response": previous_response, "failed_diff_intent": list(generated.changes),
        "current_plan_ref": _artifact_ref_dict(current_plan_ref),
        "current_evidence_ref": _artifact_ref_dict(current_evidence_ref),
        "repair_plan_ref": _artifact_ref_dict(repair_ref), "allowed_edit_binding_ids": allowed,
        "source_snapshot_sha256": inspector.source_snapshot_sha256,
        "generated_changes_sha256": _canonical_sha256(generated.changes), "approval_inherited": False,
    }
    if failure_source == "behavior_report":
        require(current_plan_ref == old_plan_ref and current_evidence_ref == old_evidence_ref,
                "Unapplied behavior repair changed its baseline Plan.")
        report_ref = existing["failure_report_ref"]
        report = json.loads(_read_hashed_repair_file(report_ref))
        require(report.get("status") in {"behavior_failed", "needs_evidence"}
                and report.get("generated_changes_sha256") == context["generated_changes_sha256"]
                and report.get("source_snapshot_sha256") == inspector.source_snapshot_sha256
                and report.get("observations"), "Behavior failure does not bind the original checked code.")
        context.update(failure_report=report, failure_report_ref=dict(report_ref),
            base_relationship="full_replacement_against_unchanged_parent_base")
        return context

    require(failure_source == "build", "This Repair source has no admitted executed-code adapter.")
    build_ref = selected("build_result")
    require(upstream(repair_envelope, "build_result") == build_ref, "Repair selected another Build result.")
    build = read(build_ref)
    data = build["data"]
    require(data.get("status") == "failed" and data.get("real_build_performed") is True
            and data.get("execution_mode") == "local" and data.get("input_execution_mode") == "isolated_apply"
            and data.get("diagnostics"), "Build has no executed failed isolated input and diagnostics.")
    apply_ref = upstream(build, "isolated_apply_result")
    applied = read(apply_ref)
    require(upstream(applied, "patch_proposal") == parent_ref
            and upstream(applied, "proposal_review") == review_ref,
            "Build input does not belong to the original Proposal and Review.")
    applied_data = applied["data"]
    require(applied["status"] == "success" and applied_data.get("actual_write_performed") is True
            and applied_data.get("real_patch_applied") is True and applied_data.get("changes")
            and applied_data.get("approved_diff_hash") == applied_data.get("diff_hash")
            and bool(applied_data.get("diff_hash")),
            "Original Apply did not record actual written code.")
    require(current_plan_ref != old_plan_ref and current_evidence_ref != old_evidence_ref,
            "Applied Repair needs Graph-owned current Evidence and Plan revisions.")
    original_bindings = {binding["binding_id"]: binding
                         for binding in old_plan["binding_registry"]["edit_bindings"]}
    _validate_applied_source_chain(workspace_root, applied_data["changes"], original_bindings, set(original_by_binding))
    build_file_ref = {"path": build_ref.path, "sha256": hashlib.sha256(Path(build_ref.path).read_bytes()).hexdigest()}
    context.update(
        base_relationship="revision_against_verified_applied_parent",
        isolated_apply_ref=_artifact_ref_dict(apply_ref), build_result_ref=_artifact_ref_dict(build_ref),
        failure_report_ref=build_file_ref, failure_report_origin="build_result_projection",
        failure_report={"status": "build_failed", "failure_owner": "unknown",
            "owner_binding_ids": list(repair["allowed_edit_binding_ids"]),
            "observations": deepcopy(data["diagnostics"]), "report_ref": build_file_ref,
            "source_snapshot_sha256": inspector.source_snapshot_sha256,
            "generated_changes_sha256": context["generated_changes_sha256"],
            "failure_source": "build", "diagnosis_is_not_authority": True},
    )
    return context


class RequestPatchExecution:
    """One task's worker assembly; each Graph visit has a distinct invocation."""

    def __init__(self, *, artifact_store: ArtifactStore, workspace_root: Path,
                 profile: Any, identity_reader: Callable[..., Any],
                 policy: PatchAgentLoopPolicy, reserve_model_call: Callable[[str], None],
                 budget_snapshot: Callable[[], Mapping[str, Any]],
                 behavior_evaluator: Any = None, trace_configuration: Any = None,
                 repair_profile: Any = None, worker_configuration_ref: Any = None,
                 adapter_factory: Callable[..., Any] | None = None):
        self.store = artifact_store
        self.workspace_root = Path(workspace_root).resolve()
        self.profile = profile
        self.repair_profile = repair_profile
        self.identity_reader = identity_reader
        self.policy = policy
        self.reserve_model_call = reserve_model_call
        self.budget_snapshot = budget_snapshot
        self.behavior_evaluator = behavior_evaluator
        self.trace_configuration = trace_configuration or PatchExecutionTraceConfiguration()
        self.worker_configuration_ref = worker_configuration_ref
        self.adapter_factory = adapter_factory
        self.journals: list[Any] = []
        self.receipts: list[dict[str, Any]] = []
        self._repair_attempts: list[int] = []
        self._upstream_effects = normalize_upstream_effects(None)
        self._consumed_reads = 0
        self._consumed_bytes = 0

    def bind_upstream_effects(self, effects: Mapping[str, str]) -> None:
        self._upstream_effects = normalize_upstream_effects(effects)

    def patch_attempt_receipt(self) -> dict[str, Any]:
        return deepcopy(self.receipts[-1]) if self.receipts else {}

    def __call__(self, state, implementation, evidence_pack):
        from src.mod_agent.fresh_planning_continuation import PatchContinuationAttemptJournal
        from src.mod_agent.local_entry import LocalEntryError, LocalOllamaInitialPatchAdapter

        role = "repair" if state.get("current_stage") == "repair_plan" else "initial_patch"
        repair_context = (admit_product_repair_context(
            artifact_store=self.store, workspace_root=self.workspace_root, state=state,
            implementation=implementation, evidence_pack=evidence_pack, worker_receipts=self.receipts)
            if role == "repair" else None)
        refs = {kind: ArtifactRef(feature_id=state["feature_id"], artifact_type=kind,
                                 path=state["artifacts"][kind],
                                 artifact_hash=state["artifact_hashes"][kind])
                for kind in ("feature_spec", "evidence_pack", "implementation_plan")}
        if self.store.read(refs["implementation_plan"])["data"] != implementation:
            raise LocalEntryError("PRODUCT_PATCH_PLAN_CONTEXT_MISMATCH")
        if self.store.read(refs["evidence_pack"])["data"] != evidence_pack:
            raise LocalEntryError("PRODUCT_PATCH_EVIDENCE_CONTEXT_MISMATCH")
        invocation = f"{state['run_id']}_patch_{len(self.journals) + 1}"
        profile = self.repair_profile if role == "repair" and self.repair_profile is not None else self.profile
        limits = self.budget_snapshot()
        remaining = min(limits["remaining"], limits["by_stage"][role]["remaining"],
                        self.policy.max_total_model_turns)
        if remaining < 1:
            raise LocalEntryError("PRODUCT_MODEL_CALL_BUDGET_EXHAUSTED")
        policy = replace(self.policy, max_total_model_turns=remaining,
                         max_tool_rounds=max(0, self.policy.max_tool_rounds - self._consumed_reads),
                         max_observation_bytes=max(0, self.policy.max_observation_bytes - self._consumed_bytes))
        journal = PatchContinuationAttemptJournal.for_product_execution(
            artifact_root=self.store.root, run_id=invocation, request_id=state["request_id"],
            parent_run_id=state["run_id"], feature_spec_ref=refs["feature_spec"],
            evidence_pack_ref=refs["evidence_pack"], implementation_plan_ref=refs["implementation_plan"],
            workspace_root=self.workspace_root, max_model_calls=remaining,
            worker_configuration_ref=self.worker_configuration_ref,
            worker_profile_sha256=(hashlib.sha256(json.dumps(
                profile.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                allow_nan=False).encode()).hexdigest() if self.worker_configuration_ref else None))
        self.journals.append(journal)
        self._repair_attempts.append(state["retry_count"])
        worker = (self.adapter_factory or LocalOllamaInitialPatchAdapter)(
            profile=profile, artifact_store=self.store, workspace_root=self.workspace_root,
            patch_agent_loop_policy=policy, identity_reader=self.identity_reader,
            behavior_evaluator=self.behavior_evaluator, enable_recovery_loop=True)

        def record(event):
            if isinstance(event.get("factory_receipt"), Mapping):
                receipt = deepcopy(event["factory_receipt"])
                if len(self.receipts) < len(self.journals):
                    self.receipts.append(receipt)
                else:
                    self.receipts[-1] = receipt
            journal.record({**dict(event), "model_role": role,
                            "shared_model_budget": dict(self.budget_snapshot())})

        worker.bind_attempt_recorder(record)
        worker.bind_upstream_effects(self._upstream_effects)
        if repair_context is not None:
            worker.bind_repair_context(repair_context)
            journal.record({"phase": "product_repair_context_admitted", "repair_context": {
                key: value for key, value in repair_context.items()
                if key not in {"previous_response", "failed_diff_intent", "failure_report"}}})
        worker._shared_model_call_reserver = lambda _worker_role: self.reserve_model_call(role)
        worker_state = deepcopy(state)
        worker_state["run_id"] = invocation
        trace = self.trace_configuration.make_trace(run_id=invocation, feature_id=state["feature_id"],
            artifact_store_root=self.store.root, recorder=journal.record_observation)
        try:
            with trace.activate():
                changes = worker(worker_state, implementation, evidence_pack)
                journal.record({"phase": "product_patch_generated", "model_role": role,
                    "selected_artifacts": {key: asdict(ref) for key, ref in refs.items()},
                    "shared_model_budget": dict(self.budget_snapshot())})
                return changes
        finally:
            receipt = worker.patch_attempt_receipt()
            loop = receipt.get("patch_agent_loop") or {}
            phases = [loop, *(value["execution"] for name in ("validator_correction", "behavior_correction")
                             if isinstance(value := loop.get(name), Mapping)
                             and isinstance(value.get("execution"), Mapping))]
            self._consumed_reads += sum(int(phase.get("tool_rounds_used") or 0) for phase in phases)
            self._consumed_bytes += (sum(int(phase.get("total_observation_bytes") or 0) for phase in phases)
                                     + worker._recovery_observation_bytes)
            summary = self.trace_configuration.finish(trace)
            summary.update(trace_id=trace.context.trace_id, session_id=trace.session_id,
                           environment=trace.environment)
            journal.record_trace_summary(summary)

    def complete_product(self, result) -> None:
        """Project owner results into each worker's original queryable receipt."""
        self._complete_projection(result.to_dict(), result.outputs, result.effect_events,
                                  origin="ProductExecutionResultV1")

    def complete_deferred(self, pending) -> None:
        """Retain the original exact approval checkpoint without granting Apply."""
        from src.mod_agent.product_executor import ProductApprovalDeferred

        if not isinstance(pending, ProductApprovalDeferred):
            raise ValueError("PRODUCT_APPROVAL_DEFERRED_REQUIRED")
        if any(event.effect_role in {"isolated_apply", "build", "runtime"}
               for event in pending.effect_events):
            raise ValueError("PRODUCT_APPROVAL_DEFERRED_EFFECT_CONFLICT")
        self._complete_projection(pending.to_dict(), pending.outputs, pending.effect_events,
                                  origin="ProductApprovalDeferred", pending=pending)

    def _complete_projection(self, parent, outputs, effects, *, origin, pending=None):
        """A read-side projection, never a new execution result or Store Artifact."""
        from src.mod_agent.fresh_planning_continuation import _canonical_sha256

        parent_identity = {"owner": origin, "run_id": parent["run_id"],
            "sha256": _canonical_sha256(parent), "hash_basis": "canonical_owner_to_dict",
            "store_artifact": False, "full_result_retained_by": "parent_product_owner"}
        for journal, repair_attempt in zip(self.journals, self._repair_attempts):
            document = json.loads(journal.path.read_bytes())
            if (document["parent_run_id"] != parent["run_id"]
                    or document["request_id"] != parent["request_id"]
                    or document["feature_id"] != parent["feature_id"]):
                raise ValueError("PRODUCT_PATCH_OUTCOME_PARENT_IDENTITY_MISMATCH")
            segment = [output for output in outputs if output.repair_attempt == repair_attempt]
            selected = document["selected_artifacts"]
            refs = self._segment_output_refs(document, segment)
            deferred = pending is not None and refs.get("dry_run_result") == asdict(pending.dry_run_ref)
            if deferred:
                refs["workflow_checkpoint"] = asdict(pending.checkpoint_ref)
            invocations = {role: sum(event.effect_role == role and event.event_status == "started"
                and event.repair_attempt == repair_attempt for event in effects)
                for role in ("patch_generation", "dry_run", "isolated_apply", "build", "runtime")}
            native = document.get("execution_observations")
            model_calls = (sum(row.get("kind") == "generation" and row.get("name") == "patch.generate"
                and row.get("attributes", {}).get("transport_started") is True for row in native.values())
                if isinstance(native, dict) else None)
            counts = {"model": model_calls, "patch": invocations["patch_generation"],
                "dry_run": invocations["dry_run"],
                **{name: 0 if invocations[role] == 0 else None
                   for name, role in (("apply", "isolated_apply"), ("build", "build"), ("runtime", "runtime"))}}
            reached = [output for output in segment
                       if refs.get(output.artifact_role) == asdict(output.artifact_ref)]
            stage = (max(reached, key=lambda output: output.sequence).node_name
                     if reached else "generate_patch_proposal")
            terminal = {
                "origin": "product_execution_worker_projection", "source_owner": origin,
                "run_id": document["run_id"], "request_id": document["request_id"],
                "feature_id": document["feature_id"], "parent_product_run_id": parent["run_id"],
                "parent_product_result_identity": parent_identity,
                "parent_platform_status": parent.get("platform_status"),
                "parent_execution_disposition": parent.get("execution_disposition"),
                "status": ("awaiting_approval" if deferred else "blocked"
                           if parent.get("execution_disposition") == "domain_blocked"
                           else parent.get("platform_status", "partial")),
                "terminal_stage": "dry_run_apply" if deferred else stage,
                "first_failure": document.get("failure"), "execution_counts": counts,
                "execution_count_basis": "native_transport_markers_and_owner_effect_invocations; positive_apply_build_runtime_unmeasured",
                "owner_effect_invocations": invocations, "approval_granted": False,
                **{field: selected.get(kind) for kind, field in (
                    ("feature_spec", "feature_spec_artifact"), ("evidence_pack", "evidence_pack_artifact"),
                    ("implementation_plan", "implementation_plan_artifact"))},
                **{field: refs.get(kind) for kind, field in (
                    ("patch_proposal", "patch_proposal_artifact"), ("proposal_review", "proposal_review_artifact"),
                    ("dry_run_result", "dry_run_artifact"))},
            }
            if deferred:
                terminal.update(stopped_before="isolated_apply", workflow_checkpoint=asdict(pending.checkpoint_ref),
                    diff_hash=parent["diff_hash"], unified_diff_sha256=parent["unified_diff_sha256"],
                    approval_recorded=False)
            journal.record({"phase": "awaiting_approval" if deferred else "product_execution_finished",
                "artifacts": refs, "proposal_admitted": "patch_proposal" in refs,
                "parent_product_run_id": parent["run_id"], "parent_product_result_identity": parent_identity,
                "terminal_result": terminal, "terminal_result_sha256": _canonical_sha256(terminal),
                "shared_model_budget": dict(self.budget_snapshot())})

    def _segment_output_refs(self, document, outputs):
        """Join owner output lineage to this segment's exact Plan and response."""
        selected = document["selected_artifacts"]
        response = (document.get("factory_receipt") or {}).get("model_response")
        if not isinstance(response, Mapping) or not response.get("output_sha256"):
            return {}
        response_hash = response["output_sha256"]
        refs = {}

        def has(envelope, ref):
            return any(all(row.get(key) == ref[key] for key in ("artifact_type", "path", "artifact_hash"))
                       for row in envelope["inputs"]["upstream_artifacts"])

        for kind, required in (("patch_proposal", ("implementation_plan", "evidence_pack")),
                               ("proposal_review", ("patch_proposal",)),
                               ("dry_run_result", ("patch_proposal", "proposal_review")),
                               ("isolated_apply_result", ("patch_proposal", "proposal_review", "dry_run_result")),
                               ("build_result", ("dry_run_result", "isolated_apply_result"))):
            owners = selected if kind == "patch_proposal" else refs
            if any(name not in owners for name in required):
                continue
            matches = []
            for output in outputs:
                if output.artifact_role != kind or output.artifact_ref.feature_id != document["feature_id"]:
                    continue
                envelope = self.store.semantic_read_immutable(output.artifact_ref)
                if not all(has(envelope, owners[name]) for name in required):
                    continue
                if kind == "patch_proposal":
                    changes = envelope["data"]["diff_intent"]
                    if not response_hash or not changes or any(
                            change.get("generation", {}).get("model_response_sha256") != response_hash for change in changes):
                        continue
                matches.append(asdict(output.artifact_ref))
            if len(matches) == 1:
                refs[kind] = matches[0]
        return refs
