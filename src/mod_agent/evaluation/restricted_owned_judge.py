"""Host-private JSON assertions over real restricted C# process observations.

The trusted host owns case selection and comparison. Candidate code runs only
through restricted_csharp; this is not isolation from arbitrary trusted-host
code. No hidden cases, expectations or private report paths enter model feedback.
为什么要有它：实际容器约束保护host判定材料，不能用callback名称或process标签冒充执行隔离。
"""
from __future__ import annotations

import codecs
import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from uuid import uuid4

from scripts import prepare_lease_scope_subject_worker as public_worker
from scripts import run_lease_scope_trusted_cases as trusted_cases
from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.evaluation import restricted_csharp as runtime
from src.mod_agent.evaluation.independent_product_adapter import project_owned_judge_result
from src.mod_agent.evaluation.independent_release import validate_protected_judge_result
from src.mod_agent.execution.patch_apply import materialize_exact_text_patch
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector

TASK_ID = "private_eval_20260909_lease_scope_001"
WORKER_NAME = "__public_lease_scope_worker__.cs"
CASE_BUNDLE_SCHEMA = "restricted_csharp_case_bundle_v1"
PUBLIC_DEVELOPMENT_SCHEMA = "restricted_csharp_public_development_cases_v1"
PUBLIC_DEVELOPMENT_ELIGIBILITY = "public_development_only_not_independent_acceptance"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_OPERATIONS = {"FailOpen", "Records", "ThrowOnRecord", "PreopenCallerHandle"}


def _require(value, code):
    if not value:
        raise ValueError("RESTRICTED_JUDGE_" + code)


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def _reference_bytes(reference):
    _require(isinstance(reference, Mapping) and set(reference) == {"path", "sha256"}
             and isinstance(reference["sha256"], str) and _SHA.fullmatch(reference["sha256"]), "REFERENCE_INVALID")
    path = Path(reference["path"])
    _require(path.is_absolute(), "REFERENCE_INVALID")
    raw = runtime._read_bytes(path)
    _require(_hash(raw) == reference["sha256"], "REFERENCED_BYTES_CHANGED")
    return raw


def _read(reference):
    return _json(_reference_bytes(reference))


