"""Minimal local product entry that assembles the existing controlled graph."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from src.core.settings import load_settings
from src.libs.llm import LLMFactory
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.build import BuildAdapter, BuildCommandResult, BuildProfile
from src.mod_agent.evidence import RgLiveEvidenceProvider
from src.mod_agent.execution import ExactTextPatchApplier
from src.mod_agent.planning.request_planner import requested_scope_text
from src.mod_agent.proposal import LLMExactPatchGenerator
from src.mod_agent.workflow import build_graph, create_initial_state


class LocalEntryError(RuntimeError):
    """Raised when the local real-slice entry cannot start truthfully."""


SOURCE_DISCLOSURE_DATA_CLASSES = (
    "natural_language_request",
    "retrieved_local_source_excerpts",
    "binding_registry",
    "side_effect_boundaries",
)


def run_local_request(
    *,
    description: str,
    target_project: str | Path,
    workspace_base: str | Path,
    settings_path: str | Path,
    api_key_env: str = "DASHSCOPE_API_KEY",
    base_url_env: str = "DASHSCOPE_BASE_URL",
    confirm_isolated_write: bool,
    allow_build: bool,
    allow_source_disclosure: bool,
    diff_approval_reader: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Run one request through the existing graph against an isolated target copy."""

    if not description.strip():
        raise LocalEntryError("run-request requires a non-empty natural-language request.")
    if not allow_source_disclosure:
        raise LocalEntryError(
            "run-request requires --allow-source-disclosure before reading local "
            "target source or calling the configured external LLM."
        )
    if not confirm_isolated_write:
        raise LocalEntryError("run-request requires --confirm-isolated-write.")
    if not allow_build:
        raise LocalEntryError("run-request requires --allow-build for the real build step.")
    if diff_approval_reader is None:
        raise LocalEntryError("run-request requires an exact diff approval reader.")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise LocalEntryError(f"Required API key environment variable is missing: {api_key_env}")
    settings = load_settings(settings_path)
    llm_base_url = os.environ.get(base_url_env) or settings.llm.base_url
    if not llm_base_url:
        raise LocalEntryError(
            f"Required LLM base URL is missing from settings and environment: {base_url_env}"
        )
    _sanitized_endpoint_url(llm_base_url)
    started_at = datetime.now(timezone.utc).isoformat()
    source_disclosure = _source_disclosure_record(
        provider=settings.llm.provider,
        model=settings.llm.model,
        base_url=llm_base_url,
        approved_at=started_at,
    )

    source = Path(target_project).resolve()
    if not source.is_dir() or not any(source.glob("*.csproj")):
        raise LocalEntryError("Target project must be an existing directory with a .csproj file.")
    base = Path(workspace_base).resolve()
    base.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex[:8]
    run_root = (base / run_id).resolve()
    target_copy = run_root / "generated_mods" / source.name
    target_copy.parent.mkdir(parents=True)
    shutil.copytree(
        source,
        target_copy,
        ignore=shutil.ignore_patterns("bin", "obj", ".git", ".idea"),
    )
    source_projects = tuple(source.glob("*.csproj"))
    if len(source_projects) != 1:
        raise LocalEntryError("Target project must contain exactly one top-level .csproj file.")
    source_project = source_projects[0]
    assembly_name = _project_text_property(
        source_project,
        property_name="AssemblyName",
    )
    source_bepinex_dir = _resolve_project_path_property(
        source_project,
        property_name="BepInExDir",
    )
    if not source_bepinex_dir.is_dir():
        raise LocalEntryError(f"Resolved BepInExDir is missing: {source_bepinex_dir}")
    isolated_bepinex_dir = run_root / "build_dependencies" / "BepInEx"
    isolated_bepinex_dir.parent.mkdir(parents=True)
    shutil.copytree(source_bepinex_dir, isolated_bepinex_dir)
    build_command = ("dotnet", "build", f"-p:BepInExDir={isolated_bepinex_dir}")
    baseline_stdout = run_root / "baseline_build.stdout.log"
    baseline_stderr = run_root / "baseline_build.stderr.log"
    baseline_started = time.perf_counter()
    baseline = subprocess.run(
        build_command,
        cwd=target_copy,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    baseline_stdout.write_text(baseline.stdout, encoding="utf-8")
    baseline_stderr.write_text(baseline.stderr, encoding="utf-8")
    expected_artifact = f"bin/Debug/{assembly_name}.dll"
    baseline_artifact = target_copy / expected_artifact
    baseline_result = {
        "exit_code": baseline.returncode,
        "duration_ms": int((time.perf_counter() - baseline_started) * 1000),
        "artifact_exists": baseline_artifact.is_file(),
        "artifact_sha256": (
            hashlib.sha256(baseline_artifact.read_bytes()).hexdigest()
            if baseline_artifact.is_file()
            else None
        ),
        "stdout_path": str(baseline_stdout),
        "stderr_path": str(baseline_stderr),
    }

    llm = LLMFactory.create(
        settings,
        api_key=api_key,
        base_url=llm_base_url,
    )
    generator = LLMExactPatchGenerator(llm)
    applier = ExactTextPatchApplier()
    evidence_provider = RgLiveEvidenceProvider(run_root)
    artifact_store = ArtifactStore(run_root / "a")
    build_stdout = run_root / "build.stdout.log"
    build_stderr = run_root / "build.stderr.log"
    pending_dry_run: dict[str, Any] | None = None

    def evidence_factory(state: dict[str, Any], _: dict[str, Any]):
        return evidence_provider.collect(
            query=requested_scope_text(state["user_request"]),
            search_root=f"generated_mods/{source.name}",
        )

    def patch_change_factory(
        state: dict[str, Any],
        implementation: dict[str, Any],
        evidence_pack: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        _verify_source_disclosure(
            source_disclosure,
            requested_data_classes=SOURCE_DISCLOSURE_DATA_CLASSES,
        )
        generated = generator.generate(
            user_request=state["user_request"],
            evidence_items=list(evidence_pack.get("items") or []),
            binding_registry=dict(implementation.get("binding_registry") or {}),
            constraints=[str(item) for item in implementation.get("side_effect_boundaries") or []],
        )
        planned_by_binding = {
            str(item.get("edit_binding_id")): item
            for item in implementation.get("proposed_changes") or []
            if isinstance(item, dict) and item.get("edit_binding_id")
        }
        changes: list[dict[str, Any]] = []
        for generated_change in generated.changes:
            binding_id = str(generated_change["edit_binding_id"])
            planned = planned_by_binding.get(binding_id)
            if planned is None:
                raise LocalEntryError("Generated patch is outside implementation-plan bindings.")
            changes.append(
                {
                    **planned,
                    "rationale": generated_change["rationale"],
                    "expected_validation": generated_change["expected_validation"],
                    "rollback_hint": generated_change["rollback_hint"],
                    "patch": generated_change["patch"],
                    "generation": {
                        "provider": settings.llm.provider,
                        "model": generated.model,
                        "usage": generated.usage,
                        "api_key_env": api_key_env,
                    },
                }
            )
        return tuple(changes)

    def dry_run_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        nonlocal pending_dry_run
        pending_dry_run = applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=False,
        )
        return pending_dry_run

    def isolated_apply_factory(
        proposal: dict[str, Any],
        implementation: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        if pending_dry_run is None:
            raise LocalEntryError("Exact diff approval requested before dry-run completed.")
        approved_diff_hash = diff_approval_reader(dict(pending_dry_run)).strip()
        return applier.run(
            workspace_root=run_root,
            proposal=proposal,
            implementation_plan=implementation,
            review=review,
            allow_write=True,
            approved_diff_hash=approved_diff_hash,
        )

    def build_result_factory(feature_id: str, input_execution_mode: str | None):
        profile = BuildProfile(
            profile_id="v2_codegen_real_local_dotnet",
            build_system="dotnet",
            working_directory=str(target_copy),
            command=build_command,
            timeout_seconds=120,
            expected_artifacts=(expected_artifact,),
        )

        def command_runner(selected: BuildProfile) -> BuildCommandResult:
            started = time.perf_counter()
            completed = subprocess.run(
                selected.command,
                cwd=selected.working_directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=selected.timeout_seconds,
                check=False,
            )
            build_stdout.write_text(completed.stdout, encoding="utf-8")
            build_stderr.write_text(completed.stderr, encoding="utf-8")
            return BuildCommandResult(
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        return BuildAdapter().run_local(
            feature_id=feature_id,
            profile=profile,
            command_runner=command_runner,
            allow_execution=True,
            input_execution_mode=input_execution_mode,
        )

    manifest = {
        "run_id": run_id,
        "started_at": started_at,
        "request": description,
        "target_source": str(source),
        "target_source_provenance": "externally_produced_read_only_input",
        "isolated_workspace": str(run_root),
        "source_snapshot": _source_snapshot(source),
        "model": settings.llm.model,
        "base_url": _sanitized_endpoint_url(llm_base_url),
        "base_url_env": base_url_env,
        "base_url_env_present": bool(os.environ.get(base_url_env)),
        "api_key_env": api_key_env,
        "api_key_present": True,
        "api_key_value_persisted": False,
        "source_disclosure": source_disclosure,
        "assembly_name": assembly_name,
        "build_dependency": {
            "source": str(source_bepinex_dir),
            "isolated_copy": str(isolated_bepinex_dir),
            "build_uses_isolated_copy": True,
        },
        "baseline_build": baseline_result,
        "limits": [
            "No claim that the external BetterHitFeedback project was generated by this platform.",
            "No real GTFO launch or gameplay validation is performed.",
            "The dotnet process executes user-authorized project build logic and is not an OS sandbox.",
        ],
    }
    (run_root / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if baseline.returncode != 0 or not baseline_result["artifact_exists"]:
        raise LocalEntryError(
            "Unmodified isolated baseline build failed; code generation was not started."
        )
    for generated_directory in (target_copy / "bin", target_copy / "obj"):
        if generated_directory.exists():
            shutil.rmtree(generated_directory)

    graph = build_graph(
        artifact_store,
        evidence_pack_factory=evidence_factory,
        patch_change_factory=patch_change_factory,
        dry_run_factory=dry_run_factory,
        isolated_apply_factory=isolated_apply_factory,
        build_result_factory=build_result_factory,
        use_default_proposal_git_binding=False,
        stop_after_build=True,
    )
    state = create_initial_state(
        run_id=run_id,
        request_id=f"request_{run_id}",
        user_request=description,
        target_domain="gtfo",
        target_mod=source.name,
        confirmed_isolated_write=True,
    )
    with _working_directory(run_root):
        try:
            result = graph.invoke(state)
        except Exception as exc:
            failure = {
                "run_id": run_id,
                "current_stage": "failed_before_result",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "run_root": str(run_root),
            }
            (run_root / "run_failure.json").write_text(
                json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise LocalEntryError(f"Controlled graph failed: {type(exc).__name__}: {exc}") from exc

    summary = {
        "run_id": run_id,
        "current_stage": result["current_stage"],
        "feature_id": result.get("feature_id"),
        "blockers": result.get("blockers") or [],
        "artifacts": result.get("artifacts") or {},
        "build_summary": result.get("build_summary") or {},
        "run_root": str(run_root),
        "build_stdout": str(build_stdout) if build_stdout.exists() else None,
        "build_stderr": str(build_stderr) if build_stderr.exists() else None,
    }
    (run_root / "run_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _source_snapshot(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and "bin" not in path.parts and "obj" not in path.parts
    ]


def _source_disclosure_record(
    *,
    provider: str,
    model: str,
    base_url: str | None,
    approved_at: str,
) -> dict[str, Any]:
    return {
        "approved": True,
        "approved_at": approved_at,
        "approval_actor_type": "local_cli_invoker",
        "consent_mechanism": "--allow-source-disclosure",
        "destination": {
            "provider": provider,
            "model": model,
            "base_url": _sanitized_endpoint_url(base_url),
        },
        "approved_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "requested_data_classes": list(SOURCE_DISCLOSURE_DATA_CLASSES),
        "scope": "this_run_only",
    }


def _verify_source_disclosure(
    record: dict[str, Any],
    *,
    requested_data_classes: tuple[str, ...],
) -> None:
    if record.get("approved") is not True:
        raise LocalEntryError("Source disclosure is not explicitly approved.")
    approved = record.get("approved_data_classes")
    if not isinstance(approved, list):
        raise LocalEntryError("Source disclosure approved_data_classes is missing.")
    unapproved = sorted(set(requested_data_classes) - {str(item) for item in approved})
    if unapproved:
        raise LocalEntryError(
            "Source disclosure does not approve requested data classes: "
            + ", ".join(unapproved)
        )


def _resolve_project_path_property(project_file: Path, *, property_name: str) -> Path:
    value = Path(
        _project_text_property(project_file, property_name=property_name).replace(
            "\\", os.sep
        )
    )
    return value.resolve() if value.is_absolute() else (project_file.parent / value).resolve()


def _project_text_property(project_file: Path, *, property_name: str) -> str:
    root = ET.parse(project_file).getroot()
    values = [
        item.text.strip()
        for item in root.iter(property_name)
        if isinstance(item.text, str) and item.text.strip()
    ]
    if not values:
        raise LocalEntryError(f"Project file does not define {property_name}.")
    if len(values) != 1:
        raise LocalEntryError(
            f"Project file must define exactly one non-empty {property_name}."
        )
    return values[0]


def _sanitized_endpoint_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    parsed = urlsplit(base_url)
    if not parsed.scheme or parsed.hostname is None:
        raise LocalEntryError("Configured LLM base_url is not a valid absolute URL.")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    try:
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
    except ValueError as exc:
        raise LocalEntryError("Configured LLM base_url has an invalid port.") from exc
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)
