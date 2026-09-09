"""Public-entry migration checks; transport and compiler doubles are explicit."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.libs.llm import Message
from src.mod_agent import local_entry
from tests.unit import test_mod_agent_cli as public_entry_tests
from tests.unit.test_mod_agent_cli import (
    test_cli_run_request_real_public_product_executor_compile_success as _public_compile_scenario,
)


def test_public_request_entry_imports_in_a_fresh_process():
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "from pathlib import Path; from src.mod_agent import local_entry; "
         "assert Path(local_entry.__file__).resolve() == "
         "Path('src/mod_agent/local_entry.py').resolve()"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("operator_targets,defer_approval", [(True, False), (False, False), (False, True)])
def test_public_run_request_reaches_the_existing_shared_worker(tmp_path, monkeypatch, capsys, operator_targets, defer_approval):
    calls = []
    original = local_entry.LocalOllamaInitialPatchAdapter.__call__

    def observe(self, state, implementation, evidence_pack):
        calls.append((state, implementation, evidence_pack))
        return original(self, state, implementation, evidence_pack)

    monkeypatch.setattr(local_entry.LocalOllamaInitialPatchAdapter, "__call__", observe)

    def sender(self, url, payload, headers):
        assert url == "http://127.0.0.1:11434/api/chat"
        content = payload["messages"][1]["content"]
        context = json.loads(content)
        if "patch_agent_context_encoding" in context:
            context = local_entry._restore_patch_agent_context(context)
        if "allowed_edit_evidence_ids" in context:
            assert operator_targets is False
            response = json.dumps({"decision": "select_targets",
                "selected_evidence_ids": context["allowed_edit_evidence_ids"],
                "rationale": "Engineering transport fixture selected the observed source unit.",
                "missing_evidence": []})
            return {"model": payload["model"], "message": {"role": "assistant", "content": response},
                    "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20}
        response = local_entry.OllamaLLM.chat(
            SimpleNamespace(timeout=self.timeout_seconds),
            [Message(role="user", content=json.dumps(context))],
        )
        return {"model": response.model, "message": {"role": "assistant", "content": response.content},
                "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 20}

    monkeypatch.setattr("src.libs.llm.agent_turn._LoopbackHttpJsonSender.__call__", sender)
    original_main = public_entry_tests.main
    pending_results = []

    class ApprovalPausedError(Exception):
        pass

    def main_without_operator_targets(arguments):
        if not operator_targets:
            offset = arguments.index("--planning-target-evidence-id")
            arguments = arguments[:offset] + arguments[offset + 2:]
        if defer_approval:
            arguments = [*arguments, "--defer-approval"]
        exit_code = original_main(arguments)
        if defer_approval:
            result = json.loads(capsys.readouterr().out)
            assert exit_code == 0, result
            pending_results.append(result)
            raise ApprovalPausedError
        return exit_code

    monkeypatch.setattr(public_entry_tests, "main", main_without_operator_targets)
    if defer_approval:
        with pytest.raises(ApprovalPausedError):
            _public_compile_scenario(tmp_path, monkeypatch, capsys)
        pending = pending_results[0]
        assert pending["status"] == "awaiting_approval"
        assert pending["approval_recorded"] is False
        assert pending["actual_write_performed"] is False
        assert pending["builds_performed"] == pending["runtime_executions_performed"] == 0
        assert pending["canonical_source_unchanged"] is True
        assert pending["model_call_budget"]["by_stage"]["planning"]["consumed"] == 1
        assert pending["workflow_checkpoint"]["artifact_type"] == "workflow_checkpoint"
        assert pending["unified_diff"] and pending["patch_execution_receipts"]
        assert "product_execution_result" not in pending
    else:
        _public_compile_scenario(tmp_path, monkeypatch, capsys)
    assert calls, "run-request bypassed the existing shared Patch worker"
    state, implementation, evidence = calls[0]
    assert state["artifacts"]["implementation_plan"]
    assert implementation["binding_registry"]["edit_bindings"]
    assert evidence["requirement_coverage"]
    if not operator_targets:
        reports = list((tmp_path / "runs").rglob("planning_model_selection.json"))
        assert len(reports) == 1
        planning = json.loads(reports[0].read_text(encoding="utf-8"))
        assert planning["selection_mode"] == "model"
        assert planning["operator_target_ids_supplied"] is False
        assert planning["model_responses_received"] == 1
