---
name: release-evidence-packager
description: Generate a release evidence manifest and delivery draft from explicitly verified commit, test, CI, build, runtime, and trace references. Use during release or Day 9-10 resume preparation when every claim must remain bound to evidence and unsupported claims must be marked not_demonstrated.
---

# Release Evidence Packager

Create delivery artifacts as a derived index over existing evidence. The source
commit, test output, CI run, build receipt, runtime observation, and trace remain
authoritative; generated files never become a second product-state layer.

## Evidence preparation

Read every supplied source_ref before packaging it. Preserve its exact identity
and observed result. Do not accept model prose, an old summary, or a control
document as proof of a current run.

Build one strict JSON input for scripts/package_release_evidence.py:

- schema_version must be release-evidence-input.v1.
- release_id and project_name must be explicit.
- evidence items require evidence_id, kind, status, summary, source_ref,
  command, commit_sha, and metrics.
- kind is one of commit, test, ci, build, runtime, or trace.
- status is one of verified, failed, or blocked.
- commit_sha may bind any evidence item to an exact revision. It may be null for
  any kind except commit; commit evidence requires a non-null value.
- release_commit_evidence_id is either null or the ID of a commit item.
- claims require claim_id, statement, evidence_ids, and placements.
- delivery_lines contains exactly five caller-defined lines. Each line requires
  line_id, label, objective_refs, evidence_ids, unknowns, and next_gate.
- demo requires an explicit duration_minutes from 3 through 5 and explicit
  steps with title, narration, and evidence_ids.

Unknown or missing fields, duplicate object keys or identifiers, and unresolved
evidence references fail closed. Empty evidence_ids are valid and produce
not_demonstrated.

## Generate

Run:

    python <skill-dir>/scripts/package_release_evidence.py --input <input.json> --output-dir <approved-dir>

The helper stages and fsyncs release_manifest.json and
release_evidence_draft.md before changing either target, and it restores prior
files when a caught commit error permits rollback. It does not guarantee
two-file atomicity across process termination, operating-system failure, or
power loss. Without --overwrite, either existing target blocks with zero
output-file changes. It
projects:

- evidence status for commit, test, CI, build, runtime, and trace;
- five explicit delivery lines, each showing evidence, unknowns, and next_gate;
- a results table;
- a 3-5 minute demo script;
- evidence-bound resume bullets and interview evidence.

A claim, delivery line, demo step, or evidence-kind view is demonstrated only
when the release commit evidence is verified and every cited evidence item has
status verified with commit_sha exactly equal to that release commit SHA.
Otherwise the output is not_demonstrated and does not present the narration as
established.

## Boundaries

- Do not invent metrics, recommend numbers, strengthen wording, or add claims.
- Do not infer status from filenames, claim text, project plans, or absent data.
- Do not alter product source, product state, readiness documents, or evidence.
- Do not use the manifest to authorize Apply, Build, Runtime, release, or a
  resume claim.
- Keep unknowns and next_gate exactly as explicitly supplied; they are a view,
  not new evidence.
- Stop and repair the input when the helper rejects it. Do not bypass schema
  validation or silently discard fields.
