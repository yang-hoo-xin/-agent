"""SFT eval uses production continuation/transport with explicit offline fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from scripts import prepare_patch_sft_data as data
from scripts import run_patch_sft_eval as evaluation
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchProfileV1,
    _restore_patch_agent_context,
)
from tests.unit.test_patch_repair_cli import _message_jsons


def _fake_execution(root, source, program, tools):
    root.mkdir(parents=True)
    path = root / "Subject.cs"
    path.write_text(source, encoding="utf-8", newline="\n")
    assembly = root / "fake.dll"
    assembly.write_bytes(b"synthetic execution record")
    failed = "if (!publish) return;" in source or "Published++;" in source and "if (publish) Published++;" not in source
    checks = [{"check": "publication_bound", "expected": True, "observed": not failed, "passed": not failed, "group": "new"},
              {"check": "preserve_enabled", "expected": True, "observed": True, "passed": True, "group": "preservation"}]
    compilation = data.save(root / "compilation.json", {"exit_code": 0, "stdout": "synthetic", "stderr": ""})
    record = {"status": "behavior_failed" if failed else "passed", "checks": checks,
        "failed_checks": [row["check"] for row in checks if not row["passed"]], "preservation_passed": True,
        "execution_origin": "actual_csharp_process", "source_ref": data.ref(path),
        "compilation_ref": compilation, "assembly_ref": data.ref(assembly), "fixture_only": True}
    return {**record, "report_ref": data.save(root / "behavior.json", record)}


def _fixture(tmp_path, monkeypatch):
    module = data.load_tasks()
    definition = module.TASKS[0]
    monkeypatch.setattr(data, "execute_version", _fake_execution)
    sample, task = data.prepare_one(definition, tmp_path / "task", {}, module.harness(definition["checks"]))
    manifest = data.save(tmp_path / "manifest.json", {"tasks": [task]})
    profile = LocalOllamaInitialPatchProfileV1(profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        base_url="http://127.0.0.1:11434", model="offline-sft", context_window=16384, output_budget=4096, timeout_seconds=30)
    profile_ref = data.save(tmp_path / "profile.json", profile.to_dict())
    return task, manifest, profile_ref, sample


def _install(monkeypatch):
    chats = []
    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "offline-sft", "model": "offline-sft",
                "digest": "a" * 64, "modified_at": "2026-09-08T00:00:00Z", "size": 1,
                "details": {"context_length": 32768}, "capabilities": ["completion", "tools"]}]}, request=request)
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        chats.append(payload)
        values = _message_jsons(payload)
        prompt = _restore_patch_agent_context(next(value for _, value in values if "required_change_units" in value))
        if len(chats) == 1:
            binding = prompt["required_change_units"][0]["edit_binding_id"]
            message = {"role": "assistant", "content": "", "tool_calls": [{"function": {
                "name": "inspect_plan_binding_source", "arguments": {"binding_id": binding}}}]}
        else:
            context = next(iter(prompt["edit_binding_contexts"].values()))
            after = context["source_excerpt"].replace("Published++;", "if (publish) Published++;")
            message = {"role": "assistant", "content": json.dumps({"changes": [{"edit_binding_id": context["binding_id"],
                "rationale": "Synthetic response in an offline integration test.", "rollback_hint": "Restore original.", "after_text": after}]})}
        return httpx.Response(200, json={"model": "offline-sft", "message": message, "done": True,
            "done_reason": "stop", "prompt_eval_count": 200, "eval_count": 80}, request=request)
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    monkeypatch.setattr("socket.socket.connect", lambda *_: (_ for _ in ()).throw(AssertionError("No real network")))
    monkeypatch.setattr(evaluation, "execute_version", _fake_execution)
    monkeypatch.setattr(evaluation, "toolchain", lambda: {})
    return chats


@pytest.mark.parametrize("mode", ["fixed_failure", "initial_patch"])
def test_preparation_and_shared_worker_transport_reach_review_and_dry_run_without_hidden_c2(tmp_path, monkeypatch, mode):
    task, manifest, profile, sample = _fixture(tmp_path, monkeypatch)
    chats = _install(monkeypatch)
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
        mode=mode, attempt_id="offline-"+mode, output_root=tmp_path / "attempt")
    assert not chats and prepared["model_calls"] == 0
    result = evaluation.execute_prepared(prepared["prepared_ref"])
    assert result["task_succeeded"] is True, result
    assert len(chats) == result["actual_model_calls_recorded"] == 2
    assert result["execution_counts"]["review"] == result["execution_counts"]["dry_run"] == 1
    assert result["execution_counts"]["apply"] == result["execution_counts"]["build"] == result["execution_counts"]["runtime"] == 0
    assert result["preservation_passed"] is True
    first = json.dumps(chats[0])
    assert "hidden_oracle" not in first and "CheckApp" not in first
    assert "if (publish) Published++;" not in first
    teacher_c2 = json.loads(sample["completion"][0]["content"])["changes"][0]["after_text"]
    assert teacher_c2 not in [message.get("content") for message in chats[0]["messages"]]
    if mode == "initial_patch":
        assert result["initial_output_correct"] is True and result["repair_required"] is False
        assert "patch_repair_context" not in first
    else:
        assert result["effective_revision"] is True
        assert "patch_repair_context" in first
        parent = json.loads((tmp_path / "attempt/teacher-parent-receipt.json").read_text(encoding="utf-8"))
        assert parent["origin"] == "operator_authored_fixed_failure" and parent["provider_send_count"] == 0
        assert parent["historical_model_attempt_claimed"] is False


def test_duplicate_attempt_output_is_not_overwritten(tmp_path, monkeypatch):
    task, manifest, profile, _ = _fixture(tmp_path, monkeypatch)
    output = tmp_path / "attempt"
    prepared = evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
        mode="initial_patch", attempt_id="unique", output_root=output)
    original = Path(prepared["prepared_ref"]["path"]).read_bytes()
    with pytest.raises(FileExistsError):
        evaluation.prepare_eval(manifest_ref=manifest, case_id=task["case_id"], profile_ref=profile,
            mode="initial_patch", attempt_id="unique", output_root=output)
    assert hashlib.sha256(original).hexdigest() == prepared["prepared_ref"]["sha256"]
