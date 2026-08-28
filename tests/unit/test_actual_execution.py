from __future__ import annotations

import hashlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.mod_agent.actual_execution import (
    ACTUAL_CONSUMPTION_FILENAME,
    ACTUAL_JOURNAL_FILENAME,
    ACTUAL_PACKET_FILENAME,
    ACTUAL_SEAL_FILENAME,
    ACTUAL_THIN_LAUNCHER_FILENAME,
    ActualExecutionDependenciesV1,
    ActualProductExecutionSelectionV1,
    ActualRunError,
    ActualRunPreparationRequestV1,
    ActualRunSpecV1,
    execute_sealed_actual_run,
    prepare_sealed_actual_run,
)
from src.mod_agent.cli import build_parser, main as cli_main
from src.mod_agent.entry_admission import (
    EntryAdmissionDependenciesV1,
    admit_sealed_entry,
    entry_request_from_preflight_packet,
)
from src.mod_agent.local_entry import LocalEntryError, run_local_request
from src.mod_agent.preflight_preparation import (
    _load_actual_record,
    prepare_sealed_entry_preflight,
)
from tests.unit.test_preflight_preparation import (
    _file_sha256,
    _fixture as preflight_fixture,
    _seal_actual_fixture,
)


def _admit_preflight(
    request: Any,
    preflight_dependencies: Any,
) -> tuple[Path, Path]:
    root = Path(request.packet_root)
    packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
    entry = entry_request_from_preflight_packet(
        packet,
        payload_manifest_sha256=json.loads(
            (root / "PREFLIGHT.json").read_text(encoding="utf-8")
        )["payload_manifest_sha256"],
    )
    run = admit_sealed_entry(
        entry,
        dependencies=EntryAdmissionDependenciesV1(
            git_admission=entry.strict_git_admission(),
            model_identity_reader=preflight_dependencies.model_identity_reader,
            server_version_reader=preflight_dependencies.server_version_reader,
            context_validator=preflight_dependencies.context_validator,
        ),
    )
    assert run.result.status == "ready"
    return Path(str(run.receipt_path)), Path(str(run.receipt_manifest_path))
def _prepared_actual(tmp_path: Path):
    preflight_request, preflight_dependencies, _ = preflight_fixture(tmp_path)
    preflight = prepare_sealed_entry_preflight(
        preflight_request,
        dependencies=preflight_dependencies,
    )
    receipt, receipt_manifest = _admit_preflight(
        preflight_request,
        preflight_dependencies,
    )
    packet_root = tmp_path / "delivery" / "actual10"
    request = ActualRunPreparationRequestV1(
        contract_version="1",
        packet_root=str(packet_root),
        accepted_preflight_packet_path=str(
            Path(preflight_request.packet_root) / "packet.json"
        ),
        accepted_preflight_packet_sha256=preflight.packet_sha256,
        accepted_preflight_manifest_sha256=preflight.preflight_sha256,
        accepted_payload_manifest_sha256=preflight.payload_manifest_sha256,
        accepted_receipt_path=str(receipt),
        accepted_receipt_sha256=_file_sha256(receipt),
        accepted_receipt_manifest_path=str(receipt_manifest),
        accepted_receipt_manifest_sha256=_file_sha256(receipt_manifest),
        actual_lineage_packet_paths=tuple(
            preflight_request.actual_lineage_packet_paths
        ),
        product_execution=ActualProductExecutionSelectionV1(
            contract_version="1",
            workspace_base=str((tmp_path / "actual_workspaces").resolve()),
            settings_path=str((tmp_path / "settings.yaml").resolve()),
            requested_completion_scope="compile_only",
            completion_classification=(
                ("changed_product_build", True),
                ("runtime_required", False),
            ),
            objective_verification_command=("dotnet", "test"),
            game_folder_build_binding=None,
            compiled_artifact_inspection_profile=None,
        ),
    )
    dependencies = ActualExecutionDependenciesV1(
        model_identity_reader=preflight_dependencies.model_identity_reader,
        server_version_reader=preflight_dependencies.server_version_reader,
        context_validator=preflight_dependencies.context_validator,
    )
    result = prepare_sealed_actual_run(request, dependencies=dependencies)
    return request, dependencies, result, preflight


