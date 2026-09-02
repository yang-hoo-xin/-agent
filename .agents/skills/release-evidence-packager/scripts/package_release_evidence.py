#!/usr/bin/env python3
"""Create deterministic release drafts from strict, explicitly supplied evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


INPUT_VERSION = "release-evidence-input.v1"
OUTPUT_VERSION = "release-evidence-manifest.v1"
EVIDENCE_KINDS = ("commit", "test", "ci", "build", "runtime", "trace")
EVIDENCE_STATUSES = {"verified", "failed", "blocked"}
PLACEMENTS = {"results_table", "demo_script", "resume", "interview"}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "release_id",
    "project_name",
    "release_commit_evidence_id",
    "evidence",
    "claims",
    "delivery_lines",
    "demo",
}
EVIDENCE_FIELDS = {
    "evidence_id",
    "kind",
    "status",
    "summary",
    "source_ref",
    "command",
    "commit_sha",
    "metrics",
}
METRIC_FIELDS = {"name", "value", "unit"}
CLAIM_FIELDS = {"claim_id", "statement", "evidence_ids", "placements"}
LINE_FIELDS = {
    "line_id",
    "label",
    "objective_refs",
    "evidence_ids",
    "unknowns",
    "next_gate",
}
DEMO_FIELDS = {"duration_minutes", "steps"}
DEMO_STEP_FIELDS = {"title", "narration", "evidence_ids"}


class InputError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise InputError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise InputError(f"unsupported JSON constant: {value}")


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"cannot read input: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError("input must be UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, InputError) as exc:
        raise InputError(f"invalid JSON input: {exc}") from exc
    if not isinstance(value, dict):
        raise InputError("input root must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _exact_fields(
    value: dict[str, Any], expected: set[str], location: str
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(unknown)}")
        raise InputError(f"{location}: {'; '.join(parts)}")


def _text(value: Any, location: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise InputError(f"{location} must be a string")
    if not value or value != value.strip():
        raise InputError(f"{location} must be non-empty without outer whitespace")
    if "\n" in value or "\r" in value:
        raise InputError(f"{location} must be one line")
    return value


def _text_list(
    value: Any, location: str, *, minimum: int = 0
) -> list[str]:
    if not isinstance(value, list):
        raise InputError(f"{location} must be an array")
    result = []
    for index, item in enumerate(value):
        checked = _text(item, f"{location}[{index}]")
        assert isinstance(checked, str)
        result.append(checked)
    if len(result) < minimum:
        raise InputError(f"{location} must contain at least {minimum} item(s)")
    if len(set(result)) != len(result):
        raise InputError(f"{location} must not contain duplicate values")
    return result


def _object_list(value: Any, location: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InputError(f"{location} must be an array")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise InputError(f"{location}[{index}] must be an object")
        result.append(item)
    return result


def _validate_metrics(value: Any, location: str) -> list[dict[str, Any]]:
    result = []
    names = set()
    for index, metric in enumerate(_object_list(value, location)):
        item_location = f"{location}[{index}]"
        _exact_fields(metric, METRIC_FIELDS, item_location)
        name = _text(metric["name"], f"{item_location}.name")
        metric_value = _text(metric["value"], f"{item_location}.value")
        unit = _text(metric["unit"], f"{item_location}.unit", nullable=True)
        assert isinstance(name, str)
        if name in names:
            raise InputError(f"{location} contains duplicate metric name: {name}")
        names.add(name)
        result.append({"name": name, "value": metric_value, "unit": unit})
    return result


def _validate_evidence(value: Any) -> list[dict[str, Any]]:
    result = []
    identifiers = set()
    for index, evidence in enumerate(_object_list(value, "evidence")):
        location = f"evidence[{index}]"
        _exact_fields(evidence, EVIDENCE_FIELDS, location)
        evidence_id = _text(evidence["evidence_id"], f"{location}.evidence_id")
        kind = _text(evidence["kind"], f"{location}.kind")
        status = _text(evidence["status"], f"{location}.status")
        assert isinstance(evidence_id, str)
        assert isinstance(kind, str)
        assert isinstance(status, str)
        if evidence_id in identifiers:
            raise InputError(f"duplicate evidence_id: {evidence_id}")
        if kind not in EVIDENCE_KINDS:
            raise InputError(
                f"{location}.kind must be one of: {', '.join(EVIDENCE_KINDS)}"
            )
        if status not in EVIDENCE_STATUSES:
            raise InputError(
                f"{location}.status must be one of: "
                + ", ".join(sorted(EVIDENCE_STATUSES))
            )
        commit_sha = _text(
            evidence["commit_sha"], f"{location}.commit_sha", nullable=True
        )
        if kind == "commit" and commit_sha is None:
            raise InputError(f"{location}.commit_sha is required for commit evidence")
        identifiers.add(evidence_id)
        result.append(
            {
                "evidence_id": evidence_id,
                "kind": kind,
                "status": status,
                "summary": _text(evidence["summary"], f"{location}.summary"),
                "source_ref": _text(
                    evidence["source_ref"], f"{location}.source_ref"
                ),
                "command": _text(
                    evidence["command"], f"{location}.command", nullable=True
                ),
                "commit_sha": commit_sha,
                "metrics": _validate_metrics(
                    evidence["metrics"], f"{location}.metrics"
                ),
            }
        )
    return result


def _validate_claims(
    value: Any, evidence_ids: set[str]
) -> list[dict[str, Any]]:
    result = []
    identifiers = set()
    for index, claim in enumerate(_object_list(value, "claims")):
        location = f"claims[{index}]"
        _exact_fields(claim, CLAIM_FIELDS, location)
        claim_id = _text(claim["claim_id"], f"{location}.claim_id")
        assert isinstance(claim_id, str)
        if claim_id in identifiers:
            raise InputError(f"duplicate claim_id: {claim_id}")
        refs = _text_list(claim["evidence_ids"], f"{location}.evidence_ids")
        unknown_refs = sorted(set(refs) - evidence_ids)
        if unknown_refs:
            raise InputError(
                f"{location}.evidence_ids contains unknown IDs: "
                + ", ".join(unknown_refs)
            )
        placements = _text_list(
            claim["placements"], f"{location}.placements", minimum=1
        )
        unknown_placements = sorted(set(placements) - PLACEMENTS)
        if unknown_placements:
            raise InputError(
                f"{location}.placements contains unknown values: "
                + ", ".join(unknown_placements)
            )
        identifiers.add(claim_id)
        result.append(
            {
                "claim_id": claim_id,
                "statement": _text(claim["statement"], f"{location}.statement"),
                "evidence_ids": refs,
                "placements": placements,
            }
        )
    return result


def _validate_lines(
    value: Any, evidence_ids: set[str]
) -> list[dict[str, Any]]:
    raw_lines = _object_list(value, "delivery_lines")
    if len(raw_lines) != 5:
        raise InputError("delivery_lines must contain exactly five items")
    result = []
    identifiers = set()
    for index, line in enumerate(raw_lines):
        location = f"delivery_lines[{index}]"
        _exact_fields(line, LINE_FIELDS, location)
        line_id = _text(line["line_id"], f"{location}.line_id")
        assert isinstance(line_id, str)
        if line_id in identifiers:
            raise InputError(f"duplicate line_id: {line_id}")
        refs = _text_list(line["evidence_ids"], f"{location}.evidence_ids")
        unknown_refs = sorted(set(refs) - evidence_ids)
        if unknown_refs:
            raise InputError(
                f"{location}.evidence_ids contains unknown IDs: "
                + ", ".join(unknown_refs)
            )
        identifiers.add(line_id)
        result.append(
            {
                "line_id": line_id,
                "label": _text(line["label"], f"{location}.label"),
                "objective_refs": _text_list(
                    line["objective_refs"],
                    f"{location}.objective_refs",
                    minimum=1,
                ),
                "evidence_ids": refs,
                "unknowns": _text_list(
                    line["unknowns"], f"{location}.unknowns"
                ),
                "next_gate": _text(line["next_gate"], f"{location}.next_gate"),
            }
        )
    return result


def _validate_demo(
    value: Any, evidence_ids: set[str]
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError("demo must be an object")
    _exact_fields(value, DEMO_FIELDS, "demo")
    duration = value["duration_minutes"]
    if isinstance(duration, bool) or not isinstance(duration, int):
        raise InputError("demo.duration_minutes must be an integer")
    if duration < 3 or duration > 5:
        raise InputError("demo.duration_minutes must be from 3 through 5")
    steps = []
    for index, step in enumerate(_object_list(value["steps"], "demo.steps")):
        location = f"demo.steps[{index}]"
        _exact_fields(step, DEMO_STEP_FIELDS, location)
        refs = _text_list(step["evidence_ids"], f"{location}.evidence_ids")
        unknown_refs = sorted(set(refs) - evidence_ids)
        if unknown_refs:
            raise InputError(
                f"{location}.evidence_ids contains unknown IDs: "
                + ", ".join(unknown_refs)
            )
        steps.append(
            {
                "title": _text(step["title"], f"{location}.title"),
                "narration": _text(
                    step["narration"], f"{location}.narration"
                ),
                "evidence_ids": refs,
            }
        )
    return {"duration_minutes": duration, "steps": steps}


def _validate(value: dict[str, Any]) -> dict[str, Any]:
    _exact_fields(value, TOP_LEVEL_FIELDS, "root")
    if value["schema_version"] != INPUT_VERSION:
        raise InputError(f"schema_version must equal {INPUT_VERSION}")
    evidence = _validate_evidence(value["evidence"])
    evidence_ids = {item["evidence_id"] for item in evidence}
    release_commit_id = _text(
        value["release_commit_evidence_id"],
        "release_commit_evidence_id",
        nullable=True,
    )
    if release_commit_id is not None:
        by_id = {item["evidence_id"]: item for item in evidence}
        if release_commit_id not in by_id:
            raise InputError("release_commit_evidence_id is unknown")
        if by_id[release_commit_id]["kind"] != "commit":
            raise InputError(
                "release_commit_evidence_id must reference commit evidence"
            )
    return {
        "release_id": _text(value["release_id"], "release_id"),
        "project_name": _text(value["project_name"], "project_name"),
        "release_commit_evidence_id": release_commit_id,
        "evidence": evidence,
        "claims": _validate_claims(value["claims"], evidence_ids),
        "delivery_lines": _validate_lines(
            value["delivery_lines"], evidence_ids
        ),
        "demo": _validate_demo(value["demo"], evidence_ids),
    }


def _projection_status(
    refs: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
    release_commit_sha: str | None,
) -> str:
    if release_commit_sha is None or not refs:
        return "not_demonstrated"
    if all(
        evidence_by_id[item]["status"] == "verified"
        and evidence_by_id[item]["commit_sha"] == release_commit_sha
        for item in refs
    ):
        return "demonstrated"
    return "not_demonstrated"


def _build_manifest(inputs: dict[str, Any], source_hash: str) -> dict[str, Any]:
    evidence_by_id = {
        item["evidence_id"]: item for item in inputs["evidence"]
    }
    release_commit_id = inputs["release_commit_evidence_id"]
    release_commit_sha = None
    if release_commit_id is not None:
        release_commit_item = evidence_by_id[release_commit_id]
        if release_commit_item["status"] == "verified":
            release_commit_sha = release_commit_item["commit_sha"]

    category_view = {}
    for kind in EVIDENCE_KINDS:
        refs = [
            item["evidence_id"]
            for item in inputs["evidence"]
            if item["kind"] == kind
        ]
        category_view[kind] = {
            "status": _projection_status(
                refs, evidence_by_id, release_commit_sha
            ),
            "evidence_refs": refs,
        }

    if release_commit_id is None:
        release_commit = {
            "status": "not_demonstrated",
            "evidence_ref": None,
            "commit_sha": None,
            "source_ref": None,
        }
    else:
        item = evidence_by_id[release_commit_id]
        release_commit = {
            "status": _projection_status(
                [release_commit_id], evidence_by_id, release_commit_sha
            ),
            "evidence_ref": release_commit_id,
            "commit_sha": item["commit_sha"],
            "source_ref": item["source_ref"],
        }

    claims = []
    for claim in inputs["claims"]:
        claims.append(
            {
                **claim,
                "status": _projection_status(
                    claim["evidence_ids"],
                    evidence_by_id,
                    release_commit_sha,
                ),
            }
        )
    lines = []
    for line in inputs["delivery_lines"]:
        lines.append(
            {
                **line,
                "evidence_status": _projection_status(
                    line["evidence_ids"],
                    evidence_by_id,
                    release_commit_sha,
                ),
            }
        )
    demo_steps = []
    for step in inputs["demo"]["steps"]:
        status = _projection_status(
            step["evidence_ids"], evidence_by_id, release_commit_sha
        )
        demo_steps.append({**step, "status": status})

    return {
        "schema_version": OUTPUT_VERSION,
        "manifest_role": "derived_evidence_index_not_authoritative",
        "source_input_sha256": source_hash,
        "release_id": inputs["release_id"],
        "project_name": inputs["project_name"],
        "release_commit": release_commit,
        "evidence": inputs["evidence"],
        "evidence_by_kind": category_view,
        "claims": claims,
        "delivery_lines": lines,
        "demo": {
            "duration_minutes": inputs["demo"]["duration_minutes"],
            "steps": demo_steps,
        },
    }


def _cell(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value) if value else "none"
    else:
        text = str(value)
    return text.replace("|", "\\|")


def _refs(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _markdown(manifest: dict[str, Any]) -> str:
    lines = [
        f"# Release Evidence Draft: {manifest['release_id']}",
        "",
        f"Project: {manifest['project_name']}",
        "",
        f"Source input SHA-256: {manifest['source_input_sha256']}",
        "",
        "Role: derived evidence index only; source references remain authoritative.",
        "",
        "## Release Commit",
        "",
        "| status | commit_sha | evidence_ref | source_ref |",
        "| --- | --- | --- | --- |",
    ]
    commit = manifest["release_commit"]
    lines.append(
        "| "
        + " | ".join(
            _cell(commit[key])
            for key in ("status", "commit_sha", "evidence_ref", "source_ref")
        )
        + " |"
    )

    lines.extend(
        [
            "",
            "## Evidence by Kind",
            "",
            "| kind | status | evidence_refs |",
            "| --- | --- | --- |",
        ]
    )
    for kind in EVIDENCE_KINDS:
        view = manifest["evidence_by_kind"][kind]
        lines.append(
            f"| {_cell(kind)} | {_cell(view['status'])} | "
            f"{_cell(_refs(view['evidence_refs']))} |"
        )

    lines.extend(
        [
            "",
            "## Five-Line Delivery View",
            "",
            "| line | objective_refs | evidence_status | evidence_refs | unknowns | next_gate |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in manifest["delivery_lines"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(f"{item['line_id']}: {item['label']}"),
                    _cell(_refs(item["objective_refs"])),
                    _cell(item["evidence_status"]),
                    _cell(_refs(item["evidence_ids"])),
                    _cell(_refs(item["unknowns"])),
                    _cell(item["next_gate"]),
                )
            )
            + " |"
        )

    result_claims = [
        item
        for item in manifest["claims"]
        if "results_table" in item["placements"]
    ]
    lines.extend(
        [
            "",
            "## Results Table",
            "",
            "| claim_id | status | statement | evidence_refs |",
            "| --- | --- | --- | --- |",
        ]
    )
    if result_claims:
        for item in result_claims:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _cell(item["claim_id"]),
                        _cell(item["status"]),
                        _cell(item["statement"]),
                        _cell(_refs(item["evidence_ids"])),
                    )
                )
                + " |"
            )
    else:
        lines.append("| none | not_demonstrated | none | none |")

    lines.extend(
        [
            "",
            f"## Demo Script ({manifest['demo']['duration_minutes']} minutes)",
            "",
        ]
    )
    if manifest["demo"]["steps"]:
        for index, step in enumerate(manifest["demo"]["steps"], start=1):
            lines.append(f"### {index}. {step['title']}")
            lines.append("")
            lines.append(f"Status: {step['status']}")
            lines.append("")
            lines.append(f"Evidence: {_refs(step['evidence_ids'])}")
            if step["status"] == "demonstrated":
                lines.extend(["", step["narration"]])
            lines.append("")
    else:
        lines.extend(["not_demonstrated", ""])

    resume_claims = [
        item for item in manifest["claims"] if "resume" in item["placements"]
    ]
    supported_resume = [
        item for item in resume_claims if item["status"] == "demonstrated"
    ]
    unsupported_resume = [
        item for item in resume_claims if item["status"] != "demonstrated"
    ]
    lines.extend(["## Resume Bullets", ""])
    if supported_resume:
        for item in supported_resume:
            lines.append(
                f"- {item['statement']} [evidence: {_refs(item['evidence_ids'])}]"
            )
    else:
        lines.append("- not_demonstrated")
    if unsupported_resume:
        lines.extend(["", "### Unsupported Resume Claims", ""])
        for item in unsupported_resume:
            lines.append(
                f"- not_demonstrated: {item['statement']} "
                f"[evidence: {_refs(item['evidence_ids'])}]"
            )

    interview_claims = [
        item
        for item in manifest["claims"]
        if "interview" in item["placements"]
    ]
    lines.extend(
        [
            "",
            "## Interview Evidence",
            "",
            "| claim_id | status | statement | evidence_refs |",
            "| --- | --- | --- | --- |",
        ]
    )
    if interview_claims:
        for item in interview_claims:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _cell(item["claim_id"]),
                        _cell(item["status"]),
                        _cell(item["statement"]),
                        _cell(_refs(item["evidence_ids"])),
                    )
                )
                + " |"
            )
    else:
        lines.append("| none | not_demonstrated | none | none |")
    return "\n".join(lines).rstrip() + "\n"


def _stage_output(output_dir: Path, filename: str, content: str) -> Path:
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{filename}-", suffix=".tmp", dir=output_dir
    )
    temporary = Path(temporary_name)
    complete = False
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        complete = True
        return temporary
    finally:
        if not complete and temporary.exists():
            temporary.unlink()


def _unused_backup_path(output_dir: Path, filename: str) -> Path:
    handle, backup_name = tempfile.mkstemp(
        prefix=f".{filename}-", suffix=".bak", dir=output_dir
    )
    os.close(handle)
    backup = Path(backup_name)
    backup.unlink()
    return backup


def _sync_directory(output_dir: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(output_dir, flags)
    except OSError:
        if os.name == "nt":
            return
        raise
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_output_pair(
    output_dir: Path,
    manifest_content: str,
    markdown_content: str,
    *,
    overwrite: bool,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "release_manifest.json"
    markdown_path = output_dir / "release_evidence_draft.md"
    targets = (manifest_path, markdown_path)

    non_files = [path for path in targets if path.exists() and not path.is_file()]
    if non_files:
        raise InputError(
            "output target exists and is not a file: "
            + ", ".join(str(path) for path in non_files)
        )
    existing = [path for path in targets if path.exists()]
    if existing and not overwrite:
        raise InputError(
            "output exists; pass --overwrite to replace both files: "
            + ", ".join(str(path) for path in existing)
        )

    staged: dict[Path, Path] = {}
    try:
        staged[manifest_path] = _stage_output(
            output_dir, manifest_path.name, manifest_content
        )
        staged[markdown_path] = _stage_output(
            output_dir, markdown_path.name, markdown_content
        )
    except Exception:
        for temporary in staged.values():
            if temporary.exists():
                temporary.unlink()
        raise

    backups: dict[Path, Path] = {}
    installed: set[Path] = set()
    try:
        for target in targets:
            if target.exists():
                backup = _unused_backup_path(output_dir, target.name)
                os.replace(target, backup)
                backups[target] = backup
        for target in targets:
            os.replace(staged[target], target)
            installed.add(target)
        _sync_directory(output_dir)
    except Exception as commit_error:
        rollback_errors = []
        for target in reversed(targets):
            backup = backups.get(target)
            try:
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                elif target in installed and target.exists():
                    target.unlink()
            except OSError as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        for temporary in staged.values():
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError as cleanup_error:
                rollback_errors.append(f"{temporary}: {cleanup_error}")
        if not rollback_errors:
            _sync_directory(output_dir)
        if rollback_errors:
            raise OSError(
                "output commit failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from commit_error
        raise
    else:
        for backup in backups.values():
            if backup.exists():
                backup.unlink()
        return manifest_path, markdown_path
    finally:
        for temporary in staged.values():
            if temporary.exists():
                temporary.unlink()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package strict release evidence into JSON and Markdown."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    try:
        raw, source_hash = _load_json(arguments.input)
        inputs = _validate(raw)
        manifest = _build_manifest(inputs, source_hash)
        output_dir = arguments.output_dir.resolve()
        manifest_path, markdown_path = _write_output_pair(
            output_dir,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            _markdown(manifest),
            overwrite=arguments.overwrite,
        )
        print(str(manifest_path))
        print(str(markdown_path))
        return 0
    except (InputError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
