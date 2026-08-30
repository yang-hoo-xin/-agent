# Non-authoritative Projection Interface Checkpoint

Status: code/test checkpoint awaiting macro-page review

Implementation base: `d6753f50aa879408dc1adc345e0a5c3c6c31589e`

Responsibility authority:
`docs/audits/NON_AUTHORITATIVE_PROJECTION_RESPONSIBILITY_BOUNDARY_20260830.md`

This checkpoint freezes one read-only, rebuildable interface for Thin Lineage,
owner-test migration, a future Langfuse exporter, and ProjectionRebuild. It does
not merge either rejected whole-commit design and does not create an Artifact,
Graph branch, Approval, Gateway, queue, fact owner, or execution decision.

## 1. Package and exact public surface

The independent package is `src.non_authoritative_projection`. It uses only the
Python standard library and its own modules. Its public surface is:

- `FactRefV1`
- `OwnerFactV1`
- `EdgeReporterV1`
- `ExplicitEdgeV1`
- `ProjectionDiagnosticV1`
- `ProjectionViewV1`
- `ProjectionContractError`
- the frozen relation, direction, diagnostic-code, and schema-version constants

`OwnerFactV1` has exactly these fields, in this serialized order:

1. `schema_version`
2. `owner`
3. `fact_type`
4. `fact_ref`
5. `payload_sha256`
6. `payload_schema_version`
7. `owner_sequence`

It contains no owner payload and no extensible metadata map. `owner`,
`fact_type`, and `payload_schema_version` are exact lowercase schema tokens.
The shared package does not register, translate, or reinterpret their values;
each future owner-specific adapter must copy its exact owner-issued identifiers.
This prevents the projection package from becoming a second owner taxonomy.

An owner fact is unique only by `owner` plus `fact_ref`. A duplicate pair is a
contract error even when all other bytes match. `owner_sequence` is interpreted
only within the named owner.

## 2. Explicit edges

Each endpoint is an exact `FactRefV1` containing `owner` and `fact_ref`.
`EdgeReporterV1` binds the issuing fact's full `FactRefV1`, exact
`payload_sha256`, and exact `owner_sequence`. Rebuild checks that source, target,
and reporter facts exist and that the reporter hash and sequence equal the
referenced owner fact.

The finite relations and directions are:

| `relation` | direction |
| --- | --- |
| `references` | source is the owner fact containing an explicit reference to target |
| `derived_from` | source is the owner fact explicitly produced from target |
| `caused_by` | source is the owner fact explicitly declaring target as its cause |
| `conflicts_with` | source is explicitly reported as conflicting with target; direction conveys no priority |

No relation is inferred from a timestamp, input order, write order, path,
filename, similar identifier, owner sequence, or payload hash.

## 3. Rebuild, serialization, and diagnostics

`ProjectionViewV1.rebuild(facts, edges)` treats collection order as
non-semantic, rejects duplicate fact refs and duplicate edges, sorts only for
serialization, and derives every diagnostic from the complete supplied facts
and edges. Facts sort by `(owner, fact_ref)`. Edges sort by their exact endpoint,
relation, and reporter binding fields. Diagnostics sort by their canonical
bytes.

These sort orders are not an event order, cross-owner order, causal order,
failure order, or priority order. `owner_sequence` is never compared between
different owners.

Canonical bytes are compact UTF-8 JSON with the exact contract field order,
`ensure_ascii=False`, `allow_nan=False`, and separators `(',', ':')`.
`canonical_sha256()` hashes those bytes as 64 lowercase hexadecimal
characters. `from_dict` accepts only the canonical field and collection order.
Unknown fields, reordered fields or collections, duplicate refs, duplicate
edges, duplicate diagnostics, malformed hashes, unsupported versions,
unsupported owner/fact pairs, unsupported relations, and diagnostics not
exactly regenerated from the inputs all fail explicitly.

The only diagnostic codes are:

- `missing_source_fact`
- `missing_target_fact`
- `missing_reporter_fact`
- `reporter_payload_sha256_mismatch`
- `reporter_owner_sequence_mismatch`
- `explicit_conflict`

A valid `conflicts_with` edge retains both facts and produces one
`explicit_conflict` diagnostic. It does not select a winner. Missing and
reporter-mismatch diagnostics describe only this read model. There is no
aggregate projection-integrity result, product status, route result, retry
decision, failure chain, first-failure result, claim-impact result, or
authorization field.

## 4. Optional ProductExecution observer seam

