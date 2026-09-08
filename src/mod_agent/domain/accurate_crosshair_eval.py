"""Independent fixed-task oracles over real AccurateCrosshair source.

The C# code under test is supplied by the existing exact materializer. These
programs contain assertions and dependency doubles, never a replacement Mod.
They establish local behavior only, not Unity or GTFO Runtime.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.model_qualification import canonical_hash, read_bound_json

CONFIG_CASE = "accurate-crosshair-recoil-default-off"
API_CASE = "accurate-crosshair-spread-api-input-validation"
CONFIG_SOURCES = ("AccurateCrosshair/Configuration.cs", "AccurateCrosshair/CrosshairPatches/FirstShotType.cs")
API_SOURCES = ("AccurateCrosshair/API/SpreadAPI.cs",)
CONFIG_CHECKS = ("fresh.recoil_default_false", "fresh.other_defaults_preserved", "fresh.exact_configuration_keys",
                 "existing_true.explicit_value_preserved", "existing_false.explicit_value_preserved")
API_VALID_CHECKS = ("valid.product", "valid.replacement", "valid.removal", "valid.no_change_no_callback", "valid.zero_allowed")
API_INVALID_VALUES = ("negative", "nan", "positive_infinity", "negative_infinity")
API_CHECKS = (*API_VALID_CHECKS, *(f"{case}.{check}" for case in API_INVALID_VALUES
    for check in ("rejected", "state_preserved", "callbacks_preserved")))

_COMMON = '''using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Globalization;
static class Checks {
    public static readonly List<object> Rows = new();
    public static void Add(string name, bool passed, object expected, object actual) {
        Rows.Add(new {check=name, passed, expected, actual});
    }
    public static void Print() => Console.WriteLine(JsonSerializer.Serialize(Rows));
}
'''
_CONFIG_DOUBLES = '''using System;
using System.Collections.Generic;
namespace BepInEx { public static class Paths { public static string ConfigPath = "."; } }
namespace BepInEx.Configuration {
    public sealed class ConfigEntry<T> {
        public T Value;
        public object BoxedValue { get => Value!; set => Value = (T)value; }
        public ConfigEntry(T value) { Value = value; }
    }
    public sealed class ConfigFile {
        public static bool? RecoilOverride;
        public static readonly Dictionary<string, object> Entries = new();
        public ConfigFile(string path, bool saveOnInit) { }
        public ConfigEntry<T> Bind<T>(string section, string key, T value, string description) {
            if (key == "Follow Recoil" && RecoilOverride.HasValue) value = (T)(object)RecoilOverride.Value;
            var result = new ConfigEntry<T>(value); Entries[section + "/" + key] = result; return result;
        }
        public dynamic this[string section, string key] => Entries[section + "/" + key];
        public void Reload() { }
    }
}
namespace GTFO.API.Utilities {
    public sealed class LiveEditEventArgs { }
    public sealed class LiveEditListener { public event Action<LiveEditEventArgs>? FileChanged; }
    public static class LiveEdit {
        public static LiveEditListener CreateListener(string root, string file, bool recursive) => new();
    }
}
namespace AccurateCrosshair { internal static class Loader { public const string MODNAME = "AccurateCrosshair"; } }
'''
_CONFIG_PROGRAM = '''static class Program {
    static void Main(string[] args) {
        string mode = args[0];
        if (mode != "fresh") BepInEx.Configuration.ConfigFile.RecoilOverride = mode == "existing_true";
        bool recoil = AccurateCrosshair.Configuration.FollowsRecoil;
        if (mode == "fresh") {
            Checks.Add("fresh.recoil_default_false", !recoil, false, recoil);
            bool unchanged = AccurateCrosshair.Configuration.FirstShotType == AccurateCrosshair.CrosshairPatches.FirstShotType.Inner
                && AccurateCrosshair.Configuration.FirstShotMinDelay == 0.15f && !AccurateCrosshair.Configuration.PopEnabled
                && AccurateCrosshair.Configuration.MinSize == 10f && AccurateCrosshair.Configuration.SpeedScalar == 1f;
            Checks.Add("fresh.other_defaults_preserved", unchanged,
                new {firstShot="Inner", minDelay=0.15f, pop=false, minSize=10f, resizeModifier=1f},
                new {firstShot=AccurateCrosshair.Configuration.FirstShotType.ToString(),
                    minDelay=AccurateCrosshair.Configuration.FirstShotMinDelay, pop=AccurateCrosshair.Configuration.PopEnabled,
                    minSize=AccurateCrosshair.Configuration.MinSize, resizeModifier=AccurateCrosshair.Configuration.SpeedScalar});
            string[] expected = {"Follow Recoil", "First Shot Display Mode", "First Shot Min Delay", "Pop Enabled", "Minimum Size", "Resize Modifier"};
            var actual = BepInEx.Configuration.ConfigFile.Entries.Keys.OrderBy(x => x).ToArray();
            var expectedKeys = expected.Select(x => "General Settings/" + x).OrderBy(x => x).ToArray();
            bool same = expectedKeys.SequenceEqual(actual);
            Checks.Add("fresh.exact_configuration_keys", same, expectedKeys, actual);
        } else {
            bool expected = mode == "existing_true";
            Checks.Add(mode + ".explicit_value_preserved", recoil == expected, expected, recoil);
        }
        Checks.Print();
    }
}
'''
_API_DOUBLES = '''namespace AccurateCrosshair.CrosshairPatches {
    internal static class SpreadPatches { public static int Calls; public static void UpdateCrosshairSize() { Calls++; } }
}
'''
_API_PROGRAM = '''static class Program {
    static void Main(string[] args) {
        string mode = args[0];
        if (mode == "valid") {
            AccurateCrosshair.API.SpreadAPI.SetModifier("a", 2f);
            AccurateCrosshair.API.SpreadAPI.SetModifier("b", 3f);
            Check("valid.product", 6f, 2);
            AccurateCrosshair.API.SpreadAPI.SetModifier("a", 0.5f);
            Check("valid.replacement", 1.5f, 3);
            AccurateCrosshair.API.SpreadAPI.RemoveModifier("b");
            Check("valid.removal", 0.5f, 4);
            AccurateCrosshair.API.SpreadAPI.RemoveModifier("absent");
            Check("valid.no_change_no_callback", 0.5f, 4);
            AccurateCrosshair.API.SpreadAPI.SetModifier("a", 0f);
            Check("valid.zero_allowed", 0f, 5);
        } else {
            AccurateCrosshair.API.SpreadAPI.SetModifier("a", 2f);
            float value = mode switch {"negative" => -1f, "nan" => float.NaN,
                "positive_infinity" => float.PositiveInfinity, _ => float.NegativeInfinity};
            bool rejected = false;
            string exceptionType = "none";
            try { AccurateCrosshair.API.SpreadAPI.SetModifier("a", value); }
            catch (ArgumentOutOfRangeException error) { rejected = true; exceptionType = error.GetType().FullName!; }
            catch (Exception error) { exceptionType = error.GetType().FullName!; }
            Checks.Add(mode + ".rejected", rejected, "System.ArgumentOutOfRangeException", exceptionType);
            Checks.Add(mode + ".state_preserved", AccurateCrosshair.API.SpreadAPI.SpreadModifier == 2f,
                "2", AccurateCrosshair.API.SpreadAPI.SpreadModifier.ToString(CultureInfo.InvariantCulture));
            Checks.Add(mode + ".callbacks_preserved", AccurateCrosshair.CrosshairPatches.SpreadPatches.Calls == 1,
                1, AccurateCrosshair.CrosshairPatches.SpreadPatches.Calls);
        }
        Checks.Print();
    }
    static void Check(string name, float expected, int callbacks) {
        Checks.Add(name, AccurateCrosshair.API.SpreadAPI.SpreadModifier == expected
            && AccurateCrosshair.CrosshairPatches.SpreadPatches.Calls == callbacks,
            new {modifier=expected, callbacks}, new {modifier=AccurateCrosshair.API.SpreadAPI.SpreadModifier,
                callbacks=AccurateCrosshair.CrosshairPatches.SpreadPatches.Calls});
    }
}
'''


def _reference(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _save(path, value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
    return _reference(path)


def _response_scope(context):
    path = context["model_response"].get("path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError("PATCH_EVAL_RESPONSE_LOCATION_REQUIRED")
    return canonical_hash({"model_response_path": path})[:20]


def _dotnet_identity():
    executable = shutil.which("dotnet")
    if not executable:
        raise ValueError("PATCH_EVAL_DOTNET_UNAVAILABLE")
    root = Path(executable).resolve().parent
    compiler = root / "sdk/7.0.401/Roslyn/bincore/csc.dll"
    references = sorted((root / "packs/Microsoft.NETCore.App.Ref/7.0.11/ref/net7.0").glob("*.dll"))
    runtime = sorted((root / "shared/Microsoft.NETCore.App/7.0.11").glob("*.dll"))
    if not compiler.is_file() or not references or not runtime:
        raise ValueError("PATCH_EVAL_FIXED_NET7_TOOLCHAIN_UNAVAILABLE")
    return {"executable": _reference(executable), "compiler": _reference(compiler),
            "references": [_reference(path) for path in references], "runtime": [_reference(path) for path in runtime],
            "target_framework": "net7.0", "scope": "listed_dotnet_toolchain_and_dependency_doubles_not_full_OS_or_game_runtime"}


class AccurateCrosshairTaskOracle:
    def __init__(self, *, case_id, workspace_root, implementation_plan, output_root, source_prefix=""):
        if case_id not in {CONFIG_CASE, API_CASE}:
            raise ValueError("PATCH_EVAL_CASE_UNSUPPORTED")
        self.case_id, self.workspace_root = case_id, Path(workspace_root).resolve(strict=True)
        self.plan, self.output_root = implementation_plan, Path(output_root).resolve()
        if (not isinstance(source_prefix, str) or "\\" in source_prefix
                or PurePosixPath(source_prefix).is_absolute() or ".." in PurePosixPath(source_prefix).parts
                or ":" in source_prefix):
            raise ValueError("PATCH_EVAL_SOURCE_PREFIX_INVALID")
        selected_sources = CONFIG_SOURCES if case_id == CONFIG_CASE else API_SOURCES
        self.sources = tuple((PurePosixPath(source_prefix) / name).as_posix() for name in selected_sources)
        if any(not (self.workspace_root / name).resolve().is_relative_to(self.workspace_root) for name in self.sources):
            raise ValueError("PATCH_EVAL_SOURCE_OUTSIDE_WORKSPACE")
        self.expected_check_ids = CONFIG_CHECKS if case_id == CONFIG_CASE else API_CHECKS
        self.environment = _dotnet_identity()
        self.source_hashes = {name: hashlib.sha256((self.workspace_root / name).read_bytes()).hexdigest()
                              for name in self.sources}
        self.calls = 0

    def verification_identity(self):
        if _dotnet_identity() != self.environment:
            raise ValueError("PATCH_EVAL_ENVIRONMENT_CHANGED")
        current = {name: hashlib.sha256((self.workspace_root / name).read_bytes()).hexdigest()
                   for name in self.sources}
        if current != self.source_hashes:
            raise ValueError("PATCH_EVAL_BASELINE_CHANGED")
        return {"validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "inputs_sha256": canonical_hash({"case_id": self.case_id, "checks": self.expected_check_ids,
                                                 "sources": self.source_hashes}),
                "environment_sha256": canonical_hash(self.environment), "deterministic_reuse_allowed": False}

    def _run_sources(self, sources):
        modes = ("fresh", "existing_true", "existing_false") if self.case_id == CONFIG_CASE else ("valid", *API_INVALID_VALUES)
        checks = []
        # Compilation happens only in a fresh short temporary directory; never in the Mod tree.
        with tempfile.TemporaryDirectory(prefix="ace-") as directory:
            root = Path(directory).resolve()
            root.relative_to(Path(tempfile.gettempdir()).resolve())
            (root / "Program.cs").write_text(_COMMON + (_CONFIG_PROGRAM if self.case_id == CONFIG_CASE else _API_PROGRAM), encoding="utf-8")
            (root / "ExternalDoubles.cs").write_text(_CONFIG_DOUBLES if self.case_id == CONFIG_CASE else _API_DOUBLES, encoding="utf-8")
            for index, name in enumerate(self.sources):
                (root / f"Source{index}.cs").write_bytes(sources[name])
            executable = self.environment["executable"]["path"]
            env = {**os.environ, "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1"}
            # Reuse the established direct C# compiler path; no NuGet configuration or restore is consulted.
            arguments = ["-nologo", "-target:exe", "-langversion:11.0", "-nullable:enable", '-out:"' + str(root / "Harness.dll") + '"']
            arguments.extend('-r:"' + ref["path"] + '"' for ref in self.environment["references"])
            arguments.extend('"' + str(path) + '"' for path in sorted(root.glob("*.cs")))
            response_file = root / "compiler.rsp"
            response_file.write_text("\n".join(arguments), encoding="utf-8")
            build = subprocess.run([executable, self.environment["compiler"]["path"], "@" + str(response_file)],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
            if build.returncode:
                raise ValueError("PATCH_EVAL_HARNESS_COMPILE_FAILED: " + build.stdout[-3000:] + build.stderr[-1000:])
            (root / "Harness.runtimeconfig.json").write_text(json.dumps({"runtimeOptions": {
                "tfm": "net7.0", "framework": {"name": "Microsoft.NETCore.App", "version": "7.0.11"},
                "rollForward": "Disable"}}), encoding="utf-8")
            for mode in modes:
                run = subprocess.run([executable, str(root / "Harness.dll"), mode],
                    cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=20)
                if run.returncode:
                    raise ValueError("PATCH_EVAL_PROCESS_FAILED: " + run.stderr[-1000:])
                checks.extend({**row, "input": {"scenario": mode}} for row in json.loads(run.stdout))
        if tuple(row["check"] for row in checks) != self.expected_check_ids:
            raise ValueError("PATCH_EVAL_CHECK_SET_CHANGED")
        return {"checks": checks, "failures": [row for row in checks if not row["passed"]], "executions": len(modes)}

    def verify_baseline(self):
        """Measure the unchanged input; this is never a model trial or successful repair."""
        self.verification_identity()
        result = self._run_sources({name: (self.workspace_root / name).read_bytes() for name in self.sources})
        return {**result, "case_id": self.case_id, "execution_origin": "executed",
                "input_kind": "unchanged_baseline", "model_calls": 0,
                "verification_identity": self.verification_identity()}

    def __call__(self, context):
        return self._evaluate(context, self.plan)

    def _evaluate(self, context, plan, *, plan_ref=None):
        identity = self.verification_identity()
        output_root = self.output_root / _response_scope(context)
        result = materialize_exact_text_patch(workspace_root=self.workspace_root,
            diff_intent=context["generated_changes"], implementation_plan=plan)
        code = {"baseline_sha256": result.baseline_sha256, "code_sha256": result.code_sha256, "files": sorted(result.files)}
        if context.get("materialized_code_identity") != code:
            raise ValueError("PATCH_EVAL_CODE_IDENTITY_MISMATCH")
        source_values = {name: (self.workspace_root / name).read_bytes() for name in self.sources}
        if not set(result.files).issubset(self.sources):
            raise ValueError("PATCH_EVAL_SOURCE_COVERAGE_INCOMPLETE")
        source_values.update(result.files)
        matrix = self._run_sources(source_values)
        matrix.update(materialized_code_identity=code)
        self.calls += 1
        matrix_ref = _save(output_root / f"matrix-{self.calls:03d}.json", matrix)
        failures = matrix["failures"]
        report = {"status": "behavior_failed" if failures else "passed", "failure_owner": "patch_implementation" if failures else None,
            "owner_binding_ids": sorted({row["edit_binding_id"] for row in context["generated_changes"]}) if failures else [],
            "observations": [{"check_id": row["check"], "input": row["input"],
                              "expected": row["expected"], "observed": row["actual"]} for row in failures],
            "generated_changes_sha256": context["generated_changes_sha256"], "source_snapshot_sha256": context["source_snapshot_sha256"],
            "model_response_sha256": context["model_response"]["output_sha256"], "materialized_code_identity": code,
            "verification_identity": identity, "verification_ref": matrix_ref,
            "verification_summary": {"checks": len(matrix["checks"]), "failed_checks": len(failures), "executions": matrix["executions"]},
            "execution_origin": "executed", "verification_scope": "isolated_real_CSharp_source_with_dependency_doubles_not_GTFO_Runtime"}
        if plan_ref is not None:
            report["implementation_plan_ref"] = dict(plan_ref)
        return {**report, "report_ref": _save(output_root / f"report-{self.calls:03d}.json", report)}


def make_behavior_evaluator(*, case_id, artifact_store_root, workspace_root, plan_ref, output_root, expected_check_ids):
    from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
    ref = ArtifactRef(**plan_ref)
    plan = ArtifactStore(artifact_store_root).read(ref)["data"]
    oracle = AccurateCrosshairTaskOracle(case_id=case_id, workspace_root=workspace_root,
        implementation_plan=plan, output_root=output_root)
    if tuple(expected_check_ids) != oracle.expected_check_ids:
        raise ValueError("PATCH_EVAL_CHECK_SET_MISMATCH")
    return oracle


class CurrentPlanTaskOracle(AccurateCrosshairTaskOracle):
    """Keep fixed task assertions while binding each attempt to its current Plan."""

    def __init__(self, *, case_id, artifact_store_root, workspace_root, output_root, expected_check_ids,
                 source_prefix=""):
        from src.mod_agent.artifacts import ArtifactStore

        super().__init__(case_id=case_id, workspace_root=workspace_root,
                         implementation_plan={}, output_root=output_root, source_prefix=source_prefix)
        if tuple(expected_check_ids) != self.expected_check_ids:
            raise ValueError("PATCH_EVAL_CHECK_SET_MISMATCH")
        self.store = ArtifactStore(artifact_store_root)

    def __call__(self, context):
        from src.mod_agent.artifacts import ArtifactRef
        from src.mod_agent.proposal.patch_agent_loop import (
            PatchAgentLoopPolicy,
            PlanBoundSourceInspector,
        )

        self.verification_identity()
        ref = ArtifactRef(**context["implementation_plan_ref"])
        envelope = self.store.read(ref)
        plan = envelope["data"]
        if (ref.artifact_type != "implementation_plan" or envelope["status"] != "success"
                or plan.get("blocking") or plan != context["implementation_plan"]):
            raise ValueError("PATCH_EVAL_CURRENT_PLAN_MISMATCH")
        inspector = PlanBoundSourceInspector(workspace_root=self.workspace_root,
            implementation_plan=plan, policy=PatchAgentLoopPolicy())
        if inspector.source_snapshot_sha256 != context["source_snapshot_sha256"]:
            raise ValueError("PATCH_EVAL_CURRENT_SOURCE_MISMATCH")
        changes = context["generated_changes"]
        if canonical_hash(changes) != context["generated_changes_sha256"]:
            raise ValueError("PATCH_EVAL_CHANGE_IDENTITY_MISMATCH")
        response = context["model_response"]
        raw = Path(response["path"]).read_bytes()
        if (hashlib.sha256(raw).hexdigest() != response["output_sha256"]
                or len(raw) != response["output_utf8_bytes"]):
            raise ValueError("PATCH_EVAL_RESPONSE_IDENTITY_MISMATCH")
        submitted = json.loads(raw)["changes"]
        by_id = {row["edit_binding_id"]: row for row in submitted}
        planned = {(row["change_id"], row["edit_binding_id"]): row for row in plan["proposed_changes"]}
        if (len(by_id) != len(submitted) or len(changes) != len(submitted)
                or set(by_id) != {row["edit_binding_id"] for row in changes}
                or {(row["change_id"], row["edit_binding_id"]) for row in changes} != set(planned)):
            raise ValueError("PATCH_EVAL_CHANGE_SET_MISMATCH")
        bindings = {row["binding_id"]: row for row in plan["binding_registry"]["edit_bindings"]}
        for change in changes:
            if change["expected_validation"] != planned[(change["change_id"], change["edit_binding_id"])]["expected_validation"]:
                raise ValueError("PATCH_EVAL_VALIDATION_OBLIGATION_CHANGED")
            binding = bindings[change["edit_binding_id"]]
            path = binding["canonical_target_path"]
            if path not in self.sources:
                raise ValueError("PATCH_EVAL_SOURCE_COVERAGE_INCOMPLETE")
            original = (self.workspace_root / path).read_bytes()
            after, returned = change["patch"]["after_text"], by_id[change["edit_binding_id"]]["after_text"]
            if after != returned and not (
                original.startswith(codecs.BOM_UTF8) and after == "\ufeff" + returned
                or not original.startswith(codecs.BOM_UTF8) and returned == "\ufeff" + after
            ):
                raise ValueError("PATCH_EVAL_MODEL_OUTPUT_CHANGED")
        return self._evaluate(context, plan, plan_ref=context["implementation_plan_ref"])


class BoundExistingMatrixOracle:
    """Add prospective identity to an existing unchanged matrix, preserving originals."""
    def __init__(self, *, configuration_ref, identity_refs, expected_check_ids, output_root):
        from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
        self.configuration_ref = configuration_ref
        self.identity_refs, self.expected_check_ids = identity_refs, tuple(expected_check_ids)
        self.output_root, self.calls = Path(output_root).resolve(), 0
        read_bound_json(configuration_ref)
        self.configuration = PatchWorkerConfiguration.load(configuration_ref["path"])
        self.delegate = self.configuration.behavior_evaluator()
        if self.delegate is None:
            raise ValueError("PATCH_EVAL_EXISTING_VALIDATOR_MISSING")
        self.verification_identity()

    def verification_identity(self):
        read_bound_json(self.configuration_ref)
        groups = {}
        for kind in ("validator", "inputs", "environment"):
            selected = self.identity_refs.get(kind)
            if not isinstance(selected, list) or not selected:
                raise ValueError("PATCH_EVAL_IDENTITY_INCOMPLETE")
            for reference in selected:
                if _reference(reference["path"]) != reference:
                    raise ValueError("PATCH_EVAL_REFERENCE_CHANGED")
            groups[kind] = selected
        return {"validator_sha256": canonical_hash({"wrapper": _reference(__file__), "files": groups["validator"]}),
                "inputs_sha256": canonical_hash({"checks": self.expected_check_ids, "files": groups["inputs"]}),
                "environment_sha256": canonical_hash(groups["environment"]), "deterministic_reuse_allowed": False}

    def __call__(self, context):
        from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration

        identity = self.verification_identity()
        scope = _response_scope(context)
        output_root = self.output_root / scope
        configuration = read_bound_json(self.configuration_ref)
        kwargs = configuration["behavior_evaluator"]["kwargs"]
        kwargs["output_root"] = str(Path(kwargs["output_root"]) / scope)
        self.calls += 1
        config_ref = _save(output_root / f"delegate-worker-{self.calls:03d}.json", configuration)
        delegate = PatchWorkerConfiguration.load(config_ref["path"]).behavior_evaluator()
        observed = delegate(context)
        original = read_bound_json(observed["report_ref"])
        if original.get("execution_origin") != "executed":
            return observed
        matrix = read_bound_json(original["verification_ref"])
        if sorted(row["check"] for row in matrix["checks"]) != sorted(self.expected_check_ids):
            raise ValueError("PATCH_EVAL_CHECK_SET_CHANGED")
        if original.get("materialized_code_identity") != context["materialized_code_identity"]:
            raise ValueError("PATCH_EVAL_CODE_IDENTITY_MISMATCH")
        matrix = {**matrix, "materialized_code_identity": context["materialized_code_identity"],
                  "source_matrix_ref": original["verification_ref"]}
        report = {**original, "source_report_ref": observed["report_ref"], "verification_identity": identity,
            "model_response_sha256": context["model_response"]["output_sha256"],
            "verification_ref": _save(output_root / f"matrix-{self.calls:03d}.json", matrix)}
        report.pop("report_ref", None)
        self.verification_identity()
        return {**report, "report_ref": _save(output_root / f"report-{self.calls:03d}.json", report)}


def make_existing_matrix_evaluator(**kwargs):
    return BoundExistingMatrixOracle(**kwargs)
