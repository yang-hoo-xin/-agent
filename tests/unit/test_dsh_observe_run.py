"""A UI reply must release the original reader without fabricating runtime success."""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts import dsh_observe_run as bridge
from src.mod_agent.runtime.gtfo_automation import (
    GTFOOperatorCompletionRequest,
    _read_operator_completion,
    make_operator_completion_file_reader,
)


def test_page_response_completes_original_reader_and_keeps_unknown(tmp_path):
    request = GTFOOperatorCompletionRequest(
        request_id="operator_test", feature_id="feature_test", profile_id="profile_test",
        runtime_process_pid=4242, acceptance_criteria=("Restore position", "Preserve reload"),
        timeout_seconds=5, operator_guidance={"Restore position": "Observe the actual position"},
    )
    reader = make_operator_completion_file_reader(tmp_path, poll_interval_seconds=0.01)
    with ThreadPoolExecutor() as executor:
        future = executor.submit(_read_operator_completion, request=request, reader=reader)
        deadline = time.monotonic() + 2
        while not (tmp_path / "operator_test.request.json").exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        pending = bridge.pending_observations(tmp_path)
        shown = pending["requests"][0]
        result = bridge.submit_observations(tmp_path, {
            "request_id": shown["request_id"], "request_sha256": shown["request_sha256"],
            "observed_by": "tester", "observations": [
                {"status": "failed", "notes": "Position remained offset"},
                {"status": "not_observed", "notes": "Did not reload"},
            ],
        })
        completion = future.result(timeout=2)
    assert result["status"] == "submitted"
    assert result["runtime_success_claimed"] is False
    assert [row["status"] for row in completion.observations] == ["failed", "not_observed"]
    assert completion.semantic_consistency["status"] == "consistent"
    raw = (tmp_path / "operator_test.response.json").read_bytes()
    confirmation = json.loads((tmp_path / "operator_test.confirmation.json").read_text())
    assert confirmation["response_sha256"] == hashlib.sha256(raw).hexdigest()
    assert bridge.pending_observations(tmp_path)["requests"] == []
    with pytest.raises(ValueError, match="ALREADY_SUBMITTED"):
        bridge.submit_observations(tmp_path, {"request_id": "operator_test"})


def _exchange(tmp_path):
    from src.mod_agent.runtime.gtfo_automation import _operator_completion_exchange_payload
    request = GTFOOperatorCompletionRequest("operator_test", "feature_test", "profile_test", 4242,
                                            ("Restore position",), 60)
    path = tmp_path / "operator_test.request.json"
    path.write_text(json.dumps(_operator_completion_exchange_payload(request)), encoding="utf-8")
    return path, {"request_id": request.request_id, "request_sha256": request.to_dict()["request_sha256"],
                  "observed_by": "tester", "observations": [{"status": "failed", "notes": "offset"}]}


def test_general_runtime_deployment_forwards_page_exchange_to_original_runner(tmp_path, monkeypatch):
    from src.mod_agent import local_entry
    captured = {}
    monkeypatch.setattr(local_entry, "stagger_profile_from_settings", lambda _: None)
    def factory(settings, **kwargs):
        captured.update(kwargs)
        return lambda *_: {}
    monkeypatch.setattr(local_entry, "make_gtfo_runtime_evidence_factory_from_settings", factory)
    local_entry._make_deploying_runtime_evidence_factory(
        settings=object(), allow_game_launch=True, allow_game_directory_write=True,
        build_artifact_path=tmp_path / "build.dll", expected_artifact="build.dll",
        destination_path=tmp_path / "installed.dll", backup_directory=tmp_path / "backup",
        expected_destination_existed=False, expected_destination_sha256=None,
        operator_completion_directory=tmp_path / "exchange")
    assert callable(captured.get("operator_completion_reader"))


def test_manual_gameplay_profile_does_not_require_fabricated_product_log_marker(tmp_path):
    from src.mod_agent import local_entry
    from tests.unit.test_local_entry import _runtime_destination, _runtime_settings
    settings = _runtime_settings(tmp_path)
    settings.runtime.gtfo.acceptance_markers = {}
    settings.runtime.gtfo.operator_completion_required = True
    feature = {"acceptance_criteria": ["Press once toggles recoil and shows the new state.",
                                       "Holding the key does not toggle repeatedly."]}
    result = local_entry._runtime_profile_preflight_record(settings,
        runtime_plugin_destination=_runtime_destination(tmp_path), feature_spec=feature)
    assert result["acceptance_boundary"]["feature_spec_marker_criterion"] is None
    assert result["acceptance_boundary"]["remaining_acceptance_criteria_require_separate_observation"] == feature["acceptance_criteria"]
    assert result["capability_report"]["checks"]["explicit_launch_approval"]["allow_game_launch"] is False
    settings.runtime.gtfo.operator_completion_required = False
    with pytest.raises(local_entry.LocalEntryError):
        local_entry._runtime_profile_preflight_record(settings,
            runtime_plugin_destination=_runtime_destination(tmp_path), feature_spec=feature)


@pytest.mark.parametrize("fault", ["old_hash", "expired", "missing_criterion", "ambiguous", "path"])
def test_invalid_reply_never_publishes_confirmation(tmp_path, fault):
    path, response = _exchange(tmp_path)
    if fault == "old_hash":
        response["request_sha256"] = "0" * 64
    elif fault == "expired":
        os.utime(path, (time.time() - 120, time.time() - 120))
    elif fault == "missing_criterion":
        response["observations"] = []
    elif fault == "ambiguous":
        response["observations"][0]["status"] = "probably fine"
    else:
        response["request_id"] = "../outside"
    with pytest.raises(ValueError):
        bridge.submit_observations(tmp_path, response)
    assert not list(tmp_path.glob("*.confirmation.json"))
    assert not list(tmp_path.glob("*.response.json"))
