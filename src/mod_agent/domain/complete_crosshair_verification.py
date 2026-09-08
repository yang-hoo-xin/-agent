"""Compose existing pre-approval checks into one shared-worker feedback owner."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from src.mod_agent.domain.accurate_crosshair_configuration import (
    ActualCrosshairConfigurationChecker,
)
from src.mod_agent.domain.accurate_crosshair_revalidation import CurrentPlanExistingMatrixOracle
from src.mod_agent.domain.full_project_compilation import FullProjectCompilationChecker, _ref, _save
from src.mod_agent.local_entry import RunLocalGameFolderBindingV1
from src.mod_agent.model_qualification import canonical_hash


class CompleteCrosshairVerification:
    """Each failing phase returns original observations to the existing worker.

    Completion here means the declared pre-approval checks passed. It never
    claims plugin deployment, Unity startup, automatic watching or gameplay.
    """
    def __init__(self, *, matrix, compilation, configuration, output_root):
        self.matrix, self.compilation, self.configuration = matrix, compilation, configuration
        self.output_root = Path(output_root)
        self.calls = 0

    def verification_identity(self):
        children = {"matrix": self.matrix.verification_identity(),
                    "compilation": self.compilation.verification_identity(),
                    "configuration": self.configuration.verification_identity()}
        return {"validator_sha256": canonical_hash({"owner": _ref(__file__), "children": children}),
                "inputs_sha256": canonical_hash({key: value["inputs_sha256"] for key, value in children.items()}),
                "environment_sha256": canonical_hash({key: value["environment_sha256"] for key, value in children.items()}),
                "deterministic_reuse_allowed": False}

    def __call__(self, context):
        identity = self.verification_identity()
        self.calls += 1
        scope = canonical_hash(context["model_response"])[0:20]
        destination = self.output_root / scope / ("verification_" + str(self.calls))
        phases = {"full_compilation": {"status": "not_executed"},
                  "configuration": {"status": "not_executed"},
                  "behavior_matrix": {"status": "not_executed"},
                  "runtime": {"status": "not_executed"}, "automatic_liveedit": {"status": "not_executed"}}
        observations, bindings = [], []
        status, owner = "passed", None
        matrix_report = None
        full = self.compilation(context)
        compilation = full.get("changed", full.get("baseline"))
        phases["full_compilation"] = {"status": full["status"], "report_ref": compilation["report_ref"],
            "all_required_files_compiled": compilation.get("all_required_files_compiled", False),
            "baseline_compilation_performed_in_this_call": full.get("baseline_compilation_performed_in_this_call", False)}
        if full["status"] != "passed":
            owner = full.get("failure_owner", "unknown")
            status = "behavior_failed" if owner == "patch_implementation" else "infrastructure_failed"
            observed = {"compilation_status": full["status"], "report_ref": compilation["report_ref"]}
            for label in ("stdout_ref", "stderr_ref"):
                reference = compilation.get(label)
                if reference is not None:
                    if _ref(reference["path"]) != reference:
                        raise ValueError("FULL_COMPILE_DIAGNOSTIC_CHANGED")
                    observed[label.removesuffix("_ref")] = Path(reference["path"]).read_text(encoding="utf-8")[:4096]
            observations.append({"check_id": "full_project_compilation", "input": {
                "materialized_code_identity": context["materialized_code_identity"]},
                "expected": {"status": "passed", "all_required_files_compiled": True}, "observed": observed})
        else:
            config = self.configuration(compilation)
            phases["configuration"] = {"status": config["status"], "report_ref": config["report_ref"],
                "checks_run": len(config["checks"]), "checks_failed": sum(not row["passed"] for row in config["checks"])}
            if config["status"] != "passed":
                status, owner = config["status"], config.get("failure_owner", "unknown")
                observations.extend({"check_id": "configuration." + row["check_id"],
                    "input": {"compiled_assembly_ref": config["built_artifact_ref"], "configuration_report_ref": config["report_ref"]},
                    "expected": row["expected"], "observed": row["observed"]}
                    for row in config["checks"] if not row["passed"])
                if not observations:
                    observations.append({"check_id": "configuration_execution", "input": {},
                        "expected": "Declared configuration checks execute successfully.",
                        "observed": {"status": status, "report_ref": config["report_ref"]}})
            else:
                matrix_report = self.matrix(context)
                status, owner = matrix_report["status"], matrix_report.get("failure_owner")
                observations = deepcopy(matrix_report["observations"])
                bindings = list(matrix_report["owner_binding_ids"])
                phases["behavior_matrix"] = {"status": status, "report_ref": matrix_report["report_ref"],
                    "verification_ref": matrix_report.get("verification_ref"),
                    "verification_summary": matrix_report.get("verification_summary")}
        if owner == "patch_implementation" and matrix_report is None:
            bindings = [row["edit_binding_id"] for row in context["generated_changes"]]
        if self.verification_identity() != identity:
            raise ValueError("COMPLETE_VERIFICATION_IDENTITY_CHANGED")
        report = {"status": status, "failure_owner": owner, "owner_binding_ids": bindings,
            "observations": observations, "validation_results": phases,
            "generated_changes_sha256": context["generated_changes_sha256"],
            "source_snapshot_sha256": context["source_snapshot_sha256"],
            "model_response_sha256": context["model_response"]["output_sha256"],
            "materialized_code_identity": context["materialized_code_identity"],
            "implementation_plan_ref": context["implementation_plan_ref"], "verification_identity": identity,
            "execution_origin": matrix_report.get("execution_origin", "unknown") if matrix_report is not None else "incomplete",
            "verification_summary": (matrix_report.get("verification_summary") if matrix_report is not None else
                                     {"checks": 0, "failed_checks": 0, "executions": 0}),
            "verification_scope": "full_compilation_and_real_configuration_and_original_cold_behavior_matrix_not_runtime"}
        if matrix_report is not None and matrix_report.get("verification_ref") is not None:
            report["verification_ref"] = deepcopy(matrix_report["verification_ref"])
        return {**report, "report_ref": _save(destination / "report.json", report)}


def make_complete_crosshair_evaluator(*, matrix_kwargs, compilation_kwargs, configuration_kwargs,
                                     output_root, baseline_compilation_ref=None):
    """Select via the existing worker factory_ref/factory_name/kwargs contract."""
    run_scope = uuid4().hex[:16]
    parameters = deepcopy(compilation_kwargs)
    if baseline_compilation_ref is None:
        parameters["output_root"] = str(Path(parameters["output_root"]) / run_scope)
    config_parameters = deepcopy(configuration_kwargs)
    config_parameters["output_root"] = str(Path(config_parameters["output_root"]) / run_scope)
    binding = parameters["dependency_binding"]
    if binding.pop("binding_version", None) != "run_local_game_folder_binding_v1":
        raise ValueError("FULL_COMPILE_DEPENDENCY_BINDING_VERSION_INVALID")
    parameters["dependency_binding"] = RunLocalGameFolderBindingV1(**binding)
    compilation = FullProjectCompilationChecker(**parameters)
    if baseline_compilation_ref is not None:
        compilation.adopt_baseline(baseline_compilation_ref)
    return CompleteCrosshairVerification(matrix=CurrentPlanExistingMatrixOracle(**matrix_kwargs),
        compilation=compilation, configuration=ActualCrosshairConfigurationChecker(**config_parameters), output_root=Path(output_root) / run_scope)