def test_prepare_derives_future_identities_and_preserves_owner_inputs(
    tmp_path: Path,
) -> None:
    request, _, result, preflight = _prepared_actual(tmp_path)

    assert result.outer_run_id == preflight.identities.outer_run_id
    assert result.actual_attempt_id == preflight.identities.future_actual_id
    assert result.actual_authorized is False
    assert result.model_generation_calls == 0
    assert result.ProductExecution_runs == 0
    assert result.Builds == 0
    assert result.Apply_runs == 0
    root = Path(request.packet_root)
    assert {path.name for path in root.iterdir()} == {
        ACTUAL_PACKET_FILENAME,
        ACTUAL_SEAL_FILENAME,
        ACTUAL_THIN_LAUNCHER_FILENAME,
        "RUN.md",
    }
    packet = json.loads((root / ACTUAL_PACKET_FILENAME).read_text(encoding="utf-8"))
    spec = ActualRunSpecV1.from_dict(packet["actual_run_spec"])
    preflight_packet = json.loads(
        Path(request.accepted_preflight_packet_path).read_text(encoding="utf-8")
    )
    assert spec.outer_run_id == preflight.identities.outer_run_id
    assert spec.actual_attempt_id == preflight.identities.future_actual_id
    assert spec.request == "Enable a deterministic AccurateCrosshair spread toggle."
    assert spec.platform["HEAD"] == preflight_packet["platform"]["current_checkpoint"]
    assert spec.model["digest"] == "b" * 64
    assert spec.model["quantization_level"] == "Q4_K_M"
    assert spec.model["configured_context"] == 32768
    assert spec.model["output_budget"] == 4096
    assert spec.selected_configuration["main_ollama_timeout_seconds"] == 600.0
    assert spec.selected_configuration["route"] == (
        "qwen3.6:27b × current full_correction"
    )
    assert spec.product_execution == request.product_execution
    assert spec.accepted_preflight["receipt_sha256"] == _file_sha256(
        Path(request.accepted_receipt_path)
    )
    assert "feature_spec_sha256" not in json.dumps(spec.to_dict())
    run_text = (root / "RUN.md").read_text(encoding="utf-8")
    assert result.packet_sha256 in result.run_command_requiring_separate_authorization
    assert result.seal_sha256 in result.run_command_requiring_separate_authorization
    assert result.run_command_requiring_separate_authorization in run_text
    assert "receipt remains non-authorizing" in run_text


def test_public_prepare_request_has_no_independent_outer_or_actual_identity() -> None:
    fields = set(inspect.signature(ActualRunPreparationRequestV1).parameters)
    assert fields.isdisjoint(
        {
            "outer_run_id",
            "actual_attempt_id",
            "future_actual_id",
            "future_canary_number",
        }
    )


def test_run_local_request_requires_explicit_identities_as_one_pair() -> None:
    signature = inspect.signature(run_local_request)
    assert signature.parameters["run_id"].default is None
    assert signature.parameters["request_id"].default is None

    with pytest.raises(LocalEntryError, match="must be supplied together"):
        run_local_request(
            description="request",
            target_project="missing",
            workspace_base="missing",
            settings_path="missing",
            confirm_isolated_write=True,
            allow_build=True,
            allow_source_disclosure=False,
            local_ollama=True,
            diff_approval_reader=lambda _diff: "literal user input",
            run_id="outer_001",
        )


