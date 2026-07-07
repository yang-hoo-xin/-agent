---
name: patch-review-playbook
description: Process-only patch review playbook for the Controlled Mod Agent Platform. Use when reviewing a patch proposal, implementation diff, repair proposal, evidence binding, permission boundary, forbidden path check, runtime-risk decision, or handoff readiness for a mod delivery workflow. Do not use as a source of product facts, current state, interface schemas, test results, or autonomous platform-code development.
---

# Patch Review Playbook

## Boundary

Use this skill to review proposed changes before execution, after execution, or during repair. Keep product facts, current state, interface contracts, artifact payloads, queue status, and test evidence in `DEV_SPEC.md`, `docs/PROJECT_STATE.md`, `docs/IMPLEMENTATION_QUEUE.md`, `docs/SPEC_COVERAGE_MATRIX.md`, artifacts, command output, and source files.

Do not store current branch facts in this skill. Read the current files before naming paths, fields, commands, artifact schemas, tests, or status values. If required evidence is missing, ask for it or block the review instead of guessing.

Do not approve writes, build claims, runtime claims, or gameplay claims from legacy RAG context, auxiliary evidence, generated prose, or historical records alone.

## Review Inputs

Before deciding, locate the current evidence for the review target:

1. User request or repair reason.
2. Current feature specification or stated acceptance criteria.
3. Evidence used to justify the proposal.
4. Proposed edit targets and read-only evidence sources.
5. Diff or patch proposal, if present.
6. Permission, path, and domain policy context.
7. Relevant tests, build commands, runtime checks, logs, or artifact outputs.

Separate current-branch evidence from restored historical records. Treat restored history as reconstruction support unless the referenced files exist now and the relevant checks were rerun.

## Review Procedure

1. Establish scope
   - Identify the requested behavior, affected files, expected artifact chain, and whether the review is pre-execution, post-diff, or repair.
   - Mark out-of-scope optional capability expansion separately.

2. Verify evidence binding
   - Check that every proposed edit is tied to current evidence or an approved repair artifact.
   - Reject read-only evidence sources as edit targets unless current files prove they are writable targets.
   - Block proposals that rely only on auxiliary retrieval, restored history, or unsupported generated claims.

3. Check scope and permissions
   - Verify that target paths stay inside the intended project or explicitly approved output area.
   - Check forbidden paths, domain policy, destructive operations, game directory writes, process launches, and network or MCP write operations.
   - Require explicit user approval for high-risk writes or real game operations.

4. Inspect behavior and failure modes
   - Look for no-op patches, overly broad edits, stale artifacts, missing upstream artifacts, schema drift, unsafe fallbacks, and silent success paths.
   - For repair proposals, confirm the repair is bounded by the failing evidence and retry budget.

5. Check test and evidence claims
   - Match the claimed confidence to the command that actually ran.
   - Distinguish focused tests, affected suites, full-suite runs, dry runs, local probes, supplied output, manual evidence, and real runtime evidence.
   - Never treat build success as runtime success.

6. Decide the review result
   - Approve only when scope, evidence, permissions, and verification claims are coherent.
   - Request repair when the proposal is directionally valid but missing bounded fixes or evidence.
   - Block when required identifiers, paths, fields, schemas, permissions, or runtime evidence cannot be verified.

## Output Format

Use a review-first structure:

```text
Decision: approve | repair_required | blocked

Findings:
- Severity | Location | Issue | Evidence | Required action

Evidence checked:
- Current files, artifacts, commands, logs, and historical records consulted

Verification boundary:
- What the review proves
- What it does not prove

Next action:
- Execute, repair, ask user for evidence, or hand off
```

When reviewing code, lead with actionable findings ordered by severity and include file and line references when available. Keep summaries secondary.

## Stop Conditions

Stop and report clearly when:

- The proposal names identifiers, paths, fields, schemas, commands, or tests that cannot be verified from current files or supplied evidence.
- The review requires real build, real game runtime, DLL copy, process launch, or MCP write evidence that has not been explicitly approved and collected.
- The task is actually platform implementation from `DEV_SPEC.md`; use `auto-coder` for that work.
- The patch would expand default-paused optional capabilities without explicit user selection.
