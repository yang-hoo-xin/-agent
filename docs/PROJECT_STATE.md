# Project State

Status: active control summary
Last updated: 2026-07-23

Authority and reading order are defined only by `AGENTS.md` section 2.

## 1. Current Selection

```text
current_queue: PHASE2B-BETTERHITFEEDBACK-ENABLED-001
current_documentation_task: None
selected_product_request: Make BetterHitFeedback General.Enabled control startup patch registration
phase_2b_execution_status: blocked_on_bound_ollama_context_admission_after_34000b2b
most_recent_completed_capability: V2-RUNTIME-BOUNDARY-001
v2_c_evaluation_state: core_complete (single real-run evidence)
```

`V2-LOCAL-PROVIDER-ADMISSION-001` is complete. The existing complete
`run-request` entry now accepts the same four local Ollama arguments as the
evidence-only entry, requires an exact model selected from the current
literal-loopback `/api/tags` response, rereads and compares the model digest
before patch generation, creates `OllamaLLM` through run-level settings
injection, and records `/api/chat`, local execution, no external disclosure,
no API-key access, and no provider fallback. The external API-key and per-run
source-disclosure gates remain fail-closed. The specified 76 focused tests and
17 applier no-write/exact-hash tests passed; `git diff --check` passed, and no
P0/P1 diff issue was found. Ruff was unavailable in the environment. This
platform completion does not complete Phase 2B, product behavior runtime
verification, or V2. The queue has returned directly to
`PHASE2B-BETTERHITFEEDBACK-ENABLED-001`.

`PHASE2B-BETTERHITFEEDBACK-ENABLED-001` is the selected meaningful product
slice. Current source binds `ConfigEnabled` to `General.Enabled` with default
`true`, but `Plugin.Load()` never reads its value and always calls
`Harmony.PatchAll()`. The approved change is limited to the isolated copy of
`Plugin.cs`: `false` must emit one structured disabled marker and return before
patch registration; `true` must preserve current behavior. GUID, name, version,
visual/audio behavior, and runtime hot-toggle support are out of scope.

Fresh local run `abcf2669` re-bound repository HEAD
`0fd187246a437d43ceb539903275b9c8e77dad4b`, BetterHitFeedback tree
`6e8c3d5f704b7ede8a7fe9e13946a104e81d0676`, complete snapshot SHA256
`c6fa81b35ca6005dc9091beca601d82afcf180b593b9926b77f642fe37f4f30f`,
and `Plugin.cs` raw SHA256
`b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c`.
Its baseline build and compiled identity verification passed. Admission bound
the current literal-loopback `/api/tags` entry `qwen3:4b-instruct` with digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`,
recorded destination `http://127.0.0.1:11434/api/chat`, and recorded no API-key
access, external disclosure, provider fallback, or automatic retry. The one
authorized patch-generation call failed strict JSON parsing at line 1 column
2172 with `PatchGenerationError`. No Proposal, Review, Dry-run, Apply, final
build, or runtime action occurred. Canonical and isolated `Plugin.cs` still
have the bound raw SHA256. The one-call local run budget is exhausted, so this
run is blocked before Proposal and cannot be retried without a new explicit
run/model authorization. Because that immutable failed run did not preserve the
complete `message.content`, its Patch failure attribution remains unknown; the
observed fact remains the strict JSON parsing failure at line 1 column 2172.

The bounded local Patch Generation admission repair is implemented and verified
without changing LangGraph routing, Runtime, RunState, RAG, patch apply, exact
diff approval, build, runtime, or external-provider behavior. The existing
Ollama request timeout was confirmed as an explicit `120.0` seconds and was
reused unchanged. The local structured path now persists the exact frozen
provider request before invocation and sends those same bytes, separates
provider-envelope admission from Patch payload parsing, and performs the
post-response model/digest drift check after Response Admission and before
Patch materialization. Failed `message.content` is measured and hashed over its
complete UTF-8 bytes; content up to the product-policy limit of 262,144 bytes is
preserved exactly in the isolated run workspace, while content above the limit
is not preserved or truncated. The focused suite passed 94 tests and scoped
`git diff --check` passed. No model call or new Phase 2B run was created during
the repair; `abcf2669` remains immutable and failed before Proposal.

Run `054fe2df` then re-bound the same canonical source and current local Ollama
identity but failed the unmodified baseline build before graph invocation or any
model call because the restricted process could not read
`C:\Users\10160\AppData\Roaming\NuGet\NuGet.Config`. Its baseline exit code is
1, no DLL was produced, and the run remains immutable. The single authorized
permission canary redirected all outputs to a temporary directory and proved
that the equivalent baseline succeeds when that user-level file is readable.

The resulting limited NuGet-isolated build repair does not claim a fully
hermetic build. The existing local delivery entry now binds one shared
`v2_codegen_real_local_dotnet_nuget_isolated` profile for baseline and final
build: explicit `dotnet restore --configfile <run-local config> --packages
<run-local packages>`, run-local `NUGET_PACKAGES`, `NUGET_HTTP_CACHE_PATH`,
`NUGET_SCRATCH`, and `NUGET_PLUGINS_CACHE_PATH`, followed by `dotnet build
--no-restore`. Existing BepInExDir, 120-second timeout, DLL identity inspection,
and fail-closed behavior remain. The focused suite passed 67 tests. Real
canary `nuget_isolated_build_canary_001` passed restore and build without user
NuGet-directory access, produced DLL SHA256
`bb80ec3fe54fdb6ea416b5f313d87d0f4df07a73718e7cb5291357d78beeeb10`,
and passed GUID/name/version plus `Plugin.Load` inspection. The canary created
no Phase 2B run and called no model.

Fresh local run `608f67d9` subsequently passed that baseline profile and made
one bound `qwen3:4b-instruct` Patch Generation call. It produced current-run
Feature Spec, EvidencePack, Implementation Plan, Proposal, and Proposal Review;
the Review allowed no-write Dry-run, which then failed because the Proposal
`before_text` used LF while the bound source used CRLF. No write occurred. A
read-only replay additionally proved that the same Proposal omitted the
configuration guard and disabled behavior it claimed to implement. The run
remains immutable and failed; canonical and isolated `Plugin.cs` bytes remain
unchanged.

The resulting bounded Proposal validation repair does not hard-code
BetterHitFeedback behavior. Patch Generation now receives the Implementation
Plan's validation requirements by bound edit id and rejects a model response
that omits any of them before Proposal materialization. ProposalReviewer
independently applies the same upstream-coverage rule by bound edit id, so a
non-model Proposal path cannot bypass it by rewriting a change id. A no-model
replay of `608f67d9` after only correcting EOL now fails with
`upstream_validation_omitted` for all five omitted plan requirements. The
direct and affected suites passed 138 tests, the CLI suite passed 22 tests, and
Python syntax checks passed. This proves upstream validation preservation, not
C# branch semantics, runtime behavior, or Phase 2B completion. No model was
called and no new run was created by this repair.

Fresh split-worktree run `c213e978` subsequently passed the unmodified
NuGet-isolated baseline build but failed before graph invocation and before any
model call because its compiled-artifact verifier referenced an ignored,
prebuilt `r8_il_inspector.dll` that was absent from the clean worktree. The old
entry also failed before writing `run_manifest.json` or `run_failure.json`.
That run remains immutable; its failure does not permanently block Phase 2B.

