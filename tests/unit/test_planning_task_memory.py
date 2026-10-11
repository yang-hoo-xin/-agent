"""Planning memory reaches the original request and cannot grant source authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import pytest
import yaml

from src.core.settings import SettingsError, TaskMemorySettings, load_settings
from src.libs.llm.agent_turn import OllamaChatAgentAdapter
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.local_entry import LocalEntryError, _verify_planning_task_memory_disclosure
from src.mod_agent.planning.model_selection import (
    TASK_MEMORY_DATA_CLASS,
    ModelPlanningTargetSelector,
    PlanningTargetSelectionError,
)
from src.mod_agent.planning.task_memory import TaskMemory
from tests.unit.test_fresh_planning_continuation import _inputs


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _client(captured, *, selected=None):
    def send(url, payload, headers):
        captured.append(deepcopy(payload))
        model_input = json.loads(payload["messages"][1]["content"])
        return {
            "model": "memory-planning-test", "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": _json({
                "decision": "select_targets",
                "selected_evidence_ids": (model_input["allowed_edit_evidence_ids"]
                                          if selected is None else selected),
                "rationale": "Select only the current evidence units.", "missing_evidence": [],
            })},
            "prompt_eval_count": 100, "eval_count": 30,
        }

    return OllamaChatAgentAdapter(
        base_url="http://127.0.0.1:11434", model="memory-planning-test",
        max_output_tokens=1024, context_window=65536, request_sender=send,
    )


def _record(memory, inputs, root, lesson_id="timeout", *, value=4, scope="transport",
            applicability=None, expires_at=None):
    path = root / f"{lesson_id}.json"
    path.write_text(_json({
        "request": inputs.feature_payload["user_request"] + " OLD_REQUEST_BODY_ONLY",
        "calls": value, "private_path": str(root / "private" / "source.cs"),
        "outcome": "Request timed out with call allowance remaining.",
    }), encoding="utf-8")
    ref = memory.record(
        lesson_id=lesson_id,
        evidence_refs=[{"kind": "json_file", "evidence_id": "receipt", "path": str(path),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
        request={"evidence_id": "receipt", "locator": ["request"]},
        facts=[{"evidence_id": "receipt", "locator": ["calls"], "scope": scope,
                "key": "observed_calls", "role": "observation"},
               {"evidence_id": "receipt", "locator": ["private_path"], "scope": scope,
                "key": "source_path", "role": "observation"}],
        outcome={"evidence_id": "receipt", "locator": ["outcome"]},
        applicability=(applicability if applicability is not None else {
            "target_mod": inputs.feature_payload["target_mod"],
            "provider": "ollama_chat_local", "model": "memory-planning-test",
        }),
        unknowns=["No behavior result was obtained."],
        invalidation_conditions=["Recheck the current provider and model."],
        expires_at=expires_at,
    )
    return ref, path


def _selector(inputs, client, memory_root=None, *, receipt="planning.json", max_chars=6000):
    return ModelPlanningTargetSelector.from_settings(
        settings=SimpleNamespace(task_memory=(
            TaskMemorySettings(enabled=True, store_root=str(memory_root), max_context_chars=max_chars)
            if memory_root is not None else None)),
        client=client, workspace_root=inputs.workspace,
        receipt_path=inputs.store.root / receipt,
        model_identity={"model": client.model, "digest": "current-model-digest"},
    )


def test_memory_facts_reach_native_planning_wire_and_original_receipt(tmp_path):
    inputs = _inputs(tmp_path)
    memory_root = tmp_path / "memory"
    memory = TaskMemory(ArtifactStore(memory_root))
    ref, original = _record(memory, inputs, tmp_path)
    captured = []
    selector = _selector(inputs, _client(captured), memory_root)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    feature_before, evidence_before = deepcopy(inputs.feature_payload), deepcopy(evidence)
    prepared = selector.prepare(inputs.feature_payload, evidence)
    assert not selector.receipt_path.exists()
    selected = selector(inputs.feature_payload, evidence)
    wire = json.loads(captured[0]["messages"][1]["content"])
    view = wire["retrieved_experience"]
    assert view == prepared.messages[1].content["retrieved_experience"]
    assert view["authority"] == "planning_only"
    assert view["lessons"][0]["artifact_hash"] == ref.artifact_hash
    assert view["lessons"][0]["facts"] == [
        {"scope": "transport", "key": "observed_calls", "value": 4, "role": "observation"}
    ]
    assert "OLD_REQUEST_BODY_ONLY" not in _json(view)
    assert str(tmp_path) not in _json(view)
    assert wire["allowed_edit_evidence_ids"] == list(selected)
    assert captured[0]["format"]["properties"]["selected_evidence_ids"]["items"]["enum"] == list(selected)
    assert inputs.feature_payload == feature_before and evidence == evidence_before
    receipt = json.loads(selector.receipt_path.read_text(encoding="utf-8"))["task_memory"]
    assert receipt["model_lesson_refs"] == [{"lesson_id": "timeout", "artifact_hash": ref.artifact_hash}]
    assert receipt["model_view_sha256"] == hashlib.sha256(_json(view).encode("utf-8")).hexdigest()
    assert receipt["model_view_chars"] <= 6000
    assert receipt["model_view_utf8_bytes"] == len(_json(view).encode("utf-8"))
    assert receipt["data_classes"] == [TASK_MEMORY_DATA_CLASS]
    context = receipt["current_context"]
    assert context["target_mod"] == inputs.feature_payload["target_mod"]
    assert context["provider"] == "ollama_chat_local"
    assert context["model_digest"] == "current-model-digest"
    for item in evidence["items"]:
        if item["source_type"] == "target_source":
            assert context["source_hash:" + item["source_path"]] == item["source_hash"]
    assert receipt["retrieved_experience"]["relevant_lessons"][0]["evidence_refs"][0]["path"] == str(original)


def test_expired_conflicting_and_changed_evidence_never_reach_planning(tmp_path):
    inputs = _inputs(tmp_path)
    memory_root = tmp_path / "memory"
    memory = TaskMemory(ArtifactStore(memory_root))
    _record(memory, inputs, tmp_path, "conflict-a", value=4)
    _record(memory, inputs, tmp_path, "conflict-b", value=5)
    _record(memory, inputs, tmp_path, "expired", scope="old",
            expires_at="2000-01-01T00:00:00+00:00")
    _, changed = _record(memory, inputs, tmp_path, "changed", scope="changed")
    changed.write_text("{}", encoding="utf-8")
    _record(memory, inputs, tmp_path, "wrong-context", scope="other",
            applicability={"model": "another-model"})
    captured = []
    selector = _selector(inputs, _client(captured), memory_root, max_chars=12000)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    selector(inputs.feature_payload, evidence)
    assert "retrieved_experience" not in json.loads(captured[0]["messages"][1]["content"])
    receipt = json.loads(selector.receipt_path.read_text(encoding="utf-8"))["task_memory"]
    unavailable = _json(receipt["retrieved_experience"]["unavailable_evidence"])
    assert "conflicting_scope_key_values" in unavailable
    assert "experience expired" in unavailable
    assert "source hash changed" in unavailable
    assert "applicability changed: model" in unavailable
    assert receipt["model_lesson_refs"] == []


def test_memory_cannot_add_an_edit_id_to_model_selection(tmp_path):
    inputs = _inputs(tmp_path)
    memory_root = tmp_path / "memory"
    _record(TaskMemory(ArtifactStore(memory_root)), inputs, tmp_path, value="unregistered-edit-id")
    captured = []
    selector = _selector(inputs, _client(captured, selected=["unregistered-edit-id"]), memory_root)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    with pytest.raises(PlanningTargetSelectionError) as error:
        selector(inputs.feature_payload, evidence)
    assert error.value.code == "PLANNING_MODEL_SELECTION_OUTSIDE_ENUM"
    wire = json.loads(captured[0]["messages"][1]["content"])
    assert "unregistered-edit-id" in _json(wire["retrieved_experience"])
    assert "unregistered-edit-id" not in wire["allowed_edit_evidence_ids"]


def test_each_prepare_revalidates_memory_and_missing_identity_is_not_invented(tmp_path):
    inputs = _inputs(tmp_path)
    memory = TaskMemory(ArtifactStore(tmp_path / "memory"))
    _, receipt = _record(memory, inputs, tmp_path)
    _record(memory, inputs, tmp_path, "unknown-digest", scope="versioned",
            applicability={"model_digest": "not-observed"})
    selector = ModelPlanningTargetSelector(client=_client([]), workspace_root=inputs.workspace,
        receipt_path=tmp_path / "planning.json", task_memory=memory,
        task_memory_max_context_chars=6000)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    first = selector.prepare(inputs.feature_payload, evidence).messages[1].content
    assert [item["lesson_id"] for item in first["retrieved_experience"]["lessons"]] == ["timeout"]
    receipt.write_text("{}", encoding="utf-8")
    second = selector.prepare(inputs.feature_payload, evidence).messages[1].content
    assert "retrieved_experience" not in second


@pytest.mark.parametrize("configuration", [None, TaskMemorySettings(), TaskMemorySettings(store_root="unused")])
def test_unconfigured_and_disabled_memory_preserve_original_payload(tmp_path, configuration):
    inputs = _inputs(tmp_path)
    arguments = dict(client=_client([]), workspace_root=inputs.workspace,
                     receipt_path=tmp_path / "selection.json")
    selector = ModelPlanningTargetSelector.from_settings(
        settings=SimpleNamespace(task_memory=configuration), **arguments)
    original = ModelPlanningTargetSelector(**arguments)
    evidence = inputs.store.read(inputs.evidence_ref)["data"]
    assert asdict(selector.prepare(inputs.feature_payload, evidence)) == asdict(
        original.prepare(inputs.feature_payload, evidence))


def test_planning_memory_requires_its_own_external_disclosure_class(tmp_path):
    inputs = _inputs(tmp_path)
    root = tmp_path / "memory"
    _record(TaskMemory(ArtifactStore(root)), inputs, tmp_path)
    payload = _selector(inputs, _client([]), root).prepare(
        inputs.feature_payload, inputs.store.read(inputs.evidence_ref)["data"]).messages[1].content
    approved = {"approved": True, "approved_data_classes": ["verification_feedback"]}
    with pytest.raises(LocalEntryError, match=TASK_MEMORY_DATA_CLASS):
        _verify_planning_task_memory_disclosure(payload, approved, external=True)
    _verify_planning_task_memory_disclosure(payload, approved, external=False)
    _verify_planning_task_memory_disclosure(payload, {
        **approved, "approved_data_classes": [TASK_MEMORY_DATA_CLASS]}, external=True)


def _settings_file(tmp_path, memory):
    data = {
        "llm": {"provider": "ollama", "model": "test", "temperature": 0, "max_tokens": 1024},
        "embedding": {"provider": "ollama", "model": "test", "dimensions": 2},
        "vector_store": {"provider": "chroma", "persist_directory": "db", "collection_name": "test"},
        "retrieval": {"dense_top_k": 1, "sparse_top_k": 1, "fusion_top_k": 1, "rrf_k": 60},
        "rerank": {"enabled": False, "provider": "none", "model": "none", "top_k": 1},
        "evaluation": {"enabled": False, "provider": "custom", "metrics": []},
        "observability": {"log_level": "INFO", "trace_enabled": False,
                          "trace_file": "trace.jsonl", "structured_logging": True},
    }
    if memory is not None:
        data["task_memory"] = memory
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_settings_loads_optional_task_memory_through_original_loader(tmp_path):
    assert load_settings(_settings_file(tmp_path, None)).task_memory is None
    settings = load_settings(_settings_file(tmp_path, {
        "enabled": True, "store_root": "artifacts", "max_context_chars": 1234,
    }))
    assert settings.task_memory == TaskMemorySettings(True, "artifacts", 1234)


@pytest.mark.parametrize("memory", [
    {"enabled": True}, {"enabled": "true"}, {"enabled": True, "store_root": ""},
    {"max_context_chars": 255}, {"max_context_chars": True}, {"other_key": True},
])
def test_invalid_task_memory_settings_fail_before_execution(tmp_path, memory):
    with pytest.raises(SettingsError):
        load_settings(_settings_file(tmp_path, memory))
