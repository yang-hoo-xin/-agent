# Non-authoritative Projection Responsibility Boundary

Status: frozen architecture responsibility decision

Baseline: `2af5e36e73343ff5088ef7c1cb813a5a700335d0`

This decision governs future Coding Agent v0 lineage, diagnostic reconstruction,
Failure Capsule, Langfuse, and UI work. It freezes responsibility before any
shared projection interface is defined. It is not a second implementation queue
and does not authorize a model call, probe, Actual, Repair, Apply, Build, Runtime,
network export, or external disclosure.

## 1. Rejected whole-commit designs

| Commit | Disposition | Reason |
| --- | --- | --- |
| `1275e87e0ec49a8bcd2dec1fe17c2432967b9da5` | `whole_commit_merge: rejected_at_2af5e36`; `original_cherry_pick: do_not_merge` | It recomputes cross-owner failure order, failure chains, claim impact, and execution-authority hints. |
| `7a6c96f7da7a141381ca5c9df87adc5e0071c704` | `whole_commit_merge: rejected_at_2af5e36`; `original_cherry_pick: do_not_merge` | It wraps historical fixtures in hand-authored owner, boundary, conformance, queue, and fresh-Actual decisions. |

The commits remain Git audit evidence. This rejection applies to their current
projection and promotion semantics, not to every integrity primitive or test
input. Selective migration is allowed only through current owner contracts and
new code review. The current consumer count for their public namespaces and
schemas at the baseline is zero.

## 2. Current fact and decision owners

| Owner | Owns | Does not delegate to a projection |
| --- | --- | --- |
| Entry Admission | Entry gate results and its owner-local first-failure fields | Product execution, retry, or Apply decisions |
| Actual execution | Packet/seal validation, receipt, identity consumption, and explicit run authorization | Model-role, Repair, or product-success claims |
| ProductExecution | Platform status, execution disposition, failure stage, blockers, Store/effect records, and completion variant | Fresh-Actual admission or human approval |
| ArtifactStore | Durable Artifact revisions, refs, hashes, inputs, blockers, and trace refs | Graph routing or semantic approval |
| LangGraph StateGraph | Runtime state and conditional routing | Durable claim ownership |
| Build/Runtime owners | Their bound Build or Runtime result and evidence limits | Broader delivery or stable-Agent claims |
| Human decision boundary | Exact-diff approval and other explicit user decisions | Automatic inference from a trace, score, or projection |

Owner-local ordering may be displayed as owner-local ordering. No projection may
create a total order across owners unless an explicit owner-issued causal edge
already records that relationship.

## 3. Projection responsibility

A future projection may:

- copy exact owner-issued fields with their source ref and hash;
- validate ref, hash, schema, path boundary, duplicate identity, and explicit edge shape;
- display owner-local sequences and explicit causal/reference edges;
- report missing, conflicting, or unreadable facts as projection-integrity diagnostics;
- redact sensitive content for a separately authorized sink.

A future projection may not:

- compute a cross-owner first failure or canonical failure order;
- choose a winning status when owners conflict;
- create a product claim or reinterpret a claim's evidence level;
- decide readiness, retry, pause, resume, fresh-Actual status, Repair, Apply, or approval;
- write to the current ArtifactStore or modify owner records;
- become an input to Graph routing, Actual admission, Repair, Apply, or retry;
- treat telemetry delivery success as product success.

Missing or conflicting projection inputs may make only the projection incomplete.
They cannot block or change the product execution that produced those inputs.

## 4. Dependency direction

```text
owner contracts and immutable results
                |
                v
non-authoritative projection
                |
        +-------+-------+
        v               v
 local query/report   telemetry sink
```

The reverse dependency is forbidden. Graph, Actual, Apply, Repair, approval, and
product-result owners must not import or consume the projection or telemetry
implementation. Production code must not import historical test replay runners.

The machine guard is
`tests/unit/test_non_authoritative_projection_boundary.py`. It intentionally does
not ban legitimate owner fields such as `first_failure_stage`, `failure_stage`,
`platform_status`, or `execution_disposition`.

## 5. Selective reuse boundary

The following ideas may be reimplemented after the shared interface is frozen:

- exact hash/ref/path/schema checks;
- missing-reference, hash-conflict, duplicate-relation, no-write, and redaction tests;
- exact owner-issued Artifact refs, terminal refs, and trace events;
- raw fixture hashes and owner-specific regression inputs;
- fake exporter, fail-open export, redaction, and flush tests.

The following must not migrate:

- cross-owner `first_failure`, `failure_chain`, or `claim_impact` derivation;
- replay promotion, `fresh_actual_status`, queue mutation, or authority effects;
- inferred causal edges based on timestamps, filename similarity, or write order;
- production dependencies on private loading helpers from another owner;
- whole-commit cherry-picks of the rejected designs.

## 6. Activation and next gate

No new projection interface or runtime observer is implemented by this decision.
The next serial task is to freeze one minimal, non-authoritative fact and explicit
edge interface that obeys this boundary. Only after that interface checkpoint is
accepted may Thin Lineage, owner test migration, Langfuse export, and read-only
ProjectionRebuild proceed in parallel from the same HEAD.

This decision does not permanently reject complete observability capabilities.
It rejects only implementations that acquire product interpretation or execution
authority outside the existing owners.
