# Non-authoritative Projection Identity V2 Checkpoint

Status: accepted/reviewed/integrated on `codex/rag-capability-mainline`

Accepted source lineage:
`d9c9a65aaccd093ba0bf45453b104fbd4d5a6f1b -> 99c2faa2f651832b8b994d81b2170bfbb15d32fa`

Integrated mainline lineage:
`163595ba3c6658a5e9a3d95128a94f0f0d3149c0 -> fc555a8439642bdb61fc8548ba8d7045cfda9340`

Initial checkpoint parent:
`a79565197e7c5242f5f22b6ff6ddfe75db94f7ed`

Corrective checkpoint parent:
`d9c9a65aaccd093ba0bf45453b104fbd4d5a6f1b`

Responsibility authority:
`docs/audits/NON_AUTHORITATIVE_PROJECTION_RESPONSIBILITY_BOUNDARY_20260830.md`

V1 interface checkpoint:
`docs/audits/NON_AUTHORITATIVE_PROJECTION_INTERFACE_CHECKPOINT_20260830.md`

This checkpoint corrects one representational failure without changing an
owner contract or the accepted Projection V1 interface. It adds a separate,
pure `src.non_authoritative_projection.contracts_v2` module and focused tests.
It creates no Artifact, Graph branch, Approval, Gateway, queue, observer,
exporter, production adapter, production consumer, or execution decision.

## 1. Verified reachable contract counterexample

The current owner contracts permit this complete combination:

1. `ProductExecutionOutputV1.sequence` identifies one ProductExecution-owned
   output occurrence in the enclosing `ProductExecutionResultV1`.
2. `ProductExecutionOutputV1.artifact_ref` identifies the referenced immutable
   Artifact revision. The ProductExecution result contract does not require
   different committed output occurrences to have different
   `ArtifactRef.path` or `ArtifactRef.artifact_hash` values.
3. `ArtifactStore.write_with_result` returns an already valid committed
   revision as `outcome="committed"`, `commit_started=False`, and the same
   `ArtifactRef` when the complete committed identity already exists.
4. `_ProductStoreRecorder._record` appends one independent
   `ProductExecutionStoreAttemptV1` and one independent
   `ProductExecutionOutputV1` for every committed result, including the
   idempotently reused identity.
5. `FactRefV1(owner, fact_ref)` uses only the owner plus Artifact path. Two
   ProductExecution output occurrences with the same path therefore collapse
   to one V1 fact identity even when their owner-local sequences differ.

The V1 identity cannot represent those two legal occurrences in one View:
retaining both causes its duplicate-ref rejection, while retaining one loses
an owner-issued occurrence. Changing ProductExecution, Recorder, or
ArtifactStore would move a projection limitation into an authoritative owner,
so those modules remain unchanged.

The evidence level is a reachable contract counterexample, not an observed
public/default Graph production event. It combines the real
`ArtifactStore.write_with_result` idempotent committed-ref mechanism and its
focused test, the real `_ProductStoreRecorder` and ProductExecution contracts,
and one strictly replayable synthetic composition of those contracts. It does
not claim that a public/default Graph `ProductExecutionResultV1` has physically
emitted the same `patch_proposal` revision twice in one recorded run.

## 2. Independent V2 surface

V2 is available only through the new direct module. The package root
`src.non_authoritative_projection.__init__` is unchanged, so importing the V1
package surface does not upgrade or replace any V1 type.

The V2 module exposes these versioned constants and types:

- `PROJECTION_SCHEMA_VERSION_V2 = "2"`
- `OWNER_FACT_ADMISSION_VERSION_V2 = "owner_fact_admission_v2"`
- `OWNER_FACT_ADMISSION_V2`
- `RELATIONS_V2`
- `RELATION_DIRECTIONS_V2`
- `DIAGNOSTIC_CODES_V2`
- `ArtifactRefV2`
- `FactRefV2`
- `OwnerFactV2`
- `EdgeReporterV2`
- `ExplicitEdgeV2`
- `ProjectionDiagnosticV2`
- `ProjectionViewV2`
- the existing `ProjectionContractError`, imported only from the package's V1
  contract module

The closed admission table, in exact row and field order, is:

