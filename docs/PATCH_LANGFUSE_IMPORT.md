# Historical Patch metadata import

`src.observability.patch_langfuse` is a post-run consumer of the existing
`project_patch_executions` query. It does not run Patch, Repair, a verifier, the
Graph, or Artifact writes. The original Projection V2 identity exporter and its
closed owner whitelist are unchanged.

## What is exported

One source journal with a verified terminal-result hash produces one deterministic
trace ID. Its children represent retained model-turn records, source-tool records,
code-response **references**, behavior-verification records, and any upstream
provider records. Parentage is the imported run; the importer does not invent
cross-record causal edges or missing links.

Every observation is an `event` tagged `historical_import` and `metadata_only`.
OTLP requires timestamps: start/end are the explicitly recorded import snapshot
time, with `original_event_time=unknown`. They are not reconstructed original
execution times. Native generation latency, native model-call totals and native
cost dashboards must not be treated as measurements of these historical runs.
Recorded token counts and run counters remain separate metadata with their source
claim boundary.

The default network payload excludes source text, prompts, model output, actual
file paths, free-form diagnostics, and expected/actual code or test values.
References expose hashes and hashed locators; unknown text labels are hashed.
Known machine statuses and numeric counters are retained. Credentials are read
only for `send`/`verify`, from `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY` and
`LANGFUSE_SECRET_KEY`, and are never part of an import batch or result.

An explicitly executed, admitted behavior report can yield
`historical_local_check_pass_fraction` only when report/code links and the hashed
matrix agree with the recorded check denominator. Reused, unknown, incomplete,
missing or inconsistent verification produces no score. These are local check
fractions, not cross-task success rates, model qualifications, Build or Runtime.
The report must bind the exact matrix path and hash, explicitly record execution,
and agree with the evaluation's source/code identities and retained response bytes.
Any identities also stated by the matrix must agree. Older matrices may bind code
through that exact report reference; no missing identity is invented. Matrix,
report and evaluation counts must agree wherever recorded. An ineligible score is
marked `score_eligible=false` in the imported verification metadata; the trace can
still be imported without a score.

## Transport and readback

The adapter uses the existing locked `httpx` dependency; no Langfuse SDK, OTel
runtime, new service or lock-file edit is required for HTTP/JSON transport.

* Observations: `POST /api/public/otel/v1/traces`, JSON, Basic project-key auth,
  `x-langfuse-ingestion-version: 4`.
* Scores: `POST /api/public/scores`, explicit deterministic score IDs.
* Readback: `GET /api/public/v2/observations?traceId=...` and
  `GET /api/public/v3/scores?id=...`.

The supported target is current Langfuse Cloud or self-hosted v4. A v3 instance
may need a separately selected legacy read adapter; this implementation does not
silently fall back to deprecated APIs. HTTPS is required except literal local
loopback HTTP. Redirects and environment proxies are disabled.

`read_observation(trace_id, observation_id)` selects the exact observation from
bounded, paginated trace results. Import verification checks source-journal
identity and score subject/value, with at most five read attempts and a bounded
delay. API acceptance alone is not readback success.

IDs are stable across repeated preparations of the same journal. The client
checks for them before writes; fully present data returns `already_present`
without any POST. Partial data, a timeout, or pending visibility is not
automatically re-sent by that client; use readback to reconcile it. There is no
new durable retry ledger and no distributed exactly-once claim across process
crashes, concurrent importers, or arbitrary remote retention. Do not launch
multiple importers for the same source while its delivery is unresolved.

Sink errors return `export_failed_open`/`partial_ingestion`/`readback_pending` or
`reconciliation_required_no_resend`. They never update product facts or authorize
another model attempt. An unavailable service does not erase the original run.

## Usage

Zero-network preview; output contains only the allowlisted outbound payload:

```powershell
python -B -m src.observability.patch_langfuse prepare --artifact-store-root <store> --attempt-locator <exact-journal-path>
```

After selecting the target project, setting its three environment variables, and
authorizing the displayed data classes for that destination:

```powershell
python -B -m src.observability.patch_langfuse send --artifact-store-root <store> --attempt-locator <exact-journal-path>
python -B -m src.observability.patch_langfuse verify --artifact-store-root <store> --attempt-locator <exact-journal-path>
```

These commands do not read API keys from arguments or print them. `prepare`
neither reads credentials nor sends anything. Configuration or this document
does not grant upload permission. Missing credentials or endpoint return an
explicit export error, not a claim that the service is absent elsewhere.

The module re-reads the source projection before sending; changed source or
mutated prepared payload is rejected before HTTP. Existing 009/013 journals can
be imported without executing their models or matrices again. Whether a chosen
live service ingests, persists, displays and returns them still needs that actual
service acceptance; HTTP substitutes do not prove deployment.

## Official interface sources

* [Langfuse native OTLP integration](https://langfuse.com/integrations/native/opentelemetry): HTTP/JSON,
  HTTP/protobuf, authentication, v4 header, observation attributes and timestamp handling.
* [Custom ingestion migration](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4):
  complete spans and the supported ingestion path.
* [Observations API](https://langfuse.com/docs/api-and-data-platform/features/observations-api):
  v2 trace filters, pagination, field selection and delayed availability.
* [Scores API](https://langfuse.com/docs/api-and-data-platform/features/scores-api) and
  [score writes](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk).
* [OTLP specification](https://opentelemetry.io/docs/specs/otlp/): JSON hex IDs,
  numeric enums, uint64 timestamps and partial-success semantics.
