from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import src.mod_agent.evaluation.hidden_golden as hidden_golden_module
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.evaluation.hidden_golden import evaluate_committed_hidden_golden
from src.mod_agent.evidence.calibration import (
    CommittedCalibrationActual,
    HiddenGoldenActualInput,
    HiddenGoldenCalibrationError,
    commit_manifest_bound_calibration_actual,
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
    contamination_sentinel: str | None = None,
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
        "acceptance_criteria": (
            [contamination_sentinel] if contamination_sentinel else []
        ),
        "evidence_requirements": (
            [contamination_sentinel] if contamination_sentinel else []
        ),
        "runtime_verification_plan": [],
        "blocked": False,
        "blockers": [],
    }


def _semantic_pack(
    query: str,
    *,
    run_id: str = "run-synthetic",
    request_id: str = "request-synthetic",
    model_identity: dict[str, object] | None = None,
) -> EvidencePack:
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
    pack = EvidenceReadinessClassifier().classify(
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
    return replace(
        pack,
        model_identity=(
            model_identity
            if model_identity is not None
            else {
                "execution_kind": "local_agent_turn_adapter",
                "provider": "synthetic-local-provider",
                "model": "synthetic-local-model",
                "endpoint": "http://127.0.0.1:11434",
            }
        ),
        provenance_validation={
            **pack.provenance_validation,
            "run_id": run_id,
            "request_id": request_id,
        },
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


def _corpus_snapshot_resolver(
    corpus_root: Path,
    source_allowlist: tuple[str, ...],
) -> str:
    from src.mod_agent.evaluation.arm_a import RunManifestCollector

    return RunManifestCollector(corpus_root).canonical_corpus_snapshot(
        source_allowlist
    ).corpus_snapshot_sha256


def _actual_manifest_binding(
    actual_input: HiddenGoldenActualInput,
) -> dict[str, object]:
    return {
        "case_identity": actual_input.case_identity,
        "request_sha256": actual_input.request_sha256,
        "declared_corpus_snapshot_sha256": (
            actual_input.declared_corpus_snapshot_sha256
        ),
        "observed_corpus_snapshot_sha256": (
            actual_input.observed_corpus_snapshot_sha256
        ),
        "source_allowlist": list(actual_input.source_allowlist),
    }


def _commit_pack(
    tmp_path: Path,
    *,
    query: str,
    actual_input: HiddenGoldenActualInput,
    manifest_binding: object | None = None,
    include_manifest_binding: bool = True,
):
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature-hidden-golden"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_feature_payload(feature_id),
    )
    pack = _semantic_pack(query)
    provenance_validation = dict(pack.provenance_validation)
    if include_manifest_binding:
        provenance_validation["manifest_bound_actual"] = (
            _actual_manifest_binding(actual_input)
            if manifest_binding is None
            else manifest_binding
        )
    pack = replace(pack, provenance_validation=provenance_validation)
    actual_ref = store.write(
        feature_id=feature_id,
        artifact_type="evidence_pack",
        payload=pack.to_artifact_payload(),
        upstream_refs=[feature_ref],
    )
    return store, actual_ref


def _feature_store(
    tmp_path: Path,
    *,
    request: str,
    contamination_sentinel: str | None = None,
):
    store = ArtifactStore(tmp_path / "artifacts")
    feature_id = "feature-hidden-golden"
    feature_ref = store.write(
        feature_id=feature_id,
        artifact_type="feature_spec",
        payload=_feature_payload(
            feature_id,
            request=request,
            contamination_sentinel=contamination_sentinel,
        ),
    )
    return store, feature_ref


def test_manifest_bound_actual_commits_reads_and_strictly_rehydrates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = "Find an observed current method."
    contamination_sentinel = "EXPECTED_SIDE_SENTINEL_MUST_NOT_REACH_ACTUAL"
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(
        tmp_path,
        request=request,
        contamination_sentinel=contamination_sentinel,
    )
    executor_calls: list[dict[str, object]] = []
    events: list[str] = []
    original_read = store.read
    original_write = store.write

    def recording_read(ref):
        events.append(f"read:{ref.artifact_type}")
        return original_read(ref)

    def recording_write(**kwargs):
        events.append(f"write:{kwargs['artifact_type']}")
        return original_write(**kwargs)

    monkeypatch.setattr(store, "read", recording_read)
    monkeypatch.setattr(store, "write", recording_write)

    def executor(
        *,
        r8_root: Path,
        request: str,
        run_id: str,
        request_id: str,
    ) -> EvidencePack:
        events.append("executor:start")
        executor_calls.append(
            {
                "r8_root": r8_root,
                "request": request,
                "run_id": run_id,
                "request_id": request_id,
            }
        )
        pack = _semantic_pack(request, run_id=run_id, request_id=request_id)
        events.append("executor:finished")
        return pack

    committed = commit_manifest_bound_calibration_actual(
        case_root=root,
        corpus_root=root,
        store=store,
        feature_spec_ref=feature_ref,
        run_id="run-synthetic",
        request_id="request-synthetic",
        corpus_snapshot_resolver=_corpus_snapshot_resolver,
        executor=executor,
    )

    assert isinstance(committed, CommittedCalibrationActual)
    assert executor_calls == [
        {
            "r8_root": root.resolve(),
            "request": request,
            "run_id": "run-synthetic",
            "request_id": "request-synthetic",
        }
    ]
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
    assert events.index("executor:finished") < events.index("read:feature_spec")
    assert events.index("read:feature_spec") < events.index("write:evidence_pack")
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
    serialized_payload = json.dumps(payload, ensure_ascii=False)
    assert "annotation.json" not in serialized_payload
    assert contamination_sentinel not in serialized_payload


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
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
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
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
            executor=lambda **_: _semantic_pack(request),
        )

    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


