---
name: release-evidence-packager
description: Generate a release manifest and Markdown draft using the repository's release-evidence-input.v1 input contract and revision-bound evidence.
---

# Release Evidence Packager

Use this skill for the current repository's fixed version-1 release evidence
bundle. It derives two delivery files; it does not decide whether to release.

## Current input contract

Build one strict JSON input for
`scripts/package_release_evidence.py` with:

- `schema_version` equal to `release-evidence-input.v1`;
- explicit `release_id`, `project_name`, and
  `release_commit_evidence_id`;
- evidence items containing the exact fields accepted by the helper;
- claims containing `claim_id`, `statement`, `evidence_ids`, and
  `placements`;
- exactly five `delivery_lines`, each with `line_id`, `label`,
  `objective_refs`, `evidence_ids`, `unknowns`, and `next_gate`;
- a `demo` object with `duration_minutes` from 3 through 5 and a `steps`
  array.

为什么要有它： the current helper enforces these fields, exactly five delivery
lines, and the demo duration. This fixed shape is a current compatibility
constraint, not a general recommendation for every release artifact.

Each evidence item uses one of `commit`, `test`, `ci`, `build`,
`runtime`, or `trace`, and one of `verified`, `failed`, or `blocked`.
为什么要有它： the renderer projects these exact categories.

Read every supplied `source_ref` and preserve its identity and observed result.
为什么要有它： model prose, filenames, old summaries, and control documents do
not prove a current run.

## Generate

Run:

```text
python <skill-dir>/scripts/package_release_evidence.py --input <input.json> --output-dir <approved-dir>
```

为什么要有它： the helper validates references, writes
`release_manifest.json` and `release_evidence_draft.md`, and blocks existing
targets unless `--overwrite` is explicit.

A view is `demonstrated` only when the selected release commit evidence is
verified and every cited item is verified with the same exact `commit_sha`.
为什么要有它： evidence from another revision cannot demonstrate the release
revision.

Empty evidence references remain `not_demonstrated`. 为什么要有它： missing
support must stay visible rather than being inferred from narration.

## Boundaries

- Do not invent metrics, strengthen wording, or add claims. 为什么要有它： the
  packager is a projection over supplied evidence.
- Keep `unknowns` and `next_gate` exactly as supplied. 为什么要有它： those
  fields describe caller-known limits and are not new evidence.
- Do not use the output to authorize Apply, Build, Runtime, release, or a resume
  claim. 为什么要有它： generated delivery files have no execution authority.
- Repair rejected input instead of bypassing validation or dropping fields. Why
  this exists: silent loss would change the evidence claim.
- Treat two-file rollback as best effort across ordinary caught errors; it does
  not guarantee atomicity across process termination or operating-system
  failure. 为什么要有它： the helper's write implementation cannot provide
  cross-file transactional durability.
