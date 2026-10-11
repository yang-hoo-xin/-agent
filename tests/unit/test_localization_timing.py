"""Clock, retention and material boundaries; every provider is an offline double."""
import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.libs.llm.agent_turn import AgentToolCall, AgentTurnResponse, AgentUsage
from src.mod_agent.evaluation import localization_timing as timing


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *_: pytest.fail("No model/network in localization tests"))


@pytest.fixture
def snapshot_source(tmp_path, monkeypatch):
    source = tmp_path / "snapshot-source"
    for name in ("src/mod_agent/evaluation/localization_timing.py", "scripts/run_localization_timing.py",
                 "src/libs/llm/agent_turn.py", "src/mod_agent/model_admission.py"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# controlled frozen-source fixture\n", encoding="utf-8")
    monkeypatch.setattr(timing, "SOURCE_ROOT", source)
    return source


def case(tmp_path, value=None):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(value or {"reason": "actual failure"}), encoding="utf-8")
    return {"case_id": "cb1-basic", "sample_id": "cb1", "arm": "basic", "documents": [{
        "material_id": "terminal", "name": "run_result.json", "bytes": path.stat().st_size,
        "material_ref": timing.file_ref(path)}]}


def identity(*_):
    return {"name": timing.PROFILE["model"], "model": timing.PROFILE["model"],
        "base_url": timing.PROFILE["base_url"], "digest": timing.PROFILE["digest"],
        "details": {"context_length": 32768}, "capabilities": ["tools", "completion"]}


def reply(content=None, calls=()):
    return AgentTurnResponse(provider="ollama_chat_local", model=timing.PROFILE["model"], content=content,
        tool_calls=calls, provider_state={"content": "", "tool_calls": [{"function": {
            "name": c.name, "arguments": c.arguments}} for c in calls]}, usage=AgentUsage(16, 8),
        raw_response={"prompt_eval_count": 16, "eval_count": 8, "load_duration": 1234567})


def final():
    return json.dumps({"status": "diagnosed", "cause": "actual failure",
        "evidence": [{"read_id": "read-1", "quote": "actual failure"}], "uncertainties": []})


class Clock:
    value = 0.0

    def now(self):
        return self.value


@pytest.mark.parametrize("before_read,after_read,late", [(7, 5, False), (100, 90, True), (7, 181, True)])
def test_catalog_clock_counts_selection_without_reset_at_first_read(tmp_path, before_read, after_read, late):
    selected = case(tmp_path)
    clock, requests, timeouts = Clock(), [], []

    def model_identity(*args):
        clock.value += 100
        return identity(*args)

    def complete(request):
        requests.append(request)
        if len(requests) == 1:
            clock.value += before_read
            return reply(calls=(AgentToolCall("call-1", "read_material", {"material_id": "terminal"}),))
        assert len(request.historical_tool_exchanges) == 1
        assert request.historical_tool_exchanges[0].tool_results[0].call_id == "call-1"
        clock.value += after_read
        return reply(final())

    def client_factory(timeout):
        if not timeouts:
            clock.value += 25  # Initial client setup, before catalog exposure.
        timeouts.append(timeout)
        return SimpleNamespace(complete_turn=complete)

    root = tmp_path / "cell"
    ref = timing.execute_case(selected, root, identity_reader=model_identity,
        client_factory=client_factory, clock=clock.now)
    result = json.loads(timing.read_exact(ref))
    assert result["status"] == ("timeout" if late else "submitted")
    assert result["diagnostic_started_monotonic"] == 125
    assert result["first_material_read_monotonic"] == 125 + before_read
    assert result["localization_seconds"] == before_read + after_read
    assert result["first_read_to_final_seconds"] == after_read
    assert timeouts == [180, 180 - before_read]
    assert (result["answer"] is None) is late
    assert result["calls"][0]["native_usage"] == {"input_tokens": 16, "output_tokens": 8}
    assert result["calls"][0]["native_load_duration_ns"] == 1234567
    assert json.loads((root / "first-read.json").read_text())["first_material_read_monotonic"] == 125 + before_read
    raw = (root / "first-final-response.json").read_bytes()
    with pytest.raises(FileExistsError):
        timing.execute_case(selected, root, identity_reader=model_identity,
            client_factory=lambda _: pytest.fail("Never repeat a finalized cell"))
    assert (root / "first-final-response.json").read_bytes() == raw