The bounded follow-up now writes the admitted run manifest before workspace,
build, or verifier work; a pre-graph failure writes `run_failure.json` and binds
its SHA256 from the same manifest. The verifier is built inside the run
workspace from the tracked `scripts/r8_il_inspector` source with explicit
run-local NuGet configuration and caches, and records source-project,
source-snapshot, and compiled-inspector SHA256 values. The same bound inspector
is used for baseline and final compiled-artifact verification. The direct and
affected suite passed 139 tests. No-model canary
`run_local_inspector_build_canary_001` passed inspector restore/build,
BetterHitFeedback baseline restore/build, and GUID/name/version plus
`Plugin.Load` inspection. Its inspector SHA256 is
`c6edbc003b3645560f40aaa89efef1037241155b8d740b3c5d43b6b252d76301` and
baseline DLL SHA256 is
`387806362f0347d2cf75e0c9d6d50f42f00c7e8c2a475eb85388c568b5516757`.
The canonical snapshot remained unchanged; no Phase 2B run, graph, or model
call was created. This removes the observed clean-worktree verifier and
pre-graph terminal-record gaps only; it does not claim a fully hermetic build,
product runtime behavior, Phase 2B completion, or V2 completion.

Fresh run `58df438b` consumed the one authorized replacement run. Its tracked
inspector build, BetterHitFeedback baseline restore/build, and compiled identity
inspection passed, but cleanup of isolated build outputs failed before graph
invocation because one `obj` entry disappeared during `shutil.rmtree`. No model
or provider invocation occurred, no ArtifactStore business artifact or source
change was produced, and canonical/isolated `Plugin.cs` remained at raw SHA256
`b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c`.
The same run was terminally sealed as
`pre_graph_generated_directory_cleanup`; it remains immutable.

The bounded cleanup repair now ignores only `FileNotFoundError` reported while
removing generated `bin`/`obj` entries, propagates all other I/O errors, checks
that each selected directory is absent after cleanup, and routes cleanup
exceptions through the existing pre-graph terminal handler. The affected suite
passed 142 tests. No-model canary `pre_graph_cleanup_canary_001` used real
`shutil.rmtree`, removed one entry immediately before its unlink error, then
completed cleanup; a simulated `PermissionError` remained fail-closed. No new
run, model call, graph invocation, product source change, or architecture
change occurred. A replacement Phase 2B run requires new explicit
authorization.

Fresh run `f8e6c814` consumed the next explicit run authorization. Its tracked
inspector build, baseline restore/build, and compiled identity inspection
passed, then cleanup failed automatically and terminally before graph/model
with `OSError` and Windows `winerror=145` because `obj\Debug` remained nonempty.
Subsequent read-only inspection observed the generated editor-config entry
disappear during enumeration, establishing continued directory mutation but
not the responsible process. No provider invocation, business Artifact, or
source change occurred; canonical and isolated snapshots remained equal. The
run remains immutable.

The bounded convergence repair now retries generated-directory cleanup
immediately and exactly once only for `winerror=145`. It still ignores
entry-level `FileNotFoundError`, never retries permission or other I/O errors,
and fails closed if the second cleanup attempt does not converge. Cleanup
results expose actual attempt and directory-not-empty retry counts. The
affected suite passed 144 tests. No-model canary
`pre_graph_cleanup_winerror145_canary_001` used real `shutil.rmtree`, converged
after one injected `winerror=145`, and separately proved that two consecutive
145 errors fail closed after exactly two attempts. No new run, model call,
graph invocation, product source change, or architecture change occurred.

That automation limit is not a new permanent platform prerequisite. For this
bounded product slice, semantic closure remains assigned to the existing
controlled chain: current-run Proposal and complete no-write diff, independent
exact-diff approval, compiled `Plugin.Load` inspection, and the separately
authorized false/true runtime acceptance. Run `f8e6c814` consumed the most
recently authorized fresh local run. No automatic replacement run is
authorized; any later run must receive new explicit authorization and retain
the immutable-failure/no-write exact-diff stop boundary.

Fresh run `ae6f408b` then passed the NuGet-isolated baseline restore/build and
compiled identity inspection, but the same `obj\Debug` editor-config entry
survived both immediate cleanup attempts. The run terminally failed at
`pre_graph_generated_directory_cleanup` with `model_call_count=0`,
`graph_invoked=false`, and `actual_write_performed=false`; its manifest binds
the immutable `run_failure.json` hash. A no-model canary proved that adding
`--disable-build-servers` to restore/build does not remove this filesystem
race, so that command change was not retained.

The replacement bounded repair removes the race from the delivery path rather
than extending retry timing. The admitted canonical snapshot is copied once to
the business workspace at `generated_mods/<Mod>` and separately to
`baseline_source/<Mod>`. Baseline restore/build and DLL inspection use only the
baseline copy; the existing LangGraph, Evidence, Proposal, dry-run, apply, and
final-build path continues to use the untouched business workspace. Both use
the existing `v2_codegen_real_local_dotnet_nuget_isolated` profile definition,
run-local NuGet caches, BepInEx copy, commands, and 120-second timeout. Sixty-two
focused local-entry/CLI tests passed. No-model canary
`pre_graph_baseline_copy_canary_001` passed restore, build, GUID/name/version
and `Plugin.Load` inspection, kept business `bin`/`obj` absent, and reproduced
the canonical snapshot SHA256 exactly. No Phase 2B run, graph, model call,
product-source write, or final build occurred during the repair. Another real
Phase 2B run requires new explicit authorization.

Fresh run `b237e35e` then passed the run-local inspector and NuGet-isolated
baseline, made one bound local Ollama Patch Generation call, and reached the
no-write exact-diff boundary. The generated replacement contained `return
false;` inside the bound `public override void Load()` method. That C# code is
invalid because `Load` returns `void`; the user rejected the displayed diff,
so no apply, final build, runtime action, or source write occurred. The old
terminal projection nevertheless recorded the rejection as
`ISOLATED_APPLY_FAILED`, left `run_manifest.json` at `baseline_verified` with
`graph_invoked=false` and `model_call_count=0`, labelled the baseline DLL as a
passed final verification, and emitted a generic Phase A blocked message that
contradicted the completed Evidence, Plan, Proposal, Review, and Dry-run work.
The run remains immutable; these defects are recorded as defects in its
projection, not retroactively rewritten facts.

Two separate bounded repairs now close the observed gaps without a model call
or a new run. First, live C# Evidence carries the enclosing method declaration,
declaring type, method name, parameter types, and return type into the edit
binding and Patch Generation context. Deterministic Patch admission rejects a
value-returning statement in a bound C# `void` method before Proposal
materialization; a no-model replay of the preserved `b237e35e` model payload is
rejected as `csharp_return_value_in_void_method`. The implementation is a
language/edit-binding rule and contains no BetterHitFeedback behavior keyword
check. The direct and affected suite passed 134 tests.

