# Non-authoritative Projection Interface Checkpoint

Status: accepted corrective code/test checkpoint integrated on
`codex/rag-capability-mainline`

Accepted source lineage:
`4469279de886f5eba22d451dd215837c3e8fc389 -> 889ecd54e51db4d0882df0c4cc2b0d66850fb167 -> be8a91077e0ec28fdbf72ee5d5fa063f700ed41a`

Integrated mainline lineage:
`c2c8e31abaed1b795d61c5b62e5d39defcb984da -> 7576d86853f77acba6b73f5ace07e4ccb3755297 -> 36d51d897ab6d329c5efac7d6012d8837d9cd772`

Responsibility authority:
`docs/audits/NON_AUTHORITATIVE_PROJECTION_RESPONSIBILITY_BOUNDARY_20260830.md`

This checkpoint freezes one read-only, rebuildable interface for Thin Lineage,
owner-test migration, a future Langfuse exporter, and ProjectionRebuild. It does
not merge either rejected whole-commit design and does not create an Artifact,
Graph branch, Approval, Gateway, queue, fact owner, production consumer, or
execution decision.

## 1. Exact public surface and owner-fact admission

The independent package is `src.non_authoritative_projection`. It uses only the
Python standard library and its own modules. Its public surface is:

- `FactRefV1`
- `OwnerFactV1`
- `EdgeReporterV1`
- `ExplicitEdgeV1`
- `ProjectionDiagnosticV1`
- `ProjectionViewV1`
- `ProjectionContractError`
- the frozen admission, relation, direction, diagnostic-code, and schema-version constants

`OwnerFactV1` has exactly these fields, in this serialized order:

1. `schema_version`
2. `owner`
3. `fact_type`
4. `fact_ref`
5. `payload_sha256`
6. `payload_schema_version`
7. `owner_sequence`

It contains no owner payload and no extensible metadata map. Admission is the
closed, versioned `owner_fact_admission_v1` table:

| `owner` | `fact_type` | payload schema | sequence mode |
| --- | --- | --- | --- |
| `artifact_store` | `artifact_revision_v1` | exact `1.0` | `unavailable`; serialized only as `null`; cannot report an edge |
| `product_execution` | `product_execution_output_v1` | exact `1.0` | `required`; exact integer `>= 0` |

Callers cannot register a pair. `OwnerFactV1` validates the table in its
constructor and `from_dict`; `FactRefV1` rejects owners outside the table.
Unknown owners, responsibility owners not admitted by this checkpoint,
cross-paired fact types, status/claim-like fact types, wrong payload schema,
and invented/missing sequence values fail before a View can accept them.

### 1.1 Exact current owner field sources

`product_execution/product_execution_output_v1` is admitted only for one
Artifact output contained in a completely returned and strictly replayable
`ProductExecutionResultV1`:

| projection field | current owner source |
| --- | --- |
| `fact_ref` | `ProductExecutionOutputV1.artifact_ref.path` |
| `payload_sha256` | `ProductExecutionOutputV1.artifact_ref.artifact_hash` |
| `payload_schema_version` | the matching validated output-readback envelope's `schema_version` |
| `owner_sequence` | `ProductExecutionOutputV1.sequence` |

The current ProductExecution strict replay already binds the output ref/hash to
the matching output-readback envelope. The projection test copies these fields
only after `execute_product_execution` returns.

`artifact_store/artifact_revision_v1` is admitted from one immutable revision:

| projection field | current owner source |
| --- | --- |
| `fact_ref` | `ArtifactRef.path` |
| `payload_sha256` | `ArtifactRef.artifact_hash`, equal to `ArtifactEnvelope.artifact_hash` |
| `payload_schema_version` | `ArtifactEnvelope.schema_version` |
| `owner_sequence` | `null`; ArtifactStore exposes no revision-local integer sequence |

The missing ArtifactStore sequence is represented, not fabricated. The
admission table makes this pair endpoint-only, so a caller cannot put `0` in
the field and use it as an edge reporter.

## 2. Explicit exclusions

The table is deliberately smaller than the responsibility-owner list:

