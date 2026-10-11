"""Publish three authorized answer-free tasks and calibrate their protected judge.

Hidden source variants, checks, expected values and failure observations remain
inside the sealed input and private judge directories. Stdout is aggregate only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_patch_sft_eval import (  # noqa: E402
    OwnedSftOracle,
    _contract,
    _request,
)
from src.libs.llm import ChatResponse  # noqa: E402
from src.mod_agent.evaluation.independent_preparation import (  # noqa: E402
    file_ref,
    write_once,
)
from src.mod_agent.evaluation.patch_task_suite import _checked_profile  # noqa: E402
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch  # noqa: E402
from src.mod_agent.fresh_planning_continuation import preflight_patch_continuation  # noqa: E402
from src.mod_agent.git import GitRepository  # noqa: E402
from src.mod_agent.model_qualification import (  # noqa: E402
    canonical_hash,
    read_bound_json,
    worker_implementation_identity,
)
from src.mod_agent.proposal.patch_agent_loop import (  # noqa: E402
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
)


class PublisherError(RuntimeError):
    def __init__(self, code, stage):
        super().__init__(code)
        self.code = code
        self.stage = stage


def _fail(code, stage):
    raise PublisherError(code, stage)


def _save(path, value):
    return write_once(path, value)


def _find_exact(root, name, sha256):
    direct = root / name
    if direct.is_file() and hashlib.sha256(direct.read_bytes()).hexdigest() == sha256:
        return direct
    matches = []
    for base, _, files in os.walk(root):
        for filename in files:
            if not filename.endswith(".json"):
                continue
            path = Path(base) / filename
            try:
                if hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
                    matches.append(path)
            except OSError:
                continue
    if not matches:
        _fail("PUBLISH_REQUIRED_EXACT_FILE_MISSING", "sealed_identity")
    return sorted(matches)[0]


def _authority_hashes(protocol, metadata):
    values = {"manifest": protocol.get("sealed_manifest_sha256"),
              "toolchain": metadata.get("toolchain_metadata_sha256"),
              "profile": (protocol.get("model") or {}).get("profile_sha256")}
    if any(not isinstance(value, str) or len(value) != 64 for value in values.values()):
        _fail("PUBLISH_PUBLIC_IDENTITY_INCOMPLETE", "public_identity")
    return values


def _source(task, manifest_path):
    recorded = Path(task["source_root"]) / "OwnedTraining/Subject.cs"
    if recorded.is_file():
        return recorded.resolve()
    archived = manifest_path.parent / "tasks" / task["case_id"] / "source/OwnedTraining/Subject.cs"
    if archived.is_file():
        return archived.resolve()
    _fail("PUBLISH_B0_SOURCE_MISSING", "source_identity")


def _response(task, version):
    if version == "C1":
        raw = read_bound_json(task["raw_request_ref"])
        values = [row["content"] for row in raw["messages"]
                  if row["role"] == "assistant" and isinstance(row["content"], str)]
        if len(values) != 1:
            _fail("PUBLISH_C1_RESPONSE_NOT_UNIQUE", "judge_calibration")
        return values[0]
    hidden = read_bound_json(task["hidden_oracle_ref"])
    completion = hidden["completion"]
    if (not isinstance(completion, list) or len(completion) != 1
            or not isinstance(completion[0].get("content"), str)):
        _fail("PUBLISH_C2_RESPONSE_NOT_UNIQUE", "judge_calibration")
    return completion[0]["content"]


def _judge_request(task, response):
    request = _request(read_bound_json(task["continuation_input_ref"]))
    admitted, generator, contract = _contract(request)
    generated = generator.materialize_prepared_native(
        contract, ChatResponse(content=response, model="protected_calibration_not_model_run"))
    materialized = materialize_exact_text_patch(
        workspace_root=request.workspace_root, diff_intent=generated.changes,
        implementation_plan=admitted.implementation_plan)
    inspector = PlanBoundSourceInspector(
        workspace_root=request.workspace_root, implementation_plan=admitted.implementation_plan,
        policy=PatchAgentLoopPolicy())
    identity = {
        "baseline_sha256": materialized.baseline_sha256,
        "code_sha256": materialized.code_sha256,
        "files": sorted(materialized.files),
    }
    return {"generated_changes": generated.changes,
            "implementation_plan": admitted.implementation_plan,
            "generated_changes_sha256": canonical_hash(generated.changes),
            "source_snapshot_sha256": inspector.source_snapshot_sha256,
            "materialized_code_identity": identity,
            "model_response": {"output_sha256": hashlib.sha256(response.encode()).hexdigest()}}


def _compile_b0(source, tools, root):
    root.mkdir(parents=True, exist_ok=False)
    assembly, response = root / "B0.dll", root / "compile.rsp"
    response.write_text("\n".join(["/nologo", "/target:library", "/langversion:latest",
        f'/out:"{assembly}"', *(f'/r:"{item["path"]}"' for item in tools["references"]),
        f'"{source}"']), encoding="utf-8")
    environment = {name: os.environ[name] for name in
                   ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP")
                   if name in os.environ}
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    result = subprocess.run([tools["dotnet"]["path"], tools["compiler"]["path"], "@" + str(response)],
        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=40)
    return {"exit_code": result.returncode,
            "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
            "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
            "assembly_sha256": file_ref(assembly)["sha256"] if assembly.is_file() else None,
            "scope": "B0 library compilation only; not product Build or behavior verification"}


def _archive_private_tree(root, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            _fail("PUBLISH_PRIVATE_ARCHIVE_INVALID", "judge_calibration")
    return file_ref(destination)


def _admit_inputs(*, independent_root, output_root, repository_root):
    independent_root = Path(independent_root).resolve(strict=True)
    output_root = Path(output_root).resolve()
    repository_root = Path(repository_root).resolve(strict=True)
    if output_root.exists():
        _fail("PUBLISH_OUTPUT_ALREADY_EXISTS", "output_admission")
    protocol_path, metadata_path = independent_root / "protocol.json", independent_root / "metadata.json"
    protocol, metadata = json.loads(protocol_path.read_text()), json.loads(metadata_path.read_text())
    if file_ref(protocol_path)["sha256"] != "ba3b65ce5326c7b8be81ed25518a4e759dd13abb2abde730704a86bee1cbeb77":
        _fail("PUBLISH_PROTOCOL_CHANGED", "public_identity")
    if file_ref(metadata_path)["sha256"] != "5122ddac6c956750e9093d1b72585c10638aba2a14b3e9566d3a4c6e19d1e099":
        _fail("PUBLISH_METADATA_CHANGED", "public_identity")
    sealed = independent_root / "sealed"
    authority = _authority_hashes(protocol, metadata)
    manifest_path = _find_exact(sealed, "manifest.json", authority["manifest"])
    toolchain_path = _find_exact(sealed, "toolchain.json", authority["toolchain"])
    profile_path = _find_exact(sealed, "profile.json", authority["profile"])
    manifest = json.loads(manifest_path.read_text())
    profile = _checked_profile(json.loads(profile_path.read_text()))
    if profile["model"] != protocol["model"]["name"]:
        _fail("PUBLISH_PROFILE_MODEL_CHANGED", "profile_identity")
    selected = []
    for meta in metadata["tasks"]:
        matches = [task for task in manifest["tasks"] if task["case_id"] == meta["task_id"]
                   and task["family_id"] == meta["family_id"]]
        if len(matches) != 1:
            _fail("PUBLISH_CASE_MAPPING_NOT_UNIQUE", "task_mapping")
        task = matches[0]
        source = _source(task, manifest_path)
        if hashlib.sha256(source.read_bytes()).hexdigest() != meta["baseline_source_sha256"]:
            _fail("PUBLISH_B0_IDENTITY_CHANGED", "source_identity")
        admitted = preflight_patch_continuation(_request(read_bound_json(task["continuation_input_ref"])))
        if hashlib.sha256(admitted.feature_spec["user_request"].encode()).hexdigest() != meta["requirements_sha256"]:
            _fail("PUBLISH_REQUIREMENTS_IDENTITY_CHANGED", "request_identity")
        selected.append((meta, task, source, admitted))
    return {"independent_root": independent_root, "output_root": output_root,
        "repository_root": repository_root, "protocol_path": protocol_path,
        "metadata_path": metadata_path, "protocol": protocol, "metadata": metadata,
        "manifest_path": manifest_path, "manifest": manifest, "toolchain_path": toolchain_path,
        "profile_path": profile_path, "profile": profile, "selected": selected}


def preflight_publish(*, independent_root, output_root, repository_root):
    admitted = _admit_inputs(independent_root=independent_root, output_root=output_root,
                             repository_root=repository_root)
    return {"status": "ready_to_write", "stage": "output_admission",
        "output_root": str(admitted["output_root"]),
        "sealed_manifest_sha256": file_ref(admitted["manifest_path"])["sha256"],
        "toolchain_file_sha256": file_ref(admitted["toolchain_path"])["sha256"],
        "profile_file_sha256": file_ref(admitted["profile_path"])["sha256"],
        "tasks": [{"task_id": meta["task_id"], "case_id": task["case_id"],
                   "family_id": meta["family_id"], "source_identity_sha256": meta["baseline_source_sha256"],
                   "requirements_identity_sha256": meta["requirements_sha256"]}
                  for meta, task, _, _ in admitted["selected"]],
        "writes_performed": False, "model_calls": 0}


def publish(*, independent_root, output_root, repository_root):
    admitted_inputs = _admit_inputs(independent_root=independent_root, output_root=output_root,
                                    repository_root=repository_root)
    independent_root = admitted_inputs["independent_root"]
    output_root = admitted_inputs["output_root"]
    repository_root = admitted_inputs["repository_root"]
    protocol_path, metadata_path = admitted_inputs["protocol_path"], admitted_inputs["metadata_path"]
    protocol, metadata = admitted_inputs["protocol"], admitted_inputs["metadata"]
    manifest_path, manifest = admitted_inputs["manifest_path"], admitted_inputs["manifest"]
    toolchain_path, profile_path = admitted_inputs["toolchain_path"], admitted_inputs["profile_path"]
    output_root.mkdir(parents=True)
    public, private = output_root / "public", output_root / "protected"
    public.mkdir()
    private.mkdir()
    published_toolchain = public / "toolchain.json"
    published_profile = public / "profile.json"
    shutil.copyfile(toolchain_path, published_toolchain)
    shutil.copyfile(profile_path, published_profile)
    protocol_ref, metadata_ref = file_ref(protocol_path), file_ref(metadata_path)
    inventory = {"protocol_ref": protocol_ref, "metadata_ref": metadata_ref,
        "toolchain_metadata_sha256": metadata["toolchain_metadata_sha256"],
        "model": {"name": protocol["model"]["name"],
                  "profile_sha256": protocol["model"]["profile_sha256"]},
        "tasks": [{"task_id": row["task_id"], "root_cause_family": row["family_id"],
                   "requirements_sha256": row["requirements_sha256"],
                   "input_sha256": row["baseline_source_sha256"],
                   "partition": next(task["split"] for task in manifest["tasks"]
                                     if task["case_id"] == row["task_id"])}
                  for row in metadata["tasks"]]}
    inventory_ref = _save(public / "inventory.json", inventory)
    manifest_ref = file_ref(manifest_path)
    tools = read_bound_json(file_ref(published_toolchain))
    results = []
    for meta, task, source, admitted in admitted_inputs["selected"]:
        feature = admitted.feature_spec
        task_root = public / "tasks" / meta["task_id"]
        task_root.mkdir(parents=True)
        request_ref = _save(task_root / "request.json", {"schema_version": "independent_task_request_v1",
            "task_id": meta["task_id"], "request": feature["user_request"], "target_mod": feature["target_mod"],
            "acceptance_criteria": feature["acceptance_criteria"],
            "preservation_requirements": feature["non_goals"]})
        source_root = task_root / "source"
        (source_root / "OwnedTraining").mkdir(parents=True)
        shutil.copyfile(source, source_root / "OwnedTraining/Subject.cs")
        (source_root / "OwnedTraining.csproj").write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net7.0</TargetFramework>'
            '<OutputType>Library</OutputType><ImplicitUsings>disable</ImplicitUsings>'
            '<Nullable>disable</Nullable></PropertyGroup></Project>\n', encoding="utf-8", newline="\n")
        source_files = [{"relative_path": path.relative_to(source_root).as_posix(),
                         "sha256": file_ref(path)["sha256"]}
                        for path in sorted(source_root.rglob("*")) if path.is_file()]
        compilation_ref = _save(task_root / "B0-compilation.json",
            _compile_b0(source_root / "OwnedTraining/Subject.cs", tools,
                        private / "B0-compilation" / task["case_id"]))
        if read_bound_json(compilation_ref)["exit_code"] != 0:
            _fail("PUBLISH_B0_COMPILATION_FAILED", "B0_compilation")
        release = {"schema_version": "independent_task_release_v1",
            "status": "published_not_authorized_for_execution", "protocol_ref": protocol_ref,
            "metadata_ref": metadata_ref, "task": {"task_id": meta["task_id"],
                "case_id": task["case_id"], "family_id": meta["family_id"], "mode": "initial_patch",
                "request_ref": request_ref, "requirements_identity_sha256": meta["requirements_sha256"],
                "source_root": str(source_root), "source_files": source_files,
                "source_identity_sha256": meta["baseline_source_sha256"]},
            "toolchain_ref": file_ref(published_toolchain), "model_profile_ref": file_ref(published_profile),
            "publisher_attestation": {"answer_free_initial_source_only": True,
                "contains_hidden_tests": False, "contains_reference_repairs": False,
                "contains_failure_observations": False, "model_exposure_prepared": True,
                "execution_authorized": False}}
        release_ref = _save(task_root / "release.json", release)
        short_judge_root = Path(tempfile.mkdtemp(prefix="ije-"))
        judge = OwnedSftOracle(manifest_ref=manifest_ref, case_id=task["case_id"],
                               output_root=short_judge_root)
        judge_identity = judge.verification_identity()
        judge_status_ref = _save(task_root / "judge-status.json", {
            "status": "blocked_untrusted_code_filesystem_isolation_not_demonstrated",
            "verification_identity": judge_identity, "protected_process_handle": None,
            "reason": "Existing execute_version runs submitted CSharp under the same Windows account with full .NET references; no OS ACL, restricted token or container prevents file/process access.",
            "evaluated_model_prompt_has_filesystem_or_process_tool": False,
            "application_source_root": str(source_root), "private_judge_root": str(private),
            "roots_disjoint": not private.is_relative_to(source_root) and not source_root.is_relative_to(private),
            "logical_non_disclosure_is_not_physical_sandbox": True})
        calibration = {}
        try:
            for version in ("C1", "C2"):
                context = _judge_request(task, _response(task, version))
                private_result = judge(context)
                calibration[version] = {
                    "status": private_result["status"],
                    "task_success": (True if private_result["status"] == "passed"
                                     else False if private_result["status"] == "behavior_failed" else None),
                    "execution_origin": private_result["execution_origin"],
                    "verification_summary": private_result["verification_summary"],
                    "preservation_passed": private_result["preservation_passed"],
                    "verification_identity": judge_identity,
                    "materialized_code_identity": context["materialized_code_identity"],
                    "model_response_sha256": context["model_response"]["output_sha256"],
                    "report_sha256": private_result["report_ref"]["sha256"],
                    "detail_visibility": "private observations and report path withheld",
                }
        finally:
            _archive_private_tree(short_judge_root,
                private / "judge-calibration-logs" / (task["case_id"] + ".zip"))
            shutil.rmtree(short_judge_root)
        calibration_ref = _save(task_root / "judge-calibration.json", {"case_id": task["case_id"],
            "C1": calibration["C1"], "C2": calibration["C2"], "model_calls": 0,
            "private_material_returned": False,
            "scope": "trusted teacher C1/C2 internal discrimination only; not an untrusted-submission sandbox"})
        if any(calibration[version]["task_success"] is None for version in ("C1", "C2")):
            _fail("PUBLISH_JUDGE_CALIBRATION_INFRASTRUCTURE_FAILED", "judge_calibration")
        if calibration["C1"]["task_success"] is not False or calibration["C2"]["task_success"] is not True:
            _fail("PUBLISH_JUDGE_DISCRIMINATION_FAILED", "judge_calibration")
        results.append({"task_id": meta["task_id"], "case_id": task["case_id"],
            "family_id": meta["family_id"], "partition": task["split"], "release_ref": release_ref,
            "judge_status_ref": judge_status_ref, "judge_calibration_ref": calibration_ref,
            "B0_compilation_ref": compilation_ref, "request_sha256": meta["requirements_sha256"],
            "source_identity_sha256": meta["baseline_source_sha256"], "status": "published_and_calibrated"})
    summary = {"status": "published_and_calibrated", "role": "new_authorized_publication_and_judge_custodian_not_original_author",
        "protocol_ref": protocol_ref, "metadata_ref": metadata_ref, "sealed_manifest_sha256": manifest_ref["sha256"],
        "inventory_ref": inventory_ref, "toolchain_ref": file_ref(published_toolchain),
        "profile_ref": file_ref(published_profile), "tasks": results,
        "model_calls": 0, "training": False, "external_disclosure": False,
        "product_apply": False, "formal_product_build": False, "deployment": False, "game_runtime": False,
        "protected_judge_handle": "blocked; OS isolation for untrusted submitted code not demonstrated",
        "calibration_scope": "trusted C1/C2 internal discrimination only",
        "agent_source_identity": {"git": GitRepository(repository_root).working_tree_snapshot().to_dict(),
                                  "worker": worker_implementation_identity()},
        "evaluation_accounting": {
            "denominator_unit": "distinct_task_id",
            "independent_attempt": "one frozen task/environment/model/budget execution",
            "revision": "submission after feedback within the same independent attempt",
            "same_task_rerun_increases_task_denominator": False,
            "first_submission_success_separate_from_completed_after_revision": True,
            "correct_stop_is_distinct_outcome": True,
            "infrastructure_failure_retained": True,
            "not_executed_or_unknown_retained": True,
            "missing_token_or_duration_value": None,
            "requirement_clarification_or_approval_is_technical_intervention": False,
            "system_version_drift_results_comparable": False,
            "calibration_development_and_held_out_are_separate": True,
            "engineering_failure_automatically_becomes_training_preference": False
        },
        "exposure_policy": protocol["exposure_policy"]}
    return _save(public / "publication-summary.json", summary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--independent-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--repository-root", default=str(ROOT))
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.preflight_only:
            result = preflight_publish(independent_root=args.independent_root, output_root=args.output_root,
                                       repository_root=args.repository_root)
        else:
            result = publish(independent_root=args.independent_root, output_root=args.output_root,
                             repository_root=args.repository_root)
    except PublisherError as exc:
        print(json.dumps({"status": "blocked", "code": exc.code, "stage": exc.stage},
                         ensure_ascii=False))
        return 2
    except Exception:
        print(json.dumps({"status": "blocked", "code": "PUBLISH_UNEXPECTED_ERROR",
                          "stage": "publisher"}, ensure_ascii=False))
        return 2
    if args.preflight_only:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"status": "published_and_calibrated", "publication_summary_ref": result,
                          "model_calls": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
