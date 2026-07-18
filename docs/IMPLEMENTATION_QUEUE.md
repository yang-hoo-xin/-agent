# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-16

Authority and reading order are defined only by `AGENTS.md` section 2.
Completed, frozen, review, and superseded records belong in
`docs/audits/LOOP_HISTORY.md`, not in this queue.

## 1. Current Queue

```text
current_queue: None
selected_product_request: None
```

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-015` completed exactly one authorized
post-014 local real-model run and moved to `docs/audits/LOOP_HISTORY.md`. Prompt
v6 did not expose the old copyable query value, but the model used the same five
zero-result behavioral symbol strings across both sources and then twice
returned to an already executed source/tool/arguments signature. The repeat
validator stopped the run before any method_id, IL inspection, or model finish.
All three formal gates failed; no rerun or repair is selected automatically.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-014` completed the deterministic repair and
moved to `docs/audits/LOOP_HISTORY.md`. Prompt v6 removes value-like query
examples, shares finish decision/open-gap constraints with initial and
correction context, and reports valid metadata-derived method provenance
independently from final convergence. No real model ran and no rerun is
selected automatically.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-013` completed exactly one same-model local
replication and moved to `docs/audits/LOOP_HISTORY.md`. It reached metadata-to-
IL without an executed repeat but exhausted finish correction and failed all
three formal gates. No automatic retry or repair is selected.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-012` completed the selected deterministic
query-semantics and pre-execution exact-repeat repair and moved to
`docs/audits/LOOP_HISTORY.md`. It did not call a real model. A same-model local
rerun is not implied and requires a separately selected task.

The ProposalCritic documentation/contract cleanup is complete and did not
activate a product-expansion task. `WALLCRAWLER-INTELLIGENT-EVIDENCE-006` has
completed its one approved real-model execution and moved to
`docs/audits/LOOP_HISTORY.md`; its exact bounded repair was selected as 007.
`WALLCRAWLER-INTELLIGENT-EVIDENCE-007` completed that local repair and is also
archived there. `WALLCRAWLER-INTELLIGENT-EVIDENCE-008` was the selected one-run
external acceptance; it completed exactly once and is archived in
`docs/audits/LOOP_HISTORY.md`. Its bounded compact-IL/context repair completed
as `WALLCRAWLER-INTELLIGENT-EVIDENCE-009` with 75 focused tests passing and is
also archived there. 010 was blocked before process creation. 011 completed one
loopback-only local-model run and is archived with failed capability,
convergence, and semantic gates. Its bounded 012 repair is also complete; no
new task is selected automatically.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-004` is completed and recorded in current
state/history; it is not retained as an active queue item. A real external-model
Evidence run requires a new explicit per-run disclosure approval and does not
implicitly unlock Proposal-only or Mod implementation.

Its acceptance-hardening insertion is also complete: conclusion classification,
durable sanitized trace hashes, truthful multi-source selection accounting, and
the two-source machine-local registry were added without creating an active
queue item. The next real-model run still requires explicit disclosure.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-005` is also completed and moved to current
state/history. It adds the provider-neutral structured Agent-turn boundary,
locally tested Qwen Chat and OpenAI Responses adapters, compact trajectory
reconstruction, focused metadata observations, and stricter trajectory-level
acceptance. No external model was called. A real Qwen semantic run remains a
separate execution requiring a new per-run disclosure approval; it is not an
active infrastructure task and cannot cross the evidence-only stop boundary.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-006` then ran that real Qwen path once. It
stopped correctly at `evidence_retrieval` but exhausted 8 model steps and all 6
tool calls after six metadata searches, no IL inspection, and two rejected
finish objects. The exact bounded repair direction is to expose the full nested
finish schema and current IL/conclusion acceptance state to the model;
`WALLCRAWLER-INTELLIGENT-EVIDENCE-007` completed only that repair with 70
focused tests passing. V2-C remains unresolved until a separately selected and
approved real-model rerun exercises it. That rerun completed as 008: it fixed
the 006 convergence and finish-shape failures but exposed one exact compact-IL
representation and inspection-citation failure. No repair was selected
automatically. The user then selected 009 to repair only that failure and
the directly observed repeated-context growth. That repair is complete; a new
real-model run is not implied or authorized.

The confirmed V2 product direction is specified in `DEV_SPEC.md` section 51:
controlled intelligent input, a bounded Evidence loop, an approved real
WallCrawler model run, and only then one failure-driven capability or loop
repair when the run proves it is needed. This direction is not a preactivated
consecutive queue. A later external real-model rerun requires explicit task
selection plus disclosure approval. A local real-model rerun requires a
separately selected task and the literal-loopback boundary. Every result stops
at `evidence_retrieval` and may only recommend a later bounded repair or
separately selected Proposal-only task.

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
