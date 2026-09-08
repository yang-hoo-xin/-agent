"""Paired preparation tests use synthetic tasks; no model or verifier executes."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest

from scripts.prepare_patch_eval_suite import main
from src.observability.evaluation.patch_model_experiment import (
    prepare_patch_model_experiment,
    select_patch_experiment_cell,
)
from src.mod_agent.evaluation.patch_task_suite import reference, save_once
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchProfileV1,
)
from src.mod_agent.model_qualification import SUITE_SCHEMA, canonical_hash, read_bound_json
from src.mod_agent.patch_worker_configuration import PatchWorkerConfiguration
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy
from tests.unit.test_fresh_planning_continuation import _feature_payload, _inputs, _patch_request

_VERIFIER = '''import hashlib, json, sys
from pathlib import Path
class Verifier:
    def __init__(self, expected_check_ids): self.checks = expected_check_ids
    def verification_identity(self):
        return {"validator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "inputs_sha256": hashlib.sha256(json.dumps(self.checks).encode()).hexdigest(),
                "environment_sha256": hashlib.sha256(sys.version.encode()).hexdigest(),
                "deterministic_reuse_allowed": False}
    def __call__(self, context): raise AssertionError("Experiment preparation must not execute verification")
def build_evaluator(*, expected_check_ids): return Verifier(expected_check_ids)
'''


@pytest.fixture
def seed(tmp_path, monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("No model/network in preparation"))
    profile = LocalOllamaInitialPatchProfileV1(LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        "http://127.0.0.1:11434", "synthetic-model-a", 49152, 4096, 60).to_dict()
    policy = PatchAgentLoopPolicy(max_total_model_turns=5, max_tool_rounds=6,
        require_source_inspection=False, finalize_after_first_observation=False)
    cases = []
    for index in range(3):
        case_root = tmp_path / ("task" + str(index))
        feature = _feature_payload()
        feature["feature_id"] = "synthetic_experiment_task_" + str(index)
        feature["user_request"] += " Explicit synthetic contract task " + str(index)
        with monkeypatch.context() as patch:
            patch.setattr("tests.unit.test_fresh_planning_continuation._feature_payload", lambda: deepcopy(feature))
            inputs = _inputs(case_root)
            request = _patch_request(inputs)
        factory = case_root / "verifier.py"
        factory.write_text(_VERIFIER, encoding="utf-8")
        checks = ["behavior_" + str(index), "preservation_" + str(index)]
        config_ref = save_once(case_root / "worker.json", {
            "schema_version": "patch_worker_configuration_v1", "policy": asdict(policy), "enable_recovery_loop": True,
            "behavior_evaluator": {"factory_ref": reference(factory), "factory_name": "build_evaluator",
                "kwargs": {"expected_check_ids": checks}}})
        request = replace(request, worker_configuration_ref=config_ref, worker_profile_sha256=canonical_hash(profile))
        request_ref = save_once(case_root / "request.json", asdict(request))
        verifier = PatchWorkerConfiguration.load(config_ref["path"]).behavior_evaluator()
        cases.append({"case_id": "case-" + str(index), "artifact_store_root": str(inputs.store.root),
            "workspace_root": str(inputs.workspace), "feature_spec_ref": asdict(request.feature_spec_ref),
            "expected_check_ids": checks, "verification_identity": verifier.verification_identity(),
            "execution": {"role": "initial_patch", "continuation_input_ref": request_ref,
                "worker_configuration_ref": config_ref, "planning_target_selection": "synthetic_contract_fixture"}})
    suite_ref = save_once(tmp_path / "suite.json", {"schema_version": SUITE_SCHEMA,
        "scope": {"target_mod": "SyntheticMod"}, "execution_profile": profile, "cases": cases})
    profiles = []
    for label in ("a", "b"):
        selected = {**profile, "model": "synthetic-model-" + label}
        identity_ref = save_once(tmp_path / (label + ".identity.json"), {"name": selected["model"], "model": selected["model"],
            "base_url": selected["base_url"], "digest": hashlib.sha256(label.encode()).hexdigest(),
            "details": {"context_length": 49152}, "capabilities": ["completion", "tools"]})
        profiles.append({"profile_id": label, "profile": selected, "model_identity_ref": identity_ref})
    return {"suite_ref": suite_ref, "experiment_id": "offline-paired", "output_root": str(tmp_path / "prepared"),
        "partitions": {"training": ["case-0"], "validation": ["case-1"], "holdout": ["case-2"]}, "profiles": profiles}


def test_prepared_pair_uses_same_original_task_inputs_and_does_not_invent_scores(seed):
    result = prepare_patch_model_experiment(**seed)
    prepared = read_bound_json(result["experiment_ref"])
    assert result["planned_trial_denominator"] == 6 and result["distinct_task_denominator"] == 3
    assert prepared["split_task_denominators"] == {"training": 1, "validation": 1, "holdout": 1}
    assert prepared["training_performed"] is False and prepared["training_gain"] is None
    assert prepared["observed_trials_at_preparation"] == 0 and prepared["observed_task_success_rate"] is None
    assert all(row["protocol"] == row["compilation"] == row["behavior"] == "not_run" for row in prepared["cells"])
    assert all(row["action_quality"] == "not_evaluated" and row["performance"] == "not_measured" for row in prepared["cells"])
    for offset in (0, 2, 4):
        first, second = prepared["cells"][offset:offset+2]
        assert first["shared_input_sha256"] == second["shared_input_sha256"]
        a, b = first["arguments"], list(second["arguments"])
        for flag in ("--ollama-model", "--attempt-id"):
            b[b.index(flag)+1] = a[a.index(flag)+1]
        assert a == b
    selected = select_patch_experiment_cell(experiment_ref=result["experiment_ref"], cell_id=prepared["cells"][0]["cell_id"])
    assert selected["arguments"][0] == "continue-fresh-patch" and selected["model_calls"] == 0


@pytest.mark.parametrize("kind", ["overlap", "missing", "exposed_holdout", "budget", "duplicate_model"])
def test_invalid_partition_or_unfair_profile_is_rejected_before_prepared_output(seed, kind, tmp_path):
    if kind == "overlap":
        seed["partitions"]["holdout"] = ["case-0"]
    elif kind == "missing":
        seed["partitions"]["holdout"] = []
    elif kind == "budget":
        seed["profiles"][1]["profile"]["output_budget"] += 1
    elif kind == "duplicate_model":
        seed["profiles"][1] = deepcopy(seed["profiles"][0])
    else:
        suite = read_bound_json(seed["suite_ref"])
        suite["cases"][2]["prior_failure_observation_ref"] = {"path": "historical-exposure-record", "sha256": "f"*64}
        seed["suite_ref"] = save_once(tmp_path / "exposed-suite.json", suite)
    with pytest.raises(ValueError, match="EXPERIMENT_"):
        prepare_patch_model_experiment(**seed)
    assert not Path(seed["output_root"]).exists()


@pytest.mark.parametrize("kind", ["worker", "verifier", "profile", "experiment"])
def test_frozen_identity_drift_blocks_selection_and_cannot_shrink_check_denominator(seed, monkeypatch, kind):
    result = prepare_patch_model_experiment(**seed)
    frozen = read_bound_json(result["experiment_ref"])
    if kind == "worker":
        monkeypatch.setattr("src.observability.evaluation.patch_model_experiment.worker_implementation_identity", lambda: {})
    elif kind == "verifier":
        path = Path(frozen["tasks"][0]["verifier_factory_ref"]["path"])
        path.write_text(path.read_text()+"\n# changed\n", encoding="utf-8")
    elif kind == "profile":
        Path(frozen["profiles"][0]["model_identity_ref"]["path"]).write_text("{}", encoding="utf-8")
    else:
        path = Path(result["experiment_ref"]["path"])
        data = json.loads(path.read_text())
        data["tasks"][0]["expected_check_ids"].pop()
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        select_patch_experiment_cell(experiment_ref=result["experiment_ref"], cell_id=frozen["cells"][0]["cell_id"])


def test_existing_prepare_cli_selects_exact_frozen_experiment_cell_without_model(seed, capsys, tmp_path):
    input_path = tmp_path / "seed.json"
    input_path.write_text(json.dumps(seed), encoding="utf-8")
    assert main(["--prepare-experiment", str(input_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    frozen = read_bound_json(result["experiment_ref"])
    assert main(["--experiment", result["experiment_ref"]["path"], "--experiment-sha256", result["experiment_ref"]["sha256"],
        "--cell-id", frozen["cells"][0]["cell_id"]]) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["status"] == "prepared_cell_admitted" and selected["arguments"][0] == "continue-fresh-patch"


@pytest.mark.parametrize("change", ["trim_check_set", "drop_paired_cell"])
def test_rehashed_manifest_cannot_restate_fixed_checks_or_paired_denominator(seed, tmp_path, change):
    result = prepare_patch_model_experiment(**seed)
    frozen = read_bound_json(result["experiment_ref"])
    selected = frozen["cells"][0]["cell_id"]
    if change == "trim_check_set":
        frozen["tasks"][0]["expected_check_ids"].pop()
    else:
        frozen["cells"].pop()
        frozen["planned_trial_denominator"] -= 1
    altered = save_once(tmp_path / "altered-experiment.json", frozen)
    with pytest.raises(ValueError, match="EXPERIMENT_"):
        select_patch_experiment_cell(experiment_ref=altered, cell_id=selected)


def test_paired_cells_reach_same_production_serialized_prompt_with_only_model_changed(seed, monkeypatch, capsys):
    from src.mod_agent.cli import main as product_main

    result = prepare_patch_model_experiment(**seed)
    frozen = read_bound_json(result["experiment_ref"])
    requests = []

    def respond(request):
        assert request.url.host == "127.0.0.1" and request.url.port == 11434
        if request.method == "GET":
            assert request.url.path == "/api/tags"
            return httpx.Response(200, json={"models": [read_bound_json(p["model_identity_ref"]) for p in seed["profiles"]]}, request=request)
        assert request.method == "POST" and request.url.path == "/api/chat"
        requests.append(json.loads(request.content))
        raise httpx.ReadTimeout("Synthetic transport stop before any model response", request=request)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: transport.handle_request(request))
    for cell in frozen["cells"][:2]:
        chosen = select_patch_experiment_cell(experiment_ref=result["experiment_ref"], cell_id=cell["cell_id"])
        assert product_main(chosen["arguments"]) != 0
        actual = json.loads(capsys.readouterr().out)
        assert actual["patch_proposal_artifact"] is None and actual["execution_counts"]["apply"] == 0
    assert len(requests) == 2 and requests[0]["model"] != requests[1]["model"]
    normalized = deepcopy(requests[1])
    normalized["model"] = requests[0]["model"]
    assert normalized == requests[0]  # Actual native serializer, not an argument-only comparison.
