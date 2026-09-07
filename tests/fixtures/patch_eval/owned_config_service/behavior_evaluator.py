"""One independent disk/process oracle and input preparer; no model runner.

The application sources are new MIT fixture code. The oracle contains behavioral
expectations, never replacement source or a corrected implementation.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evidence.requirement_coverage import (
    default_feature_requirement_projection,
    materialize_requirement_coverage_projection,
)
from src.mod_agent.evidence.requirement_coverage_provider import build_requirement_coverage_pack
from src.mod_agent.evidence.rg_live import RgLiveEvidenceProvider
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.fresh_planning_continuation import (
    PATCH_CONTINUATION_CONTRACT_VERSION,
    PatchContinuationInputV1,
    preflight_patch_continuation,
)
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.planning.implementation_plan import ImplementationPlanner
from src.mod_agent.planning.models import FeatureSpec, stable_feature_id
from src.mod_agent.product_executor import SOURCE_DISCLOSURE_DATA_CLASSES
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy

HERE = Path(__file__).resolve().parent
CASE_ID = "owned-config-max-retries-validation"
APPLICATION = "OwnedConfigService"
INVALID_VALUES = (("negative", "-1"), ("above_limit", "6"), ("fraction", "1.5"),
                  ("string", '"3"'), ("null", "null"), ("boolean", "true"),
                  ("oversized_integer", "99999999999999999999"))
PRESERVATION_CHECKS = ("valid_zero_persists", "valid_middle_persists", "valid_five_persists",
    "unknown_nested_update_roundtrips", "unknown_existing_keys_preserved", "service_name_update_preserved",
    "restart_reads_last_committed_value", "malformed_json_rejection_preserved")
CHANGE_CHECKS = tuple("reject_" + name + "_without_write" for name, _ in INVALID_VALUES)
CHECKS = (*CHANGE_CHECKS, *PRESERVATION_CHECKS)
SEED = {"maxRetries": 2, "serviceName": "node-A", "extension": {"enabled": True, "steps": [1, 2], "note": "fixture"}}
REQUEST = (
    "Add validation to OwnedConfigService's set command for the exact configuration key maxRetries. "
    "Only JSON integer tokens in the inclusive range 0 through 5 are valid. Reject negative, above-range, "
    "fractional, string, null, boolean and oversized integer values with process exit code 2 and JSON status rejected, "
    "before changing any existing configuration-file bytes. Valid updates must still persist and be visible to a "
    "new show process. Preserve serviceName updates, every unrelated and unknown key/value, repeated updates followed "
    "by process restart, and existing rejection of malformed JSON. Do not modify the oracle or its applicability."
)


def reference(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    return reference(path)


def source_files(root):
    root = Path(root).resolve()
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.cs"))}


def _dotnet_identity():
    executable = shutil.which("dotnet")
    if executable is None:
        raise ValueError("OWNED_CONFIG_DOTNET_REQUIRED")
    root = Path(executable).resolve().parent
    compiler = root / "sdk/7.0.401/Roslyn/bincore/csc.dll"
    references = sorted((root / "packs/Microsoft.NETCore.App.Ref/7.0.11/ref/net7.0").glob("*.dll"))
    runtime = sorted((root / "shared/Microsoft.NETCore.App/7.0.11").glob("*.dll"))
    if not compiler.is_file() or not references or not runtime:
        raise ValueError("OWNED_CONFIG_FIXED_NET7_TOOLCHAIN_REQUIRED")
    return {"dotnet": reference(executable), "compiler": reference(compiler),
        "reference_assemblies": [reference(path) for path in references],
        "runtime_assemblies": [reference(path) for path in runtime],
        "scope": "fixed_local_net7_toolchain_not_general_deployment_or_OS_sandbox"}


class OwnedConfigOracle:
    def __init__(self, *, workspace_root, output_root, expected_check_ids=CHECKS):
        if tuple(expected_check_ids) != CHECKS:
            raise ValueError("OWNED_CONFIG_CHECK_SET_CHANGED")
        self.workspace = Path(workspace_root).resolve(strict=True)
        self.output_root = Path(output_root).resolve()
        self.sources = source_files(self.workspace)
        self.toolchain = _dotnet_identity()
        self.evaluations = 0

    def verification_identity(self):
        return {"validator_sha256": reference(__file__)["sha256"],
            "inputs_sha256": canonical_hash({"case_id": CASE_ID, "checks": CHECKS, "invalid_values": INVALID_VALUES,
                "seed": SEED, "source_snapshot": self.sources,
                "project": reference(self.workspace / APPLICATION / (APPLICATION + ".csproj")),
                "package_sources": reference(self.workspace / APPLICATION / "NuGet.Config")}),
            "environment_sha256": canonical_hash(self.toolchain), "deterministic_reuse_allowed": False}

    def _command(self, arguments, cwd, home, *, timeout=20):
        # The program under test receives no provider keys from the parent.
        allowed = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP", "DOTNET_ROOT",
                   "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "APPDATA", "LOCALAPPDATA", "USERPROFILE")
        environment = {name: os.environ[name] for name in allowed if name in os.environ}
        environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1",
                           DOTNET_NOLOGO="1", DOTNET_CLI_HOME=str(home), DOTNET_ADD_GLOBAL_TOOLS_TO_PATH="0")
        process = subprocess.Popen(arguments, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            code, timed_out = process.returncode, False
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            code, timed_out = process.returncode, True
        return {"argv": arguments, "cwd": str(cwd), "process_id": process.pid,
                "exit_code": code, "timed_out": timed_out, "stdout": stdout, "stderr": stderr,
                "environment_keys": sorted(environment)}

    def _evaluate_files(self, run, replacements):
        if source_files(self.workspace) != self.sources:
            raise ValueError("OWNED_CONFIG_SOURCE_CHANGED")
        stage = Path(tempfile.mkdtemp(prefix="ownedcfg-"))
        project = stage / APPLICATION
        shutil.copytree(self.workspace / APPLICATION, project)
        for relative, content in replacements.items():
            target = (stage / relative).resolve()
            if not target.is_relative_to(project) or relative not in self.sources:
                raise ValueError("OWNED_CONFIG_MATERIALIZATION_ESCAPE")
            target.write_bytes(content)
        executable = self.toolchain["dotnet"]["path"]
        binary_root = stage / "bin"
        binary_root.mkdir()
        application = binary_root / (APPLICATION + ".dll")
        # Reuse the established fixed .NET7 compiler/reference approach. No
        # package restore or user NuGet configuration is involved.
        arguments = ["/nologo", "/target:exe", "/langversion:latest", "/nullable:disable", "/deterministic+",
                     '/out:"' + str(application) + '"']
        arguments.extend('/reference:"' + ref["path"] + '"' for ref in self.toolchain["reference_assemblies"])
        arguments.extend('"' + str(path) + '"' for path in sorted(project.rglob("*.cs")))
        response_file = stage / "compile.rsp"
        response_file.write_text("\n".join(arguments), encoding="utf-8")
        commands = [self._command([executable, self.toolchain["compiler"]["path"], "@" + str(response_file)],
                                 project, stage / "cli-home", timeout=60)]
        command_ref = save_once(run / "build-commands.json", commands)
        if any(item["exit_code"] != 0 or item["timed_out"] for item in commands):
            compile_error = not commands[-1]["timed_out"] and "error CS" in commands[-1]["stdout"]
            diagnostic = (commands[-1]["stdout"] + commands[-1]["stderr"]).replace(str(stage), "<isolated-build>")[:4096]
            return {"status": "compiler_failed" if compile_error else "infrastructure_failed", "checks": [], "executions": 0,
                    "compiler_exit_code": commands[-1]["exit_code"], "compiler_diagnostic": diagnostic,
                    "build_commands_ref": command_ref, "build_workspace": str(stage), "application_ref": None}
        runtime_config = binary_root / (APPLICATION + ".runtimeconfig.json")
        runtime_config.write_text(json.dumps({"runtimeOptions": {"tfm": "net7.0",
            "framework": {"name": "Microsoft.NETCore.App", "version": "7.0.11"}}}), encoding="utf-8")
        observations, checks = [], []

        def invoke(arguments):
            item = self._command([executable, str(application), *arguments], stage, stage / "cli-home", timeout=5)
            observations.append(item)
            try:
                item["json"] = json.loads(item["stdout"])
            except ValueError:
                item["json"] = None
            return item

        def fresh(name):
            path = stage / "data" / (name + ".json")
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(json.dumps(SEED, ensure_ascii=False, separators=(",", ":")).encode())
            return path

        for name, value in INVALID_VALUES:
            path = fresh(name)
            before = path.read_bytes()
            observed = invoke(["set", str(path), "maxRetries", value])
            actual = {"exit_code": observed["exit_code"], "stdout_status": (observed["json"] or {}).get("status"),
                      "file_unchanged": path.read_bytes() == before, "timed_out": observed["timed_out"]}
            expected = {"exit_code": 2, "stdout_status": "rejected", "file_unchanged": True, "timed_out": False}
            checks.append({"check": "reject_" + name + "_without_write", "group": "requested_change", "input": {"key": "maxRetries", "json_value": value},
                           "expected": expected, "actual": actual, "passed": actual == expected})
        for name, value in (("zero", 0), ("middle", 3), ("five", 5)):
            path = fresh("valid_" + name)
            updated = invoke(["set", str(path), "maxRetries", str(value)])
            shown = invoke(["show", str(path)])
            expected = {**SEED, "maxRetries": value}
            checks.append({"check": "valid_" + name + "_persists", "group": "preservation", "input": {"key": "maxRetries", "value": value},
                "expected": expected, "actual": shown["json"], "passed": updated["exit_code"] == shown["exit_code"] == 0 and shown["json"] == expected})
        for name, key, value in (("unknown_nested_update_roundtrips", "futurePlugin", {"items": [1, {"flag": True}], "mode": "opaque"}),
                                 ("unknown_existing_keys_preserved", "maxRetries", 4),
                                 ("service_name_update_preserved", "serviceName", "node-B")):
            path = fresh(name)
            updated = invoke(["set", str(path), key, json.dumps(value, separators=(",", ":"))])
            shown = invoke(["show", str(path)])
            expected = {**SEED, key: value}
            checks.append({"check": name, "group": "preservation", "input": {"key": key, "value": value},
                "expected": expected, "actual": shown["json"], "passed": updated["exit_code"] == shown["exit_code"] == 0 and shown["json"] == expected})
        path = fresh("restart")
        first = invoke(["set", str(path), "maxRetries", "0"])
        second = invoke(["set", str(path), "maxRetries", "5"])
        shown = invoke(["show", str(path)])
        expected = {**SEED, "maxRetries": 5}
        checks.append({"check": "restart_reads_last_committed_value", "group": "preservation", "input": {"updates": [0, 5], "read_in_new_process": True},
            "expected": expected, "actual": shown["json"], "passed": first["exit_code"] == second["exit_code"] == shown["exit_code"] == 0 and shown["json"] == expected})
        path = fresh("malformed")
        before = path.read_bytes()
        malformed = invoke(["set", str(path), "maxRetries", "{broken"])
        actual = {"exit_code": malformed["exit_code"], "file_unchanged": path.read_bytes() == before}
        checks.append({"check": "malformed_json_rejection_preserved", "group": "preservation", "input": {"json_value": "{broken"},
            "expected": {"exit_code": 2, "file_unchanged": True}, "actual": actual,
            "passed": actual == {"exit_code": 2, "file_unchanged": True}})
        if tuple(row["check"] for row in checks) != CHECKS:
            raise ValueError("OWNED_CONFIG_CHECK_MATRIX_INCOMPLETE")
        observation_ref = save_once(run / "process-observations.json", observations)
        return {"status": "passed" if all(row["passed"] for row in checks) else "behavior_failed",
                "checks": checks, "executions": len(observations), "build_commands_ref": command_ref,
                "process_observations_ref": observation_ref, "application_ref": reference(application),
                "build_workspace": str(stage), "source_unchanged": source_files(self.workspace) == self.sources,
                "scope": "independent_application_process_and_disk_behavior_not_game_runtime"}

    def verify_baseline(self):
        run = self.output_root / "baseline"
        run.mkdir(parents=True, exist_ok=False)
        matrix = self._evaluate_files(run, {})
        matrix_ref = save_once(run / "matrix.json", matrix)
        failed = [row["check"] for row in matrix["checks"] if not row["passed"]]
        result = {"case_id": CASE_ID, "baseline_status": matrix["status"], "matrix_ref": matrix_ref,
            "expected_change_failures": list(CHANGE_CHECKS), "observed_failures": failed,
            "all_preservation_checks_passed": (tuple(row["check"] for row in matrix["checks"] if row["group"] == "preservation") == PRESERVATION_CHECKS
                and all(row["passed"] for row in matrix["checks"] if row["group"] == "preservation")),
            "expected_failure_signature_observed": failed == list(CHANGE_CHECKS),
            "new_model_calls": 0, "product_apply_performed": False, "corrected_source_supplied": False}
        save_once(run / "baseline-result.json", result)
        return result

    def __call__(self, context):
        self.evaluations += 1
        response_path = context["model_response"].get("path")
        if not isinstance(response_path, str) or not Path(response_path).is_absolute():
            raise ValueError("OWNED_CONFIG_RESPONSE_LOCATION_REQUIRED")
        response_scope = canonical_hash({"model_response_path": response_path})[:20]
        run = self.output_root / response_scope / ("evaluation_" + str(self.evaluations))
        run.mkdir(parents=True, exist_ok=False)
        source_ref = context["model_response"]
        if reference(source_ref["path"])["sha256"] != source_ref["output_sha256"]:
            raise ValueError("OWNED_CONFIG_MODEL_RESPONSE_CHANGED")
        materialized = materialize_exact_text_patch(workspace_root=self.workspace,
            diff_intent=context["generated_changes"], implementation_plan=context["implementation_plan"])
        identity = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256, "files": sorted(materialized.files)}
        if identity != context["materialized_code_identity"]:
            raise ValueError("OWNED_CONFIG_MATERIALIZED_CODE_IDENTITY_MISMATCH")
        matrix = self._evaluate_files(run, materialized.files)
        matrix_ref = save_once(run / "matrix.json", matrix)
        failed = [row for row in matrix["checks"] if not row["passed"]]
        compilation_failed = matrix["status"] == "compiler_failed"
        owner = "environment" if matrix["status"] == "infrastructure_failed" else "patch_implementation" if failed or compilation_failed else None
        observations = [{"check_id": row["check"], "input": row["input"], "expected": row["expected"], "observed": row["actual"]}
                        for row in failed]
        if compilation_failed or owner == "environment":
            observations.append({"check_id": "application_compilation", "input": {"stage": "isolated_csharp_compilation"},
                "expected": {"exit_code": 0}, "observed": {"exit_code": matrix["compiler_exit_code"],
                "diagnostic": matrix["compiler_diagnostic"]}})
        report = {"status": "behavior_failed" if compilation_failed else matrix["status"], "failure_owner": owner,
            "owner_binding_ids": [row["edit_binding_id"] for row in context["generated_changes"]] if failed or compilation_failed else [],
            "observations": observations, "verification_ref": matrix_ref,
            "verification_summary": {"checks": len(matrix["checks"]), "failed_checks": len(failed), "executions": matrix["executions"]},
            "generated_changes_sha256": context["generated_changes_sha256"], "source_snapshot_sha256": context["source_snapshot_sha256"],
            "materialized_code_identity": identity, "verification_identity": self.verification_identity(),
            "execution_origin": "incomplete" if owner == "environment" or compilation_failed else "executed",
            "verification_scope": "owned application with actual disk writes and fresh process observations"}
        report_ref = save_once(run / "report.json", report)
        return {**report, "report_ref": report_ref}


def make_behavior_evaluator(*, workspace_root, output_root, expected_check_ids):
    return OwnedConfigOracle(workspace_root=workspace_root, output_root=output_root, expected_check_ids=expected_check_ids)


def prepare_owned_config_task(*, output_root):
    """Prepare one initial-Patch task, never qualify a model or run a provider."""
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "source"
    shutil.copytree(HERE / "source", workspace)
    store = ArtifactStore(root / "store")
    feature = FeatureSpec(feature_id=stable_feature_id(REQUEST), user_request=REQUEST, target_behavior=REQUEST,
        target_mod=APPLICATION, risk_level="low", acceptance_criteria=(
            "Reject all seven listed invalid maxRetries input classes before changing existing file bytes.",
            "Accept JSON integer tokens 0 through 5 and persist them for a fresh show process.",
            "Preserve unrelated known and unknown configuration values, restart behavior, and malformed-JSON rejection."),
        non_goals=("Do not change the command protocol, oracle, check set or validation applicability.",),
        evidence_requirements=("Current exact application source and its disk/process calling path.",),
        runtime_verification_plan=("Compile and run the fixed owned configuration application disk/process matrix.",))
    feature_ref = store.write(feature_id=feature.feature_id, artifact_type="feature_spec", payload=feature.to_artifact_payload())
    projection = default_feature_requirement_projection(feature.to_artifact_payload())
    for item in projection["requirements"]:
        item["query_leads"] = ["Update", "Read", "Persist", "Main"]
    materialized = materialize_requirement_coverage_projection(feature_data=feature.to_artifact_payload(), request=REQUEST, projection=projection)
    retrieved = RgLiveEvidenceProvider(workspace).collect_query_set(queries=tuple(materialized["queries"]),
        search_root=APPLICATION, max_items=max(32, len(materialized["queries"])))
    targets = [item.evidence_id for item in retrieved.items if item.source_path == APPLICATION + "/JsonConfigStore.cs" and item.symbol == "Update"]
    if len(targets) != 1:
        raise ValueError("OWNED_CONFIG_TARGET_EVIDENCE_AMBIGUOUS")
    findings = {"findings": []}
    for index, item in enumerate(materialized["requirements"], 1):
        deferred = item["role"] == "post_change_acceptance"
        findings["findings"].append({"relation_index": index, "relationship": "missing" if deferred else "support",
            "evidence_ids": [] if deferred else [row.evidence_id for row in retrieved.items],
            "edit_target_evidence_ids": targets if item["role"] == "change" else [],
            "unresolved_gaps": ["Run the independent behavior matrix after generated code."] if deferred else []})
    pack = build_requirement_coverage_pack(query=REQUEST, materialized_projection=materialized, retrieved_pack=retrieved, findings=findings)
    evidence = pack.to_artifact_payload()
    evidence["budget_summary"]["fixture_authorship"] = {"semantic_owner": "explicit_operator_authored_owned_source_task", "model_calls": 0,
                                                         "fresh_model_execution": False, "existing_requirements_already_satisfied": False}
    evidence_ref = store.write(feature_id=feature.feature_id, artifact_type="evidence_pack", payload=evidence, upstream_refs=[feature_ref])
    plan = ImplementationPlanner().build(feature_spec=feature, evidence_pack=evidence,
        formal_requirement_coverage_required=True, planning_target_evidence_ids=tuple(targets))
    if plan.blocking:
        raise ValueError("OWNED_CONFIG_PLANNING_BLOCKED")
    plan_ref = store.write(feature_id=feature.feature_id, artifact_type="implementation_plan", payload=plan.to_artifact_payload(),
                           upstream_refs=[feature_ref, evidence_ref])
    oracle = OwnedConfigOracle(workspace_root=workspace, output_root=root / "verification")
    baseline = oracle.verify_baseline()
    policy = PatchAgentLoopPolicy(max_total_model_turns=5, max_tool_rounds=6, max_observation_bytes=32768,
        require_source_inspection=False, finalize_after_first_observation=False, enable_supporting_reads=True,
        allow_upstream_request=True, allow_batched_reads=True, reuse_covered_source_observations=True)
    configuration = {"schema_version": "patch_worker_configuration_v1", "policy": asdict(policy), "enable_recovery_loop": True,
        "behavior_evaluator": {"factory_ref": reference(__file__), "factory_name": "make_behavior_evaluator",
            "kwargs": {"workspace_root": str(workspace), "output_root": str(root / "verification/model_outputs"), "expected_check_ids": list(CHECKS)}}}
    config_ref = save_once(root / "worker.json", configuration)
    request = PatchContinuationInputV1(contract_version=PATCH_CONTINUATION_CONTRACT_VERSION,
        artifact_store_root=str(store.root), workspace_root=str(workspace), feature_spec_ref=feature_ref,
        evidence_pack_ref=evidence_ref, implementation_plan_ref=plan_ref)
    preflight_patch_continuation(request)
    request_ref = save_once(root / "continuation-input.json", asdict(request))
    disclosure = {"approved": False, "permission_source": "requires_current_task_user_authorization",
        "requested_data_classes": [*SOURCE_DISCLOSURE_DATA_CLASSES, "generated_patch", "verification_feedback"],
        "source_files": source_files(workspace), "source_root": str(workspace), "license_ref": reference(HERE / "LICENSE"),
        "authorship": "new independent fixture code; license metadata does not grant upload permission",
        "excluded_from_model_input": ["oracle implementation", "compiler binaries", "API keys", "other project workspaces"],
        "external_requests_performed": 0}
    disclosure_ref = save_once(root / "source-disclosure-preview.json", disclosure)
    result = {"case_id": CASE_ID, "target_mod": APPLICATION, "distinct_task_count": 1,
        "feature_spec_ref": asdict(feature_ref), "evidence_pack_ref": asdict(evidence_ref), "implementation_plan_ref": asdict(plan_ref),
        "continuation_input_ref": request_ref, "worker_configuration_ref": config_ref,
        "verification_identity": oracle.verification_identity(), "expected_check_ids": list(CHECKS),
        "baseline": baseline, "source_disclosure_preview_ref": disclosure_ref,
        "ready_for_model_screen": baseline["expected_failure_signature_observed"] and baseline["all_preservation_checks_passed"],
        "planning_target_selection": "explicit_operator_authored_fixture", "model_calls": 0,
        "local_and_external_profile_selection": "not_selected_by_preparation", "model_qualification": "not_demonstrated",
        "product_apply_performed": False, "production_entry": "continue-fresh-patch or run_external_patch_continuation"}
    save_once(root / "task.json", result)
    return result