| `owner` | `fact_type` | payload schema | result scope mode | sequence mode |
| --- | --- | --- | --- | --- |
| `artifact_store` | `artifact_revision_v1` | `1.0` | `unavailable` | `unavailable` |
| `product_execution` | `product_execution_output_v1` | `1.0` | `product_execution_result` | `required` |

Callers cannot register another row by rebinding the public constant.

`owner` and `fact_type` are Projection V2 closed-admission labels. They are not
native owner-issued fields of `ProductExecutionOutputV1`, `ArtifactRef`, or
`ArtifactEnvelope`. The current exact owner-contract sources are limited to:

| Projection V2 field | exact current source |
| --- | --- |
| `run_id` | enclosing `ProductExecutionResultV1.run_id` |
| `request_id` | enclosing `ProductExecutionResultV1.request_id` |
| `owner_sequence` for a ProductExecution occurrence | `ProductExecutionOutputV1.sequence` |
| `artifact_ref.feature_id` | `ProductExecutionOutputV1.artifact_ref.feature_id` / matching `ArtifactRef.feature_id` |
| `artifact_ref.artifact_type` | `ProductExecutionOutputV1.artifact_ref.artifact_type` / matching `ArtifactRef.artifact_type` |
| `artifact_ref.path` | `ProductExecutionOutputV1.artifact_ref.path` / matching `ArtifactRef.path` |
| `artifact_ref.artifact_hash` | `ProductExecutionOutputV1.artifact_ref.artifact_hash` / matching `ArtifactRef.artifact_hash` and readback `ArtifactEnvelope.artifact_hash` |
| `payload_sha256` | the same referenced `ArtifactRef.artifact_hash`; not an occurrence-record hash |
| `payload_schema_version` | matching validated output-readback `ArtifactEnvelope.schema_version` |

The Projection labels add no owner authority and do not assert that the owner
contracts natively serialize those labels.

## 3. Exact serialized fields

`ArtifactRefV2` is the structured copy of the exact owner-issued `ArtifactRef`.
Its serialized fields are:

1. `feature_id`
2. `artifact_type`
3. `path`
4. `artifact_hash`

`FactRefV2` is the complete V2 edge endpoint and fact identity. Its serialized
fields are:

1. `owner`
2. `fact_type`
3. `run_id`
4. `request_id`
5. `owner_sequence`
6. `artifact_ref`

`OwnerFactV2` has exactly:

1. `schema_version`
2. `fact`
3. `payload_sha256`
4. `payload_schema_version`

`OwnerFactV2.payload_sha256` must equal
`OwnerFactV2.fact.artifact_ref.artifact_hash`. The payload schema must equal the
closed admission row's exact `1.0`.

For `product_execution/product_execution_output_v1`, that
`payload_sha256` currently binds the referenced Artifact payload. It is not a
hash of the complete `ProductExecutionOutputV1` occurrence record, the enclosing
result, or the structured occurrence identity. Scope and sequence are preserved
as explicit identity fields; this checkpoint makes no complete occurrence
content-integrity claim.

`EdgeReporterV2` has exactly:

1. `fact`
2. `payload_sha256`
3. `owner_sequence`

`ExplicitEdgeV2` has exactly:

1. `schema_version`
2. `relation`
3. `source`
4. `target`
5. `reporter`

Both edge endpoints and `reporter.fact` carry the complete `FactRefV2` rather
than a path-only reference. Construction requires `reporter.fact == source`.
ArtifactStore revisions have no owner sequence and cannot be a source or
reporter. `EdgeReporterV2` itself rejects every sequence-unavailable admission,
including direct construction and `from_dict`; this does not defer solely to
`ExplicitEdgeV2`. For a sequence-required ProductExecution fact, the reporter's
separate `owner_sequence` and `payload_sha256` may remain inconsistent long
enough for `ProjectionViewV2` to emit the exact item-level mismatch diagnostic.

`ProjectionDiagnosticV2` preserves the V1 item-level diagnostic structure with
complete V2 fact identities:

1. `schema_version`
2. `code`
3. `edge_sha256`
4. `primary_fact`
5. `related_fact`
6. `fact_payload_sha256`
7. `reporter_payload_sha256`
8. `fact_owner_sequence`
9. `reporter_owner_sequence`

`ProjectionViewV2` has exactly:

1. `schema_version`
2. `facts`
3. `edges`
4. `diagnostics`

