# Active Product Contract

Status: normative daily execution contract
Last updated: 2026-08-29

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
-> complete Plan/binding deterministic proposal review
-> no-write unified diff and low-cost static checks
-> human semantic review and exact-diff approval
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

### 1.1 Current Development Selection

The current product milestone is **Coding Agent v0**. The first integrated
delivery is **Coding Agent v0 internal alpha**, which composes the existing
RAG/ER, Planning, Proposal, Review/Dry-run, Build/Test, Repair, Graph, and
ArtifactStore modules. It does not create a second Agent framework or a second
workflow.

The selected simple task remains `ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001`.
P0 false-sufficiency closure remains completed, and the current product stage
remains the P2 empirical path. P1 code structure does not by itself establish
product completion.

The latest real ProductExecution is `p2_ac_20260825_015/actual_15`, consumed
once. Its wrapper reached terminal while ProductExecution remained `partial`.
It passed Entry, continuation-packet revalidation, baseline Build,
compiled-plugin inspection, `requirement_projection`, `requirement_findings`,
sufficient Coverage, and non-blocking Planning. The `initial_patch` request was
admitted and the third real model call formed, but the provider returned no
response before the 600.0-second timeout. The Patch payload parser was not
entered. Detailed run evidence and exact Issue triggers are kept only in
`docs/audits/ENGINEERING_ISSUE_REGISTER.md`.

`EVID-003` and `EVID-004` remain closed. The authorized-once 27B Patch-only
replay has now been consumed. It reconstructed the frozen two-unit Plan and
formed exactly one `qwen3.6:27b` `initial_patch` call under the frozen
configuration, but again reached provider timeout without a complete response
or parser entry. `EVID-005` therefore remains active; repeating the same 27B
call or increasing timeout is not the next route.

The replay also supplied the independent close evidence for `PLAN-002`: the
three edit units normalized to two, the outer authorized 115-160 unit remained,
and the inner evidence remained in supporting lineage before provider
invocation. `PLAN-002` is now closed. Provider response is outside that Issue.

A separate isolated `qwen3:4b-instruct` Patch-role probe used the same canonical
input identities and normalized provider body. Its single call returned a
complete response and entered the parser, but deterministic admission rejected
`edit_binding_001` with `before_text_outside_edit_binding`; the raw response had
two changes and formed zero `GeneratedPatch` items. This was not an actual or a
fallback and does not establish a 4B production Patch role.

The rejection was correct and is not resolved by deterministically injecting
`before_text`. `edit_binding_001` authorizes only `Configuration.cs`,
`OnFileChanged`, span 35-55. The requested setting also
requires a property declaration near lines 12-17 and a default binding in
`BindAll` near lines 50-78; the latter appears only as supporting evidence, not
edit authority. The 4B `before_text` crosses from `OnFileChanged` into
`BindAll`. Its `after_text` also references nonexistent `_targetSpread` inside
`Configuration`, while its Spread change sets `_targetSpread = 0.0f` and then
still overwrites the game-supplied raw `crosshairSize` with
`GetCrosshairSize()`. The raw response is therefore not a semantically valid
zero-model `GeneratedPatch` materialization reference.

`EVID-007` is closed by checkpoint
`d80a188bd694f07dc725590b76f959514102d3c9`. The frozen owner audit localized
the defect to `resolve_requirement_coverage`: v1 treated every
change-plus-support `unresolved_gaps` entry as an expected implementation delta,
so the actual15 Finding's missing Configuration property/BindAll authority was
ignored. Coverage v2 now reserves `unresolved_gaps` for missing evidence,
current-source facts, or edit authority required before Patch. Any such gap
clears edit targets and blocks before Patch; the requested behavior's expected
implementation delta is carried by the change requirement instead. Historical
v1 Artifacts retain their original semantics. `EVID-006` is now the next active
response-contract/model-role boundary.

The current code lineage is compact Patch input checkpoint
`05bbca578baad23403d3ab7fc3327755592e3ac8`, sealed run-family continuation
orchestration checkpoint `d353bd0cf4750e8c902f1639c7787fed4b6afa20`, and
nested physical edit-unit normalization checkpoint
`53d228fa14e00ebd2fcbc64cc1ba331623668fd4`, and Coverage gap-semantics
checkpoint `d80a188bd694f07dc725590b76f959514102d3c9`. Its claim is bounded to
deterministic orchestration, change-unit normalization, authority-gap
admission, and tests. It is not a
claim of model, Patch, or Build success; actual15's baseline Build is separate
run evidence. It also does not prove Review, Dry-run, Apply, or a
changed-product Build.

Current execution order:

```text
-> P0 false-sufficiency closure complete
-> P1a structural coverage and P1b formal provider entry complete
-> actual15 passes Entry through sufficient Coverage and non-blocking Planning
-> actual15 Patch request admitted; real initial_patch call formed; EVID-004 closes
-> authorized-once frozen 27B Patch-only replay repeats provider timeout; EVID-005 remains active
-> replay verifies three-to-two physical edit-unit normalization; PLAN-002 closes
-> isolated 4B probe returns a complete but semantically invalid response; exact-binding admission correctly rejects it
-> EVID-007 owner audit localizes the loss to Coverage v1 change-gap semantics
-> checkpoint d80a188 introduces versioned v2 semantics and closes EVID-007
-> EVID-006 becomes the next response-contract/model-role code/test boundary
-> only after both boundaries are reviewed, decide whether to authorize a fresh Patch-only probe
-> do not repeat the same 27B call, increase timeout, run a 4B correction, or prepare actual16
-> PatchProposal -> ProposalReview
-> complete Dry-run diff -> wait for human exact-diff approval
-> only after approval: isolated Apply -> changed-product Build
-> complete one actual-only Build/Test success and one Failure -> Different Repair -> Revalidation
-> Coding Agent v0 internal alpha checkpoint
```

The one bounded Patch-only replay authorization has been consumed. No fresh
Patch-only probe, fresh preflight, actual16 packet, or actual16 execution is
authorized or created. Exact-diff approval can be requested only after a
complete Dry-run diff. The current product stage remains the P2 empirical path;
`P0` decision priority in the Issue Register is work priority, not a product
stage. The two Internal Alpha hard gates remain false: actual-only
changed-product Build/Test success and Failure -> Different Repair ->
Revalidation. Coding Agent v0 internal alpha, Runtime, stable Agent capability,
and Public Alpha all remain false or unauthorized.

## 2. Current Verified Capability

The remainder of this section records previously verified bounded product and
Harness facts. It is not the current implementation queue and does not prove
the current RAG/ER or Coding Agent v0 milestone.

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

