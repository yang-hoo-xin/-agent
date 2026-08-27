from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.mod_agent.cli import build_parser, main as cli_main
from src.mod_agent.preflight_preparation import (
    PreflightPreparationDependenciesV1,
    PreflightPreparationError,
    SealedPreflightPreparationRequestV1,
    derive_run_identities,
    prepare_sealed_entry_preflight,
)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _git_executable() -> Path:
    selected = shutil.which("git")
    assert selected is not None
    return Path(selected).resolve()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        (str(_git_executable()), "-C", str(root), *args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout.rstrip("\r\n")


def _initialize_repository(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root.parent, "init", str(root))
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "core.autocrlf", "false")


def _seal_preflight_fixture(
    root: Path,
    *,
    outer_run_id: str = "p2_ac_20260825_009",
    attempt_id: str = "preflight_10",
    preflight_id: str = (
        "entry_preflight_011_timeout_600_selected_qwen36_27b_full_correction"
    ),
    canary_number: int = 9,
    actual_id: str = "actual_9",
) -> dict[str, Path | str]:
    root.mkdir(parents=True)
    runner = root / "sealed_entry_runner.py"
    runner.write_text("raise SystemExit('fixture runner is not executable')\n", encoding="utf-8")
    receipt_root = root / f"fresh_preflight_root_{attempt_id}"
    receipt_root.mkdir()
    receipt = receipt_root / "entry_admission_receipt.json"
    receipt_manifest = receipt_root / "entry_admission_receipt_manifest.json"
    packet = root / "packet.json"
    preflight = root / "PREFLIGHT.json"
    packet_payload = {
        "packet_version": "p2_thin_entry_admission_packet_v6",
        "outer_run_id": outer_run_id,
        "attempt_id": attempt_id,
        "preflight_id": preflight_id,
        "delivery": {
            "packet_root_text": str(root),
            "packet_root_canonical_text": root.resolve().as_posix(),
            "fresh_preflight_root_text": str(receipt_root),
            "fresh_preflight_root_canonical_text": receipt_root.resolve().as_posix(),
            "expected_receipt_path": receipt.resolve().as_posix(),
            "expected_receipt_manifest_path": receipt_manifest.resolve().as_posix(),
            "execution_root": None,
        },
        "product_execution_selection": {
            "status": "preserved_as_non_authorizing_future_identity",
            "future_canary_number": canary_number,
            "future_attempt_id": actual_id,
            "authorized": False,
            "execution_root": None,
        },
        "permissions": {
            "fresh_preflight_authorized": True,
            "canary_authorized": False,
            "actual_authorized": False,
            "ProductExecution": False,
            "Build": False,
            "Runtime": False,
            "Apply": False,
        },
    }
    _write_json(packet, packet_payload)
    payload_files = {
        "packet.json": _file_sha256(packet),
        "sealed_entry_runner.py": _file_sha256(runner),
    }
    payload_manifest = _canonical_sha256(payload_files)
    _write_json(
        preflight,
        {
            "preflight_version": "fixture_seal_v1",
            "packet_sealed": True,
            "preflight_executed": False,
            "canary_executed": False,
            "actual_executed": False,
            "files": {
                name: {"sha256": digest, "bytes": (root / name).stat().st_size}
                for name, digest in payload_files.items()
            },
            "payload_manifest_material": [
                "packet.json",
                "sealed_entry_runner.py",
            ],
            "payload_manifest_sha256": payload_manifest,
        },
    )
    receipt_payload = {
        "actual_authorized": False,
        "output_root_text": str(receipt_root),
        "packet_root_text": str(root),
        "receipt_version": "sealed_entry_admission_receipt_v1",
        "request_identity": {
            "attempt_id": attempt_id,
            "outer_run_id": outer_run_id,
            "payload_manifest_sha256": payload_manifest,
        },
        "result": {
            "Builds": 0,
            "ProductExecution_runs": 0,
            "actual_authorized": False,
            "attempt_consumed": False,
            "attempt_id": attempt_id,
            "blockers": [],
            "contract_version": "1",
            "execution_root_created": False,
            "first_failure_code": None,
            "first_failure_message": None,
            "first_failure_stage": None,
            "gate_receipts": [],
            "model_calls": 0,
            "outer_run_id": outer_run_id,
            "output_root_text": str(receipt_root),
            "packet_root_text": str(root),
            "payload_manifest_sha256": payload_manifest,
            "status": "ready",
        },
    }
    _write_json(receipt, receipt_payload)
    _write_json(
        receipt_manifest,
        {
            "actual_authorized": False,
            "manifest_version": "sealed_entry_admission_manifest_v1",
            "payload_manifest_sha256": payload_manifest,
            "receipt_path": str(receipt),
            "receipt_sha256": _file_sha256(receipt),
        },
    )
    return {
        "packet": packet,
        "preflight": preflight,
        "receipt": receipt,
        "receipt_manifest": receipt_manifest,
        "payload_manifest": payload_manifest,
        "preflight_id": preflight_id,
    }