Second, the exact-diff input now has an explicit `REJECTED_BY_USER` decision
that produces `EXACT_DIFF_REJECTED`, `status=blocked`, and
`actual_write_performed=false`; other nonmatching input remains a hash-mismatch
apply failure. `blocked_report` now records the live blockers and upstream
Artifact refs instead of the generic Phase A claim. Final DLL and source-change
verification run only after a real successful final build and use the final
artifact in the business workspace, never the baseline DLL. Returned graph
results update the same run manifest with terminal stage, result hash,
`graph_invoked`, model-call count, Patch-parser entry, and actual-write facts.
The focused terminal suite passed 121 tests. These repairs do not approve a
replacement run and do not prove product runtime behavior, Phase 2B completion,
or V2 completion.

Fresh run `6ea884bf` then passed the run-local inspector, NuGet-isolated
baseline, one bound local Ollama Patch Generation call, Proposal Review, and
no-write Dry-run. The displayed diff used `if (!ConfigEnabled)` even though the
same current source declares `ConfigEnabled` as `ConfigEntry<bool>`; read-only
inspection of the bound BepInEx assembly confirmed `ConfigEntry<T>.get_Value`
and no implicit Boolean or unary-not operator. The user explicitly rejected the
diff. The immutable run is truthfully terminal as `EXACT_DIFF_REJECTED` with
`model_call_count=1` and `actual_write_performed=false`; canonical and isolated
`Plugin.cs` remain at raw SHA256
`b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c`.

The resulting bounded semantic-admission repair extracts exact class-level C#
field/property declared types from the same live source and declaring type,
carries them through Evidence and the Implementation Plan edit binding, and
rejects unary `!` applied directly to a bound non-Boolean member before Proposal
materialization. It contains no BetterHitFeedback, `ConfigEnabled`,
`ConfigEntry`, or `.Value` special case and does not claim full C# compilation
or general member-resolution coverage. A no-model replay of the preserved
`6ea884bf` diff now fails as
`csharp_boolean_operator_operand_type_mismatch`; 157 direct and affected tests
passed. No run file, product source, model call, graph route, or architecture
boundary changed during the repair. A replacement real run still requires new
explicit authorization.

