from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evaluation.hidden_golden import (
    CommittedCalibrationActual,
    HiddenGoldenCalibrationError,
    commit_manifest_bound_calibration_actual,
    evaluate_committed_hidden_golden,
    load_hidden_golden_actual_input,
)
from src.mod_agent.evidence.models import (
    DETERMINISTIC_EVIDENCE_AUTHORITY,
    EvidenceItem,
    EvidencePack,
    EvidenceRequest,
)
from src.mod_agent.evidence.readiness import EvidenceReadinessClassifier


def _canonical_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest().upper()


def _feature_payload(
    feature_id: str,
    *,
    request: str = "Find an observed current method.",
) -> dict[str, object]:
    return {
        "node_name": "draft_feature_spec",
        "stage": "feature_spec",
        "message": "Hidden-Golden isolation fixture.",
        "feature_id": feature_id,
        "user_request": request,
        "target_behavior": request,
        "non_goals": [],
        "target_mod": None,
        "risk_level": "medium",
        "acceptance_criteria": [],
        "evidence_requirements": [],
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _semantic_pack(query: str):
    item = EvidenceItem(
        evidence_id="ev-observed-method",
        source_type="decompiled_api",
        source_path="interop/Observed.dll",
        symbol="Observed.Type.Move",
        span=None,
        retrieval_method="current_interop_metadata_il_read",
        score=1.0,
        claim_supported="Bound physical method identity.",
        excerpt="{}",
        source_hash="A" * 64,
        file_hash="A" * 64,
        usage="hook_evidence",
        declaring_type="Observed.Type",
        method_name="Move",
        module_mvid="00000000-0000-0000-0000-000000000001",
        metadata_token="0x06000001",
        signature_blob="200001",
        authority=DETERMINISTIC_EVIDENCE_AUTHORITY,
        source_authority="authoritative",
    )
    return EvidenceReadinessClassifier().classify(
        request=EvidenceRequest(
            query=query,
            hook_requirement={
                "required": True,
                "reason": "natural_language_hook_discovery",
                "request_type": "hook_discovery",
                "required_lanes": ["metadata_il"],
                "evidence_requirements": [
                    {
                        "requirement_id": "req-observed-method",
                        "description": "Bind an observed current method.",
                        "relationship": "support",
                        "planning_blocking": True,
                        "match": {"symbols": ["Observed.Type.Move"]},
                    }
                ],
                "limitations": ["Final Runtime correctness remains unverified."],
            },
        ),
        items=[item],
        lane_coverage=(
            {
                "lane": "metadata_il",
                "status": "searched_with_results",
                "hit_count": 1,
                "scope": {"source_ids": ["current-interop"]},
                "failure": None,
            },
        ),
    )


def _annotation() -> dict[str, object]:
    identity = {
        "assembly_sha256": "A" * 64,
        "module_mvid": "00000000-0000-0000-0000-000000000001",
        "declaring_type": "Observed.Type",
        "method_name": "Move",
        "metadata_token": "0x06000001",
        "signature_blob": "200001",
        "acceptance_scope": "Observation direction only.",
    }
    judgment = {
        "required_evidence": ["A current exact method identity."],
        "forbidden_evidence": ["A method name without physical identity."],
        "acceptable_hook_full_identities": [identity],
        "forbidden_hook_full_identities": [],
        "required_missing_evidence": [],
        "expected_sufficiency": "sufficient",
        "expected_control_action": "continue",
    }
    digest = _canonical_sha256(judgment)
    return {
        "case_identity": "synthetic_hidden_golden_case",
        "technical_review_authority": (
            "independently_model_reviewed_technical_calibration_annotation"
        ),
        "current_rag_actual_output_accessed": False,
        "judgment_payload": judgment,
        "judgment_hash_protocol": (
            "sha256_of_canonical_json_over_judgment_payload_only"
        ),
        "proposed_judgment_hash": digest,
        "frozen_judgment_hash": digest,
    }


def _actual_input_root(tmp_path: Path, *, request: str) -> Path:
    root = tmp_path / "synthetic"
    root.mkdir()
    request_bytes = (request + "\n").encode("utf-8")
    (root / "request.txt").write_bytes(request_bytes.replace(b"\n", b"\r\n"))
    source_root = root / "current" / "source"
    source_root.mkdir(parents=True)
    (source_root / "Observed.cs").write_text(
        "internal sealed class Observed {}\n", encoding="utf-8"
    )
    from src.mod_agent.evaluation.arm_a import RunManifestCollector

    corpus_snapshot = RunManifestCollector(root).canonical_corpus_snapshot(
        ["current/source"]
    )
    manifest = {
        "case_identity": "synthetic_hidden_golden_case",
        "request": {
            "ref": "fixtures/synthetic/request.txt",
            "sha256": hashlib.sha256(request_bytes).hexdigest().upper(),
        },
        "actual_retrieval_scope": {
            "mode": "allowlist_only",
            "search_root_allowlist": ["current/source"],
            "excluded_source_classes": [
                "technical_annotation",
                "prior_agent_or_rag_outputs",
            ],
        },
        "canonical_corpus_snapshot": {
            "search_root_allowlist": ["current/source"],
            "corpus_snapshot_sha256": corpus_snapshot.corpus_snapshot_sha256,
        },
    }
    (root / "corpus_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def _commit_pack(tmp_path: Path, *, query: str):
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature-hidden-golden"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_feature_payload(feature_id),
    )
    actual_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=_semantic_pack(query).to_artifact_payload(),
        upstream_refs=[feature_ref],
    )
    return store, actual_ref


