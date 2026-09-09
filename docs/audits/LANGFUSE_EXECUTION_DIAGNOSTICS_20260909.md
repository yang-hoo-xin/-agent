# Langfuse execution diagnostics

Base: `7faf3a32c44606b166549638d94b35758d7e6b90`.

The user requested direct use of Cloud tracing and useful journal capabilities
in Langfuse. The Cloud remains a query/evaluation projection. Local journals and
Artifacts retain source bytes, approval authority, recovery inputs and replay.
This change does not move workflow state or grant model/source disclosure.

## Direct Cloud query

`python -m src.observability.patch_langfuse_query --trace-id <actual trace ID>`
reads one trace with the existing environment-configured HTTP transport.
`--output <local JSON path>` writes the regenerable diagnostic result.
The reader discovers current Cloud MCP tool/input/observation-field schemas;
it allows only observation/schema/score reads, requests neither input nor output,
and expands the three existing structured metadata fields used for bindings.
Pagination and response sizes remain bounded. Schema drift, identity conflicts
and incomplete pagination fail explicitly rather than claim complete evidence.

The result reports recorded generations separately from `model.request`
observations and reserved worker calls; times are calculated from actual UTC
start/end values. Token aggregation understands this mapper's exclusive usage
buckets and the Cloud-added derived `total`, without adding that total twice.
Unmeasured usage, cost and TTFT remain unknown. Tool consumption joins use both
call identity and observed-byte hash. Verification joins use the recorded output
hash. These joins establish recorded identity, not semantic correctness.

One actual Cloud trace (`08109b3cf24f0f65374c3932cc7516ad`) was queried with the
new reader: 18 observations, 3 generations, 1 behavior-failed verification bound
to generation 2, and one source observation consumed by generations 2 and 3.
Generation 3 registered an upstream request with
`upstream_execution_performed=false`; the root is partial at
`generate_patch_proposal`. Cloud scores for that trace were empty. This is an old
owned debugging run, not the current Repair acceptance or Mod delivery.

The first live query exposed HTTP 406 because the reused HTTP helper did not
declare MCP response types. The helper now adds
`Accept: application/json, text/event-stream` only for the MCP endpoint.
The same read then succeeded. Existing OTLP and historical score paths retain
their request headers.

## Cloud dashboard already verified

