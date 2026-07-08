# V1 To V2 Transition

This document records the engineering progression rules for moving from the
accepted-with-gaps V1 contract path toward V2 implementation work.

It is not a replacement for `DEV_SPEC.md`, `docs/SPEC_COVERAGE_MATRIX.md`,
`docs/PROJECT_STATE.md`, or `docs/IMPLEMENTATION_QUEUE.md`.

Last updated: 2026-07-08

## Purpose

```text
V1 goal:
  Prove the controlled local contract path, artifact/evidence/review/build/runtime
  boundaries, and claim discipline.

Transition goal:
  Reduce the risk of wrong continuation, wrong success claims, unreviewable code
  changes, unsafe external interfaces, and ambiguous runtime evidence before V2
  expansion.

V2 goal:
  Add real production-facing capabilities only after the transition gates are
  explicit and testable.
```

The transition stage is not feature expansion. It is the stage that makes later
feature expansion auditable.

## Maturity Levels

These levels describe module engineering maturity. They do not replace the
coverage status values in `docs/SPEC_COVERAGE_MATRIX.md`.

| Level | Meaning | RAG-style analogue |
| --- | --- | --- |
| M0 Contract | Schema, interface, artifact, failure payload, and forbidden claims are explicit | Define `Document`, `Chunk`, `EvidenceItem`, `EvidencePack`, and retriever contracts |
| M1 Local Deterministic | Local deterministic, fake, mock, or supplied-output path can run with explicit execution mode | Exact/symbol/BM25 path runs without semantic embedding as authority |
| M2 Integrated Loop | LangGraph, ArtifactStore, trace, tests, blockers, and failure policy consume the module output | Retrieval output participates in readiness and graph routing with downgrade/blocking rules |
| M3 Eval And Dashboard | Eval cases, metrics, dashboard projection, and claim-boundary tests make behavior inspectable | Retrieval trace dashboard, eval report, and false-success guard exist |

M3 does not mean production-ready. Production readiness requires separate
authentication, deployment, durability, concurrency, observability, recovery,
and operational evidence.

## Progression Rule

A module can hand off to downstream work when all five checks pass:

| Check | Continue when true | Stop when false |
| --- | --- | --- |
| Claim boundary | The module prevents wrong success claims | Add claim-boundary tests and forbidden-claim fields |
| Downstream contract | Downstream code can consume the output without guessing | Add schema, artifact, trace, or config contract |
| Failure artifact | Failure produces a blocker or audit artifact | Add failure payloads, blockers, and no-silent-skip tests |
| Focused tests | Main path and failure path have focused tests | Add or repair focused tests before expansion |
| Risk isolation | Known gaps do not pollute the next decision | Close the gap or make the next task explicitly blocked by it |

Do not require every module to reach M3 before any other work proceeds. Require
only the maturity level needed to keep the next module honest.

## Task Width Control

| Width | Appropriate use | Required control |
| --- | --- | --- |
| S | One bug, one field, one focused test, or one narrow doc correction | 1-3 files and one focused validation path |
| M | One module loop such as Eval Gate, Git Binding, Proposal Context Pack, MCP Wire Boundary, or Runtime Evidence Binding | 4-10 files, explicit out-of-scope list, focused tests, and control-doc update |
| L | Cross-module stage such as V1_TO_V2_TRANSITION | Must be split into M tasks before implementation |

Default implementation width is M. L tasks are planning containers only unless
the user explicitly approves a narrower subtask inside them.

## Human Supervision Contract

Before implementation, the agent should state:

```text
Task:
Goal:
Scope:
Out of scope:
Risk:
Expected files:
Focused tests:
Completion unlocks:
Requires explicit approval:
```

After implementation, the agent should state:

```text
Completed:
Changed files:
Validation:
Now true:
Still unproven:
Allowed claims:
Forbidden claims:
Next:
```

The user does not need to inspect every line of code to supervise the project.
The user should be able to check whether the stated scope, tests, and forbidden
claims make sense.

## Module Progression Boundaries