def _seal_actual_fixture(
    root: Path,
    predecessor: dict[str, Path | str],
    *,
    outer_run_id: str = "p2_ac_20260825_009",
    actual_id: str = "actual_9",
    accepted_attempt_id: str = "preflight_10",
    accepted_preflight_id: str | None = None,
) -> Path:
    root.mkdir(parents=True)
    packet_path = Path(predecessor["packet"])
    receipt_path = Path(predecessor["receipt"])
    receipt_manifest_path = Path(predecessor["receipt_manifest"])
    preflight_id = accepted_preflight_id or str(predecessor["preflight_id"])
    actual = root / "packet.json"
    _write_json(
        actual,
        {
            "packet_version": "p2_receipt_bound_actual_packet_v6",
            "outer_run_id": outer_run_id,
            "actual_attempt_id": actual_id,
            "accepted_entry_receipt": {
                "preflight_packet_root_text": str(packet_path.parent),
                "preflight_packet_root_canonical_text": (
                    packet_path.parent.resolve().as_posix()
                ),
                "preflight_output_root_text": str(receipt_path.parent),
                "preflight_output_root_canonical_text": (
                    receipt_path.parent.resolve().as_posix()
                ),
                "preflight_attempt_id": accepted_attempt_id,
                "preflight_id": preflight_id,
                "payload_manifest_sha256": predecessor["payload_manifest"],
                "receipt_path": receipt_path.resolve().as_posix(),
                "receipt_sha256": _file_sha256(receipt_path),
                "receipt_manifest_path": receipt_manifest_path.resolve().as_posix(),
                "receipt_manifest_sha256": _file_sha256(receipt_manifest_path),
                "receipt_status": "ready",
                "receipt_actual_authorized": False,
                "macro_review": "accepted_for_execution_packet_preparation_only",
            },
            "seal_status": {
                "packet_prepared": True,
                "packet_sealed": True,
                "execution_root_created": False,
                "model_calls": 0,
                "ProductExecution_runs": 0,
                "Builds": 0,
                "Runtime_runs": 0,
            },
        },
    )
    return actual


def _rewrite_preflight_packet(
    predecessor: dict[str, Path | str],
    mutate,
) -> None:
    packet_path = Path(predecessor["packet"])
    preflight_path = Path(predecessor["preflight"])
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    mutate(packet)
    _write_json(packet_path, packet)
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    payload_files = {
        "packet.json": _file_sha256(packet_path),
        "sealed_entry_runner.py": _file_sha256(packet_path.parent / "sealed_entry_runner.py"),
    }
    preflight["files"] = {
        name: {"sha256": digest, "bytes": (packet_path.parent / name).stat().st_size}
        for name, digest in payload_files.items()
    }
    preflight["payload_manifest_sha256"] = _canonical_sha256(payload_files)
    _write_json(preflight_path, preflight)


