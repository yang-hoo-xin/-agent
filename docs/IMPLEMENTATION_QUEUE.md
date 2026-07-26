# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-26

Authority and reading order are defined only by `AGENTS.md` section 2.
Completed, frozen, review, and superseded records belong in
`docs/audits/LOOP_HISTORY.md`, not in this queue.

## 1. Current Queue

```text
current_queue: AGENT-HARNESS-H3-REAL-RUNTIME-ACCEPTANCE-001
selected_product_request: Prove the implemented H3 observation-failure ownership route in one controlled real GTFO Runtime resume without re-entering source repair
```

```text
task_id: AGENT-HARNESS-H3-REAL-RUNTIME-ACCEPTANCE-001
product_request_or_failure: Real run e7daa266 proved the accepted automated Runtime route, while WF-005 records that no failing non-source owner route has been real-exercised. Run one fresh Build-to-Runtime lineage whose startup, process, deployment, restoration, and screenshot collection remain valid while one deliberately defined acceptance marker is absent. The expected terminal result is blocked observation ownership, not product source repair.
exact_evidence: Current src/mod_agent/runtime/gtfo_automation.py maps incomplete acceptance observation to owner observation and failure_class runtime_observation_incomplete; src/mod_agent/repair/planner.py maps observation to RUNTIME_OBSERVATION_REPAIR_REQUIRED with source_repair_allowed false. Tests exercise this locally. Accepted real run e7daa266 proves the corresponding deployment, launch, marker collection, restoration, and Build-checkpoint resume path, but docs/SPEC_COVERAGE_MATRIX.md WF-005 explicitly records that a failing non-source owner route remains without real execution evidence.
affected_coverage_ids: WF-005, EXEC-006, EXEC-009, EXEC-010, MISS-026E, MISS-026F
dependencies: Repository HEAD 2f0d0aa49e23218a463188e12d129862fa7783d2; completed H1.1 Build-to-Runtime handoff; completed H3 failure ownership; a new compile-only run and fresh Build checkpoint; one run-local Runtime configuration whose exact deliberately absent marker is verified absent from current source and pre-run logs.
permissions_and_disclosure: No external model or external source disclosure is authorized. One local Ollama compile-only delivery lineage may be prepared under the existing local-provider gates and must stop for its new exact-diff approval. DLL deployment, game-directory write, GTFO launch, process termination, log/screenshot collection, and restoration require a later separate one-run approval after no-launch preflight and Build checkpoint. No retry is authorized.
files_in_scope: docs/IMPLEMENTATION_QUEUE.md and docs/PROJECT_STATE.md for admission; one ignored run-local settings file and normal ignored run Artifacts for execution. Platform source, canonical Mod source, and game files are not implementation edit targets.
focused_verification: Before Runtime, verify current source/log absence of the deliberate marker, no GTFO process, destination/restoration state, configuration SHA256, Build Artifact identity, and checkpoint freshness. After resume, verify RuntimeEvidence failure_ownership, RepairPlan blocker and retry state, zero resume-stage model calls, no repeated upstream stage or new Proposal/Dry-run/Apply/Build revision, blocked terminal result, process exit, destination restoration, and configuration hash preservation.
stop_condition: Stop at the new exact-diff approval boundary; then stop again before deployment/launch for separate physical Runtime approval. After one approved Runtime attempt, record either the first bound negative-path result or one immutable failure, clean the environment, return the queue to None, and do not activate H1.2, H2, H4-H6, Phase 2C, or any new Migration Boundary.
status: active
```

`AGENT-HARNESS-RUNTIME-FAILURE-OWNERSHIP-001` completed H3 Phase A and Phase B
and moved to `docs/audits/LOOP_HISTORY.md`. No later Harness boundary is
selected. H1.2, H2, and H4-H6 remain inactive pending a separate admission
trigger and review.

`AGENT-HARNESS-BUILD-RUNTIME-HANDOFF-001` completed H1.1 and moved to
`docs/audits/LOOP_HISTORY.md`. No H1.2 or H2-H6 task is selected
automatically. A later Harness boundary requires a new section 9 admission
review from `docs/audits/AGENT_HARNESS_TRANSITION.md`.

`PHASE2B-BETTERHITFEEDBACK-ENABLED-001` completed its selected real-runtime
claim boundary and moved to `docs/audits/LOOP_HISTORY.md`.

`V2-RUNTIME-TERMINAL-CHAIN-001` also completed and moved to
`docs/audits/LOOP_HISTORY.md`; it does not leave a continuing infrastructure
task in the active queue.

The two known Harness observability defects remain recorded but do not activate
a platform task by themselves: successful raw Patch Generation response
persistence is missing, and the nested pre-call model count can remain stale.
They may enter the queue only when a selected product run is blocked or its
claim cannot be reconstructed because of one of those defects.

## 2. Entry Rule

A task may enter the active queue only when all of the following are recorded:

1. one concrete product capability, real Mod request, observed failure, or
   bounded product decision;
2. exact current source/configuration/log evidence for the touched identifiers;
3. explicit dependencies and permission/disclosure boundaries;
4. the affected coverage rows and focused verification command;
5. a stopping condition that returns work to the product mainline.

Do not activate work solely because a SPEC, frozen plan, historical review, or
open gap describes it.

## 3. Conditional Work

| Work area | Trigger required before queue entry | Current disposition |
| --- | --- | --- |
| ProposalCritic external-model adapter | A selected proposal-review task explicitly requires a separate model assessment, exact data disclosure is approved for that run, and the local/injected boundary is insufficient | Conditional; local/injected boundary only |
| Specialist fan-out or bounded ReAct | A selected task contains separable risk dimensions or an observed fixed-step failure that changes a decision | Conditional; no always-on swarm or top-level ReAct migration |
| Reference/community knowledge loader | Authentic, traceable material exists and a selected product task cannot proceed adequately with current source/live reads | Conditional; community synthetic fixture remains plumbing only |
| Symbol/structured retrieval deepening | A selected product task records a structural lookup failure that current `rg` plus live reads cannot resolve efficiently | Conditional; current retrieval direction remains `rg` plus live reads |
| Formal retrieval validation | A precise promotion-grade or cross-project claim is required | Conditional; Arms A-G and H1-H5 are not active |
| Dense, RRF, rerank, or Agentic routing | A recorded semantic-recall failure persists after deterministic retrieval and a bounded decision experiment is approved | Conditional; no production RAG direction is active |
| Dashboard polish | A real operator or demonstration task records an inspection gap in existing artifact projections | Conditional |
| MCP write/runtime route | A selected external MCP client must drive an approved controlled workflow action | Conditional; read/report boundary remains sufficient |
| GTFO launch, copy, or gameplay evidence | A selected Mod acceptance criterion requires it and the user separately approves exact launch/copy actions | Conditional |
| Production ArtifactStore hardening | A real delivery task exposes recovery, concurrency, history-query, migration, or retention failure | Conditional |
| Long-term memory/closed-loop automation | Repeated verified tasks expose a recurrence or retrieval failure that manually recorded lessons cannot solve | Conditional; history is not trusted policy memory |

## 4. Task Record Template

When a task is activated, add only this bounded record:

```text
task_id:
product_request_or_failure:
exact_evidence:
affected_coverage_ids:
dependencies:
permissions_and_disclosure:
files_in_scope:
focused_verification:
stop_condition:
status: active
```

Move the record to `docs/audits/LOOP_HISTORY.md` when it becomes completed,
frozen, superseded, or review-only. Do not keep a second completed-work table in
this file.
