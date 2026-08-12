"""Offline two-slice fixture validator.

This module verifies reproducible inputs, evidence recomputation,
leakage boundaries, and annotation bindings.

It does not determine data-readiness approval, RAG quality,
evaluation promotion, or product authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.mod_agent.evaluation.arm_a import RunManifestCollector
from src.mod_agent.evidence.gtfo_r8 import R8_EXPECTED_SHA256
from src.mod_agent.evidence.r8_il import BoundILInspectionRunner, R8_IL_SYMBOLS


CASE_NAMES = ("better_hit_feedback", "wall_crawler")
SEARCH_ROOT_ALLOWLIST = ("Assets/Scripts/Modules-ASM", "Datablocks")
PROJECTION_REFS = {
    "current_api_metadata_il_facts": "evidence/better_hit_feedback_current_il_projection.json",
    "historical_implementation_and_runtime_support_facts": "evidence/better_hit_feedback_runtime_projection.json",
    "r8_api_metadata_il_and_coverage_facts": "evidence/wall_crawler_r8_il_projection.json",
}
FORBIDDEN_REQUEST_LITERALS = {
    "better_hit_feedback": (
        "ES_Hitreact",
        "ActivateState",
        "BulletDamage",
        "OnTakeDamage",
        "HitFeedbackBehaviorPatch",
        "STAGGER_FEEDBACK_SHOWN",
    ),
    "wall_crawler": (
        "ES_PathMove",
        "CommonFixedUpdate",
        "UpdateRotation",
        "R8_METHOD_BODY_STUB_ONLY",
    ),
}
JUDGMENT_FIELDS = (
    "required_evidence",
    "forbidden_evidence",
    "acceptable_hook_full_identities",
    "forbidden_hook_full_identities",
    "required_missing_evidence",
    "expected_sufficiency",
    "expected_control_action",
)
CANONICAL_JSON_KWARGS = {
    "ensure_ascii": False,
    "sort_keys": True,
    "separators": (",", ":"),
}


class FixtureValidationError(ValueError):
    """Raised when fixture content or a supplied input does not match."""


class FixtureInputBlockedError(FixtureValidationError):
    """Raised when a required lawful external input cannot be obtained."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, **CANONICAL_JSON_KWARGS).encode("utf-8")
    return _sha256_bytes(raw)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FixtureValidationError(f"Cannot read exact JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise FixtureValidationError(f"Expected one JSON object: {path}")
    return value


def _require_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise FixtureValidationError(message)


def _external_input(
    manifest: dict[str, Any], logical_role: str
) -> dict[str, Any]:
    rows = manifest.get("external_inputs")
    if not isinstance(rows, list):
        raise FixtureValidationError("Manifest external_inputs must be a list.")
    matches = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("logical_role") == logical_role
    ]
    if len(matches) != 1:
        raise FixtureValidationError(
            f"Manifest requires exactly one external input role: {logical_role}"
        )
    return matches[0]


def _projection(logical_role: str) -> dict[str, Any]:
    ref = PROJECTION_REFS[logical_role]
    path = PACKAGE_ROOT / Path(*ref.split("/"))
    if not path.is_file():
        raise FixtureValidationError(f"Projection is missing: {ref}")
    return _load_object(path)


