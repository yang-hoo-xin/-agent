# Qualified local Patch model selection

`continue-fresh-patch --qualified-model-routing <routing.json>` is an optional
role selector. It consumes existing Patch/Repair execution and verification facts
before constructing the worker. It does not run qualification models, change
permissions, switch providers after failure, or provide an external-model route.
The existing explicit `--ollama-*` path remains available without a qualification
gate. New explicit trials also record the worker identity needed for later
qualification; an unqualified model can therefore still be tested explicitly.

The role is derived by the product entry: an explicit Repair input/verification
selection uses `repair`; other Patch continuations use `initial_patch`. Users do
not supply a role override. Qualified selection can supply the model, context,
output and timeout settings. If an `--ollama-*` value is also supplied, it must
match the selected profile exactly; conflicts are rejected without model sends.

## Configuration and existing owners

The local routing JSON has exactly `schema_version` (value
`qualified_patch_model_routing_v1`) and `routes`. Each supported role maps to one
`qualification_ref`, an existing absolute file path plus its exact SHA-256.
There is no fallback list or persistent profile database.

The qualification document has these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | `patch_model_qualification_v1` |
| `role` | `initial_patch` or `repair` |
| `scope` | Exact `target_mod` from the selected FeatureSpec |
| `profile` | Exact existing `LocalOllamaInitialPatchProfileV1.to_dict()` |
| `model_digest` | Exact Ollama model digest observed during the trials |
| `implementation_sha256` | Producer-recorded worker implementation fingerprint |
| `worker_policy_sha256` | Hash of the existing worker policy |
| `task_suite_ref` | Exact frozen task-definition file reference |
| `attempts` | One `case_id` and exact `attempt_ref` per fixed task |
| `quality_policy` | Existing `QualityGatePolicy`, for `task_success_rate` only |

The task suite has `schema_version=patch_qualification_tasks_v1`, the same
`scope`, and `cases`. Each case has `case_id`, explicit `artifact_store_root` and `workspace_root`,
an exact `feature_spec_ref`, `expected_check_ids`, and `verification_identity`
(`validator_sha256`, `inputs_sha256`, `environment_sha256`, and the recorded
`deterministic_reuse_allowed` value). At least three distinct Feature IDs and
FeatureSpec hashes are required. Repeated attempts do not add tasks.

These are versioned input documents, not proof from a `qualified: true` flag.
The resolver validates their file hashes and recomputes each task result from
the exact attempt, its final behavior report, its complete matrix, and its
Proposal/Review/Dry-run artifacts. The matrix check identities must equal the
fixed task definition, not merely agree with their own shortened summary.
The last retained provider response must match the stored Patch bytes. The
existing native generator and exact-text materializer reconstruct the result
from its fixed baseline; its identity must match both the behavior report and
the matrix. Missing retained baseline or matrix code identity remains pending.
Every required task must pass; a valid schema or deterministic Review cannot
hide a final behavior failure. Retrieval metrics are not reused as Patch scores.

`model_admission` still owns live model-name/digest validation and the local-only
boundary. `QualityGatePolicy` still owns numeric threshold validation.
`ArtifactStore.read` validates artifacts; the original continuation canonical
hash validates terminal receipts. The role selector does not replace these owners.

## Evidence limits and revalidation

New Patch receipts carry `qualification_execution_identity`. Its fingerprint
lists the exact worker, continuation, generator, materializer and Graph source
files; it does not use Git HEAD or documentation hashes. It does not claim to
fingerprint every dependency or the full operating system. Verifier and input
versions belong to the explicit per-task verification identity.

Missing execution records, legacy receipts without worker fingerprints,
incomplete matrices, replayed trials, or version mismatches remain pending.
Final behavior failures are not qualified. Missing qualifications never select
another model. References are checked again before a qualified model generates.
The routing reference participates in the existing attempt identity, preventing
an old explicit run from silently becoming a qualified invocation. Cached calls
still pass current qualification selection before returning their old result,
including callers of the shared continuation API rather than only the CLI.

The selection receipt records the role, scoped task outcomes, denominator,
profile/digest and evidence references. It explicitly grants neither disclosure
nor Apply authority. Existing live-source, exact-diff approval, Build and Runtime
rules remain separate.

The included tests use synthetic production-path receipts and an HTTP transport
stub. They demonstrate the Repair role selector and rejection paths; they do not
qualify any installed real model or establish cross-task model performance.
No production model qualification configuration is shipped by this change.
