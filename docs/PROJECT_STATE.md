# Project State

Status: active control summary
Last updated: 2026-07-13

Authority and reading order are defined only by `AGENTS.md` section 2.

## 1. Current Selection

```text
current_queue: None
current_documentation_task: None
selected_product_request: None
```

The ProposalCritic contract, active-state cleanup, queue cleanup, coverage
separation, and architecture-reference maturity labels are complete. They do
not authorize another evaluator, retrieval, Dashboard, MCP, memory, multi-agent,
or runtime platform expansion.

After this cleanup, the next implementation task must be selected from a
concrete product capability or real Mod request. This file intentionally does
not prescribe that task.

## 2. Current Verified Product Boundary

The repository has a tested controlled chain for request planning, evidence
binding, implementation planning, patch proposal, deterministic review,
no-write dry-run, isolated apply, build evidence, and explicit blocked/repair
routes.

The preserved real BetterHitFeedback run proves one local request-to-build
execution with:

- an externally produced, read-only source input;
- current-source inspection with `rg` plus live file reads;
- an evidence-bound generated patch;
- deterministic review, dry-run, isolated apply, and real build;
- unchanged external input and a verified built DLL.

It does not prove GTFO gameplay behavior, general Mod quality, production
runtime automation, production RAG, cross-project generality, or autonomous
delivery.

The bounded `V2-RET-DIRECTIONAL-001` result retains `rg` plus live reads as the
current retrieval direction. The existing SymbolIndexer remains locally
interesting but did not cross the frozen investment threshold. The community
BM25 path had no authentic traceable corpus and was recorded as plumbing only.
No Dense, RRF, rerank, Agentic routing, H1-H5, or promotion work is active.

## 3. ProposalCritic Local/Injected Assessment Boundary

The current implementation provides a read-only ProposalCritic provider inside
`review_proposal`. It may write a separately bound `critic_assessment` artifact
but cannot select paths, authorize writes, bypass ProposalReviewer, or choose a
LangGraph route.

The caller must set `critic_requirement` explicitly:

| State | Exact condition | Route effect |
| --- | --- | --- |
| `not_required` | `critic_requirement="not_required"` and no provider | Run normal ProposalReviewer rules; no `critic_assessment` is written |
| `required_succeeded` | `critic_requirement="required"` and a valid current-hash-bound assessment is returned | Apply the versioned score policy, then all deterministic hard rules |
| `required_failed` | Required provider is absent, raises, returns unresolved, stale, malformed, wrong-policy, or wrong-hash output | Block before dry-run; do not retry implicitly |

Supplying a provider while `critic_requirement="not_required"` is a
configuration error. There is no inferred risk trigger.

Newly emitted `proposal_review` payloads include `critic_gate`. The existing
`proposal_review` 1.0 registry contract does not make that field mandatory, so
previously stored review artifacts remain readable without a migration task.

Policy `proposal_critic_local_injected_v1` applies only to patch proposal
review. It uses `equal_weight_rounded_mean` over four exact dimensions:
`evidence_grounding`, `scope_discipline`, `verification_quality`, and
`reversibility`. Each weight is 25 percent; the rounded mean must be at least
80, the verdict must be `pass`, and there must be no blocking Critic finding.
ProposalReviewer hard rules, permissions, bindings, and human approval always
take priority over the score.

The local rule-based implementation and injected-provider boundary are tested.
No external-model Critic execution or semantic-quality improvement has been
verified.

## 4. Current Claims And Known Gaps

| Area | Current state | Claim boundary |
| --- | --- | --- |
| Controlled LangGraph workflow | tested | One graph owns routing; this is not a general autonomous multi-agent framework |
| Artifact lineage and Binding Registry | tested on the controlled path | Stored hashes and bindings do not prove runtime behavior |
| Proposal review and dry-run | tested | Dry-run proves no-write validation, not compilation or gameplay |
| Isolated apply and real build | verified on the narrow BetterHitFeedback run | Build success does not prove GTFO runtime behavior |
| ProposalCritic local/injected boundary | tested for not-required, required-success, and required-failure | External model assessment quality remains unverified |
| Runtime/evaluation | interfaces and focused tests exist | Real GTFO gameplay success remains unproven |
| Retrieval direction | bounded local decision completed | Keep `rg` plus live reads; no production RAG claim |

Open implementation gaps remain tracked by Status, Provenance, and Trigger in
`docs/SPEC_COVERAGE_MATRIX.md`. A gap does not enter the active queue until its
recorded trigger is satisfied.

## 5. Verification Snapshot

The ProposalCritic-affected unit command currently passes 111 tests:

```text
.\.venv\Scripts\python.exe -m pytest tests/unit/test_proposal_review.py tests/unit/test_workflow_graph.py tests/unit/test_artifact_contract.py tests/unit/test_dashboard_projection.py tests/unit/test_repair_loop.py tests/unit/test_repair_checkpoint_smoke.py tests/unit/test_domain_adapter.py -q --tb=short
```

This count applies only to the touched proposal/artifact/workflow behavior. It
is not a claim that the full repository test suite or any real gameplay path is
green.

## 6. Historical Records

Completed queues, frozen validation tracks, review history, previous latest
summaries, and superseded direction statements are retained in
`docs/audits/LOOP_HISTORY.md` and Git history. They are not active work.
