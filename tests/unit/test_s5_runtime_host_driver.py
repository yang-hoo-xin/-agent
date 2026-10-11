import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

PATH = Path(__file__).resolve().parents[2] / "artifacts/eval_driven_20261005/benchmark10/S5/host/runtime-driver-v1/driver.py"
SPEC = importlib.util.spec_from_file_location("s5_host_driver", PATH)
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "clone"
    config_root = root / "BepInEx/config"
    config_root.mkdir(parents=True)
    cfg = config_root / "benchmark.gtfo.livepanel.cfg"
    cfg.write_bytes(b"original-config")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"selected_actions": [dict(id=i, operation=o, visible=v, caption=c, width=w) for i, o, v, c, w in driver._FIXED]}))
    obj = driver.HostActionDriver(game_root=root, config_path=cfg, subject_config_ref=driver.file_ref(cfg),
        action_manifest_ref=driver.file_ref(manifest), session_id="session-current", owner_pid=456,
        artifact_directory=tmp_path / "artifacts")
    evidence = tmp_path / "baseline-evidence.bin"
    evidence.write_bytes(b"offline-test-baseline")
    obj.start(user_go=True, baseline_evidence_ref=driver.file_ref(evidence))
    return obj, tmp_path


def request(obj, action_id="ordinary_save_1"):
    item = obj.actions[action_id]
    expected = {key: item[key] for key in ("visible", "caption", "width")}
    return dict(kind="action_request", session_id=obj.session_id, action_id=action_id,
                operation=item["operation"], config_path=str(obj.config_path), expected=expected,
                config_utf8=driver._config_text(expected), window_ms=2500)


def perform(setup, payload=None, **binding_changes):
    obj, root = setup
    payload = payload or request(obj)
    record = root / (uuid4().hex + ".json")
    record.write_text(json.dumps(payload), encoding="utf-8")
    binding = dict(owner_pid=obj.owner_pid, session_id=obj.session_id, record_ref=driver.file_ref(record))
    binding.update(binding_changes)
    return obj.process_action(payload, record_binding=binding)


def test_exact_write_receipt_and_control_order(setup):
    obj, _ = setup
    result = perform(setup)
    assert result["result"]["status"] == "committed"
    assert obj.config_path.read_bytes() == request(obj)["config_utf8"].encode()
    receipt = json.loads(driver.read_ref(result["result"]["receipt_ref"]))
    assert receipt["write_started_perf_counter_ns"] <= receipt["write_completed_perf_counter_ns"]
    assert receipt["config_sha256"] == driver.file_ref(obj.config_path)["sha256"]
    control = json.loads(obj.control_path.read_bytes())
    assert control["receipt_ref"] == result["result"]["receipt_ref"]
    assert control["session_id"] == "session-current"


@pytest.mark.parametrize("change", [
    {"session_id": "session-foreign"}, {"action_id": "../../outside"},
    {"config_path": "../benchmark.gtfo.livepanel.cfg"},
    {"operation": "delete"}, {"config_utf8": "arbitrary"},
    {"expected": {"visible": 1, "caption": "AMMO", "width": 144}},
])
def test_unknown_or_modified_requests_never_write(setup, change):
    obj, _ = setup
    payload = {**request(obj), **change}
    with pytest.raises(driver.DriverError):
        perform(setup, payload)
    assert obj.config_path.read_bytes() == b"original-config"


def test_same_destination_via_parent_traversal_rejected(setup):
    obj, _ = setup
    path = str(obj.config_root / ".." / "config" / obj.config_path.name)
    with pytest.raises(driver.DriverError, match="PATH"):
        perform(setup, {**request(obj), "config_path": path})
    assert obj.config_path.read_bytes() == b"original-config"


@pytest.mark.parametrize("binding", [{"owner_pid": 457}, {"session_id": "session-foreign"}])
def test_wrong_current_run_binding_rejected(setup, binding):
    with pytest.raises(driver.DriverError, match="BINDING"):
        perform(setup, **binding)


def test_duplicate_returns_original_receipt_without_reapplying(setup):
    obj, _ = setup
    first = perform(setup)
    obj.config_path.write_bytes(b"later legitimate state")
    control_before = obj.control_path.read_bytes()
    second = perform(setup)
    assert second["reused"] is True
    assert second["result_ref"] == first["result_ref"]
    assert second["result"]["receipt_ref"] == first["result"]["receipt_ref"]
    assert obj.config_path.read_bytes() == b"later legitimate state"
    assert obj.control_path.read_bytes() == control_before


def test_duplicate_tampered_receipt_is_rejected(setup):
    first = perform(setup)
    Path(first["result"]["receipt_ref"]["path"]).write_bytes(b"tampered")
    with pytest.raises(driver.DriverError, match="HASH"):
        perform(setup)


def test_atomic_replace_failure_preserves_config_and_cleans_only_own_temp(setup, monkeypatch):
    obj, _ = setup
    for action in list(obj.actions)[:3]:
        assert perform(setup, request(obj, action))["result"]["status"] == "committed"
    before = obj.config_path.read_bytes()
    unrelated = obj.config_root / "someone-elses.tmp"
    unrelated.write_bytes(b"keep")
    original_replace = driver.os.replace
    def broken(source, target):
        if Path(target) == obj.config_path:
            raise OSError("atomic replacement refused")
        return original_replace(source, target)
    monkeypatch.setattr(driver.os, "replace", broken)
    result = perform(setup, request(obj, "replace_repeat_0"))
    assert result["result"]["status"] == "failed"
    assert obj.config_path.read_bytes() == before
    assert unrelated.read_bytes() == b"keep"
    assert not list(obj.config_root.glob(".*.s5-*.tmp"))
    assert any(Path(ref["path"]).name == "write-intent.json" for ref in result["result"]["artifact_refs"])
    duplicate = perform(setup, request(obj, "replace_repeat_0"))
    assert duplicate["reused"] and duplicate["result"]["status"] == "failed"


def test_control_replace_failure_does_not_repeat_successful_config_write(setup, monkeypatch):
    obj, _ = setup
    original_replace = driver.os.replace
    def broken(source, target):
        if Path(target) == obj.control_path:
            raise OSError("control replacement refused")
        return original_replace(source, target)
    monkeypatch.setattr(driver.os, "replace", broken)
    first = perform(setup)
    assert first["result"]["status"] == "failed"
    assert first["result"]["receipt_ref"]
    obj.config_path.write_bytes(b"root restoration")
    second = perform(setup)
    assert second["reused"] and second["result"]["status"] == "failed"
    assert obj.config_path.read_bytes() == b"root restoration"


def test_no_start_without_explicit_user_go(setup):
    obj, root = setup
    before = obj.control_path.read_bytes()
    with pytest.raises(driver.DriverError, match="USER_GO"):
        obj.start(user_go=False, baseline_evidence_ref=driver.file_ref(root / "baseline-evidence.bin"))
    assert obj.control_path.read_bytes() == before


def test_out_of_order_action_rejected(setup):
    obj, _ = setup
    with pytest.raises(driver.DriverError, match="PREVIOUS_ACTION"):
        perform(setup, request(obj, "replace_repeat_0"))
