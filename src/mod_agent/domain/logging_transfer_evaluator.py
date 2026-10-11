"""Cold-DLL oracle for the preselected logging experience-transfer tasks."""
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator, project_config_logging_observation
from src.mod_agent.domain.startup_notice_verification import assess_observation
from src.mod_agent.model_qualification import read_bound_json


def _configuration_entries_equal(actual, expected):
    """Compare exact typed entries by identity, independently of binding order."""
    # 为什么要有它：Config绑定顺序不是配置语义；归一后仍须拒绝重复、缺失、额外键和类型/默认值差异。
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    fields = {"section", "key", "value", "default_value", "value_type"}
    if any(not isinstance(row, dict) or set(row) != fields
           or type(row["section"]) is not str or type(row["key"]) is not str for row in actual):
        return False
    identities = [(row["section"], row["key"]) for row in actual]
    if len(set(identities)) != len(identities):
        return False
    ordered = lambda rows: sorted(rows, key=lambda row: (row["section"], row["key"]))
    try:
        return json.dumps(ordered(actual), sort_keys=True, allow_nan=False) == json.dumps(ordered(expected), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False


def assess_logging_transfer(observed, *, case, defaults, assembly_sha256):
    entries = []
    for name, value in sorted(case["entries"].items()):
        section, key = name.split(".", 1)
        entries.append({"section": section, "key": key, "value": value, "default_value": defaults[name],
                        "value_type": "System.Boolean" if type(value) is bool else "System.String"})
    execution = assess_observation(observed, enabled=True, message="", assembly_sha256=assembly_sha256)["execution_binding"]
    logs = [{"level": row.get("level"), "message": row.get("message")} for row in observed.get("logs", [])]
    return {"execution_binding": execution,
            "configuration": _configuration_entries_equal(observed.get("entries"), entries),
            "logging": logs == case["logs"]}


class LoggingTransferEvaluator(CompiledProbeEvaluator):
    error_prefix = "LOGGING_TRANSFER"
    probe_filename = "bepinex_plugin_probe.dll"
    scope = "cold_Load_real_BepInEx_configuration_and_logging_not_constructor_chainloader_or_game"
    trace_name = "validate.logging_transfer"
    patch_failure_phases = {"plugin_load"}
    protocol_sources = (__file__,)

    def __init__(self, *, compilation, output_root, probe_configuration_ref, preselection_ref, task_id):
        protocol = read_bound_json(preselection_ref)
        tasks = [task for task in protocol["tasks"] if task["task_id"] == task_id]
        if len(tasks) != 1:
            raise ValueError("LOGGING_TRANSFER_TASK_NOT_PRESELECTED")
        self.task = deepcopy(tasks[0])
        self.defaults = next(case["entries"] for case in self.task["cases"] if case["id"] == "fresh")
        self.protocol_parameters = {"preselection_ref": preselection_ref, "task_id": task_id}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def case_definitions(self):
        return tuple((case["id"], case) for case in self.task["cases"])

    def request_fields(self, case):
        return {"seed_config": case[1]["seed_config"]}

    def expected(self, case):
        return {"entries": case[1]["entries"], "defaults": self.defaults, "logs": case[1]["logs"]}

    def assess(self, observed, case, assembly_sha256):
        return assess_logging_transfer(observed, case=case[1], defaults=self.defaults, assembly_sha256=assembly_sha256)

    def check_observation(self, observed, key):
        return project_config_logging_observation(observed, key)

    def stable_observation(self, observed):
        return {key: observed.get(key) for key in ("status", "entries", "logs", "error_type", "message")}


def make_logging_transfer_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, preselection_ref, task_id):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / "compilation-feedback"))
    return LoggingTransferEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref, preselection_ref=preselection_ref, task_id=task_id)
