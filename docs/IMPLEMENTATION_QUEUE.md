# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-23

Authority and reading order are defined only by `AGENTS.md` section 2.
Completed, frozen, review, and superseded records belong in
`docs/audits/LOOP_HISTORY.md`, not in this queue.

## 1. Current Queue

```text
current_queue: PHASE2B-BETTERHITFEEDBACK-ENABLED-001
selected_product_request: Make BetterHitFeedback General.Enabled control startup patch registration
```

```text
task_id: PHASE2B-BETTERHITFEEDBACK-ENABLED-001
classification: Phase 2B meaningful product slice
product_request: Make the existing BetterHitFeedback General.Enabled configuration control startup patch registration. When false, emit one structured disabled marker and return before Harmony.PatchAll. When true, preserve current behavior. Configuration changes take effect on the next plugin load; runtime hot-toggle support is not included.
canonical_source: C:\Users\10160\PycharmProjects\pythonProject3\generated_mods\BetterHitFeedback
source_revision: repository HEAD 0fd187246a437d43ceb539903275b9c8e77dad4b; BetterHitFeedback tree 6e8c3d5f704b7ede8a7fe9e13946a104e81d0676; complete snapshot SHA256 c6fa81b35ca6005dc9091beca601d82afcf180b593b9926b77f642fe37f4f30f; Plugin.cs raw SHA256 b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c
write_scope: A fresh isolated workspace; only generated_mods/BetterHitFeedback/Plugin.cs may change. Canonical source remains read-only.
model_authorization: Exactly one local Ollama patch-generation call after current /api/tags confirms model qwen3:4b-instruct and digest 0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0. Base URL is literal loopback http://127.0.0.1:11434; destination is /api/chat; external disclosure, provider fallback, automatic retry, and any external call are prohibited.
build_authorization: Fresh isolated workspace, baseline and final dotnet build, and read-only DLL metadata/IL inspection are approved. No final source build before exact-diff approval.
runtime_authorization: After an approved apply and verified build, controlled game-directory copy and two GTFO launch modes are approved for General.Enabled=false and true. Each mode must bind configuration state, DLL SHA256, run identity, current-run logs, process identity, and applicable acceptance markers. No gameplay claim may be inferred from build or IL alone.
acceptance: Evidence proves ConfigEnabled is bound but unread and PatchAll is unconditional; one-file implementation binding; deterministic review; no-write dry-run; separate exact diff-hash approval; isolated apply; baseline/final build; compiled GUID local.betterhitfeedback, name BetterHitFeedback, version 0.1.0 unchanged; compiled Plugin.Load contains the approved false-before-PatchAll branch; canonical snapshot unchanged; false-mode real runtime records the disabled marker and no current-run PATCH_APPLIED/HOOK_TRIGGERED marker; true-mode real runtime records PATCH_APPLIED and preserves current enabled behavior.
stop_condition: Stop on source drift, any edit outside Plugin.cs, GUID/name/version change, visual/audio change, runtime hot-toggle work, missing exact-diff approval, provider fallback/retry, build failure, compiled-identity mismatch, unbound runtime logs, or any need to modify platform code. Do not claim product-slice completion from build/IL evidence alone.
status: blocked_on_bcc045f6_upstream_validation_omitted; runs 608f67d9, c213e978, 58df438b, f8e6c814, ae6f408b, b237e35e, 6ea884bf, 230e70a6, 3360a57e, 34000b2b, and bcc045f6 remain immutable. The bounded source/member Evidence repair passes 213 direct and affected tests and the read-only 230e70a6 replay. The context-admission repair passes 202 affected tests and is verified by real run bcc045f6: `num_ctx=32768` admitted the 6,034-token prompt and Ollama completed normally. Deterministic Patch admission then rejected the parsed response as `upstream_validation_omitted` because it omitted the exact authoritative `compile or static validation` entry already present in the prompt and Implementation Plan. The run stopped before Proposal and Dry-run with no write. Its one-call authorization is exhausted; no retry or admission-rule change is authorized. The blocked external Retry1 remains unused and must not execute.
```

Working-tree update: the bounded context-admission repair is implemented,
passes 121 direct and 202 affected no-model tests, and passed real request
admission in run `bcc045f6`. The run sent `num_ctx=32768`, Ollama completed
normally, and deterministic Patch admission correctly stopped the parsed
response before Proposal because one authoritative validation entry was
omitted. Current execution status is
`blocked_on_bcc045f6_upstream_validation_omitted`; the next action is a bounded
decision about validation ownership and regression preservation, not an
automatic retry.

Harness reliability is a tracked diagnostic consideration, not a new queue.
Subsequent failures must distinguish workspace/build integration, provider
request admission, model output, and correct deterministic rejection. Broader
Harness simplification requires repeated cross-stage evidence after bounded
repairs and may not weaken review, approval, write, build, or runtime gates.
Run `bcc045f6` specifically exposes possible representation friction from
requiring the model to repeat a deterministic upstream validation string.
Changing that contract must preserve the behavior-omission detection established
by run `608f67d9`; this record does not authorize silent list union, weaker
admission, another model call, or platform expansion.

Run `054fe2df` is an immutable baseline-build failure caused by denied access to
the user-level NuGet configuration; graph invocation and model-call count both
remained zero. The limited NuGet-isolated build repair is verified: baseline
and final build now share profile
`v2_codegen_real_local_dotnet_nuget_isolated`, the focused suite passed 67
tests, and real baseline canary `nuget_isolated_build_canary_001` passed restore,
`--no-restore` build, and DLL identity inspection inside the restricted
workspace. This removes the observed user-level NuGet config/cache dependency
only; it does not claim a fully hermetic build. That build repair itself created
no replacement Phase 2B run.

Run `608f67d9` is the first post-build-repair local product run. Baseline and
one local Patch Generation call completed, but no-write Dry-run failed on an
LF/CRLF exact-source mismatch. No write occurred. Its Proposal also omitted the
claimed configuration guard and disabled branch, while Review had allowed
Dry-run. The bounded follow-up now requires every generated change to preserve
all validation requirements from its bound Implementation Plan change and
rechecks that coverage in ProposalReviewer by edit binding. A no-model replay
blocks the preserved bad response as `upstream_validation_omitted`; 138 direct
and affected tests plus 22 CLI tests pass. This is not control-flow semantic
verification. `608f67d9` remains immutable, and no replacement run or model call
was created during the repair.

`V2-PATCH-APPLIER-EOL-001` and `PHASE2A-DELIVERY-CANARY-001` completed and
moved to `docs/audits/LOOP_HISTORY.md`. Run `42c5d93c` remains the immutable
successful Phase 2A record.

V2-C is frozen as a `V2 intelligence-loop validation spike` and has no
continuing product route. Its real-run record remains
`source_binding_status=missing`.

`V2 Agent runtime path reconstruction` is a pending read-only task type only.
It has no task id, is not an active queue item, and is not a permanent product
gate.

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
focused tests passing. At that historical checkpoint V2-C remained unresolved
until a separately selected and approved real-model rerun exercised it. That
rerun completed as 008: it fixed
the 006 convergence and finish-shape failures but exposed one exact compact-IL
representation and inspection-citation failure. No repair was selected
automatically. The user then selected 009 to repair only that failure and
the directly observed repeated-context growth. That repair is complete; a new
real-model run is not implied or authorized.

`DEV_SPEC.md` section 51 now classifies that sequence as the frozen V2-C
experiment and places read-only runtime-path reconstruction before any later
product gate. The reconstruction itself is not preactivated and does not
authorize another V2-C rerun or Proposal-only task.

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
