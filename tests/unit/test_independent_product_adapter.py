"""A new evaluation adapter actually invokes the original public Graph entry.

Reuse public fixture setup only; HTTP/compilation stay explicit doubles. No
operator target reaches either evaluation arm. The common judge returns unknown
because this wiring fixture has no real C# behavior execution.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from src.mod_agent.evaluation.independent_preparation import file_ref
from src.mod_agent.evaluation.independent_product_adapter import run_public_product_pair
from tests.unit import test_mod_agent_cli as setup


def test_evaluation_adapter_invokes_full_graph_and_simple_from_equal_public_inputs(tmp_path, monkeypatch, capsys):
    public_main = setup.main
    results, judgments = [], []

    class FinishedCalibrationError(Exception):
        pass

    def independent_judge(document):
        judgments.append(document)
        assert document["unified_diff"]
        return {"compilation": "controlled_stub_only", "behavior": "not_evaluated",
                "outcome": "insufficient_observation", "task_success": None}

    def invoke(arguments):
        # All network is already replaced by this existing public fixture's
        # controlled response transport. The real parser/Graph/worker run.
        assert "--planning-target-evidence-id" not in arguments
        output = io.StringIO()
        with redirect_stdout(output):
            code = public_main(arguments)
        return code, json.loads(output.getvalue())

    def route_existing_fixture_into_new_adapter(arguments):
        monkeypatch.setattr("src.mod_agent.cli.run_local_request", setup.local_entry_module.run_local_request)
        source = tmp_path / "Example"
        initial = {p.name: p.read_text(encoding="utf-8") for p in source.iterdir() if p.is_file()}
        # This response belongs to the explicitly public fixture and is shared
        # engineering authorship, not an independent task/reference repair.
        after = initial["Plugin.cs"].replace("{}", "{ /* PRODUCT_TEST_CHANGE */ }")
        result = run_public_product_pair(task_id="public-product-entry", description=arguments[1],
            initial_files=initial, search_patterns=["Load"], output_root=tmp_path / "comparison",
            settings_path="config/settings.yaml",
            controlled_profile={"model": "qwen3:4b-instruct", "context_window": 32768,
                "output_tokens": 4096, "timeout_seconds": 600, "total_calls": 5},
            simple_submission={"action": "submit", "files": {"Plugin.cs": after}},
            invoke_controlled_product=invoke, final_judge=independent_judge,
            final_judge_identity=file_ref(Path(__file__)))
        results.append(result)
        raise FinishedCalibrationError

    monkeypatch.setattr(setup, "main", route_existing_fixture_into_new_adapter)
    with pytest.raises(FinishedCalibrationError):
        setup.test_cli_run_request_real_public_product_executor_compile_success(tmp_path, monkeypatch, capsys)
    result = results[0]
    assert result["product_exit_code"] == 0 and result["product_graph_invoked"] is True
    assert result["product_status"] == "awaiting_approval"
    assert result["product_budget"]["maximum"] == result["simple_loop_budget"]["max_total_model_turns"] == 5
    assert result["product_budget"]["by_stage"]["planning"]["consumed"] == 1
    assert len(judgments) == 2 and judgments[0]["initial_files"] == judgments[1]["initial_files"]
    assert all(row["verdict"]["task_success"] is None and row["native_model_calls"] == 0 for row in result["results"])
    assert len({row["input_sha256"] for row in result["results"]}) == 1
    assert result["model_task_success_rate"] is None and result["live_comparison_admitted"] is False
    product = json.loads((tmp_path / "comparison/full_product_graph/product-result.json").read_text())
    assert product["actual_write_performed"] is False
    assert product["builds_performed"] == product["runtime_executions_performed"] == 0