def _feature_store(tmp_path: Path, *, request: str):
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature-hidden-golden"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_feature_payload(feature_id, request=request),
    )
    return store, feature_ref


def test_manifest_bound_actual_commits_reads_and_strictly_rehydrates(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    executor_calls: list[dict[str, object]] = []

    def executor(*, r8_root: Path, request: str) -> EvidencePack:
        executor_calls.append({"r8_root": r8_root, "request": request})
        return _semantic_pack(request)

    committed = commit_manifest_bound_calibration_actual(
        case_root=root,
        corpus_root=root,
        store=store,
        feature_spec_ref=feature_ref,
        run_id="run-synthetic",
        request_id="request-synthetic",
        executor=executor,
    )

    assert isinstance(committed, CommittedCalibrationActual)
    assert executor_calls == [{"r8_root": root.resolve(), "request": request}]
    assert committed.store is store
    assert committed.actual_ref.artifact_type == "evidence_pack"
    assert committed.actual_input.request_text == request
    assert committed.actual_input.observed_corpus_snapshot_sha256 == (
        committed.actual_input.declared_corpus_snapshot_sha256
    )
    envelope = store.read(committed.actual_ref)
    payload = envelope["data"]
    assert EvidencePack.requires_strict_semantic_rehydrate(payload) is True
    assert EvidencePack.from_artifact_payload(payload) == committed.evidence_pack
    assert committed.evidence_pack.query == request
    assert payload["provenance_validation"]["run_id"] == "run-synthetic"
    assert payload["provenance_validation"]["request_id"] == "request-synthetic"
    assert payload["provenance_validation"]["manifest_bound_actual"] == {
        "case_identity": "synthetic_hidden_golden_case",
        "request_sha256": committed.actual_input.request_sha256,
        "declared_corpus_snapshot_sha256": (
            committed.actual_input.declared_corpus_snapshot_sha256
        ),
        "observed_corpus_snapshot_sha256": (
            committed.actual_input.observed_corpus_snapshot_sha256
        ),
        "source_allowlist": list(committed.actual_input.source_allowlist),
    }
    assert "annotation.json" not in json.dumps(payload, ensure_ascii=False)


def test_manifest_bound_actual_snapshot_mismatch_stops_before_executor_and_write(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    before_refs = store.list_feature_artifacts(feature_ref.feature_id)
    (root / "current" / "source" / "Observed.cs").write_text(
        "internal sealed class Changed {}\n",
        encoding="utf-8",
    )
    executor_called = False

    def executor(**_: object) -> EvidencePack:
        nonlocal executor_called
        executor_called = True
        return _semantic_pack(request)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_CORPUS_SNAPSHOT_MISMATCH",
    ):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            executor=executor,
        )

    assert executor_called is False
    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


def test_manifest_bound_actual_requires_expected_source_exclusions(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    manifest_path = root / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["actual_retrieval_scope"]["excluded_source_classes"] = [
        "prior_agent_or_rag_outputs"
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    store, feature_ref = _feature_store(tmp_path, request=request)
    before_refs = store.list_feature_artifacts(feature_ref.feature_id)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_EXPECTED_EXCLUSION_MISSING",
    ):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            executor=lambda **_: _semantic_pack(request),
        )

    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


def test_manifest_bound_actual_rejects_feature_request_drift_before_executor(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request="Different request.")
    before_refs = store.list_feature_artifacts(feature_ref.feature_id)
    executor_called = False

    def executor(**_: object) -> EvidencePack:
        nonlocal executor_called
        executor_called = True
        return _semantic_pack(request)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_FEATURE_REQUEST_MISMATCH",
    ):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            executor=executor,
        )

    assert executor_called is False
    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


def test_manifest_bound_actual_rejects_non_semantic_pack_before_write(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    before_refs = store.list_feature_artifacts(feature_ref.feature_id)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_ACTUAL_NOT_SEMANTIC",
    ):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            executor=lambda **_: EvidencePack.empty(
                query=request,
                reason="synthetic non-semantic result",
            ),
        )

    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


