# Retrieval Validation Plan

## 1. Objective

Determine which retrieval mechanisms materially improve the Evidence-Grounded
Controlled Code Generation Agent Platform over a live-workspace `rg` baseline,
without increasing unsafe edit decisions, stale evidence use, latency, or cost
beyond agreed budgets.

Every track freezes its cases and decision rules before first result collection.
The QualityGatePolicy requirements below apply to formal benchmark/promotion
runs; the directional pilot uses raw local counts and no promotion gate.
Thresholds may be changed before the first formal benchmark run, but not after
inspecting results without recording a new experiment version.

Benchmark thresholds are a versioned `QualityGatePolicy`, not caller-supplied
free-form flags. The policy must exactly cover its declared metrics, cover the
required retrieval metrics, use finite non-zero retrieval thresholds, and be
bound into the evaluation protocol identity. The transition Gate independently
recomputes the result from policy plus metrics.

## 1.1 Two Validation Tracks

This document separates two different activities that must not be promoted into
each other by implication:

| Track | Purpose | Active status |
| --- | --- | --- |
| `V2-RET-DIRECTIONAL-001` | Time-boxed local evidence for the next product investment | Completed; bounded local decision retained rg plus live reads |
| `V2-RET-001A/B/C` and H1-H5 | Promotion-grade or broader formal validation when a concrete product decision requires it | Conditional long-term roadmap |

The directional track is not a smaller claim disguised as a formal benchmark.
It records raw local evidence and supports only a bounded next-step decision.
The formal track remains available, but its Arms A-G, downstream contracts,
mutation matrix, and promotion rules are not consecutive V2 blockers.

The completed evaluator-contract, formal-attestation smoke v5, and directional
raw results are reusable assets. Do not generalize them further unless a later
bounded experiment cannot preserve truthful raw results without a specific repair.

## 1.2 Completed One-Day Directional Pilot

### Decision question

For the recorded repository revision and frozen directional cases, choose one:

1. retain `rg` plus live file reads as the default;
2. invest next in the current SymbolIndexer/structural-navigation path;
3. invest next in a minimal authentic community/history BM25 path;
4. record insufficient evidence and retain `rg` without expanding retrieval infrastructure.

### Directional arms

| Arm | Bounded behavior | Claim boundary |
| --- | --- | --- |
| A | `rg` plus live file reads | Local baseline only |
| B | Arm A plus the current SymbolIndexer and live result revalidation | Measures the current implementation, not a complete AST/LSP/call-graph system |
| D | Small authentic community/history BM25 fixture plus current-source verification | Measures real traceable hints; a synthetic-only fixture is `plumbing_only` |

Do not run code-BM25-only, Dense, RRF, rerank, or Agentic routing in this pilot.
Do not add a production CommunityNoteLoader, general ranked-Hook schema,
Dashboard/MCP surface, or LangGraph node merely to make an arm runnable.

### Directional cases and observations

Use a small set frozen before first result collection, with a target maximum of
12 cases only when the ground truth can be established from current source/API,
tests, or traceable authentic history. Cases used to tune smoke v5 are excluded.
Keep code/exact, current-SymbolIndexer-compatible, and community/history strata
separate; do not average non-applicable arms into one headline score.

Record per case:

- correct file found at 5;
- correct Hook/symbol found at 5 where the current arm can represent it;
- first correct result rank and MRR;
- irrelevant returned-file count;
- community hint found, then verified, rejected, or unresolved by current source;
- latency;
- implementation effort and estimated maintenance burden, explicitly not an observed long-term maintenance cost.

Absolute case counts may guide the next investment. Small-sample percentages,
H1-H5 pass/fail labels, statistical significance, cross-project superiority,
wrong-file modification, final Agent success, and production promotion are
outside this pilot.

### Time box and stop rules

Stop the pilot when any of these occurs:

- one working day is exhausted;
- an arm needs more than 90 minutes of new platform contract/schema work;
- an arm requires LangGraph, Dashboard, MCP, production loader, Dense, RRF, or Agentic expansion;
- a frozen-case defect invalidates the run; retain the invalid result and create a new version rather than editing in place;
- raw A/B/D results, manual judgments, limitations, and the next-step decision are saved.

After the directional report, return to product capability delivery. Collect
wrong-target, proposal-review, task-success, retry, and maintenance outcomes in
real product work. Open another bounded experiment only when those observations
create a concrete decision that cannot be made from existing evidence.

## 2. Conditional Formal-Validation Questions

These are the long-term questions that separate bounded experiments may answer
when a product decision triggers them. `V2-RET-DIRECTIONAL-001` answers only the
A/B/D next-investment subset defined in section 1.2.

1. How much does BM25 improve Recall@K over `rg`-only, and on which source types?
2. How many additional correct Hooks does dense retrieval find beyond BM25 and
   deterministic code retrieval?
3. Does source-aware mixed retrieval reduce wrong-file modification rate?
4. Does Agentic query rewrite/retry improve final task success?
5. What latency, token/API usage, and monetary cost does each improvement add?
6. How often do code indexes return stale, renamed, deleted, or branch-mismatched
   results?

