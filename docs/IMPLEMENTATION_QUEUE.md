# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-25

Authority and reading order are defined only by `AGENTS.md` section 2.
Completed, frozen, review, and superseded records belong in
`docs/audits/LOOP_HISTORY.md`, not in this queue.

## 1. Current Queue

```text
current_queue: AGENT-HARNESS-RUNTIME-FAILURE-OWNERSHIP-001
selected_product_request: None
```

`AGENT-HARNESS-BUILD-RUNTIME-HANDOFF-001` completed H1.1 and moved to
`docs/audits/LOOP_HISTORY.md`. No H1.2 or H2-H6 task is selected
automatically. A later Harness boundary requires a new section 9 admission
review from `docs/audits/AGENT_HARNESS_TRANSITION.md`.

### AGENT-HARNESS-RUNTIME-FAILURE-OWNERSHIP-001

```text
task_id: AGENT-HARNESS-RUNTIME-FAILURE-OWNERSHIP-001
product_request_or_failure:
  H3 bounded Runtime failure ownership and repair routing. Preserved real run
  ec71c3a5 lost the earlier Chainloader marker through Harness output
  truncation, then stopped at blocked through REPAIR_SCOPE_UNRESOLVED even
  though the later accepted repair changed Runtime observation rather than Mod
  source.
exact_evidence:
  docs/PROJECT_STATE.md records RuntimeEvidence hash
  566a8a6554da0211bf7307d499803bea2592f7b3b927d1d6dcc6abe0abe574a6
  and run_result.json hash
  98a94df597e5f8c05b2acdf3b9767c3bffe4ac923c9588bf61e6fa134d6d1797;
  route_after_runtime_evidence sends every acceptance_verified=false result to
  create_repair_plan; _run_create_repair_plan sends every RuntimeEvidence
  failure to RepairPlanner.from_runtime_failure; that planner derives
  failure_class only from acceptance_status or verification_status and has no
  failure-owner decision before source-repair scope resolution.
affected_coverage_ids: WF-003, WF-005, EXEC-009, EXEC-010, MISS-008
dependencies:
  existing RuntimeEvidence, ArtifactStore hashes and lineage, RepairPlanner,
  repair_plan, conditional graph routes, blocked_report, Eval, Terminal, and
  current permission/admission contracts; H1.2 is not a dependency.
permissions_and_disclosure:
  local source edits and focused tests only; no external model disclosure,
  model call, GTFO launch, game-directory read/write, or gameplay evidence.
files_in_scope:
  src/mod_agent/runtime/evidence.py;
  src/mod_agent/runtime/gtfo_automation.py;
  src/mod_agent/repair/planner.py;
  src/mod_agent/workflow/graph.py;
  src/mod_agent/workflow/transitions.py;
  src/mod_agent/artifacts/registry.py;
  focused RuntimeEvidence, repair-loop, workflow-graph, and GTFO-provider tests.
focused_verification:
  python -m pytest -q tests/unit/test_runtime_evidence.py
  tests/unit/test_repair_loop.py tests/unit/test_workflow_graph.py
  tests/unit/test_gtfo_runtime_automation.py --tb=short -p no:cacheprovider;
  python -m compileall -q src; git diff --check.
stop_condition:
  stop after focused tests prove durable provider-neutral Runtime failure
  ownership; only product-behavior failures with existing bound source evidence
  may enter the current Proposal/Review path; observation, environment,
  provider, permission, and unknown failures produce an owner-specific
  fail-closed repair/terminal result without another model, Proposal, Apply, or
  Build; then perform Phase B authority-document repair.
status: active
```

The affected baseline currently has one separately recorded failure:
`test_graph_failed_build_enters_repair_and_stops_at_retry_budget` expects
`retry_exhausted=true` while the current result is false. H3 implementation
must reconcile that existing same-path baseline without weakening its
assertion or counting it as a new H3 regression.

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
