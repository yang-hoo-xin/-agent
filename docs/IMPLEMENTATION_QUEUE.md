# Implementation Queue

Status: active and conditional work only
Last updated: 2026-07-27

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
  Fresh evidence-only run sfe_99ca8e29 materialized the selected Phase 2B
  source bytes with snapshot SHA256
  E82C26667A82CB207FBFF0B9DCB2198A8CC2B1DF3BF52FE510C59BF3B8EBC2E0
  and reread both registered current assemblies without target execution.
  EvidencePack
  1fc2d8129d45d03fb16bc31fea015df3c228e35caf3ea307180d7bae8a6ea01d
  is fresh and supports input_event_mapping, result_event_mapping,
  enemy_identity_mapping, and yellow_x_visual_path. reaction_type_scope,
  exactly_once_correlation, and feature_audio_path remain unresolved. The
  pack is partial, can_generate_patch=false, authoritative_for_patch=false,
  and blocks deterministically before Implementation Plan. The post-run
  ArtifactStore, Artifact contract, Planning, and Workflow suite passed
  129 tests in 22.64s; diff checks passed.
  That first EvidencePack remains immutable historical evidence. Separately
  authorized diagnostic Runtime sfcp_001_runtime_001 then recorded 336
  contiguous events: 144 BulletDamage, 124 EnemyAgent.OnTakeDamage, 34
  ES_Hitreact.DoHitReact, and 34 ES_Hitreact.ActivateState, with zero probe
  failures. Twenty-three of fifty-seven OnTakeDamage groups had no
  ActivateState, while every DoHitReact/ActivateState result pair matched.
  The operator-defined Micro/Light/Heavy scope retained nine Light and twelve
  Heavy results, observed no Micro result, excluded thirteen ToDeath results,
  and observed no duplicate accepted identity. The structured Runtime result
  SHA256 is
  467FD878A0A2F432177F95D68397E9E31520F100129BFBA2A8807534F11AE0E3.
  The run exited and restored its temporary DLL, log, and configuration state.
  Evidence revision sfe2_467fd878 combines that bounded Runtime record with
  the operator scope and exact current metadata for
  AK.EVENTS.get_HACKING_PUZZLE_CORRECT. EvidencePack
  c9db43852eb91f711282753daca180ef49e7eaef0ad32784db954554df7c39e5
  is fresh, supports all seven essential technical hypotheses, and has
  can_generate_patch=true and authoritative_for_patch=true. It selects direct
  ES_Hitreact.ActivateState token 0x06001387, signature blob
  2006011184301184340212B9DC11511186F8, instead of the expiring
  BulletDamage/result cache.
  Deterministic Implementation Plan
  db13ebc8f8acfaa8b0b42dea761e42a443f483aaa5f8014c4eb23a1d61bf31a6
  is fresh and non-blocking. It binds only
  Patches/HitFeedbackBehaviorPatch.cs and records the result Hook/gates,
  short-lived yellow X, and exact Wwise event path. Audible attribution,
  visible behavior, repeated valid reactions on the same enemy, and the final
  STAGGER_FEEDBACK_SHOWN exactly-once claim remain product Runtime obligations.
  The affected Planning, ArtifactStore, Artifact contract, Workflow, and
  ProposalReview suite passed 159 tests in 18.10s.
  Authorized local Proposal continuation sfp_qwen36_27b_001 then revalidated
  the exact Artifact, source, edit-binding, and selected Runtime assembly
  identities. It exposed a deterministic Proposal context conflict before
  consuming the model: the fixed 6000-character snippet budget omitted 15 of
  17 required evidence refs, which ProposalReviewer necessarily blocked.
  build_graph now accepts an explicit positive
  proposal_source_snippet_char_limit while retaining the default 6000.
  The run-specific 32768 limit preserved all 17 snippets and 25098 characters
  with no omission blocker; a no-model continuation probe reached
  proposal_review and produced no later-stage Artifact. The Workflow suite
  passed 52 tests.
  The one admitted loopback-only qwen3.6:27b call used exact digest
  a50eda8ed977ab48a12431878896b27ffd5cef552c17af3317d9623b939a7f1e,
  request body 62181 UTF-8 bytes, output budget 8192, num_ctx 131072, and
  conservative required context 70373. It timed out at the explicit 1800.0
  second provider boundary before a response or patch parser entry.
  model_call_count=1, external_disclosure_occurred=false, and
  actual_write_performed=false. No PatchProposal, ProposalReview, Dry-run,
  Apply, Build, Runtime, or Evaluation Artifact was created. The failed run is
  immutable and does not authorize a hidden retry.
  Synthetic-only local Provider probe provider_probe_qwen3_4b_001 then used
  exact installed qwen3:4b-instruct digest
  0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0.
  Its single 4805-byte loopback request was context-admitted and returned to
  deterministic Patch parsing in 6843 milliseconds. Parsing failed closed
  because the response declared RETURN_VALUE_TRUE as a literal validation
  marker but omitted that marker from after_text. The probe did not supply an
  authoritative required_validation_by_binding even though the response
  schema requires at least one expected_validation entry. It therefore proves
  local Provider transport, identity, native-schema response arrival, and the
  deterministic guardrail, but it does not qualify the 4B profile for a real
  stagger Proposal. It used synthetic input only, persisted no provider body,
  raw response, or patch text, and performed no ArtifactStore, source, game
  directory, or launch action.
  Corrected synthetic run provider_probe_qwen3_4b_002 supplied exact required
  validation provider_probe_edit_001 -> ["dotnet build"]. Its one 4942-byte
  request was admitted at conservative requirement 6990 against configured
  context 16384 and returned in 5371 milliseconds. The run reached and
  returned from LLMExactPatchGenerator.generate, proving native-schema parsing,
  stable post-response model identity, allowed binding, verbatim evidence
  substring, real replacement, and required-validation admission. It then
  failed the probe-only assertion that before_text equal the entire synthetic
  file. Product source requires only an exact non-empty substring of a
  registered evidence excerpt. The current 4B Provider and product Patch
  parser boundary are therefore verified, but the later return-true semantic
  assertion was not reached and raw response/Patch text was not retained.
  This is not real stagger Proposal-quality evidence. The run again included
  no project or commercial input and performed no ArtifactStore, source, game
  directory, or launch action.
  Real local run sfp_qwen3_4b_001 then revalidated the same four upstream
  Artifact hashes, source snapshot, all three edit bindings, the selected
  Runtime assembly, and all 17 Proposal snippets. Its one 62187-byte request
  used body SHA256
  744cde59b4f8c7c0144ab02e879bcdad4f207023078a502fe5b271abd2d0311a,
  output budget 8192, and num_ctx 131072 because the default byte proxy
  required 70379. Ollama measured the prompt at 17866 tokens, but the oversized
  profile reserved 18432 MiB of context, loaded only 9/37 layers on GPU, and
  timed out at 300 seconds. The run made one model call, entered no Patch
  parser, created no PatchProposal or later Artifact, persisted no provider
  body or raw failure response, and changed no target source or game state.
  The bounded repair preserves the byte proxy as the default and adds an
  optional bound-observation mode. It accepts observed prompt tokens only when
  the normalized structured-request SHA256 matches, with only num_ctx allowed
  to differ. Reconstruction matched the failed provider body hash and size
  exactly. Bound identity
  1680f893d40dea804b3bb190ab31c6663a9a3c4913fa23c8d8651ea5436b90b9
  admits 17866 + 8192 = 26058 inside num_ctx 32768; drift blocks before HTTP.
  Separately authorized run sfp_qwen3_4b_002 then revalidated those exact
  identities and made one loopback-only call. The 62186-byte request had
  SHA256
  7740a890725b648fa0aef3265d7bb39c12df4e7ecbf17608b9a795b9ea211f74,
  completed in about 182.5 seconds, and reported 17866 prompt plus 1344
  completion tokens. Patch parsing succeeded and wrote PatchProposal
  63b21873458088d8c26a44acc5a0f6d428967d5a5848d5899713f7be2ff2b67d.
  ProposalReview
  8c24dca68f1dace6e971f5e98efc608ed2c54ccf3c4519e1c2959c3f16ddb258
  returned blocked_scope_risk with no allowed next stage. The displayed target
  Patches/HitFeedbackBehaviorPatch.cs was outside the GTFO policy's
  root-qualified allowed paths, and review identified the marker-free branch
  root rather than the run-local materialized project, so the GameProfile was
  unsupported. No target source or later-stage Artifact was written.
  Authorized no-model run sfp_qwen3_4b_002_rereview_001 then implemented the
  bounded context repair. DomainReviewPolicy now binds one explicit target
  root while retaining allowed roots, forbidden paths, traversal rejection,
  absolute-path containment, and GameProfile status. build_graph accepts this
  explicit policy only as an alternative to an explicit DomainAdapter
  registry. The run identified the exact materialized project as
  gtfo/experimental and uniquely projected exact FeatureSpec lineage
  r/007b1b58/generated_mods/BetterHitFeedback to target root
  generated_mods/BetterHitFeedback. All three relative edit bindings passed.
  It reused PatchProposal
  63b21873458088d8c26a44acc5a0f6d428967d5a5848d5899713f7be2ff2b67d
  and wrote ProposalReview
  fa0557a0e9ceea114f19e84cd062d019907a0454cc18237ca85d4e6161f70dc1
  with approve_dry_run, no required changes, and only the manual-review
  warning. The old blocked Review remained immutable. No model or upstream
  stage ran, source hashes remained unchanged, and no Dry-run or later
  Artifact was created.
