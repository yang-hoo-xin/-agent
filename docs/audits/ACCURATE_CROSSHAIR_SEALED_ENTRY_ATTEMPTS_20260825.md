# AccurateCrosshair Sealed-Entry Attempts 1–5 Incident

Status: frozen P2 entry incident record

Recorded: 2026-08-25

Current owner: `ENTRY-002` — sealed/fresh execution entry preflight

## 1. Authority And Claim Boundary

This record preserves the detailed physical sequence behind the current
`P2-entry-preflight-blocked` status. It is not an execution packet, retry
authorization, expected-side truth, ProductExecution result, or capability
completion claim.

Attempts 1–4 were outer sealed-entry attempts. None entered ProductExecution;
each recorded zero model calls and zero product writes. Attempt5 was a fresh
same-context preflight-only task. It did not consume its packet's outer attempt.

## 2. Bound Product Coordinate

```yaml
task_id: ACCURATE-CROSSHAIR-SPREAD-TOGGLE-001
platform_branch: codex/rag-capability-mainline
platform_checkpoint: 32a939b3f217721b076704cd7e701369fef532ed
P0_checkpoint: c8004845fe3f01d844e79ab8b6aba0634b6a5c01
P1a_checkpoint: d377ab466fb3e2c57c4c33e29bc2408864e5976e
P1b_checkpoint: 32a939b3f217721b076704cd7e701369fef532ed
P2_product_path_admission: true
P2_sealed_entry_admission: false
P2_ProductExecution_actual_runs: 0
empirical_actual_started: false
internal_alpha_changed_product_build_test_success: false
internal_alpha_failure_different_repair_revalidation_success: false
```

## 3. Attempt Ledger

| Entry attempt | Immutable packet identity | First physical failure | Downstream effects |
| --- | --- | --- | --- |
| A1 — `p2_ac_20260825_001/attempt_1` | payload `54c03f5572f1466ecbdee8217ab2e79731b0c2381d0c750653a00c4c3475e2a2`; delivery `673b0def9ae4ebeb7532cf34b58167dd5a5b1061104d9384250aa32a88fdd00b` | porcelain `??` for the protected untracked WIP was incorrectly classified as a staged change | ProductExecution actual 0; model calls 0; product writes 0 |
| A2 — `p2_ac_20260825_002/attempt_1` | payload `bee9c5f3b539717442b90d7b8aed08b2aea7a6466e3377aa1de52423b0d378f9`; delivery `87fe69d8cf202b456a12f7e0fa44cc57b8878f56139165b03197b3ea7100fd8b` | `_git` used `stdout.strip()`, deleting the leading fixed-width porcelain status character before parsing | ProductExecution actual 0; model calls 0; product writes 0 |
| A3 — `p2_ac_20260825_003/attempt_1` | payload `8989b74c61caf217992e3561a29565ffc89ff96f5599f573a5cf87afd9827254`; delivery `a30b73b4ae88a19b68744dae19eec668036202aee6bc83786455a804372ab9cc` | source Git returned nonzero in the fresh task; stderr was not retained, so the exact cause could not be assigned | ProductExecution actual 0; model calls 0; product writes 0 |
| A4 — `p2_ac_20260825_004/attempt_1` | payload `6de8a96e511a3ac8bed74a04404ea49acadf75b606ab3ab23ab2c2faa041f0a3`; delivery `e6012c4f3f62ed2e95b07e8a4b62c746f7969c0e437316ebba2cc743951b86b3` | source Git returned `fatal: detected dubious ownership in repository`; retained stderr SHA256 `6a145ccecaebaf6afac3ed33d8bd612bcf568f22f1b4b6baabe11effc56f2841` | ProductExecution actual 0; model calls 0; product writes 0 |
| A5 preflight — `p2_ac_20260825_005/attempt_1` | payload `979c0fdeca85dbedf9e1156931cf0bf724b57fa69a0cdd2394612745d88f78f7` | exit 1 at `sealed_run.py::_write_fresh_preflight_receipt`: `RuntimeError: fresh preflight output root argument drifted` | no receipt/hash; outer attempt unconsumed; actual, ProductExecution, Build, Runtime, model generation, diff approval, and Apply not started |

Attempt4 established a security-principal mismatch rather than source-identity
drift. The bounded Attempt5 packet therefore used process-local
`git -c safe.directory=<exact packet root>` only. Global Git configuration,
`safe.directory=*`, parent-directory trust, and other-worktree trust remained
forbidden.

## 4. Attempt5 Final Attribution

`packet.json` recorded the preflight output root with `/` separators. `RUN.md`
supplied the same Windows physical path with `\` separators. Before normalizing
either value to a resolved physical identity, `_write_fresh_preflight_receipt`
compared the two strings directly and rejected them as drift.

This is a sealed-entry Windows path-equivalence failure. It does not reopen the
P0 false-sufficiency owner or the P1 requirement-coverage/provider owners.

The observed call sequence reached the return boundary of `_verify_packet`,
`_verify_platform`, `_verify_source`, and `_verify_ollama` before the exception.
Because no preflight receipt was written, this record does **not** promote those
gates to formally passed. The only supported statement is that no earlier
exception was reported and the frozen first failure moved later to output-root
admission.

## 5. Filesystem Observation Sources

The fresh task stopped immediately after the exception and did not perform a
post-failure filesystem reread. It therefore does not claim that all filesystem
writes were zero.

A later macro-page read-only directory listing did not observe
`fresh_preflight_root`. That is a separate observation from a different task
context. It supports `fresh_preflight_root_not_observed_by_later_macro_listing`,
not a universal no-write claim for the failed fresh process.

Across all attempts, no evidence shows an intentional product-content write,
ProductExecution entry, model generation, Build, Runtime, exact-diff approval,
or Apply.

## 6. Current Route

```yaml
current_queue: P2-entry-preflight-blocked
current_owner: ENTRY-002
P0_reopened: false
P1_reopened: false
attempt5_rerun_authorized: false
actual_authorized: false
next_step: bounded packet-owner repair of Windows physical-path equivalence, followed by a newly authorized fresh same-context preflight
actual_gate: preflight success plus receipt/hash macro review plus separate actual authorization
```

This incident record does not claim that sealed-entry engineering is complete
and does not authorize a rerun, attempt6, or empirical actual.
