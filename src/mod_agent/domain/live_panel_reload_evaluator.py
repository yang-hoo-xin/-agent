"""S5's frozen disk-save/FrameRelay checks through normal bounded Patch feedback."""
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.domain.full_project_compilation import _ref
from src.mod_agent.model_qualification import read_bound_json


SCOPE = "real_BasePlugin_constructor_ConfigFile_Load_disk_writes_and_production_FrameRelay_with_substituted_rendering_and_frames_not_Unity_Update_GUI_or_game_runtime"
ALLOWED_SOURCE_PATHS = frozenset({"Plugin.cs", "LivePanelController.cs"})


class LivePanelReloadEvaluator(CompiledProbeEvaluator):
    error_prefix = "LIVE_PANEL_RELOAD"
    probe_filename = "s5_config_probe.dll"
    scope = SCOPE
    trace_name = "validate.live_panel_reload"
    patch_failure_phases = {"candidate_contract", "plugin_constructor", "plugin_load", "production_frame_relay"}

    def __init__(self, *, compilation, output_root, probe_configuration_ref, case_configuration_ref, assessor_ref):
        self.case_configuration_ref = deepcopy(case_configuration_ref)
        self.assessor_ref = deepcopy(assessor_ref)
        self.contract = read_bound_json(case_configuration_ref)
        if self.contract.get("schema_version") != "s5-behavior-cases.v1":
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
        # 为什么要有它：平台执行已公布的原始断言，不以显式 Reload 或重写 oracle 代替真实保存检测。
        assessor = ModuleType("_s5_bound_assessor_" + uuid4().hex)
        assessor.__file__ = assessor_ref["path"]
        exec(compile(Path(assessor_ref["path"]).read_bytes(), assessor_ref["path"], "exec", dont_inherit=True), assessor.__dict__)
        if not callable(getattr(assessor, "assess", None)) or not callable(getattr(assessor, "project_observation", None)):
            raise self.error("ASSESSOR_CONTRACT_INVALID")
        self.assessor = assessor
        self.protocol_sources = (__file__, assessor_ref["path"])
        self.protocol_parameters = {"case_configuration_ref": self.case_configuration_ref, "assessor_ref": self.assessor_ref}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def verification_identity(self):
        if (read_bound_json(self.case_configuration_ref) != self.contract
                or _ref(self.assessor_ref["path"]) != self.assessor_ref):
            raise self.error("CONTRACT_CHANGED")
        return super().verification_identity()

    def __call__(self, context):
        # 为什么要有它：公开范围只含两份业务源码，修改帧/渲染替身或工程依赖不能被当成任务修复。
        checker = self.compilation.checker
        bindings = {row["binding_id"]: row for row in context["implementation_plan"]["binding_registry"]["edit_bindings"]}
        for change in context["generated_changes"]:
            target = (checker.workspace_root / bindings[change["edit_binding_id"]]["canonical_target_path"]).resolve()
            if not target.is_relative_to(checker.source_root) or target.relative_to(checker.source_root).as_posix() not in ALLOWED_SOURCE_PATHS:
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
        return deepcopy(self.assessor.project_observation(observed, key))

    def stable_observation(self, observed):
        return deepcopy(observed)


def make_live_panel_reload_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, case_configuration_ref, assessor_ref):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters, output_root=str(Path(output_root) / scope / "compile-feedback"))
    return LivePanelReloadEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref, case_configuration_ref=case_configuration_ref, assessor_ref=assessor_ref)
