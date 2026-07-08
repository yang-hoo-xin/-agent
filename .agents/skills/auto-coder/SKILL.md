---
name: auto-coder
description: Capability-first guardrail for DEV_SPEC.md-driven platform development in this Controlled Mod Agent Platform. Use when user says "auto code", "自动开发", "自动写代码", "auto dev", "一键开发", "autopilot", or requests a bounded platform-development loop that must follow source code, tests, artifacts, docs/IMPLEMENTATION_QUEUE.md, docs/SPEC_COVERAGE_MATRIX.md, and LangGraph workflow evidence without treating this Skill as the control plane.
---

# Auto Coder

## Capability-First Guardrail Role

This Skill is a capability-first execution guardrail. It is not the project
control plane and must not replace source code, focused tests, artifacts,
current state documents, or LangGraph workflow routing.

Project progression is led by the implemented system:

```text
source code -> focused tests -> artifact contracts -> LangGraph graph execution
-> docs/PROJECT_STATE.md -> docs/IMPLEMENTATION_QUEUE.md
-> docs/SPEC_COVERAGE_MATRIX.md
```

`DEV_SPEC.md` remains the product and architecture source of truth. This Skill
only defines how an agent should read that truth, choose a bounded task, turn
missing capability into implementation plans, validate claims, and avoid unsafe
shortcuts.

This project is a vertical controlled code generation platform, not a generic
RAG Q&A app. `DEV_SPEC.md` is the source of truth. Always obey the highest
priority overrides near the top of `DEV_SPEC.md`, especially capability-first
execution, LangGraph control-plane rules, and the current product direction
lock.

Preserve the mature RAG skeleton and imported RAG spec as the
`knowledge_hub` / Evidence Knowledge Subsystem. Keep loaders, splitters,
transforms, embeddings, sparse/dense retrieval, hybrid fusion, rerank,
citations, multimodal evidence, observability, evaluation, MCP exposure, and
dashboard surfaces. Change their product role: RAG grounds planning,
implementation plans, patch proposals, review gates, build/runtime repair, eval,
and dashboard explanations.

RAG must not approve writes, apply patches, run builds, claim runtime success,
override review gates, or replace LangGraph workflow routing.

Upgrade non-RAG modules to the same engineering depth as the mature RAG spec:
goals/non-goals, named strategies, inputs/outputs, schemas, state transitions,
failure paths, implementation classes, observability, tests, acceptance
criteria, forbidden behaviors, phase breakdown, and ADR/trade-off notes.

Prefer runnable controlled-loop progress over passive schema/audit work, but do
not treat this Skill as the workflow runner:

```text
request -> feature_spec -> evidence_pack -> implementation_plan
-> patch_proposal -> proposal_review -> dry_run_result -> build_result
-> runtime/manual evidence -> workflow_summary
```

Source, tests, artifacts, and LangGraph execution decide whether progress is
real. This Skill only guards the agent's reading order, implementation-path
discipline, and unsupported-claim prevention. It must not downgrade product
goals into dev-only, local-only, process-only, schema-only, or documentation-only
end states.

When an intended capability is not implemented yet, the default action is to
produce an implementation plan, not to narrow the product claim. Every gap must
be compressed into:

- source code locations;
- artifact contract changes;
- LangGraph routing changes;
- focused test files;
- success acceptance criteria.

If current evidence is local, fixture-style, process-only, or partial, state
that fact only as the current implementation status and immediately attach the
implementation path for the full product capability.

Do not infer exact identifiers, JSON paths, artifact names, stage names, config
keys, route labels, or test names. Read the relevant source, tests, artifacts,
logs, config, or docs and copy exact names from them.

---

## Working Protocol

Use this protocol for bounded platform-development work. The current queue,
source code, tests, artifacts, and LangGraph graph execution remain the
authority for what to do next and what is actually complete.

Do not commit automatically. Commit only when the user explicitly asks, after
focused tests and status review.

> **⚠️ CRITICAL: Activate `.venv` before ANY `python`/`pytest` command (idempotent, re-run if unsure).**
> - **Windows**: `.\.venv\Scripts\Activate.ps1`
> - **macOS/Linux**: `source .venv/bin/activate`

## Reference Map

Generated quick-reference files live under `.agents/skills/auto-coder/references/`.
Use them as indexes only; if they conflict with `DEV_SPEC.md`, trust
`DEV_SPEC.md`.