@pytest.mark.parametrize(
    "failure",
    (
        "receipt_status",
        "receipt_hash",
        "manifest_hash",
        "payload_manifest",
        "future_identity",
        "identity_consumed",
        "platform_head",
        "source",
        "model",
    ),
)
def test_prepare_fails_closed_before_actual_packet_write(
    tmp_path: Path,
    failure: str,
) -> None:
    preflight_request, preflight_dependencies, predecessor = preflight_fixture(tmp_path)
    prepared_preflight = prepare_sealed_entry_preflight(
        preflight_request,
        dependencies=preflight_dependencies,
    )
    receipt, receipt_manifest = _admit_preflight(
        preflight_request,
        preflight_dependencies,
    )
    accepted_receipt_sha256 = _file_sha256(receipt)
    accepted_receipt_manifest_sha256 = _file_sha256(receipt_manifest)
    actual_lineage = list(preflight_request.actual_lineage_packet_paths)
    if failure == "receipt_status":
        payload = json.loads(receipt.read_text(encoding="utf-8"))
        payload["result"]["status"] = "blocked"
        receipt.write_text(json.dumps(payload), encoding="utf-8")
    elif failure == "receipt_hash":
        receipt.write_text(receipt.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif failure == "manifest_hash":
        receipt_manifest.write_text(
            receipt_manifest.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
    elif failure == "payload_manifest":
        payload = json.loads(receipt_manifest.read_text(encoding="utf-8"))
        payload["payload_manifest_sha256"] = "e" * 64
        receipt_manifest.write_text(json.dumps(payload), encoding="utf-8")
    elif failure == "future_identity":
        packet_path = Path(preflight_request.packet_root) / "packet.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["future_execution_binding"]["future_attempt_id"] = "actual_999"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
    elif failure == "identity_consumed":
        current_preflight = {
            "packet": Path(preflight_request.packet_root) / "packet.json",
            "receipt": receipt,
            "receipt_manifest": receipt_manifest,
            "payload_manifest": json.loads(
                (Path(preflight_request.packet_root) / "PREFLIGHT.json").read_text()
            )["payload_manifest_sha256"],
            "preflight_id": json.loads(
                (Path(preflight_request.packet_root) / "packet.json").read_text()
            )["preflight_id"],
        }
        actual_lineage.append(
            str(
                _seal_actual_fixture(
                    tmp_path / "lineage" / "consumed_actual10",
                    current_preflight,
                    outer_run_id="p2_ac_20260825_010",
                    actual_id="actual_10",
                    accepted_attempt_id="preflight_12",
                )
            )
        )
    elif failure == "platform_head":
        platform = Path(preflight_request.platform_root)
        (platform / "new.txt").write_text("new\n", encoding="utf-8")
        from tests.unit.test_preflight_preparation import _git

        _git(platform, "add", ".")
        _git(platform, "commit", "-m", "drift")
    elif failure == "source":
        Path(preflight_request.target_project, "Loader.cs").write_text(
            "public sealed class Changed {}\n", encoding="utf-8"
        )
    else:
        preflight_dependencies = replace(
            preflight_dependencies,
            model_identity_reader=lambda base_url, model: {
                "name": model,
                "model": model,
                "digest": "d" * 64,
                "base_url": base_url,
                "details": {
                    "context_length": 65536,
                    "quantization_level": "Q4_K_M",
                },
                "capabilities": ["completion"],
            },
        )
    request = ActualRunPreparationRequestV1(
        contract_version="1",
        packet_root=str(tmp_path / "delivery" / "actual10"),
        accepted_preflight_packet_path=str(
            Path(preflight_request.packet_root) / "packet.json"
        ),
        accepted_preflight_packet_sha256=prepared_preflight.packet_sha256,
        accepted_preflight_manifest_sha256=prepared_preflight.preflight_sha256,
        accepted_payload_manifest_sha256=(
            prepared_preflight.payload_manifest_sha256
        ),
        accepted_receipt_path=str(receipt),
        accepted_receipt_sha256=accepted_receipt_sha256,
        accepted_receipt_manifest_path=str(receipt_manifest),
        accepted_receipt_manifest_sha256=accepted_receipt_manifest_sha256,
        actual_lineage_packet_paths=tuple(actual_lineage),
        product_execution=ActualProductExecutionSelectionV1(
            contract_version="1",
            workspace_base=str((tmp_path / "workspaces").resolve()),
            settings_path=str((tmp_path / "settings.yaml").resolve()),
            requested_completion_scope="compile_only",
        ),
    )
    dependencies = ActualExecutionDependenciesV1(
        model_identity_reader=preflight_dependencies.model_identity_reader,
        server_version_reader=preflight_dependencies.server_version_reader,
        context_validator=preflight_dependencies.context_validator,
    )

    with pytest.raises(ActualRunError):
        prepare_sealed_actual_run(request, dependencies=dependencies)

    assert not Path(request.packet_root).exists()
    assert Path(predecessor["packet"]).is_file()


def test_execute_requires_runtime_authorization_and_revalidates_before_owner(
    tmp_path: Path,
) -> None:
    request, dependencies, prepared, _ = _prepared_actual(tmp_path)
    calls: list[dict[str, Any]] = []
    dependencies = replace(
        dependencies,
        execution_owner=lambda **kwargs: calls.append(kwargs) or {},
    )

    with pytest.raises(ActualRunError, match="ACTUAL_EXECUTION_AUTHORIZATION_REQUIRED"):
        execute_sealed_actual_run(
            request.packet_root,
            expected_packet_sha256=prepared.packet_sha256,
            expected_seal_sha256=prepared.seal_sha256,
            actual_execution_authorized=False,
            diff_approval_reader=lambda _diff: "user-input",
            dependencies=dependencies,
        )

    assert calls == []
    assert not (Path(request.packet_root) / ACTUAL_CONSUMPTION_FILENAME).exists()

    with pytest.raises(ActualRunError, match="ACTUAL_REVIEW_HASH_DRIFT"):
        execute_sealed_actual_run(
            request.packet_root,
            expected_packet_sha256="f" * 64,
            expected_seal_sha256=prepared.seal_sha256,
            actual_execution_authorized=True,
            diff_approval_reader=lambda _diff: "user-input",
            dependencies=dependencies,
        )
    assert calls == []
    assert not (Path(request.packet_root) / ACTUAL_CONSUMPTION_FILENAME).exists()


def test_repeat_root_does_not_overwrite_and_concurrent_seal_has_one_winner(
    tmp_path: Path,
) -> None:
    request, dependencies, prepared, _ = _prepared_actual(tmp_path)
    marker = Path(request.packet_root) / ACTUAL_PACKET_FILENAME
    packet_sha256 = _file_sha256(marker)

    with pytest.raises(ActualRunError, match="ACTUAL_PACKET_ROOT_ALREADY_EXISTS"):
        prepare_sealed_actual_run(request, dependencies=dependencies)
    assert _file_sha256(marker) == packet_sha256

    race = replace(request, packet_root=str(tmp_path / "delivery" / "actual10_race"))

    def prepare() -> str:
        try:
            return prepare_sealed_actual_run(race, dependencies=dependencies).status
        except ActualRunError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: prepare(), range(2)))

    assert outcomes.count("sealed") == 1
    assert outcomes.count("ACTUAL_PACKET_ROOT_ALREADY_EXISTS") == 1
    assert {path.name for path in Path(race.packet_root).iterdir()} == set(
        ACTUAL_SEALED_FILE_SET_FOR_TEST
    )