def test_large_nodes_are_shapes_without_silent_truncation_then_exact_child(tmp_path):
    data = {"important": {"reason": "actual failure"}, "other": "x" * 9000}
    selected = case(tmp_path, data)
    reader = timing.MaterialReader(selected["documents"])
    oversized = reader.charge(reader.read("terminal"))
    assert oversized["status"] == "body_not_returned_node_too_large"
    assert oversized["keys"] == ["important", "other"] and "value" not in oversized
    body = reader.charge(reader.read("terminal", "/important"))
    assert body["value"] == data["important"]
    with pytest.raises(ValueError, match="CITATION_NOT_RETURNED"):
        timing._admit_answer({"status": "diagnosed", "cause": "guess",
            "evidence": [{"read_id": "read-1", "quote": "actual failure"}], "uncertainties": []}, reader)


@pytest.mark.parametrize("value,quote", [
    ('Rejected "candidate".\n  Six\tlines.', 'Rejected "candidate".\n  Six\tlines.'),
    ('Rejected "candidate".\n  Six\tlines.', 'Rejected "candidate". Six lines.'),
    ({"details": ['Rejected "candidate".\n  Six lines.']}, 'Rejected "candidate". Six lines.'),
    ({"status": "failed", "count": 2}, '{"status":"failed","count":2}'),
])
def test_citation_accepts_returned_decoded_text_and_literal_json(tmp_path, value, quote):
    reader = timing.MaterialReader(case(tmp_path, value)["documents"])
    reader.charge(reader.read("terminal"))
    answer = {"status": "diagnosed", "cause": "Not semantically scored here",
        "evidence": [{"read_id": "read-1", "quote": quote}], "uncertainties": []}
    assert timing._admit_answer(answer, reader) == answer


def test_citation_cannot_join_fields_or_quote_a_field_outside_the_returned_node(tmp_path):
    reader = timing.MaterialReader(case(tmp_path, {"shown": {"left": "alpha", "right": "omega"},
        "hidden": "unreturned secret"})["documents"])
    reader.charge(reader.read("terminal", "/shown"))
    for quote in ("alpha omega", "unreturned secret", "alpha unreturned secret"):
        with pytest.raises(ValueError, match="CITATION_NOT_RETURNED"):
            timing._admit_answer({"status": "diagnosed", "cause": "guess",
                "evidence": [{"read_id": "read-1", "quote": quote}], "uncertainties": []}, reader)


def test_material_scope_hash_and_actual_read_budget(tmp_path):
    selected = case(tmp_path)
    reader = timing.MaterialReader(selected["documents"], budget={**timing.BUDGET, "material_reads": 1})
    with pytest.raises(KeyError):
        reader.read("host-rubric")
    assert reader.first_read is None
    reader.read("terminal", "/reason")
    with pytest.raises(ValueError, match="READ_BUDGET"):
        reader.read("terminal")
    Path(selected["documents"][0]["material_ref"]["path"]).write_text("changed")
    with pytest.raises(ValueError, match="REFERENCE_CHANGED"):
        timing.MaterialReader(selected["documents"]).read("terminal")


def test_loop_respects_six_calls_and_does_not_invent_material_exposure(tmp_path):
    requests = []
    def complete(request):
        requests.append(request)
        return reply(calls=(AgentToolCall(f"call-{len(requests)}", "list_materials", {}),))
    result = json.loads(timing.read_exact(timing.execute_case(case(tmp_path), tmp_path / "cell",
        client_factory=lambda _: SimpleNamespace(complete_turn=complete), identity_reader=identity)))
    assert len(requests) == 6 and result["status"] == "model_budget_exhausted"
    assert result["localization_seconds"] >= 0 and result["material_reads"] == []
    assert result["first_read_to_final_seconds"] is None
    assert [len(r.historical_tool_exchanges) for r in requests] == list(range(6))


def test_timeout_preserves_current_attempt_without_retry(tmp_path):
    requests = []
    def complete(request):
        requests.append(request)
        raise RuntimeError("Local Agent request timed out after 180 seconds.")
    result = json.loads(timing.read_exact(timing.execute_case(case(tmp_path), tmp_path / "cell",
        client_factory=lambda _: SimpleNamespace(complete_turn=complete), identity_reader=identity)))
    assert result["status"] == "timeout" and len(requests) == 1
    assert result["calls"][0]["error"]["type"] == "RuntimeError"
    assert result["answer"] is None


