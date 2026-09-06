"""Worker configuration bytes join the existing attempt identity without execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from src.mod_agent.fresh_planning_continuation import (
    PatchContinuationAttemptJournal,
    PatchContinuationError,
    _patch_attempt_identity,
    preflight_patch_continuation,
    run_fresh_patch_continuation,
)
from src.mod_agent.local_entry import make_exact_no_write_dry_run_factory
from tests.unit.test_fresh_planning_continuation import (
    _inputs,
    _local_patch_adapter,
    _patch_request,
)


@pytest.fixture
def selected(tmp_path):
    inputs = _inputs(tmp_path)
    return inputs, replace(_patch_request(inputs), attempt_id="worker-configuration-identity-test")


def _configuration_ref(path: Path, content: bytes = b'{"worker":"not_imported.worker:factory"}') -> dict[str, str]:
    path.write_bytes(content)
    return {"path": str(path), "sha256": hashlib.sha256(content).hexdigest()}


def _canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _with_configuration(request, ref):
    return replace(request, worker_configuration_ref=ref, worker_profile_sha256="d" * 64)


@pytest.mark.parametrize("budget", [1, 5])
def test_unconfigured_request_keeps_the_preexisting_canonical_identity(selected, budget):
    _, request = selected
    # Explicitly freeze the old input shape rather than derive it from new fields.
    old_request = {
        "contract_version": request.contract_version,
        "artifact_store_root": request.artifact_store_root,
        "workspace_root": request.workspace_root,
        "feature_spec_ref": asdict(request.feature_spec_ref),
        "evidence_pack_ref": asdict(request.evidence_pack_ref),
        "implementation_plan_ref": asdict(request.implementation_plan_ref),
        "repair_parent_proposal_ref": None,
        "repair_parent_review_ref": None,
        "repair_failure_report_ref": None,
        "repair_parent_response_ref": None,
        "repair_parent_attempt_ref": None,
        "attempt_id": request.attempt_id,
    }
    assert request.worker_configuration_ref is None
    assert request.worker_profile_sha256 is None
    assert _patch_attempt_identity(request, budget) == _canonical({"request": old_request, "max_model_calls": budget})


def test_selected_configuration_and_existing_outer_budget_both_bind_identity(selected, tmp_path):
    _, request = selected
    first = _with_configuration(request, _configuration_ref(tmp_path / "worker-a.json"))
    second = _with_configuration(request, _configuration_ref(tmp_path / "worker-b.json"))
    legacy_worker_request = asdict(first)
    assert legacy_worker_request.pop("repair_source_attempt_ref") is None
    assert legacy_worker_request.pop("repair_verification_ref") is None
    assert legacy_worker_request.pop("qualified_model_routing_ref") is None
    assert _patch_attempt_identity(first, 5) == _canonical({"request": legacy_worker_request, "max_model_calls": 5})
    assert len({_patch_attempt_identity(request, 5), _patch_attempt_identity(first, 5),
                _patch_attempt_identity(second, 5), _patch_attempt_identity(first, 4)}) == 4


@pytest.mark.parametrize("ref", [
    {}, {"path": "worker.json"}, {"sha256": "a" * 64},
    {"path": "worker.json", "sha256": "a" * 64, "extra": True},
    {"path": "  ", "sha256": "a" * 64},
    {"path": 1, "sha256": "a" * 64},
    {"path": "worker.json", "sha256": "A" * 64},
    {"path": "worker.json", "sha256": "a" * 63},
    {"path": "worker.json", "sha256": "g" * 64},
    [("path", "worker.json"), ("sha256", "a" * 64)],
])
def test_invalid_configuration_reference_is_rejected_at_input(selected, ref):
    _, request = selected
    with pytest.raises(PatchContinuationError, match="PATCH_WORKER_CONFIGURATION_IDENTITY_INVALID"):
        _with_configuration(request, ref)


def test_preflight_reads_exact_bytes_without_importing_configuration_content(selected, tmp_path):
    _, request = selected
    supplied = _configuration_ref(tmp_path / "worker.json")
    request = _with_configuration(request, supplied)
    supplied["sha256"] = "0" * 64
    admitted = preflight_patch_continuation(request)
    assert admitted.implementation_plan
    assert request.worker_configuration_ref["sha256"] != supplied["sha256"]


@pytest.mark.parametrize("mutation", ["drift", "missing"])
def test_configuration_file_failure_stops_before_any_factory_call(selected, tmp_path, mutation):
    inputs, request = selected
    path = tmp_path / "worker.json"
    request = _with_configuration(request, _configuration_ref(path))
    if mutation == "drift":
        path.write_bytes(b'{"changed":true}')
    else:
        path.unlink()
    with pytest.raises(PatchContinuationError, match="PATCH_WORKER_CONFIGURATION_IDENTITY_INVALID"):
        preflight_patch_continuation(request)
    calls = []
    result = run_fresh_patch_continuation(request, patch_change_factory=lambda *_: calls.append("patch"),
        dry_run_factory=lambda *_: calls.append("dry_run"), max_model_calls=5)
    assert result.first_failure["code"] == "PATCH_WORKER_CONFIGURATION_IDENTITY_INVALID"
    assert not calls
    assert not list(inputs.store.root.glob("cr/*.json"))


def test_attempt_journal_preserves_selected_configuration_ref(selected, tmp_path):
    inputs, request = selected
    request = _with_configuration(request, _configuration_ref(tmp_path / "worker.json"))
    admitted = preflight_patch_continuation(request)
    journal = PatchContinuationAttemptJournal(artifact_root=inputs.store.root,
        run_id="worker-identity-journal", request_id="worker-identity-request", request=request,
        admitted=admitted, max_model_calls=5)
    recorded = json.loads(journal.path.read_text(encoding="utf-8"))
    assert recorded["worker_configuration_ref"] == dict(request.worker_configuration_ref)
    assert recorded["worker_profile_sha256"] == request.worker_profile_sha256
    assert recorded["attempt_identity_sha256"] == _patch_attempt_identity(request, 5)


@pytest.mark.parametrize("mutation", ["new_ref", "profile", "same_ref_drift", "same_ref_missing"])
def test_terminal_attempt_cannot_reuse_result_after_configuration_change(selected, tmp_path, mutation):
    inputs, request = selected
    path = tmp_path / "worker.json"
    request = _with_configuration(request, _configuration_ref(path))
    adapter, client = _local_patch_adapter(inputs)
    result = run_fresh_patch_continuation(request, patch_change_factory=adapter,
        dry_run_factory=make_exact_no_write_dry_run_factory(inputs.workspace))
    assert result.status == "terminal" and client.calls == 1
    receipt_path = Path(result.attempt_receipt["path"])
    before = receipt_path.read_bytes()
    if mutation == "new_ref":
        request = replace(request, worker_configuration_ref=_configuration_ref(tmp_path / "other-worker.json"))
    elif mutation == "profile":
        request = replace(request, worker_profile_sha256="e" * 64)
    elif mutation == "same_ref_drift":
        path.write_bytes(b'{"changed":true}')
    else:
        path.unlink()
    calls = []
    stopped = run_fresh_patch_continuation(request,
        patch_change_factory=lambda *_: calls.append("patch"), dry_run_factory=lambda *_: calls.append("dry_run"))
    assert stopped.first_failure["code"] == ("PATCH_CONTINUATION_ATTEMPT_IDENTITY_CONFLICT" if mutation in {"new_ref", "profile"}
        else "PATCH_WORKER_CONFIGURATION_IDENTITY_INVALID")
    assert not calls and client.calls == 1
    assert receipt_path.read_bytes() == before


@pytest.mark.parametrize("profile", [None, "", "A" * 64, "d" * 63, True])
def test_configuration_requires_valid_matching_profile_identity(selected, tmp_path, profile):
    _, request = selected
    ref = _configuration_ref(tmp_path / "worker.json")
    with pytest.raises(PatchContinuationError, match="PATCH_WORKER_CONFIGURATION_IDENTITY_INVALID"):
        replace(request, worker_configuration_ref=ref, worker_profile_sha256=profile)


def test_profile_identity_alone_cannot_change_an_unconfigured_attempt(selected):
    _, request = selected
    with pytest.raises(PatchContinuationError, match="PATCH_WORKER_CONFIGURATION_IDENTITY_INVALID"):
        replace(request, worker_profile_sha256="d" * 64)
