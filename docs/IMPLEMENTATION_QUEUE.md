# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-26

Authority and reading order are defined only by `AGENTS.md` section 2.
Completed, frozen, review, and superseded records belong in
`docs/audits/LOOP_HISTORY.md`, not in this queue.

## 1. Current Queue

```text
current_queue: GTFO-BETTERHITFEEDBACK-STAGGER-FEEDBACK-001
selected_product_request: BetterHitFeedback stagger-confirmed yellow-X and audio feedback
```

```text
task_id: GTFO-BETTERHITFEEDBACK-STAGGER-FEEDBACK-001
product_request_or_failure:
  When a local player's weapon hit actually causes an enemy hit reaction,
  show one yellow X at the hit position, play one short sound, and emit
  STAGGER_FEEDBACK_SHOWN exactly once for that hit. General.Enabled=false must
  produce none of those three effects.
exact_evidence:
  User confirmed the product behavior and its visual/log acceptance boundary
  on 2026-07-26. The selected source-lineage input is the preserved final
  Phase 2B tree under r/007b1b58/generated_mods/BetterHitFeedback: Plugin.cs
  SHA256 10DDF3032058853BB41053F27A0BF7D09D0049169058B704D3EB3A86273F8286,
  HitFeedbackBehaviorPatch.cs SHA256
  92EAB8010EED49E8C84094DC6EB5376D5F995414C40CF7D2C44FC1955D405E1A,
  HitFeedbackDiagnosticPatch.cs SHA256
  49CAEFE5071C92A3185D1D83E0DA1A2273C1720B92767F6AA6D5C9D5A78FEF14,
  and BetterHitFeedback.csproj SHA256
  05B6B0BB6226A0880A0642FBC381208648BC8EA362B120C449DF9B658EDF2777.
  Plugin.cs contains the already real-verified startup General.Enabled gate.
  The behavior source already observes Dam_EnemyDamageBase.BulletDamage,
  carries its position and staggerMulti input, and contains reusable HUD and
  audio helpers; staggerMulti is not accepted as proof of an actual hit
  reaction.
  Read-only inspection of the current installed BepInEx interop
  Modules-ASM.dll bound SHA256
  B0127EB1E9228A61B7ED04EA0152348E24DA693636711D03A248049618BB74BB and
  module MVID 85155e68-33a5-4fa5-a419-c563e7ea5e60. It found
  Enemies.EnemyAgent.OnTakeDamage token 0x0600F223 with signature blob
  2005010C12B9DC11511151118430, ES_Hitreact.ActivateState token 0x06001387
  with signature blob 2006011184301184340212B9DC11511186F8, and
  ES_Hitreact.DoHitReact token 0x0600138A with signature blob
  200701081184301184340C0211511151. ES_HitreactType exposes Unspecified,
  None, Micro, Light, Heavy, ToDeath, and InstantRagdollDeath.
  A second read-only inspection found
  ES_Hitreact.NativeMethodInfoPtr_DoHitReact_Protected_Virtual_Void_Int32_ES_HitreactType_ImpactDirection_Single_Boolean_Vector3_Vector3_0,
  Dam_EnemyDamageBase.get_Owner token 0x060023A3, and
  Enemies.ES_Base.get_m_enemyAgent token 0x0600F41A. Current installed
  EnemyAnimationFix.dll SHA256
  6367AF9BF155675AA8EEED6CA32C398144A7AAB6790F1AD10CBCDC2FFD4E87AC,
  MVID 4ca43650-39a3-4399-b2e8-cd45ce386963, independently patches
  ES_Hitreact.DoHitReact through
  EnemyAnimationFix.Patches.EnemyAnimPatches.FixLowStagger token 0x0600001E.
  Its exact HarmonyPatch custom attribute names ES_Hitreact and DoHitReact.
  Operator-guided inspection selected a Hook design that uses BulletDamage
  only to capture the current local-player damage sequence, enemy Owner, and
  hit position, and uses DoHitReact as the result-side event bound through
  m_enemyAgent. Micro, Light, and Heavy are in scope; Unspecified, None,
  ToDeath, and InstantRagdollDeath are excluded. One stored damage sequence
  plus matching enemy identity is the bounded deduplication key. This design
  is an operator reference for later comparison, not an input to the bounded
  internal-Agent experiment and not proof of automated discovery.
  The no-answer-leak local experiment ran twice. Pre-repair run
  intelligent_evidence_f66e69cc385a477b9e738f9838874f6f produced
  EvidencePack dd21a23a4a3fdd9a2bee5cd68c83c8cb8d05775b65b80dadc00e89d1d56c0ab7
  after one zero-result metadata search and no IL inspection. The bounded
  repair now requires one different recovery search before accepting that
  first zero-result stop. Post-repair run
  intelligent_evidence_cad5aa77e5214883a258be4d0bc02068 exercised the new
  rejection ZERO_RESULT_RECOVERY_REQUIRED and executed a second search, but
  local qwen3:4b-instruct repeated unsupported feedback-name variants, found
  no method, and selected no IL inspection. EvidencePack
  3bbdc8b150a25fe1be17093fecc698173f8b12c1815047a5a6be2b87e9a2c214
  remained insufficient with can_generate_patch=false. This closes the one
  permitted minimal experiment repair and keeps automation_claim not_proven.
  The revised operator-guided FeatureSpec is registered under
  workspaces/stagger_feedback_feature_spec_001/stgfs001/a with feature id
  feature_4f4c63c3802d and Artifact hash
  81830b22ab6ec0c07c45be895906677facc270e65f5266d8f24add4353214f09.
  It supersedes but does not rewrite earlier FeatureSpec Artifact
  d463563884f3fd79fd9883a69b9b3b87e88be45cfee0fe09bfcb833de2d6f486.
  Its upstream request-planning Artifact hash is
  2aa1a32f6f9ef6260d31fb9481ce8bfafd0ef861fd3b629ede080d85b05872d4.
  It keeps seven product acceptance criteria while moving the two-event
  correlation, enemy identity path, reaction-type scope, exactly-once design,
  visual path, and audio path into seven falsifiable operator-guided technical
  hypotheses. Current Evidence may support, reject, or leave them unresolved;
  any rejected or unresolved essential hypothesis blocks before
  Implementation Plan. The marker records only code-level visual creation and
  audio-event acceptance; visible and audible product success remain separate
  Runtime requirements. Direct ArtifactStore/lineage checks passed, and the
  final affected discovery, planning, graph, CLI, and Artifact suite passed
  199 tests in 21.19s. Source compilation and diff checks also passed.
affected_coverage_ids:
  PLAN-001, PLAN-002, PLAN-003, PLAN-004, RET-007, RET-008, RET-011,
  EXEC-002, EXEC-003, EXEC-005, EXEC-006
dependencies:
  Fresh run-local materialization from the exact selected source-lineage
  bytes; current live GTFO interop metadata; an EvidencePack that independently
  supports or rejects every essential technical hypothesis; existing
  single-StateGraph review/apply/build/runtime gates.
permissions_and_disclosure:
  Current admission authorizes local read-only source, metadata, and IL
  discovery only. No external model disclosure, source write, Apply, game
  directory copy, GTFO launch, screenshot capture, or gameplay claim is
  authorized by this record. Each later side effect retains its existing
  separate approval boundary.
files_in_scope:
  r/007b1b58/generated_mods/BetterHitFeedback is read-only lineage input.
  A writable target path is not admitted until current source is freshly
  materialized and Hook evidence resolves an exact edit binding.
focused_verification:
  Evaluate every operator-guided technical hypothesis against fresh
  hash/MVID-bound source, metadata, and IL evidence without treating its names
  as predetermined truth; then run affected planning/evidence/proposal tests,
  an isolated dotnet build, and separately authorized Enabled=false plus
  Enabled=true real GTFO acceptance with visible, audible, and exact
  STAGGER_FEEDBACK_SHOWN evidence.
stop_condition:
  Stop before Proposal if fresh source materialization cannot preserve the
  exact selected lineage, or if the FeatureSpec/EvidencePack cannot bind the
  two-hook correlation, local-player source, enemy identity, hit position, and
  one-hit deduplication rule. After accepted two-mode Runtime evidence, return
  to the product mainline and perform Harness re-admission only if this slice
  exposed a concrete generic Harness failure.
status: operator_guided_feature_spec_complete_ready_for_fresh_materialization_and_evidence_pack
automation_claim: not_proven
```

`AGENT-HARNESS-H3-POSTFIX-REAL-RUNTIME-ACCEPTANCE-001` completed as real
run `95efb988` and moved to `docs/audits/LOOP_HISTORY.md`. It proved the
post-fix single-missing-marker condition and the existing observation-owner
blocked route. No retry, later Harness boundary, Phase 2C, or broader Harness
expansion is selected.

`RUNTIME-OBSERVATION-MULTISNAPSHOT-001` completed the bounded observation
repair triggered by `06c09532` and moved to `docs/audits/LOOP_HISTORY.md`.
Run `95efb988` now provides its post-fix real acceptance evidence.

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
