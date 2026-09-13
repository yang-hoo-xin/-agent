# Unified product execution tracing

Base: `fa947cc388d4336967283b9bff66682825f08907`.
Implementation branch: `codex/upstream-execution-trace`.

The user requested that environment, materials and baseline preparation join
requirements, Findings, Planning and Patch in one execution tree, with readable
decision facts and verifiable local material links. This is prospective capture
at the actual owners. It does not reconstruct missing historical timestamps or
private model reasoning.

## Execution coverage

| Actual owner | Observation and retained facts |
| --- | --- |
| Settings and model environment admission | `environment.settings`, `environment.prepare`; duration, return or original exception |
| Initial target admission | `source.admission`; directory/project-file availability and original source-admission failure |
| Existing dependency, workspace and baseline callbacks | Original `failure_stage` name, `execution_phase=pre_graph`, callback invocation/return; a failed callback retains its existing failure report |
| Requirement interpretation | `requirements.projection`; input/output identities and actual `requirements.project` model generations |
| Source retrieval and optional augmentation | `evidence.retrieve`, actual `evidence.source_query` tool calls, `evidence.augment`; exact returned source/excerpt identities and distinct retrieval outcomes |
| Findings | `requirements.coverage`, actual `requirements.findings` generations; supplied excerpts, support/conflict/missing counts and deterministic admission outcome |
| Final evidence assembly | `evidence.member_access_enrich` when invoked and `evidence.assemble`; final returned pack hash after audit additions or enrichment fallback, API fact counts/hashes |
| Planning | `planning.decision`, actual `planning.select` generations; final pack and model-input hashes, selected evidence identities, local rationale receipt |
| Graph, shared worker and product checks | Existing node/Patch/verification/Review/Dry-run observations reuse the product trace; `workflow.route` records actual conditional selector results and mapped destination |

One invocation has one `product.execution` root. Worker journals subscribe only
to their segment: upstream generations do not increase the worker's own call
counter. The full invocation is retained in the existing run manifest at
`execution_observations`, with `execution_trace` identifying its trace/session.

Valid-task tracing begins before loading settings. It buffers observations in
memory until the original code creates the run manifest; it does not create a
directory early or modify an older run's manifest. Failure before that point is
available on the original exception and CLI error JSON as
`execution_observations` and `execution_trace`. At `ed5234b` this was memory-only;
the subsequent retention change below adds a checked local file reference.
Malformed arguments and absent authorization still fail before task creation.
Existing failure reports already bound by hash are not rewritten.

Each physical product invocation must have a distinct trace identity, including
same-number retries. Verified continuations sharing the existing ArtifactStore
and logical request correlate through the same session. Reusing the same text
request ID in an unrelated store does not establish a shared task. Active-trace
reuse checks product ownership; an unrelated context must not absorb this task.

## Meaning of material and decision links

The recorded stages distinguish assembly, transport attempt and valid provider
response. A timeout is not evidence that a model consumed its input. Generation
observations begin at the actual HTTP transport boundary, not at preview or
budget reservation. Missing measured usage remains unknown.

Material links compare the recorded evidence identity and exact excerpt hash;
source hashes are also checked where the actual input supplies them. A retrieved
item missing from a complete recorded input inventory is visible. This does not
by itself prove the item was needed, nor does a matching input prove model
attention, understanding, a correct modification or a unique root cause.

Planning receives a final EvidencePack, but its current model projection does
not include every `verified_member_accesses` field. The new fact hashes record
assembly/enrichment and explicitly leave full API-fact model delivery unproven.
This tracing change does not silently expand model input.

Cloud decision summaries are deterministic descriptions of approved structured
facts. Actual free-form Planning rationale stays in its local receipt, linked
by hash. A stage without an actual rationale retains `reason_unavailable`; no
extra model call generates an explanation after the event. A selected next node
is a routing decision, not proof that the node executed.

## Cloud and local query

The mapper `patch_live_langfuse_metadata_v3` sends native observation structure,
safe enums/counts, material hashes and deterministic summaries. All observations
of the product trace are named `Product execution` at trace level. Local request
and response bodies, source text, file paths, credentials and free-form rationale
are excluded. Body capture uses the exact application messages/schema/options,
not HTTP headers; payload and saved-document hashes have distinct meanings.

The existing read-only query supports:

```text
python -m src.observability.patch_langfuse_query --trace-id <recorded trace ID>
  --local-journal <existing run_manifest.json or retained CLI error JSON>
  --local-journal-sha256 <exact SHA-256 of that file>
  --local-artifact-root <explicit allowed local root>
```

The command above is one invocation, shown wrapped for readability. Local
joining verifies the selected JSON bytes, observation IDs/parents/types/times
and mapped facts before returning local references. Reading referenced bytes
additionally requires resolved containment in the explicit root and an exact
hash match. The returned summary does not contain or upload those bodies.
Missing parents, unmatched material origins and incomplete mappings remain
visible. Recorder/export failures cannot change business results or cause a
second model invocation.