The current Stagger M1 product continuation has now exercised the repaired
BetterHitFeedback source and the bounded two-mode GTFO Harness. The approved
`edit_binding_004` change replaced only the failed RectTransform acquisition;
source SHA256 moved from `65489604...BB3B` to `77D0E4C6...F0AE`, and the real
local Build produced DLL SHA256 `129F13DD...76D`. Run-local `run_004` exposed
one Harness defect after the second process: a valid byte-zero
`replaced_or_truncated_after_prelaunch_boundary` log generation was rejected
by the post-run full-copy saver. That failed run remains immutable, records no
product acceptance, and restored both DLL and config state. The bounded repair
accepts both valid byte-zero generation modes and has focused success,
exception, restoration, process-termination, independent-output-root, and full
post-run-copy coverage.

Real `run_005` then completed both ordered modes. The disabled process produced
no BetterHitFeedback output. In the enabled process the operator directly
observed the yellow X, attributable extra cue, and existing Mod feedback as
normal; current-run markers also recorded `visual_reason=yellow_x_spawned` and
nonzero audio acceptance. Both full current-run generations were copied under
the run-local root with prefix identity verification, all GTFO/Python processes
terminated, the temporary DLL was removed, and the config returned to SHA256
`717C5F4B...DB82E`. The result remains `inconclusive`, not accepted: duplicate
result-event behavior and the listed non-local/stale/excluded negative paths
were not directly exercised. Screenshot files retain confidence `0.0` and do
not replace the operator observations.

The existing ArtifactStore now records blocked-report revision
`967A9629...07F0` for the formal continuation boundary. It does not manufacture
a new `BuildResult` or `RuntimeEvidence`: the latest registered BuildResult is
for the prior DLL, and the complete deterministic projection payload behind
approved diff hash `sha256:e8f41d05...b7163` was not persisted. Reconstructing
that missing identity is forbidden. This formal blocker does not undo the real
Harness result, but it prevents promotion to an ArtifactStore Runtime success.
This Harness repair introduced no new Artifact, Approval, Request, or
permission contract. Earlier in the same Stagger M1 branch, the
Planner-admission slice had already added and materialized
`repair_planning_request`, `repair_planning_approval`,
`root_cause_evidence`, and `repair_hypothesis_set`; those persisted revisions
remain readable, but the later contract-reuse-first rule forbids further
Stagger-specific contract expansion without a separately proven repeated gap.

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

Post-fix negative run `95efb988` real-exercised the multi-generation
observation repair. The collector retained current-run `BepInEx`,
`Chainloader`, and `chain_probe=true` facts through the full timeout while only
the deliberately absent marker remained missing. The same graph emitted an
observation-owned RepairPlan, authorized no source repair, repeated no upstream
stage, reached blocked terminal, and restored the deployed DLL.

The selected stagger-feedback product slice remains at its evidence-bound
Implementation Plan. Local Proposal continuation `sfp_qwen36_27b_001`
revalidated the current source, Artifact, edit-binding, and Runtime assembly
identities and used an explicit graph-level snippet budget to retain all 17
required evidence refs. Its one authorized loopback-only `qwen3.6:27b` call
timed out at 1800 seconds before any response or parser entry. Therefore no
PatchProposal or later-stage Artifact exists, no source was written, and the
failed run grants no retry authority. A later attempt must be separately
authorized and must continue from the existing Implementation Plan without
repeating upstream stages.

Synthetic-only local Provider probe `provider_probe_qwen3_4b_001` then bound
the installed `qwen3:4b-instruct` digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
and returned through the loopback native-schema path in 6.843 seconds. The
deterministic Patch parser rejected the response because it declared
`RETURN_VALUE_TRUE` as a literal validation marker without placing that marker
in `after_text`. The synthetic probe supplied no
`required_validation_by_binding` even though the response schema requires at
least one `expected_validation` entry, so this run proves local transport,
identity, context admission, response arrival, and fail-closed parsing; it
does not qualify the 4B profile for the real stagger Proposal. The run included
no project or commercial source, persisted neither provider body nor raw
response or patch text, made no ArtifactStore or target write, and did not
launch the game. Stagger therefore remains at the existing EvidencePack and
Implementation Plan with Proposal absent.

Separately authorized corrected synthetic probe
`provider_probe_qwen3_4b_002` supplied exact
`provider_probe_edit_001 -> ["dotnet build"]` validation ownership. Its one
4,942-byte request was admitted at conservative context requirement 6,990
against configured 16,384 and returned in 5.371 seconds. The actual
`LLMExactPatchGenerator` completed native-schema parsing, post-response model
identity admission, binding validation, verbatim evidence-substring
validation, real-replacement validation, and required-validation checks. The
run then failed only in the probe's stricter outer assertion that
`before_text` equal the entire synthetic file, while the product contract
accepts an exact non-empty substring of a registered evidence excerpt. This
qualifies the 4B local Provider through the current product Patch parser, but
does not prove that the unpersisted generated `after_text` satisfied the
requested `return true;` behavior or that 4B can produce an acceptable real
stagger Proposal. No additional synthetic call is selected. Real Proposal
continuation remains separately authorized work.

The first real 4B continuation `sfp_qwen3_4b_001` then revalidated all four
upstream Artifacts, the three edit bindings, source snapshot, selected Runtime
assembly, and the 17-snippet Proposal context before making one local call.
The 62,187-byte request used `num_ctx=131072` because the default conservative
byte proxy reported required context 70,379. Ollama later reported the exact
prompt as only 17,866 tokens, but the oversized context reserved 18,432 MiB,
offloaded most context plus 28 of 37 model layers to host memory, and timed out
at 300 seconds before Patch parsing. No PatchProposal or later Artifact was
created, no provider body or raw failure response was persisted, and no target
source or game state changed.

The bounded repair keeps that default fail-closed byte proxy unchanged. A new
optional admission mode accepts a prior observed prompt count only when a
normalized structured-request identity SHA256 also matches; the identity
excludes only `num_ctx`. Reconstruction of `sfp_qwen3_4b_001` matched its
recorded provider-body SHA256 and byte count exactly. The bound observation
therefore admits the same prompt plus the 8,192 output budget as 26,058 tokens
inside `num_ctx=32768`, while any input/schema/profile drift blocks before
HTTP. Focused affected tests pass.

