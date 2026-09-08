"""Prepare independently owned, executed repair demonstrations for a local pilot.

No model or network calls. Teacher C2 is allowed only as train completion or a
hidden validation oracle. Public worker input uses its original contracts.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from src.libs.llm import ChatResponse
from src.libs.llm.agent_turn import AgentMessage, AgentResponseFormat
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
from src.mod_agent.local_entry import (
    LocalOllamaInitialPatchAdapter,
    _external_evidence_items,
    _patch_agent_initial_messages,
    _patch_generation_obligation_projection,
)
from src.mod_agent.model_qualification import canonical_hash, read_bound_json
from src.mod_agent.planning.implementation_plan import ImplementationPlanner
from src.mod_agent.planning.models import FeatureSpec, stable_feature_id
from src.mod_agent.proposal import LLMExactPatchGenerator
from src.mod_agent.proposal.patch_agent_loop import (
    PatchAgentLoopPolicy,
    PlanBoundSourceInspector,
    run_patch_agent_loop,
)

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests/fixtures/patch_sft_owned"
BASE_MODEL = {"model_id": "Qwen/Qwen3-1.7B", "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"}


def ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return ref(path)


def load_tasks():
    spec = importlib.util.spec_from_file_location("owned_patch_sft_tasks", FIXTURES / "tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def toolchain():
    dotnet = Path("C:/Program Files/dotnet/dotnet.exe")
    sdk = dotnet.parent / "sdk/7.0.401/Roslyn/bincore/csc.dll"
    references = sorted((dotnet.parent / "packs/Microsoft.NETCore.App.Ref/7.0.11/ref/net7.0").glob("*.dll"))
    if not dotnet.is_file() or not sdk.is_file() or not references:
        raise ValueError("OWNED_SFT_FIXED_NET7_TOOLCHAIN_UNAVAILABLE")
    return {"dotnet": ref(dotnet), "compiler": ref(sdk), "references": [ref(path) for path in references]}


def execute_version(root, source, program, tools):
    root.mkdir(parents=True, exist_ok=False)
    subject, harness = root / "Subject.cs", root / "Program.cs"
    subject.write_text(source, encoding="utf-8", newline="\n")
    harness.write_text(program, encoding="utf-8", newline="\n")
    response = root / "compile.rsp"
    assembly = root / "CheckApp.dll"
    response.write_text("\n".join(["/nologo", "/target:exe", "/langversion:latest", f'/out:"{assembly}"',
        *(f'/r:"{item["path"]}"' for item in tools["references"]), f'"{subject}"', f'"{harness}"']), encoding="utf-8")
    environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP") if name in os.environ}
    environment.update(DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1")
    compiled = subprocess.run([tools["dotnet"]["path"], tools["compiler"]["path"], "@" + str(response)],
        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=40)
    compile_ref = save(root / "compilation.json", {"exit_code": compiled.returncode, "stdout": compiled.stdout,
        "stderr": compiled.stderr, "sources": [ref(subject), ref(harness)], "arguments_ref": ref(response)})
    if compiled.returncode:
        raise ValueError("OWNED_SFT_COMPILATION_FAILED: " + str(compile_ref))
    save(root / "CheckApp.runtimeconfig.json", {"runtimeOptions": {"tfm": "net7.0", "framework": {"name": "Microsoft.NETCore.App", "version": "7.0.11"}}})
    observed = subprocess.run([tools["dotnet"]["path"], str(assembly), str(root / "files")], cwd=root,
        env=environment, capture_output=True, text=True, encoding="utf-8", timeout=15)
    rows = json.loads(observed.stdout)
    if observed.returncode not in (0, 1) or not isinstance(rows, list) or not rows:
        raise ValueError("OWNED_SFT_BEHAVIOR_DID_NOT_EXECUTE")
    failed = [row for row in rows if row["passed"] is False]
    if observed.returncode != int(bool(failed)):
        raise ValueError("OWNED_SFT_PROCESS_VERDICT_MISMATCH")
    result = {"status": "passed" if not failed else "behavior_failed", "checks": rows,
        "failed_checks": [row["check"] for row in failed], "preservation_passed": all(row["passed"] for row in rows if row["group"] == "preservation"),
        "compilation_ref": compile_ref, "assembly_ref": ref(assembly), "exit_code": observed.returncode,
        "stdout": observed.stdout, "stderr": observed.stderr, "execution_origin": "actual_csharp_process", "source_ref": ref(subject)}
    return {**result, "report_ref": save(root / "behavior.json", result)}


def prepare_contract(definition, root):
    workspace = root / "source"
    source = workspace / "OwnedTraining/Subject.cs"
    source.parent.mkdir(parents=True)
    source.write_text(definition["sources"]["B0"], encoding="utf-8", newline="\n")
    store = ArtifactStore(root / "store")
    feature = FeatureSpec(feature_id=stable_feature_id(definition["request"]), user_request=definition["request"],
        target_behavior=definition["request"], target_mod="PatchSftOwned", risk_level="low",
        acceptance_criteria=("The fixed independent execution checks pass for all declared inputs.",),
        non_goals=("Preserve the original behaviors and public signatures; do not edit the checks or their expectations.",),
        evidence_requirements=("Current exact subject source and its state fields.",),
        runtime_verification_plan=("Compile and execute the fixed C# checks in an isolated process.",))
    feature_ref = store.write(feature_id=feature.feature_id, artifact_type="feature_spec", payload=feature.to_artifact_payload())
    projection = default_feature_requirement_projection(feature.to_artifact_payload())
    for item in projection["requirements"]:
        item["query_leads"] = ["Apply"]
    projected = materialize_requirement_coverage_projection(feature_data=feature.to_artifact_payload(), request=definition["request"], projection=projection)
    retrieved = RgLiveEvidenceProvider(workspace).collect_query_set(queries=tuple(projected["queries"]), search_root="OwnedTraining", max_items=32)
    targets = [item.evidence_id for item in retrieved.items if item.source_path == "OwnedTraining/Subject.cs" and item.symbol == "Apply"]
    if len(targets) != 1:
        raise ValueError("OWNED_SFT_TARGET_NOT_UNIQUE")
    findings = {"findings": [{"relation_index": index, "relationship": "missing" if item["role"] == "post_change_acceptance" else "support",
        "evidence_ids": [] if item["role"] == "post_change_acceptance" else [row.evidence_id for row in retrieved.items],
        "edit_target_evidence_ids": targets if item["role"] == "change" else [],
        "unresolved_gaps": ["Execute the fixed checks on the submitted version."] if item["role"] == "post_change_acceptance" else []}
        for index, item in enumerate(projected["requirements"], 1)]}
    pack = build_requirement_coverage_pack(query=definition["request"], materialized_projection=projected, retrieved_pack=retrieved, findings=findings).to_artifact_payload()
    pack["budget_summary"]["fixture_authorship"] = {"semantic_owner": "authorized_teacher_fixture", "model_calls": 0, "fresh_model_execution": False}
    evidence_ref = store.write(feature_id=feature.feature_id, artifact_type="evidence_pack", payload=pack, upstream_refs=[feature_ref])
    plan = ImplementationPlanner().build(feature_spec=feature, evidence_pack=pack, formal_requirement_coverage_required=True,
                                         planning_target_evidence_ids=tuple(targets))
    if plan.blocking:
        raise ValueError("OWNED_SFT_PLAN_BLOCKED")
    plan_data = plan.to_artifact_payload()
    plan_ref = store.write(feature_id=feature.feature_id, artifact_type="implementation_plan", payload=plan_data, upstream_refs=[feature_ref, evidence_ref])
    request = PatchContinuationInputV1(contract_version=PATCH_CONTINUATION_CONTRACT_VERSION, artifact_store_root=str(store.root),
        workspace_root=str(workspace), feature_spec_ref=feature_ref, evidence_pack_ref=evidence_ref, implementation_plan_ref=plan_ref)
    preflight_patch_continuation(request)
    obligations = _patch_generation_obligation_projection(feature_spec=feature.to_artifact_payload(), implementation=plan_data,
                                                       planned_changes=plan_data["proposed_changes"])
    generator = LLMExactPatchGenerator(None)
    prepared = generator.prepare_native_contract(user_request=definition["request"], evidence_items=_external_evidence_items(pack["items"]),
        binding_registry=plan_data["binding_registry"], constraints=obligations["side_effect_boundaries"],
        target_behavior=obligations["target_behavior"], acceptance_criteria=obligations["acceptance_criteria"],
        runtime_verification_plan=obligations["runtime_verification_plan"], required_change_units=obligations["required_change_units"],
        required_validation_by_binding={row["edit_binding_id"]:row["expected_validation"] for row in obligations["required_change_units"]})
    return workspace, plan_data, generator, prepared, request


def structured_output(definition, version, root, plan, generator, prepared, workspace):
    version_root = root / "teacher_sources" / version
    version_root.mkdir(parents=True)
    version_file = version_root / "Subject.cs"
    version_file.write_text(definition["sources"][version], encoding="utf-8", newline="\n")
    evidence = RgLiveEvidenceProvider(version_root).collect(query="Apply", search_root=".", max_items=4)
    methods = [item for item in evidence.items if item.symbol == "Apply"]
    if len(methods) != 1:
        raise ValueError("OWNED_SFT_TEACHER_METHOD_NOT_UNIQUE")
    span = methods[0].span
    after = b"".join(version_file.read_bytes().splitlines(keepends=True)[span["start_line"] - 1:span["end_line"]]).decode()
    output = json.dumps({"changes": [{"edit_binding_id": plan["binding_registry"]["edit_bindings"][0]["binding_id"],
        "rationale": "Preserve unrelated behavior while satisfying the bound state and result obligations.",
        "rollback_hint": "Restore the original bound method.", "after_text": after}]}, ensure_ascii=False)
    generated = generator.materialize_prepared_native(prepared, ChatResponse(content=output, model="authorized-teacher-not-a-model-run"))
    materialized = materialize_exact_text_patch(workspace_root=workspace, diff_intent=generated.changes, implementation_plan=plan)
    if materialized.files["OwnedTraining/Subject.cs"] != definition["sources"][version].encode():
        raise ValueError("OWNED_SFT_COMPLETE_B0_DIFFERENCE_MISMATCH")
    return output, generated, materialized


class _CapturedError(RuntimeError):
    def __init__(self, request):
        self.request = request


class _PreparationClient:
    provider, model = "no_model", "request_preparation_only"
    def complete_turn(self, request):
        raise _CapturedError(request)


def prepare_one(definition, root, tools, program, reuse_root=None):
    root.mkdir(parents=True, exist_ok=False)
    versions, reused = {}, 0
    for version, source in definition["sources"].items():
        prior = next((path for old in (reuse_root or [])
                      if (path := old / "tasks" / definition["case_id"] / "hidden_verification" / version / "behavior.json").is_file()), None)
        prior = prior.parent if prior is not None else None
        if prior is not None and (prior / "behavior.json").is_file():
            result = json.loads((prior / "behavior.json").read_text(encoding="utf-8"))
            compilation = read_bound_json(result["compilation_ref"])
            expected = (hashlib.sha256(source.encode()).hexdigest(), hashlib.sha256(program.encode()).hexdigest())
            if tuple(item["sha256"] for item in compilation["sources"]) != expected:
                raise ValueError("OWNED_SFT_REUSE_INPUT_CHANGED")
            if any(ref(item["path"]) != item for item in compilation["sources"]):
                raise ValueError("OWNED_SFT_REUSE_SOURCE_CHANGED")
            versions[version] = {**result, "report_ref": ref(prior / "behavior.json")}
            reused += 1
        else:
            versions[version] = execute_version(root / "hidden_verification" / version, source, program, tools)
    if not versions["B0"]["preservation_passed"] or versions["C1"]["status"] != "behavior_failed" or versions["C2"]["status"] != "passed":
        raise ValueError("OWNED_SFT_DEMONSTRATION_REJECTED: " + definition["case_id"])
    workspace, plan, generator, prepared, continuation = prepare_contract(definition, root)
    outputs = {version: structured_output(definition, version, root, plan, generator, prepared, workspace) for version in ("C1", "C2")}
    if outputs["C2"][2].code_sha256 == outputs["C2"][2].baseline_sha256:
        raise ValueError("OWNED_SFT_EMPTY_REPAIR")
    failed = {"status": "behavior_failed", "failure_owner": "patch_implementation", "owner_binding_ids": [plan["binding_registry"]["edit_bindings"][0]["binding_id"]],
        "observations": [{"check_id": row["check"], "input": {"case_id": definition["case_id"], "group": row["group"]},
                          "expected": row["expected"], "observed": row["observed"]} for row in versions["C1"]["checks"] if not row["passed"]],
        "generated_changes_sha256": canonical_hash(outputs["C1"][1].changes), "model_response_sha256": hashlib.sha256(outputs["C1"][0].encode()).hexdigest(),
        "failure_origin": "executed_teacher_authored_C1_not_prior_model_execution"}
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False,
        enable_supporting_reads=True, allow_upstream_request=True, allow_batched_reads=True, reuse_covered_source_observations=True)
    inspector = PlanBoundSourceInspector(workspace_root=workspace, implementation_plan=plan, policy=policy)
    observation = inspector.inspect(binding_id=inspector.available_binding_ids[0], observation_id="teacher-source-observation-001")
    messages = (*_patch_agent_initial_messages(prepared.messages),
        AgentMessage("user", {"message_type": "provided_source_observation", "origin": "deterministic_preparation_not_model_tool_call", "observation": observation.model_view()}),
        *LocalOllamaInitialPatchAdapter._revision_messages(outputs["C1"][0], failed, message_type="patch_repair_context"))
    try:
        run_patch_agent_loop(client=_PreparationClient(), initial_messages=messages, source_inspector=inspector,
            final_response_format=AgentResponseFormat(name="patch_generation_v2", description="Bound complete replacement relative to B0.", schema=prepared.response_schema))
    except _CapturedError as captured:
        raw_request = asdict(captured.request)
    else:
        raise ValueError("OWNED_SFT_WORKER_PREPARATION_NOT_REACHED")
    prompt = [{"role": row["role"], "content": row["content"] if isinstance(row["content"], str) else json.dumps(row["content"], ensure_ascii=False)}
              for row in raw_request["messages"]]
    tool_defs = [{"type": "function", "function": {"name": item["name"], "description": item["description"], "parameters": item["parameters"]}} for item in raw_request["tools"]]
    sample = {"sample_id": definition["case_id"], "case_id": definition["case_id"], "family_id": definition["family_id"], "split": definition["split"],
        "format": "conversational_prompt_completion", "pairing": "authorized_teacher_supervision_not_original_model_turns",
        "learning_objective": "repair_code_against_executed_failure_preserving_behavior", "prompt": prompt, "tools": tool_defs,
        "loss_contract": {"completion_only_loss": True, "assistant_only_loss_over_full_history": False,
                          "prompt_message_loss_mask": [False]*len(prompt), "completion_message_loss_mask": [True]},
        "training_executed": False, "data_disclosure": "local_only", "model_calls": 0, "planning_owner": "operator_authored_fixture"}
    completion = [{"role": "assistant", "content": outputs["C2"][0]}]
    if definition["split"] == "train":
        sample["completion"] = completion
    hidden_ref = save(root / "hidden_oracle.json", {"completion": completion, "source": definition["sources"]["C2"],
        "checks_source": program, "version_reports": {key: value["report_ref"] for key, value in versions.items()}})
    provenance = {"case_id": definition["case_id"], "family_id": definition["family_id"], "split": definition["split"],
        "continuation_input_ref": save(root / "continuation-input.json", asdict(continuation)),
        "raw_request_ref": save(root / "raw-request.json", raw_request), "response_schema_ref": save(root / "response-schema.json", prepared.response_schema),
        "hidden_oracle_ref": hidden_ref, "version_reports": {key: value["report_ref"] for key, value in versions.items()},
        "source_root": str(workspace), "correct_code_location": "train_completion_or_hidden_oracle_only",
        "C1_failed_checks": versions["C1"]["failed_checks"], "C2_checks": len(versions["C2"]["checks"]),
        "verified_compilations": 3, "verified_behavior_processes": 3, "new_compilations": 3-reused,
        "new_behavior_processes": 3-reused, "reused_version_reports": reused, "real_model_calls": 0, "fresh_execution_claimed": False}
    save(root / "provenance.json", provenance)
    return sample, provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reuse-verification-from", type=Path, action="append", help="Explicit prior run; only exact source/check/toolchain matches are reused")
    args = parser.parse_args(argv)
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    module = load_tasks()
    tools = toolchain()
    if any(json.loads((old / "toolchain.json").read_text(encoding="utf-8")) != tools for old in (args.reuse_verification_from or [])):
        raise ValueError("OWNED_SFT_REUSE_TOOLCHAIN_CHANGED")
    families = {}
    for item in module.TASKS:
        families.setdefault(item["family_id"], set()).add(item["split"])
    if len(families) != 6 or any(len(splits) != 1 for splits in families.values()):
        raise ValueError("OWNED_SFT_FAMILY_PARTITION_INVALID")
    save(output / "toolchain.json", tools)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(prepare_one, item, output / "tasks" / item["case_id"], tools, module.harness(item["checks"]), args.reuse_verification_from) for item in module.TASKS]
        prepared = [future.result() for future in futures]
    refs = {}
    for split in ("train", "validation", "holdout"):
        path = output / (split + ".jsonl")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            for sample, _ in prepared:
                if sample["split"] == split:
                    stream.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
        refs[split] = ref(path)
    manifest = {"base_model": BASE_MODEL, "splits": refs, "tasks": [provenance for _, provenance in prepared],
        "family_split": {key: next(iter(value)) for key, value in families.items()},
        "family_count": 6, "case_count": 12, "split_case_counts": {split: sum(sample["split"]==split for sample,_ in prepared) for split in refs},
        "distinct_independent_task_families": 6, "related_variants_are_not_independent_families": True,
        "verified_compilations": 36, "verified_behavior_processes": 36,
        "new_compilations": sum(row["new_compilations"] for _,row in prepared),
        "new_behavior_processes": sum(row["new_behavior_processes"] for _,row in prepared), "real_model_calls": 0,
        "licence_ref": ref(FIXTURES / "LICENSE"), "definition_ref": ref(FIXTURES / "tasks.py"),
        "claims": {"teacher_authored": True, "local_training_pilot_only": True, "generalization_proven": False,
                   "autonomous_planning_proven": False, "natural_language_to_runtime_proven": False,
                   "FirstShot_or_prior_OwnedConfigService_solution_in_holdout": False}}
    result = save(output / "manifest.json", manifest)
    print(json.dumps({"manifest": result, "split_case_counts": manifest["split_case_counts"], "families": 6,
                      "verified_compilations": 36, "verified_behavior_processes": 36, "real_model_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
