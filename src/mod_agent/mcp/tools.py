"""Safe read-only/report-only MCP tool surface for controlled-agent artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError
from src.mod_agent.dashboard import DashboardProjectionBuilder


CONTROLLED_AGENT_TOOL_NAMES = (
    "list_features",
    "get_feature_status",
    "get_artifact",
    "preview_retrieval",
    "preview_patch_proposal",
    "get_proposal_review",
    "get_eval_report",
    "get_job_status",
)

DANGEROUS_TOOL_NAMES = frozenset(
    {
        "apply_patch",
        "confirmed_apply",
        "copy_to_game_directory",
        "run_build",
        "run_game",
        "collect_runtime_evidence",
        "delete_artifacts",
    }
)


@dataclass(frozen=True)
class ControlledAgentMCPTool:
    """Schema-level definition for one safe controlled-agent tool."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class ControlledAgentMCPToolSurface:
    """Read-only/report-only tool facade over controlled-agent artifacts."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store
        self.projection_builder = DashboardProjectionBuilder(artifact_store)
        self._tools = {
            tool.name: tool
            for tool in (
                ControlledAgentMCPTool(
                    name="list_features",
                    description="List feature ids with controlled-agent artifacts.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                ControlledAgentMCPTool(
                    name="get_feature_status",
                    description="Return sanitized controlled-agent workflow status for a feature.",
                    input_schema=_feature_schema(),
                ),
                ControlledAgentMCPTool(
                    name="get_artifact",
                    description="Return a sanitized artifact summary, not the raw artifact body.",
                    input_schema=_feature_artifact_schema(),
                ),
                ControlledAgentMCPTool(
                    name="preview_retrieval",
                    description="Return sanitized evidence/retrieval readiness preview.",
                    input_schema=_feature_schema(),
                ),
                ControlledAgentMCPTool(
                    name="preview_patch_proposal",
                    description="Return sanitized patch proposal preview without raw diff body.",
                    input_schema=_feature_schema(),
                ),
                ControlledAgentMCPTool(
                    name="get_proposal_review",
                    description="Return sanitized proposal review status.",
                    input_schema=_feature_schema(),
                ),
                ControlledAgentMCPTool(
                    name="get_eval_report",
                    description="Return sanitized evaluation summary.",
                    input_schema=_feature_schema(),
                ),
                ControlledAgentMCPTool(
                    name="get_job_status",
                    description="Return sanitized async job status and budget decision semantics.",
                    input_schema=_feature_schema(),
                ),
            )
        }

    def list_tools(self) -> list[dict[str, Any]]:
        """Return schemas for safe tools only."""

        return [self._tools[name].to_dict() for name in CONTROLLED_AGENT_TOOL_NAMES]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a safe read-only tool and return MCP-shaped structured content."""

        arguments = dict(arguments or {})
        if name not in self._tools:
            return _tool_result(
                status="unsupported",
                message=f"Unsupported controlled-agent MCP tool: {name}",
                structured_content={
                    "tool": name,
                    "supported_tools": list(CONTROLLED_AGENT_TOOL_NAMES),
                },
                blockers=[
                    {
                        "stage": "mcp",
                        "code": "UNSUPPORTED_TOOL",
                        "message": f"Tool {name!r} is not exposed by the controlled-agent MCP surface.",
                    }
                ],
                is_error=True,
            )

        try:
            if name == "list_features":
                return self._list_features()

            feature_id = _required_str(arguments, "feature_id")
            if name == "get_feature_status":
                return self._get_feature_status(feature_id)
            if name == "get_artifact":
                artifact_type = _required_str(arguments, "artifact_type")
                return self._get_artifact(feature_id, artifact_type)
            if name == "preview_retrieval":
                return self._projection_section(feature_id, "evidence", "retrieval")
            if name == "preview_patch_proposal":
                return self._projection_section(feature_id, "proposal", "proposal")
            if name == "get_proposal_review":
                return self._proposal_review(feature_id)
            if name == "get_eval_report":
                return self._projection_section(feature_id, "evaluation", "eval")
            if name == "get_job_status":
                return self._get_job_status(feature_id)
        except (ArtifactStoreError, ValueError) as exc:
            return _tool_result(
                status="blocked",
                message=str(exc),
                structured_content={"tool": name, "error": str(exc)},
                blockers=[
                    {
                        "stage": "mcp",
                        "code": "TOOL_INPUT_OR_ARTIFACT_ERROR",
                        "message": str(exc),
                    }
                ],
                is_error=True,
            )

        return self.call_tool("__unsupported_internal__", {})

    def _list_features(self) -> dict[str, Any]:
        features_dir = self.artifact_store._guard_path(self.artifact_store.root / "features")
        feature_ids = []
        if features_dir.exists():
            feature_ids = sorted(path.name for path in features_dir.iterdir() if path.is_dir())
        return _tool_result(
            status="available",
            message=f"Found {len(feature_ids)} controlled-agent feature ids.",
            structured_content={"feature_ids": feature_ids, "feature_count": len(feature_ids)},
        )

    def _get_feature_status(self, feature_id: str) -> dict[str, Any]:
        projection = self.projection_builder.build_feature_projection(feature_id)
        artifact_refs = _artifact_ref_strings(self.artifact_store.list_feature_artifacts(feature_id))
        return _tool_result(
            status=str(projection.get("status")),
            message=f"Controlled-agent status for {feature_id}: {projection.get('status')}",
            structured_content={
                "feature_id": feature_id,
                "status": projection.get("status"),
                "workflow": projection.get("workflow"),
                "missing_artifacts": projection.get("missing_artifacts") or [],
            },
            artifact_refs=artifact_refs,
            trace_refs=_trace_refs_for_feature(self.artifact_store, feature_id),
            blockers=projection.get("blockers") or [],
        )

    def _get_artifact(self, feature_id: str, artifact_type: str) -> dict[str, Any]:
        summary = self._artifact_summary(feature_id, artifact_type)
        return _tool_result(
            status=str(summary.get("projection_status") or summary.get("status")),
            message=f"Sanitized artifact summary for {feature_id}/{artifact_type}.",
            structured_content={
                "feature_id": feature_id,
                "artifact": summary,
                "raw_body_exposed": False,
            },
            artifact_refs=[_artifact_ref_string(ref) for ref in self._refs_by_type(feature_id, artifact_type)],
            trace_refs=self._trace_refs_by_type(feature_id, artifact_type),
            blockers=_summary_blockers(summary),
        )

    def _projection_section(
        self,
        feature_id: str,
        section_name: str,
        label: str,
    ) -> dict[str, Any]:
        projection = self.projection_builder.build_feature_projection(feature_id)
        section = projection.get(section_name) or {}
        return _tool_result(
            status=str(section.get("projection_status") or section.get("status")),
            message=f"Controlled-agent {label} preview for {feature_id}.",
            structured_content={"feature_id": feature_id, label: section},
            artifact_refs=_artifact_ref_strings(self.artifact_store.list_feature_artifacts(feature_id)),
            trace_refs=_trace_refs_for_feature(self.artifact_store, feature_id),
            blockers=projection.get("blockers") or [],
        )

    def _proposal_review(self, feature_id: str) -> dict[str, Any]:
        review = self._artifact_summary(feature_id, "proposal_review")
        return _tool_result(
            status=str(review.get("projection_status") or review.get("status")),
            message=f"Proposal review summary for {feature_id}.",
            structured_content={
                "feature_id": feature_id,
                "proposal_review": review.get("dashboard_projection") or {},
                "artifact": review,
            },
            artifact_refs=[_artifact_ref_string(ref) for ref in self._refs_by_type(feature_id, "proposal_review")],
            trace_refs=self._trace_refs_by_type(feature_id, "proposal_review"),
            blockers=_summary_blockers(review),
        )

    def _get_job_status(self, feature_id: str) -> dict[str, Any]:
        summary = self._artifact_summary(feature_id, "job_status")
        refs = self._refs_by_type(feature_id, "job_status")
        envelope = self.artifact_store.read(refs[-1]) if refs else None
        data = envelope.get("data") if isinstance(envelope, dict) else {}
        data = data if isinstance(data, dict) else {}
        budget_summary = data.get("budget_summary")
        budget_summary = budget_summary if isinstance(budget_summary, dict) else None

        if budget_summary is not None:
            decision_status = budget_summary.get("status")
            continuation_allowed = budget_summary.get("allowed")
            decision_source = "budget_summary"
        else:
            decision_status = data.get("status")
            continuation_allowed = None
            decision_source = "payload.status"

        status = str(decision_status or data.get("status") or summary.get("status"))
        is_error = continuation_allowed is False
        return _tool_result(
            status=status,
            message=f"Job status for {feature_id}: {status}",
            structured_content={
                "feature_id": feature_id,
                "job": summary.get("dashboard_projection") or {},
                "budget_decision": {
                    "status": decision_status,
                    "allowed": continuation_allowed,
                    "source": decision_source,
                },
                "artifact_visibility": {
                    "envelope_status": summary.get("artifact_status"),
                    "rule": (
                        "Envelope status is an audit/visibility signal; budget continuation "
                        "semantics use budget_summary.allowed."
                    ),
                },
            },
            artifact_refs=[_artifact_ref_string(ref) for ref in refs],
            trace_refs=self._trace_refs_by_type(feature_id, "job_status"),
            blockers=_summary_blockers(summary),
            is_error=is_error,
        )

    def _artifact_summary(self, feature_id: str, artifact_type: str) -> dict[str, Any]:
        projection = self.projection_builder.build_feature_projection(feature_id)
        for artifact in projection.get("artifacts") or []:
            if artifact.get("artifact_type") == artifact_type:
                return artifact
        raise ArtifactStoreError(
            f"Artifact {artifact_type!r} does not exist for feature {feature_id!r}"
        )

    def _refs_by_type(self, feature_id: str, artifact_type: str) -> list[ArtifactRef]:
        return [
            ref
            for ref in self.artifact_store.list_feature_artifacts(feature_id)
            if ref.artifact_type == artifact_type
        ]

    def _trace_refs_by_type(self, feature_id: str, artifact_type: str) -> list[str]:
        trace_refs: list[str] = []
        for ref in self._refs_by_type(feature_id, artifact_type):
            envelope = self.artifact_store.read(ref)
            trace_refs.extend(str(item) for item in envelope.get("trace_refs") or [])
        return trace_refs