The next bounded API/member Evidence repair is now implemented without a model
call or a new Phase 2B run. `rg_live.py` remains source-only and now binds each
current declaration to its evidence id, source path/hash, full declaring type,
member kind, exact declaration span, and declared type. A neutral run-local
metadata enrichment module joins that fact to the same run's baseline consumer
member, its TypeRef and direct AssemblyRef scope, the uniquely resolved
dependency DLL, SHA256/MVID/AssemblyDefinition identity, and a public,
non-static, readable, non-index property whose direct generic result closes to
`System.Boolean`. The existing tracked inspector gained a separately versioned
read-only report mode; the existing R8 report mode remains unchanged and Phase
2B does not import the R8 evidence module. Implementation Plan bindings add the
current edit binding id and source hash, while Patch Generation accepts
`!receiver.member` only when all source, edit, compiled receiver, TypeRef, and
member identities still match. Direct/affected suites passed 213 tests. The
inspector rebuilt with zero warnings/errors, and a read-only replay against run
`230e70a6` resolved both `ConfigEnabled` and `EnableDiagnosticLogging` to the
raw metadata name ``BepInEx.Configuration.ConfigEntry`1<System.Boolean>`` and its
`Value` property in the uniquely matched `core/BepInEx.Core.dll`; no target code
executed. The full unit suite also completed with 1725 passed, 7 skipped, and 34
pre-existing unrelated failures. This repair does not prove a replacement model
run, generated patch correctness, build/runtime behavior, or Phase 2B
completion; a fresh run still requires explicit authorization.

Fresh run `3360a57e` then re-bound the unchanged canonical source and exact
local Ollama identity, built the tracked inspector, passed the unmodified
baseline restore/build, and passed baseline GUID/name/version plus
`Plugin.Load` inspection. Its first graph Artifact write failed before Evidence
or any model call because the requested revision path was 261 characters and
Windows `os.replace` returned `WinError 3`. The run is terminal at
`graph_invocation`; `model_call_count=0`,
`patch_payload_parser_entered=false`, `actual_write_performed=false`, no
business Artifact was persisted, and no local-model input audit exists.
Canonical, isolated business, and baseline `Plugin.cs` remain at raw SHA256
`b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c`.
Its immutable `run_failure.json` is bound by SHA256
`46fc81e58634026986ab8335e787ee25b7625dab239da09bf2518448034368e`.
The observed failure can be avoided without a platform-code change by selecting
a shorter run workspace root, but that requires a new run id and therefore a
new explicit authorization; no automatic replacement run was created.

Authorized short-path replacement run `34000b2b` removed that filesystem
boundary and persisted current Request Planning, Planning Brief, Feature Spec,
EvidencePack, and Implementation Plan artifacts. Its EvidencePack is sufficient
and binds both `ConfigEnabled.Value` and `EnableDiagnosticLogging.Value` through
the exact source declaration, baseline consumer member, TypeRef/AssemblyRef,
unique `core/BepInEx.Core.dll`, and closed `System.Boolean` result. The
Implementation Plan is non-blocking and carries both verified facts under
`edit_binding_001`. The sole local Ollama call then failed at
`provider_response_admission` with HTTP 400: the exact request contained 6,018
prompt tokens while the active session exposed `n_ctx=4096`. `/api/tags`
reported model `context_length=262144`, but the persisted provider body options
contain only `num_predict=4096` and `temperature=0.0`; no `num_ctx` was sent.
The run is immutable with `model_call_count=1`,
`patch_payload_parser_entered=false`, `actual_write_performed=false`, and
terminal SHA256
`20d42107b75fc923e37c54f93378e5da79a979ce6eab2d8389d34b26df613212`.
Canonical and isolated `Plugin.cs` remain unchanged. No retry, fallback,
Proposal, Dry-run, Apply, final build, or runtime action occurred. Further
Phase 2B execution first requires a bounded, explicitly reviewed Ollama context
admission repair and then a separately authorized fresh run.

The run was approved for one `qwen3.6-plus` call under approval id
`PHASE2B-BETTERHITFEEDBACK-ENABLED-001-QWEN-EXTERNAL-20260720`, the same four
disclosed data classes, no fallback, and no automatic retry. Run `d3718a7e`
bound the correct `Plugin.cs` Evidence and one-file Implementation Plan, and its
baseline build plus compiled identity verification passed. The sole external
call then failed with a 60-second read timeout. No Proposal, Review, Dry-run,
Apply, final build, or runtime action occurred; canonical and isolated
`Plugin.cs` remain at raw SHA256
`b51afbdd3b426628c96431171e9299d767fe422f7b036adfc28596404bfbdf2c`.
At that checkpoint the one-run approval was exhausted and active execution was
cleared. Exact-diff approval remains unused.

On 2026-07-21 the user approved exactly one controlled external Retry1 under
approval id
`PHASE2B-BETTERHITFEEDBACK-ENABLED-001-QWEN-EXTERNAL-RETRY1-20260721`.
Retry1 must use a new run_id, repeat source/baseline binding, keep the exact
`d3718a7e` request and `Plugin.cs` scope, use the same provider/model,
destination, and four disclosed data classes, and perform no fallback or
automatic Retry2. It must stop at no-write Dry-run for separate exact-diff
approval. The previous run and its timeout artifacts remain immutable.

The environment initially rejected Retry1 before process creation because the
approved payload would disclose local source excerpts and run context to the
external DashScope endpoint. No run_id, baseline build, external call, or
Artifact was created, so the Retry1 call budget remained unused. On 2026-07-21
the user explicitly acknowledged that disclosed risk and approved Retry1 again,
but tenant policy rejected the same execution again before process creation
because DashScope is not a trusted internal destination. Retry1 remains unused
and must not execute. The later independent
`V2-LOCAL-PROVIDER-ADMISSION-001` task established a separately authorized
literal-loopback local provider path; this does not bypass or relax the blocked
external disclosure path.

`PHASE2A-DELIVERY-CANARY-001` completed as a source-bound delivery-pipeline
canary in the new run `42c5d93c`. Mechanical review of the raw-byte applier
found no P0/P1 issue and 17 focused tests passed before the run. Fresh Evidence,
Implementation Plan, Proposal, Review, and no-write Dry-run artifacts bound one
`Plugin.cs` replacement from `VERSION = "0.1.0"` to `VERSION = "0.1.1"`.
The user approved exact diff hash
`sha256:43688b71e08227feb8d6517301636af658eed07ffdcb47a9eccbf11c56c5b109`.
Isolated Apply preserved all 62 CRLF line endings and produced raw SHA256
`ba54e3b58efd75b304cb8f678ac0a8f29ea6e0c437b73fd455daaf52823ca82c`.
The real local build succeeded; the final DLL SHA256 is
`d5cb0f0a2b35316cfc90226a06c0bbb6a4ebce79a34f95e21522928642ceb1d9`,
and read-only inspection confirmed GUID `local.betterhitfeedback`, name
`BetterHitFeedback`, and version `0.1.1`. The bound canonical BetterHitFeedback
subtree remained unchanged. Full attempts and artifact refs are archived in
`docs/audits/LOOP_HISTORY.md`.

Completion remains deliberately narrow:
`delivery_canary_complete=true`, `product_slice_complete=false`,
`runtime_behavior_verified=false`, and `phase_2_complete=false`. Phase 2B
meaningful product-slice selection is next, but no request or queue item is
selected.

`V2-RUNTIME-BOUNDARY-001` completed one Phase 1 source-bound no-write lineage
slice through the existing intelligent Evidence entry and local Ollama. Run
`intelligent_evidence_4c811b6933d54a258b8ba0b2c4e14229` bound the registered
`gtfo-r8-modules-asm` identity, persisted eight LangGraph trace events and a
non-routing post-run validation, and ended with all ten lineage checks true.
The EvidencePack contains the exact
`Player.PlayerCharacterController.Move` metadata-to-IL observation. No
implementation, Proposal, apply, build, game-runtime, or target-source-write
artifact was produced. This does not reopen V2-C as a product route; the V2-C
run keeps `source_binding_status=missing`.

Checkpoint `5c78e06` implements durable `evidence_run_attempt` identity and
sanitized provider diagnostics for the evidence-only entry. A `running`
revision is persisted before `graph.invoke`, and its terminal revision keeps
the same `run_id`. Provider-reported and adapter-extracted tool names remain
separate; argument content is represented only by validity fields and SHA256.
The production Qwen Evidence call is non-streaming. Unknown tool validation
executes no evidence tool and performs no automatic provider retry. Focused
verification passed 171 tests; compileall and diff checks passed.

Exactly one separately approved `qwen3.6-plus` run then completed under run id
`intelligent_evidence_448f8515e5634f9faf629494f8febbef`, with no second run or
automatic retry. It used 7 model turns and 6 evidence tools: four metadata
searches and two IL inspections selected through current-run `candidate_ref`
values. EvidencePack provenance preserves both
observation -> `candidate_ref` -> internal method identity -> IL observation
chains and reports
`all_method_inspections_derived_from_observations=true`. The run ended
`completed` with a `needs_more_evidence` finish at `evidence_retrieval`, left
no pending or temporary files, and produced no implementation, Proposal,
build, or runtime artifact. The EvidencePack hash is
`2174bca310480916658811dd46e9cd8858b2a241371310a4365379add2b60a81`.

This is real evidence that the bounded intelligent identity loop is executable;
it is not V2-C completion. The recorded evaluator result was a false positive:
it accepted claims about Hook viability, base-class logic, and movement/surface
behavior that are not established by the cited `nop; ret` and static-field-
getter observations.

Current source repairs that exact defect. Deterministic observation facts and
their exact `canonical_claim` values are model-visible without internal method
identity, while the complete `observation_fact_catalog` is persisted. Only an
`observed` conclusion that exactly matches one fact and cites its observation
enters `verified_findings`; inferred conclusions remain unverified and unknown
conclusions may express grounded abstention. The same post-run evaluator now
covers local and external model providers. Related regression passed 154 tests,
compileall passed, and offline reevaluation of the preserved Qwen pack changed
the gate result to capability=true, convergence=false, semantic=false, rejecting
both unsupported observed conclusions. No model rerun occurred. Semantic
acceptance, evidence sufficiency, implementation readiness, and V2-C completion
remain unresolved; Proposal remains locked and `most_recent_completed_capability`
remains 014.

The later repaired-path run
`intelligent_evidence_36d25ed53f3447e3adeaa71f42fb7ec0` now supplies the
missing real semantic evidence. Its EvidencePack artifact hash is
`bb6dbc8303648d01ff84464e1ed5559ac46d4f697567ef8ec97adb406afb9cea`.
The model autonomously executed six read-only evidence actions, including two
metadata-bound IL inspections. Finish step 7 was rejected with
`OBSERVED_CONCLUSION_CANONICAL_FACT_MISMATCH`; step 8 corrected the two observed
claims to exact deterministic facts and retained two interpretations only as
bounded unverified inference. Provenance is valid, capability=true, and
semantic=true, so V2-C `core_complete` has single-run real evidence. This state
means only that one real run demonstrated the core behavior loop; it does not
identify an independently reconstructable source baseline.
Convergence=false is a separate non-blocking result. Readiness remains
`partial`, `can_generate_patch=false`, evidence sufficiency and implementation
readiness remain false, and Proposal remains locked.

The run artifact does not bind `source_revision`, `git_commit`, or
`modified_files_hash`; therefore `source_binding_status=missing`. Future real
runs require those identities before cross-run code attribution. No further
semantic or general validation work is selected without a concrete false
acceptance, false rejection, missing diagnostic, or gate conflict.

V2-C is frozen as a `V2 intelligence-loop validation spike`. It has no
continuing product route, and `selected_product_request=None`.

`V2 Agent runtime path reconstruction` is a pending read-only task type only.
It is not an approved task, an active queue item, or a permanent product gate.

The ArtifactStore path failure that blocked the next local V2-C execution
before Agent logic is repaired for the current Windows, NTFS, and configured
artifact-root boundary. Revision and pending files now use the shared short
physical layout documented in `DEV_SPEC.md` section 49.2.7 while complete
artifact hashes remain revision identity and upstream provenance. Existing
legacy revision refs remain readable, valid legacy revisions are reused
idempotently, short-locator collisions block deterministically, and the normal
pending -> revision -> latest -> cleanup protocol is unchanged.

The intelligent-evidence entry performs a real atomic-path preflight for
`request_planning_report`, `mod_planning_brief`, `feature_spec`, and
`evidence_pack` before graph, model, or tool execution. A recognized path
replace failure now maps to the existing CLI `BLOCKED` status, exit code 2, and
an `artifact_preflight` diagnostic with zero model/tool calls. The earlier
blocked run's exit code 1 remains historical observation; current repository
evidence does not explain that difference and does not rewrite it.

Focused no-model verification passed 134 tests. The broader `tests/unit`
collection could not start because this environment lacks unrelated `jieba`
and `mcp` dependencies, so the repository-wide unit suite is not claimed green.
The actual new revision and pending paths measured 224 characters at the
previously blocked root, versus the observed 269-character pending target in
the failed layout.

Exactly one post-repair loopback-only run then executed with the same 342-byte
request, source identities, artifact root, `qwen3:4b-instruct`, and unchanged
8-step/6-tool envelope. Run
`intelligent_evidence_5327cb5988774bc5aba6cfcc53f8d2ab` persisted all four
evidence-only runtime artifact types as validated revisions and latest
projections; no pending, temporary, `implementation_plan`, or later artifact
remained. The Agent used 6 model turns, executed 4 metadata searches, rejected
2 repeated actions, selected no IL inspection, and produced no accepted
conclusion. Its legal result was `budget_exhausted`; capability, convergence,
and semantic gates remain false. This is an Artifact persistence result, not a
new V2 intelligence capability, so `most_recent_completed_capability` remains
014 and no retry or repair enters the queue automatically.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-015` completed exactly one authorized local
real-model acceptance run after 014. It is a completed failed acceptance task,
not a new implemented capability, so `most_recent_completed_capability` remains
014. The request was loaded directly from the 013 EvidencePack and retained its
342-byte UTF-8 representation and SHA256
`8eae153e6c0492be4ab3fdd6ba7f8c0a1a04d215e117e12e6824d5920509a9e7`.
Both registered assembly SHA256/MVID identities matched before execution, the
Ollama model id remained `0edcdef34593`, and the run stayed on literal
`127.0.0.1` with no external disclosure.

