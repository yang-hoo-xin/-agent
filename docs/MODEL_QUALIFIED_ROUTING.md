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

## Fixed real-source task preparation and selection

`python -m scripts.prepare_patch_eval_suite` prepares and selects task inputs for
the existing `continue-fresh-patch` CLI. It does not introduce a service, another
queue, or an execution database. `--suite PATH` performs input preflight only;
`--select CASE_ID --attempt-id ID` prints the exact existing CLI arguments.
Only an explicit additional `--execute` calls that CLI and its real model path.
The returned run and attempt receipt references remain the existing result/query
interface. This document does not authorize an execution.

Preparation takes one explicit `--prepare-seed PATH`. The seed binds an output
root, existing P0 CLI arguments, the unchanged original P0 matrix, and the files
that identify its validator, source input and execution environment. Existing
output directories are not overwritten. The result uses the already-supported
`patch_qualification_tasks_v1` schema and can be consumed as `task_suite_ref` by
the qualification resolver after independent real trials exist.

The first dataset defines three distinct AccurateCrosshair Feature tasks:

| Task | Scope and independent oracle |
| --- | --- |
| `accurate-crosshair-recoil-default-off` | A newly defined Eval request, not a change to the user's production request. Fresh Follow Recoil defaults false; explicit true/false, five other defaults and configuration keys are preserved. Five checks across three C# processes. |
| `accurate-crosshair-spread-api-input-validation` | A newly defined public Mod API request. Negative/non-finite modifiers throw `ArgumentOutOfRangeException` without changing state or callback count; finite non-negative input, replacement, removal and notification semantics remain. Seventeen checks across five C# processes. |
| `accurate-crosshair-spread-toggle` | The existing P0 Feature and Plan, counted once. Reuses its original 36-check matrix; prospective verification identity is added to new report copies without rewriting historical reports or changing expected results. |

The two new input Plans and source-support judgments are explicitly operator
authored. Their requests and checks are fixed before any product model attempt.
They qualify only the Patch role being measured, not autonomous Evidence or
Planning. Repeating P0 in Repair mode does not create another Feature task or
increase the denominator. All new task trials start as `not_run`; baseline
oracle runs and successful input preflight do not count as model successes.

Evidence levels remain separate:

1. Synthetic contract tests validate selection, rejection and record binding.
2. Real original C# source with explicit dependency/engine doubles validates
   the selected local behavior. Compiler, references and runtime are fixed;
   this is not a complete host/OS reproducibility claim.
3. Real-model task trials must retain original responses, behavior matrices
   and the Proposal/Review/Dry-run chain before A7 can qualify a profile.
4. DSH/service operation and GTFO Runtime remain separate, unexecuted acceptance
   layers. Neither is implied by this task dataset.
