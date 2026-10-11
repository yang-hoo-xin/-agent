"""S4's frozen camera/logging observations through the existing Patch feedback owner."""
from copy import deepcopy
import json
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.domain.full_project_compilation import _ref
from src.mod_agent.model_qualification import read_bound_json


SCOPE = "real_BasePlugin_constructor_ConfigFile_Log_Load_and_production_TickRelay_with_substituted_camera_and_frames_not_Unity_Update_or_game_runtime"
ALLOWED_SOURCE_PATHS = frozenset({"Plugin.cs", "FovController.cs"})


class DisabledWarningEvaluator(CompiledProbeEvaluator):
    error_prefix = "DISABLED_WARNING"
    probe_filename = "s4_camera_probe.dll"
    scope = SCOPE
    trace_name = "validate.disabled_warning"
    patch_failure_phases = {"candidate_contract", "plugin_constructor", "plugin_load", "controlled_tick"}

    def __init__(self, *, compilation, output_root, probe_configuration_ref,
                 case_configuration_ref, assessor_ref):
        self.case_configuration_ref = deepcopy(case_configuration_ref)
        self.assessor_ref = deepcopy(assessor_ref)
        self.contract = read_bound_json(case_configuration_ref)
        if self.contract.get("schema_version") != "s4-fov-disabled-warning-cases.v2":
            raise self.error("CASES_SCHEMA_INVALID")
        cases = self.contract.get("cases")
        if (not isinstance(cases, list) or not cases
                or any(not isinstance(case, dict) or not isinstance(case.get("id"), str)
                       or not case["id"] or Path(case["id"]).name != case["id"]
                       or "/" in case["id"] or "\\" in case["id"] or case["id"] in {".", ".."}
                       or not isinstance(case.get("seed_config"), str)
                       or not isinstance(case.get("actions"), list) for case in cases)
                or len({case["id"] for case in cases}) != len(cases)):
            raise self.error("CASES_INVALID")
        if _ref(assessor_ref["path"]) != self.assessor_ref:
            raise self.error("ASSESSOR_CHANGED")
        # 为什么要有它：平台复用已冻结的实际断言，不能重写一套近似规则或向模型提供验收器源码。
        assessor = ModuleType("_s4_bound_assessor_" + uuid4().hex)
        assessor.__file__ = assessor_ref["path"]
        exec(compile(Path(assessor_ref["path"]).read_bytes(), assessor_ref["path"], "exec", dont_inherit=True), assessor.__dict__)
        if not callable(getattr(assessor, "assess", None)) or not callable(getattr(assessor, "project_observation", None)):
            raise self.error("ASSESSOR_CONTRACT_INVALID")
        self.assessor = assessor
        self.protocol_sources = (__file__, assessor_ref["path"])
        self.protocol_parameters = {"case_configuration_ref": self.case_configuration_ref,
                                    "assessor_ref": self.assessor_ref}
        super().__init__(compilation=compilation, output_root=output_root,
                         probe_configuration_ref=probe_configuration_ref)

    def verification_identity(self):
        if (read_bound_json(self.case_configuration_ref) != self.contract
                or _ref(self.assessor_ref["path"]) != self.assessor_ref):
            raise self.error("CONTRACT_CHANGED")
        return super().verification_identity()

    def __call__(self, context):
        # 为什么要有它：S4公开编辑范围只含两份业务文件，模型不能修改相机替身边界或帧装配入口制造通过。
        checker = self.compilation.checker
        bindings = {row["binding_id"]: row for row in context["implementation_plan"]["binding_registry"]["edit_bindings"]}
        for change in context["generated_changes"]:
            target = (checker.workspace_root / bindings[change["edit_binding_id"]]["canonical_target_path"]).resolve()
            if target.relative_to(checker.source_root).as_posix() not in ALLOWED_SOURCE_PATHS:
                raise self.error("CHANGE_OUTSIDE_PUBLIC_SCOPE")
        return super().__call__(context)

    def case_definitions(self):
        return tuple((case["id"], deepcopy(case)) for case in self.contract["cases"])

    def request_fields(self, case):
        return {"seed_config": case[1]["seed_config"], "actions": deepcopy(case[1]["actions"])}

    def expected(self, case):
        return deepcopy(case[1])

    def assess(self, observed, case, assembly_sha256):
        return self.assessor.assess(observed, case=case[1], assembly_sha256=assembly_sha256)

    def check_observation(self, observed, key):
        result = deepcopy(self.assessor.project_observation(observed, key))
        if isinstance(result, dict):
            # 为什么要有它：一万帧重复Warning仍须完整计数；可逆连续游程仅减少反馈体积，实际断言与原始执行日志不变。
            for name in ("logs", "camera_writes"):
                values = result.get(name)
                if not isinstance(values, list) or len(values) <= 32:
                    continue
                runs = []
                previous_key = None
                for value in values:
                    value_key = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                    if runs and previous_key == value_key:
                        runs[-1]["count"] += 1
                    else:
                        runs.append({"value": value, "count": 1})
                    previous_key = value_key
                compact = {"sequence_encoding": "ordered_runs_v1", "total_items": len(values), "runs": runs,
                           "expansion": "Repeat each run.value run.count times in listed order; concatenate the results."}
                if len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(values, ensure_ascii=False)):
                    result[name] = compact
        return result

    def stable_observation(self, observed):
        return deepcopy(observed)


def make_disabled_warning_evaluator(*, compilation_kwargs, output_root,
                                    probe_configuration_ref, case_configuration_ref, assessor_ref):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / "compile-feedback"))
    return DisabledWarningEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref,
        case_configuration_ref=case_configuration_ref, assessor_ref=assessor_ref)
