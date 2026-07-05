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
status: real_runtime_evidence_branch_accepted_with_known_gaps
last_completed_queue_task: MISS-022
current_audit_task: none
```

V1 can currently claim a controlled local contract path for workflow, artifacts,
deterministic evidence, review gates, dry-run/build/runtime contracts, repair,
eval contracts, read-only/report-only MCP facade tools, dashboard projection,
and performance budget contracts.

V1 can now claim a tested real runtime evidence branch through an injected
runtime_evidence_factory and explicit runtime probe payload. V1 still cannot
claim production-grade runtime automation, production-grade dense retrieval,
production frontend, wire-level MCP JSON-RPC compliance, real performance
benchmarking, or full production runtime branch coverage.

## Requirement Checks

| Area | V1 audit result | Evidence | Remaining gap |
| --- | --- | --- | --- |
| Controlled workflow | contract covered for fake/local path and tested real runtime evidence path | Q-011 through Q-015, R-012, V1-AUDIT-002, V1-AUDIT-003, V1-AUDIT-004, MISS-022, repair checkpoint smoke | production runtime launcher/log collector remains open |
| Acceptance | contract linkage covered for fake/manual/supplied builders and injectable real runtime probe evidence | V1-AUDIT-002 carries FeatureSpec acceptance contract into runtime_evidence and eval_report with strict acceptance_verified routing; V1-AUDIT-003 verifies manual/supplied evidence must support every acceptance_criteria entry in acceptance_contract; V1-AUDIT-004 adds v1_acceptance_status and v1_acceptance_blockers to eval_report and workflow_summary; MISS-022 adds build_real_runtime_evidence_payload and a graph E2E test that reaches v1_acceptance_status=accepted with local build and real runtime probe evidence | production runtime launcher/log collector remains open |
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

The default graph still uses the fake/local runtime evidence builder for the
controlled workflow tail. MISS-022 adds an injected real runtime evidence branch
for tests and future adapters. V1-AUDIT-004 keeps the default fake/local
boundary explicit in `eval_report` and `workflow_summary`.

```text
fake/local requested_behavior_status: may be verified for the contract fixture
fake/local v1_acceptance_status: blocked
required blockers: REAL_BUILD_EVIDENCE_MISSING and REAL_RUNTIME_EVIDENCE_MISSING
forbidden claim: fake/local workflow completion is real V1 runtime acceptance
real runtime probe path: can reach v1_acceptance_status=accepted when local build and real runtime evidence are both verified
```

The `v1_acceptance_status` and `v1_acceptance_blockers` fields are V1 audit
boundary fields. They are intentionally not generalized in this audit; a later
release policy layer can replace them with a release-neutral acceptance policy
result if the project needs multiple release tracks.

## Final Verdict

```text
V1 contract path verdict: accepted with known gaps
Real runtime evidence branch verdict: accepted with known gaps
Reason: injectable local build plus real runtime probe evidence reaches v1_acceptance_status=accepted in graph tests.
Allowed claim: controlled local contract path and injectable real runtime evidence branch are implemented and tested.
Forbidden claim: the project has production runtime automation or a production game process launcher.
```

## Queue Handoff

```text
V1 audit queue: completed
MISS-022 real runtime evidence branch: completed
If the next goal is production runtime automation: start from MISS-026 production runtime launcher/log collector.
If the next goal is feature expansion: select the next task from docs/SPEC_COVERAGE_MATRIX.md open gaps.
Do not claim production runtime automation until MISS-026 is closed by implementation and tests.
```