def _build_inspector(temp_root: Path) -> Path:
    project = REPOSITORY_ROOT / "scripts" / "r8_il_inspector" / "r8_il_inspector.csproj"
    if not project.is_file():
        raise FixtureValidationError("Repository IL inspector project is missing.")
    output = temp_root / "bin"
    intermediate = temp_root / "obj"
    completed = subprocess.run(
        (
            "dotnet",
            "build",
            str(project),
            "--configuration",
            "Release",
            "--output",
            str(output),
            f"-p:BaseIntermediateOutputPath={intermediate.as_posix()}/",
            f"-p:MSBuildProjectExtensionsPath={intermediate.as_posix()}/",
        ),
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise FixtureValidationError(
            f"Read-only IL inspector build failed: dotnet build exit={completed.returncode}"
        )
    inspector = output / "r8_il_inspector.dll"
    if not inspector.is_file():
        raise FixtureValidationError("Repository IL inspector output is missing.")
    return inspector


def _method_projection(report: dict[str, Any]) -> list[dict[str, Any]]:
    methods = report.get("methods")
    if not isinstance(methods, list):
        raise FixtureValidationError("IL report methods are missing.")
    projected: list[dict[str, Any]] = []
    for method in methods:
        if not isinstance(method, dict):
            raise FixtureValidationError("IL report contains a non-object method.")
        row = {
            key: method[key]
            for key in (
                "symbol",
                "metadata_token",
                "signature_blob",
                "has_method_body",
                "rva",
            )
        }
        if "il_bytes" in method:
            row["il_bytes"] = method["il_bytes"]
        projected.append(row)
    return projected


def _validate_retrieval_boundary(
    manifest: dict[str, Any],
    request_text: str,
    case_name: str,
) -> None:
    scope = manifest.get("actual_retrieval_scope")
    snapshot = manifest.get("canonical_corpus_snapshot")
    if not isinstance(scope, dict) or not isinstance(snapshot, dict):
        raise FixtureValidationError("Retrieval scope or corpus snapshot is missing.")
    _require_equal(scope.get("mode"), "allowlist_only", "retrieval mode drift")
    _require_equal(
        tuple(scope.get("search_root_allowlist", ())),
        SEARCH_ROOT_ALLOWLIST,
        "retrieval allowlist drift",
    )
    _require_equal(
        tuple(snapshot.get("search_root_allowlist", ())),
        SEARCH_ROOT_ALLOWLIST,
        "snapshot root allowlist drift",
    )
    excluded = scope.get("excluded_source_classes")
    if not isinstance(excluded, list) or not all(isinstance(x, str) for x in excluded):
        raise FixtureValidationError("Retrieval excluded-source classes are missing.")
    literals = FORBIDDEN_REQUEST_LITERALS[case_name]
    hits = [literal for literal in literals if literal.casefold() in request_text.casefold()]
    _require_equal(hits, [], "request contains a forbidden complete-answer literal")


def _validate_request_and_annotation(
    case_root: Path,
    manifest: dict[str, Any],
    case_name: str,
) -> str:
    request_spec = manifest.get("request")
    if not isinstance(request_spec, dict):
        raise FixtureValidationError("Manifest request identity is missing.")
    expected_ref = request_spec.get("ref")
    request_path = case_root / "request.txt"
    _require_equal(
        expected_ref,
        request_path.relative_to(REPOSITORY_ROOT).as_posix(),
        "request ref drift",
    )
    request_text = request_path.read_text(encoding="utf-8").rstrip("\n")
    _require_equal(
        _sha256_file(request_path),
        request_spec.get("sha256"),
        "request hash drift",
    )
    _validate_retrieval_boundary(manifest, request_text, case_name)

    annotation_path = case_root / "annotation.json"
    annotation = _load_object(annotation_path)
    _require_equal(
        annotation.get("case_identity"),
        manifest.get("case_identity"),
        "annotation case identity drift",
    )
    payload = annotation.get("judgment_payload")
    if not isinstance(payload, dict):
        raise FixtureValidationError("Annotation judgment_payload is missing.")
    _require_equal(tuple(payload), JUDGMENT_FIELDS, "judgment payload field drift")
    calculated = _canonical_sha256(payload)
    _require_equal(
        annotation.get("proposed_judgment_hash"),
        calculated,
        "proposed judgment hash drift",
    )
    _require_equal(
        annotation.get("technical_review_authority"),
        "independently_model_reviewed_technical_calibration_annotation",
        "technical review authority drift",
    )
    _require_equal(
        annotation.get("evidence_projection_relationship"),
        "evidence projection may support annotation creation, but annotation judgment is not mechanically derived from projection",
        "projection/annotation relationship drift",
    )
    confirmation = annotation.get("operator_confirmation")
    if not isinstance(confirmation, dict):
        raise FixtureValidationError("operator_confirmation is missing.")
    status = confirmation.get("final_payload_product_semantics_status")
    frozen_hash = annotation.get("frozen_judgment_hash")
    if status == "pending":
        _require_equal(frozen_hash, None, "pending judgment must not be frozen")
        _require_equal(
            annotation.get("technical_calibration_annotation_status"),
            "provisional_pending_operator_product_semantics_confirmation",
            "provisional annotation status drift",
        )
        annotation_binding_state = "provisional"
    elif status == "confirmed":
        _require_equal(frozen_hash, calculated, "frozen judgment hash drift")
        _require_equal(
            annotation.get("technical_calibration_annotation_status"),
            "frozen_after_operator_product_semantics_confirmation",
            "frozen annotation status drift",
        )
        if not confirmation.get("final_payload_confirmed_by") or not confirmation.get("final_payload_confirmed_at"):
            raise FixtureValidationError("confirmed product semantics lacks operator identity or time")
        annotation_binding_state = "frozen"
    else:
        raise FixtureValidationError("operator confirmation status is invalid.")
    return annotation_binding_state


def _validate_corpus_and_sources(
    manifest: dict[str, Any],
    r8_root: Path,
    *,
    require_r8_owner_match: bool,
) -> None:
    snapshot_spec = manifest.get("canonical_corpus_snapshot")
    if not isinstance(snapshot_spec, dict):
        raise FixtureValidationError("Canonical corpus snapshot is missing.")
    before = RunManifestCollector(r8_root).canonical_corpus_snapshot(
        SEARCH_ROOT_ALLOWLIST
    )
    _require_equal(
        before.corpus_snapshot_sha256,
        snapshot_spec.get("corpus_snapshot_sha256"),
        "canonical corpus snapshot drift",
    )
    _require_equal(
        len(before.files),
        snapshot_spec.get("file_count"),
        "canonical corpus file count drift",
    )

    included = manifest.get("included_sources")
    if not isinstance(included, list) or not included:
        raise FixtureValidationError("included_sources is missing.")
    verified_owner_sources: dict[str, str] = {}
    for row in included:
        if not isinstance(row, dict):
            raise FixtureValidationError("included_sources contains a non-object.")
        relative = row.get("relative_path")
        if not isinstance(relative, str) or not relative:
            raise FixtureValidationError("included source relative_path is invalid.")
        path = (r8_root / Path(*relative.split("/"))).resolve()
        try:
            path.relative_to(r8_root)
        except ValueError as exc:
            raise FixtureValidationError("included source escapes --r8-root") from exc
        if not path.is_file():
            raise FixtureInputBlockedError(
                f"Required included source is unavailable: {relative}"
            )
        _require_equal(
            _sha256_file(path), row.get("sha256"), f"included source hash drift: {relative}"
        )
        _require_equal(
            path.stat().st_size,
            row.get("size_bytes"),
            f"included source size drift: {relative}",
        )
        if row.get("authority") == "R8_EXPECTED_SHA256":
            verified_owner_sources[relative] = row["sha256"]
    if require_r8_owner_match:
        _require_equal(
            verified_owner_sources,
            R8_EXPECTED_SHA256,
            "R8_EXPECTED_SHA256 drift",
        )

    after = RunManifestCollector(r8_root).canonical_corpus_snapshot(
        SEARCH_ROOT_ALLOWLIST
    )
    _require_equal(after, before, "corpus changed during local replay")


def _validate_bhf_evidence(
    manifest: dict[str, Any],
    inspector: Path,
    r8_root: Path,
    current_interop: Path,
    historical_implementation_path: Path,
    runtime_result_path: Path,
    bounded_log_path: Path,
    full_log_path: Path,
) -> None:
    assembly_input = _external_input(manifest, "current_interop_assembly")
    if not current_interop.is_file():
        raise FixtureInputBlockedError("--current-interop-assembly is unavailable.")
    _require_equal(
        _sha256_file(current_interop),
        assembly_input.get("expected_sha256"),
        "current interop assembly hash drift",
    )
    il_projection = _projection("current_api_metadata_il_facts")
    methods = il_projection.get("methods")
    if not isinstance(methods, list) or not methods:
        raise FixtureValidationError("BHF IL methods are missing.")
    symbols = tuple(row["symbol"] for row in methods)
    report = BoundILInspectionRunner(inspector, symbols=symbols).inspect(
        current_interop
    )
    _require_equal(
        report.get("assembly_sha256"),
        assembly_input.get("expected_sha256"),
        "BHF inspected assembly hash drift",
    )
    _require_equal(
        report.get("module_mvid"),
        assembly_input.get("expected_mvid"),
        "BHF inspected assembly MVID drift",
    )
    observed_methods = _method_projection(report)
    expected_keys = (
        "symbol",
        "metadata_token",
        "signature_blob",
        "has_method_body",
        "rva",
    )
    _require_equal(
        [{key: row[key] for key in expected_keys} for row in observed_methods],
        [{key: row[key] for key in expected_keys} for row in methods],
        "BHF API/metadata/IL fact drift",
    )
    _require_equal(report.get("target_code_executed"), False, "BHF target execution drift")
    source_api_facts = il_projection.get("source_api_facts")
    if not isinstance(source_api_facts, list) or not source_api_facts:
        raise FixtureValidationError("BHF source API facts are missing.")
    for row in source_api_facts:
        if not isinstance(row, dict):
            raise FixtureValidationError("BHF source API fact is invalid.")
        relative = row.get("relative_path")
        facts = row.get("facts")
        if not isinstance(relative, str) or not isinstance(facts, list):
            raise FixtureValidationError("BHF source API fact protocol is invalid.")
        source_path = r8_root / Path(*relative.split("/"))
        if not source_path.is_file():
            raise FixtureInputBlockedError(f"BHF source API input is unavailable: {relative}")
        source_text = source_path.read_text(encoding="utf-8")
        if not all(isinstance(fact, str) and fact in source_text for fact in facts):
            raise FixtureValidationError(f"BHF source API fact drift: {relative}")
        if not any(
            isinstance(included, dict) and included.get("relative_path") == relative
            for included in manifest.get("included_sources", [])
        ):
            raise FixtureValidationError(f"BHF source API input identity is missing: {relative}")

    runtime_projection = _projection(
        "historical_implementation_and_runtime_support_facts"
    )
    supplied = {
        "bhf_historical_successful_implementation": historical_implementation_path,
        "bhf_runtime_result": runtime_result_path,
        "bhf_runtime_bounded_log": bounded_log_path,
        "bhf_runtime_full_log": full_log_path,
    }
    specs = {role: _external_input(manifest, role) for role in supplied}
    for role, path in supplied.items():
        if not path.is_file():
            raise FixtureInputBlockedError(f"Runtime input is unavailable: {role}")
        _require_equal(
            _sha256_file(path),
            specs[role].get("expected_sha256"),
            f"Runtime input hash drift: {role}",
        )
        _require_equal(
            path.stat().st_size,
            specs[role].get("size_bytes"),
            f"Runtime input size drift: {role}",
        )

    historical_extraction = runtime_projection.get("historical_implementation_extraction")
    if not isinstance(historical_extraction, dict):
        raise FixtureValidationError("Historical implementation extraction is missing.")
    _require_equal(
        _sha256_file(historical_implementation_path),
        historical_extraction.get("source_sha256"),
        "Historical implementation projection source hash drift",
    )
    historical_source = historical_implementation_path.read_text(encoding="utf-8")
    source_facts = historical_extraction.get("source_facts")
    if not isinstance(source_facts, list) or not all(
        isinstance(fact, str) for fact in source_facts
    ):
        raise FixtureValidationError("Historical implementation extraction protocol drift")
    if not all(fact in historical_source for fact in source_facts):
        raise FixtureValidationError("Historical implementation fact drift")

    runtime_result = _load_object(runtime_result_path)
    expected_bindings = runtime_projection.get("runtime_result_bindings")
    if not isinstance(expected_bindings, dict):
        raise FixtureValidationError("Runtime-result bindings are missing.")
    _require_equal(
        runtime_result.get("run_id"),
        expected_bindings.get("run_id"),
        "Runtime run_id drift",
    )
    _require_equal(
        runtime_result.get("feature_id"),
        expected_bindings.get("feature_id"),
        "Runtime feature_id drift",
    )
    repair_attempt = runtime_result.get("repair_attempt")
    if not isinstance(repair_attempt, dict):
        raise FixtureValidationError("Runtime repair_attempt is missing.")
    for key in ("source_sha256", "source_snapshot_sha256", "dll_sha256", "diff_hash"):
        _require_equal(
            repair_attempt.get(key),
            expected_bindings.get(key),
            f"Runtime {key} drift",
        )
    identities = runtime_result.get("run_local_log_identities")
    enabled = identities.get("general_enabled_true") if isinstance(identities, dict) else None
    if not isinstance(enabled, dict):
        raise FixtureValidationError("Runtime log identities are missing.")
    for runtime_key, role in (
        ("bounded_projection", "bhf_runtime_bounded_log"),
        ("post_run_full_copy", "bhf_runtime_full_log"),
    ):
        identity = enabled.get(runtime_key)
        if not isinstance(identity, dict):
            raise FixtureValidationError(f"Runtime log identity is missing: {runtime_key}")
        _require_equal(
            str(identity.get("sha256", "")).upper(),
            specs[role].get("expected_sha256"),
            f"Runtime-result log hash drift: {runtime_key}",
        )
        _require_equal(
            identity.get("size_bytes"),
            specs[role].get("size_bytes"),
            f"Runtime-result log size drift: {runtime_key}",
        )

    extraction = runtime_projection.get("raw_log_extraction")
    if not isinstance(extraction, dict):
        raise FixtureValidationError("Runtime raw-log extraction is missing.")
    result_marker = extraction.get("result_marker")
    damage_marker = extraction.get("damage_input_marker")
    predicates = extraction.get("required_result_predicates")
    if (
        not isinstance(result_marker, str)
        or not isinstance(damage_marker, str)
        or not isinstance(predicates, list)
        or not all(isinstance(item, str) for item in predicates)
    ):
        raise FixtureValidationError("Runtime extraction protocol is invalid.")
    for role, expected_key in (
        ("bhf_runtime_bounded_log", "enabled_bounded_log"),
        ("bhf_runtime_full_log", "enabled_full_log"),
    ):
        text = supplied[role].read_text(encoding="utf-8")
        lines = text.splitlines()
        result_lines = [line for line in lines if result_marker in line]
        damage_lines = [line for line in lines if damage_marker in line]
        if not result_lines:
            raise FixtureValidationError(f"Runtime result marker is absent: {role}")
        if not all(
            all(predicate in line for predicate in predicates)
            for line in result_lines
        ):
            raise FixtureValidationError(f"Runtime result predicate drift: {role}")
        observed = {
            "line_count": len(lines),
            "result_marker_count": len(result_lines),
            "damage_input_marker_count": len(damage_lines),
            "observed_reaction_types": sorted(
                set(re.findall(r"reaction_type=([^ ]+)", "\n".join(result_lines)))
            ),
        }
        _require_equal(
            observed,
            extraction.get(expected_key),
            f"Runtime raw-log fact drift: {role}",
        )


def _validate_wall_evidence(
    manifest: dict[str, Any],
    inspector: Path,
    r8_root: Path,
) -> None:
    root_input = _external_input(manifest, "r8_root")
    assembly_spec = root_input.get("expected_assembly")
    if not isinstance(assembly_spec, dict):
        raise FixtureValidationError("WallCrawler assembly identity is missing.")
    relative = assembly_spec.get("relative_path")
    if not isinstance(relative, str):
        raise FixtureValidationError("WallCrawler assembly relative_path is invalid.")
    assembly = r8_root / Path(*relative.split("/"))
    if not assembly.is_file():
        raise FixtureInputBlockedError("R8 Modules-ASM.dll is unavailable.")
    _require_equal(
        _sha256_file(assembly),
        assembly_spec.get("sha256"),
        "WallCrawler assembly hash drift",
    )
    projection = _projection("r8_api_metadata_il_and_coverage_facts")
    methods = projection.get("methods")
    if not isinstance(methods, list):
        raise FixtureValidationError("WallCrawler IL methods are missing.")
    report = BoundILInspectionRunner(inspector, symbols=R8_IL_SYMBOLS).inspect(
        assembly
    )
    _require_equal(
        report.get("assembly_sha256"),
        assembly_spec.get("sha256"),
        "WallCrawler inspected assembly hash drift",
    )
    _require_equal(
        report.get("module_mvid"),
        assembly_spec.get("mvid"),
        "WallCrawler inspected assembly MVID drift",
    )
    expected_methods = [
        {
            key: row[key]
            for key in (
                "symbol",
                "metadata_token",
                "signature_blob",
                "has_method_body",
                "rva",
                "il_bytes",
            )
        }
        for row in methods
    ]
    _require_equal(
        _method_projection(report),
        expected_methods,
        "WallCrawler API/metadata/IL fact drift",
    )
    _require_equal(
        report.get("target_code_executed"),
        False,
        "WallCrawler target execution drift",
    )
    structure_facts = projection.get("source_structure_facts")
    if not isinstance(structure_facts, list) or not structure_facts:
        raise FixtureValidationError("WallCrawler source structure facts are missing.")
    for row in structure_facts:
        if not isinstance(row, dict):
            raise FixtureValidationError("WallCrawler source structure fact is invalid.")
        relative = row.get("relative_path")
        facts = row.get("facts")
        if not isinstance(relative, str) or not isinstance(facts, list):
            raise FixtureValidationError("WallCrawler source structure protocol is invalid.")
        source_path = r8_root / Path(*relative.split("/"))
        if not source_path.is_file():
            raise FixtureInputBlockedError(
                f"WallCrawler structure source is unavailable: {relative}"
            )
        source_text = source_path.read_text(encoding="utf-8")
        if not all(isinstance(fact, str) and fact in source_text for fact in facts):
            raise FixtureValidationError(
                f"WallCrawler source structure fact drift: {relative}"
            )


def _validate_case(
    *,
    case_name: str,
    r8_root: Path,
    inspector: Path,
    current_interop: Path,
    historical_implementation: Path,
    runtime_result: Path,
    bounded_log: Path,
    full_log: Path,
) -> tuple[dict[str, str], str]:
    case_root = PACKAGE_ROOT / case_name
    manifest = _load_object(case_root / "corpus_manifest.json")
    expected_identity = {
        "better_hit_feedback": "better_hit_feedback_positive_calibration",
        "wall_crawler": "wall_crawler_insufficient_evidence_calibration",
    }[case_name]
    _require_equal(
        manifest.get("case_identity"),
        expected_identity,
        "case identity drift",
    )
    annotation_binding_state = _validate_request_and_annotation(
        case_root, manifest, case_name
    )
    _validate_corpus_and_sources(
        manifest,
        r8_root,
        require_r8_owner_match=case_name == "wall_crawler",
    )
    if case_name == "better_hit_feedback":
        _validate_bhf_evidence(
            manifest,
            inspector,
            r8_root,
            current_interop,
            historical_implementation,
            runtime_result,
            bounded_log,
            full_log,
        )
    else:
        _validate_wall_evidence(manifest, inspector, r8_root)
    return (
        {
            "case_identity": expected_identity,
            "input_identity_validation": "passed",
            "corpus_validation": "passed",
            "evidence_recomputation": "passed",
            "leakage_scan": "passed",
            "annotation_binding": "passed",
        },
        annotation_binding_state,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r8-root", type=Path, required=True)
    parser.add_argument("--current-interop-assembly", type=Path, required=True)
    parser.add_argument("--bhf-historical-implementation", type=Path, required=True)
    parser.add_argument("--bhf-runtime-result", type=Path, required=True)
    parser.add_argument("--bhf-runtime-bounded-log", type=Path, required=True)
    parser.add_argument("--bhf-runtime-full-log", type=Path, required=True)
    args = parser.parse_args()

    try:
        r8_root = args.r8_root.resolve()
        if not r8_root.is_dir():
            raise FixtureInputBlockedError("--r8-root is unavailable.")
        with tempfile.TemporaryDirectory(prefix="two-slice-offline-fixture-") as temp_dir:
            inspector = _build_inspector(Path(temp_dir))
            results = [
                _validate_case(
                    case_name=case_name,
                    r8_root=r8_root,
                    inspector=inspector,
                    current_interop=args.current_interop_assembly.resolve(),
                    historical_implementation=args.bhf_historical_implementation.resolve(),
                    runtime_result=args.bhf_runtime_result.resolve(),
                    bounded_log=args.bhf_runtime_bounded_log.resolve(),
                    full_log=args.bhf_runtime_full_log.resolve(),
                )
                for case_name in CASE_NAMES
            ]
        cases = [row for row, _ in results]
        annotation_states = {state for _, state in results}
        if len(annotation_states) != 1:
            raise FixtureValidationError("Case annotation binding states differ.")
        annotation_binding_state = annotation_states.pop()
        local_replay_validation = "passed"
        failure = None
        exit_code = 0
    except FixtureInputBlockedError as exc:
        cases = []
        annotation_binding_state = "unknown"
        local_replay_validation = "blocked"
        failure = {"kind": "external_input_unavailable", "message": str(exc)}
        exit_code = 2
    except (FixtureValidationError, OSError, UnicodeError) as exc:
        cases = []
        annotation_binding_state = "unknown"
        local_replay_validation = "failed"
        failure = {"kind": "fixture_validation_failure", "message": str(exc)}
        exit_code = 1

    report = {
        "report_schema_version": "1",
        "local_replay_validation": local_replay_validation,
        "annotation_binding_state": annotation_binding_state,
        "cases": cases,
        "failure": failure,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
