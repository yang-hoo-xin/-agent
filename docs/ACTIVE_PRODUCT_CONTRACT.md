# Active Product Contract

Status: normative daily execution contract
Last updated: 2026-07-26

## 1. Product

This repository is an evidence-grounded controlled code-generation Agent
platform. Its first verified domain is a local GTFO / BepInEx Mod project, but
the product boundary is controlled vertical code delivery rather than GTFO or
general-purpose RAG question answering.

The product must turn a concrete development request into inspectable evidence,
a bounded change, and truthful verification:

```text
request
-> acceptance boundary and runtime/evaluation applicability
-> live target evidence
-> implementation bindings
-> generated patch
-> proposal review
-> no-write dry-run
-> exact-diff approval
-> isolated apply
-> real build
-> required verification, repair, or explicit blocked result
-> delivery or explicit unresolved result
```

Before implementation, define the selected request's acceptance boundary and
record whether runtime and evaluation gates are required. A real build may end
in a compile-level handoff only when that boundary is explicitly compile-level
and downstream runtime and evaluation verification are not applicable.
Otherwise, each required gate remains part of the controlled workflow. Missing
authorization or evidence is unresolved or blocked; it is not delivery success.

Evaluation, schemas, policies, dashboards, MCP, and retrieval mechanisms serve
this chain. They are not independent product lines.

## 2. Current Verified Capability

The current branch combines one narrow real request-to-build run against an
externally produced, read-only BetterHitFeedback target with focused
post-run hardening tests:

- `rg` plus live file reads selected current target source and symbol evidence;
- `qwen3.6-plus` produced an evidence-bound exact-text patch;
- existing proposal review approved dry-run;
- dry-run wrote nothing and exposed exact before/after plus a context hash;
- the user approved that exact hash;
- the real run applied one approved isolated occurrence; focused hardening tests
  additionally prove that apply rereads live source and binds Proposal,
  Implementation Plan, Evidence identity, source snapshot, path, before, and
  after before writing;
- a real local `dotnet build` produced and verified the expected DLL;
- the external target source remained unchanged;
- local-source disclosure to an external LLM required separate per-run consent.

The later controlled run `007b1b58` extends this narrow capability through a
meaningful BetterHitFeedback behavior change and real two-mode GTFO
verification. The exact built DLL ran once with `General.Enabled=false`, where
the plugin emitted the disabled marker and registered no patches or hooks, and
once with `General.Enabled=true`, where patch registration plus bound gameplay
hook and visual/audio behavior markers were observed. The canonical target
source remained unchanged and the game directory was restored to the read-only
preflight state after capture.

The bounded Agent Engineering Harness path now also distinguishes Runtime
failure ownership before granting source-repair authority. New RuntimeEvidence
normalizes product-behavior, observation, environment, provider, permission,
and unknown outcomes. Only product behavior with evidence that resolves to an
existing allowed edit binding may re-enter Proposal/Review. Other owners stop
with an owner-specific RepairPlan result and do not repeat model, Proposal,
Apply, or Build work. Older ownerless RuntimeEvidence remains readable but has
no source-repair authority.

Post-H3 mainline run `e7daa266` real-exercised the bounded Build-to-Runtime
continuation. A fresh compile-only process persisted a Build checkpoint; a
separately authorized `resume-runtime` process retained the original
run/request/feature and Build Artifact hash, deployed the exact built DLL,
verified source/expected/destination SHA256 equality, launched GTFO, observed
the startup and `chain_probe=true` markers, wrote RuntimeEvidence, Eval, and
WorkflowSummary, then restored the game directory. The continuation made zero
model calls and reported `upstream_stages_repeated=false`. The acceptance
marker occurred at run-local character offset 22,826, proving the current
pre-truncation structured-marker repair against the real failure shape that
defeated the older 20,000-character projection.