| excluded owner/fact | exact missing representation |
| --- | --- |
| `EntryAdmissionResultV1` / `EntryAdmissionRunV1` | no exact owner-local integer sequence tied to the receipt ref/hash/schema |
| `ActualRunResultV1` | journal ref/hash exist, but the result has no contract/schema version and no exact owner-local integer sequence; `actual_attempt_id` is not parsed into one |
| top-level `ProductExecutionResultV1` | no exact fact ref, payload hash, or owner-local sequence |
| LangGraph `TraceEvent` / `ModAgentState` | no single owner-issued schema, payload hash, and owner-local sequence tuple |
| `BuildResult` | no owner-issued fact ref, payload hash, schema version, or owner-local sequence |
| Runtime evidence payload builders | no frozen Runtime owner-result contract carrying the complete tuple |
| human exact-diff and authority decisions | no current owner record carrying the complete ref/hash/schema/owner-local sequence tuple |

No fixture value, concatenated identity, parsed numeric suffix, status, claim,
or default `0` substitutes for these missing owner fields.

## 3. Explicit edge semantics

Each endpoint is an exact `FactRefV1` containing `owner` and `fact_ref`.
`EdgeReporterV1` binds the source fact's full `FactRefV1`, exact
`payload_sha256`, and exact `owner_sequence`.

The interface mechanically enforces `reporter.fact == source`. There is no
third-party reporter form. Source is therefore both the directional source
endpoint and the fact that explicitly signs the relation; target is only the
directional target endpoint. Rebuild checks that source/reporter and target
facts exist and that reporter hash and sequence equal the admitted source fact.

The finite relations and exact directions are:

| `relation` | direction |
| --- | --- |
| `references` | source is the reporter fact explicitly signing source -> target as a reference |
| `derived_from` | source is the reporter fact explicitly signing source as derived from target |
| `caused_by` | source is the reporter fact explicitly signing source as caused by target |
| `conflicts_with` | source is the reporter fact explicitly signing a conflict with target; direction conveys no priority |

No relation is inferred from a timestamp, input order, write order, path,
filename, similar identifier, owner sequence, or payload hash.

## 4. Rebuild, serialization, and diagnostics

`ProjectionViewV1.rebuild(facts, edges)` treats collection order as
non-semantic, rejects duplicate fact refs and duplicate edges, sorts only for
serialization, and derives every diagnostic from the complete supplied facts
and edges. Facts sort by `(owner, fact_ref)`. Edges sort by their exact endpoint,
relation, and source-reporter binding fields. Diagnostics sort by canonical
bytes.

These sort orders are not an event order, cross-owner order, causal order,
failure order, or priority order. `owner_sequence` is never compared between
different owners.

Canonical bytes are compact UTF-8 JSON with exact contract field order,
`ensure_ascii=False`, `allow_nan=False`, and separators `(',', ':')`.
`canonical_sha256()` hashes those bytes as 64 lowercase hexadecimal
characters. `from_dict` accepts only canonical field and collection order.
Unknown fields, reordered fields or collections, duplicate refs, duplicate
edges, duplicate diagnostics, malformed hashes, unsupported versions,
unadmitted owner/fact pairs, unsupported relations, and diagnostics not exactly
regenerated from the inputs all fail explicitly.

The diagnostic codes remain item-level only:

- `missing_source_fact`
- `missing_target_fact`
- `missing_reporter_fact`
- `reporter_payload_sha256_mismatch`
- `reporter_owner_sequence_mismatch`
- `explicit_conflict`

A valid cross-owner `conflicts_with` edge retains both facts and produces one
`explicit_conflict` diagnostic. It does not select a winner. There is no
aggregate projection-integrity result, product status, route result, retry
decision, failure chain, first-failure result, claim-impact result, or
authorization field.

## 5. No observer and no production consumer

The synchronous ProductExecutor callback added by the original checkpoint is
removed. `execute_product_execution` has no projection/callback parameter and
`src.mod_agent.product_executor` does not import this package. An arbitrary
callable could capture Store, Graph, files, network clients, or process-control
capabilities through a closure; copying only the result object cannot prove
capability or Store isolation.

The invariance test instead performs this sequence:

