"""Dataset selection checks; no live provider and no invented qualification."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from src.mod_agent.evaluation.patch_task_suite import (
    TASKS,
    _checked_suite,
    prepare_source_task,
    reference,
    save_once,
    select_patch_task,
    task_cli_arguments,
)
from src.mod_agent.local_entry import (
    LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
    LocalOllamaInitialPatchProfileV1,
)
from src.mod_agent.model_qualification import SUITE_SCHEMA
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy


@pytest.fixture(scope="module")
def selected_case(tmp_path_factory):
    if not Path("C:/Program Files/dotnet/sdk/7.0.401/Roslyn/bincore/csc.dll").is_file():
        pytest.skip("The fixed local .NET 7 task environment is unavailable.")
    root = tmp_path_factory.mktemp("ps")
    source = Path(__file__).parents[1] / "fixtures/patch_eval/accurate_crosshair"
    profile = LocalOllamaInitialPatchProfileV1(profile_version=LOCAL_OLLAMA_PATCH_PROFILE_VERSION,
        base_url="http://127.0.0.1:11434", model="explicit-test-profile", context_window=49152,
        output_budget=4096, timeout_seconds=30).to_dict()
    policy = PatchAgentLoopPolicy(require_source_inspection=False, finalize_after_first_observation=False)
    case = prepare_source_task(definition=TASKS[0], source_root=source, output_root=root / "c1", policy=policy, profile=profile)
    # Only the selected real-source case is executed here. The other identities
    # are contract fixtures for denominator checks, not additional real tasks.
    others = []
    for i in (2, 3):
        other = deepcopy(case)
        other["case_id"] = f"unselected-contract-fixture-{i}"
        other["feature_spec_ref"]["feature_id"] = f"fixture-{i}"
        other["feature_spec_ref"]["artifact_hash"] = str(i) * 64
        others.append(other)
    suite = {"schema_version": SUITE_SCHEMA, "scope": {"target_mod": "AccurateCrosshair"},
             "execution_profile": profile, "cases": [case, *others]}
    return root, case, suite, save_once(root / "suite.json", suite)


def test_select_exact_case_reuses_production_preflight_and_existing_cli(selected_case, monkeypatch):
    root, case, _, suite_ref = selected_case
    monkeypatch.setattr("socket.socket.connect", lambda *_: pytest.fail("Task selection must not call any model."))
    request = select_patch_task(suite_ref=suite_ref, case_id=case["case_id"], attempt_id="selected-once")
    assert request.attempt_id == "selected-once"
    assert asdict(request.feature_spec_ref) == case["feature_spec_ref"]
    arguments = task_cli_arguments(suite_ref=suite_ref, case_id=case["case_id"], attempt_id="selected-once")
    assert arguments[0] == "continue-fresh-patch"
    assert arguments[arguments.index("--attempt-id") + 1] == "selected-once"
    assert arguments[arguments.index("--patch-worker-config") + 1] == case["execution"]["worker_configuration_ref"]["path"]
    assert not list((root / "c1/store/cr").glob("*.json"))


@pytest.mark.parametrize("change", ["duplicate_feature", "trim_checks", "different_profile"])
def test_scope_drift_or_trimmed_denominator_stops_before_execution(selected_case, change):
    root, case, original, _ = selected_case
    suite = deepcopy(original)
    if change == "duplicate_feature":
        suite["cases"][1]["feature_spec_ref"] = deepcopy(suite["cases"][0]["feature_spec_ref"])
    elif change == "trim_checks":
        suite["cases"][0]["expected_check_ids"].pop()
    else:
        suite["execution_profile"]["model"] = "another-model"
    selected = save_once(root / f"changed-{change}.json", suite)
    with pytest.raises(ValueError, match="PATCH_EVAL_"):
        select_patch_task(suite_ref=selected, case_id=case["case_id"], attempt_id="no-execution")


def test_unknown_case_is_not_guessed(selected_case):
    _, _, _, suite_ref = selected_case
    with pytest.raises(ValueError, match="PATCH_EVAL_CASE_NOT_FOUND"):
        select_patch_task(suite_ref=suite_ref, case_id="unknown", attempt_id="no-execution")
    assert _checked_suite(suite_ref)["schema_version"] == SUITE_SCHEMA
    assert reference(suite_ref["path"]) == suite_ref
