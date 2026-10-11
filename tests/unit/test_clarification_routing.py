"""Clarification replay preserves intent, costs and the existing product owner."""
import json
from pathlib import Path

import pytest

from scripts import dsh_request_routing as routing
from scripts import dsh_run_request as bridge
from src.mod_agent.planning.task_intent import (
    ASSESSMENT_FIELDS,
    intent_schema,
    validate_assessed_intent,
)
from tests.unit import test_dsh_request_routing as routing_tests
from tests.unit.test_dsh_request_routing import Model, capture_product, decision
from tests.unit.test_dsh_run_request import execution_config  # noqa: F401

profile = routing_tests.profile


def call(profile, value, text, **kwargs):
    model = value if isinstance(value, Model) else Model(value)
    return routing.run_natural_request(execution_config=str(profile), description=text, llm=model,
        identity_reader=lambda *_: {"model": model.model, "digest": "a" * 64},
        conversation_id="session", **kwargs)


def pending(profile, **kwargs):
    return call(profile, decision("clarify", question="修改已有工程还是新建？"), "启用开关默认关闭", **kwargs)


def test_answer_dispatches_full_transcript_once_and_keeps_separate_cost(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    first = pending(profile, turn_id="first")
    second = call(profile, decision("new_project", name="开关"), "新建，改为默认开启", turn_id="answer",
                  clarification_for=first["route_id"])
    assert second["status"] == "awaiting_approval"
    assert len(dispatched) == 1
    assert all(text in dispatched[0][-1] for text in ("启用开关默认关闭", "改为默认开启", "助手澄清问题仅为上下文"))
    assert second["cumulative_routing_calls"] == 2
    assert second["cumulative_routing_usage"] == {"input_tokens": 200, "output_tokens": 40}
    assert second["budget"]["product_new_task_call_limit"] == 9
    assert second["cumulative_routing_elapsed_seconds"] >= second["routing_elapsed_seconds"]
    assert first["clarification_id"] == first["route_id"]
    replay = call(profile, Model(None), "新建，改为默认开启", turn_id="answer", clarification_for=first["route_id"])
    assert replay == second and len(dispatched) == 1
    repeated = call(profile, Model(None), "新建，改为默认开启", turn_id="repeat", clarification_for=first["route_id"])
    assert repeated == second and len(dispatched) == 1


def test_automatic_pending_multiple_questions_keep_original_and_answers(profile):
    first = pending(profile)
    second = call(profile, decision("clarify", question="叫什么名字？"), "新建")
    third = call(profile, decision("new_project", name="开关"), "开关", preview_only=True,
                 clarification_for=second["route_id"])
    request = json.loads(Path(third["request_ref"]["path"]).read_text(encoding="utf-8"))
    assert [item["content"] for item in request["conversation_turns"]] == [
        "启用开关默认关闭", first["question"], "新建", second["question"], "开关"]
    assert third["cumulative_routing_calls"] == 3


def test_preview_explicit_chain_never_allocates_or_becomes_automatic_pending(profile, monkeypatch):
    monkeypatch.setattr(bridge, "prepare_new_task", lambda **_: pytest.fail("preview allocated"))
    first = pending(profile, preview_only=True)
    assert first["clarification_id"] is None
    second = call(profile, decision("new_project", name="新建"), "新建", preview_only=True,
                  clarification_for=first["route_id"])
    assert second["status"] == "route_selected"
    assert "启用开关默认关闭" in json.loads(Path(second["request_ref"]["path"]).read_text(encoding="utf-8"))["effective_description"]
    third = call(profile, decision("clarify", question="哪个？"), "另外一个需求")
    assert json.loads(Path(third["request_ref"]["path"]).read_text(encoding="utf-8"))["effective_description"] == "另外一个需求"


def test_cross_session_clarification_cannot_bind(profile):
    first = pending(profile)
    with pytest.raises(ValueError, match="NOT_IN_CONVERSATION"):
        routing.run_natural_request(execution_config=str(profile), description="新建",
                                    conversation_id="other", clarification_for=first["route_id"])


def test_configuration_drift_requires_new_confirmation_without_model(profile):
    first = pending(profile)
    profile.write_text(profile.read_text(encoding="utf-8") + " ", encoding="utf-8")
    model = Model(None)
    second = call(profile, model, "新建", clarification_for=first["route_id"])
    assert second["status"] == "needs_clarification" and second["reason"] == "CLARIFICATION_CONTEXT_CHANGED"
    assert not model.calls and second["cumulative_routing_calls"] == 1
    third = call(profile, decision("new_project", name="开关"), "确认当前配置", preview_only=True,
                 clarification_for=second["route_id"])
    assert third["status"] == "route_selected"


def test_turn_reuse_changed_input_rejected(profile):
    pending(profile, turn_id="same")
    with pytest.raises(ValueError, match="DIFFERENT_INPUT"):
        call(profile, Model(None), "不同输入", turn_id="same")


def test_unknown_failed_provider_usage_is_not_zero_and_new_turn_can_retry(profile):
    first = pending(profile)
    model = Model(None, during=lambda: (_ for _ in ()).throw(RuntimeError("provider disconnected")))
    failed = call(profile, model, "新建", turn_id="fail", clarification_for=first["route_id"])
    assert failed["status"] == "routing_failed"
    assert failed["cumulative_routing_usage"] == {"input_tokens": None, "output_tokens": None}
    retry = call(profile, decision("new_project", name="开关"), "新建", turn_id="retry",
                 clarification_for=first["route_id"], preview_only=True)
    assert retry["status"] == "route_selected" and retry["cumulative_routing_calls"] == 3


def test_dispatch_failure_never_allocates_again(profile, monkeypatch):
    first = pending(profile)
    calls = []
    def fail(argv):
        calls.append(argv)
        raise RuntimeError("owner outcome unavailable")
    monkeypatch.setattr(bridge.cli, "main", fail)
    failed = call(profile, decision("new_project", name="开关"), "新建", clarification_for=first["route_id"])
    repeated = call(profile, Model(None), "新建", clarification_for=first["route_id"])
    assert repeated == failed and len(calls) == 1 and failed["status"] == "dispatch_failed"


def test_changed_record_rejected_before_dispatch(profile):
    first = pending(profile)
    Path(first["request_ref"]["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="RECORD_CHANGED"):
        call(profile, Model(None), "新建")


def test_indeterminate_claim_does_not_claim_process_is_live(profile):
    first = pending(profile, turn_id="same")
    (Path(first["routing_record_path"]).parent / "conversation_receipt.json").unlink()
    result = pending(profile, turn_id="same")
    assert result["status"] == "routing_indeterminate"
    assert result["process_liveness"] == "unknown" and result["routing_model_calls_reserved"] == 0


def test_continuation_actual_result_ref_without_original_result(profile, monkeypatch):
    run_root = profile.parent / "runs/prior"
    run_root.mkdir(parents=True)
    manifest = {"request": "原始需求", "target_project": "Example"}
    (run_root / "run_manifest.json").write_text(json.dumps(manifest))
    continuation = run_root / "continuations/one/result.json"
    continuation.parent.mkdir(parents=True)
    continuation.write_text(json.dumps({"status": "blocked"}))
    ref = bridge._file_ref(continuation)
    monkeypatch.setattr(bridge, "task_execution_config", lambda **_: str(profile))
    monkeypatch.setattr(bridge, "inspect_run", lambda **_: {"run_root": str(run_root), "manifest": manifest,
        "result": {"status": "blocked"}, "continuation": {"result_ref": ref}})
    context, bindings = routing.routing_context(execution_config=str(profile), active_run_id="prior")
    assert context["tasks"][0]["status"] == "blocked" and bindings["active_result_ref"] == ref


def test_verified_delivered_resume_is_read_only(profile, monkeypatch):
    monkeypatch.setattr(routing, "routing_context", lambda **_: ({"projects": [{"id": "prior"}],
        "tasks": [{"id": "prior", "status": "delivered"}], "active_task_id": "prior"},
        {"active_delivery_refs": [{"path": "verified", "sha256": "a" * 64}]}))
    monkeypatch.setattr(bridge, "advance_task", lambda **_: pytest.fail("already delivered"))
    result = call(profile, decision("resume_task", target="prior"), "继续", active_run_id="prior")
    assert result["status"] == "delivered" and result["product_result"]["read_only"]
    assert not result["product_owner_invoked"]


def test_preparation_failure_is_side_effect_unknown_and_never_reallocated(profile, monkeypatch):
    first = pending(profile)
    allocations = []
    def prepare(**kwargs):
        allocations.append(kwargs)
        raise RuntimeError("partial allocation")
    monkeypatch.setattr(bridge, "prepare_new_task", prepare)
    failed = call(profile, decision("new_project", name="开关"), "新建", clarification_for=first["route_id"])
    repeated = call(profile, Model(None), "新建", clarification_for=first["route_id"])
    assert failed == repeated and failed["status"] == "dispatch_failed" and len(allocations) == 1


def test_whole_valid_other_conversation_receipt_cannot_be_transplanted(profile):
    first = pending(profile, turn_id="one")
    other = routing.run_natural_request(execution_config=str(profile), description="其他需求",
        conversation_id="other", turn_id="one", llm=Model(decision("clarify", question="哪个？")),
        identity_reader=lambda *_: {"model": Model.model, "digest": "a" * 64})
    destination = Path(first["routing_record_path"]).parent / "conversation_receipt.json"
    source = Path(other["routing_record_path"]).parent / "conversation_receipt.json"
    destination.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="IDENTITY_CHANGED"):
        pending(profile, turn_id="one")


def test_unknown_transport_does_not_become_measured_zero(profile):
    result = pending(profile)
    assert result["routing_transport_calls"] is None
    assert result["cumulative_routing_transport_calls"] is None
    assert result["cumulative_routing_transport_calls_known_subtotal"] == 0
    assert "reserved" in result["cumulative_routing_calls_scope"]
    assert result["budget"]["conversation_reserved_routing_plus_new_product_maximum"] == 10


@pytest.mark.parametrize("flag", ASSESSMENT_FIELDS)
def test_each_reported_ambiguity_overrides_native_dispatch_in_one_call(profile, monkeypatch, flag):
    monkeypatch.setattr(bridge, "prepare_new_task", lambda **_: pytest.fail("ambiguous dispatch"))
    native = {"assessment": {key: key == flag for key in ASSESSMENT_FIELDS},
              "decision": decision("new_project", name="Example")}
    model = Model(native)
    result = call(profile, model, "具有待澄清分支的需求")
    assert result["status"] == "needs_clarification" and len(model.calls) == 1
    assert result["decision"]["action"] == "clarify" and result["question"]
    assert result["assessment"][flag] is True
    assert result["intent_provenance"]["native_decision"] == native["decision"]
    assert result["intent_provenance"]["decision_overridden"] is True
    saved = json.loads((Path(result["routing_record_path"]).parent / "selection.json").read_text(encoding="utf-8"))
    assert saved["intent_provenance"] == result["intent_provenance"]
    assert result["routing_protocol"] == "task-intent.v3"


def test_reported_ambiguity_with_native_clarification_preserves_question(profile):
    native = {"assessment": {key: True for key in ASSESSMENT_FIELDS},
              "decision": decision("clarify", question="先处理哪个目标？")}
    result = call(profile, Model(native), "需要明确选择")
    assert result["question"] == "先处理哪个目标？"
    assert result["intent_provenance"]["decision_overridden"] is False


@pytest.mark.parametrize("assessment", [
    {}, {key: "false" for key in ASSESSMENT_FIELDS},
    {key: 0 for key in ASSESSMENT_FIELDS},
    {**{key: False for key in ASSESSMENT_FIELDS}, "extra": False},
])
def test_malformed_assessment_never_dispatches(profile, assessment):
    result = call(profile, Model({"assessment": assessment, "decision": decision("new_project", name="A")}), "需求")
    assert result["status"] == "routing_failed" and not result["product_owner_invoked"]
    assert result["reason"] == "TASK_INTENT_ASSESSMENT_INVALID"


def test_resolved_assessment_allows_corrected_action_instead_of_permanent_clarification(profile):
    first = call(profile, Model({"assessment": {key: True for key in ASSESSMENT_FIELDS},
        "decision": decision("clarify", question="先处理哪一个？")}), "初始需求")
    corrected = call(profile, Model(decision("new_project", name="A")), "更正：仅新建，原任务以后再做",
                     clarification_for=first["route_id"], preview_only=True)
    assert corrected["status"] == "route_selected"
    assert not any(corrected["assessment"][key] for key in ASSESSMENT_FIELDS)
    assert corrected["decision"]["action"] == "new_project"


def test_assessment_protocol_retains_action_target_validation():
    with pytest.raises(ValueError, match="TARGET_NOT_AVAILABLE"):
        validate_assessed_intent({"assessment": {"catalogue_roles": {}, **{key: False for key in ASSESSMENT_FIELDS}},
            "decision": decision("modify_project", target="unbound")}, {"projects": [], "tasks": []})


def test_active_project_name_comes_from_verified_initialization_receipt(profile):
    selected = bridge.prepare_new_task(execution_config=str(profile), description="原需求", project_name="显示名称")
    _, options = bridge._configuration_arguments(selected)
    context, bindings = routing.routing_context(execution_config=str(profile), active_run_id=options["--run-id"])
    assert context["projects"][-1]["name"] == "显示名称"
    receipt_ref = bridge.read_json_object(selected)["new_project_binding"]["receipt_ref"]
    assert bindings["active_project_initialization_ref"] == receipt_ref
    Path(receipt_ref["path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        routing.routing_context(execution_config=str(profile), active_run_id=options["--run-id"])


def test_new_turn_correction_to_resolved_clarification_is_recorded_rejected(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    first = pending(profile)
    delivered = call(profile, decision("new_project", name="A"), "新建", turn_id="answer",
                     clarification_for=first["route_id"])
    model = Model(None)
    corrected = call(profile, model, "更正：修改已有工程", turn_id="correction",
                     clarification_for=first["route_id"])
    assert corrected["status"] == "routing_rejected"
    assert corrected["reason"] == "CLARIFICATION_ALREADY_RESOLVED_NEW_INPUT"
    assert corrected != delivered and not corrected["product_owner_invoked"]
    assert corrected["routing_model_calls_reserved"] == 0 and not model.calls and len(dispatched) == 1
    request = json.loads(Path(corrected["request_ref"]["path"]).read_text(encoding="utf-8"))
    assert request["description"] == "更正：修改已有工程"
    assert json.loads(Path(corrected["routing_record_path"]).read_text(encoding="utf-8")) == corrected
    assert call(profile, Model(None), "更正：修改已有工程", turn_id="correction",
                clarification_for=first["route_id"]) == corrected


def test_new_turn_same_answer_with_changed_binding_does_not_replay_old_success(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    first = pending(profile)
    call(profile, decision("new_project", name="A"), "新建", clarification_for=first["route_id"])
    profile.write_text(profile.read_text(encoding="utf-8") + " ", encoding="utf-8")
    result = call(profile, Model(None), "新建", clarification_for=first["route_id"])
    assert result["status"] == "routing_rejected" and len(dispatched) == 1
    assert result["reason"] == "CLARIFICATION_ALREADY_RESOLVED_NEW_INPUT"


def assessed_roles(roles, selected):
    return {"assessment": {"catalogue_roles": roles, **{key: False for key in ASSESSMENT_FIELDS}},
            "decision": selected}


def test_role_conflict_question_names_target_without_inventing_user_conflict(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    model = Model(assessed_roles({"configured_project":"reference_only"},
                                decision("modify_project", target="configured_project")))
    result = call(profile, model, "我不想每次改 config 都重启游戏，希望配置保存后自动生效。", turn_id="initial")
    assert result["status"] == "needs_clarification" and not dispatched
    assert result["product_execution_started"] is False and result["product_owner_invoked"] is False
    assert "Example" in result["question"] and "仅作参考" in result["question"]
    assert "不同工程" not in result["question"] and "多个工程" not in result["question"]
    assert result["assessment"]["catalogue_roles"]["configured_project"] == "reference_only"
    assert result["intent_provenance"]["native_decision"]["action"] == "modify_project"
    assert result["intent_provenance"]["role_gate_reasons"] == ["selected_catalogue_target_not_current"]
    assert len(model.calls) == 1


def test_role_conflict_confirmation_reenters_normal_routing_once(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    original = "配置保存后自动生效，保留原有面板和默认值。"
    first = call(profile, assessed_roles({"configured_project":"reference_only"},
        decision("modify_project",target="configured_project")), original, turn_id="initial")
    first_bytes = Path(first["routing_record_path"]).read_bytes()
    answer = "是，修改 Example，不是仅作参考。"
    resolved = call(profile, decision("modify_project",target="configured_project"), answer,
        turn_id="confirmed",clarification_for=first["route_id"])
    assert resolved["status"] == "awaiting_approval" and len(dispatched) == 1
    assert original in dispatched[0][-1] and answer in dispatched[0][-1]
    assert "--defer-approval" in dispatched[0]
    assert resolved["cumulative_routing_calls"] == 2
    assert resolved["cumulative_routing_usage"] == {"input_tokens":200,"output_tokens":40}
    assert first_bytes == Path(first["routing_record_path"]).read_bytes()
    replay = call(profile, Model(None), answer,turn_id="confirmed",clarification_for=first["route_id"])
    assert replay == resolved and len(dispatched) == 1


def test_role_conflict_stays_blocked_when_followup_model_still_contradicts(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    native = assessed_roles({"configured_project":"reference_only"},
        decision("modify_project",target="configured_project"))
    first = call(profile,native,"配置保存自动生效",turn_id="initial")
    second = call(profile,native,"是，修改 Example",turn_id="answer",clarification_for=first["route_id"])
    assert second["status"] == "needs_clarification" and not dispatched
    assert second["assessment"]["catalogue_roles"]["configured_project"] == "reference_only"
    assert second["product_owner_invoked"] is False


def test_role_conflict_question_does_not_override_a_later_new_project_choice(profile, monkeypatch):
    dispatched = capture_product(monkeypatch)
    first = call(profile,assessed_roles({"configured_project":"reference_only"},
        decision("modify_project",target="configured_project")),"配置保存自动生效",turn_id="initial")
    second = call(profile,assessed_roles({"configured_project":"reference_only"},
        decision("new_project",name="SeparatePanel")),"Example 只作参考，请另建 SeparatePanel。",
        turn_id="answer",clarification_for=first["route_id"])
    assert second["status"] == "awaiting_approval" and len(dispatched) == 1
    argv = dispatched[0]
    assert Path(argv[argv.index("--target-project")+1]) != profile.parent / "Example"


def test_role_conflict_preserves_real_multiple_target_question():
    selected, provenance = validate_assessed_intent(assessed_roles(
        {"a":"current_target","b":"current_target"},decision("modify_project",target="a")),
        {"projects":[{"id":"a","name":"A"},{"id":"b","name":"B"}],"tasks":[]})
    assert selected["action"] == "clarify" and "不同工程" in selected["clarification"]
    assert "multiple_current_targets" in provenance["role_gate_reasons"]


@pytest.mark.parametrize("roles,selected,reason", [
    ({"a": "current_target", "b": "current_target"}, decision("modify_project", target="a"), "multiple_current_targets"),
    ({"a": "unresolved_candidate", "b": "not_referenced"}, decision("modify_project", target="a"), "unresolved_target_candidate"),
    ({"a": "current_target", "b": "not_referenced"}, decision("modify_project", target="b"), "decision_target_conflicts_with_current_reference"),
    ({"a": "current_target", "b": "not_referenced"}, decision("resume_task", target="b"), "decision_target_conflicts_with_current_reference"),
    ({"a": "current_target", "b": "requested_new_name"}, decision("new_project", name="New"), "new_project_discards_current_existing_target"),
])
def test_roles_force_clarification_even_when_all_model_flags_are_false(roles, selected, reason):
    context = {"projects": [{"id": "a"}, {"id": "b"}], "tasks": [{"id": "a"}, {"id": "b"}]}
    chosen, provenance = validate_assessed_intent(assessed_roles(roles, selected), context)
    assert chosen["action"] == "clarify" and chosen["clarification"]
    assert provenance["decision_overridden"] and reason in provenance["role_gate_reasons"]
    assert provenance["native_decision"] == selected


@pytest.mark.parametrize("action", ["modify_project", "resume_task"])
@pytest.mark.parametrize("role", ["excluded_or_retracted", "reference_only", "not_referenced", "requested_new_name"])
def test_selected_catalogue_object_requires_current_target_role(action, role):
    selected = decision(action, target="a")
    chosen, provenance = validate_assessed_intent(assessed_roles({"a": role}, selected),
        {"projects": [{"id": "a"}], "tasks": [{"id": "a"}]})
    assert chosen["action"] == "clarify"
    assert provenance["decision_overridden"]
    assert "selected_catalogue_target_not_current" in provenance["role_gate_reasons"]
    assert provenance["native_decision"] == selected


@pytest.mark.parametrize("action", ["modify_project", "resume_task"])
def test_selected_current_catalogue_target_can_dispatch(action):
    selected = decision(action, target="a")
    chosen, provenance = validate_assessed_intent(assessed_roles({"a": "current_target"}, selected),
        {"projects": [{"id": "a"}], "tasks": [{"id": "a"}]})
    assert chosen == selected
    assert not provenance["decision_overridden"] and not provenance["role_gate_reasons"]


def test_task_outside_project_catalogue_retains_existing_resume_contract():
    selected = decision("resume_task", target="task-only")
    chosen, provenance = validate_assessed_intent(assessed_roles({"a": "not_referenced"}, selected),
        {"projects": [{"id": "a"}], "tasks": [{"id": "task-only"}]})
    assert chosen == selected and not provenance["decision_overridden"]
    with pytest.raises(ValueError, match="TARGET_NOT_AVAILABLE"):
        validate_assessed_intent(assessed_roles({"a": "not_referenced"}, selected),
            {"projects": [{"id": "a"}], "tasks": []})


@pytest.mark.parametrize("roles,selected", [
    ({"a": "current_target", "b": "excluded_or_retracted"}, decision("modify_project", target="a")),
    ({"a": "current_target", "b": "requested_new_name"}, decision("modify_project", target="a")),
    ({"a": "reference_only", "b": "requested_new_name"}, decision("new_project", name="New")),
    ({"a": "not_referenced", "b": "not_referenced"}, decision("new_project", name="New")),
])
def test_roles_allow_single_project_correction_rename_and_new_project(roles, selected):
    chosen, provenance = validate_assessed_intent(assessed_roles(roles, selected),
        {"projects": [{"id": "a"}, {"id": "b"}], "tasks": []})
    assert chosen == selected and not provenance["decision_overridden"]


@pytest.mark.parametrize("roles", [{}, {"a": "current_target", "unbound": "not_referenced"}, {"a": True}, {"a": "invented"}])
def test_role_map_must_cover_exact_caller_catalogue(roles):
    with pytest.raises(ValueError, match="PROJECT_ROLES_INVALID"):
        validate_assessed_intent(assessed_roles(roles, decision("new_project", name="New")),
                                {"projects": [{"id": "a"}], "tasks": []})


def test_catalogue_roles_schema_precedes_flags_after_provider_key_sorting():
    schema = json.loads(json.dumps(intent_schema({"projects": [{"id": "b"}, {"id": "a"}]}), sort_keys=True))
    properties = schema["properties"]["assessment"]["properties"]
    assert list(properties)[0] == "catalogue_roles"
    assert set(properties["catalogue_roles"]["properties"]) == {"a", "b"}
    assert properties["catalogue_roles"]["additionalProperties"] is False


def test_latest_literal_answer_is_separate_from_complete_conversation_history(profile):
    first = pending(profile)
    second = call(profile, decision("clarify", question="要继续修改还是另建？"), "先考虑修改")
    model = Model(decision("new_project", name="独立工程"))
    latest = "更正：另建独立工程，原默认值要求保留"
    result = call(profile, model, latest, preview_only=True, clarification_for=second["route_id"])
    assert result["status"] == "route_selected" and len(model.calls) == 1
    payload = json.loads(model.calls[0][0][-1].content)
    assert payload["current_user_message"] == latest
    assert [row["content"] for row in payload["conversation_turns"]] == [
        "启用开关默认关闭", first["question"], "先考虑修改", second["question"], latest]
    assert "启用开关默认关闭" in payload["request"]
    assert "先考虑修改" in payload["request"] and latest in payload["request"]
