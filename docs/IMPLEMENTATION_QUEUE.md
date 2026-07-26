# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-26

Authority and reading order are defined only by `AGENTS.md` section 2.
Completed, frozen, review, and superseded records belong in
`docs/audits/LOOP_HISTORY.md`, not in this queue.

## 1. Current Queue

```text
current_queue: AGENT-HARNESS-H3-POSTFIX-REAL-RUNTIME-ACCEPTANCE-001
selected_product_request: Prove the repaired multi-generation Runtime observation path in one controlled real GTFO negative acceptance without re-entering source repair
```

```text
task_id: AGENT-HARNESS-H3-POSTFIX-REAL-RUNTIME-ACCEPTANCE-001
product_request_or_failure: Real run 06c09532 proved deterministic observation-owner routing but could not establish the intended single-missing-marker condition because its final current-run window also lacked Chainloader and chain_probe=true. Commit c8c91b31dcc344ff08960ecc3d4c83980c35a6d2 repairs cross-poll and cross-generation marker retention. Run one new Build-to-Runtime lineage in which h3_observation_negative_probe=absent is deliberately absent and the other current-run markers remain bound.
exact_evidence: Preflight on 2026-07-26 found no GTFO process, no deployed BetterHitFeedback.dll, canonical Plugin.cs SHA256 b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c with neither test marker, zero h3_observation_negative_probe=absent occurrences in the current BepInEx log, BepInEx.cfg SHA256 cad94700be6c79cbe6efbf6e953fead502b9c5723ee67cc1fb19e63c94326616, and exactly AppendLog = false under [Logging.Disk]. Commit c8c91b3 and 244 focused tests provide the local repair evidence; run 06c09532 remains immutable inconclusive history.
affected_coverage_ids: WF-005, EXEC-006, EXEC-009, EXEC-010, MISS-026E, MISS-026F, MISS-026G
dependencies: Repository HEAD c8c91b31dcc344ff08960ecc3d4c83980c35a6d2; completed H1.1 handoff/resume; completed H3 ownership routing; completed RUNTIME-OBSERVATION-MULTISNAPSHOT-001; one new isolated delivery lineage, exact-diff binding, Build checkpoint, and run-local GTFO settings.
permissions_and_disclosure: The user authorized this complete one-run scope on 2026-07-26, including local Ollama use, isolated write and Build, DLL deployment, game-directory write, GTFO launch and termination, log/process-diagnostic/screenshot collection, restoration, evidence documentation, and Git closure. No external provider or external source disclosure is authorized. Isolated Apply may continue unattended only if the fresh no-write diff is byte-for-byte identical to the previously user-approved chain_probe=true Plugin.cs replacement and all fresh binding checks pass; otherwise the run must stop before write. No Runtime retry is authorized.
files_in_scope: docs/IMPLEMENTATION_QUEUE.md and docs/PROJECT_STATE.md for admission and later closure; one ignored run-local settings file and normal ignored run Artifacts; isolated BetterHitFeedback Plugin.cs for the exact previously reviewed replacement. Canonical Mod source and other platform source are not edit targets.
focused_verification: Before Runtime, verify fresh source/binding identity, exact no-write diff equality, successful Build Artifact and checkpoint, deliberate-marker absence, GTFO process absence, destination pre-state, BepInEx.cfg binding, and configuration hash. After Runtime, require BepInEx, Chainloader, and chain_probe=true observations bound to current-run source_window identities; only h3_observation_negative_probe=absent may remain missing. Verify owner observation, source_repair_allowed false, RUNTIME_OBSERVATION_REPAIR_REQUIRED, retry_count zero, no resume-stage model call or repeated upstream stage, no new Proposal/Dry-run/Apply/Build revision, blocked terminal, bounded non-authoritative process_diagnostics, process exit, destination restoration, and configuration hash preservation.
stop_condition: After exactly one Runtime attempt, preserve its result whether the stronger condition passes or fails, clean the physical environment, return the queue to None, record the evidence boundary, and do not activate Phase 2C, H1.2, H2, H4-H6, a retry, or a broader Harness expansion.
status: active
```

`RUNTIME-OBSERVATION-MULTISNAPSHOT-001` completed the bounded observation
repair triggered by `06c09532` and moved to `docs/audits/LOOP_HISTORY.md`.
The selected post-fix Runtime acceptance uses a new V2TA/M lineage and new
Build under the explicit one-run permission recorded above.

`AGENT-HARNESS-H3-REAL-RUNTIME-ACCEPTANCE-001` completed one separately
authorized real Runtime attempt and moved to `docs/audits/LOOP_HISTORY.md`.
Run `06c09532` real-exercised the implemented observation-owner blocked route
without a resume-stage model call or repeated upstream delivery stage. The
stronger single-missing-marker experiment condition did not hold because the
current-run log window also lacked `Chainloader` and `chain_probe=true`; no
retry or automatic repair is selected.

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

Run `06c09532` remains immutable historical inconclusive evidence. Its bounded
observation diagnosis produced `RUNTIME-OBSERVATION-MULTISNAPSHOT-001`; the
repair does not rewrite that run or promote its result.

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
