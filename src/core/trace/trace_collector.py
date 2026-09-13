"""Trace collector – receives finished TraceContext and persists them.

The collector is the bridge between in-memory TraceContext objects and
the on-disk JSON Lines log used by the Dashboard.  It is intentionally
decoupled from the logging module so that trace persistence remains
predictable and testable.
"""

import json
import logging
import hashlib
import os
import re
from pathlib import Path
from typing import Optional
from uuid import uuid4

from src.core.settings import resolve_path
from src.core.trace.trace_context import TraceContext

logger = logging.getLogger(__name__)

# Default absolute path for traces file (CWD-independent)
_DEFAULT_TRACES_PATH = resolve_path("logs/traces.jsonl")


class TraceCollector:
    """Collects finished traces and appends them to a JSON Lines file.

    Args:
        traces_path: File path for the ``traces.jsonl`` output.
            Parent directories are created automatically.
    """

    def __init__(self, traces_path: str | Path | None = None) -> None:
        self._path = Path(traces_path) if traces_path is not None else _DEFAULT_TRACES_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def collect(self, trace: TraceContext) -> None:
        """Persist a single trace as one JSON line.

        If the trace has not been finished yet, ``finish()`` is called
        automatically so the output always contains timing data.

        Args:
            trace: A populated :class:`TraceContext`.
        """
        if trace.finished_at is None:
            trace.finish()

        line = json.dumps(trace.to_dict(), ensure_ascii=False)
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            logger.exception("Failed to write trace %s", trace.trace_id)

    def collect_execution(self, document: dict) -> dict[str, str]:
        """Retain one complete execution snapshot without overwriting prior runs.

        This strict local sink returns a checked file reference or raises. It
        does not change the older best-effort JSONL collector. The document uses
        the existing run-manifest observation shape so local/Cloud joins can read
        it directly. A finished file is published only after flushing its bytes.
        """
        identity = document["execution_trace"]["trace_id"]
        rows = document["execution_observations"]
        if (not isinstance(identity, str) or re.fullmatch(r"[a-f0-9]{32}", identity) is None
                or not isinstance(rows, dict) or not rows
                or any(not isinstance(row, dict) or row.get("trace_id") != identity
                       or not row.get("finished_at") for row in rows.values())):
            raise ValueError("Execution retention requires a complete, same-trace observation tree.")
        directory = self._path.parent / "execution"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (identity + ".json")
        temporary = directory / ("." + identity + "." + uuid4().hex + ".tmp")
        raw = (json.dumps(document, ensure_ascii=False, sort_keys=True,
                          indent=2, allow_nan=False) + "\n").encode("utf-8")
        created = False
        try:
            with temporary.open("xb") as stream:
                created = True
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Same-directory hard link publishes completed bytes exclusively.
            # Existing records are never replaced, even for an identity clash.
            os.link(temporary, path)
            if path.read_bytes() != raw:
                raise OSError("Retained execution bytes differ from the completed snapshot.")
            return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}
        finally:
            if created:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # Cleanup does not invalidate an already published record
                    # or replace the original storage exception.
                    logger.warning("Execution trace temporary cleanup failed.", exc_info=True)

    @property
    def path(self) -> Path:
        """Return the resolved path of the traces file."""
        return self._path
