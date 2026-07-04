"""Controlled-agent dashboard page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactStore, ArtifactStoreError
from src.mod_agent.dashboard import DashboardProjectionBuilder


def render() -> None:
    """Render read-only controlled-agent artifact summaries."""

    import streamlit as st

    st.header("Controlled Agent")

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