ACTUAL_SEALED_FILE_SET_FOR_TEST = (
    ACTUAL_PACKET_FILENAME,
    ACTUAL_SEAL_FILENAME,
    ACTUAL_THIN_LAUNCHER_FILENAME,
    "RUN.md",
)


@pytest.mark.parametrize(
    "drift_file",
    (ACTUAL_PACKET_FILENAME, ACTUAL_SEAL_FILENAME, ACTUAL_THIN_LAUNCHER_FILENAME),
)
def test_execute_rejects_actual_seal_drift_before_owner(
    tmp_path: Path,
    drift_file: str,
) -> None:
    request, dependencies, prepared, _ = _prepared_actual(tmp_path)
    selected = Path(request.packet_root) / drift_file
    selected.write_text(selected.read_text(encoding="utf-8") + " ", encoding="utf-8")
    calls = 0

    def owner(**_kwargs):
        nonlocal calls
        calls += 1
        return {}

    with pytest.raises(ActualRunError):
        execute_sealed_actual_run(
            request.packet_root,
            expected_packet_sha256=prepared.packet_sha256,
            expected_seal_sha256=prepared.seal_sha256,
            actual_execution_authorized=True,
            diff_approval_reader=lambda _diff: "user-input",
            dependencies=replace(dependencies, execution_owner=owner),
        )

    assert calls == 0


