"""Startup notice reload sequences over the shared compiled-probe execution owner."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from src.mod_agent.domain import startup_notice_verification
from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.model_qualification import read_bound_json


def _entries(state):
    return [
        {"section": "General", "key": "Enabled", "value": state["enabled"],
         "default_value": True, "value_type": "System.Boolean"},
        {"section": "General", "key": "Message", "value": state["message"],
         "default_value": "Ready", "value_type": "System.String"},
    ]


def _logs(values):
    return [{"level": row.get("level"), "message": row.get("message")} for row in values]


def _ordered_entries(rows):
    return sorted(rows, key=lambda row: (row.get("section", ""), row.get("key", "")))


def _same_entries(actual, expected):
    return (isinstance(actual, list) and all(isinstance(row, dict) for row in actual)
            and json.dumps(_ordered_entries(actual), sort_keys=True) == json.dumps(_ordered_entries(expected), sort_keys=True))


def _effective_config_state(entries):
    """Project the two observed effective values; never substitute defaults."""
    if isinstance(entries, list):
        selected = {key: [row for row in entries if isinstance(row, dict)
            and row.get("section") == "General" and row.get("key") == key] for key in ("Enabled", "Message")}
        if all(len(rows) == 1 and "value" in rows[0] for rows in selected.values()):
            return {"General." + key: deepcopy(rows[0]["value"]) for key, rows in selected.items()}
    return {"unavailable_effective_state": True, "raw_entries": deepcopy(entries)}


class StartupNoticeReloadEvaluator(CompiledProbeEvaluator):
    error_prefix = "STARTUP_RELOAD"
    probe_filename = "bepinex_plugin_probe.dll"
    scope = "complete_compilation_cold_Load_and_real_ConfigFile_Reload_not_constructor_chainloader_watcher_or_game"
    trace_name = "validate.startup_notice_reload"
    patch_failure_phases = {"plugin_load", "plugin_reload"}
    protocol_sources = (__file__, startup_notice_verification.__file__)

    def __init__(self, *, compilation, output_root, probe_configuration_ref, case_configuration_ref):
        self.case_configuration_ref = deepcopy(case_configuration_ref)
        self.contract = read_bound_json(case_configuration_ref)
        cases = self.contract.get("cases")
        # 为什么要有它：行为合同须独立冻结，重复场景或动作不能冒充完整执行覆盖。
        if (self.contract.get("schema_version") != "startup-notice-reload-cases.v1"
                or not isinstance(cases, list) or not cases
                or len({row["name"] for row in cases}) != len(cases)
                or any(len({a["id"] for a in row["reload_actions"]}) != len(row["reload_actions"]) for row in cases)):
            raise ValueError("STARTUP_RELOAD_CASES_INVALID")
        self.protocol_parameters = {"case_configuration_ref": self.case_configuration_ref}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def verification_identity(self):
        if read_bound_json(self.case_configuration_ref) != self.contract:
            raise ValueError("STARTUP_RELOAD_CASES_CHANGED")
        return super().verification_identity()

    def case_definitions(self):
        return tuple((row["name"], deepcopy(row)) for row in self.contract["cases"])

    def request_fields(self, case):
        return {"seed_config": case[1]["seed_config"], "reload_actions": [
            {"id": row["id"], "config_text": row["config_text"]} for row in case[1]["reload_actions"]]}

    def expected(self, case):
        data = case[1]
        state = data["initial"]
        initial_logs = ([{"level": "Info", "message": state["message"]}]
                        if state["enabled"] and state["message"].strip() else [])
        result = {
            "initial_binding": "one cold Load with real injected BepInEx Config and Log",
            "initial_configuration": _entries(state), "initial_logging": initial_logs,
            "plugin_identity": self.contract["plugin_identity"],
            "reload_protocol": {"protocol": "bepinex-config-reload-probe.v1", "calls": len(data["reload_actions"])},
            "sequence_identity": [row["id"] for row in data["reload_actions"]],
            "final_observation": "final entries and cumulative logs equal the recorded sequence",
        }
        for action in data["reload_actions"]:
            result[action["id"] + ".configuration"] = _entries(action["expected"])
            result[action["id"] + ".logging"] = action["expected"]["logs"]
            result[action["id"] + ".reload_completed"] = 1
        return result

    def assess(self, observed, case, assembly_sha256):
        data, actions = case[1], case[1]["reload_actions"]
        initial = data["initial"]
        first_view = deepcopy(observed)
        if isinstance(first_view.get("entries"), list) and all(isinstance(row, dict) for row in first_view["entries"]):
            first_view["entries"] = _ordered_entries(first_view["entries"])
        first = startup_notice_verification.assess_observation(first_view, enabled=initial["enabled"],
            message=initial["message"], assembly_sha256=assembly_sha256, suppress_blank_messages=True)
        rows = observed.get("reload_observations", [])
        initial_logs = observed.get("logs", [])
        identity = (isinstance(rows, list) and len(rows) == len(actions)
                    and all(isinstance(row, dict) for row in rows))
        logs_count = len(initial_logs)
        previous = observed.get("entries")
        if identity:
            for index, (row, action) in enumerate(zip(rows, actions), 1):
                # 为什么要有它：每次观察必须来自约定写入与同一实例前态，不能靠截断或移植日志凑成通过。
                identity = identity and (row.get("id") == action["id"]
                    and row.get("config_text") == action["config_text"]
                    and row.get("written_config_sha256") == hashlib.sha256(action["config_text"].encode("utf-8")).hexdigest()
                    and row.get("reload_call_index") == index and row.get("before_entries") == previous
                    and row.get("logs_before") == logs_count and isinstance(row.get("logs"), list)
                    and row.get("logs_after") == logs_count + len(row.get("logs", [])))
                logs_count += len(row.get("logs", []))
                previous = row.get("entries")
        result = {"initial_binding": first["execution_binding"], "initial_configuration": first["configuration"],
            "initial_logging": first["logging"],
            "plugin_identity": observed.get("plugin_identity") == self.contract["plugin_identity"],
            "reload_protocol": observed.get("reload_protocol") == "bepinex-config-reload-probe.v1"
                and observed.get("config_reload_calls") == len(actions)
                and observed.get("config_reloaded_events") == len(actions)
                and observed.get("target_api_methods_instrumented") is False
                and observed.get("file_watcher_started_by_probe") is False,
            "sequence_identity": bool(identity),
            "final_observation": bool(identity and observed.get("final_entries") == previous
                and observed.get("final_logs") == initial_logs + [log for row in rows for log in row["logs"]])}
        for index, action in enumerate(actions):
            row = rows[index] if identity else {}
            result[action["id"] + ".configuration"] = bool(identity and _same_entries(row.get("entries"), _entries(action["expected"])))
            result[action["id"] + ".logging"] = bool(identity and _logs(row.get("logs", [])) == action["expected"]["logs"])
            result[action["id"] + ".reload_completed"] = bool(identity and row.get("config_reloaded_events") == 1)
        return result

    def check_expectation(self, expected, key):
        return expected[key]

    def check_observation(self, observed, key):
        fields = {"initial_configuration": "entries", "initial_logging": "logs", "plugin_identity": "plugin_identity"}
        if key in fields:
            return deepcopy(observed.get(fields[key]))
        if "." in key:
            action_id, field = key.rsplit(".", 1)
            row = next((r for r in observed.get("reload_observations", []) if r.get("id") == action_id), {})
            if field == "logging":
                # 为什么要有它：日志差异必须带真实初态、前后配置和探针适用范围，避免模型凭缺失上下文猜测故障原因。
                return {"id": action_id, **{name: deepcopy(row.get(name)) for name in
                    ("logs", "logs_before", "logs_after", "reload_call_index", "config_reloaded_events")},
                    "initial_effective_state": _effective_config_state(observed.get("entries")),
                    "before_effective_state": _effective_config_state(row.get("before_entries")),
                    "after_effective_state": _effective_config_state(row.get("entries")),
                    "plugin_instance_constructor_skipped": observed.get("plugin_instance_constructor_skipped"),
                    "observation_origin": "actual_probe_inputs_and_observations_not_repair_instructions"}
            return {"id": action_id, **{name: deepcopy(row.get(name)) for name in {
                "configuration": ("entries",), "logging": ("logs", "logs_before", "logs_after"),
                "reload_completed": ("reload_call_index", "config_reloaded_events")}[field]}}
        return {name: deepcopy(observed.get(name)) for name in ("status", "reload_protocol", "config_reload_calls",
            "config_reloaded_events", "plugin_load_calls", "plugin_instance_constructor_skipped",
            "injected_base_properties", "assembly_sha256", "target_api_methods_instrumented", "file_watcher_started_by_probe")}

    def stable_observation(self, observed):
        if isinstance(observed, dict):
            return {key: deepcopy(value) for key, value in observed.items() if key != "assembly_sha256"}
        return deepcopy(observed)


def make_startup_notice_reload_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, case_configuration_ref):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / "compile-feedback"))
    return StartupNoticeReloadEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref, case_configuration_ref=case_configuration_ref)