| Module | Current judgment | Target boundary before broad V2 expansion | Do not do yet |
| --- | --- | --- | --- |
| WF | Main control chain is mostly established | M2/M3: LangGraph conditional edges, interrupt/resume, checkpoint, repair re-entry, and route audit are unified; normal/blocked/repair/resume tests exist | Do not add free-running multi-agent workers; do not let helpers replace LangGraph routing |
| ART | Base artifact contract is stable enough for V1 | M2: artifact registry, producer/consumer policy, upstream hash, stale propagation, dashboard projection, and schema version are enforced | Do not describe storage as production-grade before recovery, manifest/index, revision query, migration, locking, and garbage-collection gaps are planned |
| KB | Indexing works but loader coverage is incomplete | M1/M2: code, Markdown, artifact, and log loaders can feed evidence sources with stable identity and incremental hash behavior | Do not prioritize full PDF/PPT/vision ingestion before artifact/log/source evidence loaders |
| RET | Retrieval is one of the more mature subsystems | M2/M3: RRF, dense failure policy, rerank fallback, readiness eval, and false-continue guard are tested | Do not treat dense/vector hits as permission to patch; do not start heavy Qdrant/FastAPI work before bridge behavior is evaluated |
| PLAN | Planning and planning_brief are relatively complete | M2/M3: route taxonomy, blocking uncertainty, acceptance contract, risk-tiered evidence requirement, and planning eval cases exist | Do not keep extending heuristic keywords without eval cases |
| PROP | Proposal contract has M2 metadata context coverage | M2: Change Unit Model, proposal metadata context pack, scope boundary, evidence-backed diff intent, no-op detector, and rollback hint are available and reviewed before dry-run | Do not describe this as a full code-generation context pack; do not directly generate real diffs or write files from proposal construction |
| REVIEW | Review coverage is relatively complete | M2/M3: rule registry, structured finding, evidence binding, scope minimality, semantic alignment, permission boundary, and review eval exist | Do not let review logic become scattered conditional checks |
| GIT | Git binding has M1/M2 audit coverage | M1/M2: git state snapshot, diff hash, proposal/base revision binding metadata, rollback hint, and dirty-tree policy exist in `git_change_record` and dashboard projection | Do not claim dirty-tree policy is an execution-layer hard stop; do not automatically reset, restore, rebase, or discard user changes |
| BUILD | Build runner is usable | M2: build profile registry, structured result, error taxonomy, diagnostic extraction, and repair handoff exist | Build success must never claim runtime success |
| RUN | Runtime binding has M2 contract coverage; live GTFO gameplay is unproven | M2: verification ladder, manual/probe/log/screenshot evidence, GTFO automation failure artifact, feature/build/run binding, plugin-specific markers, and non-goal preservation fields exist | Do not claim real GTFO gameplay success before MISS-026 live validation closes |
| REPAIR | Repair loop is relatively complete | M2/M3: failure evidence pack, root-cause hypothesis, minimal fix plan, retry budget, stop condition, and review re-entry exist | Do not expand scope without evidence; do not allow unbounded repair |
| MM | Multimodal remains a shortfall | M1: screenshot registry, image metadata, mock captioner, and image_refs can enter evidence/dashboard safely | Do not call real Vision LLMs or claim image understanding is complete |
| EVAL | Eval hard routing exists; broader quality evaluation remains underdeveloped | M2/M3: golden path matrix, module eval cases, false-continue/false-block, review correctness, dry-run safety, insufficient_baseline, stale_evidence, missing_required_metric, eval_report artifact, and hard routing exist | Do not claim full agent quality evaluation or real baseline runner until Q-019 style files are restored or reimplemented |
| OBS | Observability exists but is uneven | M2: trace, metric, structured log, dashboard projection, artifact DAG, and evidence/proposal/review/build-runtime viewers are aligned | OpenTelemetry and production observability remain later work |
| MCP | Safe facade and JSON-RPC wire adapter exist | M2: initialize, notifications/initialized, `tools/list`, `tools/call`, content, structuredContent, artifact_refs, trace_refs, dangerous tool hidden/disabled policy, and wire-level tests exist | Do not claim stdio/http transport, server process wiring, or production MCP integration; do not expose `confirmed_apply`, `run_game`, or `copy_to_game_directory` as executable tools; do not treat ToolAnnotations as the safety boundary |
| PERF | Budget contract exists | M1/M2: retrieval/build/runtime budget policy, timeout, API call count, benchmark smoke, and budget-exceeded blocker exist | Do not start large-scale concurrency benchmarks yet |
| DOM | GTFO boundary is clear enough for V1 | M2: GameProfile onboarding, capability report, allowed/forbidden roots, build/runtime/evidence source profiles exist | Do not hardcode GTFO behavior into generic workflow modules |