affected_coverage_ids:
  GOV-005, PLAN-001, PLAN-002, PLAN-003, PLAN-004, RET-007, RET-008, RET-011,
  PROP-002, REVIEW-001, DOM-004, DOM-006, EXEC-002, EXEC-003, EXEC-005,
  EXEC-006
dependencies:
  The EvidencePack, Implementation Plan, fresh binding gates, and bounded
  Proposal context budget, bound local Provider call, and PatchProposal are
  complete for this revision. The bounded domain-policy context repair and
  deterministic re-review are also complete. Authorized no-write run
  sfp_qwen3_4b_002_dry_run_001 reused the exact Proposal and Review, matched one
  current-source occurrence, and materialized exact diff hash
  sha256:00172af268b605a7ea05e0197509cffbd581a16eb1c62ad4fe0ea54adc12e6db
  without changing source. Separate exact-diff approval is now pending.
  Existing review, exact approval, apply, build, and product Runtime gates
  remain unchanged.
permissions_and_disclosure:
  The one diagnostic Runtime was separately authorized, completed, and
  restored. One local-only Proposal model call was authorized and consumed;
  two later synthetic-only 4B Provider probes were also separately authorized
  and consumed. One real local 4B Proposal call was then authorized and
  consumed without producing a Proposal. The separately authorized
  sfp_qwen3_4b_002 call was also consumed and produced the blocked Proposal and
  Review described above. The current turn also authorized and consumed one
  no-model re-review, which wrote only the new ProposalReview and run-local
  audit files. The current turn separately authorized and consumed one
  no-write Dry-run; it wrote only the dry_run_result and run-local audit files.
  None disclosed externally. Current admission authorizes no additional model
  call, source write, Apply, Build, game-directory copy, GTFO launch,
  screenshot capture, or product-behavior claim. Each later side effect retains
  its existing separate approval boundary.