def test_old_first_read_timing_plan_cannot_execute_under_new_clock(tmp_path):
    path = tmp_path / "old-prepared.json"
    timing.save_once(path, {"schema_version": "ai_localization_timing_v1", "profile": timing.PROFILE,
        "budget": timing.BUDGET, "cases": [{"case_id": str(i)} for i in range(4)]})
    with pytest.raises(ValueError, match="PLAN_CHANGED"):
        timing.execute(path, tmp_path / "must-not-start")
    assert not (tmp_path / "must-not-start").exists()


def test_prepare_discovers_failed_patch_journals_without_terminal_receipt_list(tmp_path, monkeypatch, snapshot_source):
    references = {}
    for sample in ("cb1", "tb1"):
        run = tmp_path / sample
        run.mkdir()
        references[sample] = {
            "result_ref": timing.save_once(run / "run_result.json", {"status": "failed"}),
            "manifest_ref": timing.save_once(run / "run_manifest.json", {"run_id": sample}),
        }
    journal = tmp_path / "tb1/a/cr/failed.json"
    journal.parent.mkdir(parents=True)
    journal_ref = timing.save_once(journal, {"status": "failed"})
    inspected = []

    def index(root, *, attempt_locator=None, include_investigation=False):
        if include_investigation:
            inspected.append(attempt_locator)
            return {"attempts": [{"failure_summary": "recorded failure"}]}
        return {"attempts": [{"journal_ref": journal_ref}] if Path(root).parent.name == "tb1" else []}

    monkeypatch.setattr("src.observability.patch_execution_index.project_patch_executions", index)
    monkeypatch.setattr("src.mod_agent.evaluation.context_chain.inspect_context_chain", lambda **_: {})
    rubric = timing.save_once(tmp_path / "rubric.json", {"host_only": "expected answer"})
    protocol = timing.save_once(tmp_path / "protocol.json", {
        "sample_ids": ["cb1", "tb1"], "source_refs": references, "host_private_rubric_ref": rubric})
    prepared = json.loads(timing.read_exact(timing.prepare(protocol["path"], tmp_path / "prepared")))
    assert inspected == [journal_ref["path"]]
    enhanced = next(c for c in prepared["cases"] if c["case_id"] == "tb1-enhanced")
    navigation = json.loads(timing.read_exact(enhanced["documents"][-1]["material_ref"]))
    assert navigation["patch_execution_index"][0]["attempts"][0]["failure_summary"] == "recorded failure"
    assert "expected answer" not in json.dumps(navigation)


def test_scoring_keeps_four_cells_and_late_correct_answer_has_no_speed_credit(tmp_path):
    rubric = timing.save_once(tmp_path / "rubric.json", {"samples": {
        s: {"required_checks": [1, 2, 3]} for s in ("cb1", "tb1")}})
    cases, refs, grades = [], [], []
    for sample in ("cb1", "tb1"):
        for arm in ("basic", "enhanced"):
            cid = sample + "-" + arm
            cases.append({"case_id": cid})
            ref = timing.save_once(tmp_path / (cid + ".json"), {"case_id": cid, "sample_id": sample,
                "timing_policy": timing.TIMING_POLICY,
                "arm": arm, "status": "timeout" if cid == "cb1-enhanced" else "submitted",
                "localization_seconds": 181 if cid == "cb1-enhanced" else 10})
            refs.append(ref)
            grades.append({"case_id": cid, "final_sha256": ref["sha256"], "verdict": "correct",
                           "criterion_results": [True, True, True]})
    plan = timing.save_once(tmp_path / "plan.json", {"cases": cases, "rubric_ref": rubric,
        "timing_policy": timing.TIMING_POLICY})
    execution = tmp_path / "execution.json"
    timing.save_once(execution, {"prepared_ref": plan, "final_refs": refs})
    judgments = tmp_path / "judgments.json"
    timing.save_once(judgments, {"review_origin": "Controlled fixture, not real evaluation", "records": grades})
    result = json.loads(timing.read_exact(timing.summarize(execution, judgments, tmp_path / "summary.json")))
    assert result["selected_per_arm"] == 2 and len(result["rows"]) == 4
    assert result["outcomes_by_arm"]["enhanced"] == {"timeout": 1, "correct": 1}
    assert result["eligible_pair_count"] == 1
    assert result["eligible_correct_pairs"][0]["sample_id"] == "tb1"


