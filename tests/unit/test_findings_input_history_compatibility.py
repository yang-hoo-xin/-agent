"""Historical Findings retain exact meaning across reversible input text encoding."""

from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from src.mod_agent import initial_findings_continuation as continuation
from src.mod_agent.evidence import model_view
from src.mod_agent.evidence import requirement_coverage_provider as provider
from src.mod_agent.evidence.model_view import deduplicate_findings_input_text
from tests.unit import test_findings_schema_recovery as schema_scenario
from tests.unit import test_saved_reassessment as saved_scenario
from tests.unit.test_dsh_run_request import execution_config as execution_config  # noqa: F401
from tests.unit.test_initial_findings_continuation import _failed_run


def _text_wire_fixture(monkeypatch, *, historical_encoded=False):
    state = {"encoded": historical_encoded, "damage": None, "encoded_calls": 0}
    original = provider.StructuredModelRequirementCoverageProvider.__init__

    def initialize(self, complete_json, **kwargs):
        def complete(role, payload, schema):
            if role == "requirement_findings":
                payload = deepcopy(payload)
                payload["semantic_feedback"] = {"reason": "controlled historical upstream input"}
                text = "Retain this complete original obligation, its source and all constraints. " * 20
                for relation in payload["relations"]:
                    for parent in relation["parent_requirements"]:
                        parent["text"] = text
                        for obligation in parent.get("input_obligations", []):
                            obligation["text"] = text
                if state["encoded"]:
                    payload = deduplicate_findings_input_text(payload)
                    assert "findings_input_text_encoding" in payload
                    state["encoded_calls"] += 1
                parent = payload["relations"][0]["parent_requirements"][0]
                if state["damage"] == "text":
                    parent["text"] += " changed"
                elif state["damage"] == "metadata":
                    parent["fixture_changed_metadata"] = True
                elif state["damage"] == "schema":
                    schema = deepcopy(schema)
                    schema["description"] = "changed"
            return complete_json(role, payload, schema)

        original(self, complete, **kwargs)

    monkeypatch.setattr(provider.StructuredModelRequirementCoverageProvider, "__init__", initialize)
    return state


@pytest.mark.parametrize("historical_encoded", [False, True])
def test_initial_preparation_replays_raw_and_encoded_history_without_calls(
        execution_config, monkeypatch, capsys, historical_encoded):
    state = _text_wire_fixture(monkeypatch, historical_encoded=historical_encoded)
    result, posts = _failed_run(execution_config, monkeypatch, capsys)
    root = Path(result["run_root"])
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    state["encoded"] = True
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("unexpected HTTP"))
    prepared = continuation.prepare_initial_findings_continuation(
        run_root=root, run_id=result["run_id"], execution_config=execution_config)
    assert prepared["budget"] == result["model_call_budget"]
    assert prepared["model_calls_performed"] == 0
    assert state["encoded_calls"] >= 1
    assert len(posts) == 2
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("damage", ["text", "metadata", "schema"])
def test_initial_history_encoding_does_not_allow_changed_input(
        execution_config, monkeypatch, capsys, damage):
    state = _text_wire_fixture(monkeypatch)
    result, _ = _failed_run(execution_config, monkeypatch, capsys)
    state.update(encoded=True, damage=damage)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("unexpected HTTP"))
    with pytest.raises(RuntimeError, match="INITIAL_FINDINGS_CURRENT_INPUT_DIFFERS"):
        continuation.prepare_initial_findings_continuation(run_root=result["run_root"],
            run_id=result["run_id"], execution_config=execution_config)


def test_prepared_history_binds_text_codec_implementation(execution_config, monkeypatch, capsys):
    result, _ = _failed_run(execution_config, monkeypatch, capsys)
    args = {"run_root": result["run_root"], "run_id": result["run_id"], "execution_config": execution_config}
    prepared = continuation.prepare_initial_findings_continuation(**args)
    codec_path = Path(model_view.__file__).resolve()
    assert str(codec_path) in {row["path"] for row in prepared["continuation_input"]["implementation_refs"]}
    read_bytes = Path.read_bytes

    def changed_bytes(path):
        data = read_bytes(path)
        return data + b"\n# changed codec implementation\n" if path.resolve() == codec_path else data

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *_: pytest.fail("unexpected HTTP"))
    with pytest.raises(ValueError, match="INITIAL_FINDINGS_CONTINUATION_INPUT_CHANGED"):
        continuation.admit_initial_findings_continuation(prepared, **args)


def test_saved_query_finishes_with_encoded_replay_of_original_raw_findings(
        execution_config, monkeypatch, capsys):
    state = _text_wire_fixture(monkeypatch)
    original = saved_scenario.prepare_initial_findings_continuation

    def prepare(**kwargs):
        state["encoded"] = True
        return original(**kwargs)

    monkeypatch.setattr(saved_scenario, "prepare_initial_findings_continuation", prepare)
    saved_scenario.test_original_run_reuses_saved_query_and_charges_only_next_live_calls(
        execution_config, monkeypatch, capsys, accepted_gap=True, baseline_failure=False)
    assert state["encoded_calls"] >= 1


def test_schema_recovery_matches_raw_historical_input_after_encoding(
        execution_config, monkeypatch, capsys):
    from src.mod_agent import findings_schema_recovery

    state = _text_wire_fixture(monkeypatch)
    original = findings_schema_recovery.prepare_findings_schema_recovery

    def prepare(**kwargs):
        state["encoded"] = True
        return original(**kwargs)

    monkeypatch.setattr(findings_schema_recovery, "prepare_findings_schema_recovery", prepare)
    schema_scenario.test_empty_findings_refusal_recovers_once_with_original_six_charges(
        execution_config, monkeypatch, capsys)
    assert state["encoded_calls"] >= 1
