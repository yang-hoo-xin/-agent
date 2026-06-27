# Git Workflow

This repository uses Git as the rollback and audit layer for the Controlled Mod Agent Platform.

## Branch Policy

- `main` is the stable baseline branch.
- Use short-lived branches for implementation work:
  - `feat/phase-b-artifact-contract`
  - `feat/graph-routing`
  - `fix/proposal-review-gate`
- Do not force-push `main`.
- Prefer `git revert` over history rewrites after a commit has been pushed.

## Commit Policy

Each meaningful agent iteration should end in a small commit that can be reviewed and reverted.

Recommended commit format:

```text
<type>: <short outcome>

Phase: <phase or feature area>
Evidence: <tests, build, graph run, or manual audit>
Risk: <low|medium|high>
Rollback: git revert <commit>
```

Use these common commit types:

- `feat`: new user-visible or workflow behavior.
- `fix`: bug fix or failed-verification repair.
- `test`: test-only change.
- `docs`: documentation-only change.
- `chore`: repository, tooling, or baseline setup.

## Verification Before Push

Run the most relevant checks before pushing. For the current controlled-agent core, the focused baseline is:

```bash
pytest tests/unit/test_workflow_graph.py tests/unit/test_proposal_review.py tests/unit/test_planning.py tests/unit/test_evidence_retrieval.py tests/unit/test_knowledge_base.py tests/unit/test_artifact_contract.py tests/unit/test_stub_nodes.py tests/unit/test_permissions.py tests/unit/test_artifact_store.py tests/unit/test_mod_agent_state.py tests/unit/test_mod_agent_cli.py tests/unit/test_git_repository.py
```

Also audit staged files before committing:

```bash
git status --short
git diff --cached --stat
```

Generated artifacts, real game outputs, local caches, and binary mod build products must stay out of Git.

## Rollback

For a pushed commit:

```bash
git log --oneline --decorate
git revert <commit>
git push origin main
```

For an unpushed local commit:

```bash
git log --oneline --decorate -1
git revert <commit>
```

Avoid `git reset --hard` unless the user explicitly asks for destructive cleanup.

## Baseline Tags

Create tags for stable milestones:

```bash
git tag baseline-controlled-agent-v0
git push origin baseline-controlled-agent-v0
```

Rollback to inspect a milestone:

```bash
git show baseline-controlled-agent-v0
git checkout -b inspect/baseline-controlled-agent-v0 baseline-controlled-agent-v0
```

## Agent Audit Rule

When the workflow starts performing real code changes, every decision artifact and patch proposal should record the Git commit or planned commit it belongs to. The target state is:

```text
natural language request
  -> evidence artifact
  -> implementation plan
  -> patch proposal
  -> validation output
  -> Git commit
```

This makes every agent-produced change reviewable, replayable, and reversible.