The prompt-v6 run used 4 model turns and 2 executed metadata searches. It did
not copy the removed value-like query placeholder. Instead it searched both
sources with the same five invented behavioral symbol strings; both searches
returned zero methods. Its next two actions returned to the same current-
interop source/tool/arguments signature and were rejected with
`REPEATED_EXACT_TOOL_ACTION`. Changing only `evidence_need` did not change the
executable signature. Deterministic repeat-correction exhaustion ended the run
as `budget_exhausted` with no method_id, IL inspection, or model conclusion.

All three hidden gates are false. The run did not reach finish validation or
method-origin provenance, so it does not provide real-model evidence for 014's
finish-schema or provenance repair. It does provide real evidence that removal
of the copyable placeholder alone did not make this 4B model revise zero-result
literal symbol queries. The run recorded 1,949 observation bytes, 24,720
discovery-message bytes, 8,285 input tokens, 446 output tokens, zero input
pollution, no executed identical signature, no forbidden later artifact, and
`current_stage=evidence_retrieval`. Proposal remains locked. No rerun or repair
is selected automatically.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-014` completed without a real-model call.
Prompt contract `evidence_discovery_prompt_v6` replaces value-like tool argument
examples with exact argument-name lists, while the existing rule text retains
the actual managed-symbol substring semantics. The shared finish schema states
the decision/open-gap constraints, and the single finish-correction message
carries the same rules with exact field names. Accepted `inspect_method_il`
actions now derive
`provenance_validation.all_method_inspections_derived_from_observations`
directly from current-run method origin and `derived_from_observation_ids`;
failure to finish no longer falsifies that provenance fact. The hidden
capability evaluator therefore preserves a valid prior-observation method
binding even when convergence and overall capability remain false.

Deterministic injected verification passed 31 direct and 199 affected tests.
The ordinary three-turn fixture serialized 14,587 discovery-message bytes and
the seven-turn repeated-method fixture serialized 40,337 bytes, both within
their unchanged thresholds. Tools, 8-step/6-tool budgets, deterministic
validators, graph route, disclosure boundary, and `evidence_retrieval` stop are
unchanged. No Proposal, write, build, copy, game launch, runtime action, or
real-model retry occurred.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-013` completed exactly one local run with no
retry. The request was byte-identical to 011, both registered assembly hashes
matched, and the model remained `qwen3:4b-instruct` digest
`0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`,
4.0B Q4_K_M through literal `127.0.0.1`.

The run improved the observed tool trajectory from 011: 5 model turns and 3
executed tools instead of 7 and 6, no identical executed signature, and an
observation-derived `inspect_method_il` read of
`Beh_GroundMovement.OnStateEnter`. Its first finish cited that IL observation
and truthfully noted the `nop; ret` body did not establish non-walkable-surface
movement, but the object used the wrong top-level fields and was rejected with
`DISCOVERY_FINISH_SHAPE_INVALID`. The one finish correction then returned
`sufficient_for_proposal` while retaining open questions and was rejected with
`SUFFICIENT_DECISION_HAS_OPEN_GAPS`. Deterministic correction exhaustion left
no accepted model conclusion, so run status was `budget_exhausted` and all
three hidden gates failed. Proposal remained locked.