@pytest.mark.parametrize(
    "drift",
    ("receipt", "preflight_payload", "platform_head", "source", "model"),
)
def test_execute_rejects_bound_fact_drift_before_owner(
    tmp_path: Path,
    drift: str,
) -> None:
    request, dependencies, prepared, _ = _prepared_actual(tmp_path)
    if drift == "receipt":
        path = Path(request.accepted_receipt_path)
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif drift == "preflight_payload":
        path = Path(request.accepted_preflight_packet_path).parent / "sealed_entry_runner.py"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif drift == "platform_head":
        packet = json.loads(
            Path(request.accepted_preflight_packet_path).read_text(encoding="utf-8")
        )
        platform = Path(packet["platform"]["repository_root"])
        (platform / "drift.txt").write_text("drift\n", encoding="utf-8")
        from tests.unit.test_preflight_preparation import _git

        _git(platform, "add", ".")
        _git(platform, "commit", "-m", "drift")
    elif drift == "source":
        packet = json.loads(
            Path(request.accepted_preflight_packet_path).read_text(encoding="utf-8")
        )
        Path(packet["source_identity"]["target_project"], "Loader.cs").write_text(
            "public sealed class Drift {}\n", encoding="utf-8"
        )
    else:
        dependencies = replace(
            dependencies,
            model_identity_reader=lambda base_url, model: {
                "name": model,
                "model": model,
                "digest": "c" * 64,
                "base_url": base_url,
                "details": {
                    "context_length": 65536,
                    "quantization_level": "Q4_K_M",
                },
                "capabilities": ["completion"],
            },
        )
    calls = 0

    def owner(**_kwargs):
        nonlocal calls
        calls += 1
        return {}

    with pytest.raises(ActualRunError):
        execute_sealed_actual_run(
            request.packet_root,
            expected_packet_sha256=prepared.packet_sha256,
            expected_seal_sha256=prepared.seal_sha256,
            actual_execution_authorized=True,
            diff_approval_reader=lambda _diff: "literal user input",
            dependencies=replace(dependencies, execution_owner=owner),
        )

    assert calls == 0
    assert not (Path(request.packet_root) / ACTUAL_CONSUMPTION_FILENAME).exists()


def test_execute_consumes_before_exactly_one_owner_call_and_projects_safe_journal(
    tmp_path: Path,
) -> None:
    request, dependencies, prepared, _ = _prepared_actual(tmp_path)
    calls: list[dict[str, Any]] = []
    diff_payload = {
        "diff_hash": "a" * 64,
        "unified_diff": "FULL DIFF\nraw source sentinel",
        "unified_diff_sha256": "b" * 64,
    }
    approvals: list[dict[str, Any]] = []

    def read_approval(value: dict[str, Any]) -> str:
        approvals.append(value)
        return "literal user input"

    def owner(**kwargs):
        assert (Path(request.packet_root) / ACTUAL_CONSUMPTION_FILENAME).is_file()
        calls.append(kwargs)
        assert kwargs["diff_approval_reader"](diff_payload) == "literal user input"
        return {
            "run_id": kwargs["run_id"],
            "current_stage": "blocked",
            "run_root": str(Path(kwargs["workspace_base"]) / kwargs["run_id"]),
            "model_call_count": 2,
            "local_model_input_audit": {"model_role": "requirement_findings"},
            "product_execution_result": {
                "platform_status": "completed",
                "execution_disposition": "domain_blocked",
                "failure_stage": None,
                "terminal_node": "blocked",
            },
            "raw_prompt": "raw prompt sentinel",
            "reasoning": "raw reasoning sentinel",
            "source": "raw source sentinel",
        }

    result = execute_sealed_actual_run(
        request.packet_root,
        expected_packet_sha256=prepared.packet_sha256,
        expected_seal_sha256=prepared.seal_sha256,
        actual_execution_authorized=True,
        diff_approval_reader=read_approval,
        dependencies=replace(dependencies, execution_owner=owner),
    )

    assert result.status == "terminal"
    assert len(calls) == 1
    assert approvals == [diff_payload]
    kwargs = calls[0]
    assert kwargs["run_id"] == prepared.outer_run_id
    assert kwargs["request_id"] == prepared.actual_attempt_id
    assert kwargs["description"] == "Enable a deterministic AccurateCrosshair spread toggle."
    assert kwargs["ollama_timeout_seconds"] == 600.0
    assert kwargs["ollama_context_window"] == 32768
    assert kwargs["ollama_max_output_tokens"] == 4096
    assert kwargs["local_ollama"] is True
    journal_text = (Path(request.packet_root) / ACTUAL_JOURNAL_FILENAME).read_text(
        encoding="utf-8"
    )
    journal = json.loads(journal_text)
    assert journal["model_calls"] == 2
    assert journal["last_observed_model_role"] == "requirement_findings"
    assert journal["stage"] == "blocked"
    assert journal["terminal"] == {
        "execution_disposition": "domain_blocked",
        "failure_stage": None,
        "platform_status": "completed",
        "terminal_node": "blocked",
    }
    assert all(
        sentinel not in journal_text
        for sentinel in ("raw prompt sentinel", "raw reasoning sentinel", "raw source sentinel")
    )

    with pytest.raises(ActualRunError, match="ACTUAL_IDENTITY_ALREADY_CONSUMED"):
        execute_sealed_actual_run(
            request.packet_root,
            expected_packet_sha256=prepared.packet_sha256,
            expected_seal_sha256=prepared.seal_sha256,
            actual_execution_authorized=True,
            diff_approval_reader=read_approval,
            dependencies=replace(dependencies, execution_owner=owner),
        )
    assert len(calls) == 1