def _fixture(tmp_path: Path) -> tuple[
    SealedPreflightPreparationRequestV1,
    PreflightPreparationDependenciesV1,
    dict[str, Path | str],
]:
    platform = tmp_path / "platform"
    _initialize_repository(platform)
    (platform / "README.md").write_text("platform\n", encoding="utf-8")
    _git(platform, "add", ".")
    _git(platform, "commit", "-m", "platform")

    source = tmp_path / "source"
    _initialize_repository(source)
    project = source / "AccurateCrosshair"
    project.mkdir()
    (project / "AccurateCrosshair.csproj").write_text(
        "<Project />\n", encoding="utf-8"
    )
    (project / "Loader.cs").write_text(
        "public sealed class Loader {}\n", encoding="utf-8"
    )
    _git(source, "add", ".")
    _git(source, "commit", "-m", "source")

    predecessor = _seal_preflight_fixture(tmp_path / "lineage" / "preflight10")
    actual = _seal_actual_fixture(
        tmp_path / "lineage" / "actual9",
        predecessor,
    )
    model_calls: list[tuple[str, str]] = []

    def read_model(base_url: str, model: str) -> dict[str, Any]:
        model_calls.append((base_url, model))
        return {
            "name": model,
            "model": model,
            "digest": "b" * 64,
            "base_url": base_url,
            "details": {
                "context_length": 65536,
                "quantization_level": "Q4_K_M",
            },
            "capabilities": ["completion"],
        }

    dependencies = PreflightPreparationDependenciesV1(
        model_identity_reader=read_model,
        server_version_reader=lambda _base_url: "1.2.3",
        context_validator=lambda identity, requested_context_window: identity[
            "details"
        ]["context_length"],
    )
    (tmp_path / "delivery").mkdir()
    request = SealedPreflightPreparationRequestV1(
        contract_version="1",
        packet_root=str(tmp_path / "delivery" / "preflight11"),
        packet_date="2026-08-27",
        task_id="ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001",
        request_text="Enable a deterministic AccurateCrosshair spread toggle.",
        identity_series="p2_ac_20260825",
        identity_sequence=10,
        configuration_id="deterministic_projection",
        platform_root=str(platform),
        allowed_dirty_paths=(),
        source_root=str(source),
        target_project=str(project),
        project_file="AccurateCrosshair/AccurateCrosshair.csproj",
        primary_source_paths=("AccurateCrosshair/Loader.cs",),
        git_executable=str(_git_executable()),
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="local-neutral-model",
        ollama_context_window=32768,
        ollama_output_budget=4096,
        preflight_lineage_packet_paths=(str(predecessor["packet"]),),
        predecessor_receipt_path=str(predecessor["receipt"]),
        predecessor_receipt_manifest_path=str(predecessor["receipt_manifest"]),
        actual_lineage_packet_paths=(str(actual),),
    )
    return request, dependencies, predecessor


def test_actual9_preflight10_lineage_derives_the_next_identity_group(
    tmp_path: Path,
) -> None:
    request, dependencies, predecessor = _fixture(tmp_path)

    result = prepare_sealed_entry_preflight(request, dependencies=dependencies)

    assert result.status == "sealed"
    assert result.identities.to_dict() == {
        "identity_series": "p2_ac_20260825",
        "identity_sequence": 10,
        "future_canary_number": 10,
        "outer_run_id": "p2_ac_20260825_010",
        "future_actual_id": "actual_10",
        "preflight_attempt_id": "preflight_11",
        "preflight_id": (
            "entry_preflight_012_deterministic_projection_at_"
            + _git(Path(request.platform_root), "rev-parse", "HEAD")[:8]
        ),
    }
    assert result.predecessor_preflight_id == predecessor["preflight_id"]
    assert result.actual_authorized is False
    assert result.canary_authorized is False
    packet = json.loads((Path(request.packet_root) / "packet.json").read_text())
    assert packet["outer_run_id"] == "p2_ac_20260825_010"
    assert packet["future_execution_binding"] == {
        "actual_authorized": False,
        "attempt_consumed": False,
        "canary_authorized": False,
        "execution_root": None,
        "future_attempt_id": "actual_10",
        "future_canary_number": 10,
        "status": "preserved_as_non_authorizing_future_identity",
    }


def test_wrong_009_10_actual10_mapping_fails_before_any_file_write(
    tmp_path: Path,
) -> None:
    request, dependencies, predecessor = _fixture(tmp_path)

    def wrong_mapping(packet: dict[str, Any]) -> None:
        packet["product_execution_selection"]["future_canary_number"] = 10
        packet["product_execution_selection"]["future_attempt_id"] = "actual_10"

    _rewrite_preflight_packet(predecessor, wrong_mapping)

    with pytest.raises(
        PreflightPreparationError,
        match="LINEAGE_RUN_IDENTITY_MISMATCH",
    ):
        prepare_sealed_entry_preflight(request, dependencies=dependencies)

    assert not Path(request.packet_root).exists()