This proves one local request-to-real-runtime gameplay slice and one bounded
automatically collected startup-marker slice in one GTFO environment. It does
not prove cross-project or cross-environment generality, production
deployment, long-duration stability, every gameplay route, automatic Runtime
recovery, semantic root-cause accuracy, generalized Runtime Harness behavior,
or promotion-grade retrieval quality.

The local `plan-request` CLI is also a tested planning-only entry. It now runs
the deterministic RequestPlanner and ModPlanningBriefBuilder in memory, emits
the existing request-planning and planning-brief payloads, reports
`writes_performed=false`, and stops before `feature_spec`. Mixed configuration
plus gameplay requests, including the selected WallCrawler request, route to
`game_hook_investigation`; planning-only Hook work stops with `needs_evidence`.
This does not prove natural-language understanding, perform evidence lookup,
select a Hook, generate code, or enter proposal/build/runtime stages.

The bounded `evidence-request` CLI provides the next WallCrawler slice. It runs
the existing graph through `feature_spec`, rereads the explicitly supplied GTFO
R8 files, verifies their recorded SHA256 values and exact symbols, writes a
provenance-bound `evidence_pack`, and ends at `evidence_retrieval`. The pack is
`partial` and not authoritative for patch generation because movement method
behavior and current runtime binding remain unresolved. No implementation plan,
proposal, apply, build, runtime action, game launch, or target-source write occurs.

`WALLCRAWLER-HOOK-EVIDENCE-002` adds a local read-only CLI metadata/IL check
for the hash-bound R8 `Modules-ASM.dll`. The inspected concrete methods
`ES_PathMove.CommonFixedUpdate` and `ES_PathMove.UpdateRotation` each contain
only `nop; ret`; `ES_PathMoveBase.UpdateRotation` is abstract with RVA zero and
no method body. The evidence pack therefore remains `partial` and
`can_generate_patch=false`; Proposal-only is not unlocked by this snapshot.

The current-install follow-up keeps the same stop boundary. Explicit CLI paths
may add hash-bound current interop and reference-Mod metadata/IL EvidenceItems
to the existing EvidencePack; this does not create a new Agent or workflow.
The observed run still returned `partial`, `can_generate_patch=false`, stopped
before `implementation_plan`, and performed no target-source write. Generated
interop wrappers and community Harmony patches are evidence inputs only; they
do not establish native wall, slope, or ceiling movement behavior.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-004` adds the first bounded intelligent
Evidence loop inside the existing `retrieve_evidence` graph node. Given a
natural-language request and path-hidden Source Registry views, an injected or
separately authorized chat model selects `search_dotnet_metadata` or
`inspect_method_il`. Exact IL inspection accepts only a `method_id` derived
from a prior current-run metadata observation. The EvidencePack records tool
observations, findings, unresolved questions, provenance, manual-input counts,
and intelligence-transfer checks. Focused tests prove model-selected two-step
execution and the graph stop boundary; a real local-tool run against the
supplied R8 `Modules-ASM.dll` proved hash/MVID/token-bound reads without target
execution. A later approved `qwen3.6-plus` run is preserved at
`artifacts/intelligent_evidence_real_wallcrawler/features/feature_8eae153e6c04/evidence_pack.json`.
It exhausted all 8 model steps and 6 tool calls after sending 205,912 bytes of
tool observations, emitted no evidence conclusion, and did not establish
semantic discovery quality. Its older transfer flags also exposed that the
acceptance checks were too permissive. Proposal-only remains locked.

The same task's acceptance hardening now requires every final evidence
conclusion to be exactly `observed`, `inferred`, or `unknown`. Observed and
inferred conclusions must cite current-run observations; inferred conclusions
must state limitations; unknown conclusions cannot cite an observation as if it
proved the claim. EvidencePack persists only sanitized model actions plus their
hashes, observation hashes, prompt-contract and initial-context hashes, model
identity, and complete budget consumption. Raw prompts are not persisted. A
machine-local ignored registry binds two relevant choices, the supplied R8 and
current installed interop `Modules-ASM.dll`, to their live SHA256 and MVID;
the executor blocks stale identity before returning metadata to the model.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-005` hardens the actual intelligent turn
rather than adding another Workflow controller. A provider-neutral structured
Agent-turn contract now carries exact tool schemas, normalized tool calls,
call ids, final structured output, stop reason, provider/model/request identity,
and token usage. The real-validation path remains Qwen Chat with thinking and
parallel tool calls disabled; a separately callable OpenAI Responses adapter
maps typed function-call/output items, reasoning continuation items, and
`text.format` without changing the single LangGraph control plane. Both wire
adapters are locally request/response tested; no OpenAI or Qwen network call was
made for this implementation acceptance.

