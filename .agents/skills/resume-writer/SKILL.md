---
name: resume-writer
description: Write evidence-grounded Chinese or English resume project experience for this repository when the user asks for resume or interview material.
---

# Resume Writer

Turn verified project work and the user's real contribution into concise resume
material. Treat repository references as prompts for investigation, not as
current facts.

## Gather only missing inputs

Ask only for information that changes the result:

- Target role and language. 为什么要有它： role and language determine which
  verified details deserve space.
- The user's actual responsibility and contribution boundary. 为什么要有它：
  repository capability does not prove personal ownership.
- Real business context when the user wants a business-specific narrative.
  为什么要有它： a plausible scenario is not evidence that it happened.
- A preferred format or length when it matters. 为什么要有它： resume formats
  vary and this skill does not impose one universal template.

Do not require a fixed questionnaire. 为什么要有它： the user may already have
provided everything needed.

## Build the evidence set

1. Read [references/resume_principles.md](references/resume_principles.md).
   为什么要有它： it defines the claim and contribution boundaries.
2. Read only the relevant direction in
   [references/project_highlights.md](references/project_highlights.md).
   为什么要有它： loading every historical direction wastes context and can
   promote stale material.
3. Verify selected facts against current source, focused tests, receipts, or
   user-provided evidence before using them. 为什么要有它： plans and old
   summaries do not prove current behavior.
4. Label an unsupported item as not demonstrated or leave it out.
   为什么要有它：a resume must not turn a possible capability into an achieved result.

## Write the project experience

Organize the content around the relationship among:

- problem and operating context;
- technical tradeoff or design decision;
- the user's concrete action and contribution;
- observed verification or outcome;
- boundary, limitation, or scale actually supported by evidence.

Use the structure requested by the user. When none is specified, produce a
compact project heading followed by three to five bullets. 为什么要有它： the
content relationships matter more than a fixed four-part template.

Use numbers only when the user or a bound artifact supplies them. Do not invent
ranges, targets, accuracy gains, latency, document counts, test counts, Provider
counts, or completion rates. 为什么要有它： marking a number as “suggested”
does not make it a truthful resume fact.

Separate implementation from evaluation and runtime observation.
为什么要有它：code presence, a passing unit test, a build, and production use establish
different claim levels.

Keep “designed,” “implemented,” “led,” and similar ownership verbs aligned with
the user's stated role. 为什么要有它： project evidence alone cannot establish
who performed the work.

## Deliver

Return the requested resume text and a short evidence note for any material fact
that may need user confirmation. 为什么要有它： the user should be able to
distinguish verified content from missing personal context.

Provide interview follow-ups, translations, or alternate role versions only
when requested. 为什么要有它： optional deliverables should not expand every
resume request.