## 3. Formal Evaluation Dataset

Create a versioned golden dataset with four strata:

| Stratum | Purpose | Required ground truth |
| --- | --- | --- |
| Exact code lookup | Literal identifiers, config keys, errors, paths | exact files, symbols, and spans |
| Structural Hook discovery | Hook targets, overloads, callers, annotations | accepted Hook method identity and supporting API/source spans |
| Vague semantic intent | Behavior described without repository terminology | accepted implementation area, Hooks, and relevant source evidence |
| Community/history dependent | Decisions or failure hints found in curated discussions/releases | relevant note IDs plus the current source/API evidence that verifies or rejects each claim |

Each case records:

- stable case ID and dataset version;
- repository/worktree revision;
- natural-language request;
- expected source type;
- relevant files, symbols, source spans, and Hook identity where applicable;
- forbidden or known-wrong files/Hooks;
- whether community/history evidence is required;
- expected readiness outcome;
- task-level acceptance rule.

Initial development runs may use controlled fixtures. Interview-grade claims
require a separately reported set of real repository tasks that was not used to
tune routing rules.

## 4. Formal Experimental Arms

| Arm | Retrieval behavior | Role |
| --- | --- | --- |
| A | `rg` plus live file reads | required baseline |
| B | `rg` plus symbol/AST navigation and live revalidation | deterministic structural path |
| C | code BM25 only | diagnostic arm, not a proposed authority path |
| D | community/history BM25 plus code `rg`/symbol, separated by source authority | source-aware mixed path |
| E | B or D plus dense auxiliary retrieval | semantic-recall test |
| F | fixed score fusion/RRF over available retrievers | fusion comparison |
| G | Agent selects tools, rewrites/retries, and revalidates live code within a fixed budget | Agentic routing comparison |

Every arm uses the same dataset split, top-K values, repository revision,
readiness policy, proposal/review implementation, and task acceptance rules.
Report comparison has three explicit modes: `calibration` produces only
`calibration_complete`; `benchmark_measurement` requires fresh benchmark
evidence; `promotion` additionally requires the same passing quality policy.
For every compared metric, the exact `applicable_case_ids` must match.

### Deferred measurement contracts (not hidden evaluator repairs)

- H2/H3 require a unified ranked Hook-result object carrying rank, identity,
  source span, and live-revalidation provenance. The current parallel
  `retrieved_hook_ids` representation may support calibration but cannot close
  H2/H3.
- H4 requires an end-to-end modification outcome with wrong-file and
  no-modification states modeled separately. A single retrieval metric cannot
  establish the H4 claim.
- H5 requires a retry trace with attempt budgets, rewritten queries, evidence
  transitions, and final task outcome. It is not inferred from aggregate
  retrieval rows.
- The first real Arm A deliverable includes an actual RunManifest collector;
  caller-authored identity strings are not benchmark evidence.

## 5. Conditional Preregistered Hypotheses H1-H5

### H1: Historical/Community BM25 Adds Relevant Recall

On community/history-dependent cases, Arm D improves Recall@10 by at least 10
percentage points over Arm A while community evidence remains planning-only and
does not increase wrong-target decisions by more than 1 percentage point.

Decision:

- pass: keep persistent BM25 for curated historical/community sources;
- fail: do not build a broad community ingestion path until query/data quality
  is improved and re-evaluated.

### H2: Structural Retrieval Improves Hook Discovery

On structural Hook cases, Arm B improves correct Hook Recall@5 by at least 10
percentage points over Arm A, with every consumed result passing live file/hash
and method-identity validation.

Decision:

- pass: keep disposable symbol/AST navigation in the production path;
- fail: use `rg` plus live reads as the default and restrict structural indexes
  to diagnostic use.

### H3: Dense Retrieval Finds Additional Correct Hooks

On vague-intent cases, Arm E finds at least 5 percentage points of additional
correct Hook Recall@10 beyond the strongest deterministic arm, without reducing
correct-file Precision@10 by more than 2 percentage points.

Decision:

- pass: retain dense retrieval as an auxiliary, never sole patch authority;
- fail: defer production dense storage, embedding refresh, and reranking work.

### H4: Source-Aware Routing Reduces Wrong-File Modifications

Compared with fixed score fusion, source-aware separation and live-code
verification reduce wrong-file modification rate by at least 30 percent relative
while final task success is no worse by more than 2 percentage points.

Decision:

- pass: make source-specific routing and authority conflict resolution the
  production mixed-retrieval design;
- fail: retain deterministic code retrieval and investigate the failed routing
  or ground-truth assumptions before expanding fusion.

### H5: Agentic Retry Improves Final Success Within Budget

On cases where the first retrieval attempt is insufficient, Arm G improves
final task success by at least 10 percentage points over the strongest fixed
arm, with at most two retrieval retries, median end-to-end latency no more than
2x the fixed arm, and all API/token/monetary costs reported.

Decision:

