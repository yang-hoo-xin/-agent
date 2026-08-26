# Coding Agent v0 Recent Issue Interaction Audit

Status: docs-only logical-chain audit

Recorded: 2026-08-26

## 1. Scope And Counting Rule

This audit is not bounded by a calendar window. It covers the current logical
chain from the RAG-1A explicit-unresolved and relation-lineage closure through
AccurateCrosshair P0/P1, sealed Entry, Recovery actuals 1-6, and the current
requirement-projection blocker.

The unit counted below is a logical workstream, not a commit, chat page, file,
or test command. A workstream may legitimately have no Issue when it is normal
capability construction, a product decision, a successful admission, or
read-only asset governance. An Issue is required when a real failure, repeated
failure signature, safety defect, or stage blocker establishes a physical
owner and a trigger.

```yaml
logical_workstreams_reviewed: 35
direct_issue_or_conditional_catalog_interactions: 17
normal_capability_or_decision_no_issue_required: 10
issue_interaction_gaps_found: 8
cross_cutting_stale_issue_statuses_found: 3
new_registered_issues_from_this_audit:
  - EXEC-001
  - BUILD-001
  - FS-001
  - FS-002
  - EVID-002
stale_existing_entries_updated:
  - ENTRY-002
  - REPORT-001
  - DOC-001
historical_gap_recorded_without_reactivation:
  - Wall relation-aware Requirement Projection correction at 8c5509e
post_checkpoint_update_interactions_reviewed: 11
post_checkpoint_update_new_registered_issues: 0
```

The eight interaction gaps consist of one closed-route historical gap, four
distinct actual1-4 execution failures, and three projection workstreams
(actual5 failure, checkpoint `2b18874`, and actual6 revalidation) consolidated
under the same current physical owner `EVID-002`.

## 2. Complete Recent Logical-Chain Map

| # | Logical workstream | Issue interaction decision |
| --- | --- | --- |
| 1 | RAG-1A explicit-unresolved outcome and Case reliability | Existing `OBS-001` and `CASE-001`; correctly issue-linked |
| 2 | Structured relation scoring | Normal capability construction; no Issue required |
| 3 | Request-side Relation identity | Normal capability construction; no Issue required |
| 4 | Relation-to-Observation lineage | Normal capability construction; no Issue required |
| 5 | Per-call Ollama context admission and fallback boundary | Existing `CTX-001` and `REC-001`; correctly issue-linked |
| 6 | Wall relation-aware Requirement Projection correction `8c5509e` | Historical interaction gap: real correction and diagnostics were implemented without a dedicated Issue; Wall route is now explicit-unresolved and closed, so this audit records the gap without reactivating it or merging it into `EVID-002` |
| 7 | Wall pre-Artifact trace gap | Existing `REPORT-001`; correctly issue-linked |
| 8 | Relation-aware Wall route closure | Existing `OBS-001`, `CASE-001`, and `CTX-001`; correctly issue-linked |
| 9 | AccurateCrosshair task selection and bounded preflight | Successful admission/decision input; no Issue required |
| 10 | Nested product source-revision binding | Normal authority capability; no Issue required |
| 11 | AccurateCrosshair run `8d26e4e5`, owner audit, and P0 fail-closed repair | Existing `EVID-001`; correctly issue-linked |
| 12 | Public Alpha advanced robustness directions | Conditional trigger catalog; not a current Issue or Queue item |
| 13 | P1a deterministic requirement coverage authority | Selected capability construction; no Issue required |
| 14 | P0-P3 delivery-route decision | Architecture/route decision; no Issue required |
| 15 | P1b formal projection/findings providers and consumers | Selected capability construction; no Issue required at checkpoint time |
| 16 | Sealed-entry Attempts A1-A5 | Existing `ENTRY-002`; correctly issue-linked |
| 17 | Superseded packet that could substitute the exact diff hash | Existing `AUTH-001`; correctly issue-linked and closed before execution |
| 18 | Short authoritative-document drift and owner-route correction | Existing `DOC-001`; correctly issue-linked but later became stale again |
| 19 | Repository Entry owner checkpoint `c906d99` | Existing `ENTRY-002`; correctly issue-linked |
| 20 | Recovery/degradation/vector-trigger documentation | Existing `REC-001`, `OPS-001`, and conditional catalogs; not implementation claims |
| 21 | actual1 `a63fdb36` workspace path-budget failure | Missing interaction; registered as `EXEC-001` |
| 22 | actual2 `d9c35191` missing run-local `GameFolder` build binding | Missing interaction; registered as `BUILD-001` |
| 23 | actual3 `65541df6` Windows long-path dependency-copy failure | Missing interaction; registered as `FS-001` |
| 24 | actual4 `f3a54f16` incomplete long-path snapshot identity | Missing interaction; registered as `FS-002` |
| 25 | preflight4 ready followed by actual5 entering ProductExecution | Existing `ENTRY-002` close evidence; status had not been updated |
| 26 | actual5 `f6bdb182` projection disposition failure | Missing interaction; registered under current `EVID-002` |
| 27 | `2b18874` per-index disposition schema repair | Missing interaction; now recorded as an incomplete `EVID-002` mitigation, not completion |
| 28 | preflight5 ready followed by actual6 entering ProductExecution | Additional `ENTRY-002` close evidence |
| 29 | actual6 `905a0a60` repeats projection failure after one correction | Missing interaction; current active `EVID-002` evidence |
| 30 | actual6 top-level coverage blocker masks earlier provider failure and uses a false/null source-change pair | Existing `REPORT-001`; latest evidence was stale and is updated |
| 31 | actual6 isolated baseline restore/build success | Positive bounded product-path evidence; no Issue required and not changed-product success |
| 32 | One-time read-only audit of four protected WIP documents | Asset-governance decision; no Issue required and no WIP content is adopted |
| 33 | Many fresh execution pages and manual Case coordination | Existing `OPS-001` and future `ENTRY-001`; no current UI/platform implementation is activated |
| 34 | Semantic/hybrid/vector direction | Conditional retrieval catalog; triggers remain unsatisfied |
| 35 | Circuit breaker, model gateway, fallback, degradation, and distributed continuity direction | Public Alpha conditional robustness catalog; no current capability claim |

