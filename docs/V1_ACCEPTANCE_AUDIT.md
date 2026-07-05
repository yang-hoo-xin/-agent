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
status: contract_path_accepted_with_known_gaps
last_completed_queue_task: V1-AUDIT-005
current_audit_task: none
```

V1 can currently claim a controlled local contract path for workflow, artifacts,
deterministic evidence, review gates, dry-run/build/runtime contracts, repair,
eval contracts, read-only/report-only MCP facade tools, dashboard projection,
and performance budget contracts.

V1 cannot currently claim real runtime acceptance, production-grade dense
retrieval, production frontend, wire-level MCP JSON-RPC compliance, real
performance benchmarking, or full real runtime branch coverage.

## Requirement Checks

| Area | V1 audit result | Evidence | Remaining gap |
| --- | --- | --- | --- |
| Controlled workflow | contract covered for fake/local path with explicit V1 acceptance blocker | Q-011 through Q-015, R-012, V1-AUDIT-002, V1-AUDIT-003, V1-AUDIT-004, repair checkpoint smoke | full real runtime branch E2E remains open in matrix rows WF-003/WF-005 |
| Acceptance | contract linkage covered for fake/manual/supplied builder paths, and fake/local workflow completion cannot claim V1 accepted | V1-AUDIT-002 carries FeatureSpec acceptance contract into runtime_evidence and eval_report with strict acceptance_verified routing; V1-AUDIT-003 verifies manual/supplied evidence must support every acceptance_criteria entry in acceptance_contract; V1-AUDIT-004 adds v1_acceptance_status and v1_acceptance_blockers to eval_report and workflow_summary | automated real runtime branch E2E remains unimplemented |
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

## Real Runtime Boundary

The current graph still uses the fake/local runtime evidence builder for the
controlled workflow tail. V1-AUDIT-004 makes that boundary explicit in
`eval_report` and `workflow_summary`.

```text
fake/local requested_behavior_status: may be verified for the contract fixture
fake/local v1_acceptance_status: blocked
required blockers: REAL_BUILD_EVIDENCE_MISSING and REAL_RUNTIME_EVIDENCE_MISSING
forbidden claim: fake/local workflow completion is real V1 runtime acceptance
```

The `v1_acceptance_status` and `v1_acceptance_blockers` fields are V1 audit
boundary fields. They are intentionally not generalized in this audit; a later
release policy layer can replace them with a release-neutral acceptance policy
result if the project needs multiple release tracks.

## Final Verdict

```text
V1 contract path verdict: accepted with known gaps
Real runtime acceptance verdict: not accepted
Reason: automated real runtime execution and real runtime evidence collection are still unimplemented.
Allowed claim: controlled local contract path is implemented and tested.
Forbidden claim: the project has real runtime V1 acceptance.
```

## Queue Handoff

```text
V1 audit queue: completed
If the next goal is real V1 runtime acceptance: start from MISS-022 real runtime collector/E2E.
If the next goal is feature expansion: select the next task from docs/SPEC_COVERAGE_MATRIX.md open gaps.
Do not claim real runtime success until MISS-022 is closed by implementation and tests.
```
