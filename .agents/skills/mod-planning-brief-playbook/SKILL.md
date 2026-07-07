---
name: mod-planning-brief-playbook
description: "Process-only planning brief playbook for the Controlled Mod Agent Platform. Use when turning a natural language mod idea, planning discussion, gameplay request, UI feedback request, config-only request, runtime diagnostics request, hook-likely request, or unclear mod concept into a negotiated mod_planning_brief before feature_spec generation. Do not use as a RAG extractor implementation, feature_spec generator, code generator, runtime Skill system, or source of product facts, schemas, current state, test results, or artifact payloads."
---

# Mod Planning Brief Playbook

## Boundary

Use this skill before `feature_spec` when a user brings a natural language mod idea that still needs planning, evidence lookup direction, risk classification, or user negotiation. Keep product facts, current state, interface contracts, artifact payloads, queue status, and test evidence in `DEV_SPEC.md`, `docs/PROJECT_STATE.md`, `docs/IMPLEMENTATION_QUEUE.md`, `docs/SPEC_COVERAGE_MATRIX.md`, artifacts, logs, source files, command output, and supplied evidence.

Do not store current branch facts in this skill. Read current files before naming paths, fields, commands, artifact schemas, tests, source types, domain profiles, or current evidence. If required evidence is missing, ask for it or mark it unavailable instead of guessing.

This skill is not a RAG implementation, natural-language-to-RAG extractor, `feature_spec` generator, code generator, hook scanner, runtime Skill registry, Skill selector, Skill loader, LangGraph selected-skill node injection, or Skill output validator. It describes the planning procedure and the expected `mod_planning_brief` handoff artifact shape.

## Planning Inputs

Before writing a planning brief, locate or request:

1. Raw user request and any follow-up constraints.
2. Target game, target mod, expected user-visible behavior, and non-goals when known.
3. Current source, game profile, prior artifacts, restored historical records, delivery lessons, symbol search results, docs, logs, or supplied evidence that the request depends on.
4. Existing feature specification, evidence pack, proposal, review, runtime diagnosis, hook discovery, repair notes, or handoff summary when the planning request continues prior work.
5. Explicit approvals or forbidden areas for real game operations, game directory writes, process control, network access, and MCP write operations.

Separate current-branch evidence from restored history. Treat `docs/audits/LOOP_HISTORY.md` as reconstruction support unless referenced files exist now and relevant checks were rerun.

## Request Type Classification

Classify the request before selecting a planning direction:

```text
request_type:
- config-only
- UI feedback
- gameplay behavior
- runtime diagnostics
- hook-required
- unknown / needs evidence
```

Use the narrowest supported type. If current evidence cannot distinguish config/UI work from gameplay or hook-required work, classify as `unknown / needs evidence` and ask for evidence or present safe planning options.

## Planning Procedure

1. Extract user intent
   - Preserve the raw request.
   - Normalize the goal into concrete user-visible behavior.
   - Identify target game, target mod, expected behavior, constraints, and non-goals.
   - Mark unknown identifiers, paths, fields, classes, methods, logs, commands, and acceptance signals explicitly.

2. Classify request type and risk
   - Use the request type list above.
   - Note hook likelihood, runtime risk, permission risk, and evidence risk.
   - Do not promote a request into code generation when the type or risk depends on unsupported names or inferred signatures.

3. Create `knowledge_query_plan`
   - Plan lookup before claiming design direction.
   - Include source types only when they are relevant to the current request.
   - Prefer current source, game profile, prior artifacts, delivery lessons, symbol search, docs, logs, and supplied evidence before optional dense/vector or multimodal expansion.

4. Bind retrieved experience
   - Record relevant lessons, failed patterns, reusable patterns, and unavailable evidence.
   - Keep restored history separate from current-branch evidence.
   - Do not treat historical records, auxiliary retrieval, or generated prose as proof of current behavior.

5. Present planning options
   - Offer one or more scoped options when evidence allows multiple paths.
   - For each option, state expected complexity, hook likelihood, risk, required evidence, and acceptance signal.
   - Prefer low-risk config/UI paths when they satisfy the user-visible goal.
   - Block or ask questions when no option is evidence-backed enough for handoff.

6. Select or confirm a plan
   - Record selected scope, constraints, non-goals, and whether the user confirmed the plan.
   - If the user has not confirmed and the choice is material, ask a concise clarification question.
   - Do not fabricate confirmation.

7. Prepare handoff
   - Hand `feature_spec_guidance` to feature specification generation.
   - Hand hook uncertainty to hook discovery.
   - Hand risk and evidence boundaries to patch review.
   - Hand expected runtime signals to runtime diagnosis.

## Output Format

Use this default structure for planning brief reports:

```text
Decision: ready_for_feature_spec | needs_clarification | needs_evidence | blocked

mod_planning_brief:
  user_intent:
    raw_request:
    normalized_goal:
    target_game:
    target_mod:
    expected_user_visible_behavior:
  request_type:
    value:
    rationale:
  knowledge_query_plan:
    source_types:
      - current_source
      - game_profile
      - prior_artifacts
      - delivery_lessons
      - symbol_search
      - docs
    queries:
  retrieved_experience:
    relevant_lessons:
    failed_patterns:
    reusable_patterns:
    unavailable_evidence:
  planning_options:
    - option:
      expected_complexity:
      hook_likelihood:
      risk:
      required_evidence:
      acceptance_signal:
  selected_plan:
    scope:
    constraints:
    non_goals:
    user_confirmed:
  handoff:
    feature_spec_guidance:
    hook_discovery_guidance:
    patch_review_notes:
    runtime_verification_expectations:

Verification boundary:
- What the planning brief proves
- What it does not prove

Next action:
- feature_spec | ask user | evidence lookup | hook discovery | stop
```

## Stop Conditions

Stop and report clearly when:

- Required target game, target mod, behavior, acceptance signal, source path, symbol, log marker, command, or artifact reference cannot be verified from current files or supplied evidence.
- The request needs real game launch, DLL copy, persistent log collection, screenshot capture, process control, network access, or MCP write operations without explicit approval.
- The user expects implemented natural-language-to-RAG extraction, accumulated-experience retrieval, `feature_spec` generation, code generation, or runtime validation from this skill alone.
- The planning result would rely only on restored history, auxiliary retrieval, or generated prose without current evidence.
- The work turns into platform implementation from `DEV_SPEC.md`; use `auto-coder` for that work.