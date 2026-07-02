"""Workflow primitives for the Controlled Mod Agent platform."""

from .checkpointing import (
    CheckpointPolicy,
    ResumeReport,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
)
from .interrupts import InterruptRequest, ResumeDecision, ResumePayload, ResumeValidator
from .nodes import (
    NODE_ARTIFACT_MAP,
    NODE_STAGE_MAP,
    StubNodeResult,
    StubNodeRunner,
    TraceEvent,
)
from .state import (
    ArtifactRefMap,
    ExecutionPath,
    ModAgentState,
    RiskLevel,
    StageName,
    StateOwnershipPolicy,
    create_initial_state,
)


def build_graph(*args, **kwargs):
    """Build the workflow graph without importing graph during package init."""

    from .graph import build_graph as _build_graph

    return _build_graph(*args, **kwargs)


__all__ = [
    "ArtifactRefMap",
    "CheckpointPolicy",
    "ExecutionPath",
    "InterruptRequest",
    "ModAgentState",
    "NODE_ARTIFACT_MAP",
    "NODE_STAGE_MAP",
    "RiskLevel",
    "ResumeDecision",
    "ResumePayload",
    "ResumeReport",
    "ResumeValidator",
    "StageName",
    "StateOwnershipPolicy",
    "StubNodeResult",
    "StubNodeRunner",
    "TraceEvent",
    "WorkflowCheckpoint",
    "WorkflowCheckpointStore",
    "build_graph",
    "create_initial_state",
]
