"""Extract a narrow member-name repair from bound compiler/model/delivery records."""
import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from src.mod_agent.planning.task_memory import TaskMemory


def file_ref(path):
    path = Path(path).resolve(strict=True)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def read_ref(ref, *, document=True):
    if set(ref) != {"path", "sha256"} or not Path(ref["path"]).is_absolute() or file_ref(ref["path"])["sha256"] != ref["sha256"]:
        raise ValueError("MEMORY_IMPORT_SOURCE_CHANGED")
    raw = Path(ref["path"]).read_bytes()
    return json.loads(raw) if document else raw


def _missing_member(report):
    errors = report.get("source_compilation_errors", [])
    if report.get("status") != "compilation_failed" or len(errors) != 1 or errors[0].get("code") != "CS1061":
        raise ValueError("MEMORY_IMPORT_FAILURE_NOT_SINGLE_CS1061")
    message = errors[0]["message"]
    match = re.search(r"[“']([A-Za-z_][\w.]*)[”'](?:未包含| does not contain a definition for )[“']([A-Za-z_]\w*)[”']", message)
    if match is None:
        raise ValueError("MEMORY_IMPORT_COMPILER_DIAGNOSTIC_UNSUPPORTED")
    return errors[0], match.group(1), match.group(2)


def extract_member_repair(*, journal_ref, failed_report_ref, passed_report_ref, recurrence_report_ref,
                          delivery_ref, formal_checks_ref, dependency_relative_path):
    refs = {"journal": journal_ref, "failed_compilation": failed_report_ref, "passed_compilation": passed_report_ref,
            "recurring_failure": recurrence_report_ref, "delivery": delivery_ref, "formal_checks": formal_checks_ref}
    documents = {key: read_ref(ref) for key, ref in refs.items()}
    journal, failed, passed = (documents[key] for key in ("journal", "failed_compilation", "passed_compilation"))
    diagnostic, receiver_type, old_member = _missing_member(failed)
    _, recurring_type, recurring_member = _missing_member(documents["recurring_failure"])
    if (recurring_type, recurring_member) != (receiver_type, old_member):
        raise ValueError("MEMORY_IMPORT_RECURRENCE_MISMATCH")
    if documents["recurring_failure"]["dependency_binding"]["snapshot_sha256"] != failed["dependency_binding"]["snapshot_sha256"]:
        raise ValueError("MEMORY_IMPORT_RECURRENCE_DEPENDENCY_MISMATCH")
    if (passed.get("status") != "passed" or passed.get("source_compilation_errors") != []
            or not passed.get("all_required_files_compiled")
            or passed["dependency_binding"] != failed["dependency_binding"]
            or passed["materialized_code_identity"]["baseline_sha256"] != failed["materialized_code_identity"]["baseline_sha256"]):
        raise ValueError("MEMORY_IMPORT_PASS_OR_COMPARISON_INVALID")
    evaluations = journal["factory_receipt"]["patch_agent_loop"]["behavior_evaluations"]
    indexes = []
    for report in (failed, passed):
        matches = [index for index, row in enumerate(evaluations)
                   if row.get("materialized_code_identity") == report["materialized_code_identity"]
                   and row.get("model_response_sha256") == report["model_response_ref"]["sha256"]
                   and row.get("callback_invoked") is True and row.get("execution_origin") == "executed"]
        if len(matches) != 1:
            raise ValueError("MEMORY_IMPORT_CHAIN_NOT_BOUND")
        indexes.append(matches[0])
    if indexes[0] >= indexes[1]:
        raise ValueError("MEMORY_IMPORT_REPAIR_ORDER_INVALID")
    responses = [read_ref(report["model_response_ref"]) for report in (failed, passed)]
    if any(len(response.get("changes", [])) != 1 for response in responses):
        raise ValueError("MEMORY_IMPORT_MULTIPLE_CHANGES")
    changes = [response["changes"][0] for response in responses]
    if changes[0]["edit_binding_id"] != changes[1]["edit_binding_id"]:
        raise ValueError("MEMORY_IMPORT_BINDING_CHANGED")
    before, after = [change["after_text"] for change in changes]
    pattern = re.compile(r"(?P<receiver>[A-Za-z_][\w.]*)\.(?P<member>[A-Za-z_]\w*)\s*\(")
    calls = [list(pattern.finditer(text)) for text in (before, after)]
    if len(calls[0]) != len(calls[1]):
        raise ValueError("MEMORY_IMPORT_NOT_SINGLE_MEMBER_REPAIR")
    differences = [(left, right) for left, right in zip(*calls) if left.group() != right.group()]
    if len(differences) != 1:
        raise ValueError("MEMORY_IMPORT_NOT_SINGLE_MEMBER_REPAIR")
    left, right = differences[0]
    new_member = right.group("member")
    if (left.group("member") != old_member or left.group("receiver") != right.group("receiver")
            or before[:left.start("member")] + new_member + before[left.end("member"):] != after):
        raise ValueError("MEMORY_IMPORT_NOT_SINGLE_MEMBER_REPAIR")
    inputs = [read_ref(report["source_inputs_ref"]) for report in (failed, passed)]
    code_hashes = [hashlib.sha256(text.encode()).hexdigest() for text in (before, after)]
    if (inputs[0].get(diagnostic["file"]) != code_hashes[0] or diagnostic["source_sha256"] != code_hashes[0]
            or inputs[1].get(diagnostic["file"]) != code_hashes[1]
            or {k: v for k, v in inputs[0].items() if k != diagnostic["file"]}
            != {k: v for k, v in inputs[1].items() if k != diagnostic["file"]}):
        raise ValueError("MEMORY_IMPORT_COMPILED_BYTES_MISMATCH")
    for key, report in (("failed", failed), ("passed", passed)):
        refs[key + "_response"] = report["model_response_ref"]
        refs[key + "_source_inputs"] = report["source_inputs_ref"]
    read_ref(passed["built_artifact_ref"], document=False)
    delivery, formal = documents["delivery"], documents["formal_checks"]
    if (delivery.get("status") != "delivered" or delivery.get("delivery_complete") is not True
            or delivery.get("acceptance_passed") is not True or formal.get("status") != "passed"
            or len(formal.get("cases", [])) != 3
            or any(case.get("exit_code") != 0 or not case.get("checks")
                   or not all(value is True for value in case["checks"].values()) for case in formal["cases"])):
        raise ValueError("MEMORY_IMPORT_DELIVERY_NOT_VERIFIED")
    read_ref(formal["assembly_ref"], document=False)
    # 为什么要有它：验收必须绑定编译通过的字节；同字节的交付副本仍然有效。
    if formal["assembly_ref"]["sha256"] != passed["built_artifact_ref"]["sha256"]:
        raise ValueError("MEMORY_IMPORT_FORMAL_DLL_NOT_COMPILED")
    if formal["assembly_ref"] not in delivery["evidence_refs"]:
        raise ValueError("MEMORY_IMPORT_FORMAL_DLL_NOT_BOUND")
    for case in formal["cases"]:
        request = read_ref(case["request_ref"])
        observed = read_ref(case["stdout_ref"])
        expected_hash = passed["built_artifact_ref"]["sha256"]
        # 为什么要有它：顶层引用一致仍可能拼入其他 DLL 的原始执行记录。
        assembly = request.get("assembly") if isinstance(request, dict) else None
        if (not isinstance(assembly, dict) or assembly.get("sha256") != expected_hash
                or not isinstance(observed, dict) or observed.get("assembly_sha256") != expected_hash):
            raise ValueError("MEMORY_IMPORT_FORMAL_CASE_DLL_NOT_BOUND")
        read_ref(case["stderr_ref"], document=False)
    run_root = Path(journal_ref["path"]).resolve().parents[2]
    source_paths = passed["materialized_code_identity"]["files"]
    if len(source_paths) != 1:
        raise ValueError("MEMORY_IMPORT_SOURCE_SCOPE_INVALID")
    source = (run_root / source_paths[0]).resolve(strict=True)
    if not source.is_relative_to(run_root) or source.read_bytes() != after.encode():
        raise ValueError("MEMORY_IMPORT_DELIVERED_SOURCE_CHANGED")
    relative = Path(dependency_relative_path)
    dependency_root = Path(passed["dependency_copy"]["isolated_copy"]).resolve(strict=True)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".dll":
        raise ValueError("MEMORY_IMPORT_DEPENDENCY_SCOPE_INVALID")
    from src.mod_agent.build.dependencies import _binary_tree_snapshot, _binary_tree_snapshot_sha256
    snapshot = _binary_tree_snapshot(dependency_root)
    if (_binary_tree_snapshot_sha256(snapshot) != passed["dependency_binding"]["snapshot_sha256"]
            or len(snapshot) != passed["dependency_binding"]["file_count"]):
        raise ValueError("MEMORY_IMPORT_DEPENDENCY_CHANGED")
    dependency_ref = file_ref(dependency_root / relative)
    model_identity = journal["factory_receipt"]["model_identity"]
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    refs["manifest"] = file_ref(run_root / "run_manifest.json")
    return {"schema_version": "observed_member_repair_candidate_v1", "status": "candidate_pending_transfer",
        "extractor_ref": file_ref(__file__), "run_id": journal["parent_product_run_id"],
        "request": manifest["request"], "source_refs": refs,
        "compiler_failure": diagnostic, "member_substitution": {"receiver_type": receiver_type,
            "receiver_expression": left.group("receiver"), "failed_member": old_member, "passed_member": new_member},
        "source_code_hashes": {"failed": code_hashes[0], "passed": code_hashes[1]},
        "dependency_ref": dependency_ref, "dependency_relative_path": relative.as_posix(),
        "dependency_snapshot_sha256": passed["dependency_binding"]["snapshot_sha256"],
        "passed_compilation": passed["status"], "formal_dll_checks": [{"case": case["case"], "checks": case["checks"]} for case in formal["cases"]],
        "delivery_status": delivery["status"], "model_identity": model_identity,
        "authority": "planning_only", "causal_or_general_api_claim": False,
        "xml_member_presence_inferred": False, "model_calls_performed": 0}