```text
execute_product_execution returns completely
-> copy exact fields from current owner contracts into admitted facts
-> snapshot the complete ProductExecutionResult and Store revisions
-> call pure ProjectionViewV1.rebuild for normal input
-> call pure ProjectionViewV1.rebuild for missing input
-> call pure ProjectionViewV1.rebuild for cross-owner conflict input
-> compare the unchanged owner result, Graph count, Store counters, refs, paths, and bytes
```

There is no production consumer, callback, file writer, network exporter, or
runtime integration in this checkpoint.

## 6. Dependency and capability isolation

The dependency direction is:

```text
owner contracts / immutable owner results
                    |
       external owner-specific adapter
                    v
src.non_authoritative_projection
                    |
          read-only future consumers
```

`src.mod_agent` remains on the forbidden side of the reverse dependency guard.
The guard resolves absolute and relative imports across every current and
future Python module under `src/mod_agent`; it does not reject the separate
existing `src.observability` package.

The projection package's dependency allowlist contains only `__future__`,
`collections`, `dataclasses`, `hashlib`, `json`, `typing`, and its own package.
It cannot import Graph, Actual execution, ArtifactStore, ProductExecution,
Repair, Apply, UI, Langfuse, tests, or another product module.

## 7. Verification evidence

All commands use repository test doubles. No real model, network, product
preflight, packet, Actual, Build, Apply, Repair, or Runtime operation is
started.

| command | result |
| --- | --- |
| `python -m pytest tests/unit/test_non_authoritative_projection.py tests/unit/test_non_authoritative_projection_boundary.py tests/unit/test_product_execution.py -k "non_authoritative or external_post_return or no_projection_callback" -q` | `42 passed, 105 deselected` |
| `python -m pytest tests/unit/test_product_execution.py -q` | `107 passed` |
| `python -m pytest tests/unit/test_workflow_graph.py -q` | `135 passed` |

The post-return test snapshots complete ProductExecutionResult canonical bytes,
terminal, blockers, Store-attempt sequence, effect-event sequence, every output
Artifact ref/hash, Graph invocation count, Store read/write counters, and each
immutable revision's exact path and complete bytes. All three pure rebuilds
leave the snapshot byte-for-byte equal.

## 8. Claim boundary

This evidence proves only the tested admission table, strict parsing,
deterministic rebuild/serialization, mechanical item diagnostics, conflict
non-adjudication, reverse dependency guard, and post-return no-mutation
behavior. It does not prove owner payload truth, a production adapter, export,
telemetry delivery, historical rebuild, or any product, Build, Runtime,
approval, retry, or execution decision.

## 9. Shared-file no-edit rule for the four later pages

Thin Lineage, owner-test migration, Langfuse export, and ProjectionRebuild must
each start in an independent worktree from the same final mainline HEAD that
contains this accepted checkpoint and its docs-only integration state. They
must treat these shared surfaces as read-only:

- `docs/audits/NON_AUTHORITATIVE_PROJECTION_RESPONSIBILITY_BOUNDARY_20260830.md`
- `src/non_authoritative_projection/__init__.py`
- `src/non_authoritative_projection/contracts.py`
- `tests/unit/test_non_authoritative_projection.py`
- `tests/unit/test_non_authoritative_projection_boundary.py`
- the post-return invariance tests in `tests/unit/test_product_execution.py`
- this audit document

They also must not modify existing owner or control contracts to accommodate
the interface:

- `src/mod_agent/entry_admission.py`
- `src/mod_agent/actual_execution.py`
- `src/mod_agent/product_execution.py`
- `src/mod_agent/product_executor.py`
- `src/mod_agent/artifacts/**`
- `src/mod_agent/workflow/**`
- `src/mod_agent/build/**`
- `src/mod_agent/runtime/**`
- `src/mod_agent/execution/**`
- `src/mod_agent/repair/**`
- `src/mod_agent/edit_authority_capabilities.py`

Later pages may add owner-specific adapters, fixtures, exporters, or rebuild
logic outside these shared surfaces. If one page finds the frozen interface
insufficient, it must stop and return the exact missing representation to the
macro review page. It must not revise the shared interface, weaken a guard,
modify an owner contract, or create a divergent copy.
