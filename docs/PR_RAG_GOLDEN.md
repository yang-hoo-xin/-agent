# PR retrieval regression check

The `RAG retrieval golden` job runs for pull requests and pushes through the
existing CI workflow. It builds and queries the actual BM25 implementation over
eight curated questions and nine hash-bound source spans from an archived Git
revision. It uses no model, provider credentials, game installation or live
knowledge-store service.

## Run locally

```console
python scripts/check_rag_golden.py --output /absolute/output/report.json
```

The report contains the dataset and source identities, current retrieval
measurements, baseline comparisons and failure details. A successful process
exits 0; measured regressions or failed measurements exit 1; invalid baseline
configuration or output errors exit 2. The workflow uploads a produced report
even when the check fails.

## What the check establishes

- Each archived source span is checked against its registered Git blob hash.
  为什么要有它：固定语料使 PR 之间的检索变化可以比较。
- Every case must be measured, and its Recall@3, reciprocal rank and nDCG@3
  must not fall below the recorded baseline. Improvements are accepted.
  为什么要有它：逐题比较防止总均值掩盖个别案例退化，缺测不能伪装成成功。
- Dataset and baseline changes require an explicit review of the changed
  labels, source identities and acceptance scope; the command does not update
  its baseline automatically.
  为什么要有它：不能用自动重写期望结果让失败变绿。

This is a small archived-source retrieval regression set: seven development
cases and one reserved case. The labels are fixture annotations; they have no
recorded independent human adjudication. It is not evidence of answer
faithfulness, end-to-end Mod repair success, or a stable model-latency P95.
Those measurements require the separately recorded real-model task runs.

## Making failure block a merge

After the workflow has run, a repository administrator can add the exact check
name `RAG retrieval golden` to the target branch's required status checks.
Preserve the branch's existing protections and required checks.
为什么要有它：工作流返回失败与 GitHub 实际阻止合并是两层事实，不能混报。

Count actual regressions, execution failures and deliberate fault-injection
checks separately. A demonstration that the gate rejects an injected defect
must not be reported as a naturally occurring quality regression.
为什么要有它：CI 记录用于复查真实结果，不能为了简历累积虚假的拦截次数。
