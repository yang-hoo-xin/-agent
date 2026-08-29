from __future__ import annotations

import json
import inspect
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.mod_agent.actual_execution import (
    ActualExecutionDependenciesV1,
    ActualProductExecutionSelectionV1,
    ActualRunPreparationRequestV1,
    prepare_sealed_actual_run,
)
from src.mod_agent.cli import main as cli_main
from src.mod_agent.preflight_preparation import (
    PreflightPreparationError,
    RunFamilyContinuationProfileV1,
    RunFamilyContinuationRequestV1,
    project_sealed_entry_receipt_review,
    prepare_sealed_entry_preflight,
)
from tests.unit.test_preflight_preparation import (
    _canonical_sha256,
    _file_sha256,
    _fixture,
    _git,
    _git_executable,
    _seal_actual_fixture,
    _write_json,
)


def test_continuation_contract_has_no_manual_sequence_or_lineage_inputs() -> None:
    profile_fields = set(
        inspect.signature(RunFamilyContinuationProfileV1).parameters
    )
    request_fields = set(
        inspect.signature(RunFamilyContinuationRequestV1).parameters
    )

    assert request_fields == {"contract_version", "packet_root", "profile"}
    assert "platform_code_checkpoint" in profile_fields
    assert profile_fields.isdisjoint(
        {
            "identity_sequence",
            "identity_series",
            "preflight_lineage_packet_paths",
            "actual_lineage_packet_paths",
            "predecessor_receipt_path",
            "predecessor_receipt_manifest_path",
        }
    )


def _write_ready_receipt(packet_root: Path) -> dict[str, Path | str]:
    packet_path = packet_root / "packet.json"
    preflight_path = packet_root / "PREFLIGHT.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    output_root = Path(packet["delivery"]["fresh_preflight_root_canonical_text"])
    output_root.mkdir()
    receipt = output_root / "entry_admission_receipt.json"
    receipt_manifest = output_root / "entry_admission_receipt_manifest.json"
    payload_manifest = preflight["payload_manifest_sha256"]
    source_binding = packet["source_identity"]["source_revision_binding"]
    dirty_status = packet["platform"].get("allowed_dirty_status_at_seal", {})
    result = {
        "Builds": 0,
        "ProductExecution_runs": 0,
        "actual_authorized": False,
        "attempt_consumed": False,
        "attempt_id": packet["attempt_id"],
        "blockers": [],
        "contract_version": "1",
        "execution_root_created": False,
        "first_failure_code": None,
        "first_failure_message": None,
        "first_failure_stage": None,
        "gate_receipts": [
            {
                "gate": "platform",
                "decision": "passed",
                "facts": {
                    "head": packet["platform"]["current_checkpoint"],
                    "branch": packet["platform"]["branch"],
                    "dirty_records": [
                        {"path": path, "status": status}
                        for path, status in dirty_status.items()
                    ],
                },
            },
            {
                "gate": "source",
                "decision": "passed",
                "facts": {
                    "repository_root": packet["source_identity"]["canonical_root"],
                    "repository_head": source_binding["repository_head"],
                    "repository_tree": source_binding["repository_tree"],
                    "project_root": source_binding["project_root"],
                    "project_tree": source_binding["project_tree"],
                    "snapshot_sha256": packet["source_identity"]["snapshot_sha256"],
                },
            },
            {
                "gate": "model",
                "decision": "passed",
                "facts": {
                    "model": packet["model_identity"]["model"],
                    "digest": packet["model_identity"]["digest"],
                    "server_version": packet["model_identity"]["server_version"],
                    "context_limit": packet["model_identity"]["context_limit"],
                    "configured_context": packet["model_identity"][
                        "configured_num_ctx"
                    ],
                    "output_budget": packet["model_identity"]["output_budget"],
                    "generation_calls": 0,
                },
            },
        ],
        "model_calls": 0,
        "outer_run_id": packet["outer_run_id"],
        "output_root_text": str(output_root),
        "packet_root_text": str(packet_root),
        "payload_manifest_sha256": payload_manifest,
        "status": "ready",
    }
    _write_json(
        receipt,
        {
            "actual_authorized": False,
            "output_root_text": str(output_root),
            "packet_root_text": str(packet_root),
            "receipt_version": "sealed_entry_admission_receipt_v1",
            "request_identity": {
                "attempt_id": packet["attempt_id"],
                "outer_run_id": packet["outer_run_id"],
                "payload_manifest_sha256": payload_manifest,
            },
            "result": result,
        },
    )
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
        "packet": packet_path,
        "preflight": preflight_path,
        "receipt": receipt,
        "receipt_manifest": receipt_manifest,
        "payload_manifest": payload_manifest,
        "preflight_id": packet["preflight_id"],
    }