Separately authorized continuation `sfp_qwen3_4b_002` then used that exact
bound identity for one loopback-only call to the installed
`qwen3:4b-instruct` digest. The call completed in about 182.5 seconds, reported
17,866 prompt tokens and 1,344 completion tokens, entered the Patch parser, and
wrote PatchProposal
`63b21873458088d8c26a44acc5a0f6d428967d5a5848d5899713f7be2ff2b67d`.
Deterministic ProposalReview
`8c24dca68f1dace6e971f5e98efc608ed2c54ccf3c4519e1c2959c3f16ddb258`
returned `blocked_scope_risk` with no allowed next stage. It found the
proposal path `Patches/HitFeedbackBehaviorPatch.cs` outside the GTFO policy's
root-qualified allowed paths and found that review resolved the current branch
root to an `unsupported` GameProfile, even though the bound source was the
run-local materialization of the preserved GTFO lineage. This is a
continuation/domain-policy context mismatch, not authority to weaken path or
GameProfile gates. The run made exactly one model call, disclosed nothing
externally, wrote no target source, and produced no Dry-run, Apply, Build,
Runtime, Evaluation, or terminal Artifact. No further model call is authorized;
the existing Proposal may be reconsidered only through a separately bounded
no-model review-context repair and a fresh deterministic ProposalReview.

Authorized no-model run `sfp_qwen3_4b_002_rereview_001` completed that repair
without changing the existing Proposal or either source tree. The existing
`DomainReviewPolicy` can now bind one explicit target root while preserving its
allowed-root, forbidden-path, traversal, absolute-path, and GameProfile gates;
`build_graph()` accepts that explicit policy only as an alternative to its
existing DomainAdapter registry resolution. The run identified the exact
materialized BetterHitFeedback project as `gtfo/experimental` and uniquely
projected FeatureSpec lineage
`r/007b1b58/generated_mods/BetterHitFeedback` to policy target root
`generated_mods/BetterHitFeedback`. All three project-relative edit bindings
then passed the unchanged GTFO root policy. Re-review reused PatchProposal
`63b21873458088d8c26a44acc5a0f6d428967d5a5848d5899713f7be2ff2b67d`
and wrote ProposalReview
`fa0557a0e9ceea114f19e84cd062d019907a0454cc18237ca85d4e6161f70dc1`
with `approve_dry_run` and one manual-review warning. The prior blocked Review
remains immutable. The run made zero model calls, repeated no upstream stage,
changed no source, and stopped before Dry-run with no Apply, Build, Runtime,
Evaluation, or terminal Artifact. `approve_dry_run` is review evidence, not
permission to execute Dry-run or any later stage.

Separately authorized no-write continuation
`sfp_qwen3_4b_002_dry_run_001` then reused that exact Proposal and approving
Review without calling a model or repeating an upstream stage. The existing
`ExactTextPatchApplier` matched one live UTF-8 occurrence in
`Patches/HitFeedbackBehaviorPatch.cs`, staged the replacement only in memory,
and persisted successful Dry-run Artifact
`ab42c7da8bd8e1a2a209fa51f3fd023e4c0dfaf7d9d5a3f8b6ad324aeeff632f`
with exact diff hash
`sha256:00172af268b605a7ea05e0197509cffbd581a16eb1c62ad4fe0ea54adc12e6db`.
The bound file remained at SHA256
`92eab8010eed49e8c84094dc6eb5376d5f995414c40cf7d2c44fc1955d405e1a`
and the project snapshot was unchanged; no temporary patch file, Apply, Build,
Runtime, Evaluation, or terminal Artifact was produced. The Dry-run proves
only current-source exact-text applicability and the bytes proposed for a
future isolated write. It does not authorize that write or establish compile
or product behavior correctness. At that boundary, isolated Apply required
separate user approval of the exact diff hash above.

The user then supplied that exact hash. Run
`sfp_qwen3_4b_002_isolated_apply_001` revalidated the complete Artifact
lineage, three edit bindings, current source, and approved diff before
atomically applying the single change inside the run-local materialization.
Isolated Apply Artifact
`be03b9a981e27e4bc8098e144990ce762890d4dd6fa3cac421751de9dd2e325e`
records `actual_write_performed=true`, `real_patch_applied=true`, and matching
approved/applied diff hashes. Only
`Patches/HitFeedbackBehaviorPatch.cs` changed, from SHA256
`92eab8010eed49e8c84094dc6eb5376d5f995414c40cf7d2c44fc1955d405e1a`
to `8a67511bd773353f34d9e527e2d6660c461d6a291da8c7576b29eee231ae5bc5`.
The preserved source lineage was not changed, no temporary patch file
remained, and no Build, Runtime, Evaluation, or terminal Artifact was
produced. This proves only the exact approved isolated source write. A real
Build requires separate authorization and verification.

Subsequent human semantic review rejected that applied run-local diff before
Build. The immutable Apply remains evidence that the old bytes were written
only in isolation; it is not an accepted implementation and grants no Build
authority. The rejection exposed a general admission defect: Patch Generation
had not received the complete Implementation Plan change set, accepted
`before_text` from any evidence excerpt instead of the selected edit binding,
and ProposalReview checked only the returned subset. The one-change Proposal
therefore omitted `chg_002/edit_binding_002` and
`chg_003/edit_binding_003`, crossed the selected binding for `chg_001`, and
still reached an approving Review after the separate domain-context repair.

The bounded repair keeps the same graph and Artifact contracts. Patch
Generation now receives compact required change units and must return exactly
one `(change_id, edit_binding_id)` pair for every planned change.
ProposalReview independently enforces complete Plan coverage and binding-local
source. The exact-text applier additionally enforces target-span locality,
builds a full unified diff before any write, reports real insertion/deletion
counts and raw diff SHA256, and runs a low-cost C# delimiter check whose
recorded limitation is that it does not resolve symbols, types, overloads, or
all control flow. The CLI displays those pre-write facts before requesting the
exact approval hash. Focused Generator, Review, Apply, local-entry, and Workflow
tests pass `186` cases.

One new loopback-only 4B repair attempt
`sfp_qwen3_4b_repair_002` timed out at its single 600-second boundary before
parser entry and produced no Proposal. No retry or fallback occurred.
No-model run `sfp_manual_repair_005` then reused the existing FeatureSpec,
EvidencePack, Implementation Plan, domain policy, LangGraph, and ArtifactStore.
It produced three-change PatchProposal
`d3737a8679c9e64fe7c6ea13985334419810b58799d4cb477aade842f9e09a3a`
and approving ProposalReview
`e50f938ae7317fc959f20df8366b6192e8d9a10ac163c1105b3267f50e5fbe1`.
Its preapproval no-write projection changes only
`Patches/HitFeedbackBehaviorPatch.cs`, with three change units, 173 insertions,
zero deletions, unified-diff SHA256
`6164c0fb966321badd69f3b1e63cd2c3c4e5153c1c28d4578daa1cde55d1fafe`,
and future exact-approval hash
`sha256:c9e7903739f5b99422a6b6b130a6bbb0acfba41d47e6d2a4148ad33f3469cdaa`.
All three binding-span checks and the lexical C# check passed. The source
remains at SHA256
`92eab8010eed49e8c84094dc6eb5376d5f995414c40cf7d2c44fc1955d405e1a`;
no model, external disclosure, source write, Build, or Runtime occurred. A
supplied external review then judged the main Hook, reaction filter,
local-source, visual, audio, and success-gating design acceptable but identified
that the success marker did not include the FeatureSpec's two exact code-level
facts. It did not approve the displayed bytes.

