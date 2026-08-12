authority: non_authoritative_derived_presentation

# Two-feature-specific offline verification fixture

## Scope

This fixture prepares two calibration/development cases:

- `better_hit_feedback_positive_calibration`
- `wall_crawler_insufficient_evidence_calibration`

It verifies reproducible input identities, the existing Arm A canonical corpus snapshot, allowlisted retrieval scope, minimal API/metadata/IL/Runtime facts, leakage boundaries, and annotation binding. It does not implement or run RAG-1A Discovery, compare a future actual output with expected judgment, grant product admission, define CI promotion, or build a general Eval/Trace platform.

Base commit: `5f9443af80289a80a47dfe75cfe91a547c196d45`.

## Durable identity

Machine-local absolute paths are runtime locators only and are not persisted. Each `corpus_manifest.json` owns only the input world and actual-retrieval allowlist identity: logical input roles, locator arguments, expected content SHA256/MVID, repository-relative source refs, acquisition steps, included source identities, excluded source classes, and the Arm A corpus snapshot identity. Evidence projections, annotation process, judgment, confirmation, and replay metadata are not manifest-owned.

Corpus aggregation is delegated only to:

`src/mod_agent/evaluation/arm_a.py::RunManifestCollector.canonical_corpus_snapshot`

The fixture implements no second directory-hash algorithm.

## External inputs and command

The operator must supply the exact lawful inputs named by:

- `--r8-root`
- `--current-interop-assembly`
- `--bhf-historical-implementation`
- `--bhf-runtime-result`
- `--bhf-runtime-bounded-log`
- `--bhf-runtime-full-log`

From the repository root:

```powershell
python -B docs/calibration/two_slice_data_readiness/validate_data_readiness.py `
  --r8-root <lawful-r8-root> `
  --current-interop-assembly <installed-interop-Modules-ASM.dll> `
  --bhf-historical-implementation <hash-bound-historical-HitFeedbackBehaviorPatch.cs> `
  --bhf-runtime-result <bound-runtime_result.json> `
  --bhf-runtime-bounded-log <bound-enabled-bounded-log> `
  --bhf-runtime-full-log <bound-enabled-full-log>
```

The validator builds the existing read-only IL inspector in an operating-system temporary directory. It does not build a Mod or execute target code.

## Report and exit boundary

The deterministic JSON report contains only:

- `report_schema_version`
- `local_replay_validation`
- `annotation_binding_state`
- per-case mechanical validation statuses
- `failure`

Exit 0 means mechanical replay passed. Exit 1 means fixture content, IL/Runtime facts, leakage boundary, local tool execution, or binding validation failed. Exit 2 means a required lawful external input is unavailable. No result is a Data Readiness, RAG-quality, promotion, or product-authorization verdict.

## Confirmation and handoff boundary

The operator confirmed the natural-language requirements, product hard constraints, and continue/block product semantics stated in the request. Operator confirmation is not Hook approval, Patch/Apply/Build/Runtime authority, a Data Readiness verdict, or product execution approval. The technical review authority is exactly:

`independently_model_reviewed_technical_calibration_annotation`

It means an independent model reviewed the technical evidence. It does not mean independent human annotation, blind review, held-out evaluation, or promotion. The operator has confirmed the final payload product semantics, and the version-5 annotations bind:

- BetterHitFeedback `frozen_judgment_hash`: `C43DA97715FF4408FF1687EBB7B4756B2F5FED8D3EBF1ADF78A53EED8F1507A1`
- WallCrawler `frozen_judgment_hash`: `FD57B8971AD642E8471AB047E261EEFA407EEE5A94FF6448F97731F53894F7B7`

Evidence projections may support annotation creation, but annotation judgment is not mechanically derived from projection. A method, body, marker count, current provider readiness, blocker, or RAG output cannot mechanically determine an acceptable Hook, sufficiency, or continue/block action.

## Replay facts

The final 15-file bytes were replayed with the same six lawful external-input roles in:

- the 10f8 WIP owner at Git revision `5f9443af80289a80a47dfe75cfe91a547c196d45`;
- a clean checkout at exact target checkpoint `207c0572d7f78dffffe498140c0ad1fcb76c5d23`.

Both executions returned exit `0`, `local_replay_validation: passed`, `annotation_binding_state: frozen`, `failure: null`, and per-case passed statuses for input identity, canonical corpus, evidence recomputation, leakage, and annotation binding. Validator SHA256 for these runs: `33A7C24D6864ECFBECC22C5121E43880F929F2F6AAEF5963C517B71A0827EAB4`.

The current stop is pending bounded fixture acceptance. Replay success does not grant Golden completion, Data Readiness, RAG quality, promotion, product authorization, or implementation authority.