def _continuation_fixture(
    tmp_path: Path,
    *,
    dirty_path: str | None = None,
    dirty_text: str = "dirty-v1\n",
    stable_anchor: bool = False,
) -> dict[str, Any]:
    explicit, dependencies, _ = _fixture(tmp_path)
    if dirty_path is not None:
        dirty_file = Path(explicit.platform_root) / dirty_path
        dirty_file.parent.mkdir(parents=True, exist_ok=True)
        dirty_file.write_text(dirty_text, encoding="utf-8")
        explicit = replace(explicit, allowed_dirty_paths=(dirty_path,))
    prepared = prepare_sealed_entry_preflight(
        explicit,
        dependencies=dependencies,
    )
    accepted = _write_ready_receipt(Path(explicit.packet_root))
    actual_prepared = None
    if stable_anchor:
        actual_prepared = prepare_sealed_actual_run(
            ActualRunPreparationRequestV1(
                contract_version="1",
                accepted_preflight_packet_path=Path(
                    accepted["packet"]
                ).resolve().as_posix(),
                accepted_preflight_packet_sha256=_file_sha256(
                    Path(accepted["packet"])
                ),
                accepted_preflight_manifest_sha256=_file_sha256(
                    Path(accepted["preflight"])
                ),
                accepted_payload_manifest_sha256=prepared.payload_manifest_sha256,
                accepted_receipt_path=Path(
                    accepted["receipt"]
                ).resolve().as_posix(),
                accepted_receipt_sha256=_file_sha256(Path(accepted["receipt"])),
                accepted_receipt_manifest_path=Path(
                    accepted["receipt_manifest"]
                ).resolve().as_posix(),
                accepted_receipt_manifest_sha256=_file_sha256(
                    Path(accepted["receipt_manifest"])
                ),
                product_execution=ActualProductExecutionSelectionV1(
                    contract_version="1",
                    workspace_base=str((tmp_path / "workspace").resolve()),
                    settings_path=str((tmp_path / "settings.json").resolve()),
                    requested_completion_scope="compile_only",
                ),
            ),
            dependencies=ActualExecutionDependenciesV1(
                model_identity_reader=dependencies.model_identity_reader,
                server_version_reader=dependencies.server_version_reader,
                context_validator=dependencies.context_validator,
            ),
        )
        anchor = Path(actual_prepared.packet_root) / "packet.json"
    else:
        anchor = _seal_actual_fixture(
            tmp_path / "lineage" / "actual10_anchor",
            accepted,
            outer_run_id=prepared.identities.outer_run_id,
            actual_id=prepared.identities.future_actual_id,
            accepted_attempt_id=prepared.identities.preflight_attempt_id,
            accepted_preflight_id=prepared.identities.preflight_id,
        )
    platform = Path(explicit.platform_root)
    platform_code_checkpoint = _git(platform, "rev-parse", "HEAD")
    continuation = RunFamilyContinuationRequestV1(
        contract_version="1",
        packet_root=str(tmp_path / "delivery" / "preflight13"),
        profile=RunFamilyContinuationProfileV1(
            contract_version="1",
            packet_date="2026-08-29",
            anchor_actual_packet_paths=(str(anchor.resolve()),),
            platform_code_checkpoint=platform_code_checkpoint,
            allowed_post_checkpoint_paths=(),
        ),
    )
    return {
        "explicit": explicit,
        "dependencies": dependencies,
        "prepared": prepared,
        "accepted": accepted,
        "anchor": anchor,
        "actual_prepared": actual_prepared,
        "continuation": continuation,
        "platform": platform,
        "platform_code_checkpoint": platform_code_checkpoint,
    }


