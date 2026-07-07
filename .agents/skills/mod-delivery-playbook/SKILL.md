---
name: mod-delivery-playbook
description: Process-only delivery playbook for this Controlled Mod Agent Platform. Use when the user wants to turn a mod idea, planning discussion, feature request, gameplay change, UX tweak, or maintenance request into a controlled delivery chain: feature_spec, evidence lookup, implementation proposal, review, build/runtime evidence, repair loop, and handoff summary. Do not use for autonomous platform-code development; use auto-coder for DEV_SPEC.md-driven implementation work.
---

# Mod Delivery Playbook

## Boundary

Use this skill to run the user-facing mod delivery workflow. Keep product facts, interface contracts, current state, test results, artifact payloads, and queue status in `DEV_SPEC.md`, `docs/PROJECT_STATE.md`, `docs/IMPLEMENTATION_QUEUE.md`, `docs/SPEC_COVERAGE_MATRIX.md`, artifact files, and test output.

Do not replace `auto-coder`. When the task is to implement or evolve the platform itself from `DEV_SPEC.md`, use `.agents/skills/auto-coder/SKILL.md`.

Do not store current branch facts in this skill. Read current files before naming paths, fields, commands, or artifact schemas.

## Delivery Chain

Run the smallest complete chain that can answer the user's request with evidence:

```text
planning input -> feature_spec -> evidence lookup -> implementation proposal
-> review -> build/runtime evidence -> repair or handoff summary
```

Prefer a narrow vertical slice over expanding optional platform capabilities. Keep real dense retrieval, full multimodal ingestion, dashboard polish, multi-MCP writes, automatic game launch/copy operations, and large benchmark work out of the default chain unless the user explicitly selects that work.

## Procedure

1. Capture the request
   - Restate the desired mod behavior, target game/profile, acceptance conditions, and known constraints.
   - Mark unknowns explicitly. If the needed identifier, path, field, command, or schema is not in local files, ask the user for evidence instead of guessing.

2. Create or locate `feature_spec`
   - Use the existing artifact and workflow conventions from the repository.
   - Include acceptance criteria and runtime verification expectations.
   - Keep implementation details out until evidence has been checked.

3. Gather evidence
   - Read current source, docs, artifacts, tests, logs, and restored history as needed.
   - Separate current-branch evidence from historical records.
   - Treat `docs/audits/LOOP_HISTORY.md` as reconstruction support, not current test proof.

4. Produce an implementation proposal
   - Bind each proposed edit to evidence.
   - Separate read-only evidence sources from edit targets.
   - State blocked items when evidence is insufficient.

5. Review before execution
   - Check scope, permissions, forbidden paths, evidence binding, and runtime-risk level.
   - Do not approve writes from legacy RAG or auxiliary evidence alone.
   - Route unsafe or under-evidenced work to repair or clarification.

6. Collect build and runtime evidence
   - Use real build/runtime evidence only when the command actually ran and expected artifacts or acceptance signals were verified.
   - Keep fake, local, supplied, manual, and real evidence modes explicit.
   - Do not claim gameplay success from build success alone.

7. Repair or hand off
   - If build/runtime/review fails, create a bounded repair step with evidence and retry limits.
   - If the chain completes, summarize delivered behavior, files changed, evidence collected, unresolved risks, and next recommended task.

## MCP Use

Use MCP services as coordination surfaces only when they preserve the control boundary:

- Prefer read-only/report-only MCP inspection for status, artifacts, retrieval, proposal, review, eval, and jobs.
- Do not let MCP write operations bypass the review gate, permission model, artifact contracts, or LangGraph workflow.
- Treat multi-MCP write coordination as out of scope for the default delivery chain unless the user explicitly selects it.

## Stop Conditions

Stop and report clearly when:

- Required current files, logs, artifacts, or tests are missing.
- A requested identifier, path, field, schema, or command cannot be verified from local evidence.
- Build or runtime evidence is fake, local, supplied, or manual but the user asked for real proof.
- The task turns into platform implementation work that should be handled by `auto-coder`.