The Evidence specialist now reconstructs each turn from the immutable initial
goal/source projection, a compact action/observation trajectory, the latest
full observation only, and current budget state. Earlier full observations
remain in the local audit record but are not cumulatively replayed. Metadata
search requires the exact `result_kinds` and `limit_per_kind` arguments, returns
one assembly identity table instead of repeating SHA256/MVID on every row, and
reports matched/returned/truncated counts by kind. Intelligence-transfer flags
now require budget convergence, a dependent metadata-to-IL step, an
inspection-citing grounded conclusion, and absence of repeated identical tool
work. Semantic relevance remains explicitly unevaluated without a ground-truth
case. Real Qwen WallCrawler semantic acceptance still requires a new exact
per-run disclosure approval and does not unlock Proposal-only.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-006` performed that post-005 real Qwen run
once under separate disclosure approval. It stopped at `evidence_retrieval`
with no forbidden later artifact, and total model-visible observation bytes
fell from 205,912 to 20,001. It still failed V2-C: all six tool calls were
metadata searches, no observed method was inspected through IL, and finish
steps 7 and 8 failed exact validation with `DISCOVERY_DECISION_INVALID` and
`EVIDENCE_CONCLUSION_SHAPE_INVALID`. That evidence allowed only a bounded repair
of the exact nested finish schema and remaining IL/conclusion acceptance state;
007 completed that local repair below. Proposal remains locked.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-007` completed that exact local repair. The
final response format, system contract, and bounded validation correction now
share the same full nested schema. Each turn also exposes exact metadata and IL
observation ids plus the remaining inspection/conclusion acceptance
requirements. The prompt contract is now `evidence_discovery_prompt_v3`; the
production tools and 8-step/6-tool limits are unchanged. Seventy focused tests
passed without an external call. This is local repair evidence, not real Qwen
V2-C acceptance; Proposal remains locked.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-008` performed exactly one separately
approved post-007 real Qwen rerun. It completed at `evidence_retrieval` in 7 of
8 model steps with five metadata searches, one metadata-derived IL inspection,
and one valid `needs_more_evidence` finish. The run used 20,417 observation
bytes and produced no forbidden later artifact or target-source write. It did
not complete the intelligence-transfer gate: its grounded conclusion cited a
later metadata observation rather than the IL observation, the persisted flag
is `symbol_discovery_by_platform=false`, and its second conclusion incorrectly
said the IL was not retrieved even though the EvidencePack records a 42-
instruction body for `Beh_GroundMovement.OnStateEnter`. This allowed only the
separately selected compact-IL representation and inspection-citation repair
completed as 009 below. Proposal remains locked and no rerun is authorized.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-009` completed that local repair without an
external call. Prompt contract `evidence_discovery_prompt_v4` carries separate
deduplicated metadata-method and IL-inspection catalogs, never duplicates the
latest full observation in those catalogs, and persists per-turn discovery-
message byte counts. A finish that ignores an available IL observation receives
one bounded correction. Once IL exists, the next-action state directs the model
to finish unless one exact unresolved gap justifies another tool call; grounded
`needs_more_evidence` remains valid. The three-turn local path uses 13,864
message bytes versus the 38,774-byte seven-turn pre-repair baseline. This is
local message-shape and convergence evidence, not a new Qwen token or billing
claim. Seventy-five focused tests passed; Proposal remains locked and no rerun
is authorized.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-011` adds a real on-device model path without
changing the graph or evidence tools. Ollama native tool calls are normalized
through the existing Agent-turn contract. Local execution accepts only a
literal `127.0.0.1` or `::1` HTTP origin, rejects redirects and proxy routing,
and is recorded separately from external disclosure and injected/test models.
A hidden post-run evaluator reports capability, convergence, and semantic gates
independently; expected symbols and scoring remain outside model context.
Eighty-five focused tests passed.

The one 011 `qwen3:4b-instruct` run kept all request and GTFO-derived data local
and stopped at `evidence_retrieval`, but did not pass intelligence transfer. It
used 7 turns and all 6 tool calls for metadata search, repeated 3 exact action
signatures, selected no IL read, and produced no IL-grounded conclusion. Its
5,969 observation bytes and 48,741 discovery-message bytes do not indicate the
earlier observation-bloat failure; the observed failure is identifier-query
choice plus repeated work. The exact UTF-8 Chinese goal was preserved. No
Proposal or repair task is unlocked automatically.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-012` repairs only the two confounded failures
observed in 011. Prompt contract `evidence_discovery_prompt_v5` truthfully
describes metadata queries as case-insensitive literal substrings of fully
qualified managed type, method, and field symbols, not behavioral semantic
search. The loop rejects a repeated exact source/tool/arguments signature
before the local tool executes, emits at most one repeat-specific answer-free correction, and
deterministically stops on a second repeat. An injected regression recovered
through a changed symbol query, observation-derived `method_id`, IL inspection,
and an IL-bound conclusion. Thirty direct and 198 affected tests passed. This
is local contract evidence only: no real model ran, Proposal remains locked,
and a later local rerun requires separate task selection.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-013` performed that separately selected local
rerun exactly once with the same 011 request bytes, source identities, model,
quantization, and budgets. The prompt-v5 path eliminated executed repeats and
the model selected metadata, an observation-derived method, and IL for
`Beh_GroundMovement.OnStateEnter`. It did not pass acceptance: the first IL-
grounded finish had the wrong top-level shape, the correction selected
`sufficient_for_proposal` while retaining open questions, and the single finish
correction was exhausted. The final run status is `budget_exhausted`; all three
hidden gates are false; Proposal remains locked. The run also exposed a copied
query-placeholder representation and a provenance/convergence reporting
coupling. The 013 result itself did not authorize a retry or repair.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-014` completed the exact deterministic repair
selected from 013. Prompt v6 exposes metadata-tool argument names without a
copyable query value, states finish decision/open-gap constraints in the shared
schema and correction context, and computes accepted method-origin provenance
without requiring final convergence. Thirty-one direct and 199 affected tests
passed; existing message-byte thresholds, tools, budgets, validators, graph
route, and the `evidence_retrieval` stop remain unchanged. No real model ran,
Proposal remains locked, and no rerun is selected.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-015` then exercised prompt v6 exactly once
through the same loopback-only `qwen3:4b-instruct` boundary, original 013
request bytes, and two live identity-matched sources. The removed placeholder
was not copied. The model instead used the same five invented behavioral symbol
strings against both sources, received zero methods twice, and then returned
twice to the same current-interop source/tool/arguments signature. Both repeats
were rejected before tool execution. The deterministic stop produced
`budget_exhausted` after 4 model turns and 2 metadata tools, with no method_id,
IL inspection, or model conclusion. All three hidden gates remain false. The
run stopped at `evidence_retrieval`, produced no forbidden later artifact, and
does not select a retry or repair automatically.

Artifact persistence for this evidence-only entry is now verified under the
current Windows, local NTFS, and existing artifact-root boundary. Immutable
revisions use `r/<artifact_type>/<artifact_hash first 32 hex>.json`, pending
markers use `p/<artifact_type>/<artifact_hash first 32 hex>.json`, and latest
envelope projections retain their prior paths. The abbreviated locator is only
physical storage: complete hashes remain in envelopes, refs, and upstream
bindings; reads validate the complete hash and writes reject locator collisions.
Valid legacy full-hash revisions remain readable and are reused idempotently
without migration or duplicate writes.

`intelligent-evidence-request` now probes the real pending, revision, and latest
atomic-write paths before graph, model, or tool execution. A recognized
unaddressable-path replace failure returns `BLOCKED`, exit code 2, and an
`artifact_preflight` diagnostic without exposing absolute local paths. Focused
no-model verification passed 134 tests. One new loopback-only run then persisted
request planning, planning brief, feature specification, and EvidencePack
revisions and latest projections with no pending or temporary files left. It
ended later as `budget_exhausted`; persistence is unblocked, but capability,
convergence, semantic acceptance, and V2-C completion remain unproved.

The evidence-only entry now also persists an `evidence_run_attempt` before the
first possible external model call and writes a terminal revision with the same
`run_id`. Sanitized provider-turn diagnostics preserve provider-reported and
adapter-extracted tool names separately, argument validity/hash, call identity,
finish reason, non-streaming state, and usage without retaining API keys,
complete prompts, source roots, or raw arguments. Unknown tools execute no
evidence tool and receive no automatic provider retry. This contract passed
171 focused tests and is checkpointed at `5c78e06`.

One separately approved `qwen3.6-plus` run subsequently completed the bounded
metadata -> `candidate_ref` -> control-resolved method identity -> IL loop
twice under run id `intelligent_evidence_448f8515e5634f9faf629494f8febbef`.
The EvidencePack retains both identity chains, stops at `evidence_retrieval`,
and contains no later-stage artifact. This validates the real intelligent
identity loop only. Its original semantic result was a false positive.

Current source now projects deterministic observation facts, admits an
`observed` conclusion to `verified_findings` only when it exactly matches one
fact's `canonical_claim`, keeps inferred conclusions unverified, permits bounded
unknown conclusions, and invokes the same post-run evaluator for local and
external providers. Related regression passed 154 tests. Offline reevaluation
of the preserved run now reports capability true, convergence false, and
semantic false, rejecting both unsupported observed conclusions.

A later separately approved repaired-path run,
`intelligent_evidence_36d25ed53f3447e3adeaa71f42fb7ec0`, produced EvidencePack
artifact hash
`bb6dbc8303648d01ff84464e1ed5559ac46d4f697567ef8ec97adb406afb9cea`.
Its first finish failed exact observed-fact validation and its one bounded
correction produced two verified exact observed claims plus two bounded
unverified inferences. The final provider-neutral result is capability=true,
semantic=true, convergence=false; both metadata -> `candidate_ref` -> internal
method identity -> IL chains are provenance-valid. This supplies single-run
real evidence for V2-C `core_complete`. Here `core_complete` means only that
one real run demonstrated the core behavior loop. Readiness remains `partial`,
`can_generate_patch=false`, evidence sufficiency and implementation readiness
remain false, and Proposal remains locked. The run does not record
`source_revision`, `git_commit`, or `modified_files_hash`, so
`source_binding_status=missing` and the run is not an independently
reconstructable source baseline. Future real-run comparison requires those
code-identity bindings.

### 2.1 V2-C Frozen Validation-Spike Status

V2-C is frozen as a `V2 intelligence-loop validation spike`. Its one repaired-
path real run established the bounded core closure recorded above, but V2-C has
no continuing product route and `selected_product_request=None`.

The run remains `source_binding_status=missing`. `V2 Agent runtime path
reconstruction` is a pending read-only task type only; it is not an approved
task, active queue item, permanent product gate, or implementation requirement.

## 3. Non-Negotiable Authority Boundaries

1. Current target source, API shape, build output, and runtime evidence outrank
   model statements, community hints, plans, and historical artifacts.
2. Retrieval relevance never grants write authority.
3. The Binding Registry determines writable targets. The model does not invent
   or copy filesystem paths as authority.
4. Proposal review must permit dry-run before patch validation.
5. Dry-run never writes source.
6. Isolated apply requires the exact displayed context/diff hash. Missing,
   changed, stale, ambiguous, or interrupted approval means zero platform write.
7. Local source may be sent to an external LLM only with explicit, per-run
   disclosure consent covering every requested data class.
8. API Key values must not enter artifacts, logs, committed configuration, or
   user-visible summaries.
9. Build success requires a real command exit of zero and verification of the
   declared artifact. A fake, skipped, or supplied-output build is not real
   build success.
10. Build success does not prove runtime or gameplay success.
11. Game launch, game-directory copy, and real gameplay evidence require a
   separate explicit opt-in.
12. Before implementation, define the request's acceptance boundary and record
   whether runtime evidence and evaluation are required. A required gate may
   not be skipped merely because the build succeeded.
13. Registered workflow artifacts must preserve their required upstream
   references, current evidence bindings, and stale-data checks.

## 4. Current Retrieval Decision

- Current code: retain `rg` plus live reads as the default.
- Existing SymbolIndexer: optional navigation aid; deepen only after repeated
  structural-navigation failures in real product work.
- Community/history BM25: build only when authentic, traceable material and a
  concrete product decision exist.
- Dense, RRF, rerank, and top-level Agentic routing: no active product work. Trigger only
  through a bounded decision experiment tied to an observed failure.
- Arms A-G and H1-H5 are a conditional formal-validation roadmap, not the
  consecutive V2 queue.

## 5. Task Selection Rule

There is no active task until a concrete product capability or real Mod request
is selected.

A task may enter the queue only when it does at least one of the following:

- delivers a new user-visible step in the controlled chain;
- fixes a failure observed in a real request;
- removes a demonstrated safety or truthfulness defect;
- packages verified output into a usable delivery artifact;
- supplies evidence required for a current product decision.

Do not create work merely because an older roadmap, coverage row, imported
blueprint, or optional mechanism exists.

Prefer the smallest real vertical result. After it succeeds, stop infrastructure
work and return to the next product capability.

## 6. Verification And Claim Levels

Use the narrowest supported claim:

| Evidence | Allowed claim |
| --- | --- |
| Unit/focused tests | tested local behavior |
| Dry-run | the exact before-text had one match in the observed isolated source snapshot, the proposed after-text and hash were displayed, and no write occurred |
| Exact approved isolated apply | approved bytes were written in the isolated workspace |
| Verified real build | declared artifact compiled and its hash was recorded |
| Runtime logs/screenshots with binding | observed runtime facts only |
| Real acceptance evidence | requested behavior verified for that run and environment |

Never generalize one Mod, repository, language, or environment into a
cross-project claim.

Current claims must be supported by current source, current-branch focused
tests, or current-run artifacts. Uncommitted control-document edits describe
working-tree state only. Frozen documents and `docs/audits/LOOP_HISTORY.md` are
historical context and cannot promote a current capability claim.

## 7. Product-Quality And Career Standard

Project quality is demonstrated by executable evidence, not document or module
count. A strong portfolio result should show:

- a real user problem and runnable vertical workflow;
- evidence lineage from source to patch to build/runtime result;
- bounded LLM and tool permissions;
- truthful fake/local/real claim separation;
- observable failures and focused repair decisions;
- reproducible tests and immutable Git checkpoints;
- an understandable demo and delivery artifact;
- architectural decisions tied to measured product failures.

The next meaningful breadth proof should be a second different real task,
delivery handoff, or incompatible project/build contract—not another passive
schema layer.

## 8. Authority Reference

This contract does not define a second authority or reading order. Follow
`AGENTS.md` section 2 exclusively.

## 9. Conflict Rule

Current source and focused tests decide exact implemented behavior. This file
decides current execution scope, claim boundaries, and task-selection policy.
`DEV_SPEC.md` remains the detailed root specification and
`EVIDENCE_RAG_MCP_SPEC.md` remains its subsystem specification. If older or
imported material conflicts with this active contract, stop and reconcile the
documents before implementation; do not silently expand scope.