## 4. Identity keys and binding invariant

The complete ProductExecution occurrence identity is the structured tuple:

```text
(
  owner="product_execution",
  fact_type="product_execution_output_v1",
  run_id,
  request_id,
  owner_sequence,
  artifact_ref=(feature_id, artifact_type, path, artifact_hash)
)
```

`run_id` and `request_id` are copied as separate exact fields from the enclosing
`ProductExecutionResultV1`; they are not concatenated with each other or with
the Artifact path. `owner_sequence` is copied from
`ProductExecutionOutputV1.sequence`. The nested `artifact_ref` is the referenced
object and remains byte-for-byte independent from occurrence sequence.

The ProductExecution occurrence slot is:

```text
(owner, fact_type, run_id, request_id, owner_sequence)
```

Across all View facts plus every edge source, target, and reporter endpoint,
one occurrence slot may map to exactly one `ArtifactRefV2`. A second mapping to
a different feature, Artifact type, path, or hash fails closed before View
construction. An exact repeated complete occurrence identity is rejected as a
duplicate fact.

The ArtifactStore revision identity is:

```text
(
  owner="artifact_store",
  fact_type="artifact_revision_v1",
  run_id=null,
  request_id=null,
  owner_sequence=null,
  artifact_ref=(feature_id, artifact_type, path, artifact_hash)
)
```

It has no fabricated run, request, or sequence. One revision fact may be the
target of any number of distinct source-bound ProductExecution occurrence
edges.

`ProjectionViewV2` explicitly supports facts from multiple
`ProductExecutionResultV1` values. Equal owner sequence and equal Artifact
identity in different exact run/request scopes remain different fact
identities. Cross-run separation is therefore a mechanical contract, not a
caller convention.

## 5. Rebuild, diagnostics, and non-authority

`ProjectionViewV2.rebuild(facts, edges)` validates unsorted inputs, rejects
duplicate fact identities and exact duplicate edges, enforces the occurrence
binding invariant, then sorts only for canonical serialization. Fact and edge
sort keys use their complete canonical identity bytes. This order is not event,
causal, cross-owner, failure, claim, or priority order.

Canonical bytes remain compact UTF-8 JSON with exact field order,
`ensure_ascii=False`, `allow_nan=False`, and separators `(',', ':')`.
`canonical_sha256()` hashes those bytes as 64 lowercase hexadecimal characters.
Strict `from_dict` rejects unknown or reordered fields, non-canonical fact/edge/
diagnostic collection order, malformed hashes and scalar shapes, unsupported
versions, duplicate facts/edges/diagnostics, unadmitted pairs, and diagnostics
that do not exactly regenerate from the complete inputs.

The V2 diagnostic codes are only:

- `missing_source_fact`
- `missing_target_fact`
- `missing_reporter_fact`
- `reporter_payload_sha256_mismatch`
- `reporter_owner_sequence_mismatch`
- `explicit_conflict`

A reporter hash or sequence mismatch remains an item-level diagnostic. A valid
`conflicts_with` edge retains both facts and adds `explicit_conflict`; it does
not select a winner. Missing facts make only the projection incomplete and do
not block or change the product result.

V2 contains no aggregate integrity or product status, first failure, failure
chain, claim, retry, authority, queue, promotion, pause/resume, Apply, Repair,
or recovery field or decision.

## 6. V1 compatibility

This checkpoint does not modify:

- `src/non_authoritative_projection/__init__.py`
- `src/non_authoritative_projection/contracts.py`
- either accepted V1 test file
- the ProductExecution, Recorder, ArtifactStore, Graph, Actual, Apply, Repair,
  UI, Runtime, or Langfuse implementation

V1 types retain their exact API, serialized bytes, hashes, and strict parsing.
`ProjectionViewV1.from_dict` does not accept a V2 View, and
`ProjectionViewV2.from_dict` does not accept a V1 View. There is no automatic
conversion or migration. V1 remains available for exact historical API/bytes/
read compatibility, but new Thin Lineage producers must use the V2
occurrence-aware identity rather than the V1 path-only identity.

Within the current repository, current Artifact registry, and the worktree and
consumer references inspected for this page, no production projection consumer
or persistent Projection Artifact was found. This checkpoint creates neither
one. This bounded check does not claim that repository-external data, deleted
data, another host, or uninspected history contains no V1 projection data.

