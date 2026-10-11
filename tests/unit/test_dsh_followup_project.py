"""New request lineage uses real Apply/Build owners; only compiler is substituted."""
import json
from pathlib import Path

import pytest

from scripts import dsh_deliver_run as delivery
from scripts import dsh_run_request as bridge
from tests.unit.test_dsh_deliver_run import _approve, retained  # noqa: F401


@pytest.fixture
def delivered(retained):  # noqa: F811
    base = json.loads(retained.config.read_text())
    limits = retained.config.parent / "limits.json"
    limits.write_text(json.dumps({"requirement_projection": 2, "requirement_findings": 2,
        "planning": 1, "initial_patch": 2, "repair": 2}))
    base["arguments"] += ["--settings", str(Path("config/settings.yaml").resolve()),
        "--local-ollama", "--ollama-model", "qwen3:4b-instruct", "--ollama-context-window", "32768",
        "--task-model-call-limit", "9", "--stage-model-call-limits", str(limits),
        "--confirm-isolated-write", "--allow-build"]
    retained.config.write_text(json.dumps(base))
    outcome = delivery.deliver_run(**retained.arguments, action="deliver", decision=_approve(retained))
    assert outcome["status"] == "delivered", outcome
    retained.outcome = outcome
    return retained


def prepare(case, description="把上次交付的行为改为新的需求"):
    return bridge.prepare_followup_task(execution_config=str(case.config), parent_run_id=case.case.request.run_id,
                                       description=description, delivery_root=str(case.delivery))


def test_followup_uses_applied_source_new_literal_request_and_original_authority(delivered):
    before = delivered.case.canonical.read_bytes()
    selected = prepare(delivered)
    _, options = bridge._configuration_arguments(selected)
    assert options["--target-project"] == str(delivered.target)
    assert options["--run-id"] != delivered.case.request.run_id
    assert options["--task-model-call-limit"] == "9"
    assert "--defer-approval" in options and "--allow-game-launch" not in options
    assert (Path(options["--target-project"]) / "Behavior.cs").read_bytes() == delivered.case.source_after
    assert delivered.case.canonical.read_bytes() == before
    assert bridge.task_execution_config(execution_config=str(delivered.config), run_id=options["--run-id"]) == selected
    argv = bridge.build_product_argv(execution_config=selected, description="把上次交付的行为改为新的需求")
    assert argv[-1] == "把上次交付的行为改为新的需求"
    assert len(delivered.calls) == 2
    with pytest.raises(ValueError, match="REQUEST_CHANGED"):
        bridge.build_product_argv(execution_config=selected, description="different")


@pytest.mark.parametrize("damage", ["source", "dll", "parent_config", "new_config", "new_request"])
def test_followup_recovery_rejects_current_source_and_bound_input_drift(delivered, damage):
    selected = Path(prepare(delivered))
    _, options = bridge._configuration_arguments(str(selected))
    binding = json.loads(selected.read_text())["followup_binding"]
    paths = {"source": delivered.target / "Behavior.cs", "dll": delivered.target / "bin" / "Example.dll",
             "parent_config": delivered.config, "new_config": selected,
             "new_request": Path(binding["request_ref"]["path"])}
    with paths[damage].open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError):
        bridge.task_execution_config(execution_config=str(delivered.config), run_id=options["--run-id"])


def test_awaiting_approval_cannot_be_used_as_delivered_source(retained):  # noqa: F811
    with pytest.raises(ValueError, match="DELIVERED_SOURCE_REQUIRED"):
        prepare(retained)
    assert retained.calls == []


def test_original_product_delivery_layout_uses_same_immutable_apply_build_chain(delivered):
    folder = delivered.root / "delivery"
    folder.mkdir()
    receipt = delivered.outcome["receipt"]
    for name, value in (("apply.json", receipt["apply_result"]), ("build.json", receipt["build_result"])):
        (folder / name).write_text(json.dumps(value))
    (folder / "result.json").write_text(json.dumps({"status": "delivered", "delivery_complete": True,
        "execution_refs": [bridge._file_ref(folder / name) for name in ("apply.json", "build.json")]}))
    selected = bridge.prepare_followup_task(execution_config=str(delivered.config),
        parent_run_id=delivered.case.request.run_id, description="new literal requirement")
    _, options = bridge._configuration_arguments(selected)
    assert options["--target-project"] == str(delivered.target)
    assert bridge.build_product_argv(execution_config=selected, description="new literal requirement")[-1] == "new literal requirement"


def test_advance_prepared_followup_recovers_literal_request_without_new_allocation(delivered, monkeypatch):
    description = "继续新要求\n--task-model-call-limit 999 不作为参数"
    selected = prepare(delivered, description)
    _, options = bridge._configuration_arguments(selected)
    expected = bridge.build_product_argv(execution_config=selected, description=description)
    inputs = Path(selected).parent.parent
    original_allocations = sorted(path.name for path in inputs.iterdir())
    captured = []

    def original_cli(arguments):
        captured.append(arguments)
        print(json.dumps({"status": "awaiting_approval", "run_id": options["--run-id"]}))
        return 0

    monkeypatch.setattr(bridge.cli, "main", original_cli)
    monkeypatch.setattr(bridge, "prepare_new_task", lambda **_: pytest.fail("Cannot allocate during recovery"))
    result = bridge.advance_task(execution_config=str(delivered.config), run_id=options["--run-id"])
    assert result == {"status": "awaiting_approval", "run_id": options["--run-id"]}
    assert captured == [expected]
    assert expected[-1] == description
    assert expected[expected.index("--request-id") + 1] == options["--request-id"]
    assert expected[expected.index("--task-model-call-limit") + 1] == "9"
    assert sorted(path.name for path in inputs.iterdir()) == original_allocations


def test_advance_prepared_followup_rejects_parent_source_drift_before_cli(delivered, monkeypatch):
    selected = prepare(delivered)
    _, options = bridge._configuration_arguments(selected)
    delivered.case.target.write_bytes(b"changed after followup preparation")
    monkeypatch.setattr(bridge.cli, "main", lambda *_: pytest.fail("Changed source must not execute"))
    with pytest.raises(ValueError, match="APPLIED_SOURCE_CHANGED"):
        bridge.advance_task(execution_config=str(delivered.config), run_id=options["--run-id"])


def test_new_task_profile_and_workspace_preserve_original_parent_profile(delivered):
    original = delivered.config.read_bytes()
    new_profile = delivered.config.parent / "new-task-profile.json"
    value = json.loads(original)
    args = value["arguments"]
    args[args.index("--workspace-root") + 1] = str(delivered.config.parent / "next-runs")
    new_profile.write_text(json.dumps(value))
    selected = bridge.prepare_followup_task(execution_config=str(new_profile),
        parent_execution_config=str(delivered.config), parent_run_id=delivered.case.request.run_id,
        description="New requirement on delivered source", delivery_root=str(delivered.delivery))
    _, options = bridge._configuration_arguments(selected)
    assert options["--target-project"] == str(delivered.target)
    assert Path(selected).is_relative_to(delivered.config.parent / "next-runs")
    assert bridge.task_execution_config(execution_config=str(new_profile), run_id=options["--run-id"]) == selected
    assert delivered.config.read_bytes() == original
    delivered.config.write_bytes(original + b" ")
    with pytest.raises(ValueError):
        bridge.build_product_argv(execution_config=selected, description="New requirement on delivered source")
