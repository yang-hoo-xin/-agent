"""Full compiled SpreadAPI contract with an instrumented downstream game callback."""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.model_qualification import canonical_hash, read_bound_json

FIELDS = ("id", "value", "callback_count", "callback_delta", "exception_type")


def observation_view(row):
    return {key: row.get(key) for key in FIELDS}


class SpreadApiEvaluator(CompiledProbeEvaluator):
    error_prefix = "SPREAD_API"
    probe_filename = "spread_api_probe.dll"
    scope = "full_compilation_and_complete_DLL_SpreadAPI_cold_sequence_with_game_callback_body_skipped_not_game_runtime"
    trace_name = "validate.spread_api"
    patch_failure_phases = {"api_contract", "api_sequence"}
    protocol_sources = (__file__,)

    def __init__(self, *, compilation, output_root, probe_configuration_ref, case_configuration_ref):
        self.case_configuration_ref = deepcopy(case_configuration_ref)
        self.contract = read_bound_json(case_configuration_ref)
        cases = self.contract.get("cases")
        # 为什么要有它：冻结的正常及异常序列共同定义验收，调用者不能遗漏保持状态的动作而仍声称同一套检查。
        if (not isinstance(cases, list) or len(cases) != 9
                or len({row["name"] for row in cases}) != len(cases)
                or any(not row["actions"] or [x["id"] for x in row["actions"]] != [x["id"] for x in row["expected"]]
                       or len({x["id"] for x in row["actions"]}) != len(row["actions"]) for row in cases)
                or sum(len(row["actions"]) for row in cases) != 60):
            raise ValueError("SPREAD_API_CASE_CONTRACT_INVALID")
        self.protocol_parameters = {"case_configuration_ref": self.case_configuration_ref}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def verification_identity(self):
        if read_bound_json(self.case_configuration_ref) != self.contract:
            raise ValueError("SPREAD_API_CASES_CHANGED")
        return super().verification_identity()

    def case_definitions(self):
        return tuple((row["name"], deepcopy(row)) for row in self.contract["cases"])

    def request_fields(self, case):
        return {"actions": deepcopy(case[1]["actions"])}

    def expected(self, case):
        return {"execution_binding": "exact DLL, .NET 6, calibrated real Harmony callback; API methods untouched",
            "sequence_identity": [row["id"] for row in case[1]["actions"]], "initial_value": "1",
            **{row["id"]: deepcopy(row) for row in case[1]["expected"]}}

    def assess(self, observed, case, assembly_sha256):
        rows = observed.get("observations", [])
        actions, expected = case[1]["actions"], case[1]["expected"]
        identity = [row.get("id") for row in rows] == [row["id"] for row in actions]
        results = {"execution_binding": observed.get("status") == "observed"
            and observed.get("assembly_sha256") == assembly_sha256
            and observed.get("protocol") == "spread-api-probe.v1"
            and observed.get("mode") == "real_harmony_callback_prefix"
            and str(observed.get("runtime_version")).startswith("6.")
            and observed.get("callback_calibration_count") == 1
            and observed.get("callback_method") == "AccurateCrosshair.CrosshairPatches.SpreadPatches.UpdateCrosshairSize"
            and observed.get("callback_body_skipped") is True and observed.get("api_methods_instrumented") is False,
            "sequence_identity": identity, "initial_value": observed.get("initial_value") == "1"}
        for index, wanted in enumerate(expected):
            actual = rows[index] if identity else {}
            results[wanted["id"]] = (canonical_hash(observation_view(actual)) == canonical_hash(wanted)
                and actual.get("operation") == actions[index]["operation"] and actual.get("key") == actions[index]["key"]
                and actual.get("argument") == actions[index].get("value"))
        return results

    def check_expectation(self, expected, key):
        return expected[key]

    def check_observation(self, observed, key):
        # 为什么要有它：失败反馈只投影该断言的数据，完整60动作原文留在执行回执，避免重复几十次整份观察耗尽修订上下文。
        if key == "initial_value":
            return observed.get("initial_value")
        if key == "sequence_identity":
            return [row.get("id") for row in observed.get("observations", [])]
        if key == "execution_binding":
            return {name: observed.get(name) for name in ("status", "assembly_sha256", "protocol", "mode",
                "runtime_version", "callback_calibration_count", "callback_method", "callback_body_skipped", "api_methods_instrumented")}
        rows = [row for row in observed.get("observations", []) if row.get("id") == key]
        return observation_view(rows[0]) if len(rows) == 1 else {"missing_or_duplicate_step": key}

    def stable_observation(self, observed):
        if isinstance(observed, dict):
            return {key: value for key, value in observed.items() if key != "assembly_sha256"}
        return observed


def make_spread_api_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, case_configuration_ref):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters,
        output_root=str(Path(output_root) / scope / "compilation-feedback"))
    return SpreadApiEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref, case_configuration_ref=case_configuration_ref)