## 7. Verification evidence

All commands use local unit contracts and repository test doubles. No model,
network, product preflight, packet, Actual, external Build, Apply, Repair,
Runtime, game process, game-directory write, or external disclosure occurred.

| command | result |
| --- | --- |
| `python -m pytest tests/unit/test_non_authoritative_projection.py tests/unit/test_non_authoritative_projection_v2.py tests/unit/test_product_execution_projection_v2.py tests/unit/test_non_authoritative_projection_boundary.py -q` | `61 passed, 1 warning` |
| `python -m pytest tests/unit/test_product_execution.py tests/unit/test_artifact_store.py::test_write_with_result_reuses_preexisting_committed_identity_without_writes -q` | `108 passed, 1 warning` |

These are local test-double results from the original implementation page and
the macro read-only review page's reproduction. This integration page did not
rerun either command. The results are not model, Patch, product, Build, or
Runtime success.

The warning in both commands is the environment's existing `jieba` import of
the deprecated `pkg_resources` API; it is not a projection or owner-contract
test failure.

The focused V2 integration fixture builds a strictly replayable synthetic
`ProductExecutionResultV1` composition. Its real Recorder contract retains two committed
`patch_proposal` outputs with different owner sequences and one exact
ArtifactRef; the second Store result has `commit_started=False`. The V2 View
retains both occurrences, two source-bound `references` edges, and one shared
ArtifactStore revision target without mutating the owner result. This fixture
proves contract representability and replay, not a physical duplicate revision
from a public/default Graph execution.

## 8. Claim boundary

This evidence proves only the tested V2 closed admission, structured occurrence
and revision identities, same-scope sequence binding invariant, multi-result
scope separation, exact source/reporter binding, duplicate rejection, stable
canonical rebuild, strict parsing, item-level diagnostics, conflict
non-adjudication, V1 isolation, reverse dependency guard, and pure post-owner
projection behavior.

It does not prove owner payload truth, a production adapter or consumer,
historical Projection rebuild, export, telemetry delivery, model behavior,
Patch success, product success, Build success, Runtime behavior, approval,
retry, promotion, queue state, or execution authority.

## 9. Integrated restart and shared-file boundary

The former A/B/C/D worktrees stopped after the V1 path-only identity gap was
established. They produced no accepted commit, and their staged or untracked
files are not inputs to this mainline integration.

Fresh Thin Lineage, owner-test migration, Langfuse exporter, and
ProjectionRebuild worktrees must be created from one same final mainline HEAD
that contains both mapped V2 commits and the docs-only integration state. The
occurrence-aware V2 identity is their shared interface. They must treat these
V2 shared surfaces as read-only:

- `src/non_authoritative_projection/contracts_v2.py`
- `tests/unit/test_non_authoritative_projection_v2.py`
- `tests/unit/test_product_execution_projection_v2.py`
- `docs/audits/NON_AUTHORITATIVE_PROJECTION_IDENTITY_V2_CHECKPOINT_20260830.md`

Every V1 no-edit surface listed in section 9 of
`docs/audits/NON_AUTHORITATIVE_PROJECTION_INTERFACE_CHECKPOINT_20260830.md`
also remains read-only. A page that finds either shared interface insufficient
must stop and return the exact missing representation; it may not revise those
surfaces in its own worktree.

This integration creates no A/B/C/D page and no fresh Patch-only probe. The
probe still requires separate authorization and remains uncreated. `EVID-005`
and both false Internal Alpha hard gates are unchanged. No Actual or actual16,
model, Apply, Build, Runtime, Dense/RRF/reranker, Self-RAG, PDF, UI, or other
backlog work is activated.

## 10. ProductExecution scope compatibility correction (2026-08-31)

This correction starts from exact detached parent
`ccfd8e4a0ab8ffe479e620dba5dc8ad2bb0755d0`. It is the shared Projection V2
interface's last field-level compatibility closure.

### 10.1 Exact owner rule and lossless scope representation

`ProductExecutionResultV1.from_dict` validates both `run_id` and `request_id`
through the current owner function `_require_non_empty`. Its exact rule is:

```text
type(value) is str and bool(value.strip())
```

