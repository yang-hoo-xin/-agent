"""Expose whole-project compiler failures to the existing bounded Patch worker."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from src.mod_agent.build.dependencies import RunLocalGameFolderBindingV1
from src.mod_agent.domain.full_project_compilation import FullProjectCompilationChecker, _ref, _save
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.proposal import dependency_documentation


def _failure_state_observations(observations, source_root):
    """Project compiler-owned execution paths out of failure comparison only."""
    projected = deepcopy(observations)
    roots = {source_root.rstrip("/\\"), source_root.replace("\\", "/").rstrip("/"),
             source_root.replace("/", "\\").rstrip("\\")}
    for observation in projected:
        observed = observation["observed"]
        observed.pop("report_ref", None)
        for diagnostic in observed["diagnostics"]:
            for field in ("file", "message"):
                value = diagnostic.get(field)
                if isinstance(value, str):
                    for root in sorted(roots, key=len, reverse=True):
                        for separator in ("/", "\\"):
                            value = value.replace(root + separator, "<compiled-source>/")
                    diagnostic[field] = value
    return projected


class CompilationFeedback:
    """Compilation acceptance only; gameplay remains an explicit downstream gate."""

    def __init__(self, checker, output_root):
        self.checker = checker
        self.output_root = Path(output_root)
        self._documentation = None

    def verification_identity(self):
        if self._documentation is not None:
            self._documentation.validate()
        child = self.checker.verification_identity()
        return {**child, "validator_sha256": canonical_hash({"owner": _ref(__file__), "checker": child,
                    "documentation_owner": _ref(dependency_documentation.__file__)}),
                "deterministic_reuse_allowed": False}

    def __call__(self, context):
        result = self.checker(context)
        executed = result.get("changed", result["baseline"])
        status = result["status"]
        owner = result.get("failure_owner")
        diagnostics = (executed.get("build_result") or {}).get("diagnostics", [])
        documentation = None
        if owner == "patch_implementation" and any(row.get("code") == "CS1061" for row in diagnostics):
            self._documentation = dependency_documentation.prepare_dependency_documentation(
                workspace_root=self.checker.workspace_root, implementation_plan=context["implementation_plan"],
                compiler_diagnostics=diagnostics)
            if self._documentation is not None:
                documentation = self._documentation.model_view()
        # 为什么要有它：真实编译错误携带同版本依赖的只读说明，模型可据成员证据修复，仍须重新编译验收。
        report = {"status": "passed" if status == "passed" else "behavior_failed" if owner == "patch_implementation" else "infrastructure_failed",
                  "failure_owner": owner,
                  "owner_binding_ids": [row["edit_binding_id"] for row in context["generated_changes"]]
                  if owner == "patch_implementation" else [],
                  "observations": [] if status == "passed" else [{"check_id": "full_project_compilation",
                      "input": {"materialized_code_identity": context["materialized_code_identity"]},
                      "expected": "The complete changed project compiles against the selected dependencies.",
                      "observed": {"status": status, "diagnostics": diagnostics, "report_ref": executed["report_ref"],
                          **({"dependency_documentation": documentation} if documentation is not None else {})}}],
                  "generated_changes_sha256": context["generated_changes_sha256"],
                  "source_snapshot_sha256": context["source_snapshot_sha256"],
                  "materialized_code_identity": context["materialized_code_identity"],
                  "verification_identity": self.verification_identity(), "execution_origin": executed["execution_origin"],
                  "verification_scope": "compilation_only_gameplay_not_verified",
                  "validation_results": {"full_compilation": result, "runtime": {"status": "not_executed"}}}
        source_root = executed.get("isolated_source_root")
        if owner == "patch_implementation" and isinstance(source_root, str) and source_root:
            # 为什么要有它：同一编译失败不能因新验收目录和回执而变成进展；原始诊断与每次物理编译仍保留。
            report["failure_state_observations"] = _failure_state_observations(report["observations"], source_root)
        return {**report, "report_ref": _save(self.output_root / (uuid4().hex + ".json"), report)}


def make_compilation_feedback(*, compilation_kwargs, output_root):
    parameters = deepcopy(compilation_kwargs)
    binding = parameters["dependency_binding"]
    if binding is not None:
        if binding.pop("binding_version", None) != "run_local_game_folder_binding_v1":
            raise ValueError("FULL_COMPILE_DEPENDENCY_BINDING_VERSION_INVALID")
        parameters["dependency_binding"] = RunLocalGameFolderBindingV1(**binding)
    return CompilationFeedback(FullProjectCompilationChecker(**parameters), output_root)