[Mod Agent 执行与验证](https://us.cloud.langfuse.com/project/cmtr5q7ae024iad0im785u4xl/dashboards/cmttvkxin00iiad0imc5sf21d)
contains five native widgets: generation counts, latency p50/p95, input/output
tokens, behavior-failed verification counts and partial-root counts. Creation,
query results and saved placement/configuration were read back via Cloud APIs;
rendered browser appearance was not independently verified.

Its sample is the original four approved traces: 57 observations, including nine
generations. The dashboard is filtered to the existing debugging data and a
fixed September 8–10 UTC window. Counts are not production success rates. No
new source, model prompt or GTFO material was uploaded to create it.

Cloud metadata reads truncate structured keys to 200 characters unless expanded.
Expanding `artifact_refs` proved all four original lists equal the approved
payload. The nine usage differences were Cloud-added `total` values. Neither
was evidence of lost uploaded data.

## What this does not establish

- All Mod delivery stages are not yet demonstrated in Cloud. An absent span is
  unobserved; it does not independently prove that an operation did not run.
- The actual `nlcfg_002` journal contains 19 Patch/tool/verification observations
  and two `patch.generate` generations. Projection, Findings and Planning each
  ran once upstream, but are absent from those observations. Projection/Findings
  sidecars retain request/output hashes without UTC start/end or usage; Planning
  has measured elapsed/provider duration and usage but no UTC start/end. These
  old facts must not be retrofitted with inferred generation timestamps. Future
  collection belongs at `complete_requirement_coverage_json`,
  `PlanningClient.complete_turn` and their actual provider calls, with the
  existing product trace activated before those stages. Current Patch activation
  occurs afterward; adding no-op spans outside it would not solve this gap.
- A completed observation or `DEFAULT` level is not task success. Original
  records had 53 DEFAULT and four ERROR observations.
- Prompt Name requires an actual managed-prompt linkage. TTFT requires actual
  first-output timing. Neither is generated from unrelated timestamps.
- Deterministic compile, behavior, configuration and applicable Runtime results
  remain separate. An LLM judge cannot replace those checks.
- Old development tasks are not an independent evaluation set. Dataset/experiment
  use must preserve task splits, scorer versions, all failed trials and deployment
  identity. No new judge, training, model call or automatic prompt update ran here.

## Query verification

Python: existing main-repository `.venv/Scripts/python.exe` (3.10.20), cwd the
isolated `langfuse_execution_diagnostics_001` tree.

Initial query unit checks: `-B -m pytest tests/unit/test_patch_langfuse_query.py
-q --tb=short` — 10 passed, 1.15s. After the observed HTTP 406/header repair:
`-B -m pytest tests/unit/test_patch_langfuse_query.py tests/unit/test_patch_langfuse.py
-q --tb=short` — 40 passed, 4.09s. Both used short system-temp basetemp/cache paths.
The tests cover duplicate counts, conflicting IDs, mismatched tool content,
missing usage/timing, score identity, dynamic schema drift, pagination loops,
body exclusion and MCP Accept negotiation. Ruff fatal checks passed.

Actual read-only output and native dashboard receipts are retained under the
local run root `scratch/langfuse_cloud_diagnosis_20260909`; these local files
are not a second durable workflow index.

## Prospective native verifier status and bound scores

`patch_live_langfuse.py` now identifies new observations with
`patch_live_langfuse_metadata_v2`. A normally returned `patch.verify` observation
with `behavior_failed`, `needs_evidence`, `infrastructure_failed` or
`identity_failed` receives native `WARNING` and a machine status message.
Completed workflows explicitly marked partial, blocked or failed also receive
`WARNING`. Neutral observation exceptions retain native `ERROR` and OTLP error
status; a completed negative verifier keeps its completed-operation status.
`DEFAULT` and completed operations are explicitly described as not task
acceptance. No exception body, model explanation or local path is copied into
the status message. The mapping uses the documented
[`langfuse.observation.level` and `langfuse.observation.status_message`](https://langfuse.com/integrations/native/opentelemetry)
attributes; the execution/semantic distinction is this platform's declared policy.

The existing production wrapper
`LocalOllamaInitialPatchAdapter._evaluate_generated_behavior` adds one guarded
call to `verified_behavior_trace_attributes(report, model_response)` only when
an execution trace is active. The bridge reads retained response bytes and the
bound report, compares complete materialized-code and generated-change
identities, then reuses the existing historical `_verified_check_counts` reader.
It does not import historical records, alter a grader, or supply missing counts.

Eligibility requires an admitted report, an actually invoked callback, explicit
executed origin, retained response bytes matching their hash, bound report and
matrix bytes, nonempty unique check names with Boolean outcomes, a positive
explicit matrix execution count, and agreeing report/summary counts and status.
Existing reports without an explicit response hash retain the prior helper's
transitive complete-code/change binding. If a persisted report does contain
`model_response_sha256`, it must equal the current retained response hash;
contradictory hashes and explicit null are rejected even after the report's file
hash is recomputed. Missing, reused, unexecuted, incomplete or inconsistent proof
produces no behavior score. A proof-projection exception also degrades to no
score and cannot change the already-admitted product result.

The bridge exposes only `score_eligible`, `score_basis`, `checks_run`,
`checks_failed`, `verification_executions`, `verification_matrix_sha256`,
`source_snapshot_sha256` and `admission_result`; the wrapper already provides the
report, output-code, response and generated-change hashes. These are observation
metadata, not a new workflow registry. Verifiers without the existing explicit
matrix/execution-count shape remain unscored even if their callback returned a
normal result. In particular, moving a `verification_summary` number into trace
metadata alone is insufficient proof.

`build_patch_live_scores` creates at most one native NUMERIC
`local_check_pass_fraction`, with denominator equal to verified local checks.
It binds the original normalized trace/observation IDs and uses a deterministic
score ID. Zero is emitted only when an actually executed nonempty matrix failed
all checks; unknown execution is never numeric zero. One means those local
checks passed, not complete code correctness, model qualification, Mod delivery
or Runtime. The body reuses the existing
[`POST /api/public/scores` contract](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk)
and contains no source, prompts, replies, test-body content or paths.

The opt-in sink retains one bounded queue and one HTTP worker. Each item carries
its observation and optional score; their combined bytes count toward the
existing payload cap. Only a fully accepted OTLP response is followed by the
score POST. Partial/failed observation transport suppresses the score. Score
HTTP failures are counted independently, do not reverse observation acceptance
or alter the product result, and do not trigger a retry. Existing observation
statistics retain their meaning; new counters are `score_queued`,
`score_post_attempts`, `score_http_accepted`, `score_send_failures` and
`score_skipped_unaccepted_observation`. Remote readback remains not performed;
HTTP acceptance is not a delivery-proof claim. Original Cloud traces/scores
were not changed and this mapper implementation was not sent to Cloud.

## Mapper/score focused verification

Tests use local bound-file fixtures and intercepted HTTP. They are engineering
checks, not real-model or real-Cloud score results. Current selections are
`tests/unit/test_patch_live_langfuse.py` and the new
`tests/unit/test_patch_live_verification_scores.py`.

Using the existing Python 3.10.20 environment in the isolated worktree:

- Native status regression: `python -B -m pytest
  tests/unit/test_patch_live_langfuse.py -k 'completed_verifier or
  transport_exception_remains or completed_root or generic_completed' -q
  --tb=short --basetemp="$env:TEMP\lf-diag-green"` — **9 passed, 1.09s**,
  after reproducing nine failures on the old mapper.
- The score/proof/sink file initially ran 29 selections: 23 passed and six
  failed because the raw producer references lacked the historical reader's
  projection shape. After adapting that shape while preserving actual byte/hash
  validation, `python -B -m pytest tests/unit/test_patch_live_verification_scores.py
  --lf -q --tb=short --basetemp="$env:TEMP\lf-score-fix"` — **6 passed, 2.18s**.
- Independent review's recomputed-report/different-reply counterexample first
  failed twice. The targeted fix plus explicit executed-zero/one examples:
  `python -B -m pytest tests/unit/test_patch_live_verification_scores.py
  -k 'rehashed_report or extreme_scores' -q --tb=short
  --basetemp="$env:TEMP\lf-score-reply-green"` — **4 passed, 1.94s**.
- Actual production trace-wrapper composition, including a synthetic unexpected
  proof-reader exception: `python -B -m pytest
  tests/unit/test_patch_live_verification_scores.py -k 'real_verifier_trace'
  -q --tb=short --basetemp="$env:TEMP\lf-score-failopen"` — **2 passed, 1.98s**.

These selections overlap and are not added as independent case totals.
After reader and mapper implementation stopped changing, the combined command
below passed **117 tests in 32.76s**, including CLI composition:

```powershell
python -B -m pytest tests/unit/test_patch_langfuse_query.py tests/unit/test_patch_langfuse.py tests/unit/test_patch_live_langfuse.py tests/unit/test_patch_live_verification_scores.py tests/unit/test_patch_live_trace_cli.py -q --tb=short -n 2 --dist=loadfile -o cache_dir="$env:TEMP/lfdiag-cache" --basetemp="$env:TEMP/lfdiag-$PID"
```

The final reader also directly queried all four existing Cloud traces: 18/18/7/14
observations and 3/3/1/2 generations respectively; all returned no scores.
Measured totals were 29,050 input and 609 output tokens, without double-counting
the server-derived total. Results are in `cloud-query-four-final.json` under the
same local evidence root. This is actual Cloud readback; the new score writer
remains validated through intercepted HTTP until an authorized product run uses it.

Main-repository venv Ruff
`E9,F63,F7,F821` and `git diff --check` passed for the mapper/caller/tests;
the ambient Python lacked Ruff, so no dependency was installed.

Integration into `codex/rag-capability-mainline` at `4f6e696` preserved unrelated
documentation WIP. The intersecting producer/reservation/Review selection
`tests/unit/test_patch_live_verification_scores.py tests/unit/test_initial_repair_reservation.py
tests/unit/test_product_proposal_context_budget.py` passed **41 tests in 4.68s**
with the same Python, `-q --tb=short -n 2 --dist=loadfile`, short TEMP basetemp
and cache. The Repair acceptance tree remains frozen separately at `a8b8971`.