## 3. P2 Product-Recovery Attempt Ledger

| Attempt | First owner/fact | Immutable evidence | Resolution/route |
| --- | --- | --- | --- |
| actual1 / `a63fdb36` | `workspace_preparation`; long packet/run root caused Windows file materialization failures before ProductExecution | `actual_failure.json` SHA256 `257855d76ce8de66b26915ffc8ef46ef539be91ee5de4b6e4ef82f351a322808`; `run_failure.json` SHA256 `54f74947912ebee5573cd47d40481062509faeea59c5fa7288fb060075d6eede` | short-root packet path budget; `EXEC-001` mitigated for current scope |
| actual2 / `d9c35191` | `baseline_restore`; `Dependencies.props` reported `The GameFolder property must be set to the Game folder.` | `actual_failure.json` SHA256 `e001a0bf4e4861449a5ed2a71ed865b384b7b9f455da7a2e7f9af4225e84d98e`; `run_failure.json` SHA256 `8406bce8bf612ff0618ac1c525707b867c18b282286c7f909d2e8d06bacf8084` | `RunLocalGameFolderBindingV1` at `a182db4`; `BUILD-001` mitigated for current scope |
| actual3 / `65541df6` | `build_dependency_copy`; ordinary Windows paths could not read long dependency files | `actual_failure.json` SHA256 `8e62d99017f77378f138e26573658da34827385cb4de3be8b2e2c924ad5762b5`; `run_failure.json` SHA256 `5be3695894c7b31ea6041529c9256a82e5bc02f8c86f1aca5d590bafca471aaa` | extended-length copy checkpoint `1036f98`; `FS-001` mitigated for current scope |
| actual4 / `f3a54f16` | `build_dependency_copy`; source/destination physically held 165 files while ordinary snapshot traversal observed 137 and rejected identity | outer `actual_failure.json` SHA256 `507f09ca751b8c34615746d4d17448550dd436e442dd82b86542dd9b432474ab`; product `run_failure.json` SHA256 `2100c60a7e7f1580c242d2c533a09b11b5eb11312a73215b1514a77691a66b6f` | complete long-path snapshot checkpoint `2ee3e03`; `FS-002` mitigated for current scope |
| actual5 / `f6bdb182` | ProductExecution entered; projection and one correction failed `REQUIREMENT_COVERAGE_INPUT_DISPOSITION_INVALID`; findings did not run | `run_result.json` SHA256 `8f5976dc9fe5c499e3100212f0e52d6661aa580e0129f583ea89fca732022265`; `run_manifest.json` SHA256 `f909da809424ac6d9d66b9ee5938ac796de675903e7a9a12ba7bbb137078c6ac` | `2b18874` narrowed per-index schema but did not close real failure; `EVID-002` active |
| actual6 / `905a0a60` | ProductExecution and one isolated baseline build entered; the same projection failure repeated after two local-model calls; findings/Patch/changed Build did not run | `run_result.json` SHA256 `0c5b766821a3f05b0af54cb3da28ccd6c45e92265196415dcd89cc7352658c92`; `run_manifest.json` SHA256 `2fc0c051bf26755e4bbf3b83c8fbc751829ab65a5e1e8c7434456943351c35f`; EvidencePack SHA256 `9d87c968606fd8cbf7e02d43b2fe46a968096a3a597b51f2902ea481c2841f97` | freeze and repair `EVID-002` before actual7 |