def test_public_api_has_no_independent_run_identity_inputs() -> None:
    request_fields = set(inspect.signature(SealedPreflightPreparationRequestV1).parameters)
    forbidden = {
        "outer_run_id",
        "future_canary_number",
        "future_actual_id",
        "future_attempt_id",
        "attempt_id",
        "preflight_id",
    }
    assert request_fields.isdisjoint(forbidden)
    assert derive_run_identities(
        identity_series="p2_ac_20260825",
        identity_sequence=10,
    ).to_dict() == {
        "identity_series": "p2_ac_20260825",
        "identity_sequence": 10,
        "future_canary_number": 10,
        "outer_run_id": "p2_ac_20260825_010",
        "future_actual_id": "actual_10",
    }


def _cli_arguments() -> list[str]:
    return [
        "prepare-sealed-entry-preflight",
        "--packet-root",
        "C:/packet",
        "--packet-date",
        "2026-08-27",
        "--task-id",
        "task",
        "--request-text",
        "request",
        "--identity-series",
        "p2_ac_20260825",
        "--identity-sequence",
        "10",
        "--configuration-id",
        "deterministic_projection",
        "--platform-root",
        "C:/platform",
        "--source-root",
        "C:/source",
        "--target-project",
        "C:/source/Project",
        "--project-file",
        "Project/Project.csproj",
        "--primary-source",
        "Project/Entry.cs",
        "--git-executable",
        "C:/git.exe",
        "--ollama-base-url",
        "http://127.0.0.1:11434",
        "--ollama-model",
        "model",
        "--ollama-context-window",
        "32768",
        "--ollama-output-budget",
        "4096",
        "--preflight-lineage-packet",
        "C:/lineage/preflight/packet.json",
        "--predecessor-receipt",
        "C:/lineage/preflight/receipt.json",
        "--predecessor-receipt-manifest",
        "C:/lineage/preflight/receipt_manifest.json",
        "--actual-lineage-packet",
        "C:/lineage/actual/packet.json",
    ]


def test_cli_exposes_one_series_and_sequence_without_independent_identities() -> None:
    args = build_parser().parse_args(_cli_arguments())

    assert args.command == "prepare-sealed-entry-preflight"
    assert args.identity_series == "p2_ac_20260825"
    assert args.identity_sequence == 10
    assert set(vars(args)).isdisjoint(
        {
            "outer_run_id",
            "future_canary_number",
            "future_actual_id",
            "attempt_id",
            "preflight_id",
        }
    )