def test_prepare_keeps_complete_basic_records_and_rubric_out_of_model_materials(tmp_path, monkeypatch, snapshot_source):
    protocol = {"sample_ids": ["cb1", "tb1"], "source_refs": {},
        "host_private_rubric_ref": timing.save_once(tmp_path / "rubric.json", {"secret": "WITHHELD_REFERENCE_ANSWER"})}
    for sample in protocol["sample_ids"]:
        root = tmp_path / "original" / sample
        root.mkdir(parents=True)
        result = timing.save_once(root / "run_result.json", {"reason": "concrete original cause", "patch_execution_receipts": []})
        manifest = timing.save_once(root / "run_manifest.json", {"observations": ["unaltered"]})
        (root / "ordinary.stderr.log").write_text("complete normal log\n")
        protocol["source_refs"][sample] = {"result_ref": result, "manifest_ref": manifest}
    protocol_path = tmp_path / "protocol.json"
    timing.save_once(protocol_path, protocol)
    monkeypatch.setattr("src.mod_agent.evaluation.context_chain.inspect_context_chain",
        lambda **kwargs: {"run_id": kwargs["run_id"], "read_only": True})
    output = tmp_path / "prepared"
    prepared = json.loads(timing.read_exact(timing.prepare(protocol_path, output)))
    assert prepared["maximum_model_calls"] == 24 and prepared["model_calls_performed"] == 0
    assert [c["case_id"] for c in prepared["cases"]] == ["cb1-basic", "cb1-enhanced", "tb1-enhanced", "tb1-basic"]
    assert prepared["execution_order"] == list(timing.CASE_ORDER)
    assert prepared["execution_command"][1:3] == ["-I", "-B"]
    for sample in protocol["sample_ids"]:
        arms = {c["arm"]: c for c in prepared["cases"] if c["sample_id"] == sample}
        basic, enhanced = arms["basic"], arms["enhanced"]
        assert enhanced["documents"][:-1] == basic["documents"]
        original = next(d for d in basic["documents"] if d["name"] == "run_result.json")
        assert timing.read_exact(original["material_ref"]) == timing.read_exact(protocol["source_refs"][sample]["result_ref"])
        assert {d["name"] for d in basic["documents"]} == {"run_result.json", "run_manifest.json", "ordinary.stderr.log"}
        assert "WITHHELD_REFERENCE_ANSWER" not in str(timing._request(enhanced, []))
        assert all("WITHHELD_REFERENCE_ANSWER" not in timing.read_exact(d["material_ref"]).decode() for d in enhanced["documents"])
    from src.mod_agent.platform_execution_snapshot import FrozenExecution
    saved = [timing.read_exact(ref) for ref in prepared["source_refs"]]
    (snapshot_source / "src/libs/llm/agent_turn.py").write_text("# later live edit\n")
    FrozenExecution(prepared["source_snapshot_ref"]).verify_files()
    assert [timing.read_exact(ref) for ref in prepared["source_refs"]] == saved
    with pytest.raises(ValueError, match="EXECUTE_FROM_RETAINED_SOURCE"):
        timing.verify_prepared(output / "prepared.json")


def test_unknown_native_load_is_not_zero(tmp_path):
    requests = []
    def complete(request):
        requests.append(request)
        if len(requests) == 1:
            response = reply(calls=(AgentToolCall("read", "read_material", {"material_id": "terminal"}),))
            response.raw_response.pop("load_duration")
        else:
            response = reply(final())
            response.raw_response["load_duration"] = 0
        return response
    result = json.loads(timing.read_exact(timing.execute_case(case(tmp_path), tmp_path / "cell",
        client_factory=lambda _: SimpleNamespace(complete_turn=complete), identity_reader=identity)))
    assert [call["native_load_duration_ns"] for call in result["calls"]] == [None, 0]


def test_root_pointer_error_is_actionable_without_reinterpreting_empty_key():
    source = {"": "empty key value", "reason": "retained cause"}
    assert timing.json_pointer(source, "") == source
    assert timing.json_pointer(source, "/") == "empty key value"
    with pytest.raises(ValueError, match="pointer='' for the document root") as failure:
        timing.json_pointer({"reason": "retained cause"}, "/")
    assert "available_keys=['reason']" in str(failure.value)