def import_candidate(memory: TaskMemory, *, candidate_ref):
    candidate = read_ref(candidate_ref)
    if candidate.get("schema_version") != "observed_member_repair_candidate_v1" or candidate.get("authority") != "planning_only":
        raise ValueError("MEMORY_IMPORT_CANDIDATE_INVALID")
    inputs = candidate["source_refs"]
    reproduced = extract_member_repair(journal_ref=inputs["journal"], failed_report_ref=inputs["failed_compilation"],
        passed_report_ref=inputs["passed_compilation"], recurrence_report_ref=inputs["recurring_failure"],
        delivery_ref=inputs["delivery"], formal_checks_ref=inputs["formal_checks"],
        dependency_relative_path=candidate["dependency_relative_path"])
    if reproduced != candidate:
        raise ValueError("MEMORY_IMPORT_CANDIDATE_NOT_REPRODUCIBLE")
    refs = [{"evidence_id": "candidate", "kind": "json_file", **candidate_ref},
            *[{"evidence_id": key, "kind": "json_file", **ref} for key, ref in candidate["source_refs"].items()]]
    lesson_id = "member-repair:" + candidate_ref["sha256"]
    current = memory.current(lesson_id)
    if current is not None:
        return asdict(current)
    scope = candidate["dependency_ref"]["sha256"] + ":" + candidate["member_substitution"]["receiver_type"]
    fields = (("member_substitution", "verified_result"), ("compiler_failure", "failure"),
              ("passed_compilation", "verified_result"), ("formal_dll_checks", "verified_result"))
    ref = memory.record(lesson_id=lesson_id, evidence_refs=refs,
        request={"evidence_id": "candidate", "locator": ["request"]},
        facts=[{"scope": scope, "key": key, "role": role, "evidence_id": "candidate", "locator": [key]} for key, role in fields],
        outcome={"evidence_id": "candidate", "locator": ["delivery_status"]},
        applicability={"dependency_dll_sha256:" + candidate["dependency_relative_path"]: candidate["dependency_ref"]["sha256"],
                       "model_digest": candidate["model_identity"]["digest"]},
        unknowns=["Transfer effectiveness is not yet measured; the two selected tasks are exposed development transfer tasks.",
                  "The member substitution is observed in one accepted implementation, not a general API guarantee or permission."],
        invalidation_conditions=["Reject changed source records, dependency DLL or model digest. 为什么要有它：历史通过不能替代当前版本适用性。",
                                 "Withdraw from default use if paired transfer fails or misleads. 为什么要有它：经验必须由新任务效果决定取舍。"])
    return asdict(ref)
