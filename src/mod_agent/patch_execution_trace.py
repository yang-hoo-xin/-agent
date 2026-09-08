"""Prospective Patch tracing configuration; no execution or disclosure authority."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.core.trace.execution_trace import ExecutionTrace


@dataclass(frozen=True)
class PatchExecutionTraceConfiguration:
    environment: str = "local"
    sink: Any = None
    shutdown_timeout_millis: int = 1000

    def __post_init__(self):
        if not isinstance(self.environment, str) or not self.environment.strip():
            raise ValueError("Trace environment must be explicit and non-empty.")
        if type(self.shutdown_timeout_millis) is not int or not 0 <= self.shutdown_timeout_millis <= 5000:
            raise ValueError("Trace shutdown deadline must be between 0 and 5000 milliseconds.")

    def make_trace(self, *, run_id, feature_id, artifact_store_root, recorder):
        # One trace per invocation, one opaque session per existing logical feature.
        # No source path or content is disclosed by this correlation identity.
        session = sha256((str(Path(artifact_store_root).resolve()) + "\0" + feature_id).encode()).hexdigest()
        return ExecutionTrace(sha256(("live:" + run_id).encode()).hexdigest()[:32],
            "feature-" + session, self.environment, recorder=recorder, sink=self.sink)

    def finish(self, trace):
        report = {"mode": "metadata_only" if self.sink is not None else "local_only",
                  "failures": trace.failure_statistics(), "cloud_readback": "not_performed"}
        if self.sink is not None:
            try:
                report["export"] = self.sink.shutdown(timeout_millis=self.shutdown_timeout_millis)
            except Exception as error:
                report["export"] = {"status": "failed_open", "error_type": type(error).__name__}
        return report
