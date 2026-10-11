---
name: bounded-task-handoff
description: Generate one bounded implementation packet using the repository's bounded-task-handoff.v1 input contract after scope and required fields are decided.
---

# Bounded Task Handoff

Use this skill only for the current repository's version-1 handoff contract. It
is not a general planning or task-summary skill.

## Required contract

The caller must supply these exact non-Git fields:

- `task_id`, `goal`, `read_first`, `write_allowlist`, and
  `protected_paths`;
- `verification_commands`, `done_when`, `stop_when`, and `out_of_scope`;
- `supported_entry_command`, `current_node`, `first_failure_owner`, and
  `vertical_stage`;
- `surface_objectives.refs`;
- `target_commit` as an exact commit identifier or `null`.

为什么要有它： `scripts/build_handoff.py` enforces
`bounded-task-handoff.v1` with these exact fields and fails on missing or
unknown fields. Do not invent filler for a field. If the selected task does not
have this contract, do not use this skill.

## Generate

1. Confirm that one product capability and its acceptance boundary are already
   decided. 为什么要有它： the helper packages a decision; it does not choose
   the task.
2. Read the authoritative source for every supplied value and preserve exact
   identifiers. 为什么要有它： similar names, prior chat, and old packets are
   not field authority.
3. Run from the repository that owns the task:

   ```text
   python <skill-dir>/scripts/build_handoff.py --input <input.json> --repo <repo> --format markdown
   ```

   为什么要有它： the helper binds the packet to the current Git snapshot and
   validates both JSON and Markdown render limits.
4. Leave output on stdout unless a resumable active packet is explicitly
   requested. 为什么要有它： `--output` writes
   `<git-root>/.codex/task-packet.json` and therefore changes checkout state.
5. Use `--replace-active-packet` only when replacement of that exact active
   packet is part of the request. 为什么要有它： silent replacement can erase
   the current handoff context.

The current helper caps complete rendered output at an estimated 1,500 tokens
and rejects oversized input rather than dropping fields. 为什么要有它：
truncation would change the authorized scope.

## Boundaries

- Do not copy chat history or the wider roadmap. 为什么要有它： the packet is
  one short-lived implementation handoff.
- Do not decide readiness, permission, or the next objective. 为什么要有它：
  a derived packet has no decision authority.
- Do not add paths, commands, identifiers, or acceptance rules. 为什么要有它：
  only the explicit caller inputs and Git snapshot belong in the packet.
- Do not treat packet generation as executed verification. 为什么要有它：
  rendering evidence references does not run their commands.
- For concurrent persisted tasks, use independent worktrees. 为什么要有它：
  the version-1 contract supports one active packet per checkout.