## Capability Recovery Matrix

This matrix converts narrowed capability statements into implementation work.
Rows are recovery targets, not completed status claims.

| Recovery target | Source code locations | Artifact contract changes | LangGraph routing changes | Focused tests | Success acceptance criteria |
| --- | --- | --- | --- | --- | --- |
| Eval Gate Hard Routing | `src/mod_agent/evaluation/gate.py`, `src/mod_agent/workflow/graph.py`, `src/mod_agent/workflow/transitions.py` | `eval_report` envelope status follows `evaluation_gate.status`; failed gate blockers are stored on the envelope | `evaluate` routes to `blocked` when stage=evaluation and EVAL_GATE_* blockers exist | `tests/unit/test_transition_eval_gate.py`, `tests/unit/test_workflow_graph.py` | Failed eval gate cannot reach `done`, cannot write `workflow_summary`, and produces a blocked `eval_report` plus `blocked_report`; insufficient_baseline, stale_evidence, and missing_required_metric produce failed gate cases |
| Runtime Evidence Binding | `src/mod_agent/runtime/evidence.py`, `src/mod_agent/runtime/probe.py`, `src/mod_agent/workflow/graph.py`, `src/mod_agent/evaluation/gate.py` | `runtime_evidence` carries `feature_id`, build artifact ref/hash, run id, plugin-specific marker binding, screenshot refs, and non-goal preservation fields | `collect_runtime_evidence` consumes build artifact identity before writing runtime_evidence; existing failed/inconclusive evidence routing still enters repair | `tests/unit/test_runtime_evidence.py`, `tests/unit/test_transition_eval_gate.py`, `tests/unit/test_runtime_probe.py`, `tests/unit/test_workflow_graph.py` | Runtime success claims require real execution mode, build/run binding, plugin marker evidence bound to the acceptance contract, and no supplied non-goal preservation violation |
| MCP Server Transport | `src/mod_agent/mcp/protocol.py`, `src/mod_agent/mcp/tools.py`, future transport entrypoint | Tool result schema keeps `content`, `structuredContent`, `artifact_refs`, and `trace_refs`; dangerous tools remain hidden unless explicit approved routes exist | External tool calls never bypass LangGraph review/apply/runtime routes | `tests/unit/test_controlled_agent_mcp_protocol.py`, future transport smoke test | MCP client can initialize, list safe tools, call safe tools, and cannot execute write/runtime tools without approved route logic |
| Dense/RAG Production Path | `src/mod_agent/evidence/dense.py`, `src/mod_agent/evidence/retriever.py`, `src/core/settings.py` | `evidence_pack` records dense policy, failure policy, score semantics, trace refs, budget summary, and eval readiness | Required dense failure blocks evidence; optional dense failure degrades with visible blocker metadata | `tests/unit/test_vector_store_dense_provider.py`, `tests/unit/test_evidence_retrieval.py`, `tests/unit/test_workflow_graph.py` | Dense retrieval is auto-wired from settings, score semantics are normalized, required failures block, and eval/readiness can inspect retrieval quality |
| API/Dashboard Service Path | `src/mod_agent/api/http_server.py`, `src/mod_agent/dashboard/projections.py`, dashboard service modules | Dashboard projection separates artifact status, gate status, blockers, and capability recovery targets | API write/runtime operations route to approval and LangGraph-backed execution instead of direct side effects | `tests/unit/test_mod_agent_http_api.py`, `tests/unit/test_dashboard_projection.py` | API exposes inspectable state, blocks unauthorized side effects, and makes failed gates visible to consumers |
| ArtifactStore Production Hardening | `src/mod_agent/artifacts/store.py`, `src/mod_agent/artifacts/freshness.py` | Revision manifest/index, recovery records, lock metadata, migration/backfill records, and retention policy artifacts | Startup/preflight recovery runs before downstream reads; stale or unrecovered artifacts block consumers | `tests/unit/test_artifact_store.py`, `tests/unit/test_repair_checkpoint_smoke.py` | Interrupted writes, stale upstreams, concurrent writes, and revision history are recoverable and queryable |
| Planning Brief Knowledge Recovery | `src/mod_agent/planning/planning_brief.py`, `src/mod_agent/planning/feature_spec.py`, `src/mod_agent/evidence/retriever.py` | `mod_planning_brief` records retrieved experience refs, delivery lessons, evidence hashes, and selected plan provenance | `planning_brief` can route to retrieval-backed enrichment or blocked clarification | `tests/unit/test_planning.py`, `tests/unit/test_workflow_graph.py`, `tests/unit/test_mod_delivery_e2e.py` | Natural-language planning handoff is backed by retrieved evidence or explicit blockers, not only deterministic heuristics |
| Multimodal Evidence Recovery | `src/mod_agent/runtime/screenshots.py`, `src/ingestion/storage/image_storage.py`, `src/core/response/multimodal_assembler.py` | `screenshot_registry` and runtime evidence carry `image_refs`, metadata, captions, confidence, and visual limitations | Runtime visual evidence can feed evaluation/dashboard without claiming gameplay success alone | `tests/unit/test_image_storage.py`, `tests/unit/test_multimodal_assembler.py`, future screenshot registry tests | Screenshots are stored, referenced, projected, and evaluated as evidence with confidence and limitation metadata |
| Performance/Eval Recovery | `src/mod_agent/performance/budget.py`, `src/mod_agent/evaluation/gate.py`, evaluator modules | `eval_report` records baseline, budget, benchmark, consistency, and trace-matching summaries | Budget exceeded and missing baseline can block or degrade selected routes | `tests/unit/test_performance_budget.py`, `tests/unit/test_transition_eval_gate.py`, evaluator tests | Reliability or performance improvement claims require baseline evidence and focused eval results |

