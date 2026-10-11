"""Controlled-agent dashboard page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError
from src.mod_agent.dashboard import DashboardProjectionBuilder
from src.observability.dashboard.services.trace_service import TraceService

DEFAULT_PRODUCT_RUNS_ROOT = Path.home() / "ModAgentRuns"


def render() -> None:
    """Render read-only controlled-agent artifact summaries."""

    import streamlit as st

    st.header("Controlled Agent")
    trace_tab, artifacts_tab = st.tabs(["Trace Drill-down", "Artifact Projection"])
    with trace_tab:
        _render_product_trace_drilldown()
    with artifacts_tab:
        _render_artifact_projection()


def _render_artifact_projection() -> None:
    import streamlit as st

    feature_id = st.text_input(
        "Feature ID",
        value="",
        key="mod_agent_feature_id",
    ).strip()
    artifact_root = st.text_input(
        "Artifact Root",
        value="artifacts",
        key="mod_agent_artifact_root",
    ).strip()

    if not feature_id:
        st.info("Enter a feature_id to inspect controlled-agent artifacts.")
        return

    try:
        store = _artifact_store_from_input(artifact_root or "artifacts")
        projection = DashboardProjectionBuilder(store).build_feature_projection(feature_id)
    except ArtifactStoreError as exc:
        st.error(str(exc))
        return

    _render_projection(projection)


def _render_product_trace_drilldown() -> None:
    """Render one explicit local Product run without starting work."""
    import streamlit as st

    st.subheader("Product Run Trace")
    st.caption(
        "Read-only local inspection. The selected run must stay under Allowed Runs Root; "
        "Cloud-supplied paths are never followed."
    )
    allowed_root = st.text_input(
        "Allowed Runs Root", value=str(DEFAULT_PRODUCT_RUNS_ROOT), key="product_trace_allowed_root",
    ).strip()
    run_root = st.text_input("Run Root", value="", key="product_trace_run_root").strip()
    run_id = st.text_input("Run ID", value="", key="product_trace_run_id").strip()
    continuation_root = st.text_input(
        "Continuation Root (optional)", value="", key="product_trace_continuation_root",
    ).strip()
    show_raw = st.checkbox(
        "Show hash-verified local request/response bodies",
        value=False,
        key="product_trace_show_raw",
        help="Reads only request/response refs recorded inside the explicitly selected local run.",
    )
    if not st.button("Inspect Product Trace", key="product_trace_inspect", disabled=not (run_root and run_id)):
        return
    try:
        drilldown = TraceService(max_string_chars=262_144).inspect_product_run(
            allowed_root=allowed_root,
            run_root=run_root,
            run_id=run_id,
            continuation_root=continuation_root or None,
            include_local_raw=show_raw,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.error(f"Trace inspection failed: {exc}")
        return
    st.session_state["product_trace_drilldown"] = drilldown
    _render_product_trace(drilldown, show_raw=show_raw)


def _render_product_trace(drilldown: dict[str, Any], *, show_raw: bool) -> None:
    import streamlit as st

    accounting = drilldown["call_accounting"]
    cols = st.columns(4)
    cols[0].metric("Actual calls", accounting["actual_generation_records"])
    original = accounting["original"]
    latest = accounting["latest"]
    findings = accounting["latest_requirement_findings"]
    cols[1].metric("Original budget", f"{original['consumed']}/{original['maximum']}")
    cols[2].metric("Latest cumulative", f"{latest['consumed']}/{latest['maximum']}")
    cols[3].metric("Findings", f"{findings['consumed']}/{findings['maximum']}")
    st.caption(accounting["counting_rule"])

    st.subheader("Trace Sources")
    for segment in drilldown["segments"]:
        trace = segment["trace"]
        with st.expander(
            f"{segment['segment']} · trace {trace.get('trace_id')} · {segment['model_call_count']} cumulative calls",
            expanded=True,
        ):
            st.json({"run_root": segment["run_root"], "status": segment["status"],
                     "manifest_ref": segment["manifest_ref"], "result_ref": segment["result_ref"],
                     "trace": trace, "observation_count": segment["observation_count"]})
            if trace.get("mode") != "local_only" or trace.get("cloud_readback") != "not_performed":
                st.warning("Trace mode/readback differs from the expected local-only, not-performed state.")
            else:
                st.info("Local-only trace; Cloud readback was not performed. No Cloud link is available.")

    st.subheader("Model Calls")
    for call in drilldown["calls"]:
        label = (f"Call {call['call_number']} · {call['segment']} · {call['role']} · "
                 f"{call['model']} · {call['elapsed_ms']:.0f} ms")
        with st.expander(label, expanded=True):
            st.json({key: call[key] for key in (
                "request_span_id", "generation_span_id", "parent_id", "role", "model", "provider",
                "status", "started_at", "finished_at", "elapsed_ms", "transport", "usage",
                "input_payload_sha256", "output_sha256", "local_evidence", "counting")})
            if show_raw and call["raw"]:
                request = call["raw"].get("request")
                response = call["raw"].get("response")
                provider_request = call["raw"].get("provider_request")
                if request:
                    st.markdown("**Model messages**")
                    st.caption("Application-layer messages. The output constraint Schema is shown separately below.")
                    st.json(request.get("messages"))
                    st.markdown("**Output constraint Schema**")
                    st.caption(request.get("schema_visibility"))
                    st.json(request.get("response_format"))
                    with st.expander("Other application request fields"):
                        st.json(request.get("other_fields"))
                if response:
                    st.markdown("**Recorded application response**")
                    st.code(response.get("text", ""), language="json")
                if provider_request:
                    st.markdown("**Native provider request projection**")
                    st.caption("Only the hash-bound native format and non-content fields are shown; native messages and the complete body remain hidden.")
                    st.json(provider_request)

    st.subheader("Five-layer Schema Failure Chain")
    layers = drilldown["schema_failure_drilldown"]
    layer_labels = {
        "layer_1_schema_builder": "1. Schema builder constraints",
        "layer_2_application_to_native_provider": "2. Application response_format → native provider format",
        "layer_3_provider_runtime_support": "3. Ollama / llama.cpp version and support evidence",
        "layer_4_raw_response_against_recorded_schema": "4. Raw response vs recorded Schema",
        "layer_5_local_validators": "5. Local Schema and business validators",
    }
    for key, label in layer_labels.items():
        with st.expander(label, expanded=True):
            st.json(layers[key])
    st.caption(
        "Official documentation and fixed-version source analysis describe capability; "
        "they do not prove the native conversion used by this run."
    )

    latest_gate = drilldown["segments"][-1].get("post_findings_gate") or {}
    st.subheader("Current Post-Findings Gate")
    st.json({"blockers": drilldown["segments"][-1].get("blockers") or [], **latest_gate})

    reassessment = drilldown["segments"][-1].get("initial_findings_reassessment") or {}
    st.subheader("Initial Findings Query and Evidence Chain")
    st.caption(
        "Source retrieval, dependency-metadata requests, model HTTP transport, and Findings use are "
        "separate recorded boundaries. Input presence does not prove model attention or usefulness."
    )
    st.json(reassessment)

    st.subheader("Validation and Failure Timeline")
    for index, event in enumerate(drilldown["diagnostic_timeline"], 1):
        origin = event.get("origin")
        time_value = event.get("time") or "unknown (offline reconstruction has no original event time)"
        with st.expander(
            f"{index}. {event.get('segment')} · {event.get('error_code')} · {origin}", expanded=True,
        ):
            st.json({**event, "time": time_value})
            if origin == "offline_exact_input_replay":
                st.warning("Supplemental offline reconstruction; this was not backfilled as an original realtime span.")

    st.subheader("Recorded Blind Spots")
    for item in drilldown["blind_spots"]:
        st.write(f"- {item}")


def _artifact_store_from_input(artifact_root: str) -> ArtifactStore:
    root = Path(artifact_root)
    if root.is_absolute():
        resolved = root.resolve()
    else:
        resolved = (Path.cwd() / root).resolve()
        try:
            resolved.relative_to(Path.cwd().resolve())
        except ValueError as exc:
            raise ArtifactStoreError(
                "Relative Artifact Root cannot escape the project root."
            ) from exc
    return ArtifactStore(resolved)


def _render_projection(projection: dict[str, Any]) -> None:
    import streamlit as st

    st.subheader("Run Summary")
    cols = st.columns(4)
    with cols[0]:
        st.metric("Status", projection.get("status", "unknown"))
    with cols[1]:
        st.metric("Artifacts", len(projection.get("artifacts") or []))
    with cols[2]:
        st.metric("Missing", len(projection.get("missing_artifacts") or []))
    with cols[3]:
        st.metric("Blockers", len(projection.get("blockers") or []))

    workflow, evidence, proposal, build, runtime, repair, evaluation = st.tabs(
        ["Workflow", "Evidence", "Proposal", "Build", "Runtime", "Repair", "Eval"]
    )
    with workflow:
        st.json(projection.get("workflow") or {})
    with evidence:
        st.json(projection.get("evidence") or {})
    with proposal:
        st.json(projection.get("proposal") or {})
    with build:
        st.json(projection.get("build") or {})
    with runtime:
        st.json(projection.get("runtime") or {})
    with repair:
        st.json(projection.get("repair") or {})
    with evaluation:
        st.json(projection.get("evaluation") or {})

    st.subheader("Artifacts")
    artifacts = projection.get("artifacts") or []
    if artifacts:
        st.dataframe(artifacts, use_container_width=True)
    else:
        st.info("No artifacts found for this feature_id.")

    missing = projection.get("missing_artifacts") or []
    if missing:
        st.subheader("Missing Artifacts")
        st.write(missing)

    blockers = projection.get("blockers") or []
    if blockers:
        st.subheader("Blockers")
        st.dataframe(blockers, use_container_width=True)
