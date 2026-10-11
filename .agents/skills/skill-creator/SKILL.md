---
name: skill-creator
description: Create or update a project-local Codex skill when the user asks for a reusable skill package or a focused change to one.
---

# Skill Creator

Create the smallest skill package that changes Codex decisions for the requested
task. Preserve the user's intended trigger, scope, and authorization boundary.

## Define the skill

- Identify concrete requests that should activate the skill and nearby requests
  that should not. 为什么要有它： the frontmatter description controls
  discovery before the body is loaded.
- Put only the actual capability and trigger in `description`. 为什么要有它：
  exhaustive feature lists attract unrelated work.
- Keep stable shared guidance in `SKILL.md`; route substantial mode-specific
  detail to a focused reference. 为什么要有它： progressive loading avoids
  filling context with irrelevant procedures.
- Add scripts only when deterministic repeated logic materially improves the
  task. 为什么要有它： bundled code adds a maintenance and verification
  obligation.
- Do not add README files, changelogs, quick references, placeholders, or example
  directories without a concrete use. 为什么要有它： ancillary files dilute
  the skill's maintained contract.

Read [references/workflows.md](references/workflows.md) only for a real
multi-stage or branching workflow. Read
[references/output-patterns.md](references/output-patterns.md) only when the
output has a non-obvious format contract. 为什么要有它： ordinary skills do
not need both references.

## Initialize

For a new project-local skill, the current helper creates only `SKILL.md` by
default:

```text
python .agents/skills/skill-creator/scripts/init_skill.py <skill-name> --path .agents/skills
```

Pass `--include-examples` only when all three example resource types are useful.
为什么要有它： the compatibility flag retains the former examples while the
default avoids unused placeholders.

The initializer does not create `agents/openai.yaml`. Add UI metadata only when
the requested skill needs it, and keep it consistent with the frontmatter. Why
this exists: the documented interface must match the current helper output.

Do not initialize an existing skill again. 为什么要有它： the helper refuses
an existing directory and is not an update mechanism.

## Write and validate

- Use lowercase letters, digits, and hyphens for the exact skill folder and
  frontmatter name. 为什么要有它： the validator enforces that identifier
  shape.
- Require non-empty `name` and `description`. 为什么要有它： empty metadata
  makes the skill undiscoverable.
- Preserve supported optional frontmatter already used by the skill.
  为什么要有它：a focused update should not erase unrelated metadata.
- Test changed scripts with the smallest meaningful behavior check.
  为什么要有它：source inspection does not prove the helper works.

Validate with:

```text
python .agents/skills/skill-creator/scripts/quick_validate.py <skill-directory>
```

为什么要有它： the validator checks frontmatter structure and naming. It does
not prove that the skill makes good decisions.

Package only when a distributable `.skill` archive is requested:

```text
python .agents/skills/skill-creator/scripts/package_skill.py <skill-directory> [output-directory]
```

为什么要有它： packaging is a separate output operation. The packager excludes
its own archive, Python caches, and common temporary files.
