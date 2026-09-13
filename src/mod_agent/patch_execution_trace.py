"""Prospective Patch tracing configuration; no execution or disclosure authority."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

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

    def make_trace(self, *, run_id, feature_id, artifact_store_root, recorder,
                   request_id=None, root_name="patch.execution"):
        # One trace per invocation. Explicit logical requests correlate resumed
        # product runs; legacy callers retain their feature-scoped identity.
        # No source path or content is disclosed by this correlation identity.
        store_identity = str(Path(artifact_store_root).resolve())
        logical_id = request_id if request_id is not None else feature_id
        session = sha256((store_identity + "\0" + logical_id).encode()).hexdigest()
        identity = {"artifact_store_root": store_identity, "run_id": run_id, "request_id": request_id}
        trace_id = (sha256(json.dumps({**identity, "invocation_nonce": uuid4().hex},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:32]
            if request_id is not None else sha256(("live:" + run_id).encode()).hexdigest()[:32])
        trace = ExecutionTrace(trace_id,
            ("request-" if request_id is not None else "feature-") + session,
            self.environment, recorder=recorder, sink=self.sink, root_name=root_name)
        if request_id is not None:
            trace.context.metadata["logical_request_id"] = request_id
            trace.context.metadata["execution_identity"] = identity
        return trace

    def finish(self, trace):
        report = {"mode": "metadata_only" if self.sink is not None else "local_only",
                  "failures": trace.failure_statistics(), "cloud_readback": "not_performed"}
        report["session_identity_scope"] = (
            "artifact_store_and_logical_request" if "logical_request_id" in trace.context.metadata
            else "artifact_store_and_feature_legacy")
        if "logical_request_id" in trace.context.metadata:
            report["logical_request_id"] = trace.context.metadata["logical_request_id"]
        if self.sink is not None:
            try:
                report["export"] = self.sink.shutdown(timeout_millis=self.shutdown_timeout_millis)
            except Exception as error:
                report["export"] = {"status": "failed_open", "error_type": type(error).__name__}
        return report


def product_trace_identity(trace, run_root):
    """Read-only link to the existing run manifest, whose observations remain local."""
    if trace is None:
        return {"status": "unavailable"}
    return {
        "trace_id": trace.context.trace_id, "session_id": trace.session_id,
        "environment": trace.environment,
        "session_identity_scope": (
            "artifact_store_and_logical_request" if "logical_request_id" in trace.context.metadata
            else "artifact_store_and_feature_legacy"),
        **({"logical_request_id": trace.context.metadata["logical_request_id"]}
           if "logical_request_id" in trace.context.metadata else {}),
        "local_observation_source": ({
            "path": str(Path(run_root) / "run_manifest.json"),
            "json_pointer": "/execution_observations",
        } if trace.context.metadata.get("local_manifest_ready", True) else {
            "storage": "exception.execution_observations", "persisted": False,
        }),
    }


@contextmanager
def product_execution_trace(*, run_root, run_id, request_id, artifact_store_root,
                            configuration=None, buffer_until_manifest=False):
    """Observe the actual product Graph using its existing run manifest as recorder.

    This owns no product state or routing. A caller may buffer environment and
    source admission until its original manifest is created, without creating
    a directory or touching an older run's manifest on a rejected invocation.
    All persistence/export errors remain observational failures.
    """
    configuration = configuration or PatchExecutionTraceConfiguration()
    manifest_path = Path(run_root) / "run_manifest.json"
    observations = {}

    def read_manifest():
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if document.get("run_id") != run_id or document.get("request_id") != request_id:
            raise ValueError("Product trace manifest identity differs from its execution.")
        return document

    def write_manifest(document):
        temporary = manifest_path.with_name(".run_manifest.trace.tmp")
        try:
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2,
                                            sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(manifest_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def record(observation):
        observations[observation["id"]] = observation
        if not trace.context.metadata["local_manifest_ready"]:
            return
        document = read_manifest()
        document["execution_observations"] = dict(observations)
        document["execution_trace"] = product_trace_identity(trace, run_root)
        write_manifest(document)

    try:
        trace = configuration.make_trace(run_id=run_id, request_id=request_id,
            feature_id=None, artifact_store_root=artifact_store_root,
            recorder=record, root_name="product.execution")
        trace.context.metadata["local_manifest_ready"] = not buffer_until_manifest
    except Exception:
        yield None
        return
    business_error = None
    try:
        with trace.activate():
            trace.update(product_run_id=run_id, request_id=request_id,
                         timing_scope=("product_execution_from_environment_admission"
                            if buffer_until_manifest else "product_execution_from_run_manifest"))
            try:
                yield trace
            except BaseException as error:
                business_error = error
                raise
            finally:
                try:
                    document = read_manifest() if trace.context.metadata["local_manifest_ready"] else {}
                    terminal = document.get("terminal_record")
                    values = {
                        "terminal_stage": document.get("terminal_stage")
                            or document.get("terminal_failure_stage") or "unknown",
                        "workflow_status": document.get("status", "unknown"),
                    }
                    if isinstance(terminal, dict):
                        values["terminal_record_ref"] = terminal
                    elif business_error is not None:
                        failed = [row for row in observations.values()
                                  if row["status"] == "failed" and row["parent_id"] is not None]
                        values.update(workflow_status="exception", terminal_stage=(failed[-1]["name"] if failed else "unknown"))
                    trace.update(**values)
                except Exception:
                    # A failed recorder cannot replace a business result/exception.
                    pass
    finally:
        report = {}
        try:
            report = configuration.finish(trace)
            if trace.context.metadata["local_manifest_ready"]:
                document = read_manifest()
                document["execution_trace"] = {**product_trace_identity(trace, run_root), **report}
                write_manifest(document)
        except Exception:
            pass
        if business_error is not None:
            try:
                business_error.execution_trace = {**product_trace_identity(trace, run_root), **report}
                business_error.execution_observations = dict(observations)
            except Exception:
                pass


def attach_product_trace_manifest(trace):
    """The original entry calls this only after creating its new manifest."""
    if trace is not None:
        trace.context.metadata["local_manifest_ready"] = True
        trace.update(local_manifest_created=True)


def exception_execution_trace_projection(error):
    """Expose existing local trace evidence on the CLI's original error result."""
    summary = getattr(error, "execution_trace", None)
    observations = getattr(error, "execution_observations", None)
    if isinstance(summary, dict) and isinstance(observations, dict):
        return {"execution_trace": summary, "execution_observations": observations}
    return {}


def preserve_product_trace_projection(manifest, run_root):
    """Keep current telemetry when an existing owner refreshes its run manifest."""
    try:
        document = json.loads((Path(run_root) / "run_manifest.json").read_text(encoding="utf-8"))
        if any(document.get(key) != manifest.get(key) for key in ("run_id", "request_id")):
            return manifest
        return {**manifest, **{key: document[key] for key in ("execution_observations", "execution_trace")
                              if key in document}}
    except Exception:
        return manifest
