"""S2 cold-entry checks using the real compiled plugin and real ConfigFile."""
import configparser
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from src.mod_agent.domain.compilation_feedback import make_compilation_feedback
from src.mod_agent.domain.compiled_probe_evaluator import CompiledProbeEvaluator
from src.mod_agent.model_qualification import read_bound_json


def assess_hud_size(observed, *, case, assembly_sha256):
    rows = observed.get("entries", [])
    valid_rows = isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
    entries = {(row.get("section"), row.get("key")): row for row in rows} if valid_rows else {}
    others = [{"section": "HUD", "key": key, "value": value, "default_value": default, "value_type": kind}
        for key, value, default, kind in (("ShowLabel", case["show_label"], True, "System.Boolean"),
            ("Caption", case["caption"], "Vitals", "System.String"), ("Opacity", case["opacity"], 0.8, "System.Single"))]
    strict = lambda value: json.dumps(value, sort_keys=True, allow_nan=False)
    unchanged = (valid_rows and len(entries) == len(rows) == 4
        and set(entries) == {("HUD", key) for key in ("Size", "ShowLabel", "Caption", "Opacity")}
        and all(strict(entries[("HUD", row["key"])]) == strict(row) for row in others)
        and str(entries[("HUD", "Size")].get("default_value")) == "96")
    retained = True
    if case["unrelated"] is not None:
        try:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(observed.get("saved_config", ""))
            retained = parser.get("Unrelated", "Keep") == case["unrelated"]
        except (configparser.Error, ValueError):
            retained = False
    return {"execution_binding": observed.get("status") == "observed" and observed.get("assembly_sha256") == assembly_sha256
        and observed.get("plugin_load_calls") == 1 and observed.get("plugin_instance_constructor_skipped") is False
        and observed.get("injected_base_properties") == [] and observed.get("configuration_origin") == "BasePlugin_constructor" and observed.get("rendering_sink_replaced") is True
        and observed.get("config_save_called_by_probe") is False,
        "render_call": observed.get("hud_calls") == [{"size_pixels": case["size_pixels"],
            "caption": case["caption"] if case["show_label"] else "", "opacity": case["opacity"]}],
        "other_settings": unchanged, "unrelated_persistence": retained,
        "plugin_identity": observed.get("plugin_identity") == {"guid": "benchmark.gtfo.expeditionhud", "name": "Expedition HUD", "version": "1.2.0"}}


def project_hud_observation(observed, key):
    # 为什么要有它：纠错需要当前检查的实际值，不需重复依赖路径；完整进程stdout仍由execution_ref绑定保存。
    fields = {"execution_binding": ("status", "assembly_sha256", "plugin_load_calls", "plugin_instance_constructor_skipped",
        "injected_base_properties", "configuration_origin", "rendering_sink_replaced", "config_save_called_by_probe"),
        "render_call": ("hud_calls",), "other_settings": ("entries",),
        "unrelated_persistence": ("saved_config",), "plugin_identity": ("plugin_identity",)}
    return {name: deepcopy(observed.get(name)) for name in fields[key]} if key in fields else deepcopy(observed)


class HudSizeEvaluator(CompiledProbeEvaluator):
    error_prefix = "HUD_SIZE"
    probe_filename = "hud_size_probe.dll"
    scope = "real_ConfigFile_and_compiled_Plugin_Load_settings_layout; rendering_sink_replaced; real_constructor; no_chainloader_or_game"
    trace_name = "validate.hud_size"
    patch_failure_phases = {"candidate_contract", "plugin_constructor", "plugin_load"}
    protocol_sources = (__file__,)

    def __init__(self, *, compilation, output_root, probe_configuration_ref, case_configuration_ref):
        self.case_configuration_ref = case_configuration_ref
        self.contract = read_bound_json(case_configuration_ref)
        if self.contract.get("schema_version") != "benchmark-hud-size-cases.v1":
            raise ValueError("HUD_SIZE_CASES_INVALID")
        self.protocol_parameters = {"case_configuration_ref": case_configuration_ref}
        super().__init__(compilation=compilation, output_root=output_root, probe_configuration_ref=probe_configuration_ref)

    def __call__(self, context):
        # 为什么要有它：受测模型只能修改公开约定的业务文件，不能通过改Unity接收端或验收装配契约制造通过。
        checker = self.compilation.checker
        bindings = {row["binding_id"]: row for row in context["implementation_plan"]["binding_registry"]["edit_bindings"]}
        for change in context["generated_changes"]:
            path = (checker.workspace_root / bindings[change["edit_binding_id"]]["canonical_target_path"]).resolve()
            if path.relative_to(checker.source_root).as_posix() not in {"Plugin.cs", "HudSettings.cs", "HudLayout.cs"}:
                raise ValueError("HUD_SIZE_CHANGE_OUTSIDE_PUBLIC_SCOPE")
        return super().__call__(context)

    def case_definitions(self):
        return tuple((case["id"], deepcopy(case)) for case in self.contract["cases"])

    def request_fields(self, case):
        return {"seed_config": case[1]["seed_config"]}

    def expected(self, case):
        return deepcopy(case[1])

    def assess(self, observed, case, assembly_sha256):
        return assess_hud_size(observed, case=case[1], assembly_sha256=assembly_sha256)

    def check_observation(self, observed, key):
        return project_hud_observation(observed, key)

    def stable_observation(self, observed):
        return {key: observed.get(key) for key in ("status", "hud_calls", "entries", "error_type", "message")}


def make_hud_size_evaluator(*, compilation_kwargs, output_root, probe_configuration_ref, case_configuration_ref):
    parameters = deepcopy(compilation_kwargs)
    scope = uuid4().hex[:8]
    parameters["output_root"] = str(Path(parameters["output_root"]) / scope)
    compilation = make_compilation_feedback(compilation_kwargs=parameters, output_root=str(Path(output_root) / scope / "compile-feedback"))
    return HudSizeEvaluator(compilation=compilation, output_root=Path(output_root) / scope / "behavior",
        probe_configuration_ref=probe_configuration_ref, case_configuration_ref=case_configuration_ref)
