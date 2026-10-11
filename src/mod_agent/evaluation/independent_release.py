"""Admit answer-free task releases and protected-judge aggregate receipts.

This consumes publisher-owned public manifests. It never discovers sealed
material, constructs an oracle, authorizes execution, or starts a model.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.mod_agent.evaluation.independent_preparation import digest, file_ref, write_once
from src.mod_agent.evaluation.patch_task_suite import _checked_profile
from src.mod_agent.model_qualification import read_bound_json

RELEASE_SCHEMA = "independent_task_release_v1"
REQUEST_SCHEMA = "independent_task_request_v1"
RELEASE_STATUS = "published_not_authorized_for_execution"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ATTESTATION = {
    "answer_free_initial_source_only": True,
    "contains_hidden_tests": False,
    "contains_reference_repairs": False,
    "contains_failure_observations": False,
    "model_exposure_prepared": True,
    "execution_authorized": False,
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _local_path(value, *, directory=False):
    _require(isinstance(value, str) and Path(value).is_absolute()
             and not value.startswith(("\\\\", "//")), "Absolute local path required")
    path = Path(value).resolve(strict=True)
    _require(path.is_dir() if directory else path.is_file(), "Published local path is unavailable")
    return path


def _source_files(task):
    root = _local_path(task["source_root"], directory=True)
    rows = task["source_files"]
    _require(isinstance(rows, list) and rows, "Published source manifest is empty")
    seen, result = set(), {}
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {"relative_path", "sha256"},
                 "Published source entries require relative_path and sha256")
        name, sha256 = row["relative_path"], row["sha256"]
        _require(isinstance(name, str) and name == Path(name).as_posix()
                 and not name.startswith("/") and ".." not in Path(name).parts
                 and name not in seen and isinstance(sha256, str) and _SHA256.fullmatch(sha256),
                 "Published source entry is invalid")
        path = (root / name).resolve(strict=True)
        _require(path.is_relative_to(root) and path.is_file() and not path.is_symlink(),
                 "Published source path escapes its root")
        _require(file_ref(path)["sha256"] == sha256, "Published source bytes changed")
        seen.add(name)
        result[name] = path.read_bytes()
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    _require(actual == seen, "Source root contains files outside the published manifest")
    return root, result


def _request(task):
    document = read_bound_json(task["request_ref"])
    _require(set(document) == {"schema_version", "task_id", "request", "target_mod",
                               "acceptance_criteria", "preservation_requirements"}
             and document["schema_version"] == REQUEST_SCHEMA
             and document["task_id"] == task["task_id"], "Published request shape is invalid")
    for field in ("request", "target_mod"):
        _require(isinstance(document[field], str) and document[field].strip(),
                 "Published request text is incomplete")
    for field in ("acceptance_criteria", "preservation_requirements"):
        values = document[field]
        _require(isinstance(values, list) and values
                 and all(isinstance(value, str) and value.strip() for value in values)
                 and len(values) == len(set(values)), "Published requirements are incomplete")
    return document


def _toolchain(reference, expected_sha256):
    _require(reference["sha256"] == expected_sha256,
             "Published toolchain file does not match public metadata")
    document = read_bound_json(reference)
    _require(set(document) == {"dotnet", "compiler", "references"}
             and isinstance(document["references"], list) and document["references"],
             "Published toolchain shape is invalid")
    refs = [document["dotnet"], document["compiler"], *document["references"]]
    for ref in refs:
        _require(isinstance(ref, dict) and set(ref) == {"path", "sha256"},
                 "Published toolchain references are invalid")
        _require(file_ref(_local_path(ref["path"])) == ref, "Published toolchain bytes changed")
    return document


def admit_task_release(*, inventory_ref, release_ref):
    inventory = read_bound_json(inventory_ref)
    release = read_bound_json(release_ref)
    _require(release.get("schema_version") == RELEASE_SCHEMA
             and release.get("status") == RELEASE_STATUS
             and set(release) == {"schema_version", "status", "protocol_ref", "metadata_ref", "task",
                                  "toolchain_ref", "model_profile_ref", "publisher_attestation"},
             "Independent release shape or status is invalid")
    _require(release["protocol_ref"] == inventory["protocol_ref"]
             and release["metadata_ref"] == inventory["metadata_ref"],
             "Release does not bind the public protocol and metadata")
    _require(release["publisher_attestation"] == _ATTESTATION,
             "Publisher did not attest an answer-free, non-executable release")
    task = release["task"]
    _require(isinstance(task, dict) and set(task) == {"task_id", "case_id", "family_id", "mode",
             "request_ref", "requirements_identity_sha256", "source_root", "source_files",
             "source_identity_sha256"}, "Published task fields are invalid")
    matches = [row for row in inventory["tasks"] if row["task_id"] == task["task_id"]]
    _require(len(matches) == 1, "Published task is absent from public metadata")
    metadata = matches[0]
    _require(task["mode"] == "initial_patch" and isinstance(task["case_id"], str)
             and task["case_id"].strip() and task["family_id"] == metadata["root_cause_family"]
             and task["requirements_identity_sha256"] == metadata["requirements_sha256"]
             and task["source_identity_sha256"] == metadata["input_sha256"],
             "Published task identity does not match public metadata")
    request = _request(task)
    source_root, sources = _source_files(task)
    profile = _checked_profile(read_bound_json(release["model_profile_ref"]))
    _require(profile["model"] == inventory["model"]["name"]
             and release["model_profile_ref"]["sha256"] == inventory["model"]["profile_sha256"],
             "Published model profile does not match public metadata")
    toolchain = _toolchain(release["toolchain_ref"], inventory["toolchain_metadata_sha256"])
    return {"release_ref": dict(release_ref), "task_id": task["task_id"], "case_id": task["case_id"],
        "family_id": task["family_id"], "mode": "initial_patch", "request": request,
        "source_root": str(source_root), "source_files": sources, "source_manifest_sha256": digest(task["source_files"]),
        "source_identity_sha256": task["source_identity_sha256"], "requirements_identity_sha256": task["requirements_identity_sha256"],
        "toolchain": toolchain, "toolchain_ref": dict(release["toolchain_ref"]),
        "model_profile": profile, "model_profile_ref": dict(release["model_profile_ref"]),
        "execution_authorized": False, "model_calls": 0, "sealed_files_opened": 0}


def prepare_released_pair(*, inventory_ref, release_ref, output_root):
    admitted = admit_task_release(inventory_ref=inventory_ref, release_ref=release_ref)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    files = admitted.pop("source_files")
    arms = []
    for arm in ("simple_rg", "full_product_graph"):
        source = root / arm / "source"
        source.mkdir(parents=True)
        for name, raw in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        arms.append({"arm": arm, "source_root": str(source),
                     "source_manifest_sha256": digest([{"relative_path": name,
                         "sha256": file_ref(source / name)["sha256"]} for name in sorted(files)])})
    receipt = {**admitted, "scope": "answer_free_release_preparation_only", "arms": arms,
        "strategy_execution": "not_run", "protected_judge_execution": "not_run",
        "model_task_success_rate": None}
    return write_once(root / "released-pair.json", receipt)


def _validate_endpoint(identity):
    _require(isinstance(identity, Mapping) and set(identity) == {"endpoint_id", "implementation_sha256",
             "transport", "detail_policy"} and isinstance(identity["endpoint_id"], str)
             and identity["endpoint_id"].strip() and isinstance(identity["implementation_sha256"], str)
             and _SHA256.fullmatch(identity["implementation_sha256"])
             and identity["transport"] in {"protected_process", "controlled_test_double"}
             and identity["detail_policy"] == "aggregate_only_no_hidden_checks_or_paths",
             "Protected judge endpoint identity is invalid")


def validate_protected_judge_result(result, *, context, verification_identity):
    allowed = {"compilation", "behavior", "outcome", "task_success", "verification_summary",
               "preservation_passed", "verification_identity", "materialized_code_identity",
               "model_response_sha256", "report_sha256", "detail_visibility"}
    _require(isinstance(result, dict) and set(result) == allowed
             and result["verification_identity"] == verification_identity
             and result["materialized_code_identity"] == context["materialized_code_identity"]
             and result["model_response_sha256"] == context["model_response"]["output_sha256"]
             and _SHA256.fullmatch(result["report_sha256"] or "")
             and result["detail_visibility"] == "private observations and report path withheld",
             "Protected judge aggregate does not bind this submission")
    counts = result["verification_summary"]
    _require(isinstance(counts, dict) and set(counts) == {"checks", "failed_checks", "executions"}
             and all(type(value) is int and value >= 0 for value in counts.values())
             and counts["failed_checks"] <= counts["checks"]
             and (type(result["task_success"]) is bool or result["task_success"] is None)
             and result["outcome"] in {"success", "compilation_failed", "behavior_failed", "execution_error"},
             "Protected judge outcome is invalid")
    expected = {"success": True, "compilation_failed": False, "behavior_failed": False,
                "execution_error": None}
    _require(result["task_success"] is expected[result["outcome"]],
             "Protected judge outcome and task success disagree")
    return deepcopy(result)


def invoke_protected_judge(*, context, verification_identity, endpoint_identity,
                           invoke: Callable[[dict[str, Any]], dict[str, Any]]):
    _validate_endpoint(endpoint_identity)
    request = {"schema_version": "protected_owned_judge_request_v1", "context": deepcopy(context),
               "verification_identity": deepcopy(verification_identity)}
    before = digest(request)
    result = invoke(deepcopy(request))
    _require(digest(request) == before, "Protected judge invocation mutated the request")
    verdict = validate_protected_judge_result(result, context=context,
                                              verification_identity=verification_identity)
    return {"endpoint_identity": dict(endpoint_identity), "request_sha256": before,
            "verdict": verdict, "private_judge_material_received": False}