No-model marker-contract revision `sfp_mmr_007` preserves the old Proposal,
Review, and patch as immutable history. It produced PatchProposal
`37368a6353e59bd76627b72b0ac76433f459090a41058492ad038cf2616dfa93`
and approving ProposalReview
`f098d9d2c6d26c3eece62b7b39966f7b8002a4aeb8ce382f7dca3f5054af026d`.
The revised no-write patch still changes only
`Patches/HitFeedbackBehaviorPatch.cs` through the same three units and line
counts. Relative to the prior patch, exactly one patch line was replaced so
the sole `STAGGER_FEEDBACK_SHOWN` write now includes the exact FeatureSpec
facts `visual_spawn_succeeded=true` and `audio_event_accepted=true`; Hook and
behavior logic did not change. The revised unified-diff SHA256 is
`5d6d6439bf1c5b3f7795a1d27a1326c0e6f038f3fc7b8d1f4c42f1ab82c3b4cf`,
and its future exact-approval hash is
`sha256:c6fb31dfbdf09b877cdd9e018af26f5441e0b0f30680e5a0e0cb84355e30c7ca`.
All binding-span and lexical checks passed. The source still has SHA256
`92eab8010eed49e8c84094dc6eb5376d5f995414c40cf7d2c44fc1955d405e1a`;
model calls, disclosure, source writes, Apply, Build, and Runtime remain zero.
The user then approved exact-diff identity
`sha256:c6fb31dfbdf09b877cdd9e018af26f5441e0b0f30680e5a0e0cb84355e30c7ca`
for one isolated Apply while explicitly retaining Build and Runtime as later
evidence boundaries. Run `sfp_mma_008` created a fresh materialization from the
preserved source lineage, revalidated the exact Proposal, Review, three
bindings, domain policy, Runtime assembly identity, reviewed patch SHA256, and
before/after source hashes, then used the existing LangGraph to persist
Dry-run Artifact
`704fa77085b715969d2d3e05183c29b1acbdaac7fb3c81185ecd217d3184a4a6`
and isolated Apply Artifact
`0abffbc29e55b4d33d14b61f746eafdf15a1861c021e86406f71b09ff192ab21`.
Only `Patches/HitFeedbackBehaviorPatch.cs` changed, from SHA256
`92eab8010eed49e8c84094dc6eb5376d5f995414c40cf7d2c44fc1955d405e1a`
to `65489604eec41d073ff5bda77940481ae63be1917ede199c99ed04c7b180bb3b`.
The approved and applied exact-diff identities match, no temporary patch file
remains, and both the reviewed `sfp_mmr_007` source and preserved lineage retain
their original SHA256. The run made zero model calls, repeated no upstream
stage, disclosed nothing externally, and emitted no Build, Runtime, Eval, or
WorkflowSummary Artifact. Apply/Workflow/Artifact regression tests pass `95`
cases.

Separately authorized run `sfp_build_009` continued from those exact Dry-run
and Apply Artifacts without repeating any upstream stage. Run-local restore and
`dotnet build --no-restore` completed with exit code `0`, zero warnings, and
zero errors. BuildResult
`215025bd406c09062e44297982a29d9abde587b4ea04b4c0ebc26344a6b5040f`
verifies `BetterHitFeedback.dll` SHA256
`7a04ebc37c58572835621640eeac52360f7d5e8b8ea7d68a8d1c3800b2cf21aa`
and size `91136` bytes. Read-only metadata inspection verifies the BepInPlugin
identity and compiled stagger Postfix, visual helper, and audio helper without
executing target code. Fresh WorkflowCheckpoint
`1612ca4562364d84bc47c934687e3cfa2a478f4b72733f074a0593a79b23be2e`
has no lineage or Build-handoff blockers and binds
`next_graph_node=collect_runtime_evidence`. The run made zero model calls,
did not repeat Apply or Build, did not write the game directory, did not launch
GTFO, and emitted no RuntimeEvidence, ResumeReport, EvalReport, or
WorkflowSummary. The current stop is separate product Runtime authorization;
Build evidence is not product-behavior evidence.

The bounded P0 integration repair now lets `resume-runtime` accept an explicit
`artifact_store_root` independently of the manifest `run_root`, while preserving
`run_root/a` as the default. Its public `preflight-runtime` entry validates the
selected Store, checkpoint revision ownership, run/request/feature identity,
manifest handoff, recursive freshness, BuildResult, physical DLL hash/size/mtime,
lineage, and durable consumption state without writing a ResumeReport,
consuming the checkpoint, entering LangGraph, copying a DLL, or launching a
process. The real `sfp_build_009` checkpoint plus the original shared Store
passed this read-only preflight.

P1 now prepares a reviewed run-local two-process profile at
`workspaces/stagger_runtime_admission_001/runtime_profile.yaml`. It retains the
current machine paths, successful run `e7daa266`, the exact FeatureSpec and
compiled marker source, and adds two hash-bound config inputs derived from the
existing successful `General.Enabled` Runtime history. The selected GTFO-domain
provider runs `General.Enabled=false` first and `General.Enabled=true` only
after the first attempt passes. Each process gets its own DLL/config deployment,
current-run log boundary, screenshot, termination, and exact restoration
record. This is a bounded Stagger product-profile implementation, not a generic
Runtime scheduler or new Artifact system.

The provider now exposes operator completion after its required log condition.
Each request binds a fresh `request_id`, `feature_id`, profile id, process id,
the exact criterion text and SHA256, and a 900-second operator timeout. Replies
must report every displayed criterion as `passed`, `failed`, or
`not_observed`, with direct notes and operator identity. The provider recollects
the current-run logs after the reply, captures the screenshot, terminates the
process, then restores config and DLL. Only `passed` manual observations support
acceptance; failed or missing trust remains inconclusive. The 600-second
`timeout_seconds` still begins after process launch and covers startup/product
marker wait; it is separate from the later operator-completion timeout.

