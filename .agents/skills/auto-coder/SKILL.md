---
name: auto-coder
description: Autonomous spec-driven development agent for this Controlled Mod Agent Platform. Syncs DEV_SPEC.md, selects runnable controlled-code-generation tasks, implements code following the spec, preserves the mature RAG skeleton as an Evidence Knowledge Subsystem, runs tests with up to 3 auto-fix rounds, and reports progress honestly. Use when user says "auto code", "自动开发", "自动写代码", "auto dev", "一键开发", "autopilot", or wants fully automated spec-to-code workflow.
---

# Auto Coder

## Project Direction Override

This section supersedes any older generic-RAG wording below.

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

Prefer runnable controlled-loop progress over passive schema/audit work:

```text
request -> feature_spec -> evidence_pack -> implementation_plan
-> patch_proposal -> proposal_review -> dry_run_result -> build_result
-> runtime/manual evidence -> workflow_summary
```

One trigger completes **read spec → find task → code → test → persist progress**.

Optional modifiers: append a task ID (e.g. `auto code B2`) to target a specific task, or `--no-commit` to skip git commit.

---

## Pipeline

```
Sync Spec → Find Task → Implement → Test (≤3 fix rounds) → Persist
```

Pause only at the end for commit confirmation. Run everything else autonomously.

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

### 1. Sync Spec

```powershell
python .agents/skills/auto-coder/scripts/sync_spec.py
```

Then read the schedule file to get task statuses:
- Read `.agents/skills/auto-coder/references/06-schedule.md` if it is current.
- Also read the matching sections in `DEV_SPEC.md` directly.

Task markers:

| Marker | Status |
|--------|--------|
| `[ ]` / `⬜` | Not started |
| `[~]` / `🔶` / `(进行中)` | In progress |
| `[x]` / `✅` / `(已完成)` | Completed |

---

### 2. Find Task

Pick the first `IN_PROGRESS` task, then the first `NOT_STARTED`. If user specified a task ID, use that directly.

Quick-check predecessor artifacts exist (file-level only). On mismatch, log a warning and continue — only stop if the target task itself is blocked.

---

### 3. Implement

1. **Read relevant spec** from `DEV_SPEC.md` and, when useful, generated
   references under `.agents/skills/auto-coder/references/`:
   - Product direction: top-level overrides, especially `0.0B`
   - RAG preservation/integration: sections `45`, `46`, `47`
   - RAG-level depth requirements: sections `48`, `49`, `50`
   - Architecture: `05-architecture.md`
   - Tech details: `03-tech-stack.md`
   - Testing conventions: `04-testing.md`

2. **Extract** from spec: inputs/outputs, named strategies, schemas, graph or
   state transitions, failure paths, implementation classes, trace/metrics,
   file list, acceptance criteria, and forbidden behaviors.

3. **Plan** files to create/modify before writing any code.

4. **Code** — project-specific rules:
   - Treat `DEV_SPEC.md` as the single source of truth
   - Use `config/settings.yaml` values, never hardcode
   - Match existing codebase patterns and style
   - Keep mature RAG abstractions, but adapt semantics to Evidence Knowledge
     Subsystem
   - Keep LangGraph workflow as the top-level control plane

5. **Write tests** alongside code:
   - Place in `tests/unit/` or `tests/integration/` per spec
   - Mock external deps in unit tests

6. **Self-review** before running tests: verify all planned files exist and tests import correctly.

---

### 4. Test & Auto-Fix

```

Round 0..2:
  Run pytest on relevant test file
  If pass → go to step 5
  If fail → analyze error, apply fix, re-run

Round 3 still failing → STOP, show failure report to user
```

---

### 5. Persist

1. **Update `DEV_SPEC.md`** only when the task is actually complete.
2. **Re-sync when useful**: `python .agents/skills/auto-coder/scripts/sync_spec.py --force`
3. **Commit only if this workspace is a git repo and the user requested it.**
4. **Show summary & ask**:

```
✅ [A3] 配置加载与校验 — done
   Files: src/core/settings.py, tests/unit/test_settings.py
   Tests: 8/8 passed
   Commit: feat(config): [A3] implement config loader

   "commit" → git add + commit
   "skip"   → end
   "next"   → commit + start next task
```

On "next", loop back to step 1 and start the next task.