The actual6 initial Ollama body was independently reconstructed from current
source and the bound FeatureSpec. Its size `8868` and SHA256
`951d949e32259fcf76fc3f5d29608f48ebdedfd8271e17e2139f7e78213482c1`
exactly match the run audit. This proves the `2b18874` per-obligation schema
entered the actual provider request. It does not prove that Ollama obeyed the
schema or that the schema expresses every cross-field semantic invariant.

## 4. Current Route

```text
ENTRY-002 current-scope close evidence accepted
-> P2 empirical path remains blocked at projection-to-findings under active EVID-002; P0 is not reopened
-> code/test checkpoint lineage 984716f -> 22f8fa0 accepted_for_bounded_code_and_tests
-> Workflow tests-only checkpoint 1d8aeaff closes four inherited assertions without product-capability or actual claims
-> coverage-authorized ProductExecution deterministic vertical scenario
-> new sealed checkpoint-bound preflight and receipt review only after that scenario
-> separately authorized actual7; actual7 is unauthorized now
-> actual7 independently determines EVID-002 real-run closure and the later product-path result
```

This audit does not authorize code, model, actual, Build, Runtime, vector, or
Public Alpha work. Documentation registration is not capability progress.

## 5. Post-Checkpoint Issue Interaction Update

| Reviewed interaction | Decision | Issue/Queue consequence |
| --- | --- | --- |
| `984716f` -> `22f8fa0` macro checkpoint review | Existing `EVID-002` interaction | `accepted_for_bounded_code_and_tests`; `EVID-002` remains active and actual7 remains unauthorized |
| Workflow tests-only checkpoint `1d8aeaff32a93d5475debca482ba72404b9674cf` | Normal test-contract maintenance | No Issue; four inherited assertions now express current deterministic retrieval, blocking ImplementationPlan, and explicit review-policy contracts; no product capability or actual claim |
| `symbol_exact` plus `text_match` retention and two edit bindings | Existing deterministic retriever contract | Old assertion drift; no Issue |
| Insufficient Evidence commits a blocking ImplementationPlan before terminal block | Existing Workflow routing contract | Old assertion drift; no Issue |
| Legacy fixture registered a physical source root but projected relative `source_path=Plugin.cs` without `target_domain` | Fixture drift, not selected ProductExecution path failure | No Issue; explicit GTFO `DomainReviewPolicy` blocks `Plugin.cs` with `scope_boundary` and no downstream success Artifact |
| Formal requirement coverage lacks one complete ProductExecution positive/negative composition proof | Unproven boundary, not an observed production failure | Current Queue work: coverage-authorized ProductExecution deterministic vertical scenario; register an Issue only if it exposes a production-code first failure with a physical owner |
| `ART-001` production owner projection remains effective and its reopen trigger is unsatisfied | Existing `ART-001` interaction | Corrected to `mitigated_for_current_scope` and `P3`; historical evidence is unchanged |
| Default/public Graph does not carry SourceRegistry root into relative `source_path` | Conditional authority concern outside the selected write path | No Issue now; trigger only if the default/public Graph receives real write authority without exact source/root authority, or selected ProductExecution fails an explicit negative path test |
| Findings local schema | Owner not reached | No Issue now; wait for a separately authorized actual7 to reach findings and expose a findings-owned failure |
| Requirement coverage continuity through Repair | Owner not reached | No Issue now; wait for a legal Patch followed by changed-product failure that exposes coverage loss or misrepresentation |
| New sealed preflight, receipt, and actual7 | Later authority gates | Not authorized by this docs checkpoint; they follow the deterministic vertical scenario and require separate decisions |

The conditional source/root trigger does not reinterpret the legacy fixture as
a current selected-path defect. The findings and Repair interactions remain
event-triggered so an unobserved failure is not fitted to an Issue in advance.