Startup markers remain exactly `BepInEx` and `Chainloader`. The structured
`signal=STAGGER_FEEDBACK_SHOWN ... visual_spawn_succeeded=true
audio_event_accepted=true` substring remains bound only to the FeatureSpec's
code-level marker criterion and never substitutes for visible or audible
observation. The disabled attempt owns the exact `General.Enabled=false`
criterion; the enabled attempt owns the remaining six criteria, with five
directly reported by the operator and the marker criterion requiring both the
current-run log marker and its normal trust binding.

The public preflight and actual `resume-runtime` admission both receive the
exact FeatureSpec acceptance list. Actual continuation performs that profile
and provider admission before writing ResumeReport or consuming the checkpoint.
Focused settings guards prove this Runtime path does not read LLM, Embedding,
Vector Store, or Reranker settings after configuration parsing. At the
no-launch preflight boundary, the checkpoint was unconsumed, ResumeReport and
RuntimeEvidence counts were zero, and no game-directory write or process launch
had occurred. Agentic and RAG expansion is not selected: neither supplies a
missing signal for this deterministic Runtime admission boundary. The final
real-input no-write preflight returned
`READY_FOR_EXTERNAL_AUTHORIZATION` with `stagger_acceptance.status=ready`,
current config SHA256
`717c5f4bce731d33defc861da3a9e54011f7baa8f1b61bc8a383d20f775db82e`,
and no checkpoint consumption, ResumeReport, RuntimeEvidence, process launch,
DLL copy, or file write. This is readiness to request the external launch/write
permission for the reviewed two-process attempt; it is not Runtime evidence or
seven-criterion acceptance.

The separately authorized first real continuation then wrote accepted
ResumeReport `resume_87604d6c789049a19e19c708be168b7d` and consumed the
single Build checkpoint, but failed before either GTFO process launch. The
configuration backup path ending in
`general_enabled_false/config/local.betterhitfeedback.cfg.before` is 273
characters on this run root; `shutil.copy2` raised `FileNotFoundError`. No
RuntimeEvidence, EvalReport, or WorkflowSummary was written. The GTFO process
is absent, the plugin destination is absent, and the game configuration remains
at SHA256
`717c5f4bce731d33defc861da3a9e54011f7baa8f1b61bc8a383d20f775db82e`.
Only empty backup directories were added under the Build root. The continuation
is blocked: preserve the accepted ResumeReport, consumed checkpoint, and empty
directories until the backup-path and post-acceptance recovery boundary is
repaired and separately authorized.

The bounded recovery repair now uses the fixed backup filename `original.bin`,
so the longest real Stagger backup path is 251 characters instead of 273.
Empty directories are reusable, but any file or symlink under the backup root
remains a hard blocker. New `--recover-accepted-resume` mode requires the exact
prior `resume_id`, exactly one accepted ResumeReport bound to the checkpoint,
fresh unchanged Build lineage and bytes, no RuntimeEvidence/EvalReport/
WorkflowSummary for the run, and an unchanged Runtime admission snapshot. It
reuses the immutable ResumeReport and writes no second report. The real-input
recovery preflight returned `READY_FOR_EXTERNAL_AUTHORIZATION` with zero writes,
zero graph entry, zero process launch, zero DLL copy, and no backup material.
It also returned `accepted_resume_admission_match=true`, proving the exact
current admission snapshot still equals the immutable accepted ResumeReport.
The separately authorized recovery then executed the first
`General.Enabled=false` process. GTFO PID 8432 loaded BepInEx, Chainloader, and
BetterHitFeedback; the current-run log recorded `MOD_DISABLED` after plugin
load. The operator submitted `failed` while directly reporting that repeated
shotgun hits produced no BetterHitFeedback UI or audio. That observation
content is consistent with the disabled-mode negative criterion, but the
explicit failed status is authoritative and cannot be reinterpreted as a pass.
The provider therefore skipped `General.Enabled=true` and wrote blocked
RuntimeEvidence `12223427...93c4d`, RepairPlan `21d71010...a4dc`, and
BlockedReport `3d4b76bc...87088`. Failure ownership is `observation`,
`source_repair_allowed=false`, and none of the seven criteria is proved.

The run restored the plugin and config exactly: GTFO process count is zero, the
destination DLL is absent, and the config SHA256 is again
`717c5f4bce731d33defc861da3a9e54011f7baa8f1b61bc8a383d20f775db82e`.
It also exposed two new Harness evidence blockers. The UTF-8 Chinese operator
note was not preserved in RuntimeEvidence, and the 272-character process
diagnostic output path failed with `FileNotFoundError`. The captured screenshot
is visual-only with no acceptance support.

The bounded post-observation repair preserves that immutable result while
closing all three forward evidence-integrity gaps. Operator stdin is now read
as bytes and decoded explicitly as UTF-8. Process diagnostics use fixed
run-local `stdout.log` and `stderr.log` names, and no-launch continuation
preflight validates both deployment-backup and diagnostic paths against the
Windows boundary. Stagger operator requests now hash-bind mode-specific product
guidance and require the operator to report the criterion fact separately from
the status: `true` with `passed`, `false` with `failed`, and `null` with
`not_observed`. A missing or contradictory fact yields
`operator_status_semantic_conflict`, `correction_required=true`, an
inconclusive observation-owned result, and no source-repair authority. Machine
markers, configuration, current-run log windows, and restoration checks remain
independent gates and cannot be overridden by the operator fields. This repair
does not reinterpret the prior Artifact. The existing backup material remains a
hard blocker on the old run root.

A new bounded observation-retry branch now reuses the exact immutable
checkpoint and accepted ResumeReport without creating either Artifact again.
It admits only the latest RuntimeEvidence when it is inconclusive,
observation-owned, bound to the same Build, and explicitly forbids source
repair; the latest RepairPlan must require `repair_runtime_observation`, require
new evidence, retain retry budget, and bind that exact RuntimeEvidence. Prior
DLL/config restoration must be complete. Every retry uses a separate absolute
empty output root, isolates captures/diagnostics/backups/results there, and is
counted against the RepairPlan budget from immutable RuntimeEvidence revisions.
Product-owned failures, stale Build lineage, terminal Eval/Workflow state,
changed admission, incomplete restoration, occupied output roots, and exhausted
budgets block before graph entry or external action.