def test_anchor_rebuilds_lineage_and_derives_next_identity_without_manual_inputs(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)

    result = prepare_sealed_entry_preflight(
        fixture["continuation"],
        dependencies=fixture["dependencies"],
    )

    assert result.identities.identity_sequence == 11
    assert result.identities.outer_run_id == "p2_ac_20260825_011"
    assert result.identities.future_actual_id == "actual_11"
    assert result.actual_authorized is False
    assert result.model_generation_calls == 0
    assert result.ProductExecution_runs == 0
    assert result.Builds == 0
    assert result.Runtime_runs == 0
    assert result.Apply_runs == 0
    assert result.execution_root_created is False
    root = Path(fixture["continuation"].packet_root)
    assert {item.name for item in root.iterdir()} == {
        "packet.json",
        "sealed_entry_runner.py",
        "PREFLIGHT.json",
        "RUN.md",
        "FRESH_PREFLIGHT_PROMPT.md",
    }
    packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
    assert packet["packet_version"] == "p2_thin_entry_admission_packet_v6"
    assert packet["run_family_continuation"][
        "caller_supplied_identity_sequence"
    ] is False
    assert packet["run_family_continuation"][
        "caller_supplied_full_lineage"
    ] is False
    review = packet["run_family_continuation"]["accepted_receipt_review"]
    assert review["status"] == "ready"
    assert all(review["hashes"]["matches"].values())
    preflight = json.loads(
        (root / "PREFLIGHT.json").read_text(encoding="utf-8")
    )
    assert preflight["run_family_continuation"][
        "accepted_receipt_review"
    ] == review
    stable_facts = packet["run_family_continuation"]["stable_fact_reuse"]
    assert stable_facts["source_snapshot_sha256"] == packet["source_identity"][
        "snapshot_sha256"
    ]
    assert stable_facts["model"]["digest"] == packet["model_identity"]["digest"]
    actual_sources = [
        item
        for item in packet["identity_lineage"]["unused_check_sources"]
        if item["role"] == "actual_packet"
    ]
    assert packet["identity_lineage"]["boundary"] == (
        "anchor_reconstructed_finite_paths"
    )
    assert actual_sources[-1]["path"] == Path(fixture["anchor"]).resolve().as_posix()


def test_continuation_and_explicit_requests_have_equivalent_run_semantics(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    continuation_result = prepare_sealed_entry_preflight(
        fixture["continuation"],
        dependencies=fixture["dependencies"],
    )
    explicit = fixture["explicit"]
    expected = replace(
        explicit,
        packet_root=str(tmp_path / "delivery" / "explicit_preflight13"),
        packet_date="2026-08-29",
        identity_sequence=11,
        selected_configuration=replace(
            explicit.selected_configuration,
            projection_contract_checkpoint=_git(
                fixture["platform"],
                "rev-parse",
                "HEAD",
            ),
        ),
        preflight_lineage_packet_paths=(
            *explicit.preflight_lineage_packet_paths,
            str(fixture["accepted"]["packet"]),
        ),
        predecessor_receipt_path=str(fixture["accepted"]["receipt"]),
        predecessor_receipt_manifest_path=str(
            fixture["accepted"]["receipt_manifest"]
        ),
        actual_lineage_packet_paths=(
            *explicit.actual_lineage_packet_paths,
            str(fixture["anchor"]),
        ),
    )
    explicit_result = prepare_sealed_entry_preflight(
        expected,
        dependencies=fixture["dependencies"],
    )

    assert continuation_result.identities == explicit_result.identities
    continuation_packet = json.loads(
        (Path(fixture["continuation"].packet_root) / "packet.json").read_text(
            encoding="utf-8"
        )
    )
    explicit_packet = json.loads(
        (Path(expected.packet_root) / "packet.json").read_text(encoding="utf-8")
    )
    for field in (
        "identity_allocation",
        "source_identity",
        "model_identity",
        "future_execution_binding",
        "preflight_budget",
        "permissions",
    ):
        assert continuation_packet[field] == explicit_packet[field]
    continuation_lineage = dict(continuation_packet["identity_lineage"])
    explicit_lineage = dict(explicit_packet["identity_lineage"])
    assert continuation_lineage.pop("boundary") == (
        "anchor_reconstructed_finite_paths"
    )
    assert explicit_lineage.pop("boundary") == "explicit_finite_paths_only"
    assert continuation_lineage == explicit_lineage
    continuation_configuration = dict(continuation_packet["selected_configuration"])
    explicit_configuration = dict(explicit_packet["selected_configuration"])
    continuation_configuration.pop("configuration_source")
    explicit_configuration.pop("configuration_source")
    assert continuation_configuration == explicit_configuration


def test_receipt_review_projects_five_hashes_three_gates_and_zero_authority(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)

    review = project_sealed_entry_receipt_review(
        str(fixture["accepted"]["packet"])
    ).to_dict()

    assert set(review["hashes"]) == {
        "packet",
        "PREFLIGHT",
        "payload_manifest",
        "receipt",
        "receipt_manifest",
        "matches",
    }
    assert all(review["hashes"]["matches"].values())
    assert [gate["gate"] for gate in review["gates"]] == [
        "platform",
        "source",
        "model",
    ]
    assert review["first_blocker"] is None
    assert review["attempt_consumed"] is False
    assert review["actual_authorized"] is False
    assert review["counts"] == {
        "generation_calls": 0,
        "model_calls": 0,
        "ProductExecution_runs": 0,
        "Builds": 0,
        "Runtime_runs": 0,
        "Apply_runs": 0,
        "execution_root_created": False,
    }
    assert review["platform_code_checkpoint"] == {
        "status": "legacy_packet_without_platform_code_checkpoint",
        "platform_HEAD": fixture["platform_code_checkpoint"],
        "platform_code_checkpoint": None,
        "verified": False,
    }


def test_receipt_hash_tamper_fails_review_and_continuation_before_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    receipt = Path(fixture["accepted"]["receipt"])
    receipt.write_text(receipt.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(PreflightPreparationError):
        project_sealed_entry_receipt_review(str(fixture["accepted"]["packet"]))
    with pytest.raises(PreflightPreparationError):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )

    assert not Path(fixture["continuation"].packet_root).exists()


def test_multiple_equally_latest_anchors_fail_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(tmp_path)
    second = _seal_actual_fixture(
        tmp_path / "lineage" / "actual10_second_anchor",
        fixture["accepted"],
        outer_run_id=fixture["prepared"].identities.outer_run_id,
        actual_id=fixture["prepared"].identities.future_actual_id,
        accepted_attempt_id=fixture["prepared"].identities.preflight_attempt_id,
        accepted_preflight_id=fixture["prepared"].identities.preflight_id,
    )
    request = replace(
        fixture["continuation"],
        profile=replace(
            fixture["continuation"].profile,
            anchor_actual_packet_paths=(
                str(Path(fixture["anchor"]).resolve()),
                str(second.resolve()),
            ),
        ),
    )

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_LATEST_LINEAGE_AMBIGUOUS",
    ):
        prepare_sealed_entry_preflight(
            request,
            dependencies=fixture["dependencies"],
        )

    assert not Path(request.packet_root).exists()