## Transition Queue

These tasks prepare the project for V2 without starting V2 expansion.

| Task | Width | Status | Scope | Unlocks |
| --- | --- | --- | --- | --- |
| TRANSITION-001 | M | completed | Eval Gate: module eval cases, false-continue/false-block checks, claim-boundary tests, review correctness, dry-run safety, insufficient_baseline, stale_evidence, missing_required_metric, eval_report artifact coverage, blocked eval_report envelope status, and hard routing from evaluate to blocked on failed gates | Safer V2 feature expansion |
| TRANSITION-002 | M | completed | Git Binding: git state snapshot, diff hash, proposal/base revision binding, rollback hint, and dirty-tree policy | Auditable real code changes |
| TRANSITION-003 | M | completed | Proposal Context Pack: Change Unit Model, evidence-backed context pack, scope boundary, no-op handling, and rollback hint propagation | Less guessing in patch proposals |
| TRANSITION-004 | M | completed | MCP JSON-RPC Wire Boundary: initialize, notifications/initialized, `tools/list`, `tools/call`, content, structuredContent, artifact_refs, trace_refs, JSON-RPC error behavior, and dangerous tool hidden/disabled policy | Safer external tool interface without claiming transport or production server integration |
| TRANSITION-005 | M | completed | Runtime Evidence Binding: `feature_id`, build artifact ref/hash, run id, plugin-specific marker binding, screenshot refs, non-goal preservation fields, and runtime claim-boundary tests | Reliable MISS-026 live GTFO validation |

## V2 Expansion Gate

Do not start broad V2 expansion until the transition queue is either completed
or the user explicitly accepts the named risk of skipping a task.

V2 expansion includes:

```text
production dense/RAG
real GTFO gameplay validation
production runtime automation
production HTTP API or dashboard service
multimodal vision pipeline
large benchmark harness
multi-provider or deployment work
```

The next recommended implementation task is `MISS-026` live GTFO gameplay validation if runtime automation is selected; otherwise choose one explicit recovery target above.