The function returns the original string. It uses `strip()` only for the
non-empty predicate; it does not return the stripped value.

Projection V2 now mirrors that rule only for `FactRefV2.run_id` and
`FactRefV2.request_id` when the closed admission row has
`scope_mode=product_execution_result`. The dedicated
`_require_product_execution_scope_text` function returns the original string.
It does not trim, normalize, rewrite, concatenate, or case-fold the value.
This is owner-contract compatibility, not identifier cleaning.

Accepted scope values preserve their exact Unicode character sequence.
Canonical compact UTF-8 JSON uses the required JSON escapes for tab and
newline, then decodes to the exact original string; reparsing and re-emitting
produces the same canonical bytes. `ArtifactRefV2` and every other V2 text
field continue to use the existing strict `_require_text` rule. That rule
still rejects leading or trailing whitespace and ASCII control characters.

### 10.2 Owner-versus-V2 differential matrix

Every value below is applied independently to `run_id` and `request_id`. The
test first constructs a valid current-owner result, replaces exactly one scope
field, and parses it through `ProductExecutionResultV1.from_dict`. It parses
the same value through `FactRefV2.from_dict` and compares the two outcomes.

| class | exact Python values | ProductExecution owner | Projection V2 |
| --- | --- | --- | --- |
| leading/trailing ordinary space | `" leading_scope"`, `"trailing_scope "` | accept, preserve | accept, preserve |
| tab | `"\tleading_scope"`, `"trailing_scope\t"`, `"scope\tvalue"` | accept, preserve | accept, preserve |
| newline before/after/internal | `"\nleading_scope"`, `"trailing_scope\n"`, `"scope\nvalue"` | accept, preserve | accept, preserve |
| Unicode non-ASCII | `"运行_Δ_日本語"` | accept, preserve | accept, preserve |
| Unicode whitespace around non-empty text | `"\u3000scope\u00a0"` | accept, preserve | accept, preserve |
| empty or whitespace-only strings | `""`, `"   "`, `"\t\t"`, `"\n\n"`, `"\u3000\u00a0\u2003"` | reject | reject |
| non-`str` values | `True`, `b"scope"`, `None`, `1` | reject | reject |

For every accepted value, the test proves exact-value and stable canonical-byte
roundtrips through the current owner result, `FactRefV2`, `OwnerFactV2`, and
`ProjectionViewV2`. Five additional cases prove owner-compatible whitespace or
control-bearing strings still fail when placed in `ArtifactRefV2.feature_id`.

### 10.3 Unchanged semantics and stop boundary

This correction does not change the general `_require_text` function,
`ArtifactRefV2`, closed owner/fact-type admission, ArtifactStore null scope,
sequence identity, edge or reporter behavior, diagnostics, rebuild ordering,
or any V1 surface. It adds no owner, relation, diagnostic, Artifact, consumer,
control decision, or execution behavior. ProductExecution, ArtifactStore,
Graph, Actual, Apply, Repair, Build, Runtime, and the former A/B/C/D worktrees
remain unchanged.

If a later differential matrix exposes another owner-legal state that the
shared V2 representation cannot express losslessly, the next action is to
re-audit the V2 abstraction and its information model. No further
field-by-field compatibility patch is authorized by this checkpoint.

### 10.4 Verification evidence

All commands remained local and used repository tests or test doubles. No
model, network, Actual, Build, Apply, Repair, Runtime, game process, or external
disclosure occurred.

| command | result |
| --- | --- |
| `python -m pytest tests/unit/test_non_authoritative_projection_v2_scope_compatibility.py -q` | `43 passed` |
| `python -m pytest tests/unit/test_non_authoritative_projection.py tests/unit/test_non_authoritative_projection_v2.py tests/unit/test_product_execution_projection_v2.py tests/unit/test_non_authoritative_projection_boundary.py -q` | `61 passed, 1 warning` |
| `python -m pytest tests/unit/test_product_execution.py tests/unit/test_artifact_store.py::test_write_with_result_reuses_preexisting_committed_identity_without_writes -q` | `108 passed, 1 warning` |
| `git diff --check` | exit `0`; no whitespace errors; working-copy LF-to-CRLF warnings only |

Both warnings are the existing `jieba` import of deprecated `pkg_resources`;
they are not projection, scope, owner-contract, or ArtifactStore test failures.