The first metadata call copied the prompt placeholder text `literal managed-
symbol substring` as a literal query. Separately, the accepted IL action passed
the deterministic `method_id` origin validation against `obs-002`, but
`provenance_validation.all_method_inspections_derived_from_observations` was
false because it aliased a transfer flag that also required final convergence.
These were the structural confounders subsequently repaired by 014 above.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-012` completed under the existing
evidence-only boundary. Prompt contract `evidence_discovery_prompt_v5` now
states that `search_dotnet_metadata` performs case-insensitive literal-
substring matching over fully qualified managed type, method, and field
symbols, not behavioral semantic search. An already executed identical
source/tool/arguments action is rejected before tool execution and receives at
most one repeat-specific answer-free corrective turn. A deterministic injected trajectory
recovered from a behavioral query and one rejected repeat through a changed
symbol query, observation-derived `method_id`, `inspect_method_il`, and an IL-
bound conclusion. A second repeat stopped deterministically. Thirty direct and
198 affected tests passed. No real model ran; no budget, tool, Proposal, write,
build, or runtime boundary changed.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-006` completed one separately approved real
Qwen V2-C execution on 2026-07-15. The run preserved the evidence-only stop but
failed intelligence-transfer acceptance. Its exact evidence and bounded repair
direction are archived in `docs/audits/LOOP_HISTORY.md`.
`WALLCRAWLER-INTELLIGENT-EVIDENCE-007` completed the local bounded repair: the
model now receives one shared exact nested finish schema, field-specific
correction feedback, and current metadata-to-IL/conclusion progress. The task
did not call an external model or authorize Proposal, write, build, game, or
runtime action.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-008` completed exactly one approved post-007
`qwen_chat / qwen3.6-plus` evidence-only acceptance run. It ended `completed`
at `evidence_retrieval` after 7 of 8 model steps and all 6 tool calls, with no
forbidden later artifact or target-source write. The model selected one exact
metadata-derived IL inspection and returned a valid `needs_more_evidence`
finish without a correction step. The intelligence-transfer gate remains
unresolved because no grounded conclusion cited the IL observation and
`symbol_discovery_by_platform=false`.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-009` completed that bounded local repair.
Compact context now preserves direct IL method/outcome facts in a deduplicated
inspection catalog, deduplicates metadata method identities, excludes the
latest full observation from both catalogs, records discovery-message bytes per
turn, and corrects a finish that ignores an available IL observation. After an
IL observation, budget state directs the model to finish unless one exact
unresolved gap justifies another tool call. Seventy-five focused tests passed;
no external model call, disclosure, budget increase, or later-stage action
occurred.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-010` received exact user approval for one
external execution, but the Codex tenant execution-policy
reviewer rejected process creation because the payload would contain non-public
material derived from local commercial GTFO assemblies and target a third-party
DashScope endpoint. No process was created, no external request was sent, and
no 010 artifact root or EvidencePack exists. The rejection forbids workaround
or indirect execution, and the user also forbade automatic retry. 010 is
archived as blocked before execution; its three-turn and token acceptance
measurements are unavailable. 011 subsequently tested the real model loop
locally through a literal loopback endpoint. Proposal and all later stages
remain locked.

`WALLCRAWLER-LOCAL-MODEL-EVIDENCE-011` completed one real on-device model run.
Ollama 0.32.0 listened only on `127.0.0.1:11434`; the installed
`qwen3:4b-instruct` identity was `0edcdef34593`, 4.0B Q4_K_M with native tool
support. The local Agent-turn adapter rejects non-literal-loopback origins,
does not inherit HTTP proxy settings, does not follow redirects, and records
the run as `local_agent_turn_adapter` rather than external or injected/test.
The exact natural-language request remained byte-identical to the queue record;
terminal mojibake was display-only.

The run completed and stopped at `evidence_retrieval`, but all three hidden
011 gates failed. It used 7 model turns and all 6 tool calls for metadata
searches, repeated 3 exact source/tool/arguments signatures, selected no
`inspect_method_il` action, produced no EvidenceItem, and grounded no conclusion
in IL. Total model-visible observation bytes were 5,969, the largest single
observation was 1,006 bytes, serialized discovery messages totaled 48,741
bytes, and Ollama reported 15,351 input plus 1,032 output tokens. Those token
counts are local-tokenizer measurements and are not compared numerically with
DashScope. Input pollution remained zero, no external model was called, no
forbidden later artifact or target write occurred, and Proposal remains locked.
The exact 011 query-semantics/repeat repair completed as 012. Intelligence
transfer remains unresolved until a separately selected real-model rerun.

### 1.1 Historical Pre-Closure V2 Intelligence Boundary

The table below preserves the state at the 015 checkpoint. It is superseded for
current selection by the repaired-path core closure and frozen V2-C disposition
in section 1; it is not the current queue or mainline status.

| V2 step | Current state | Evidence boundary |
| --- | --- | --- |
| V2-A controlled intelligent input | implemented and locally tested | Path-hidden registered sources, budgets, disclosure, and evidence-only stop are provided without manual symbols, tool order, Hook, or precomputed IL report |
| V2-B bounded Evidence loop | implemented and locally tested | Model source/tool selection, deterministic validation, observation-derived follow-up, EvidencePack persistence, and LangGraph routing remain inside `retrieve_evidence` |
| V2-C real WallCrawler model acceptance | 015 post-014 same-model local rerun completed; capability, convergence, and semantic gates failed | Literal-loopback/local-data and evidence-only boundaries passed; the removed placeholder was not copied, but two zero-result metadata searches were followed by repeat rejection, no method_id or IL was selected, and intelligence transfer remains unresolved |
| V2-D failure-driven capability growth | 008-triggered repair completed as 009; 011-triggered repair as 012; 013-triggered structural repair as 014 | Direct IL outcome is preserved; exact repeats are bounded; query examples are non-copyable field lists; finish cross-field rules are model-visible; provenance is independent from convergence; no tools or runtime budgets were added |
| Intelligence-transfer completion gate | unresolved | Requires a real-model run with zero manual answers, budget convergence, dependent metadata-to-IL work, an observation-bound conclusion, deterministic acceptance, and the evidence-only stop |

The deterministic WallCrawler work through
`WALLCRAWLER-CURRENT-HOOK-EVIDENCE-003` is supporting evidence and regression
baseline, not intelligent-transfer proof. `WALLCRAWLER-INTELLIGENT-EVIDENCE-004`
implemented V2-A/V2-B and exposed the first V2-C failure. Its acceptance
hardening and `WALLCRAWLER-INTELLIGENT-EVIDENCE-005` repaired the observed
context, observation, provider-boundary, and acceptance defects.

The 006 run reduced total model-visible observation bytes from 205,912 to
20,001, recorded 43,978 provider tokens, preserved all four zero input-pollution
counts, repeated no identical source/tool/arguments action, and produced no
forbidden later artifact. It nevertheless spent all six tool calls on metadata
search, never called `inspect_method_il`, and failed both finish validations:
`DISCOVERY_DECISION_INVALID` followed by `EVIDENCE_CONCLUSION_SHAPE_INVALID`.

Deterministic replay confirmed that its selected `EnemyLocomotion`, `EnemyAI`,
`ParasiteLocomotion`, and `Beh_GroundMovement` symbols were present and that
`WallWalk` / `Climb` were absent from those observations. Claims about a
critical Hook or reusable non-horizontal movement remain unsupported because
no IL was inspected. The bounded local repair completed as 007; any new external
rerun remains a separate task requiring a new per-run disclosure approval.
Proposal remains locked.

The 008 run used 20,417 model-visible observation bytes and 36,532 provider
tokens. Step 2 inspected `Beh_GroundMovement.OnStateEnter` from the current
interop assembly through `method_f23458376ea3474ca5b1c924`; the persisted item
records metadata token `0x06000307`, RVA 63320, a method body, and 42 IL
instructions. Later compact context represented that successful IL step with
`observed_methods: []` because `_compact_step` only preserves rows from the
metadata observation's `methods` collection, while an IL observation stores
its method identity as direct fields. The final model output consequently
claimed that IL was not successfully retrieved. 009 repaired that exact local
representation and validation failure. The seven-turn repeated-method fixture
now records 38,734 discovery-message bytes versus the 38,774-byte pre-repair
baseline, while the normal metadata-to-IL-to-finish fixture completes in three
turns with 13,864 bytes. The latter is a 64.2 percent message-byte reduction
against the seven-turn baseline by avoiding post-IL broad searches; it is not a
claim about unmeasured Qwen billing. Another external call is not authorized.

`WALLCRAWLER-PLAN-001` completed the selected planning-only vertical slice.
`plan-request` is no longer a placeholder: it emits request-planning and
planning-brief payloads without ArtifactStore writes and stops before
`feature_spec`. The exact WallCrawler Chinese request is tested as high-risk,
Hook-required, runtime-required `game_hook_investigation`; pure configuration
and runtime-diagnostics routing remain separately tested. Hook discovery,
external R8 evidence registration, feature specification, proposal, Mod code,
build, and gameplay verification remain outside this completed slice.

`WALLCRAWLER-EVIDENCE-001` completed the next bounded slice. The real
`evidence-request` CLI ran the existing graph through `feature_spec`, reread and
SHA256-verified the approved `C:\Users\10160\Desktop\r8 unity` manifest, bound
exact C# symbols plus the layout `persistentID` / rundown `LevelLayoutData`
linkage into `evidence_pack`, and ended at `evidence_retrieval`. The observed
pack was `partial`, `can_generate_patch=false`, and contained no
`implementation_plan` or later artifact. Hook selection, proposal, Mod code,
build, game launch, and gameplay verification remain outside this slice.

`WALLCRAWLER-HOOK-EVIDENCE-002` completed the approved read-only assembly
inspection. The local .NET metadata reader did not load or execute target code.
For `Modules-ASM.dll` SHA256
`DD0C57D5C527E78B40FAB798456EDD73413DA0F140995A63FCA3619C36C32698`,
MVID `28e7d845-eb8b-48af-a5b2-9b1addb278ae`, the exact results are:

- `ES_PathMove.CommonFixedUpdate`: token `0x06000B8C`, RVA `8282`, IL `002A`
  (`nop; ret`);
- `ES_PathMove.UpdateRotation`: token `0x06000B8E`, RVA `8282`, IL `002A`
  (`nop; ret`);
- `ES_PathMoveBase.UpdateRotation`: token `0x06000B93`, abstract, RVA `0`, no
  method body.

The real evidence-only graph persisted these as three additional EvidenceItems
and still stopped at `evidence_retrieval`. Proposal-only remains locked because
the supplied assembly is a stub for the inspected methods, surface movement
APIs remain unresolved, and current runtime binding is absent.

`WALLCRAWLER-CURRENT-HOOK-EVIDENCE-003` closed the current-install follow-up
without entering Mod implementation. The same evidence-only graph hash-bound
the installed `BepInEx/interop/Modules-ASM.dll`, `EnemyAnimationFix.dll`, and
`StuckEnemyFix.dll`; the local metadata reader recorded exact wrapper, Harmony
attribute, and resolved IL-reference evidence. The real CLI run produced
EvidencePack `fcd5d56bef6463353ac62b1c88fc34f2ffaa1cf95bba003da19d62d401b1695b`
with 33 items, `readiness=partial`, and `can_generate_patch=false`, then stopped
at `evidence_retrieval` with no `implementation_plan` or later artifact. Current
interop proves managed wrapper/native-pointer identity, while the reference
Mods prove ordinary interception, position mutation, and `INavigation`
recovery paths. None proves non-horizontal surface navigation or native
movement semantics, so WallCrawler Proposal-only remains locked.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-004` completed the first intelligence-first
Evidence vertical slice without entering Mod implementation. The Evidence
specialist now runs a bounded model/action/observation loop inside the existing
`retrieve_evidence` node. The model receives the request plus path-hidden
Source Registry projections, selects a registered source and one of two
read-only tools, observes exact metadata results, and may inspect IL only by
referencing a `method_id` created from that current-run observation. Tool and
model-step budgets, observation-byte budgets, exact source/tool checks, and the
graph `stop_after_evidence` boundary remain deterministic.

