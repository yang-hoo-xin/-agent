"""Opt-in current-Plan consumption of an exact existing crosshair matrix.

The original adapter remains the immutable matrix/source/diagnosis anchor. Its
fixed-Plan generation adapter is not relaxed or used to materialize new edits.
"""
from __future__ import annotations

import codecs
import json
from copy import deepcopy
from pathlib import Path

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.domain.accurate_crosshair_eval import (
    BoundExistingMatrixOracle,
    _reference,
    _response_scope,
    _save,
)
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.model_qualification import canonical_hash, read_bound_json
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector


def _target_identity(binding):
    return (binding["canonical_target_path"], binding["source_hash"],
            canonical_hash(binding["target_span"]))


class CurrentPlanExistingMatrixOracle(BoundExistingMatrixOracle):
    """Validate a new exact Plan while reusing original checks and diagnostics."""

    def __init__(self, *, artifact_store_root, **kwargs):
        self.store = ArtifactStore(artifact_store_root)
        super().__init__(**kwargs)
        if len(self.expected_check_ids) != 36 or len(set(self.expected_check_ids)) != 36:
            raise ValueError("PATCH_EVAL_ORIGINAL_MATRIX_REQUIRED")

    def verification_identity(self):
        identity = super().verification_identity()
        identity["validator_sha256"] = canonical_hash({
            "original_wrapper": identity["validator_sha256"],
            "current_plan_adapter": _reference(__file__),
        })
        return identity

    def __call__(self, context):
        identity = self.verification_identity()
        ref = ArtifactRef(**context["implementation_plan_ref"])
        envelope = self.store.read(ref)
        plan = envelope["data"]
        if (ref.artifact_type != "implementation_plan" or envelope["status"] != "success"
                or plan.get("blocking") or plan != context["implementation_plan"]):
            raise ValueError("PATCH_EVAL_CURRENT_PLAN_MISMATCH")
        scope = _response_scope(context)
        output = self.output_root / scope
        self.calls += 1
        config = read_bound_json(self.configuration_ref)
        kwargs = config["behavior_evaluator"]["kwargs"]
        kwargs["output_root"] = str(Path(kwargs["output_root"]) / scope)
        config_ref = _save(output / f"delegate-worker-{self.calls:03d}.json", config)
        selected = PatchWorkerConfiguration.load(config_ref["path"]).behavior_evaluator()
        # This version specifically composes the existing observed-case factory.
        # It never changes that factory's fixed Plan or the historical instance.
        selected.prepare_for_patch_attempt()
        observed_adapter = selected._get_delegate()
        legacy = observed_adapter.delegate
        originals = legacy._current_sources()
        if ref.feature_id != legacy.plan_ref["feature_id"]:
            raise ValueError("PATCH_EVAL_FEATURE_CHANGED")
        inspector = PlanBoundSourceInspector(workspace_root=legacy.source_root,
            implementation_plan=plan, policy=PatchAgentLoopPolicy())
        if inspector.source_snapshot_sha256 != context["source_snapshot_sha256"]:
            raise ValueError("PATCH_EVAL_CURRENT_SOURCE_MISMATCH")
        changes = context["generated_changes"]
        if canonical_hash(changes) != context["generated_changes_sha256"]:
            raise ValueError("PATCH_EVAL_CHANGE_IDENTITY_MISMATCH")
        response_ref = context["model_response"]
        raw = Path(response_ref["path"]).read_bytes()
        if (_reference(response_ref["path"])["sha256"] != response_ref["output_sha256"]
                or len(raw) != response_ref["output_utf8_bytes"]):
            raise ValueError("PATCH_EVAL_RESPONSE_IDENTITY_MISMATCH")
        submitted = json.loads(raw.decode("utf-8"))["changes"]
        by_id = {row["edit_binding_id"]: row for row in submitted}
        planned = {(row["change_id"], row["edit_binding_id"]): row for row in plan["proposed_changes"]}
        if (len(by_id) != len(submitted) or len(changes) != len(submitted)
                or {(row["change_id"], row["edit_binding_id"]) for row in changes} != set(planned)):
            raise ValueError("PATCH_EVAL_CHANGE_SET_MISMATCH")
        bindings = {row["binding_id"]: row for row in plan["binding_registry"]["edit_bindings"]}
        original_targets = {_target_identity(row) for row in legacy.bindings.values()}
        compiled = set(legacy.compiled_paths)
        for change in changes:
            binding = bindings[change["edit_binding_id"]]
            if change["expected_validation"] != planned[(change["change_id"], change["edit_binding_id"])]["expected_validation"]:
                raise ValueError("PATCH_EVAL_VALIDATION_OBLIGATION_CHANGED")
            path = binding["canonical_target_path"]
            if (path not in originals or (path not in compiled
                    and _target_identity(binding) not in original_targets)):
                raise ValueError("PATCH_EVAL_SOURCE_COVERAGE_INCOMPLETE")
            before = change["patch"]["before_text"]
            span = binding["target_span"]
            if before.encode("utf-8") != b"".join(originals[path].splitlines(keepends=True)[span["start_line"] - 1:span["end_line"]]):
                raise ValueError("PATCH_EVAL_BEFORE_SPAN_MISMATCH")
            model_after = by_id[change["edit_binding_id"]]["after_text"]
            after = change["patch"]["after_text"]
            if after != model_after and not (
                originals[path].startswith(codecs.BOM_UTF8) and after == "\ufeff" + model_after
                or not originals[path].startswith(codecs.BOM_UTF8) and model_after == "\ufeff" + after
            ):
                raise ValueError("PATCH_EVAL_MODEL_OUTPUT_CHANGED")
        materialized = materialize_exact_text_patch(workspace_root=legacy.source_root,
            diff_intent=changes, implementation_plan=plan)
        code = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
                "files": sorted(materialized.files)}
        if code != context["materialized_code_identity"]:
            raise ValueError("PATCH_EVAL_CODE_IDENTITY_MISMATCH")
        run = legacy.harness / "acceptance_runs" / f"evaluation_{self.calls}"
        run.mkdir(parents=True, exist_ok=False)
        _save(run / "callback_input.json", context)
        if len({Path(path).name for path in compiled}) != len(compiled):
            raise ValueError("PATCH_EVAL_COMPILED_NAME_COLLISION")
        for name in ("baseline", "product_proposal"):
            fixture = run / name
            fixture.mkdir()
            for path in legacy.compiled_paths:
                content = materialized.files.get(path, originals[path]) if name == "product_proposal" else originals[path]
                (fixture / Path(path).name).write_bytes(content)
        _save(run / "provenance_audit.json", {
            "input_kind": "current_product_generation_pre_proposal", "proposal_hash": None, "dry_run_hash": None,
            "source_root": str(legacy.source_root), "source_sha256": legacy.baseline["source_sha256"],
            "plan_ref": context["implementation_plan_ref"], "matrix_anchor_plan_ref": legacy.plan_ref,
            "model_response": response_ref, "materialized_code_identity": code,
            "uncompiled_changed_files": sorted(set(materialized.files) - compiled),
        })
        report = legacy._execute(run, {
            "status": "identity_failed", "failure_owner": "unknown", "owner_binding_ids": [], "observations": [],
            "generated_changes_sha256": context["generated_changes_sha256"],
            "source_snapshot_sha256": context["source_snapshot_sha256"],
        })
        complete = False
        if report.get("verification_ref"):
            matrix = read_bound_json(report["verification_ref"])
            if (sorted(row["check"] for row in matrix["checks"]) != sorted(self.expected_check_ids)
                    or matrix["executions"] != 40):
                raise ValueError("PATCH_EVAL_CHECK_SET_CHANGED")
            compile_rows = [json.loads((run / f"compile_{name}.json").read_text(encoding="utf-8"))
                            for name in ("baseline", "product_proposal")]
            execution = json.loads((run / "matrix_execution.json").read_text(encoding="utf-8"))
            complete = (all(row["exit_code"] == 0 for row in compile_rows)
                and execution["exit_code"] == (1 if matrix["failures"] else 0)
                and not any(row["check"] == "CSHARP_PROCESS_EXECUTION" for row in matrix["failures"]))
            if report["status"] == "passed" and not complete:
                raise ValueError("PATCH_EVAL_INCOMPLETE_PASS_REJECTED")
            matrix["materialized_code_identity"] = code
            matrix["implementation_plan_ref"] = context["implementation_plan_ref"]
            matrix["source_matrix_ref"] = report["verification_ref"]
            report["verification_ref"] = _save(output / f"matrix-{self.calls:03d}.json", matrix)
        if report.get("failure_owner") == "patch_implementation":
            mapped = []
            for old_id in report["owner_binding_ids"]:
                old = legacy.bindings.get(old_id)
                matches = [key for key, value in bindings.items() if old and _target_identity(value) == _target_identity(old)]
                if len(matches) != 1:
                    mapped = []
                    break
                mapped.extend(matches)
            if not mapped:
                report.update(status="needs_evidence", failure_owner="unknown", owner_binding_ids=[])
            else:
                report["owner_binding_ids"] = sorted(set(mapped))
        legacy._current_sources()
        inspector.validate_snapshot()
        self.verification_identity()
        report.update(execution_origin="executed" if complete else "incomplete", callback_invoked=True,
            materialized_code_identity=code, implementation_plan_ref=deepcopy(context["implementation_plan_ref"]),
            model_response_sha256=response_ref["output_sha256"], verification_identity=identity,
            matrix_anchor_plan_ref=legacy.plan_ref)
        return {**report, "report_ref": _save(output / f"report-{self.calls:03d}.json", report)}


def make_current_plan_existing_matrix_evaluator(**kwargs):
    """Select using existing worker factory_ref/factory_name/kwargs configuration.

    kwargs are artifact_store_root plus the existing BoundExistingMatrixOracle
    configuration_ref, identity_refs, expected_check_ids and output_root. The
    configuration_ref selects the unmodified original observed-case adapter,
    including its exact matrix anchor Plan. Current Plan authority comes only
    from the worker's admitted implementation_plan_ref and matching payload.
    """
    return CurrentPlanExistingMatrixOracle(**kwargs)
