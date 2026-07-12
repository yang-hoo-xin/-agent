# V2-RET-DIRECTIONAL-001 Local Decision Report

## Scope

This is a one-day, non-promotion local direction experiment. It compares only:

- A: `rg` plus live file reads;
- B: A plus the current regex-based `SymbolIndexer` and live symbol revalidation;
- D: local BM25 plumbing over the only available community fixture plus current-source verification.

It does not produce H1-H5, production-promotion, cross-project, wrong-file
modification, final Agent success, Dense, RRF, rerank, Agentic, AST, LSP, or
call-graph conclusions.

## Prior Work Classification

### Keep for the active directional pilot

- `RgLiveReadProvider`, canonical corpus snapshot, executable identity, command
  traces, live reads, final file hashes, and persisted raw-result hashing;
- existing basic file/Hook/MRR/latency evaluation semantics;
- the synthetic community fixture only as `plumbing_only` input for D.

### Retain only as conditional future formal-validation material

- `evaluation/benchmarks/arm_a_held_out_v1.json`;
- `evaluation/benchmarks/arm_a_held_out_protocol_v1.json`;
- `evaluation/benchmarks/arm_a_held_out_policy_v1.json`;
- negative-case evaluator support and `no_relevant_result_accuracy`;
- complete protocol-document hash binding for held-out formal runs;
- held-out design and protocol-binding tests.

These assets did not block or define this directional result.

### Stop; not part of the current pilot

- `scripts/audit_arm_a_benchmark_design.py`;
- the pre-run external-audit JSON and stored audit output;
- any continuation toward multi-round GPT review, complete mutation coverage,
  downstream modification outcomes, unified ranked-Hook schemas, or promotion
  gates.

The files are retained and were not deleted or rolled back.

## Frozen Inputs

- Cases: `evaluation/directional/v2_ret_directional_001_cases_v1.json`
- Dataset SHA-256: `f9ad279a3ccf2e52a80d2fa9928a2449fa75e825b7cc1ae9f44df7fcaabf6790`
- Cases: 3 exact-code, 5 current-SymbolIndexer, 4 community-history.
- Smoke-v5 case IDs and queries are excluded.
- Repository base revision: `6278371406949c377f12b1e10420424ef23bf53f`
- Corpus snapshot SHA-256: `5b8eed82a2fcaacf7be1616ccfb81b830587f7738638fdff2a4d47e6ce224ceb`
- Corpus: 175 files under `src`.
- Working tree was dirty and is fully recorded in the raw result. The corpus and
  Git binding did not change during measurement.

## Current SymbolIndexer Boundary

- Languages: C# (`.cs`) and Python (`.py`) only.
- C#: regex extraction of class, interface, struct, enum, and method declarations.
- Python: regex extraction of class and `def` declarations.
- Query: exact case-insensitive symbol lookup in the chunk index; the older
  symbol table also supports exact/substring matching over name, signature, and
  relative path.
- Ranking: exact name first in the older table, then relative path and line; the
  chunk index orders by source path, start line, and chunk id.
- Returned fields include symbol name/kind, path, line/span, signature or
  excerpt, chunk/source identity, and content hash.
- It does not parse syntax trees, resolve overload identities, callers,
  references, inheritance, annotations, or call graphs, and it has no semantic
  ranking.

## Community Data Boundary

No authentic, traceable community/history material exists in the workspace.
The only notes use `fixture://...` locators and were created as controlled
synthetic fixtures. D therefore measures plumbing only. Its 4/4 retrieval and
source-rejection outcomes cannot support a community-BM25 product-value claim.

## Raw Results

Valid raw result:

- `evaluation/directional/results/v2_ret_directional_001_v2_1e0ded1a0d1ff91cbcc6fbd7876330c4927736b394924036805528a5cd87ffb4.json`
- Result SHA-256: `1e0ded1a0d1ff91cbcc6fbd7876330c4927736b394924036805528a5cd87ffb4`

The preserved v1 result is invalid for latency and the final report because B
omitted the reused A latency. Its invalidation record is retained next to it.
The valid v2 measurements are unchanged; only its automated recommendation is
superseded by the bound decision-correction record so it follows the frozen
missing-authentic-data rule.

### A: rg plus live read

| Stratum | Correct files | Correct symbols | Irrelevant files | Mean MRR | Total latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| exact code | 3/3 | not applicable | 0 | 1.00 | 123.56 ms |
| current SymbolIndexer cases | 5/5 | 6/7 | 4 | 0.84 | 199.78 ms |

### B: A plus current SymbolIndexer

| Stratum | Correct files | Correct symbols | Irrelevant files | Mean MRR | Total latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| exact code | 3/3 | not applicable | 0 | 1.00 | 123.58 ms |
| current SymbolIndexer cases | 5/5 | 7/7 | 3 | 1.00 | 230.27 ms |

The one-time SymbolIndexer build indexed 175 files and extracted 1,491 symbols
in 2,580.86 ms. B added one previously missed symbol on one of five structural
cases, improved first-file rank on one case, and returned one fewer irrelevant
file. It did not reach the frozen threshold of additional findings on at least
two structural cases.

### D: synthetic BM25 plumbing plus source verification

- Hints found: 4/4 at rank 1;
- source-verification result: 4 rejected, 0 verified, 0 unresolved;
- total latency: 187.67 ms;
- evidence grade: `synthetic_plumbing_only`;
- authentic product-value conclusion: prohibited.

## Local Limitations

- One small frozen case set on one repository/worktree snapshot.
- Structural cases contain explicit symbol names and therefore do not test vague
  Hook discovery.
- A returns one ranked result per file, while B can return multiple symbols from
  a file; symbol counts reflect those current interfaces.
- B measures a regex symbol table, not AST/LSP/call-graph navigation.
- No authentic D corpus exists.
- No statistical significance, downstream modification, task success, or
  production behavior was measured.

## Four-Way Decision

**Decision: evidence is insufficient; retain `rg + live read` and do not expand
retrieval infrastructure now.**

Reasons:

1. A found all correct files in all eight applicable code cases.
2. B improved additional symbol findings on only one of five structural cases,
   below the frozen two-case threshold. The result is useful but not enough to
   prioritize SymbolIndexer deepening over product work.
3. D has no authentic corpus, so community BM25 product value remains unknown.

Return to the product capability queue. Reopen a bounded Symbol experiment only
when real tasks expose repeated structural-navigation failures. Reopen D only
after a small authentic, traceable community/history set is available; do not
build a production loader merely to obtain that set.