The real retry #1 no-launch preflight bound RuntimeEvidence
`12223427...93c4d`, RepairPlan `21d71010...a4dc`, ResumeReport
`40004f6c...960a0`, and unchanged Build/checkpoint lineage. It returned
`READY_FOR_EXTERNAL_AUTHORIZATION`, with maximum planned output path 216
characters and every write/graph/process/DLL field false.

The separately authorized retry #1 then launched only
`General.Enabled=false`. The operator exercised a qualifying non-death
reaction and directly observed no additional yellow X and no
feature-attributable cue. That observation was not bound because the Codex PTY
session identifier was lost while the Runtime process was waiting on stdin.
The provider timed out rather than fabricating a response, wrote inconclusive
RuntimeEvidence `0398621b...152fd`, RepairPlan `326a4121...ae28b`, and
BlockedReport `0395c5ea...b003`, and did not launch the enabled process. This is
`operator_completion_failed` owned by observation, not a BetterHitFeedback
product failure. GTFO exited, the temporary DLL was removed, and the original
config SHA256 `717c5f4b...82e` was restored.

The bounded forward repair keeps stdin as the default for ordinary Runtime but
gives observation retries a recoverable run-local exchange. Each exact
`GTFOOperatorCompletionRequest` is persisted under the retry output root, and
the reader accepts only the response and confirmation filenames declared by
that request. A response remains editable and unread until a separate
confirmation binds the exact response-file bytes by SHA256; pre-existing
request, response, or confirmation paths block. The request survives task
compaction, so an operator response can be built, corrected, and explicitly
confirmed from the exact stored request identity and criteria without guessing
or restarting the game. The retry #2 no-write preflight returned
`READY_FOR_EXTERNAL_AUTHORIZATION`, retry number 2, one remaining attempt,
prior restoration `passed`, operator exchange path length 211, maximum output
path 216, an empty output root, and every write/graph/process/DLL field false.
It authorizes nothing by itself.

The separately authorized retry #2 predates that two-phase confirmation and is
immutable. Its disabled attempt passed the bound negative observation and its
enabled attempt loaded the exact DLL/config, then exercised multiple enemies.
Current-run logs contain in-scope `reaction_type=Light` and
`reaction_type=Heavy` samples followed by
`signal=STAGGER_FEEDBACK_SKIPPED`, `visual_spawned=False`,
`visual_reason=missing_canvas_rect_for_stagger_x`,
`audio_event_accepted=True`, and nonzero `playing_id` values. The operator
directly confirmed no additional yellow X. The first submitted response also
labelled the audio criterion failed; after submission, the operator clarified
that a quiet cue might have been masked by gunfire. Therefore the current
product statement is: visual output failed, audio-event acceptance succeeded
at code level, and player-observable audibility is not established. The
immutable RuntimeEvidence still contains the earlier audio status and is not
rewritten.

The run ended `inconclusive`/blocked with RuntimeEvidence
`3c1554faf998d491d2c09930a923334ec7bb4d4157301f4c2b99f13428646f33`,
RepairPlan
`f3cfb335b541998e5229ef4d22f0038d428ed3f8bebd311cafe74eccb9ea1664`,
and BlockedReport
`2eca02a4cbbf153c4a9a1504aa79e2685224aff1d42a05cea80a2c8796ad1886`.
The stored failure owner remains `observation`,
`source_repair_allowed=false`, because the full attempt did not bind all
required observations. GTFO exited, the temporary DLL is absent, and
`local.betterhitfeedback.cfg` was restored to SHA256
`717c5f4bce731d33defc861da3a9e54011f7baa8f1b61bc8a383d20f775db82e`.
No further Runtime attempt or Mod source repair is authorized by this result.

The current Stagger follow-up now has a public no-write Edit Authority
preflight. It rereads the exact FeatureSpec, immutable retry #2
RuntimeEvidence, current Implementation Plan, current PatchProposal, and the
read-only `sfp_build_009` source bytes. Deterministic replay binds the exact
yellow-X criterion to both the trusted
`missing_canvas_rect_for_stagger_x` current-run fact and the consistent direct
operator failed observation. It does not rewrite the stored RuntimeEvidence:
the original owner remains `observation` with
`source_repair_allowed=false`, while the replayed ownership proposed for
human review is `product_behavior`.

The same preflight proves that current `edit_binding_002` targets
`AddParallelMarkerPair`, uses the older source SHA256, and cannot authorize
`TrySpawnStaggerYellowX`. The exact proposed edit scope is current source
SHA256
`65489604EEC41D073FF5BDA77940481AE63BE1917EDE199C99ED04C7B180BB3B`,
`Patches/HitFeedbackBehaviorPatch.cs` lines 979-984, operation
`replace_hud_recttransform_acquisition_and_null_guard_only`. The no-write
result is `AWAITING_EXACT_EDIT_AUTHORITY_APPROVAL` with approval hash
`sha256:488fe9a854c359ac7dd86f54a48692441c7a4e68d2b60d7e4cc89d73a8ef7c6f`.
That preflight performed no Artifact write, Registry mutation, RepairPlanner
invocation, source modification, Build, process launch, or game action.

The user then supplied that exact approval hash. The approval entry reran the
same no-write preflight and current-source identity checks before writing four
bounded Artifact revisions to the existing shared ArtifactStore:
EditAuthorityApproval
`7dca4d3141fb193a77a1da18cbd63f7029ad0ad1bd07d068dd593dcec962203f`,
EvidencePack
`10f60361ca90f9280b7820bf9e663dda736f8efe77c1002816995b62b2e128a6`,
ImplementationPlan
`d18dfd13858b4820781198c05155a2b659d171e7a257facd79d95f53fae4f619`,
and BindingResolution
`af9ad798e8842b5682c9a188cc605739c895a77d8e97605eba3422a324c61159`.
The approved list contains only `edit_binding_004`. Deterministic resolution
produced one `resolved_repair_target` for
`BetterHitFeedback.Patches.HitFeedbackBehaviorPatch.TrySpawnStaggerYellowX`,
`Patches/HitFeedbackBehaviorPatch.cs` lines 979-984, with the same source
SHA256 above and `root_cause_status=unresolved`. Exact-revision freshness now
validates the immutable historical subgraph without requiring its nodes to
remain latest; ordinary latest-bound edges retain recursive stale detection.
All four new revisions are fresh. RepairPlanner and source Patch authority
remain false, and no RuntimeEvidence, old PatchProposal, Mod source, Build,
process, or game-directory state changed.

