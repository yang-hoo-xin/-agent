# Active Product Contract

Status: normative daily execution contract
Last updated: 2026-07-14

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

This proves one local request-to-compile workflow. It does not prove gameplay
behavior, cross-project generality, production deployment, automatic repair,
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
