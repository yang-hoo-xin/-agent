"""Public publisher/judge contracts only; no sealed task imports or reads."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.prepare_independent_release import main
from src.mod_agent.evaluation.independent_preparation import file_ref
from src.mod_agent.evaluation.independent_product_adapter import project_owned_judge_result
from src.mod_agent.evaluation.independent_release import (
    admit_task_release,
    invoke_protected_judge,
    prepare_released_pair,
)
from tests.unit.test_independent_owned_judge_adapter import public_record


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_ref(path)


def fixture(tmp_path):
    protocol = save(tmp_path / "protocol.json", {"status": "public-test"})
    metadata = save(tmp_path / "metadata.json", {"status": "public-test"})
    source = tmp_path / "published-source"
    source.mkdir()
    (source / "Subject.cs").write_text("public static class Subject { public static int Apply(int x) => x; }\n")
    (source / "Project.csproj").write_text("<Project />\n")
    source_files = [{"relative_path": path.name, "sha256": file_ref(path)["sha256"]}
                    for path in sorted(source.iterdir())]
    request = save(tmp_path / "request.json", {"schema_version": "independent_task_request_v1",
        "task_id": "public-independent-one", "request": "Make Apply return twice the input.",
        "target_mod": "PublicIndependent", "acceptance_criteria": ["Twice the finite integer input."],
        "preservation_requirements": ["Keep the public Apply signature."]})
    profile = {"profile_version": "local_ollama_initial_patch_profile_v1", "base_url": "http://127.0.0.1:11434",
               "model": "public-model", "context_window": 32768, "output_budget": 4096, "timeout_seconds": 60.0}
    normalized_profile = {**profile, "provider": "ollama", "execution_locality": "local", "temperature": 0.0,
        "native_json_schema": True, "automatic_retry": False, "automatic_provider_fallback": False}
    profile_ref = save(tmp_path / "profile.json", normalized_profile)
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("dotnet.exe", "csc.dll", "System.Runtime.dll"):
        (tools / name).write_bytes(("public-" + name).encode())
    toolchain = {"dotnet": file_ref(tools / "dotnet.exe"), "compiler": file_ref(tools / "csc.dll"),
                 "references": [file_ref(tools / "System.Runtime.dll")]}
    toolchain_ref = save(tmp_path / "toolchain.json", toolchain)
    inventory = save(tmp_path / "inventory.json", {"protocol_ref": protocol, "metadata_ref": metadata,
        "toolchain_metadata_sha256": toolchain_ref["sha256"],
        "model": {"name": "public-model", "profile_sha256": profile_ref["sha256"]},
        "tasks": [{"task_id": "public-independent-one", "root_cause_family": "public-family",
                   "requirements_sha256": "1" * 64, "input_sha256": "2" * 64}]})
    release = save(tmp_path / "release.json", {"schema_version": "independent_task_release_v1",
        "status": "published_not_authorized_for_execution", "protocol_ref": protocol, "metadata_ref": metadata,
        "task": {"task_id": "public-independent-one", "case_id": "public-case-one",
                 "family_id": "public-family", "mode": "initial_patch", "request_ref": request,
                 "requirements_identity_sha256": "1" * 64, "source_root": str(source),
                 "source_files": source_files, "source_identity_sha256": "2" * 64},
        "toolchain_ref": toolchain_ref, "model_profile_ref": profile_ref,
        "publisher_attestation": {"answer_free_initial_source_only": True, "contains_hidden_tests": False,
            "contains_reference_repairs": False, "contains_failure_observations": False,
            "model_exposure_prepared": True, "execution_authorized": False}})
    return inventory, release, source


def test_public_release_prepares_equal_arms_without_execution(tmp_path):
    inventory, release, source = fixture(tmp_path)
    admitted = admit_task_release(inventory_ref=inventory, release_ref=release)
    assert admitted["case_id"] == "public-case-one" and admitted["execution_authorized"] is False
    assert admitted["sealed_files_opened"] == admitted["model_calls"] == 0
    reference = prepare_released_pair(inventory_ref=inventory, release_ref=release,
                                      output_root=tmp_path / "pair")
    result = json.loads(Path(reference["path"]).read_text())
    assert result["strategy_execution"] == result["protected_judge_execution"] == "not_run"
    assert result["model_task_success_rate"] is None
    original = {path.name: path.read_bytes() for path in source.iterdir()}
    for arm in result["arms"]:
        copied = {path.name: path.read_bytes() for path in Path(arm["source_root"]).iterdir()}
        assert copied == original


def test_release_cli_materializes_only_answer_free_initial_sources(tmp_path, capsys):
    inventory, release, _ = fixture(tmp_path)
    assert main(["--inventory", inventory["path"], "--inventory-sha256", inventory["sha256"],
                 "--release", release["path"], "--release-sha256", release["sha256"],
                 "--output-root", str(tmp_path / "cli-pair")]) == 0
    reference = json.loads(capsys.readouterr().out)
    assert Path(reference["path"]).is_file()


@pytest.mark.parametrize("drift", ["extra_source", "attestation", "case", "profile", "toolchain"])
def test_release_rejects_unpublished_or_identity_drift(tmp_path, drift):
    inventory, release, source = fixture(tmp_path)
    document = json.loads(Path(release["path"]).read_text())
    if drift == "extra_source":
        (source / "unpublished.cs").write_text("hidden")
    elif drift == "attestation":
        document["publisher_attestation"]["contains_reference_repairs"] = True
    elif drift == "case":
        document["task"]["task_id"] = "renamed-task"
    elif drift == "profile":
        profile = json.loads(Path(document["model_profile_ref"]["path"]).read_text())
        profile["output_budget"] += 1
        document["model_profile_ref"] = save(tmp_path / "changed-profile.json", profile)
    else:
        document["toolchain_ref"] = save(tmp_path / "changed-toolchain.json", {"dotnet": document["model_profile_ref"],
            "compiler": document["model_profile_ref"], "references": [document["model_profile_ref"]]})
    changed = save(tmp_path / "changed-release.json", document)
    with pytest.raises(ValueError):
        admit_task_release(inventory_ref=inventory, release_ref=changed)


def test_protected_judge_handle_returns_only_bound_aggregate():
    context, identity, private = public_record()
    private["report_ref"]["sha256"] = "a" * 64
    seen = []

    def protected(request):
        seen.append(request)
        assert set(request) == {"schema_version", "context", "verification_identity"}
        return project_owned_judge_result(private, context=request["context"],
                                          verification_identity=request["verification_identity"])

    endpoint = {"endpoint_id": "public-protected-test", "implementation_sha256": "b" * 64,
                "transport": "controlled_test_double",
                "detail_policy": "aggregate_only_no_hidden_checks_or_paths"}
    receipt = invoke_protected_judge(context=context, verification_identity=identity,
                                     endpoint_identity=endpoint, invoke=protected)
    assert receipt["private_judge_material_received"] is False
    assert receipt["verdict"]["task_success"] is True and len(seen) == 1
    assert "DO_NOT_PROJECT" not in repr(receipt)
    assert "DO_NOT_PROJECT" not in repr(receipt) and "report_ref" not in receipt["verdict"]


def test_protected_judge_rejects_mutated_aggregate_identity():
    context, identity, private = public_record()
    private["report_ref"]["sha256"] = "a" * 64
    endpoint = {"endpoint_id": "public-protected-test", "implementation_sha256": "b" * 64,
                "transport": "protected_process", "detail_policy": "aggregate_only_no_hidden_checks_or_paths"}

    def changed(request):
        result = project_owned_judge_result(private, context=request["context"],
                                            verification_identity=request["verification_identity"])
        result["model_response_sha256"] = "drift"
        return result

    with pytest.raises(ValueError, match="does not bind"):
        invoke_protected_judge(context=deepcopy(context), verification_identity=identity,
                               endpoint_identity=endpoint, invoke=changed)


@pytest.mark.parametrize("field,value", [
    ("task_success", 1),
    ("verification_summary", {"checks": 1, "failed_checks": 2, "executions": 1}),
    ("outcome", "success"),
])
def test_protected_judge_rejects_invalid_aggregate_outcome(field, value):
    context, identity, private = public_record()
    private["report_ref"]["sha256"] = "a" * 64
    private["status"] = "infrastructure_failed"
    private["execution_origin"] = "incomplete"
    private["preservation_passed"] = None
    private["verification_summary"] = {"checks": 0, "failed_checks": 0, "executions": 0}
    endpoint = {"endpoint_id": "public-protected-test", "implementation_sha256": "b" * 64,
                "transport": "protected_process", "detail_policy": "aggregate_only_no_hidden_checks_or_paths"}

    def changed(request):
        result = project_owned_judge_result(private, context=request["context"],
                                            verification_identity=request["verification_identity"])
        result[field] = value
        return result

    with pytest.raises(ValueError, match="outcome"):
        invoke_protected_judge(context=context, verification_identity=identity,
                               endpoint_identity=endpoint, invoke=changed)