The local/injected acceptance proves source selection, tool selection, symbol
discovery, observation-derived follow-up selection, and evidence
interpretation with zero manual symbols, zero manual tool sequence, zero
precomputed reports, and zero operator intervention. A real local-tool run
searched the exact supplied R8 `Modules-ASM.dll`, observed SHA256
`DD0C57D5C527E78B40FAB798456EDD73413DA0F140995A63FCA3619C36C32698`
and MVID `28e7d845-eb8b-48af-a5b2-9b1addb278ae`, returned exact tokens, and
reread one observed method body without executing target code. An unrestricted
61-assembly run first exhausted its result budget in third-party Autodesk
symbols; the Source Registry projection now supports exact
`assembly_relative_paths` to bind the intended DLL.

The original `BaseLLM` strict-JSON route was subsequently exercised by one
approved `qwen3.6-plus` run preserved at
`artifacts/intelligent_evidence_real_wallcrawler/features/feature_8eae153e6c04/evidence_pack.json`.
That run ended `budget_exhausted` after 8 model steps, 6 tool calls, and 205,912
observation bytes. It emitted no evidence conclusion. The older transfer logic
nevertheless marked source/tool/symbol/follow-up selection true, which is the
recorded acceptance and context-shape failure that triggered
`WALLCRAWLER-INTELLIGENT-EVIDENCE-005`. Complete Hook discovery,
non-horizontal movement feasibility, and runtime behavior remain unverified;
`can_generate_patch` remains false.

The acceptance-hardening insertion for the same capability is also complete.
Final evidence conclusions now use exact `observed`, `inferred`, or `unknown`
classification with deterministic reference and limitation checks. Durable
EvidencePack audit data includes sanitized actions and hashes, observation
hashes, prompt-contract and initial-context hashes, external/injected model
identity, and actual model/tool/byte budget use; raw prompts are not stored.
Source-selection transfer is true only when at least two sources were actually
available. The ignored machine-local registry now provides two relevant exact
sources: the supplied R8 `Modules-ASM.dll` and current installed interop
`Modules-ASM.dll`. Each source is bound to its observed SHA256/MVID, and both
live identities passed local metadata reads with `target_code_executed=false`.
This hardening did not call an external model or change the Proposal-only stop.

`WALLCRAWLER-INTELLIGENT-EVIDENCE-005` completes the next intelligence-capacity
slice without changing the graph stop boundary. `BaseLLM.chat()` remains the
plain-text compatibility interface. The new adjacent Agent-turn contract
normalizes exact JSON-Schema tool definitions, call ids, parsed arguments,
final structured output, stop reason, provider/model/request identity, and
input/output/reasoning/cache token usage. `QwenChatAgentAdapter` is the real-run
path used by `intelligent-evidence-request`; it sends native tools with
`enable_thinking=false` and `parallel_tool_calls=false`, while deterministic
local validators enforce the exact action and conclusion contracts. The
separately callable `OpenAIResponsesAgentAdapter` maps typed Responses items,
function-call outputs, reasoning continuation items, and strict `text.format`.
Both adapters are locally tested with captured request/response fixtures. No
external Qwen/OpenAI call or source disclosure occurred in this task.

Discovery responsibilities are now separated into `discovery_contract.py`,
`discovery_loop.py`, and `discovery_tools.py`; `discovery.py` is a compatibility
facade. Each model step is rebuilt from the initial goal/source projection, a
compact trajectory, the latest full observation only, and budget state. A
focused regression proves an earlier full metadata observation is absent from
the third turn while its observed method identity remains in the compact
trajectory. Metadata search now requires `result_kinds` and `limit_per_kind`,
defaults to at most 50 results per kind and a 16 KiB model observation, factors
assembly SHA256/MVID into one assembly table, and reports matched, returned,
and truncated counts by kind.

Intelligence-transfer accounting now fails closed unless the run converges
before budget exhaustion, repeats no identical source/tool/argument work,
performs a metadata-to-IL follow-up bound to an observed method, and emits a
grounded conclusion that cites the inspection observation. It records
`semantic_relevance_evaluated=false` because no ground-truth semantic case was
executed. This local acceptance proves interface, state reconstruction, tool
binding, and validation behavior only. Real Qwen WallCrawler semantic quality,
Hook feasibility, and Proposal-only readiness remain unverified and require a
new exact per-run disclosure approval.

## 2. Current Verified Product Boundary

The repository has a tested controlled chain for request planning, evidence
binding, implementation planning, patch proposal, deterministic review,
no-write dry-run, isolated apply, build evidence, and explicit blocked/repair
routes.

