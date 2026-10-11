"""Workflow primitives for RepoForge."""

from .checkpointing import (
    CheckpointPolicy,
    ResumeReport,
    WorkflowCheckpoint,
    WorkflowCheckpointStore,
    resumed_state_from_decision,
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
from .verification_only import (
    VERIFICATION_ONLY_INPUT_EXECUTION_MODE,
    VerificationOnlyContinuationInput,
    VerificationOnlyRuntimeTerminalInput,
    preflight_verification_only_continuation,
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
    "VERIFICATION_ONLY_INPUT_EXECUTION_MODE",
    "VerificationOnlyContinuationInput",
    "VerificationOnlyRuntimeTerminalInput",
    "WorkflowCheckpoint",
    "WorkflowCheckpointStore",
    "build_graph",
    "create_initial_state",
    "resumed_state_from_decision",
    "preflight_verification_only_continuation",
]