A later contract review found that this historical approval entry combined
the human decision with technical diagnosis/Plan projection and exposed a
direct CLI path that could write all four revisions. Those revisions remain
immutable history, but their `repair_planner_allowed=false` and
`source_patch_allowed=false` boundaries remain closed. The forward path now
separates one technical `edit_authority_request` from the
`edit_authority_approval` that grants authority. The request exact-binds the
FeatureSpec, RuntimeEvidence, ImplementationPlan, PatchProposal, current source
scope, and projected identifiers while explicitly granting no authority. The
approval contains only the exact request/ResumeReport revisions, request hash,
human decision identity, allowed projection actions, and forbidden later
actions. It can be produced only after the existing LangGraph
interrupt/resume validator accepts the exact request hash. The public CLI can
create the request but has no direct approval command. Missing or partial
projection after approval remains blocked and cannot enter RepairPlanner.
This is a bounded repair of the current Stagger continuation, not a general
approval framework or cross-Artifact transaction system. No new request or
approval was written to the real shared ArtifactStore in this code change.
ArtifactStore rejects every new legacy-shaped EditAuthorityApproval write, so
the historical payload remains readable but cannot be used as a forward
producer contract. Current-revision admission compares both immutable revision
path and complete Artifact hash. Focused verification passed 214 tests,
including wrong request hash, stale or same-byte noncurrent revisions, direct
legacy Approval writes, and approved-but-not-materialized blocking.

The first real operational-entry check then found that the Graph gate had no
supported local caller outside tests. The bounded
`resume-stagger-edit-authority-review` entry now carries one already reviewed
exact Request hash through the existing in-process LangGraph interrupt/resume;
the CLI does not write Approval directly, and the graph still stops at
BindingResolution. ArtifactStore now also exposes exact-revision freshness,
which validates immutable subgraph integrity without treating later
latest-pointer movement as byte or lineage corruption.

The existing-binding reauthorization path now represents that historical
lineage without rewriting it. Its no-write preflight binds predecessor
ImplementationPlan
`6996ea555b43dec436ad253b46519b3e25465b9585cc7e0de7c74911ac655555`,
the directly bound PatchProposal
`37368a6353e59bd76627b72b0ac76433f459090a41058492ad038cf2616dfa93`,
current ImplementationPlan
`d18dfd13858b4820781198c05155a2b659d171e7a257facd79d95f53fae4f619`,
and existing BindingResolution
`af9ad798e8842b5682c9a188cc605739c895a77d8e97605eba3422a324c61159`
as separate exact roles. It preserves `edit_binding_004`, creates no new
binding, adds no technical meaning, and leaves RepairPlanner and source writes
forbidden. The real shared-Store preflight returned
`READY_TO_CREATE_EXISTING_BINDING_REAUTHORIZATION_REQUEST` with proposal hash
`sha256:ffa3fc0379365fc865e22287191e25929d9c6904b154332c8a637c176f659c56`.
It wrote nothing, and EditAuthorityRequest revision count remains zero.

ArtifactStore now requires the resulting BindingResolution to exact-bind the
FeatureSpec, RuntimeEvidence, both ImplementationPlan roles, PatchProposal,
previous BindingResolution, Request, Approval, and EvidencePack. Approval can
still be produced only through the LangGraph interrupt/resume gate. The next
side effect is creation of one no-authority Request in the shared Store and
requires separate permission.

The real no-authority Request now exists with Request hash
`sha256:06ed20c9c2ef7ef6c73b9208519eb52a1e92e52e798aa2dec0deaf16e545b2c3`
and Artifact hash
`3e151d449ae7d4ebac380535e2b37ef3227bd88f642ebca962a497af3f0096d4`.
Its first approved execution exposed a checkpoint integration defect before
any new checkpoint, ResumeReport, Approval, or BindingResolution write:
the Graph flattened the Request's historical exact-role upstreams into
ordinary latest-bound checkpoint state. The Store correctly rejected stale
RuntimeEvidence, predecessor Plan, and PatchProposal refs.

The bounded repair keeps only the exact current Request as the checkpoint's
direct Artifact ref for this one Request schema. The Request remains latest
and recursively validates its immutable exact subgraph, so no historical role
or validation is removed. The original Edit Authority Request schema retains
its prior upstream projection. A public no-write review preflight now enters
the real Graph interrupt and requires the projected checkpoint refs to contain
only that Request. Against the real Store and same Request hash it returned
`READY_FOR_EDIT_AUTHORITY_REVIEW_EXECUTION`; workflow checkpoint,
ResumeReport, Approval, and BindingResolution revision counts remained one
each. It did not resume, write, or reuse the failed execution authorization.

The user then explicitly authorized Graph review of that same Request hash.
The resumed Graph wrote WorkflowCheckpoint
`a96e06501d227c9f2eeb1a99dd49009d13bee1891ede2a6c456a81c4ee6c0713`,
ResumeReport
`fcc62352f7370931d107d05420da416c84e51f9f592f4a0c793c57edb86104d8`,
permission-only Approval
`d648fff15f0074202e19dda7dd48a45afdb4a4133733de5f75f3278cf7227336`,
and BindingResolution
`0786c8cf0618fc209662ec2d9c79cad5fa6a57c2401647035727548a03c03200`.
The resolution still selects only `edit_binding_004`, keeps root cause
unresolved, and leaves RepairPlanner and source writes forbidden.

Read-only correlation of the immutable retry #2 Runtime log further narrows,
but does not resolve, the product root cause. The persistent log SHA256
`D23A154A1614DFF5AF1FCBA29A2C58BE4A4931F578E71D1A7460B48900155C24`
equals the RuntimeEvidence-bound full-run log identity. Later
`missing_canvas_rect_for_stagger_x` events occur after successful
`ShowHitIndicator` hook entries, so the failure is not explained solely by
every stagger event preceding every HUD observation. The log still cannot
distinguish a null `_lastHudParent`, a non-`RectTransform` runtime value, or a
stale Unity object. Product repair therefore remains prohibited until a
separately approved diagnostic source revision and controlled Runtime attempt
produce that missing fact.