def _feature_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "feature_id": {
                "type": "string",
                "description": "Controlled-agent feature id.",
            }
        },
        "required": ["feature_id"],
        "additionalProperties": False,
    }


def _feature_artifact_schema() -> dict[str, Any]:
    schema = _feature_schema()
    schema["properties"] = {
        **schema["properties"],
        "artifact_type": {
            "type": "string",
            "description": "Registered controlled-agent artifact type.",
        },
    }
    schema["required"] = ["feature_id", "artifact_type"]
    return schema


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required string argument: {key}")
    return value.strip()


def _tool_result(
    *,
    status: str,
    message: str,
    structured_content: dict[str, Any],
    artifact_refs: list[str] | None = None,
    trace_refs: list[str] | None = None,
    blockers: list[dict[str, Any]] | None = None,
    is_error: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "content": [{"type": "text", "text": message}],
        "structuredContent": structured_content,
        "artifact_refs": artifact_refs or [],
        "trace_refs": trace_refs or [],
        "blockers": blockers or [],
        "isError": is_error,
    }


def _artifact_ref_string(ref: ArtifactRef) -> str:
    return f"{ref.feature_id}:{ref.artifact_type}:{Path(ref.path).name}:{ref.artifact_hash}"


def _artifact_ref_strings(refs: list[ArtifactRef]) -> list[str]:
    return [_artifact_ref_string(ref) for ref in refs]


def _trace_refs_for_feature(artifact_store: ArtifactStore, feature_id: str) -> list[str]:
    trace_refs: list[str] = []
    for ref in artifact_store.list_feature_artifacts(feature_id):
        envelope = artifact_store.read(ref)
        trace_refs.extend(str(item) for item in envelope.get("trace_refs") or [])
    return trace_refs


def _summary_blockers(summary: dict[str, Any]) -> list[dict[str, Any]]:
    if summary.get("projection_status") == "blocked":
        return [
            {
                "stage": "mcp",
                "code": "ARTIFACT_PROJECTION_BLOCKED",
                "message": f"Artifact projection blocked for {summary.get('artifact_type')}",
            }
        ]
    return []
