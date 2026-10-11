"""Startup-notice contract over the shared compiled-probe evaluator."""
from copy import deepcopy
from pathlib import Path
import subprocess as subprocess
from uuid import uuid4

from src.mod_agent.domain import startup_notice_verification as assessment
from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator, project_config_logging_observation
from src.mod_agent.domain.compilation_feedback import make_compilation_feedback

BLANK_CASES = (
    ("stored_empty", True, "", "[General]\nEnabled = true\nMessage =\n"),
    ("stored_whitespace", True, "", "[General]\nEnabled = true\nMessage =   \t  \n"),
)
SCOPE = "full_compilation_and_cold_Load_with_injected_BasePlugin_config_and_logging_not_constructor_chainloader_or_game_runtime"


class StartupNoticeEvaluator(CompiledProbeEvaluator):
    error_prefix = "STARTUP_NOTICE"
    probe_filename = "bepinex_plugin_probe.dll"
    scope = SCOPE
    trace_name = "validate.startup_notice"
    patch_failure_phases = {"plugin_load"}
    protocol_sources = (__file__, assessment.__file__)

    def __init__(self, *, compilation, output_root, probe_configuration_ref, suppress_blank_messages=False):
        if type(suppress_blank_messages) is not bool:
            raise ValueError("STARTUP_NOTICE_BOOLEAN_SUPPRESSION_REQUIRED")
        self.suppress_blank_messages = suppress_blank_messages
        self.protocol_parameters = {"suppress_blank_messages": suppress_blank_messages}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def case_definitions(self):
        return assessment.CASES + (BLANK_CASES if self.suppress_blank_messages else ())

    def request_fields(self, case):
        return {"seed_config": case[3]}

    def expected(self, case):
        _, enabled, message, _ = case
        return {"enabled": enabled, "message": message,
            "logs": [{"level": "Info", "message": message}] if enabled and (
                not self.suppress_blank_messages or bool(message.strip())) else [],
            "default_enabled": True, "default_message": "Ready"}

    def assess(self, observed, case, assembly_sha256):
        return assessment.assess_observation(observed, enabled=case[1], message=case[2],
            assembly_sha256=assembly_sha256, suppress_blank_messages=self.suppress_blank_messages)

    def check_observation(self, observed, key):
        return project_config_logging_observation(observed, key)

    def stable_observation(self, observed):
        return {key: observed.get(key) for key in ("status", "entries", "logs", "error_type", "message")}


def make_startup_notice_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, suppress_blank_messages=False):
    parameters = deepcopy(compilation_kwargs)
    # 为什么要有它：32位目录令真实Windows编译产物路径达到260字符；短隔离名保留独占写入并避免该工具链限制。
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / "compilation-feedback"))
    return StartupNoticeEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref, suppress_blank_messages=suppress_blank_messages)