def test_cli_delegates_to_the_preparation_owner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, Any] = {}

    class Result:
        def to_dict(self) -> dict[str, Any]:
            return {
                "status": "sealed",
                "actual_authorized": False,
                "canary_authorized": False,
            }

    def prepare(request: SealedPreflightPreparationRequestV1) -> Result:
        captured["request"] = request
        return Result()

    monkeypatch.setattr(
        "src.mod_agent.cli.prepare_sealed_entry_preflight",
        prepare,
    )

    exit_code = cli_main(_cli_arguments())

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "status": "sealed",
        "actual_authorized": False,
        "canary_authorized": False,
    }
    request = captured["request"]
    assert isinstance(request, SealedPreflightPreparationRequestV1)
    assert request.identity_series == "p2_ac_20260825"
    assert request.identity_sequence == 10
    assert request.preflight_lineage_packet_paths == (
        "C:/lineage/preflight/packet.json",
    )
    assert request.actual_lineage_packet_paths == (
        "C:/lineage/actual/packet.json",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("outer_run_id", "p2_ac_20260825_010"),
        ("actual_attempt_id", "actual_10"),
        ("accepted_attempt_id", "preflight_11"),
        (
            "accepted_preflight_id",
            "entry_preflight_012_deterministic_projection_at_deadbeef",
        ),
    ),
)
def test_any_used_identity_in_explicit_history_fails_closed(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    request, dependencies, predecessor = _fixture(tmp_path)
    kwargs = {
        "outer_run_id": "p2_ac_20260825_008",
        "actual_id": "actual_8",
        "accepted_attempt_id": "preflight_8",
        "accepted_preflight_id": "entry_preflight_009_older",
    }
    if field in kwargs:
        kwargs[field] = value
    elif field == "actual_attempt_id":
        kwargs["actual_id"] = value
    else:
        kwargs[field] = value
    extra = _seal_actual_fixture(
        tmp_path / "lineage" / f"used_{field}",
        predecessor,
        **kwargs,
    )
    request = replace(
        request,
        actual_lineage_packet_paths=(
            *request.actual_lineage_packet_paths,
            str(extra),
        ),
    )

    with pytest.raises(PreflightPreparationError):
        prepare_sealed_entry_preflight(request, dependencies=dependencies)

    assert not Path(request.packet_root).exists()


@pytest.mark.parametrize("failure", ("missing", "unknown", "receipt_hash", "contradictory"))
def test_missing_unknown_or_contradictory_lineage_fails_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    request, dependencies, predecessor = _fixture(tmp_path)
    if failure == "missing":
        request = replace(
            request,
            actual_lineage_packet_paths=(str(tmp_path / "missing.json"),),
        )
    elif failure == "unknown":
        actual = Path(request.actual_lineage_packet_paths[0])
        payload = json.loads(actual.read_text(encoding="utf-8"))
        payload["packet_version"] = "unknown_packet_v1"
        _write_json(actual, payload)
    elif failure == "receipt_hash":
        receipt = Path(request.predecessor_receipt_path)
        receipt.write_text(receipt.read_text(encoding="utf-8") + " ", encoding="utf-8")
    else:
        actual = Path(request.actual_lineage_packet_paths[0])
        payload = json.loads(actual.read_text(encoding="utf-8"))
        payload["accepted_entry_receipt"]["preflight_id"] = "entry_preflight_999_wrong"
        _write_json(actual, payload)

    with pytest.raises(PreflightPreparationError):
        prepare_sealed_entry_preflight(request, dependencies=dependencies)

    assert not Path(request.packet_root).exists()
    assert Path(predecessor["packet"]).is_file()


def test_existing_packet_root_fails_without_overwrite(tmp_path: Path) -> None:
    request, dependencies, _ = _fixture(tmp_path)
    root = Path(request.packet_root)
    root.mkdir(parents=True)
    marker = root / "keep.txt"
    marker.write_text("keep\n", encoding="utf-8")

    with pytest.raises(PreflightPreparationError, match="PACKET_ROOT_ALREADY_EXISTS"):
        prepare_sealed_entry_preflight(request, dependencies=dependencies)

    assert marker.read_text(encoding="utf-8") == "keep\n"
    assert [path.name for path in root.iterdir()] == ["keep.txt"]


def test_success_writes_exact_five_files_with_independent_manifests_and_one_command(
    tmp_path: Path,
) -> None:
    request, dependencies, _ = _fixture(tmp_path)

    result = prepare_sealed_entry_preflight(request, dependencies=dependencies)

    root = Path(request.packet_root)
    assert {path.name for path in root.iterdir()} == {
        "packet.json",
        "sealed_entry_runner.py",
        "PREFLIGHT.json",
        "RUN.md",
        "FRESH_PREFLIGHT_PROMPT.md",
    }
    assert not (root / "FRESH_ACTUAL_PROMPT.md").exists()
    preflight = json.loads((root / "PREFLIGHT.json").read_text(encoding="utf-8"))
    payload_files = {
        name: _file_sha256(root / name)
        for name in ("packet.json", "sealed_entry_runner.py")
    }
    delivery_files = {
        name: _file_sha256(root / name)
        for name in (
            "packet.json",
            "sealed_entry_runner.py",
            "RUN.md",
            "FRESH_PREFLIGHT_PROMPT.md",
        )
    }
    assert _canonical_sha256(payload_files) == result.payload_manifest_sha256
    assert _canonical_sha256(delivery_files) == result.delivery_manifest_sha256
    assert preflight["payload_manifest_sha256"] == result.payload_manifest_sha256
    assert preflight["delivery_manifest_sha256"] == result.delivery_manifest_sha256
    command = preflight["fresh_preflight"]["authorized_run_command"]
    assert command == result.authorized_run_command
    assert command in (root / "RUN.md").read_text(encoding="utf-8")
    assert command in (root / "FRESH_PREFLIGHT_PROMPT.md").read_text(encoding="utf-8")
    assert "--mode preflight-only" in command
    assert "actual_10" not in command


@pytest.mark.parametrize(
    ("mode", "code"),
    (("canary", "CANARY_NOT_AUTHORIZED"), ("actual", "ACTUAL_NOT_AUTHORIZED")),
)
def test_runner_rejects_canary_and_actual_without_side_effects(
    tmp_path: Path,
    mode: str,
    code: str,
) -> None:
    request, dependencies, _ = _fixture(tmp_path)
    result = prepare_sealed_entry_preflight(request, dependencies=dependencies)
    root = Path(request.packet_root)
    before = {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in root.rglob("*")
        if path.is_file()
    }

    completed = subprocess.run(
        (
            sys.executable,
            "-B",
            str(root / "sealed_entry_runner.py"),
            "--mode",
            mode,
            "--packet-root",
            str(root),
            "--payload-manifest-sha256",
            result.payload_manifest_sha256,
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    payload = json.loads(completed.stdout)
    after = {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert completed.returncode == 2
    assert payload["code"] == code
    assert payload["model_calls"] == 0
    assert payload["generation_calls"] == 0
    assert payload["ProductExecution_runs"] == 0
    assert payload["Builds"] == 0
    assert payload["Apply_runs"] == 0
    assert payload["execution_root_created"] is False
    assert payload["actual_authorized"] is False
    assert before == after
    assert len(after) == 5


def test_same_inputs_are_deterministic_across_two_fresh_roots(tmp_path: Path) -> None:
    request, dependencies, _ = _fixture(tmp_path)
    first = prepare_sealed_entry_preflight(request, dependencies=dependencies)
    (tmp_path / "second_delivery").mkdir()
    second_request = replace(
        request,
        packet_root=str(tmp_path / "second_delivery" / "preflight11"),
    )
    second = prepare_sealed_entry_preflight(second_request, dependencies=dependencies)
    first_root = Path(request.packet_root)
    second_root = Path(second_request.packet_root)

    assert (first_root / "sealed_entry_runner.py").read_bytes() == (
        second_root / "sealed_entry_runner.py"
    ).read_bytes()
    first_packet = json.loads((first_root / "packet.json").read_text(encoding="utf-8"))
    second_packet = json.loads((second_root / "packet.json").read_text(encoding="utf-8"))
    for packet in (first_packet, second_packet):
        packet.pop("delivery")
    assert first_packet == second_packet
    assert first.identities == second.identities
    assert first.predecessor_preflight_id == second.predecessor_preflight_id


def test_concurrent_seal_has_one_winner_and_no_partial_packet(tmp_path: Path) -> None:
    request, dependencies, _ = _fixture(tmp_path)

    def prepare() -> str:
        try:
            return prepare_sealed_entry_preflight(
                request,
                dependencies=dependencies,
            ).status
        except PreflightPreparationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: prepare(), range(2)))

    assert outcomes.count("sealed") == 1
    assert outcomes.count("PACKET_ROOT_ALREADY_EXISTS") == 1
    assert {path.name for path in Path(request.packet_root).iterdir()} == {
        "packet.json",
        "sealed_entry_runner.py",
        "PREFLIGHT.json",
        "RUN.md",
        "FRESH_PREFLIGHT_PROMPT.md",
    }


def test_preparation_uses_metadata_owners_without_execution_authority(
    tmp_path: Path,
) -> None:
    request, dependencies, _ = _fixture(tmp_path)
    calls: list[str] = []
    dependencies = replace(
        dependencies,
        model_identity_reader=lambda base_url, model: (
            calls.append("model_identity")
            or {
                "name": model,
                "model": model,
                "digest": "b" * 64,
                "base_url": base_url,
                "details": {"context_length": 65536},
                "capabilities": ["completion"],
            }
        ),
        server_version_reader=lambda _base_url: (
            calls.append("server_version") or "1.2.3"
        ),
        context_validator=lambda identity, requested_context_window: (
            calls.append("context_validation")
            or identity["details"]["context_length"]
        ),
    )

    result = prepare_sealed_entry_preflight(request, dependencies=dependencies)

    assert calls == ["model_identity", "server_version", "context_validation"]
    assert result.actual_authorized is False
    assert result.canary_authorized is False
    assert result.ProductExecution_runs == 0
    assert result.Builds == 0
    assert result.Apply_runs == 0