def test_manifest_bound_actual_rejects_tampered_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    original_read = store.read

    def tampered_read(ref):
        envelope = original_read(ref)
        if ref.artifact_type == "evidence_pack":
            envelope = deepcopy(envelope)
            envelope["data"]["query"] = "tampered request"
        return envelope

    monkeypatch.setattr(store, "read", tampered_read)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_COMMITTED_ACTUAL_REQUEST_MISMATCH",
    ):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            executor=lambda **_: _semantic_pack(request),
        )


def test_manifest_bound_actual_signature_has_no_expected_side_inputs() -> None:
    parameters = set(inspect.signature(commit_manifest_bound_calibration_actual).parameters)
    assert parameters.isdisjoint(
        {
            "annotation",
            "annotation_path",
            "golden",
            "expected",
            "expected_evidence",
            "prior_output",
            "prior_rag_output",
        }
    )
    source = inspect.getsource(commit_manifest_bound_calibration_actual)
    assert "target_mod" not in source
    assert "BetterHitFeedback" not in source
    assert "WallCrawler" not in source


def test_hidden_golden_reads_expected_only_after_committed_actual_binding(
    tmp_path: Path,
) -> None:
    root = _actual_input_root(tmp_path, request="Find an observed current method.")
    actual_input = load_hidden_golden_actual_input(root, corpus_root=root)
    annotation_path = root / "annotation.json"
    annotation_path.write_text("not-json", encoding="utf-8")
    store, actual_ref = _commit_pack(tmp_path, query="different request")

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_ACTUAL_REQUEST_MISMATCH",
    ):
        evaluate_committed_hidden_golden(
            store=store,
            actual_ref=actual_ref,
            actual_input=actual_input,
            annotation_path=annotation_path,
        )


def test_hidden_golden_minimal_comparison_uses_committed_strict_actual(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    actual_input = load_hidden_golden_actual_input(root, corpus_root=root)
    annotation_path = root / "annotation.json"
    annotation_path.write_text(json.dumps(_annotation()), encoding="utf-8")
    store, actual_ref = _commit_pack(tmp_path, query=request)

    report = evaluate_committed_hidden_golden(
        store=store,
        actual_ref=actual_ref,
        actual_input=actual_input,
        annotation_path=annotation_path,
    )

    assert report["comparison"] == {
        "sufficiency_matches": True,
        "control_action_matches": True,
        "acceptable_hook_identity_set_matches": True,
        "forbidden_hook_identity_hits": [],
    }
    assert report["actual"]["artifact_hash"] == actual_ref.artifact_hash
    assert report["blind_or_held_out_claim"] is False
    assert report["promotion_claim"] is False
    assert "data_readiness_verdict" in report["does_not_grant"]
    assert report["unscored_expected_fields"] == [
        "required_evidence",
        "forbidden_evidence",
        "required_missing_evidence",
    ]


def test_hidden_golden_rejects_annotation_hash_tampering(tmp_path: Path) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    actual_input = load_hidden_golden_actual_input(root, corpus_root=root)
    annotation = deepcopy(_annotation())
    annotation["judgment_payload"]["expected_control_action"] = "block"
    annotation_path = root / "annotation.json"
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    store, actual_ref = _commit_pack(tmp_path, query=request)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_PROPOSED_HASH_MISMATCH",
    ):
        evaluate_committed_hidden_golden(
            store=store,
            actual_ref=actual_ref,
            actual_input=actual_input,
            annotation_path=annotation_path,
        )


def test_hidden_golden_rejects_corpus_snapshot_drift(tmp_path: Path) -> None:
    root = _actual_input_root(tmp_path, request="Find an observed current method.")
    manifest_path = root / "corpus_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_corpus_snapshot"]["corpus_snapshot_sha256"] = (
        "sha256:" + "0" * 64
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_CORPUS_SNAPSHOT_MISMATCH",
    ):
        load_hidden_golden_actual_input(root, corpus_root=root)


@pytest.mark.parametrize("case_name", ["better_hit_feedback", "wall_crawler"])
def test_checked_in_calibration_actual_input_is_manifest_bound(case_name: str) -> None:
    root = (
        Path(__file__).parents[2]
        / "docs"
        / "calibration"
        / "two_slice_data_readiness"
        / case_name
    )

    actual_input = load_hidden_golden_actual_input(root)

    assert actual_input.request_text
    assert actual_input.request_sha256
    assert actual_input.source_allowlist == (
        "Assets/Scripts/Modules-ASM",
        "Datablocks",
    )
    assert "technical_annotation" in actual_input.excluded_source_classes
