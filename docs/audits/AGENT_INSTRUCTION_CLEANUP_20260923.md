# Agent instruction and workflow maintenance — 2026-09-23

Status: bounded implementation and independent review complete.
One workflow checkpoint assertion remains failed, as recorded below.

## Overall assessment and boundary

The observed problems are stale instructions, overly broad skill triggers,
mechanical verification requirements and duplicated implementation with divergent
behavior. They are not evidence that fewer rules always improve a model, or that
the product's binding and execution checks should be weakened.

This change targets repository instructions, the five active repository skills,
their direct helpers, the existing workflow and the explicitly added
`src/mod_agent/local_entry.py`. External lookups are limited to exact references
needed to decide whether a listed symbol has callers. Frozen playbooks are not
loaded or restored. Existing WIP, original model runs, permissions, budgets and
product artifacts are not reset or relabeled as successful.

The official guidance used is:

- [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra): narrow skill descriptions, progressive disclosure, contextual reading, and reconsideration of old scaffolding.
- [GPT-6 testing and verification guidance](https://developers.openai.com/api/docs/guides/latest-model#testing-and-verification): meaningful checks proportional to the change, with broader or repeated checks justified by new changes, failures or unresolved concerns.

| Guidance actually used | Application here | Limit of the inference |
|---|---|---|
| Short, discriminating skill descriptions | Ordinary test requests must not select an all-system QA itinerary. | Shortness alone does not establish correct skill selection. |
| Progressive disclosure and contextual repository reading | Keep references discoverable and read the relevant mode; remove a mandatory cognition/document prelude. | Concrete callers and fragile contracts still need inspection. |
| Reconsider elaborate recipes written for older models | Remove fixed retry counts, fabricated résumé metrics and mandatory boilerplate resources. | Deterministic identity, persistence and permission checks remain necessary where code depends on them. |
| Define completion and avoid unnecessary approval pauses | Continue authorized maintenance through its declared verification; distinguish recoverable feedback from executor defects. | This does not authorize new model disclosure, product Apply or game operations. |
| Proportionate testing | Use state-loss, write-failure and helper-input counterexamples plus affected callers. | Test success is neither product acceptance nor a measured Astra performance gain. |

The requirement to give each retained rule a reason, inspect conflicts against
actual code and obtain a separate review comes from the user's request. The
current bundled `C:/Users/10160/.codex/skills/.system/skill-creator/SKILL.md` was
also consulted for scoped triggers, optional resources and behavioral validation;
it is local tooling guidance, not a performance benchmark.

These sources inform instruction design, not correctness of this repository's
implementation. Local source, counterexamples and review provide that evidence.
No new product-model, Build, game, training or Cloud acceptance is part of this
maintenance. No Astra throughput or task-success improvement is measured here.

## Retained rules and falsifiable reasons

| Root rule | Concrete reason and code/contract boundary | What would contradict the reason |
|---|---|---|
| 1: scope and completion | Audit, platform maintenance and product execution have different requested outcomes. `run_local_request` is an execution entry, not an instruction to run it. | A read-only request starting a model run, or an implementation stopping with analysis only. |
| 2: WIP and history | `local_entry.py` already contained the gap/query/budget work before cleanup. Historical `run_result.json` is used to interpret the original attempt. | Removal of inherited hunks or changes to a historical attempt to match new code. |
| 3: bounded source reading and large-file plan | Public entry, graph assembly and checkpoint handling span large files with different responsibilities. | A split changing public behavior without call-site evidence, or repository-wide reading without a task need. |
| 4: contextual references | The contract's opening selection was stale while historical and current facts coexisted below it. A static ownership map describes responsibility rather than enforcing it. | Treating a documentation paragraph or query view as current runtime proof or execution permission. |
| 5: inactive materials | The old task packet selected a Fresh-only objective and an old base commit; hooks have a fixed active packet path. | A restored old packet overriding the current user request. Old snapshots remain history and must still be treated as non-authoritative. |
| 6: existing control and persistence | Workflow conditional edges and ArtifactStore are existing consumer boundaries. Checkpoint and operation return types have callers. | A helper extraction creating a second routing authority or changing serialized return contracts. |
| 7: roles are not permissions | `StateOwnershipPolicy` declares writers; it is not itself a runtime source-edit authorization mechanism. Model suggestions are validated by execution owners. | Documentation claiming that a declaration or retrieved path itself permits mutation. |
| 8: exact operation scope | Product Apply, model disclosure and runtime execution carry bound identities and explicit admission. Platform repository maintenance is a different action. | Reusing approval for changed bytes/scope, bypassing denial, or requiring a product Apply token for a requested local code edit. |
| 9: task-memory limits | Stored observations can support planning; they do not establish that current dependencies and source still match. | A retrieved lesson selecting writable paths or turning an untested diagnosis into fact. |
| 10: proportional checks | State copying and failed writes have behavior counterexamples; documentation size has none of those runtime side effects. | Treating repeated broad test counts as new evidence, or omitting direct-call regressions after behavior changes. |
| 11: recoverable feedback vs executor failure | The product has a bounded feedback loop, and failures must retain their original inputs and consumed budget. | Stopping every supported feedback action as a new engineering failure, or repeatedly running an unchanged broken executor. |
| 12: claim boundaries and independent review | Build, dry-run and observed behavior prove different results. A reviewer who did not author the patch can challenge assumptions. | Calling a preview an execution, AI review human verification, or peer review a guarantee of correctness. |
| 13: one detailed record and scoped skills | Duplicate status text and broad triggers made obsolete instructions appear current. | Multiple competing verification accounts or skills forcing unrelated work. |

The reasons above are hypotheses about useful constraints, not self-issued
certificates. The review and verification sections below must record contrary
evidence and unresolved limitations as well as passes.

## Disposition of the earlier A/B/C findings

Findings that change behavior are not presented as cosmetic cleanup. The
workflow and skill rows below have implementation, direct checks and independent
review evidence; unresolved retirement and checkpoint items remain explicit.

| Finding group | Intended treatment | Acceptance / reason to retain |
|---|---|---|
| A1/A2/A6: obsolete paths, QA inputs and tool names | Implemented: corrected helper paths; removed mandatory absent-plan and unavailable-question-tool assumptions. | Helpers resolve the real repository; explicitly supplied missing inputs fail clearly. |
| A3/A4: QA execution itinerary | Implemented: removed all-tests, serial one-row edits, fixed retry counts and wording-driven reruns. | QA scope follows the request; helper mutation and provider scope remain explicit. Valid evidence reuse does not force another run. |
| A5: unsupported résumé claims | Implemented: removed suggested achievements, numerical ranges and stale ready-to-use accomplishments. | Claims require observed results and contribution evidence; code presence does not establish personal authorship. |
| A7: root rule duplication | Implemented: 291 lines became 100, with 13 scoped rules and reasons. | Separate review found no lost required boundary; this is not evidence of improved model throughput. |
| A8: stale active task packet | Implemented: archived with identical bytes and verified hash. | The active path is absent; previously recorded snapshots remain historical. |
| A9: stale graph documentation | Implemented: distinguish default no-write fake path from injected exact dry-run adapter. | No execution path or permission changed to match prose. |
| B1: state-copy divergence | Implemented: shared runtime cloning; retained separate historical checkpoint projection. | The dropped review field now survives with an independent nested copy; checkpoint format is unchanged. |
| B2: resume consumption ordering | Implemented: consume only after a durable/committed report. | Old write-failure counterexample fails; fixed same-instance retry passes. |
| B3: Runtime preflight duplication | Implemented and independently reviewed: common facts, separate mode rules and failure codes. | Extra-upstream counterexample still distinguishes terminal and consolidation. |
| B4/B5/C8: possible dead code | Removed `is_vague_request`, `continue_route` and `_MaterializedRepairPatchLLM`, each unreferenced in the checked scope. Production-called helpers retained; tests-only islands remain retirement-unverified. | A test import is not proof of production need. Exact classification is below; external consumers were not audited. |
| C1–C7: helper defects | Implemented: correct roots, explicit isolated QA targets and path checks; bound/sealed backups; failure propagation; structural-only note lint; nonempty skill metadata and real YAML parsing; optional scaffold resources; archive exclusion of itself/cache/temp; no credential-prefix logging. | Disposable-file counterexamples pass. The helper guards are not an operating-system sandbox or protection against arbitrary concurrent hostile mutation. |
| C9–C11: local-entry duplication | Implemented: remove unused local bindings, share legacy Build/XML value parsing. | Typed/legacy Build checks and optional/required XML error behavior passed their focused checks. |
| Fixed release/handoff schemas | Keep current CLI/output contracts; narrow skill descriptions to supported tasks. | Removing prose alone cannot make an unsupported input valid. Generalizing schemas is not required for this cleanup. |

Correction to the first audit: the QA helper source contains destructive and
provider-switch operations, but its current root calculation points at `.agents`.
That does not establish that it actually cleared the real production store.
Repairing the root must not accidentally make those operations implicit defaults.

### What was retained, and what the evidence does not establish

- `_patch_generation_obligation_projection`,
  `_validated_plan_change_identity_and_validation` and
  `_overlay_generated_patch_changes_on_plan` have production callers in
  `LocalOllamaInitialPatchAdapter`; they are not part of the unused repair island.
- `_repair_history_fact_constraints`, `_unique_repair_diagnostics`,
  `_repair_provider_constraints`, `_runtime_source_diagnostic_lines`,
  `_runtime_repair_spans`, `_objective_verification_source_views`,
  `_repair_span_response_schema`, `_materialize_repair_span_change`,
  `_repair_review_context` and `_read_utf8_source_snapshot` have direct tests in
  `tests/unit/test_local_entry.py`, but no production caller was found in the
  checked scope. `_RuntimeRepairSpan` and
  `_implementation_with_runtime_repair_bindings` belong to that island.
  They are **retirement-unverified**, not proven necessary production code. They
  remain to avoid silently deleting a tested historical interface while its
  replacement/retirement boundary is unverified; their existing tests cannot
  themselves settle that retirement decision.
- `StubNodeRunner` is used by the graph's blocked path and is exported.
  `StateOwnershipPolicy` is exported and read as declarations by
  `scripts/engineering_cognition.py`; its executable method use found here is in
  `test_mod_agent_state.py`, not a production write gate. It is retained as a
  declaration/compatibility surface, without adding new enforcement.
- Ollama wrappers translate exceptions at the local entry boundary; the
  checkpoint snapshot has an existing persisted-format contract. Similar-looking
  implementations are not removed when that would erase their distinct boundary.

The dead-symbol lookup was bounded to exact names in `src`, `scripts` and
`tests` Python files. It does not establish the absence of unknown external
imports. No tests were deleted to manufacture a passing cleanup result.

## Split plans for files exceeding 800 lines

Counts below are the pre-change structural inventory. Plans do not authorize a
wholesale migration. Small helper extractions for the listed findings are allowed;
public imports, serialized contracts and historical artifacts remain compatible.

| File | Lines | Proposed responsibility split | Why this boundary |
|---|---:|---|---|
| `src/mod_agent/local_entry.py` | 14562 | Public request façade; model/Patch adapter; query/budget assembly; approved/frozen continuation; Build; separate Runtime admission, execution and terminal-result helpers. | These operations have different side effects and validation identities; moving all Runtime code into another giant file would not help. |
| `src/mod_agent/workflow/graph.py` | 6425 | Keep `build_graph`; extract control validation, node registration, edge registration, stage implementations and Trace helpers. | The graph must remain one control plane with the original callable entry. |
| `src/mod_agent/workflow/checkpointing.py` | 2282 | Keep public data types and store façade; separate persistence, resume fact loading, Runtime-specific preflight and lineage checks. | Shared validation must not erase terminal/consolidation differences or change historical payload formats. |
| `.agents/skills/release-evidence-packager/scripts/package_release_evidence.py` | 822 | Input validation; evidence projection; Markdown rendering; atomic file output; thin CLI. | These existing responsibilities can be reviewed separately without changing the current output schema. |
| `docs/ACTIVE_PRODUCT_CONTRACT.md` | 1762 | Short current selection; stable execution boundary; links to preserved historical records. | The opening state must not present a historical 3/11 run as current. Historical paragraphs are labeled now; full relocation needs link-preserving review. |
| `tests/unit/test_workflow_graph.py` | 8096 | Group node behavior, routing, approval, recovery and runtime verification tests. | Preserve fixture sharing and test collection identities; do not delete coverage to shorten a file. |
| `tests/unit/test_local_entry.py` | 4869 | Group admission, model/Patch adapter, Build, Runtime and terminal-result checks. | Separate independent execution surfaces while retaining their error and compatibility assertions. |

## Verification and independent review

Workflow and skill implementation and independent review are complete. Commands
below use the repository's
`.venv/Scripts/python.exe -B -m pytest`, run from the repository root.

| Check | Result and boundary |
|---|---|
| State-copy and failed-report-write counterexamples | Old code: 2 failed. Fixed code: 2 passed. The tests now live in `tests/unit/test_workflow_cleanup.py`; the old locations were in `test_workflow_graph.py` and `test_verification_only_continuation.py`. |
| `test_verification_operation_checkpointing.py` plus exact resume/result, terminal-preflight and consolidation-owner tests | 23 passed. Checks persisted/committed resume handling and operation-specific admission. |
| Cleanup tests plus public Build admission/order and XML property tests | 7 passed. No real Build was performed. |
| Cleanup tests plus `test_seven_shape_public_operation_matrix_uses_exact_typed_chain` | 11 passed. Covers typed/legacy operation compatibility. |
| Final two terminal/consolidation focused checks after the last helper edit | 2 passed. |
| Bounded two-worker checkpoint: `test_workflow_cleanup.py test_mod_agent_state.py test_verification_operation_checkpointing.py test_repair_checkpoint_smoke.py test_workflow_route_trace.py -q --tb=short -n 2 --dist=loadfile` | **37 passed, 1 failed.** The failure is not hidden or counted as passed. |
| Exact failure rerun: `test_repair_checkpoint_smoke.py::test_repair_review_checkpoint_resume_accepts_review_approval` | The same assertion fails serially: line 53, `proposal_review.allowed_next_stage` is `None`, expected `dry_run_apply`. |

For that remaining failure, a separate Python process replaced only the reachable
`WorkflowCheckpointStore.resume` implementation with its exact old consumption-
before-write version and ran the same test: **1 failed with the same signature**.
The review result is constructed by `ProposalReviewer` in `_repair_review_state`
before checkpoint/resume operations. This supports that the observed failure is
not removed by restoring the changed resume logic; it is not a whole-repository
baseline reconstruction. Its cause is not diagnosed or fixed in this cleanup.

A separate AI reviewer, who did not implement these patches, ran the four cleanup
tests (4 passed), reviewed the diff and constructed an in-memory RuntimeEvidence
with an extra `evidence_pack` upstream. Terminal continuation rejected it with
`RUNTIME_TERMINAL_EVIDENCE_LINEAGE_INVALID`; consolidation accepted it. This
counterexample confirms that extraction preserved their different upstream
requirements. Freshness and outer lineage dependencies were fixed test doubles;
it is not real Runtime evidence. The inline check wrote no files.

The reviewer independently found that a backup restore still overwrote a later
configuration change: the three skill-test files initially reported **33 passed,
1 failed** at `test_restore_rejects_unsealed_target_drift`. The helper now records
the restorable target state and its own writes update that state; third-party
drift rejects restoration. The exact drift/owned-write pair passed (2 passed),
then the final bounded checkpoint passed:

```text
.venv/Scripts/python.exe -B -m pytest tests/unit/test_project_skill_maintenance.py tests/unit/test_project_skill_safety.py tests/unit/test_project_skill_scripts.py -q --tb=short -n 2 --dist=loadfile
35 passed
```

The independent reviewer repeated these 35 checks successfully after the fix.
This also covers a prepared QA baseline reporting failure when required fixture
or command steps fail, rather than returning a success message and exit code.
No actual ingestion, provider switch, remote request or active-store deletion
was performed. The original `test_project_skill_scripts.py` has no content diff;
new cases live in two small files.

The filesystem checks exercised resolution/containment logic, including a
monkeypatched external-path counterexample. A real Windows junction was not
created in this verification. Review covered this cleanup's hunks, not all
inherited `local_entry.py` work. No unresolved high/medium-priority finding was
reported within that reviewed scope; this is not a claim of defect absence.

Changed workflow/entry files and changed skill helpers/tests passed Ruff's
`--select E9,F63,F7` checks. `git diff --check` passed for the touched tracked
files; line-ending conversion notices are not test failures.

The reviewer also caught a missing evidence link in the current contract header.
That header now links the retained local `run_result.json` and
`run_manifest.json` directly rather than using this maintenance report as proof.
This is independent source review and local behavioral verification, not a blind
model evaluation, human certification, a full-suite pass or an Astra performance
measurement. CI itself has not been executed by this maintenance.

`local_entry.py` and workflow source identities changed in this maintenance.
Any later real continuation must load the current version and regenerate its
bound Preview before execution; this report neither updates an old scope hash
nor renews its approval. The retained run history and cumulative budget remain
unchanged. The existing CI selection now includes the new focused cleanup and
skill-helper test files, without adding a new workflow or running live services.

### Visible compatibility changes and approval outcome

- The QA state helpers now require `--target-repo` and a marked independent
  checkout; the previous implicit-target invocations are intentionally rejected.
  This prevents correcting the root path from silently enabling active-store
  mutation. The marker does not establish operating-system isolation.
- `qa_validate_notes.py` takes an explicit progress file and reports structural
  validity only. It does not enforce particular evidence wording or prohibit a
  valid reference to another version-bound result.
- `init_skill.py` creates only `SKILL.md` by default. `--include-examples`
  retains the former resource examples when requested. The initializer is not
  represented as creating UI metadata that its implementation does not write.
- Bounded handoff and release helper input/output contracts were preserved.
  Their remaining fixed restrictions are compatibility limits, not claims that
  those restrictions are best practice for all tasks.

Automatic approval review rejected an attempted delete-then-add edit of the QA
`SKILL.md` and `references/test_patterns.md`, because it interpreted the operation
as removing an active skill without a replacement. That deletion did not occur.
The cleanup was written as in-place updates; the user then explicitly approved
both files. They remain present (71 and 51 lines respectively), and this approval
is not extended to unrelated actions.

## Archived active context

The old ignored task packet was moved from `.codex/task-packet.json` to
`.codex/task-packet.retired-20260923.json`. Its bytes are unchanged; SHA-256 is
`2174d15c22894b489c0399403cadf8aa7bf00a3f436534f748b3789a900a4e09`.
This is an inactive context archive, not a new task registry or run result.

## Follow-up performance pilot and return to product work

The user subsequently authorized measuring instruction-cleanup benefits. This
is a separate follow-up, not a retroactive change to the cleanup verification.
The tested intervention was old/new repository instruction Markdown with the
same helper code, three disposable diagnostic tasks, GPT-6 Astra / High,
Codex CLI 0.155.0-alpha.9.2, separate workspaces and 240 seconds per run.
It did not test the product Qwen model, RAG runtime or real Mod delivery.
The diagnostic tasks were authored by Codex and reviewed by a separate AI
agent; they are not human-authored held-out benchmark tasks.

The original frozen plan contained 12 runs (two repetitions per arm/task).
The user requested rapid closure and return to project progress: runs 01–06
form one old/new pair per task; 07 was cancelled and excluded; 08–12 were not
started. The original plan and failed/partial records remain intact; no run
was retried or given more time to improve the result.

| Diagnostic task | Old instructions | New instructions | CLI input tokens old → new | Command execution batches old → new | CLI wall time old → new |
|---|---|---|---|---|---|
| T1 nested configuration copy | Complete; behavior and trace review passed | Complete; behavior and trace review passed | 119,043 → 127,013 (+6.7%) | 4 → 6 | 192.4s → 218.3s |
| T2 bounded switch-parser QA | Generated code and verification passed; final delivery incomplete at timeout | Complete; behavior and trace review passed | Unavailable → 134,127 | 10 → 8 | 240s timeout → 206.8s complete |
| T3 evidence-constrained project description | Complete; semantic review passed | Complete; semantic review passed | 124,956 → 84,982 (−32.0%) | 4 → 4 | 154.5s → 157.9s |

All generated behavioral artifacts met the checks reached, but complete
deliveries were old 2/3 and new 3/3. The timed-out old T2 has no final
turn.completed usage record: unavailable token usage is not zero, and its
240-second timeout is a censored endpoint, not a measured completion time.
Do not infer a precise speedup from that row.

Cache and output differences matter. T1 uncached input was 15,363 → 12,581,
while output was 1,575 → 1,938. T3 uncached input was 23,964 → 22,774,
while output was 704 → 906. CLI usage is reported usage, not a provider billing
reconciliation; no monetary saving is established.

Every scored run logged five WebSocket retries before HTTP fallback. The
network wait is part of wall time and prevents treating it as pure model
processing time. A separate initial connectivity probe also failed local
execution because the test launcher omitted the host's existing
windows.sandbox="elevated" setting while ignoring user configuration.
The setting was restored for the successful second probe and every scored
run. The native workspace sandbox and managed restrictions remained enabled;
neither approval rules nor certificate validation were bypassed.

Conclusion: mixed diagnostic results, with no established stable speedup,
overall cost reduction or general capability improvement. The writing task
used fewer reported input tokens; the small code-fix task used more command
batches and had higher observed wall time. Maintenance and correctness reasons
still justify the cleanup, but this pilot is not a resume performance claim.

Raw protocol, invocations, JSONL events, usage, diffs, judgments and blind
reviews remain under
C:/Users/10160/.codex/visualizations/2026/09/20/01a0bce8-aea4-71d0-8008-83c271251d2f/instruction-perf-20260923/.
The result index is results.json / results.csv; pilot-stop.json records
the reduction. The original protocol SHA-256 is
d0d2ba736ae4f9a46cc806d3d6b81ba7c41082bb35e28ebcaa61297c22726d0c.

The user's current priority is product progress with evidence/material
collection in parallel, not immediate resume drafting. The original Mod owner
has been asked to continue the bounded shortcut task; the integration owner
maintains the existing acceptance/material index. Keep the latest real Mod
result at 13/17 until a new bound execution actually occurs. Preserve the
distinction between historical domain rejection and later stop-record wiring.
