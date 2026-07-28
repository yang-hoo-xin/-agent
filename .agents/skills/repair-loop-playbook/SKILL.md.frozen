---
name: repair-loop-playbook
description: Process-only repair loop playbook for the Controlled Mod Agent Platform. Use when a dry-run, proposal review, build, runtime evidence, eval, checkpoint resume, or handoff gate fails and the agent must decide whether to create a bounded repair plan, route a repair proposal back through review, ask for evidence, block, or hand off. Do not use as an automatic repair executor, retry engine, runtime Skill registry, Skill selector, Skill loader, LangGraph node injection mechanism, or source of product facts, schemas, current state, or test results.
---

# Repair Loop Playbook

## Boundary

Use this skill to decide and describe bounded repair after a controlled mod delivery gate fails. Keep product facts, current state, interface contracts, artifact payloads, queue status, retry counters, and test evidence in `DEV_SPEC.md`, `docs/PROJECT_STATE.md`, `docs/IMPLEMENTATION_QUEUE.md`, `docs/SPEC_COVERAGE_MATRIX.md`, artifacts, command output, logs, and source files.

Do not store current branch facts in this skill. Read current files before naming paths, fields, commands, artifact schemas, tests, status values, retry limits, or repair artifact names. If required evidence is missing, ask for it or block instead of guessing.

This skill is not an automatic repair system. It does not execute edits, retry commands, bypass review, expand scope, launch the game, copy DLLs, run MCP writes, or implement a runtime Skill registry, Skill selector, Skill loader, LangGraph selected-skill node injection, or Skill output validator.

## Repair Inputs

Before proposing repair, locate the current evidence for the failed gate:

1. User request, feature specification, selected plan, or repair reason.
2. Failing gate: proposal review, dry-run, build, runtime evidence, eval, checkpoint resume, or handoff.
3. Failure evidence: review findings, dry-run conflicts, build diagnostics, runtime logs, acceptance mismatch, eval regression, stale upstream report, or blocked report.
4. Previous artifacts that led to the failure, including implementation plan, patch proposal, proposal review, build result, runtime evidence, eval report, or resume report when present.
5. Current retry budget, previous repair attempts, and any scope constraints from current files or supplied artifacts.
6. Permission and risk context for edits, build commands, runtime probes, game directory writes, process launches, or MCP writes.
7. Commands that actually ran and their exit status when command evidence is part of the claim.

Separate current-branch evidence from restored historical records. Treat restored history as reconstruction support unless the referenced files exist now and relevant checks were rerun.

## Repair Procedure

1. Classify the failed gate
   - Identify which controlled gate failed and whether the failure is deterministic, missing evidence, permission-blocked, stale, ambiguous, or out of scope.
   - Do not repair a failure whose identifiers, paths, fields, schemas, commands, or evidence cannot be verified from current files or supplied evidence.

2. Check repair eligibility
   - Confirm the failure can be addressed by a bounded code, config, artifact, or documentation change.
   - Confirm the repair stays inside the requested behavior and does not add optional platform expansion.
   - Confirm retry budget remains when the current files or supplied artifacts define one.
   - Block instead of repairing when the next step needs unapproved real game launch, DLL copy, process control, destructive filesystem operations, network access, or MCP writes.

3. Bind repair to evidence
   - Tie each repair action to the specific failing evidence and upstream artifact.
   - Keep read-only evidence sources separate from writable edit targets.
   - Reject repair plans that rely only on generated prose, legacy RAG context, restored history, or unsupported assumptions.

4. Define minimal repair scope
   - State the smallest edit set that can address the failing evidence.
   - Preserve the original acceptance criteria unless the user explicitly changes the request.
   - Record non-goals and refused expansions.
   - Prefer clarification or evidence collection when multiple repair directions are possible and current evidence cannot choose between them.

5. Route the repair
   - Send repair proposals back through patch review before execution.
   - Send build or runtime failures with observable signals to runtime diagnosis when the claim boundary is unclear.
   - Ask the user for missing real runtime logs, screenshots, manual observations, or approval when required.
   - Hand off only when no repair is needed or the remaining work is explicitly outside the approved scope.

## Output Format

Use this structure for repair decisions:

```text
Decision: repair_ready | needs_more_evidence | blocked | handoff

Failed gate:
- proposal_review | dry_run | build | runtime_evidence | eval | checkpoint_resume | handoff

Failure evidence:
- Current files, artifacts, commands, logs, and historical records checked

Repair scope:
- Minimal changes allowed
- Non-goals and forbidden expansions
- Retry budget status when known from current evidence

Repair actions:
- Action | Evidence | Target | Risk | Required review

Verification plan:
- Focused checks to rerun
- Runtime or manual evidence needed
- What the repair would prove
- What it would not prove

Next action:
- patch review | runtime diagnosis | ask user for evidence | block | handoff
```

## Stop Conditions

Stop and report clearly when:

- The repair depends on identifiers, paths, fields, schemas, commands, tests, retry limits, or artifact names that cannot be verified from current files or supplied evidence.
- The failure is only a missing-evidence problem and no bounded code or configuration repair follows from the evidence.
- The repair would expand scope, bypass review, skip required upstream artifacts, ignore retry limits, or turn a focused fix into optional platform development.
- The task requires launching the game, copying a DLL, collecting real game logs, taking screenshots, controlling processes, or running MCP writes without explicit approval.
- The work turns into platform implementation from `DEV_SPEC.md`; use `auto-coder` for that work.
- The request tries to treat this process Skill as an automatic repair executor, retry engine, runtime Skill registry, Skill selector, Skill loader, LangGraph selected-skill injection, or output validator.