Zero consumers alone cannot prove behavior when a consumer is later attached,
so `execute_product_execution` now has the optional keyword-only parameter:

```python
result_observer: Callable[[ProductExecutionResultV1], object] | None = None
```

The executor first finishes Graph invocation, Store operations, output
readback, product validation, variant classification, and
`project_product_execution_result`. It then deep-copies the complete result
dictionary and requires `ProductExecutionResultV1.from_dict` to replay that
copy before invoking the observer. The callback receives only that deeply
separated result object. It receives no Store, Graph, adapters, Runner, route,
or permission object.

The callback return value is ignored. Ordinary `Exception` is fail-open.
`KeyboardInterrupt` and `SystemExit` are not swallowed. After the observer call,
the executor's only remaining statement returns the original frozen machine
result. No production observer is configured by this checkpoint, and the
checkpoint performs no observer network or filesystem I/O.

## 5. Dependency and capability isolation

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

`src.mod_agent` dynamically remains on the forbidden side of the reverse
dependency guard. The generic observer seam does not import the projection
package. The guard resolves absolute and relative imports across every current
and future Python module under `src/mod_agent`. Its prefix matcher does not
reject the existing, separate `src.observability` package.

The projection package's dependency allowlist contains only `__future__`,
`collections`, `dataclasses`, `hashlib`, `json`, `typing`, and its own package.
It therefore cannot import Graph, Actual execution, ArtifactStore, Repair,
Apply, UI, Langfuse, tests, or any other product module.

## 6. Verification evidence

All commands ran locally with repository test doubles. No real model, network,
product preflight, packet, Actual, Build, Apply, Repair, or Runtime operation was
started.

| command | result |
| --- | --- |
| `python -m pytest tests/unit/test_non_authoritative_projection.py tests/unit/test_non_authoritative_projection_boundary.py tests/unit/test_product_execution.py -k "non_authoritative or result_observer" -q` | `32 passed, 105 deselected` |
| `python -m pytest tests/unit/test_product_execution.py -q` | `112 passed` |
| `python -m pytest tests/unit/test_workflow_graph.py -q` | `135 passed` |
| `python -m pytest tests/unit/test_mod_agent_cli.py::test_cli_run_request_uses_real_public_product_executor_and_graph tests/unit/test_mod_agent_cli.py::test_cli_run_request_real_public_product_executor_compile_success tests/unit/test_mod_agent_cli.py::test_cli_run_request_real_public_product_executor_runtime_success -q` | `3 passed` |

Observer invariance compares an unconfigured observer with successful,
arbitrary-return, ordinary-exception, and deep-copy-mutation observers. The
test freezes the existing owner-generated trace UUIDs so the two independent
Graph runs have the same owner inputs; it does not remove or normalize any
ProductExecutionResult field. Canonical result bytes, terminal, blockers,
Store-attempt sequence, effect-event sequence, Artifact revision refs/hashes,
and immutable revision file set are equal in every mode. Runtime counters also
show one Graph invocation and no Store read/write or Graph invocation after the
observer boundary.

## 7. Claim boundary

This evidence proves the tested in-memory contract, strict parsing,
deterministic rebuild/serialization, mechanical diagnostics, conflict
non-adjudication, dependency guards, and observer isolation. It does not prove
that any owner payload bytes are available or semantically true, that a future
export succeeds, that telemetry is delivered, that historical data can be
rebuilt, or that any product, Build, Runtime, approval, retry, or execution
decision is valid.

## 8. Shared-file no-edit rule for the four later pages

Thin Lineage, owner-test migration, Langfuse export, and ProjectionRebuild must
start from the same accepted checkpoint and treat these shared surfaces as
read-only:

- `src/non_authoritative_projection/__init__.py`
- `src/non_authoritative_projection/contracts.py`
- `tests/unit/test_non_authoritative_projection.py`
- `tests/unit/test_non_authoritative_projection_boundary.py`
- the `_observe_product_execution_result` helper, `result_observer` parameter,
  and final observer/return statements in `src/mod_agent/product_executor.py`
- the `test_result_observer_*` tests and their comparison helpers in
  `tests/unit/test_product_execution.py`
- this audit document

Later pages may add owner-specific adapters, fixtures, exporters, or rebuild
logic outside those shared surfaces. If one page finds the frozen interface
insufficient, it must stop and return the exact missing representation to the
macro review page. It must not locally revise the interface, weaken a guard, or
create a divergent copy.