The preserved real BetterHitFeedback run proves one local request-to-build
execution with:

- an externally produced, read-only source input;
- current-source inspection with `rg` plus live file reads;
- an evidence-bound generated patch;
- deterministic review, dry-run, isolated apply, and real build;
- unchanged external input and a verified built DLL.

It does not prove GTFO gameplay behavior, general Mod quality, production
runtime automation, production RAG, cross-project generality, or autonomous
delivery.

The bounded `V2-RET-DIRECTIONAL-001` result retains `rg` plus live reads as the
current retrieval direction. The existing SymbolIndexer remains locally
interesting but did not cross the frozen investment threshold. The community
BM25 path had no authentic traceable corpus and was recorded as plumbing only.
No Dense, RRF, rerank, Agentic routing, H1-H5, or promotion work is active.

## 3. ProposalCritic Local/Injected Assessment Boundary

The current implementation provides a read-only ProposalCritic provider inside
`review_proposal`. It may write a separately bound `critic_assessment` artifact
but cannot select paths, authorize writes, bypass ProposalReviewer, or choose a
LangGraph route.

The caller must set `critic_requirement` explicitly:

| State | Exact condition | Route effect |
| --- | --- | --- |
| `not_required` | `critic_requirement="not_required"` and no provider | Run normal ProposalReviewer rules; no `critic_assessment` is written |
| `required_succeeded` | `critic_requirement="required"` and a valid current-hash-bound assessment is returned | Apply the versioned score policy, then all deterministic hard rules |
| `required_failed` | Required provider is absent, raises, returns unresolved, stale, malformed, wrong-policy, or wrong-hash output | Block before dry-run; do not retry implicitly |

Supplying a provider while `critic_requirement="not_required"` is a
configuration error. There is no inferred risk trigger.

Newly emitted `proposal_review` payloads include `critic_gate`. The existing
`proposal_review` 1.0 registry contract does not make that field mandatory, so
previously stored review artifacts remain readable without a migration task.

Policy `proposal_critic_local_injected_v1` applies only to patch proposal
review. It uses `equal_weight_rounded_mean` over four exact dimensions:
`evidence_grounding`, `scope_discipline`, `verification_quality`, and
`reversibility`. Each weight is 25 percent; the rounded mean must be at least
80, the verdict must be `pass`, and there must be no blocking Critic finding.
ProposalReviewer hard rules, permissions, bindings, and human approval always
take priority over the score.

The local rule-based implementation and injected-provider boundary are tested.
No external-model Critic execution or semantic-quality improvement has been
verified.

## 4. Current Claims And Known Gaps

| Area | Current state | Claim boundary |
| --- | --- | --- |
| Controlled LangGraph workflow | tested | One graph owns routing; this is not a general autonomous multi-agent framework |
| Planning-only CLI | tested for the selected WallCrawler request and routing regressions | Emits in-memory planning payloads and a no-write stop boundary; it does not retrieve evidence or prove Hook feasibility |
| Evidence-only CLI | verified against the approved GTFO R8 snapshot | Rereads exact supplied files, validates SHA256/symbol/JSON identity evidence, writes control artifacts, and stops before implementation planning; it does not prove Hook feasibility or current runtime behavior |
| R8 CLI metadata/IL inspection | verified for three exact movement/rotation symbols | Proves two `nop; ret` bodies and one abstract no-body method in the hash-bound supplied assembly; it does not provide usable movement semantics or unlock Proposal-only |
| Intelligent Evidence loop | tested end to end with injected structured turns; real local metadata/IL tools separately verified | Provider-neutral turns, Qwen Chat/OpenAI Responses wire mapping, compact history reconstruction, focused metadata observations, observation-bound IL follow-up, and stricter trajectory acceptance are locally tested; external-model semantic quality and WallCrawler Hook feasibility remain unverified |
| Artifact lineage and Binding Registry | tested on the controlled path | Stored hashes and bindings do not prove runtime behavior |
| Proposal review and dry-run | tested | Dry-run proves no-write validation, not compilation or gameplay |
| Isolated apply and real build | verified on the narrow BetterHitFeedback run | Build success does not prove GTFO runtime behavior |
| ProposalCritic local/injected boundary | tested for not-required, required-success, and required-failure | External model assessment quality remains unverified |
| Runtime/evaluation | interfaces and focused tests exist | Real GTFO gameplay success remains unproven |
| Retrieval direction | bounded local decision completed | Keep `rg` plus live reads; no production RAG claim |

Open implementation gaps remain tracked by Status, Provenance, and Trigger in
`docs/SPEC_COVERAGE_MATRIX.md`. A gap does not enter the active queue until its
recorded trigger is satisfied.

## 5. Verification Snapshot

The ProposalCritic-affected unit command currently passes 111 tests:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_proposal_review.py tests/unit/test_workflow_graph.py tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py tests/unit/test_repair_loop.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_domain_adapter.py -q --tb=short
```

This count applies only to the touched proposal/artifact/workflow behavior. It
is not a claim that the full repository test suite or any real gameplay path is
green.

The planning-only slice and affected downstream gates pass this current focused
command:

```text
python -B -m pytest tests/unit/test_mod_agent_cli.py tests/unit/test_planning.py tests/unit/test_workflow_graph.py tests/unit/test_evidence_retrieval.py tests/unit/test_artifact_contract.py tests/unit/test_domain_adapter.py -q -p no:cacheprovider
116 passed
```

These tests prove local planning/routing and existing downstream gate
regressions only. They do not prove a WallCrawler Hook or GTFO runtime behavior.

The evidence-only graph and CLI boundary pass the current focused command:

```text
python -m pytest tests/unit/test_gtfo_r8_evidence.py tests/unit/test_mod_agent_cli.py tests/unit/test_workflow_graph.py -q
48 passed
```

The real CLI run produced `request_planning_report`, `mod_planning_brief`,
`feature_spec`, and `evidence_pack`; it ended at `evidence_retrieval` with no
downstream artifact. This proves supplied-file reading and control-plane
stopping only, not a usable Hook or gameplay behavior.

The intelligent Evidence loop, CLI boundary, R8 reader, and workflow
regressions pass the current focused command:

```text
python -m pytest tests/unit/test_agent_turn_adapters.py tests/unit/test_intelligent_evidence_discovery.py tests/unit/test_mod_agent_cli.py tests/unit/test_gtfo_r8_evidence.py tests/unit/test_evidence_retrieval.py tests/unit/test_artifact_contract.py tests/unit/test_planning.py tests/unit/test_domain_adapter.py tests/unit/test_workflow_graph.py tests/unit/test_llm_providers_smoke.py -q -p no:cacheprovider
198 passed
```

The .NET metadata reader also built with zero warnings and zero errors. The
real-tool check used local supplied files and did not call an external model,
start GTFO, copy game files, create an implementation plan, or write target
source.

The 198-test command proves local request/response mapping for Qwen Chat and
OpenAI Responses, not a real provider call. It also proves the compact-history
and stricter intelligence-transfer regressions; semantic relevance remains
unevaluated until a separately approved real Qwen case is run.

## 6. Historical Records

Completed queues, frozen validation tracks, review history, previous latest
summaries, and superseded direction statements are retained in
`docs/audits/LOOP_HISTORY.md` and Git history. They are not active work.