def test_broken_or_hash_drifted_anchor_lineage_fails_before_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    accepted_packet = json.loads(
        Path(fixture["accepted"]["packet"]).read_text(encoding="utf-8")
    )
    old_actual = next(
        Path(item["path"])
        for item in accepted_packet["identity_lineage"]["unused_check_sources"]
        if item["role"] == "actual_packet"
    )
    old_actual.write_text(
        old_actual.read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_LINEAGE_SOURCE_HASH_DRIFT",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )

    assert not Path(fixture["continuation"].packet_root).exists()


def test_missing_anchor_lineage_file_fails_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(tmp_path)
    accepted_packet = json.loads(
        Path(fixture["accepted"]["packet"]).read_text(encoding="utf-8")
    )
    old_actual = next(
        Path(item["path"])
        for item in accepted_packet["identity_lineage"]["unused_check_sources"]
        if item["role"] == "actual_packet"
    )
    old_actual.unlink()

    with pytest.raises(
        PreflightPreparationError,
        match="LINEAGE_FILE_MISSING",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def test_allowed_post_checkpoint_path_passes_and_records_both_checkpoints(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    allowed = fixture["platform"] / "run-family" / "profile.json"
    allowed.parent.mkdir()
    allowed.write_text("{}\n", encoding="utf-8")
    _git(fixture["platform"], "add", "run-family/profile.json")
    _git(fixture["platform"], "commit", "-m", "allowed run family profile")
    request = replace(
        fixture["continuation"],
        profile=replace(
            fixture["continuation"].profile,
            allowed_post_checkpoint_paths=("run-family/profile.json",),
        ),
    )

    result = prepare_sealed_entry_preflight(
        request,
        dependencies=fixture["dependencies"],
    )

    head = _git(fixture["platform"], "rev-parse", "HEAD")
    checkpoint = result.continuation_audit["platform_code_checkpoint"]
    assert checkpoint["platform_HEAD"] == head
    assert checkpoint["platform_code_checkpoint"] == fixture["platform_code_checkpoint"]
    assert checkpoint["observed_post_checkpoint_paths"] == [
        "run-family/profile.json"
    ]
    root = Path(request.packet_root)
    packet = json.loads((root / "packet.json").read_text(encoding="utf-8"))
    preflight = json.loads((root / "PREFLIGHT.json").read_text(encoding="utf-8"))
    assert packet["platform"]["platform_code_checkpoint"] == checkpoint
    assert packet["selected_configuration"][
        "projection_contract_checkpoint"
    ] == head
    assert preflight["platform_identity_at_seal"][
        "platform_code_checkpoint"
    ] == checkpoint
    assert preflight["run_family_continuation"]["platform_code_checkpoint"] == checkpoint


def test_unauthorized_post_checkpoint_path_fails_before_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    changed = fixture["platform"] / "src" / "unexpected.py"
    changed.parent.mkdir()
    changed.write_text("value = 1\n", encoding="utf-8")
    _git(fixture["platform"], "add", "src/unexpected.py")
    _git(fixture["platform"], "commit", "-m", "unexpected production change")

    with pytest.raises(
        PreflightPreparationError,
        match="PLATFORM_CODE_CHECKPOINT_UNAUTHORIZED_PATH",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )

    assert not Path(fixture["continuation"].packet_root).exists()


def test_reverted_unauthorized_commit_path_still_fails_before_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    transient = fixture["platform"] / "src" / "transient.py"
    transient.parent.mkdir()
    transient.write_text("value = 1\n", encoding="utf-8")
    _git(fixture["platform"], "add", "src/transient.py")
    _git(fixture["platform"], "commit", "-m", "add transient path")
    transient.unlink()
    _git(fixture["platform"], "add", "-u", "src/transient.py")
    _git(fixture["platform"], "commit", "-m", "remove transient path")

    with pytest.raises(
        PreflightPreparationError,
        match="PLATFORM_CODE_CHECKPOINT_UNAUTHORIZED_PATH",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def _orphan_commit(root: Path) -> str:
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    completed = subprocess.run(
        (str(_git_executable()), "-C", str(root), "commit-tree", tree),
        input="orphan\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout.strip()


def test_non_ancestor_platform_code_checkpoint_fails_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(tmp_path)
    request = replace(
        fixture["continuation"],
        profile=replace(
            fixture["continuation"].profile,
            platform_code_checkpoint=_orphan_commit(fixture["platform"]),
        ),
    )

    with pytest.raises(
        PreflightPreparationError,
        match="PLATFORM_CODE_CHECKPOINT_NOT_ANCESTOR",
    ):
        prepare_sealed_entry_preflight(
            request,
            dependencies=fixture["dependencies"],
        )

    assert not Path(request.packet_root).exists()


def test_dirty_hash_drift_fails_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(
        tmp_path,
        dirty_path="README.md",
        dirty_text="dirty-v1\n",
    )
    (fixture["platform"] / "README.md").write_text(
        "dirty-v2\n",
        encoding="utf-8",
    )

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_DIRTY_HASH_DRIFT",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )

    assert not Path(fixture["continuation"].packet_root).exists()


def test_source_identity_drift_fails_before_owner_and_packet_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    source_root = Path(fixture["explicit"].source_root)
    loader = source_root / "AccurateCrosshair" / "Loader.cs"
    loader.write_text("public sealed class Loader { public int V => 2; }\n", encoding="utf-8")
    _git(source_root, "add", "AccurateCrosshair/Loader.cs")
    _git(source_root, "commit", "-m", "drift source identity")

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_SOURCE_FACT_DRIFT",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def test_model_identity_drift_fails_before_owner_and_packet_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    dependencies = replace(
        fixture["dependencies"],
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

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_MODEL_FACT_DRIFT",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=dependencies,
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def test_dirty_status_drift_fails_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(
        tmp_path,
        dirty_path="run-family-note.txt",
    )
    _git(fixture["platform"], "add", "run-family-note.txt")
    _git(fixture["platform"], "commit", "-m", "track run family note")
    (fixture["platform"] / "run-family-note.txt").write_text(
        "dirty-v2\n",
        encoding="utf-8",
    )
    request = replace(
        fixture["continuation"],
        profile=replace(
            fixture["continuation"].profile,
            allowed_post_checkpoint_paths=("run-family-note.txt",),
        ),
    )

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_DIRTY_STATUS_DRIFT",
    ):
        prepare_sealed_entry_preflight(
            request,
            dependencies=fixture["dependencies"],
        )

    assert not Path(request.packet_root).exists()


def test_continuation_packet_remains_compatible_with_stable_actual_compiler(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    result = prepare_sealed_entry_preflight(
        fixture["continuation"],
        dependencies=fixture["dependencies"],
    )
    accepted = _write_ready_receipt(Path(fixture["continuation"].packet_root))
    dependencies = fixture["dependencies"]
    actual = prepare_sealed_actual_run(
        ActualRunPreparationRequestV1(
            contract_version="1",
            accepted_preflight_packet_path=Path(accepted["packet"]).resolve().as_posix(),
            accepted_preflight_packet_sha256=_file_sha256(Path(accepted["packet"])),
            accepted_preflight_manifest_sha256=_file_sha256(
                Path(accepted["preflight"])
            ),
            accepted_payload_manifest_sha256=result.payload_manifest_sha256,
            accepted_receipt_path=Path(accepted["receipt"]).resolve().as_posix(),
            accepted_receipt_sha256=_file_sha256(Path(accepted["receipt"])),
            accepted_receipt_manifest_path=Path(
                accepted["receipt_manifest"]
            ).resolve().as_posix(),
            accepted_receipt_manifest_sha256=_file_sha256(
                Path(accepted["receipt_manifest"])
            ),
            product_execution=ActualProductExecutionSelectionV1(
                contract_version="1",
                workspace_base=str((tmp_path / "workspace").resolve()),
                settings_path=str((tmp_path / "settings.json").resolve()),
                requested_completion_scope="compile_only",
            ),
        ),
        dependencies=ActualExecutionDependenciesV1(
            model_identity_reader=dependencies.model_identity_reader,
            server_version_reader=dependencies.server_version_reader,
            context_validator=dependencies.context_validator,
        ),
    )

    assert actual.status == "sealed"
    assert actual.semantic_compatibility_boundary == (
        "repository_v6_fixture_identity_and_receipt_lineage_only"
    )
    assert actual.actual_authorized is False
    assert actual.model_generation_calls == 0
    assert actual.ProductExecution_runs == 0
    assert actual.Builds == 0
    assert actual.Apply_runs == 0
    review = project_sealed_entry_receipt_review(
        str(accepted["packet"])
    ).to_dict()
    assert review["platform_code_checkpoint"]["status"] == "verified"
    assert review["platform_code_checkpoint"]["platform_HEAD"] == _git(
        fixture["platform"],
        "rev-parse",
        "HEAD",
    )
    assert review["platform_code_checkpoint"][
        "platform_code_checkpoint"
    ] == fixture["platform_code_checkpoint"]


def test_stable_actual_anchor_with_interrupted_journal_is_consumed_and_advanced(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path, stable_anchor=True)
    journal = Path(fixture["anchor"]).parent / "actual_journal.json"
    _write_json(
        journal,
        {
            "journal_version": "actual_run_journal_reservation_v1",
            "outer_run_id": fixture["prepared"].identities.outer_run_id,
            "actual_attempt_id": fixture["prepared"].identities.future_actual_id,
        },
    )
    before = journal.read_bytes()

    result = prepare_sealed_entry_preflight(
        fixture["continuation"],
        dependencies=fixture["dependencies"],
    )

    assert result.identities.identity_sequence == 11
    assert result.identities.future_actual_id == "actual_11"
    assert journal.read_bytes() == before


def test_stable_actual_internal_state_contradiction_fails_before_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path, stable_anchor=True)
    anchor_path = Path(fixture["anchor"])
    packet = json.loads(anchor_path.read_text(encoding="utf-8"))
    packet["actual_run_spec"]["model"]["digest"] = "c" * 64
    _write_json(anchor_path, packet)
    seal_path = anchor_path.parent / "ACTUAL_SEAL.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    material = {"packet.json": _file_sha256(anchor_path)}
    seal["files"] = material
    seal["manifest_sha256"] = _canonical_sha256(material)
    seal["spec_sha256"] = _canonical_sha256(packet["actual_run_spec"])
    _write_json(seal_path, seal)

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_STABLE_ACTUAL_SPEC_CONTRADICTORY",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def _replace_receipt_result(
    fixture: dict[str, Any],
    result: dict[str, Any],
) -> None:
    receipt_path = Path(fixture["accepted"]["receipt"])
    manifest_path = Path(fixture["accepted"]["receipt_manifest"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["result"] = result
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["receipt_sha256"] = _file_sha256(receipt_path)
    _write_json(manifest_path, manifest)
    anchor_path = Path(fixture["anchor"])
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    accepted = anchor["accepted_entry_receipt"]
    accepted["receipt_sha256"] = _file_sha256(receipt_path)
    accepted["receipt_manifest_sha256"] = _file_sha256(manifest_path)
    _write_json(anchor_path, anchor)


def test_blocked_receipt_projects_first_blocker_but_cannot_continue(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    receipt = json.loads(
        Path(fixture["accepted"]["receipt"]).read_text(encoding="utf-8")
    )
    result = receipt["result"]
    blocker = {
        "stage": "model_admission",
        "code": "MODEL_NOT_READY",
        "message": "The model gate is not ready.",
        "diagnostics": {"reason": "fixture"},
    }
    result.update(
        {
            "status": "blocked",
            "first_failure_stage": blocker["stage"],
            "first_failure_code": blocker["code"],
            "first_failure_message": blocker["message"],
            "blockers": [blocker],
            "gate_receipts": result["gate_receipts"][:2],
        }
    )
    _replace_receipt_result(fixture, result)

    review = project_sealed_entry_receipt_review(
        str(fixture["accepted"]["packet"])
    ).to_dict()
    assert review["status"] == "blocked"
    assert review["first_blocker"] == blocker
    assert [gate["decision"] for gate in review["gates"]] == [
        "passed",
        "passed",
        "not_reached",
    ]
    with pytest.raises(
        PreflightPreparationError,
        match="LINEAGE_RECEIPT_RESULT_INVALID_FOR_USE",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def test_receipt_gate_state_contradiction_fails_review_and_continuation(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    receipt = json.loads(
        Path(fixture["accepted"]["receipt"]).read_text(encoding="utf-8")
    )
    result = receipt["result"]
    model_gate = next(
        gate for gate in result["gate_receipts"] if gate["gate"] == "model"
    )
    model_gate["facts"]["digest"] = "d" * 64
    _replace_receipt_result(fixture, result)

    with pytest.raises(
        PreflightPreparationError,
        match="RECEIPT_REVIEW_MODEL_GATE_CONTRADICTORY",
    ):
        project_sealed_entry_receipt_review(str(fixture["accepted"]["packet"]))
    with pytest.raises(
        PreflightPreparationError,
        match="RECEIPT_REVIEW_MODEL_GATE_CONTRADICTORY",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def _rebind_modified_preflight_and_anchor(fixture: dict[str, Any]) -> None:
    packet_root = Path(fixture["accepted"]["packet"]).parent
    packet_path = packet_root / "packet.json"
    preflight_path = packet_root / "PREFLIGHT.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    packet_sha256 = _file_sha256(packet_path)
    preflight["files"]["packet.json"] = {
        "sha256": packet_sha256,
        "bytes": packet_path.stat().st_size,
    }
    payload_files = {
        "packet.json": packet_sha256,
        "sealed_entry_runner.py": _file_sha256(
            packet_root / "sealed_entry_runner.py"
        ),
    }
    payload_manifest = _canonical_sha256(payload_files)
    preflight["payload_manifest_sha256"] = payload_manifest
    delivery_files = {
        name: _file_sha256(packet_root / name)
        for name in (
            "packet.json",
            "sealed_entry_runner.py",
            "RUN.md",
            "FRESH_PREFLIGHT_PROMPT.md",
        )
    }
    preflight["delivery_manifest_sha256"] = _canonical_sha256(delivery_files)
    _write_json(preflight_path, preflight)

    receipt_path = Path(fixture["accepted"]["receipt"])
    manifest_path = Path(fixture["accepted"]["receipt_manifest"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["request_identity"]["payload_manifest_sha256"] = payload_manifest
    receipt["result"]["payload_manifest_sha256"] = payload_manifest
    _write_json(receipt_path, receipt)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["payload_manifest_sha256"] = payload_manifest
    manifest["receipt_sha256"] = _file_sha256(receipt_path)
    _write_json(manifest_path, manifest)
    anchor_path = Path(fixture["anchor"])
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    accepted = anchor["accepted_entry_receipt"]
    accepted["payload_manifest_sha256"] = payload_manifest
    accepted["receipt_sha256"] = _file_sha256(receipt_path)
    accepted["receipt_manifest_sha256"] = _file_sha256(manifest_path)
    _write_json(anchor_path, anchor)


def test_duplicate_used_actual_identity_in_anchor_lineage_fails_before_write(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)
    packet_path = Path(fixture["accepted"]["packet"])
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    original_source = next(
        item
        for item in packet["identity_lineage"]["unused_check_sources"]
        if item["role"] == "actual_packet"
    )
    duplicate_root = tmp_path / "lineage" / "duplicate_used_actual"
    duplicate_root.mkdir()
    duplicate = duplicate_root / "packet.json"
    duplicate.write_bytes(Path(original_source["path"]).read_bytes())
    packet["identity_lineage"]["unused_check_sources"].append(
        {
            "role": "actual_packet",
            "path": duplicate.resolve().as_posix(),
            "sha256": _file_sha256(duplicate),
        }
    )
    _write_json(packet_path, packet)
    _rebind_modified_preflight_and_anchor(fixture)

    with pytest.raises(
        PreflightPreparationError,
        match="LINEAGE_ACTUAL_IDENTITY_DUPLICATE",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def test_missing_platform_code_checkpoint_object_fails_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(tmp_path)
    request = replace(
        fixture["continuation"],
        profile=replace(
            fixture["continuation"].profile,
            platform_code_checkpoint="f" * 40,
        ),
    )

    with pytest.raises(
        PreflightPreparationError,
        match="PLATFORM_CODE_CHECKPOINT_OBJECT_INVALID",
    ):
        prepare_sealed_entry_preflight(
            request,
            dependencies=fixture["dependencies"],
        )
    assert not Path(request.packet_root).exists()


def test_abbreviated_platform_code_checkpoint_is_rejected_by_typed_profile(
    tmp_path: Path,
) -> None:
    fixture = _continuation_fixture(tmp_path)

    with pytest.raises(ValueError, match="platform_code_checkpoint"):
        replace(
            fixture["continuation"].profile,
            platform_code_checkpoint=fixture["platform_code_checkpoint"][:12],
        )

    assert not Path(fixture["continuation"].packet_root).exists()


def test_dirty_path_set_drift_fails_before_write(tmp_path: Path) -> None:
    fixture = _continuation_fixture(tmp_path)
    (fixture["platform"] / "unexpected.tmp").write_text(
        "unexpected\n",
        encoding="utf-8",
    )

    with pytest.raises(
        PreflightPreparationError,
        match="RUN_FAMILY_DIRTY_PATH_DRIFT",
    ):
        prepare_sealed_entry_preflight(
            fixture["continuation"],
            dependencies=fixture["dependencies"],
        )
    assert not Path(fixture["continuation"].packet_root).exists()


def test_cli_continuation_accepts_only_profile_and_new_packet_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile_path = tmp_path / "continuation.json"
    _write_json(
        profile_path,
        {
            "contract_version": "1",
            "packet_date": "2026-08-29",
            "anchor_actual_packet_paths": [
                (tmp_path / "anchor" / "packet.json").resolve().as_posix()
            ],
            "platform_code_checkpoint": "a" * 40,
            "allowed_post_checkpoint_paths": [],
        },
    )
    captured: dict[str, Any] = {}

    class Result:
        def to_dict(self) -> dict[str, Any]:
            return {"status": "sealed", "actual_authorized": False}

    def prepare(request: RunFamilyContinuationRequestV1) -> Result:
        captured["request"] = request
        return Result()

    monkeypatch.setattr("src.mod_agent.cli.prepare_sealed_entry_preflight", prepare)
    exit_code = cli_main(
        [
            "prepare-sealed-entry-preflight",
            "--packet-root",
            str(tmp_path / "new-packet"),
            "--run-family-continuation-profile",
            str(profile_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "sealed",
        "actual_authorized": False,
    }
    request = captured["request"]
    assert isinstance(request, RunFamilyContinuationRequestV1)
    assert request.packet_root == str(tmp_path / "new-packet")
    assert request.profile.anchor_actual_packet_paths == (
        (tmp_path / "anchor" / "packet.json").resolve().as_posix(),
    )


def test_cli_continuation_rejects_manual_sequence_before_owner_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    profile_path = tmp_path / "continuation.json"
    _write_json(
        profile_path,
        {
            "contract_version": "1",
            "packet_date": "2026-08-29",
            "anchor_actual_packet_paths": [
                (tmp_path / "anchor" / "packet.json").resolve().as_posix()
            ],
            "platform_code_checkpoint": "a" * 40,
            "allowed_post_checkpoint_paths": [],
        },
    )
    called = False

    def prepare(_request: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("owner must not be called")

    monkeypatch.setattr("src.mod_agent.cli.prepare_sealed_entry_preflight", prepare)
    exit_code = cli_main(
        [
            "prepare-sealed-entry-preflight",
            "--packet-root",
            str(tmp_path / "new-packet"),
            "--run-family-continuation-profile",
            str(profile_path),
            "--identity-sequence",
            "15",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert called is False
    assert payload["code"] == "PREPARATION_REQUEST_INVALID"
    assert "identity_sequence" in payload["reason"]
    assert payload["sealed_files_written"] == 0
    assert payload["actual_authorized"] is False