| Source | Content | When to Read |
|------|---------|-------------|
| `DEV_SPEC.md` top overrides | Capability-first execution, LangGraph control plane, current product direction | Every cycle |
| `DEV_SPEC.md` sections `45-47` | RAG preservation, imported RAG subsystem, migration/conflict rules | Any Knowledge Hub / Evidence RAG work |
| `DEV_SPEC.md` sections `48-50` | Non-RAG depth upgrade, governance, framework boundaries | Any workflow, artifact, review, runtime, dashboard, MCP/API work |
| `.agents/skills/auto-coder/references/*.md` | Generated quick indexes from the spec | Optional navigation aid only |

---

### 1. Read Current Control Documents

Read these before selecting or changing work:

- `DEV_SPEC.md` sections relevant to the task, always including the top
  overrides when product direction or workflow control is involved.
- `docs/PROJECT_STATE.md` for current factual state and latest loop summary.
- `docs/IMPLEMENTATION_QUEUE.md` for the next executable small loops.
- `docs/SPEC_COVERAGE_MATRIX.md` for affected coverage rows and open gaps.

When useful, regenerate quick references:

```powershell
python .agents/skills/auto-coder/scripts/sync_spec.py
```

Generated references under `.agents/skills/auto-coder/references/` are indexes
only. If they conflict with `DEV_SPEC.md`, trust `DEV_SPEC.md`.

Task markers:

| Marker | Status |
|--------|--------|
| `[ ]` / `⬜` | Not started |
| `[~]` / `🔶` / `(进行中)` | In progress |
| `[x]` / `✅` / `(已完成)` | Completed |

---

### 2. Choose Bounded Capability Work

Select work from the current queue or an explicit user request. Prefer the next
bounded non-Skill implementation checkpoint when the queue says non-Skill work is
active.

Before editing, state:

- exact task or requested correction;
- files expected to change;
- affected coverage IDs when a queue task is being implemented;
- artifact contracts expected to change;
- LangGraph routes expected to change;
- focused tests expected to prove the change.

Do not continue splitting process Skills by default when current state says
non-Skill implementation checkpoints are active.

---

### 3. Let Source And Tests Drive Implementation

Before coding, read the exact source and test files that define the behavior.

Extract exact names from files:

- config keys from `config/settings.yaml` or settings code;
- artifact names from the artifact registry and tests;
- route labels from workflow transitions or graph tests;
- schema fields from Pydantic models and artifact contract tests;
- acceptance rules from current tests and `DEV_SPEC.md`.

Implementation rules:

- Treat `DEV_SPEC.md` as the single source of truth.
- Use `config/settings.yaml` values instead of hardcoding behavior where a
  setting already exists.
- Match existing codebase patterns and style.
- Keep mature RAG abstractions, but adapt semantics to Evidence Knowledge
  Subsystem.
- Keep LangGraph workflow as the top-level control plane.
- Add or update focused tests when behavior changes.

Self-review before running tests: verify all planned files exist and tests
import correctly.

---

### 4. Validate With Focused Tests

```

Round 0..2:
  Run focused pytest command tied to the changed behavior.
  If pass -> go to step 5.
  If fail -> inspect the error, apply the smallest evidence-backed fix, re-run.

Round 3 still failing -> STOP, show the exact failure report to the user.
```

Documentation-only Skill or control-doc corrections should at minimum run the
relevant validation script when one exists, such as:

```powershell
python .agents/skills/skill-creator/scripts/quick_validate.py .agents/skills/auto-coder
```

---

### 5. Persist Proven State With Implementation Paths

Update control documents only when their claims are backed by current files and
focused tests, or when the user explicitly requested a documentation-only
correction.

Use these evidence rules:

- current-branch claims require present files and focused test output;
- restored history is reconstruction support only;
- fake/local/supplied-output execution must be labeled honestly;
- build success does not prove runtime behavior;
- runtime success requires runtime evidence;
- real game automation remains explicit opt-in work unless the user selects it;
- after the user selects or approves real game automation, the next step must be
  an implementation path for real launch, persistent logs, screenshots,
  plugin-specific markers, build/run binding, and runtime evidence.

These rules may block unsupported claims, but they must not shrink product
goals. A limitation statement must be paired with the concrete implementation
path that removes the limitation.

For implementation work, report:

```text
Task:
Changed files:
Validation:
What is now true:
What remains unproven:
Implementation path:
Next:
```

For documentation-only guardrail corrections, report:

```text
Changed files:
Validation:
Boundary now recorded:
No source behavior changed:
```
