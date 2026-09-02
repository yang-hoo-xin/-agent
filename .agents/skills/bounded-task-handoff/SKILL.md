---
name: bounded-task-handoff
description: Create a compact, single-capability implementation handoff from explicit scope and repository facts. Use when a decided task must move from planning or audit into a bounded implementation page without copying chat history or the wider roadmap.
---

# Bounded Task Handoff

Produce one implementation packet of about 800-1500 tokens. Treat the packet as
a short-lived handoff, not as product state or a readiness assessment.

## Required inputs

Require the caller to provide every non-Git field below. Read an exact receipt
when it is the stated source, then pass the value unchanged. Do not infer a
missing value from filenames, identifier similarity, prior chat, or project
history.

- task_id
- goal
- read_first
- write_allowlist
- protected_paths
- verification_commands
- done_when
- stop_when
- out_of_scope
- supported_entry_command
- current_node
- first_failure_owner
- vertical_stage
- surface_objectives.refs

The caller must also provide target_commit explicitly as either a commit
identifier or null. The helper fills base_sha and the current Git snapshot. It
reports only direct parent relationships for target_commit; it does not derive
task scope from Git.

## Workflow

1. Confirm that the handoff describes one already-decided product capability.
2. Build a strict JSON input using the exact field names accepted by
   scripts/build_handoff.py. Keep surface_objectives.refs as references; do not
   copy the nine-item route or another long-term plan into the packet.
3. Run the helper from the repository that owns the task:

       python <skill-dir>/scripts/build_handoff.py --input <input.json> --repo <repo> --format markdown

4. Check that every supplied scope item remains present and the packet stays
   near 800-1500 tokens. If it cannot fit without dropping required facts, ask
   for a narrower work package.
5. Normally leave the packet on stdout. Pass --output only when a resumable
   runtime packet is explicitly needed. That flag writes only
   <git-root>/.codex/task-packet.json. This is the checkout's single active
   implementation packet, not a multi-page history store. An existing packet
   blocks replacement unless --replace-active-packet is also explicit.

For concurrent tasks in one checkout, keep packets on stdout. Use an independent
worktree when more than one task requires a persisted active packet.

## Boundaries

- Do not copy chat history or restate the complete delivery roadmap.
- Do not decide product readiness, permissions, or the next product objective.
- Do not add paths, commands, identifiers, or acceptance rules that the caller
  did not supply.
- Do not write product code or control documents.
- Do not use the packet as evidence that verification ran.
- Do not truncate scope or Git status to satisfy the output limit. Oversized
  input or either oversized complete renderer must fail closed.
- Stop when an input is missing, inconsistent, or broader than one vertical
  work package.
