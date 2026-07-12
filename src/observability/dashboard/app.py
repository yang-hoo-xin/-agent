"""Evidence-Grounded Controlled Code Generation Agent Platform dashboard.

Entry-point: ``streamlit run src/observability/dashboard/app.py``

Pages are registered via ``st.navigation()`` and rendered by their
respective modules under ``pages/``.  Pages not yet implemented show
a placeholder message.
"""

from __future__ import annotations

import streamlit as st


# ── Page definitions ─────────────────────────────────────────────────

def _page_overview() -> None:
    from src.observability.dashboard.pages.overview import render
    render()


def _page_data_browser() -> None:
    from src.observability.dashboard.pages.data_browser import render
    render()


def _page_ingestion_manager() -> None:
    from src.observability.dashboard.pages.ingestion_manager import render
    render()


def _page_ingestion_traces() -> None:
    from src.observability.dashboard.pages.ingestion_traces import render
    render()


def _page_query_traces() -> None:
    from src.observability.dashboard.pages.query_traces import render
    render()


def _page_evaluation_panel() -> None:
    from src.observability.dashboard.pages.evaluation_panel import render
    render()


def _page_mod_agent_dashboard() -> None:
    from src.observability.dashboard.pages.mod_agent_dashboard import render
    render()


# ── Navigation ───────────────────────────────────────────────────────

pages = [
    st.Page(_page_overview, title="Overview", icon="📊", default=True),
    st.Page(_page_mod_agent_dashboard, title="Controlled Agent", icon="🧭"),
    st.Page(_page_data_browser, title="Data Browser", icon="🔍"),
    st.Page(_page_ingestion_manager, title="Ingestion Manager", icon="📥"),
    st.Page(_page_ingestion_traces, title="Ingestion Traces", icon="🔬"),
    st.Page(_page_query_traces, title="Query Traces", icon="🔎"),
    st.Page(_page_evaluation_panel, title="Evaluation Panel", icon="📏"),
]


def main() -> None:
    st.set_page_config(
        page_title="Evidence-Grounded Controlled Code Generation Agent Platform",
        page_icon="📊",
        layout="wide",
    )

    nav = st.navigation(pages)
    nav.run()


if __name__ == "__main__":
    main()
