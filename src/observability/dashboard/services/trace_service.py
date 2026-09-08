"""TraceService – read and parse traces from logs/traces.jsonl.

Provides a typed, filterable interface over the raw JSONL trace log.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional

from src.core.settings import resolve_path

logger = logging.getLogger(__name__)

# Default path to the traces file (absolute, CWD-independent)
DEFAULT_TRACES_PATH = resolve_path("logs/traces.jsonl")

DEFAULT_MAX_STRING_CHARS = 2000
_REDACTED = "[redacted]"
_TRUNCATED_SUFFIX = "...[truncated]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)
_PATH_KEY_PARTS = (
    "file_path",
    "path",
    "source_path",
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_POSIX_ABSOLUTE_PATH = re.compile(r"^/(?:[^/\0]+)(?:/[^/\0]+)*$")


class TraceService:
    """Read-only service for querying recorded traces.

    Args:
        traces_path: Path to the JSONL file.  Defaults to
            ``logs/traces.jsonl``.
    """

    def __init__(
        self,
        traces_path: Optional[str | Path] = None,
        *,
        include_raw: bool = False,
        safe_mode: Optional[bool] = None,
        max_string_chars: int = DEFAULT_MAX_STRING_CHARS,
    ) -> None:
        self.traces_path = Path(traces_path) if traces_path else DEFAULT_TRACES_PATH
        self.include_raw = include_raw and safe_mode is not True
        self.max_string_chars = max(32, max_string_chars)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_traces(
        self,
        trace_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return traces in reverse-chronological order.

        Args:
            trace_type: Filter by ``trace_type`` field (e.g.
                ``"ingestion"`` or ``"query"``).  ``None`` = all.
            limit: Maximum number of traces to return.

        Returns:
            List of trace dicts (newest first).
        """
        traces = self._load_all()

        if trace_type:
            traces = [t for t in traces if t.get("trace_type") == trace_type]

        # Newest first
        traces.sort(key=lambda t: t.get("started_at", ""), reverse=True)

        return [self._sanitize_trace(t) for t in traces[:limit]]

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single trace by its ``trace_id``.

        Returns:
            Trace dict, or ``None`` if not found.
        """
        for t in self._load_all():
            if t.get("trace_id") == trace_id:
                return self._sanitize_trace(t)
        return None

    def get_stage_timings(self, trace: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract stage timings from a trace.

        Returns:
            List of dicts with keys: stage_name, elapsed_ms, data.
            Ordered by appearance.
        """
        stages = trace.get("stages", [])
        timings: List[Dict[str, Any]] = []
        for s in stages:
            # The raw stage dict has: stage, timestamp, data (dict), elapsed_ms
            # Extract the inner 'data' dict directly rather than flattening
            stage_data = s.get("data")
            if stage_data is None:
                stage_data = {
                    key: value
                    for key, value in s.items()
                    if key not in {"stage", "timestamp", "elapsed_ms"}
                }
            if not isinstance(stage_data, dict):
                stage_data = {}
            timings.append(
                {
                    "stage_name": s.get("stage"),
                    "elapsed_ms": s.get("elapsed_ms", 0),
                    "data": stage_data,
                }
            )
        return timings

    # ------------------------------------------------------------------
    # Sanitization helpers
    # ------------------------------------------------------------------

    def _sanitize_trace(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        """Return a dashboard-safe trace unless raw debug access is explicit."""
        if self.include_raw:
            return trace
        sanitized = self._sanitize_value(trace, key_path=())
        if isinstance(sanitized, dict):
            return sanitized
        return {"trace_summary": sanitized}

    def _sanitize_value(self, value: Any, *, key_path: tuple[str, ...]) -> Any:
        if isinstance(value, dict):
            return {
                str(key): (
                    _REDACTED
                    if self._is_sensitive_key(str(key).lower())
                    else self._sanitize_value(
                        item,
                        key_path=key_path + (str(key),),
                    )
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._sanitize_value(item, key_path=key_path)
                for item in value
            ]
        if isinstance(value, str):
            return self._sanitize_string(value, key_path=key_path)
        return value

    def _sanitize_string(self, value: str, *, key_path: tuple[str, ...]) -> str:
        key = key_path[-1].lower() if key_path else ""
        if self._is_sensitive_key(key):
            return _REDACTED
        if self._is_path_key(key) or self._looks_like_path(value):
            return self._redact_path(value)
        if len(value) > self.max_string_chars:
            return value[: self.max_string_chars] + _TRUNCATED_SUFFIX
        return value

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        return any(part in key for part in _SENSITIVE_KEY_PARTS)

    @staticmethod
    def _is_path_key(key: str) -> bool:
        return any(part == key or key.endswith(f"_{part}") for part in _PATH_KEY_PARTS)

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        return bool(
            _WINDOWS_ABSOLUTE_PATH.match(value)
            or _POSIX_ABSOLUTE_PATH.match(value)
        )

    @staticmethod
    def _redact_path(value: str) -> str:
        # Recorded path syntax is independent of the dashboard host OS.
        windows_path = PureWindowsPath(value)
        if not value.startswith("/") and (windows_path.drive or "\\" in value):
            name = windows_path.name
        else:
            name = PurePosixPath(value).name
        if not name or name == value:
            return "[redacted_path]"
        return f"[redacted_path:{name}]"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> List[Dict[str, Any]]:
        """Parse every line in the JSONL file.

        Silently skips malformed lines.
        """
        if not self.traces_path.exists():
            return []

        traces: List[Dict[str, Any]] = []
        with self.traces_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    traces.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed trace line: %s", line[:80])
        return traces
