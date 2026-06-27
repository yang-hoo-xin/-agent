"""Compatibility module for `python -m src.main` during Phase A."""

from __future__ import annotations

from .mod_agent.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