def test_owner_exception_is_one_terminal_without_retry_or_automatic_replay(
    tmp_path: Path,
) -> None:
    request, dependencies, prepared, _ = _prepared_actual(tmp_path)
    calls = 0
    approvals = 0

    def owner(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("raw source and reasoning must not persist")

    def approval(_diff):
        nonlocal approvals
        approvals += 1
        return "not used"

    result = execute_sealed_actual_run(
        request.packet_root,
        expected_packet_sha256=prepared.packet_sha256,
        expected_seal_sha256=prepared.seal_sha256,
        actual_execution_authorized=True,
        diff_approval_reader=approval,
        dependencies=replace(dependencies, execution_owner=owner),
    )

    assert result.status == "failed"
    assert calls == 1
    assert approvals == 0
    journal_text = (Path(request.packet_root) / ACTUAL_JOURNAL_FILENAME).read_text(
        encoding="utf-8"
    )
    journal = json.loads(journal_text)
    assert journal["terminal"] == {
        "exception_type": "RuntimeError",
        "status": "owner_exception",
    }
    assert "raw source and reasoning" not in journal_text


def test_historical_v6_fixture_compatibility_claim_is_identity_and_receipt_only(
    tmp_path: Path,
) -> None:
    request, _, result, _ = _prepared_actual(tmp_path)
    packet = json.loads(
        (Path(request.packet_root) / ACTUAL_PACKET_FILENAME).read_text(encoding="utf-8")
    )
    spec = packet["actual_run_spec"]
    historical = json.loads(
        Path(request.actual_lineage_packet_paths[0]).read_text(encoding="utf-8")
    )

    assert historical["packet_version"] == "p2_receipt_bound_actual_packet_v6"
    assert set(historical) == {
        "packet_version",
        "outer_run_id",
        "actual_attempt_id",
        "accepted_entry_receipt",
        "seal_status",
    }
    assert spec["accepted_preflight"]["receipt_status"] == "ready"
    assert spec["accepted_preflight"]["receipt_actual_authorized"] is False
    assert result.semantic_compatibility_boundary == (
        "repository_v6_fixture_identity_and_receipt_lineage_only"
    )


def test_stable_v7_packet_is_readable_by_existing_actual_lineage_owner(
    tmp_path: Path,
) -> None:
    request, _, _, preflight = _prepared_actual(tmp_path)

    record = _load_actual_record(
        str(Path(request.packet_root) / ACTUAL_PACKET_FILENAME)
    )

    assert record.outer_run_id == preflight.identities.outer_run_id
    assert record.actual_id == preflight.identities.future_actual_id
    assert record.accepted_receipt_sha256 == request.accepted_receipt_sha256


def test_actual10_frozen_semantics_are_representable_without_byte_comparison() -> None:
    frozen = {
        "evidence_status": "historical_task_record_external_files_unavailable",
        "packet_version": "p2_receipt_bound_actual_packet_v6",
        "outer_run_id": "p2_ac_20260825_010",
        "actual_attempt_id": "actual_10",
        "historical_hashes": {
            "packet_sha256": (
                "cf351c0d9e2b8143bd285a1df420454b9f10f68f821775c22e082673cf30d0b7"
            ),
            "runner_sha256": (
                "1061ee4ddac160ad7317859713a1afb5a5671a5aabc8d3380340ff30905f1d88"
            ),
            "payload_manifest_sha256": (
                "d6366dbb5d3b6c0f945a9ac7586ffcddbb4e8dc26d0c22625fdebc23d94b9eaf"
            ),
            "delivery_manifest_sha256": (
                "76d0c7981b128c2a182d2c2709e8fb1af84da29b726d826b33124912ad5cf379"
            ),
            "receipt_sha256": (
                "6436283873df8cf38e180b441c5973c499e81201e7da9066a57f17881ab485d0"
            ),
            "receipt_manifest_sha256": (
                "83303ded4fb31086714c1d027ec29257c9c35b61f9983d2f54bb7c603ae31d80"
            ),
            "actual_result_sha256": "596ab34dcda6c97431481b6787dd954c539c0ff49bd6c078a1c1ded0ebe82128",
        },
        "source_identity_prefixes": {
            "repository_head": "d80ae700",
            "repository_tree": "cd4a59",
            "project_tree": "3e7f515",
            "snapshot_sha256": "ae5304",
        },
        "model": {
            "model": "qwen3.6:27b",
            "digest_prefix": "a50eda8e",
            "quantization_level": "Q4_K_M",
            "configured_context": 40960,
            "output_budget": 4096,
        },
        "selected_configuration": {
            "main_ollama_timeout_seconds": 600.0,
            "repair_ollama_timeout_seconds": None,
            "provider_fallback": False,
            "automatic_retry": False,
            "external_disclosure": False,
            "route": "full_correction",
            "model_projection_fields": ["requirements", "input_dispositions"],
            "deterministic_relation_rule": "one relation per requirement",
        },
        "execution_counts": {
            "run_local_request": 1,
            "requirement_projection": 1,
            "findings": 1,
            "ProductExecution": 1,
            "baseline_Build": 1,
            "Patch": 0,
            "diff_approval": 0,
            "Apply": 0,
            "changed_Build": 0,
            "Repair": 0,
            "Runtime": 0,
        },
    }

    assert frozen["outer_run_id"].rsplit("_", 1)[1] == "010"
    assert frozen["actual_attempt_id"] == "actual_10"
    assert frozen["selected_configuration"]["provider_fallback"] is False
    assert frozen["selected_configuration"]["automatic_retry"] is False
    assert frozen["execution_counts"]["run_local_request"] == 1
    assert frozen["execution_counts"]["Runtime"] == 0
    assert frozen["evidence_status"] != "byte_for_byte_verified"


def test_cli_separates_prepare_from_later_actual_authorization(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
            "prepare-sealed-actual",
            "--packet-root",
            "C:/actual",
            "--accepted-preflight-packet",
            "C:/preflight/packet.json",
            "--accepted-preflight-packet-sha256",
            "a" * 64,
            "--accepted-preflight-manifest-sha256",
            "b" * 64,
            "--accepted-payload-manifest-sha256",
            "c" * 64,
            "--accepted-receipt",
            "C:/preflight/receipt.json",
            "--accepted-receipt-sha256",
            "d" * 64,
            "--accepted-receipt-manifest",
            "C:/preflight/manifest.json",
            "--accepted-receipt-manifest-sha256",
            "e" * 64,
            "--workspace-root",
            "C:/workspaces",
            "--settings",
            "C:/settings.yaml",
    ]
    prepare = build_parser().parse_args(arguments)
    assert prepare.command == "prepare-sealed-actual"
    assert set(vars(prepare)).isdisjoint({"outer_run_id", "actual_attempt_id"})

    captured: dict[str, Any] = {}

    class Result:
        def to_dict(self) -> dict[str, Any]:
            return {"status": "sealed", "actual_authorized": False}

    def prepare_owner(request: ActualRunPreparationRequestV1) -> Result:
        captured["request"] = request
        return Result()

    monkeypatch.setattr(
        "src.mod_agent.cli.prepare_sealed_actual_run",
        prepare_owner,
    )
    assert cli_main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "sealed",
        "actual_authorized": False,
    }
    prepared_request = captured["request"]
    assert isinstance(prepared_request, ActualRunPreparationRequestV1)
    assert prepared_request.accepted_preflight_packet_sha256 == "a" * 64
    assert prepared_request.product_execution.requested_completion_scope == (
        "compile_only"
    )

    exit_code = cli_main(
        [
            "execute-sealed-actual",
            "--packet-root",
            "C:/missing",
            "--expected-packet-sha256",
            "a" * 64,
            "--expected-seal-sha256",
            "b" * 64,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["code"] == "ACTUAL_EXECUTION_AUTHORIZATION_REQUIRED"