- pass: enable bounded Agentic rewrite/retry for classified failure modes;
- fail: retain deterministic routing and expose insufficient evidence instead
  of adding uncontrolled retries.

## 6. Formal Metrics

### Retrieval Metrics

- Recall@1, Recall@5, Recall@10;
- Precision@5 and Precision@10;
- Mean Reciprocal Rank for the first correct Hook/source span;
- unique correct Hooks added by each arm;
- citation file/symbol/span accuracy;
- stale-result rate;
- source-authority classification accuracy;
- evidence-readiness false-continue and false-block rates.

### Downstream Agent Metrics

- correct Hook selection rate;
- correct target-file selection rate;
- wrong-file modification rate;
- unsupported change-unit rate;
- proposal-review blocker precision and recall;
- first-pass and final controlled-task success;
- retrieval retry recovery rate;
- repair-loop success and retry exhaustion rate.

### Cost And Performance Metrics

- retrieval latency p50/p95;
- end-to-end task latency p50/p95;
- index build and incremental refresh time;
- peak index size and memory use;
- model/API call count;
- input/output token count;
- embedding count and cache-hit rate;
- monetary cost per case and per successful task.

## 7. Formal Freshness And Mutation Tests

Run every code-index arm through controlled mutations:

1. edit a method body without renaming it;
2. rename a file;
3. rename a symbol;
4. delete a file;
5. switch branch/worktree namespace;
6. change files concurrently between retrieval and EvidencePack consumption;
7. return an intentionally stale index result.

The evaluator records:

- whether the index refreshes automatically;
- whether stale evidence is detected before proposal generation;
- whether the system falls back to `rg` and live reads;
- whether a stale result can reach readiness, proposal, or review;
- refresh and fallback latency.

No code-index strategy passes production validation if stale evidence can grant
patch authority.

## 8. Experiment Execution Order

Implementation status on 2026-07-11:

- `V2-EVAL-001-FOLLOWUP` is complete at the evaluator-contract boundary after
  focused verification. Policy recomputation, explicit comparison modes and
  applicable populations, external-evaluation graph authority, strict inputs,
  and split observation hashes are implemented. Actual identity collection is
  deliberately the first Arm A capability, not a caller-authored evaluator field.
- `V2-RET-001A-SMOKE-ARTIFACT` retained internally consistent v1/v2 artifacts;
  v2 supports an engineering-level harness-run conclusion but does not itself
  attest binary identity or exact searchable-corpus equivalence.
- `V2-RET-001A-AUTHENTICITY` is complete with formal smoke v5. The formal
  runner owns provider/collector construction; exact rg executable identity,
  argv, normalized environment and command traces are recorded; rg searches
  only the canonical snapshot file list; returned files are rehashed; the
  exclusive result ledger hashes persisted bytes. The smoke is explicitly
  non-promotion and its tuned cases are excluded from held-out reuse.
- Formal v5 values are measured smoke observations, not held-out Arm A quality
  results. No BM25, dense, fusion, Agentic-routing, or H1-H5 result exists.

1. `GTFO-VSLICE-001C` completed: the deterministic downstream consumer and
   repair-decision taxonomy are stable for the registered evaluation path.
2. `V2-EVAL-001-FOLLOWUP` completed at the evaluator-contract boundary.
3. `V2-RET-001A-AUTHENTICITY` completed as non-promotion execution-plumbing
   evidence; it is not a retrieval-direction result.
4. Completed: `V2-RET-DIRECTIONAL-001` saved frozen A/B/D raw evidence and a
   bounded decision report. The result retains A (`rg` plus live reads), defers
   SymbolIndexer deepening until repeated structural-navigation failures, and
   defers community BM25 until authentic traceable material exists. Product
   delivery resumes with `V2-CODEGEN-REAL-001`.
5. Keep the formal held-out Arm A design already produced as future material;
   do not let it block the directional pilot or current product work.
6. Trigger only the relevant formal `V2-RET-001A/B/C` measurement when a later
   product decision requires an H1-H5 or promotion-grade claim.
7. Project a selected production path into dashboard/MCP surfaces only when the
   product path itself needs those surfaces, not merely to display an experiment.

## 9. Formal Required Outputs

Each formal benchmark run produces:

- immutable experiment configuration;
- dataset and repository revision;
- per-case retrieval results and evidence refs;
- per-arm metric summary;
- latency and cost summary;
- stale-index mutation results;
- failures and excluded cases with reasons;
- hypothesis verdicts;
- production-path decision and rollback condition.

Results must distinguish fixture-only, local-repository, and real-world task
evidence. A passing fixture benchmark alone is not a production claim.

## 10. Formal Stopping Rules

- Stop dense expansion when H3 fails; do not compensate by adding reranking or
  more infrastructure before diagnosing recall and ground truth.
- Stop Agentic retry when the retry budget is exhausted or evidence remains
  insufficient.
- Stop any arm that allows stale or non-authoritative evidence to approve a
  target file or Hook.
- Do not promote an arm on retrieval metrics alone when downstream wrong-file
  or task-success metrics regress beyond the preregistered bounds.