files_in_scope:
  r/007b1b58/generated_mods/BetterHitFeedback is read-only lineage input.
  The Implementation Plan resolves exactly one future writable target:
  Patches/HitFeedbackBehaviorPatch.cs in a fresh materialization of that
  lineage. Plugin.cs and the preserved lineage remain read-only.
focused_verification:
  python -B
  workspaces/stagger_feedback_proposal_001/proposal_continuation_driver.py
  --profile qwen3-4b --preflight-only passed with 17 snippets, 25098
  characters, zero omissions, and no forbidden later Artifact.
  The authorized non-preflight command completed with model_call_count=1,
  patch_proposal_status=success, proposal_review_status=blocked,
  proposal_review_decision=blocked_scope_risk,
  actual_write_performed=false, external_disclosure_occurred=false, and no
  forbidden later Artifact.
  python -m pytest tests/unit/test_domain_adapter.py
  tests/unit/test_proposal_review.py tests/unit/test_workflow_graph.py
  -q --tb=short passed 92 tests in 17.40s after the domain-policy context
  repair.
  python -B
  workspaces/stagger_feedback_proposal_001/proposal_rereview_driver.py
  --preflight-only admitted gtfo/experimental project identity, exact
  generated_mods/BetterHitFeedback target root, three edit bindings, the bound
  Proposal, and prior Review with model_call_count=0.
  The authorized non-preflight re-review returned approve_dry_run, wrote one
  new ProposalReview revision, preserved the old Review and both source hashes,
  repeated no upstream stage, and emitted no Dry-run or later Artifact.
  python -m pytest tests/unit/test_patch_apply.py
  tests/unit/test_workflow_graph.py tests/unit/test_artifact_contract.py
  -q --tb=short passed 93 tests in 27.87s.
  python -B
  workspaces/stagger_feedback_proposal_001/proposal_dry_run_driver.py
  --preflight-only verified the exact Proposal/Review lineage, three bindings,
  five source files, and zero Dry-run or later revisions.
  The separately authorized non-preflight command wrote successful Dry-run
  Artifact
  ab42c7da8bd8e1a2a209fa51f3fd023e4c0dfaf7d9d5a3f8b6ad324aeeff632f,
  matched one occurrence in Patches/HitFeedbackBehaviorPatch.cs, recorded
  exact diff hash
  sha256:00172af268b605a7ea05e0197509cffbd581a16eb1c62ad4fe0ea54adc12e6db,
  preserved the complete source snapshot, and emitted no Apply or later
  Artifact.
  python -m pytest tests/unit/test_ollama_llm.py
  tests/unit/test_patch_code_generator.py tests/unit/test_local_entry.py
  -q --tb=short passed 141 tests in 1.56s after the bound context repair.
  Revalidate EvidencePack
  c9db43852eb91f711282753daca180ef49e7eaef0ad32784db954554df7c39e5,
  Implementation Plan
  db13ebc8f8acfaa8b0b42dea761e42a443f483aaa5f8014c4eb23a1d61bf31a6,
  the selected assembly identity, and all three edit bindings before Proposal.
  A later product Runtime must separately prove visible and audible behavior,
  General.Enabled=false suppression, and exact marker behavior.
stop_condition:
  Stop with immutable failed runs sfp_qwen36_27b_001,
  sfp_qwen3_4b_001, and
  provider_probe_qwen3_4b_001 plus probe-outer-assertion failure
  provider_probe_qwen3_4b_002. Preserve sfp_qwen3_4b_002 as the immutable
  completed Proposal/blocked Review run and preserve
  sfp_qwen3_4b_002_rereview_001 as the successful no-model Review revision.
  Preserve sfp_qwen3_4b_002_dry_run_001 as the successful no-write exact-diff
  run. Do not call a model again. Stop before isolated Apply until the user
  separately approves exact diff hash
  sha256:00172af268b605a7ea05e0197509cffbd581a16eb1c62ad4fe0ea54adc12e6db.
  Later stages must retain exact Proposal, Review, source, Artifact, approval,
  Build, and Runtime gates.
status: dry_run_complete_exact_diff_approval_pending
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
