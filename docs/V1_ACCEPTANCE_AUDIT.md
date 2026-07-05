# V1 Acceptance Audit

Last updated: 2026-07-05

This audit maps the current implementation back to the V1-related requirements in
`DEV_SPEC.md`. It is not a replacement for `docs/SPEC_COVERAGE_MATRIX.md`.

## Source Sections

```text
DEV_SPEC.md 48.9  Dashboard / MCP / API Upgrade Requirements
DEV_SPEC.md 49.1.4 Conditional Edge Matrix
DEV_SPEC.md 49.7  Dashboard, MCP, API, CLI Data Plane
DEV_SPEC.md 50.2  Recommended Framework Decisions
DEV_SPEC.md 50.3  Evidence Decision Layer
DEV_SPEC.md 50.4  V1 Framework Cut
DEV_SPEC.md 50.6  Token and Context Budget Policy
DEV_SPEC.md 50.9  V1 implementation-level architecture reference
```

## Current Result

```text
status: implemented_with_known_gaps
last_completed_queue_task: V1-AUDIT-002
current_audit_task: V1-AUDIT-003
```

V1 can currently claim a controlled local contract path for workflow, artifacts,
deterministic evidence, review gates, dry-run/build/runtime contracts, repair,
eval contracts, read-only/report-only MCP facade tools, dashboard projection,
and performance budget contracts.

V1 cannot currently claim production-grade dense retrieval, production frontend,
wire-level MCP JSON-RPC compliance, real performance benchmarking, or full real
runtime branch coverage.

## Requirement Checks

| Area | V1 audit result | Evidence | Remaining gap |
| --- | --- | --- | --- |
| Controlled workflow | contract covered for fake/local path | Q-011 through Q-015, R-012, V1-AUDIT-002, repair checkpoint smoke | full real runtime branch E2E remains open in matrix rows WF-003/WF-005 |
| Acceptance | contract linkage covered for fake/local path | V1-AUDIT-002 carries FeatureSpec acceptance contract into runtime_evidence and eval_report with strict acceptance_verified routing | real/manual/supplied runtime acceptance evidence path remains unverified |
| Retrieval | V1 deterministic path covered | BM25/symbol/readiness rows RET-001 through RET-008 | RRF, rerank, and real dense provider remain future work |
| Dense provider boundary | test-only fake provider gated | `load_settings(..., allow_test_providers=True)` is required for `retrieval.dense_provider=fake` | real provider index/query API remains deferred |
| MCP | facade contract covered | Q-021 read-only/report-only tool surface | final JSON-RPC adapter must map unknown tool names to protocol error, tracked by MISS-020 |
| Dashboard | projection covered | R-013 dashboard projection and Q-021/Q-022 summaries | production dashboard completeness is not a V1 claim |
| Budget | contract covered | Q-020 budget policy and Q-022 dense budget summary | real batch orchestration and benchmark harness remain MISS-013 |

## Dense Retrieval Boundary

Q-022 is a contract-level dense retrieval task only.

```text
allowed claim: disabled-by-default dense retrieval provider contract exists
allowed claim: fake provider supports unit-test contract verification
forbidden claim: real embedding/vector database retrieval is implemented
forbidden claim: dense retrieval can replace BM25/symbol V1 evidence gates
```

`FakeDenseRetrievalProvider` returns configured chunk-id scores. It is now
blocked from normal settings loading unless the caller explicitly passes
`allow_test_providers=True`.

## Next Recommended Task

```text
task_id: V1-AUDIT-003
goal: verify real/manual/supplied runtime acceptance evidence behavior before any V1 acceptance claim
inputs: MISS-022, WF-003, WF-005, EXEC-005, EXEC-006, DEV_SPEC.md 49.1.4 and 50.9.3
tests: focused runtime evidence, workflow routing, repair, eval, and artifact contract tests
```