def _cases(reference, task_id, *, schema=CASE_BUNDLE_SCHEMA):
    document = _read(reference)
    _require(isinstance(document, dict) and set(document) == {"schema_version", "task_id", "eligibility", "cases"}
             and document["schema_version"] == schema
             and isinstance(task_id, str) and task_id.strip() and document["task_id"] == task_id
             and isinstance(document["eligibility"], str) and document["eligibility"].strip()
             and isinstance(document["cases"], list) and 1 <= len(document["cases"]) <= 64, "CASE_SET_INVALID")
    seen = set()
    for case in document["cases"]:
        _require(isinstance(case, dict) and set(case) == {"case_id", "operation", "assertions"}
                 and isinstance(case["case_id"], str) and case["case_id"] and case["case_id"] not in seen,
                 "CASE_INVALID")
        seen.add(case["case_id"])
        encoded = json.dumps(case["operation"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        _require(len(encoded) <= runtime.OPERATION_LIMIT, "OPERATION_LIMIT")
        _require(isinstance(case["assertions"], list) and case["assertions"], "ASSERTIONS_REQUIRED")
        for assertion in case["assertions"]:
            _require(isinstance(assertion, dict) and set(assertion) == {"path", "equals"}
                     and isinstance(assertion["path"], list)
                     and all(isinstance(key, str) or (type(key) is int and key >= 0) for key in assertion["path"]),
                     "ASSERTION_INVALID")
    return document


class RestrictedCSharpEvaluator:
    case_schema = CASE_BUNDLE_SCHEMA
    worker_name = "__public_observation_worker__.cs"
    check_prefix = "restricted_csharp"
    verification_scope = "restricted_csharp_behavior_not_product_delivery"

    def __init__(self, *, workspace_root, artifact_store_root, source_files, case_bundle_ref,
                 public_worker_source_ref, output_root, private_output_root, task_id,
                 public_case_bundle_ref=None):
        self.workspace = Path(workspace_root).resolve(strict=True)
        self.store = ArtifactStore(artifact_store_root)
        self.output = Path(output_root).resolve()
        self.private_output = Path(private_output_root).resolve()
        self.cases_ref, self.task_id = dict(case_bundle_ref), task_id
        self.public_cases_ref = deepcopy(public_case_bundle_ref)
        self.worker_ref = deepcopy(public_worker_source_ref)
        _require(self.output != self.workspace and self.output.is_relative_to(self.workspace)
                 and not self.private_output.is_relative_to(self.workspace)
                 and not self.workspace.is_relative_to(self.private_output)
                 and not Path(self.cases_ref["path"]).resolve().is_relative_to(self.workspace), "PRIVATE_SCOPE_REQUIRED")
        _require(isinstance(source_files, dict) and 1 <= len(source_files) <= 15, "SOURCE_MANIFEST_REQUIRED")
        self.sources = dict(source_files)
        for name, digest in self.sources.items():
            _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.cs", name)
                     and ".." not in PurePosixPath(name).parts and name.casefold() != self.worker_name.casefold()
                     and isinstance(digest, str) and _SHA.fullmatch(digest), "SOURCE_MANIFEST_INVALID")
        _require(len({name.casefold() for name in self.sources}) == len(self.sources), "SOURCE_PATH_COLLISION")
        self._case_set = self._case_document()
        self._public_case_set = self._public_case_document()
        self._originals = self._source_bytes()
        self._identity = self._current_identity()

    @property
    def check_ids(self):
        private_ids = tuple(f"{self.check_prefix}.{index:05d}" for index in range(
            sum(len(case["assertions"]) for case in self._case_set["cases"])))
        public_ids = tuple(f"public_development.{index:05d}" for index in range(
            sum(len(case["assertions"]) for case in (self._public_case_set or {}).get("cases", []))))
        return private_ids + public_ids

    def _case_document(self):
        return _cases(self.cases_ref, self.task_id, schema=self.case_schema)

    def _public_case_document(self):
        if self.public_cases_ref is None:
            return None
        # 为什么要有它：只有显式公开schema和独立来源才能披露逐例反馈；默认私有断言绝不转换为公开反馈。
        _require(Path(self.public_cases_ref["path"]).resolve() != Path(self.cases_ref["path"]).resolve()
                 and self.public_cases_ref["sha256"] != self.cases_ref["sha256"], "PUBLIC_CASE_SOURCE_REQUIRED")
        value = _cases(self.public_cases_ref, self.task_id, schema=PUBLIC_DEVELOPMENT_SCHEMA)
        _require(value["eligibility"] == PUBLIC_DEVELOPMENT_ELIGIBILITY, "PUBLIC_CASE_ELIGIBILITY_REQUIRED")
        return value

    def _worker_bytes(self):
        value = _reference_bytes(self.worker_ref)
        path = Path(self.worker_ref["path"])
        _require(path.suffix.lower() == ".cs" and path.resolve() != Path(self.cases_ref["path"]).resolve()
                 and 0 < len(value) <= runtime.SOURCE_LIMIT, "PUBLIC_WORKER_SOURCE_INVALID")
        value.decode("utf-8")
        return value

    def _source_bytes(self):
        values = {}
        for name, digest in self.sources.items():
            path = self.workspace / name
            _require(path.resolve().is_relative_to(self.workspace), "SOURCE_ESCAPE")
            value = runtime._read_bytes(path)
            _require(_hash(value) == digest, "SOURCE_CHANGED")
            values[name] = value
        return values

    def _current_identity(self):
        self._source_bytes()
        _require(self._case_document() == self._case_set, "CASE_SET_CHANGED")
        _require(self._public_case_document() == self._public_case_set, "PUBLIC_CASE_SET_CHANGED")
        inputs = {"sources": self.sources, "cases_sha256": self.cases_ref["sha256"], "task_id": self.task_id}
        if self.public_cases_ref is not None:
            inputs["public_development_cases_sha256"] = self.public_cases_ref["sha256"]
        return {"validator_sha256": canonical_hash({"bridge": runtime._ref(Path(__file__)),
                    "runtime": runtime._ref(Path(runtime.__file__)),
                    "public_worker": _hash(self._worker_bytes()),
                    "comparison": runtime._ref(Path(trusted_cases.__file__))}),
                "inputs_sha256": canonical_hash(inputs),
                "environment_sha256": canonical_hash({"image": runtime.IMAGE, "sdk": runtime.SDK_VERSION,
                    "runtime": runtime.RUNTIME_VERSION, "compile_timeout": runtime.COMPILE_TIMEOUT,
                    "run_timeout": runtime.RUN_TIMEOUT, "output_limit": runtime.OUTPUT_LIMIT}),
                "deterministic_reuse_allowed": False}

    def verification_identity(self):
        _require(self._current_identity() == self._identity, "VERIFIER_CHANGED")
        return deepcopy(self._identity)

    def _materialize(self, context):
        reference = ArtifactRef(**context["implementation_plan_ref"])
        envelope = self.store.read(reference)
        plan, changes = context["implementation_plan"], context["generated_changes"]
        _require(reference.artifact_type == "implementation_plan" and envelope["status"] == "success"
                 and envelope["data"] == plan and not plan.get("blocking"), "PLAN_MISMATCH")
        inspector = PlanBoundSourceInspector(workspace_root=self.workspace, implementation_plan=plan,
                                             policy=PatchAgentLoopPolicy())
        _require(inspector.source_snapshot_sha256 == context["source_snapshot_sha256"]
                 and canonical_hash(changes) == context["generated_changes_sha256"], "CONTEXT_IDENTITY_MISMATCH")
        response = context["model_response"]
        raw = runtime._read_bytes(Path(response["path"]))
        _require(_hash(raw) == response["output_sha256"] and len(raw) == response["output_utf8_bytes"], "RESPONSE_CHANGED")
        submitted = _json(raw)["changes"]
        by_id = {row["edit_binding_id"]: row for row in submitted}
        _require(len(by_id) == len(submitted) == len(changes)
                 and set(by_id) == {row["edit_binding_id"] for row in changes}, "RESPONSE_CHANGE_SET_MISMATCH")
        materialized = materialize_exact_text_patch(workspace_root=self.workspace, diff_intent=changes, implementation_plan=plan)
        code = {"baseline_sha256": materialized.baseline_sha256, "code_sha256": materialized.code_sha256,
                "files": sorted(materialized.files)}
        _require(code == context["materialized_code_identity"] and set(materialized.files) <= set(self.sources), "CODE_IDENTITY_MISMATCH")
        bindings = {row["binding_id"]: row for row in plan["binding_registry"]["edit_bindings"]}
        for row in changes:
            original = materialized.baseline_files[bindings[row["edit_binding_id"]]["canonical_target_path"]]
            after, returned = row["patch"]["after_text"], by_id[row["edit_binding_id"]]["after_text"]
            _require(after == returned or (original.startswith(codecs.BOM_UTF8) and after == "\ufeff" + returned)
                     or (not original.startswith(codecs.BOM_UTF8) and returned == "\ufeff" + after), "RESPONSE_CODE_MISMATCH")
        return {**self._source_bytes(), **materialized.files}

    def __call__(self, context):
        identity = self.verification_identity()
        _require(context.get("verification_identity", identity) == identity, "VERIFICATION_IDENTITY_MISMATCH")
        sources = self._materialize(context)
        token = uuid4().hex
        private, public = self.private_output / token, self.output / token
        private.mkdir(parents=True, exist_ok=False)
        public.mkdir(parents=True, exist_ok=False)
        report = self._evaluate(sources, context=context, identity=identity, private=private, public=public)
        _require(self.verification_identity() == identity, "VERIFIER_CHANGED")
        return report

    def _evaluate_public_cases(self, compiled, *, context, output_root):
        rows, feedback = [], []
        executions, failed = 0, 0
        status = "passed"
        cases = self._public_case_set["cases"]
        total = sum(len(case["assertions"]) for case in cases)
        try:
            for index, case in enumerate(cases):
                observation, outcomes, result = _execute_case(compiled, case, output_root / f"public-{index:03d}")
                executions += 1
                start = len(rows)
                for offset, passed in enumerate(outcomes):
                    rows.append({"check_id": f"public_development.{start + offset:05d}", "passed": passed})
                failed += outcomes.count(False)
                if not all(outcomes):
                    feedback.append({"check_id": "public_development." + case["case_id"],
                        "origin": "explicit_public_development_case", "case_bundle_sha256": self.public_cases_ref["sha256"],
                        "public_worker_sha256": _hash(self._worker_bytes()),
                        "materialized_code_identity": deepcopy(context["materialized_code_identity"]),
                        "input": deepcopy(case["operation"]), "expected": deepcopy(case["assertions"]),
                        "observed": observation, "failed_assertion_indexes": [i for i, passed in enumerate(outcomes) if not passed],
                        "execution": {"completed": result["completed"], "exit_code": result["exit_code"],
                            "timed_out": result.get("timed_out", False),
                            "output_limit_exceeded": result.get("output_limit_exceeded", False)},
                        **({"process_diagnostics": {"stdout": result["stdout"][-2048:],
                            "stderr": result["stderr"][-2048:]}} if observation is None else {})})
            status = "behavior_failed" if failed else "passed"
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            status = "infrastructure_failed"
            feedback.append({"check_id": "public_development_execution", "origin": "explicit_public_development_case",
                "observed": {"status": "infrastructure_failed"}})
        return {"status": status, "checks": total, "failed_checks": failed, "executions": executions}, rows, feedback

    def _evaluate(self, sources, *, context, identity, private, public):
        inputs = {**sources, self.worker_name: self._worker_bytes()}
        private_rows, observations, check_rows = [], [], []
        total = sum(len(case["assertions"]) for case in self._case_set["cases"])
        failed, executions = 0, 0
        private_summary, public_summary = None, None
        status, owner, compilation_status, behavior = "infrastructure_failed", "environment", "unknown", "not_evaluated"
        compilation_ref = None
        try:
            compiled = runtime.compile_csharp(sources=inputs, output_root=private / "compile")
            compile_receipt = _read(compiled.receipt_ref)
            execution = _read(compile_receipt["execution_ref"])
            _require(compile_receipt["image"] == runtime.IMAGE
                     and compile_receipt["succeeded"] is compiled.succeeded
                     and compile_receipt["source_manifest"] == {**{name: _hash(data) for name, data in inputs.items()},
                         "sources.rsp": _hash("\n".join("/inputs/" + name for name in sorted(inputs)).encode())}, "COMPILE_RECEIPT_MISMATCH")
            _admit_execution(execution)
            if not execution["completed"]:
                raise ValueError("RESTRICTED_JUDGE_COMPILE_INCOMPLETE")
            if not compiled.succeeded:
                _require(execution["exit_code"] != 0, "COMPILE_OUTPUT_MISSING")
                status, owner, compilation_status = "behavior_failed", "patch_implementation", "failed"
                observations = [{"check_id": "csharp_compilation", "expected": {"exit_code": 0},
                                 "observed": {"exit_code": execution["exit_code"],
                                              "diagnostics": (execution["stdout"] + execution["stderr"])[-8192:]}}]
            else:
                compilation_status = "passed"
                binary = runtime._bound_bytes(Path(compiled.binary_ref["path"]), compiled.binary_ref,
                                              "RESTRICTED_JUDGE_COMPILED_OUTPUT_CHANGED")
                (public / "Subject.dll").write_bytes(binary)
                public_binary = {"path": str((public / "Subject.dll").resolve()), "sha256": compiled.binary_ref["sha256"]}
                runtime._bound_bytes(public / "Subject.dll", public_binary, "RESTRICTED_JUDGE_PUBLIC_BINARY_CHANGED")
                compilation_ref = runtime._save(public / "compilation.json", {
                    "schema_version": "restricted_owned_compilation_summary_v1", "status": "passed",
                    "execution_origin": "executed", "image": runtime.IMAGE,
                    "compiler_receipt_sha256": compiled.receipt_ref["sha256"],
                    "source_manifest": {name: _hash(value) for name, value in sources.items()},
                    "materialized_code_identity": context["materialized_code_identity"],
                    "all_supplied_sources_compiled": True, "all_required_files_compiled": True,
                    "scope": "all declared CSharp sources plus public observation worker; fixed csc, no MSBuild or deployment",
                    "public_worker_sha256": _hash(inputs[self.worker_name]),
                    "built_artifact_ref": public_binary})
                for index, case in enumerate(self._case_set["cases"]):
                    observation, outcomes, result = _execute_case(compiled, case, private / f"operation-{index:03d}")
                    executions += 1
                    bad = outcomes.count(False)
                    for passed in outcomes:
                        check_rows.append({"check_id": self.check_ids[len(check_rows)], "passed": passed})
                    failed += bad
                    private_rows.append({"case_id": case["case_id"], "assertions": case["assertions"],
                        "failed_assertions": bad, "observation": observation, "execution_ref": result["receipt_ref"]})
                status, owner, behavior = ("behavior_failed", "patch_implementation", "failed") if failed else ("passed", None, "passed")
                if failed:
                    observations = [{"check_id": "restricted_host_behavior", "expected": {"failed_checks": 0},
                                     "observed": {"checks": total, "failed_checks": failed, "executions": executions}}]
                if self._public_case_set is not None:
                    private_summary = {"status": status, "checks": total, "failed_checks": failed, "executions": executions}
                    public_summary, public_rows, public_feedback = self._evaluate_public_cases(
                        compiled, context=context, output_root=private)
                    check_rows.extend(public_rows)
                    observations.extend(public_feedback)
                    total += public_summary["checks"]
                    failed += public_summary["failed_checks"]
                    executions += public_summary["executions"]
                    # 为什么要有它：公开开发反馈不能替代原私有验收，两者都通过才允许现有交付链继续。
                    if public_summary["status"] == "infrastructure_failed":
                        status, owner = "infrastructure_failed", "environment"
                    elif public_summary["status"] == "behavior_failed":
                        status, owner, behavior = "behavior_failed", "patch_implementation", "failed"
        except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            status, owner = "infrastructure_failed", "environment"
            private_rows.append({"infrastructure_error_type": type(exc).__name__, "infrastructure_error": str(exc)})
            observations = [{"check_id": "restricted_execution", "observed": {"status": "infrastructure_failed"}}]
        private_ref = runtime._save(private / "judge-report.json", {"task_id": self.task_id,
            "cases_ref": self.cases_ref, "rows": private_rows, "status": (private_summary or {}).get("status", status),
            "candidate_source_manifest": {name: _hash(value) for name, value in sources.items()},
            "materialized_code_identity": context["materialized_code_identity"]})
        compilation_summary = _read(compilation_ref) if compilation_ref else None
        origin = "executed" if compilation_status in {"passed", "failed"} else "incomplete"
        details = runtime._save(public / "checks.json", {"status": status, "execution_origin": origin,
            "checks": check_rows, "executions": executions, "materialized_code_identity": context["materialized_code_identity"],
            "built_artifact_ref": compilation_summary["built_artifact_ref"] if compilation_summary else None,
            "compilation_report_ref": compilation_ref,
            "detail_policy": "opaque check IDs and pass flags only; operations and assertions remain host-private"
                if self._public_case_set is None else
                "private checks are opaque; explicit public development failures are disclosed in report observations"})
        report = {"schema_version": "restricted_owned_behavior_v1", "status": status, "failure_owner": owner,
            "owner_binding_ids": sorted({row["edit_binding_id"] for row in context["generated_changes"]}) if owner == "patch_implementation" else [],
            "observations": observations, "generated_changes_sha256": context["generated_changes_sha256"],
            "source_snapshot_sha256": context["source_snapshot_sha256"],
            "model_response_sha256": context["model_response"]["output_sha256"],
            "materialized_code_identity": context["materialized_code_identity"], "implementation_plan_ref": context["implementation_plan_ref"],
            "verification_identity": identity, "execution_origin": origin,
            "verification_summary": {"checks": total if compilation_status == "passed" else 0,
                                     "failed_checks": failed, "executions": executions},
            "preservation_passed": True if status == "passed" else None,
            "compilation": compilation_status, "behavior": behavior,
            "verification_ref": details,
            "validation_results": {"full_compilation": {"status": compilation_status,
                "all_required_files_compiled": compilation_status == "passed", "report_ref": compilation_ref}},
            "compilation_report_ref": compilation_ref, "private_report_sha256": private_ref["sha256"],
            "judge_boundary": "trusted_host_comparison_with_fixed_image_restricted_candidate_container",
            "private_material_isolated_from": "candidate_container; not arbitrary trusted-host code",
            "eligibility": self._case_set["eligibility"], "model_calls": 0,
            "verification_scope": self.verification_scope}
        if self._public_case_set is not None:
            report.update(private_summary=private_summary or {
                "status": status, "checks": total if compilation_status == "passed" else 0,
                "failed_checks": failed, "executions": executions},
                public_development_summary=public_summary or {
                    "status": "not_evaluated", "checks": 0, "failed_checks": 0, "executions": 0},
                public_development_source={"schema_version": PUBLIC_DEVELOPMENT_SCHEMA,
                    "eligibility": PUBLIC_DEVELOPMENT_ELIGIBILITY,
                    "case_bundle_sha256": self.public_cases_ref["sha256"], "public_worker_sha256": _hash(self._worker_bytes())})
        reference = runtime._save(public / "report.json", report)
        return {**report, "report_ref": reference}


def _execute_case(compiled, case, output_root):
    returned = runtime.run_csharp(compilation=compiled, operation=deepcopy(case["operation"]), output_root=output_root)
    result = _read(returned["receipt_ref"])
    _require(result == {key: value for key, value in returned.items() if key != "receipt_ref"}
             and result["compilation_receipt_ref"] == compiled.receipt_ref
             and result["stdin_sha256"] == canonical_hash(case["operation"])
             and result["host_judge_material_mounted"] is False, "OPERATION_RECEIPT_MISMATCH")
    _admit_execution(result)
    _require(result["completed"] or result.get("timed_out") is True
             or result.get("output_limit_exceeded") is True, "RUNTIME_TRANSPORT_INCOMPLETE")
    observation, outcomes = None, [False] * len(case["assertions"])
    if result["completed"] and result["exit_code"] == 0:
        try:
            observation = _json(result["stdout"])
            outcomes = [_assertion_passed(observation, assertion) for assertion in case["assertions"]]
        except (TypeError, ValueError):
            pass
    return observation, outcomes, {**result, "receipt_ref": returned["receipt_ref"]}


def _admit_execution(result):
    _require(result["image"] == runtime.IMAGE and result["inspect_policy_verified"] is True
             and isinstance(result["container_id"], str) and _SHA.fullmatch(result["container_id"])
             and result["implementation_ref"] == runtime._ref(Path(runtime.__file__))
             and result["container_state"]["Running"] is False, "EXECUTION_NOT_VERIFIED")


def _assertion_passed(observation, assertion):
    try:
        return canonical_hash(trusted_cases._select(observation, assertion["path"])) == canonical_hash(assertion["equals"])
    except (TypeError, ValueError):
        return False


def aggregate_result(report, *, context):
    """Existing release aggregate shape, with no private reports or case values."""
    result = project_owned_judge_result(report, context=context, verification_identity=report["verification_identity"])
    return validate_protected_judge_result(result, context=context, verification_identity=report["verification_identity"])


class RestrictedLeaseScopeEvaluator(RestrictedCSharpEvaluator):
    """Existing exposed-development entry; its operation schema stays narrow."""
    case_schema = "lease_scope_trusted_cases_v1"
    worker_name = WORKER_NAME
    check_prefix = "lease_scope"
    verification_scope = "lease_scope_development_csharp_behavior_not_product_delivery"

    def __init__(self, *, cases_ref, task_id=TASK_ID, **kwargs):
        super().__init__(case_bundle_ref=cases_ref, public_worker_source_ref=None, task_id=task_id, **kwargs)

    def _worker_bytes(self):
        return public_worker.WORKER_SOURCE.encode()

    def _case_document(self):
        document = super()._case_document()
        _require(self.task_id == TASK_ID and document["eligibility"].startswith("development"), "CASE_SET_INVALID")
        for case in document["cases"]:
            operation = case["operation"]
            _require(isinstance(operation, dict) and set(operation) <= _OPERATIONS, "OPERATION_FIELDS_INVALID")
            for name, value in operation.items():
                valid = ((value is None or isinstance(value, str)) if name in {"FailOpen", "ThrowOnRecord"}
                         else type(value) is bool if name == "PreopenCallerHandle"
                         else isinstance(value, list) and all(isinstance(item, str) for item in value))
                _require(valid, "OPERATION_VALUE_INVALID")
            _require(all(assertion["path"] for assertion in case["assertions"]), "ASSERTION_INVALID")
        return document


def make_restricted_csharp_evaluator(**kwargs):
    """Current worker factory entry with explicit public-driver and private-case refs.

    为什么要有它：平台冻结后由author发布driver/cases即可换题，既不按任务改平台，也不将预期放进候选容器。
    """
    return RestrictedCSharpEvaluator(**kwargs)


def make_lease_scope_evaluator(**kwargs):
    """Existing PatchWorkerConfiguration factory_ref/factory_name/kwargs entry."""
    return RestrictedLeaseScopeEvaluator(**kwargs)