def test_manifest_bound_actual_rejects_feature_request_drift_after_executor_without_write(
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
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
            executor=executor,
        )

    assert executor_called is True
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
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
            executor=lambda **_: replace(
                EvidencePack.empty(
                    query=request,
                    reason="synthetic non-semantic result",
                ),
                model_identity={
                    "execution_kind": "local_agent_turn_adapter",
                    "provider": "synthetic-local-provider",
                    "model": "synthetic-local-model",
                    "endpoint": "http://127.0.0.1:11434",
                },
                provenance_validation={
                    "run_id": "run-synthetic",
                    "request_id": "request-synthetic",
                },
            ),
        )

    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


@pytest.mark.parametrize(
    ("provenance_validation", "error"),
    (
        (
            {"request_id": "request-synthetic"},
            "HIDDEN_GOLDEN_ACTUAL_RUN_ID_MISMATCH",
        ),
        (
            {"run_id": "different-run", "request_id": "request-synthetic"},
            "HIDDEN_GOLDEN_ACTUAL_RUN_ID_MISMATCH",
        ),
        (
            {"run_id": "run-synthetic"},
            "HIDDEN_GOLDEN_ACTUAL_REQUEST_ID_MISMATCH",
        ),
        (
            {"run_id": "run-synthetic", "request_id": "different-request"},
            "HIDDEN_GOLDEN_ACTUAL_REQUEST_ID_MISMATCH",
        ),
    ),
)
def test_manifest_bound_actual_rejects_missing_or_conflicting_execution_identity(
    tmp_path: Path,
    provenance_validation: dict[str, object],
    error: str,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    before_refs = store.list_feature_artifacts(feature_ref.feature_id)
    pack = replace(
        _semantic_pack(request),
        provenance_validation=provenance_validation,
    )

    with pytest.raises(HiddenGoldenCalibrationError, match=error):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
            executor=lambda **_: pack,
        )

    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