def test_bad_pointer_feedback_allows_same_session_recovery(tmp_path):
    requests = []
    def complete(request):
        requests.append(request)
        if len(requests) == 1:
            return reply(calls=(AgentToolCall("bad", "read_material", {"material_id": "terminal", "pointer": "/"}),))
        if len(requests) == 2:
            body = request.historical_tool_exchanges[-1].tool_results[0].output
            assert body["read_id"] == "read-1" and body["status"] == "read_error"
            assert "pointer=''" in body["message"] and "reason" in body["message"]
            return reply(calls=(AgentToolCall("fixed", "read_material", {"material_id": "terminal", "pointer": ""}),))
        return reply(final().replace("read-1", "read-2"))
    ref = timing.execute_case(case(tmp_path), tmp_path / "cell", identity_reader=identity,
        client_factory=lambda _: SimpleNamespace(complete_turn=complete))
    result = json.loads(timing.read_exact(ref))
    assert result["status"] == "submitted" and len(result["calls"]) == 3
    assert len(result["material_reads"]) == 2


@pytest.mark.parametrize("content", ['{bad json', final().replace('read-1', 'terminal')])
def test_invalid_final_is_model_output_failure_with_original_preserved(tmp_path, content):
    requests = []
    def complete(request):
        requests.append(request)
        return (reply(calls=(AgentToolCall("read", "read_material", {"material_id": "terminal"}),))
                if len(requests) == 1 else reply(content))
    root = tmp_path / "cell"
    result = json.loads(timing.read_exact(timing.execute_case(case(tmp_path), root,
        identity_reader=identity, client_factory=lambda _: SimpleNamespace(complete_turn=complete))))
    assert result["status"] == "invalid_model_answer"
    assert result["answer_validation_error"] and result["answer"] is None
    assert json.loads((root / "first-final-response.json").read_text())["raw_content"] == content
    assert not (root / "failure.json").exists()
    if content != '{bad json':
        assert result["unvalidated_answer"] == json.loads(content)


def test_summary_preserves_model_failures_separately_from_measurement(tmp_path):
    statuses = ["invalid_model_answer", "model_budget_exhausted", "tool_budget_exhausted", "measurement_error"]
    rubric = timing.save_once(tmp_path / "rubric.json", {"samples": {s: {"required_checks": [1]} for s in ("cb1", "tb1")}})
    refs, cases = [], []
    for cid, status in zip(timing.CASE_ORDER, statuses):
        sample, arm = cid.split("-")
        cases.append({"case_id": cid})
        refs.append(timing.save_once(tmp_path / (cid + '.json'), {"case_id": cid, "sample_id": sample,
            "arm": arm, "status": status, "timing_policy": timing.TIMING_POLICY, "localization_seconds": 10}))
    plan = timing.save_once(tmp_path / "plan.json", {"cases": cases, "rubric_ref": rubric, "timing_policy": timing.TIMING_POLICY})
    execution = timing.save_once(tmp_path / "execution.json", {"prepared_ref": plan, "final_refs": refs})
    judgments = timing.save_once(tmp_path / "judgments.json", {"review_origin": "fixture", "records": []})
    result = json.loads(timing.read_exact(timing.summarize(execution['path'], judgments['path'], tmp_path / "summary.json")))
    assert [row['outcome'] for row in result['rows']] == statuses[:3] + ['measurement_failure']
    assert result['eligible_pair_count'] == 0


def test_argument_error_before_read_cannot_borrow_previous_read_id(tmp_path):
    requests = []
    def complete(request):
        requests.append(request)
        if len(requests) == 1:
            return reply(calls=(AgentToolCall("read", "read_material", {"material_id": "terminal"}),))
        if len(requests) == 2:
            return reply(calls=(AgentToolCall("bad-offset", "read_material", {"material_id": "terminal", "key_offset": -1}),))
        error = request.historical_tool_exchanges[-1].tool_results[0].output
        assert error['status'] == 'read_error' and error['read_id'] is None
        return reply(final())
    result = json.loads(timing.read_exact(timing.execute_case(case(tmp_path), tmp_path / "cell",
        identity_reader=identity, client_factory=lambda _: SimpleNamespace(complete_turn=complete))))
    assert result['status'] == 'submitted' and len(result['material_reads']) == 1
