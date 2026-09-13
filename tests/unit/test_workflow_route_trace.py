"""Conditional routing is observed at invocation, without changing its result."""
from copy import deepcopy

import pytest
from langgraph.graph import END, START, StateGraph

from src.core.trace.execution_trace import ExecutionTrace
from src.mod_agent.artifacts import ArtifactStore
from src.mod_agent.workflow.graph import _add_traced_conditional_edges, build_graph
from src.mod_agent.workflow.state import create_initial_state
from src.mod_agent.workflow.transitions import (
    route_after_evidence, route_after_patch_proposal, route_after_review,
)


def _rows(trace):
    return list({stage["data"]["id"]: stage["data"] for stage in trace.context.stages}.values())


@pytest.mark.parametrize(("node", "selector", "changes", "expected"), [
    ("review_proposal", route_after_review,
     {"review_summary": {"allowed_next_stage": "dry_run_apply", "decision": "revise_proposal"}}, "continue"),
    ("review_proposal", route_after_review,
     {"review_summary": {"decision": "revise_proposal"}}, "repair"),
    ("review_proposal", route_after_review, {}, "blocked"),
    ("retrieve_evidence", route_after_evidence,
     {"artifacts": {"evidence_pack": "local-ref"}, "blockers": [{"code": "MISSING", "message": "private details"}]}, "continue"),
    ("retrieve_evidence", route_after_evidence, {}, "blocked"),
    ("generate_patch_proposal", route_after_patch_proposal,
     {"artifact_hashes": {"implementation_plan": "a" * 64},
      "runtime_summary": {"patch_upstream_pending": {"source_plan_hash": "a" * 64}}}, "upstream"),
    ("generate_patch_proposal", route_after_patch_proposal,
     {"artifact_hashes": {"implementation_plan": "a" * 64},
      "runtime_summary": {"patch_upstream_pending": {"source_plan_hash": "b" * 64}}}, "continue"),
])
def test_actual_conditional_selector_result_and_input_are_preserved(node, selector, changes, expected):
    state = create_initial_state(run_id="run", request_id="request", user_request="private user request")
    state.update(changes)
    before = deepcopy(state)
    trace = ExecutionTrace("route-test", "logical-task", "test")
    graph = StateGraph(dict)
    graph.add_node(node, lambda state: state)
    graph.add_edge(START, node)
    with trace.activate():
        _add_traced_conditional_edges(graph, node, selector,
            {"continue": END, "blocked": END, "repair": END, "upstream": END})
        compiled = graph.compile()
        assert not any(row["name"] == "workflow.route" for row in _rows(trace))
        result = compiled.invoke(state)
    assert state == before and result == before
    routes = [row for row in _rows(trace) if row["name"] == "workflow.route"]
    assert len(routes) == 1
    attrs = routes[0]["attributes"]
    assert attrs["selected_route"] == expected == selector(state)
    assert attrs["selected_next_node"] == END
    assert attrs["route_selector"] == selector.__name__
    assert attrs["decision_summary_origin"] == "deterministic_route_selector"
    assert "private user request" not in str(attrs)
    assert "private details" not in str(attrs)
    assert not any(row["name"] == END for row in _rows(trace))


def test_real_graph_registration_records_selected_edge_only_when_invoked(tmp_path):
    trace = ExecutionTrace("public-route-test", "task", "test")
    with trace.activate():
        graph = build_graph(ArtifactStore(tmp_path / "store"))
        graph.get_graph()
        assert not any(row["name"] == "workflow.route" for row in _rows(trace))
        result = graph.invoke(create_initial_state(run_id="run", request_id="request", user_request="do it"))
    assert result["current_stage"] == "blocked"
    routes = [row for row in _rows(trace) if row["name"] == "workflow.route"]
    assert len(routes) == 1
    assert routes[0]["attributes"]["from_node"] == "plan_request"
    assert routes[0]["attributes"]["selected_next_node"] == "blocked"
    assert not any(row["attributes"].get("workflow_node") == "generate_patch_proposal" for row in _rows(trace))


def test_route_projection_failure_does_not_change_selector_result():
    graph = StateGraph(dict)
    graph.add_node("route_owner", lambda state: state)
    graph.add_edge(START, "route_owner")
    trace = ExecutionTrace("route-projection-failed", "task", "test")
    with trace.activate():
        _add_traced_conditional_edges(graph, "route_owner", lambda _: "continue", {"continue": END})
        result = graph.compile().invoke({"blockers": None})
    assert result == {"blockers": None}
    route = next(row for row in _rows(trace) if row["name"] == "workflow.route")
    assert route["attributes"]["route_input_summary_status"] == "unavailable"
    assert route["attributes"]["selected_route"] == "continue"