The next bounded capability prepares that missing observation without using the
product-repair binding as diagnostic authority. A public no-write preflight
exact-binds the latest FeatureSpec, RuntimeEvidence, current Plan,
PatchProposal, BindingResolution, permission-only Approval, EvidencePack, and
source SHA256. It projects exactly two new observation-only scopes:
`edit_binding_005/chg_005` at `ShowHitIndicator_Prefix` line 301 and
`edit_binding_006/chg_006` at `TrySpawnStaggerYellowX` lines 979-984. A
separate Request and LangGraph approval may materialize only a source-scope
EvidencePack revision and diagnostic Plan revision. They cannot create a
BindingResolution, enter RepairPlanner, modify source, Build, launch GTFO, or
write the game directory. The real shared-Store preflight returned
`READY_TO_CREATE_STAGGER_HUD_PARENT_OBSERVATION_AUTHORITY_REQUEST` with
proposal hash
`sha256:11e10bb6c6ae31ddf6228c83c1b1d996f54f044e51ad1fccd5dc01033dd33ddc`.
The authorized Request
`sha256:8f420195e606bdf47f797c52a921170afaf0ea930b36610ff2fba6e43939ca81`
then entered the real LangGraph approval gate. Approval materialized
WorkflowCheckpoint `cdf39288...f6bc4`, ResumeReport `1d4d1309...8ddfe0`,
permission-only Approval `8f05ce14...c318bf`, EvidencePack
`2e4336d8...055dbf`, and diagnostic ImplementationPlan
`e45cda19...86a3c`. Readback later proved that this is a cumulative Plan: its
Registry and `proposed_changes` contain historical identities `001-006`, while
`diagnostic_scope` selects only `edit_binding_005/chg_005` and
`edit_binding_006/chg_006`. The earlier statement that the whole Plan contained
only those two changes was incorrect. No BindingResolution was created, and
`repair_planner_allowed=false` plus `source_patch_allowed=false` remain in
force.

The v2 diagnostic execution-authority closure now projects a new Plan rather
than appending to that cumulative predecessor. Its only executable identities
are `edit_binding_007-010` and `chg_007-010`; predecessor identities `001-006`
are explicit exclusions and the ordinary PatchProposal builder is
regression-tested to see only the four selected changes. The four scopes bind
selection, stagger-use, bounded diagnostic state, and identity helpers.
`General.EnableDiagnosticLogging` is the sole gate, each phase is capped at
eight records, duplicate suppression is required, and per-frame logging, HUD
tree traversal, and extra `TryGetLayerHudParent` calls are forbidden. Exact
Build dependencies bind `CrosshairGuiLayer.Pointer` plus
`RuntimeHelpers.GetHashCode` for the IL2CPP wrapper and `GetInstanceID` for
Unity objects. The diagnostic test contract ends at classified
RuntimeEvidence and cannot count as product acceptance or enter RepairPlanner.
The Graph and Store accept the v2 Request/Approval shape while preserving the
v1 history, and both successful diagnostic Plan statuses now return CLI exit
code zero.

Real shared-Store no-write preflight passed against current Plan
`e45cda19...86a3c`, Approval `8f05ce14...c318bf`, EvidencePack
`2e4336d8...055dbf`, source SHA256 `65489604...BB3B`, and the exact three
Build dependency hashes. It returned proposal hash
`sha256:ae129a2ed4312929f3c795ede58a9010b3231b4d1733696e4a188eed4a7f0f6b`.
Artifact counts remained Request/Approval/EvidencePack/Plan/
BindingResolution/checkpoint/report `2/3/3/3/2/3/3`. No new Request was
created, and no source, Build, process, or game-directory action occurred.

The exact v2 Request was subsequently created with Request hash
`sha256:c8bd821278a7507946982df121a85ab5b1883fc140634924fb12124fb73e1996`
and approved through the existing LangGraph interrupt/resume gate. The gate
wrote Approval `71623b5f...32f30`, diagnostic EvidencePack
`deeb1acd...166e8`, and diagnostic-only ImplementationPlan
`d1613594...64d68`, plus its checkpoint and ResumeReport. Counts are now
`3/4/4/4/2/4/4`. The Plan contains only
`edit_binding_007-010/chg_007-010`; no BindingResolution, RepairPlan, source,
Build, process, or game-directory action was produced.

The Stagger-specific deterministic exact-diff preflight consumes only that
current Approval, EvidencePack, Plan, source root, and their bound dependency
identities. It rejects stale or expanded scope and uses the exact binding span
to select the duplicated line-301 assignment without widening the binding.
The existing global-unique exact-text behavior remains unchanged for ordinary
changes. Human semantic review rejected the first no-write diff
`sha256:63e6b0e0...d8d8c86` because it could correlate use to a selection log
that was never emitted, output inferred values under object field names,
combine native-object and managed-wrapper changes, and hide record-limit
saturation. No source-write approval existed for those bytes.

The corrected preflight now fails closed on five evidence-truth properties:
selection correlation is emitted or explicitly marked `deduplicated` /
`record_limit_suppressed`; object fields are captured snapshots; valid Root
fallback is distinct from identity observation failure; crosshair instance
change uses native identity only; and the eighth record exposes
`record_limit_reached=true`. The real corrected no-write result contains one
file, four change units, 654 insertions, zero deletions, four passing span
checks, a passing lexical C# delimiter check, and five passing evidence-truth
checks. Its exact diff hash is
`sha256:784a6f8663f1223ed67ea1ca3a6a42e6fd626b122ddd6c8bb84b3645c1731dd1`;
the unified-diff SHA256 is
`73d6ddf478260a0e65b7f0d82ce8ac2c9219c053b7b934a619852dac26d07eb7`.
This remains an observation-only diff: it deliberately does not repair the
yellow X or feedback sound and is not source-write authority, compilation
proof, root-cause confirmation, or product acceptance.

The user subsequently approved that exact diagnostic source write plus one
isolated Apply, Build, and controlled Runtime diagnosis. The existing
exact-text applier changed only a fresh run-local materialization from source
SHA256 `65489604...BB3B` to `C39DF9D...26424`. A real
`dotnet build --no-restore` completed with exit code zero, zero errors, two
nullable warnings, and diagnostic DLL SHA256 `61DD2A82...9FAB4`, size
`102912`. GTFO process `48568` then loaded BepInEx, Chainloader, and the
diagnostic plugin under the reviewed profile. No operator gameplay action
occurred during the 600-second observation window, so
`signal=STAGGER_HUD_PARENT_DIAGNOSTIC phase=stagger_use` was not observed.
Run-local result SHA256 `1EBA129C...3C413` is therefore
`inconclusive`, owned by `observation`, and grants no source repair authority.
The process terminated, the temporary game DLL was removed, the game config
returned to SHA256 `717C5F4B...DB82E`, and the original source retained
SHA256 `65489604...BB3B`. This run-local result is not an ArtifactStore
RuntimeEvidence revision. Root cause and product repair remain blocked until
one operator-guided valid hit/reaction produces the bound diagnostic records.

This proves one local request-to-real-runtime gameplay slice, one bounded
automatically collected accepted startup-marker slice, and one bounded
single-missing-marker negative slice in one GTFO environment. It does not prove
cross-project or cross-environment generality, production deployment,
long-duration stability, every gameplay route, automatic Runtime retry or
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
