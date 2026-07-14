# Project State

Status: active control summary
Last updated: 2026-07-14

Authority and reading order are defined only by `AGENTS.md` section 2.

## 1. Current Selection

```text
current_queue: None
current_documentation_task: None
selected_product_request: None
most_recent_completed_capability: WALLCRAWLER-INTELLIGENT-EVIDENCE-005
```

The ProposalCritic contract, active-state cleanup, queue cleanup, coverage
separation, and architecture-reference maturity labels are complete. They do
not authorize another evaluator, retrieval, Dashboard, MCP, memory, multi-agent,
or runtime platform expansion.

After this cleanup, the next implementation task must be selected from a
concrete product capability or real Mod request. This file intentionally does
not prescribe that task.

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
180 passed
```

The .NET metadata reader also built with zero warnings and zero errors. The
real-tool check used local supplied files and did not call an external model,
start GTFO, copy game files, create an implementation plan, or write target
source.

The 180-test command proves local request/response mapping for Qwen Chat and
OpenAI Responses, not a real provider call. It also proves the compact-history
and stricter intelligence-transfer regressions; semantic relevance remains
unevaluated until a separately approved real Qwen case is run.

## 6. Historical Records

Completed queues, frozen validation tracks, review history, previous latest
summaries, and superseded direction statements are retained in
`docs/audits/LOOP_HISTORY.md` and Git history. They are not active work.