## Executed engineering verification

The combined affected checkpoint passed **272 tests in 18.46 seconds** on
Windows/Python 3.10.20. Command:

```text
python -m pytest -q -n 2 --dist=loadfile --basetemp <short temporary directory>
  -o cache_dir=<short temporary cache>
  tests/unit/test_upstream_model_trace.py tests/unit/test_upstream_product_trace.py
  tests/unit/test_product_trace_lifecycle.py tests/unit/test_product_pre_graph_trace.py
  tests/unit/test_upstream_evidence_observations.py tests/unit/test_workflow_route_trace.py
  tests/unit/test_upstream_langfuse_query.py tests/unit/test_patch_langfuse_query.py
  tests/unit/test_patch_live_langfuse.py tests/unit/test_ollama_llm.py
  tests/unit/test_llm_providers_smoke.py tests/unit/test_execution_trace.py
  tests/unit/test_patch_loop_execution_trace.py tests/unit/test_dotnet_metadata.py
```

The public-entry scenarios use the original Graph/providers and real HTTP
serialization with intercepted transport and existing build test doubles.
They verify normal progression to original pending approval, Findings stopping
before Planning/Patch, and unavailable export preserving the business outcome.
Focused preflight cases cover settings/model/source and original baseline
failures, no fabricated model generations, buffered persistence, and retained
failure-file hashes. Provider tests include timeout, missing usage and local
body-write failure without retries. Final API-fact mapping has one additional
focused passing check. Ruff fatal-error and Git diff-whitespace checks passed.

Final identity corrections passed **26 focused tests in 8.56 seconds** using
`test_product_trace_lifecycle.py` and `test_product_pre_graph_trace.py`.
Same-number retries, different stores/requests, exact legacy Patch identity,
unrelated parent traces and shared export shutdown are covered. The strengthened
public-entry test file then passed **3 tests in 9.68 seconds**: all mapped rows
joined back to the complete local manifest and referenced body bytes; the final
assembled EvidencePack hash matched Planning's actual pack input. These are
overlapping follow-up checks, not extra independent product tasks.

No real model request, real compilation, Apply, game launch or synthetic Cloud
upload was performed for this work. New upstream Cloud ingestion/readback is
**not demonstrated** by these offline results. The next authorized real product
run can supply that acceptance; older Patch-only histories are not backfilled.

## Handled preflight failure retention

The infrastructure follow-up uses base `ed5234b9e0c6a2c453a0fbc0352e7a43964e958e`
on `codex/preflight-failure-retention`. The old public CLI was reproduced with
missing settings: exit 2, `BLOCKED`, two observations, no task directory and
`persisted=false`. A persistence assertion failed, confirming the reported gap.

When an exception exits the buffered product trace before its manifest exists,
the existing TraceCollector now writes a complete execution snapshot beside its
configured trace log: `execution/<trace_id>.json`. The existing manifest fields
are retained along with TraceContext fields. Bytes are flushed/fsynced before
exclusive publication; an existing record is never overwritten. The exception
and CLI result return the file path, SHA-256 and `persisted=true` only after the
strict sink succeeds. A storage error preserves the original business exception
and memory observations, reports `local_persistence.status=failed`, and leaves
`persisted=false`. Existing manifest runs keep their original recorder.

The original TraceService `get_trace` can read these records by trace ID. Its
normal safe view still sanitizes local details; `include_raw=True` permits an
explicit local full-document read. The saved native observations are also in
the format consumed by the existing local/Cloud journal join. No Cloud upload,
new model invocation, new product directory or business Artifact is introduced.

Eight new focused tests passed in 7.82 seconds. They execute the public CLI in
one process, then check the returned file hash and read the complete tree through
TraceService in another process; same-run retries, a retained older manifest,
bad Cloud, normal manifest recording, invalid input and absent authorization are
also covered. Storage failure was strengthened to fail the actual fsync step:
one focused check passed in 0.18 seconds, with no published or temporary file.
Eleven existing preflight checks passed in 3.70 seconds after changing only their
old memory-only expectations and isolating local trace output.

Final affected checkpoint: **102 passed in 18.06 seconds**, with no unresolved
failure. Exact command used the main workspace `.venv/Scripts/python.exe`:

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q -n 2 --dist=loadfile --basetemp C:/Users/10160/AppData/Local/Temp/pf-ret-final -o cache_dir=C:/Users/10160/AppData/Local/Temp/pf-ret-cache tests/unit/test_preflight_failure_retention.py tests/unit/test_product_pre_graph_trace.py tests/unit/test_product_trace_lifecycle.py tests/unit/test_trace_context.py tests/unit/test_trace_service.py tests/unit/test_upstream_product_trace.py
```

Ruff `E9,F63,F7,F821` passed on the five changed Python files. These selections
overlap and are not independent product tasks. No real model, compilation,
product Apply, game or network operation was part of these checks. This proves
retention after handled failure and process exit; it does not claim recovery
after uncatchable termination, total storage failure or partial product writes.