@pytest.mark.parametrize(
    ("model_identity", "error"),
    (
        (
            {
                "execution_kind": "injected_local_or_test",
                "provider": None,
                "model": None,
            },
            "HIDDEN_GOLDEN_ACTUAL_TEST_MODEL_IDENTITY_FORBIDDEN",
        ),
        (
            {
                "execution_kind": "local_agent_turn_adapter",
                "provider": "synthetic-local-provider",
                "model": "synthetic-local-model",
                "endpoint": "",
            },
            "HIDDEN_GOLDEN_ACTUAL_MODEL_IDENTITY_INCOMPLETE",
        ),
        (
            {
                "execution_kind": "external_agent_turn_adapter",
                "provider": "synthetic-external-provider",
                "model": "synthetic-external-model",
                "approval_id": "",
            },
            "HIDDEN_GOLDEN_ACTUAL_MODEL_IDENTITY_INCOMPLETE",
        ),
        (
            {"execution_kind": "unknown"},
            "HIDDEN_GOLDEN_ACTUAL_MODEL_EXECUTION_KIND_INVALID",
        ),
    ),
)
def test_manifest_bound_actual_rejects_invalid_real_model_identity(
    tmp_path: Path,
    model_identity: dict[str, object],
    error: str,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    before_refs = store.list_feature_artifacts(feature_ref.feature_id)

    with pytest.raises(HiddenGoldenCalibrationError, match=error):
        commit_manifest_bound_calibration_actual(
            case_root=root,
            corpus_root=root,
            store=store,
            feature_spec_ref=feature_ref,
            run_id="run-synthetic",
            request_id="request-synthetic",
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
            executor=lambda **_: _semantic_pack(
                request,
                model_identity=model_identity,
            ),
        )

    assert store.list_feature_artifacts(feature_ref.feature_id) == before_refs


def test_manifest_bound_actual_accepts_external_identity_without_endpoint(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    store, feature_ref = _feature_store(tmp_path, request=request)
    committed = commit_manifest_bound_calibration_actual(
        case_root=root,
        corpus_root=root,
        store=store,
        feature_spec_ref=feature_ref,
        run_id="run-synthetic",
        request_id="request-synthetic",
        corpus_snapshot_resolver=_corpus_snapshot_resolver,
        executor=lambda **_: _semantic_pack(
            request,
            model_identity={
                "execution_kind": "external_agent_turn_adapter",
                "provider": "synthetic-external-provider",
                "model": "synthetic-external-model",
                "approval_id": "approval-synthetic",
            },
        ),
    )

    assert committed.evidence_pack.model_identity == {
        "execution_kind": "external_agent_turn_adapter",
        "provider": "synthetic-external-provider",
        "model": "synthetic-external-model",
        "approval_id": "approval-synthetic",
    }


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
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
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


def test_hidden_golden_module_has_no_actual_executor_or_store_write_owner() -> None:
    source = inspect.getsource(hidden_golden_module)
    assert "def load_hidden_golden_actual_input" not in source
    assert "def commit_manifest_bound_calibration_actual" not in source
    assert "executor(" not in source
    assert ".write(" not in source


def test_hidden_golden_reads_expected_only_after_committed_actual_binding(
    tmp_path: Path,
) -> None:
    root = _actual_input_root(tmp_path, request="Find an observed current method.")
    actual_input = load_hidden_golden_actual_input(
        root,
        corpus_root=root,
        corpus_snapshot_resolver=_corpus_snapshot_resolver,
    )
    annotation_path = root / "annotation.json"
    annotation_path.write_text("not-json", encoding="utf-8")
    store, actual_ref = _commit_pack(
        tmp_path,
        query="different request",
        actual_input=actual_input,
    )

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


@pytest.mark.parametrize(
    "binding_change",
    (
        "missing",
        "wrong_shape",
        "case_identity",
        "request_sha256",
        "declared_corpus_snapshot_sha256",
        "observed_corpus_snapshot_sha256",
        "source_allowlist",
    ),
)
def test_hidden_golden_rejects_manifest_binding_before_annotation_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_change: str,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    actual_input = load_hidden_golden_actual_input(
        root,
        corpus_root=root,
        corpus_snapshot_resolver=_corpus_snapshot_resolver,
    )
    annotation_path = root / "annotation.json"
    annotation_path.write_text("not-json", encoding="utf-8")
    binding: object = _actual_manifest_binding(actual_input)
    include_binding = binding_change != "missing"
    if binding_change == "wrong_shape":
        binding = []
    elif binding_change not in {"missing", "wrong_shape"}:
        assert isinstance(binding, dict)
        binding[binding_change] = (
            ["Datablocks"]
            if binding_change == "source_allowlist"
            else "tampered"
        )
    store, actual_ref = _commit_pack(
        tmp_path,
        query=request,
        actual_input=actual_input,
        manifest_binding=binding,
        include_manifest_binding=include_binding,
    )
    original_read_text = Path.read_text
    annotation_read = False

    def recording_read_text(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal annotation_read
        if path.resolve() == annotation_path.resolve():
            annotation_read = True
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording_read_text)

    with pytest.raises(
        HiddenGoldenCalibrationError,
        match="HIDDEN_GOLDEN_ACTUAL_MANIFEST_BINDING_MISMATCH",
    ):
        evaluate_committed_hidden_golden(
            store=store,
            actual_ref=actual_ref,
            actual_input=actual_input,
            annotation_path=annotation_path,
        )

    assert annotation_read is False


def test_hidden_golden_minimal_comparison_uses_committed_strict_actual(
    tmp_path: Path,
) -> None:
    request = "Find an observed current method."
    root = _actual_input_root(tmp_path, request=request)
    actual_input = load_hidden_golden_actual_input(
        root,
        corpus_root=root,
        corpus_snapshot_resolver=_corpus_snapshot_resolver,
    )
    annotation_path = root / "annotation.json"
    annotation_path.write_text(json.dumps(_annotation()), encoding="utf-8")
    store, actual_ref = _commit_pack(
        tmp_path,
        query=request,
        actual_input=actual_input,
    )

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
    actual_input = load_hidden_golden_actual_input(
        root,
        corpus_root=root,
        corpus_snapshot_resolver=_corpus_snapshot_resolver,
    )
    annotation = deepcopy(_annotation())
    annotation["judgment_payload"]["expected_control_action"] = "block"
    annotation_path = root / "annotation.json"
    annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
    store, actual_ref = _commit_pack(
        tmp_path,
        query=request,
        actual_input=actual_input,
    )

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
        load_hidden_golden_actual_input(
            root,
            corpus_root=root,
            corpus_snapshot_resolver=_corpus_snapshot_resolver,
        )


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
