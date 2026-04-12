# Contributing

## Adding a new skill

1. Create a directory: `mkdir my-new-skill`
2. Add a `SKILL.md` file with YAML frontmatter and instructions
3. Run `./setup` to register it with Claude Code

## SKILL.md format

Every skill needs a SKILL.md file with this structure:

```yaml
---
name: my-skill-name
version: 0.1.0
description: |
  One paragraph describing what this skill does and when to use it.
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
---

# Skill Title

Markdown instructions that Claude Code follows when the skill is invoked.
```

### Required frontmatter fields

- `name` -- skill identifier, used for invocation (`/name`)
- `version` -- semantic version
- `description` -- when and why to use this skill
- `allowed-tools` -- which Claude Code tools the skill can use

### Common tools

- `Bash` -- run shell commands
- `Read` -- read files
- `Write` -- create/overwrite files
- `Edit` -- modify existing files
- `Grep` -- search file contents
- `Glob` -- find files by pattern
- `WebSearch` -- search the web (for research skills)

## Schema conventions

- JSON Schema draft 2020-12
- Files go in `schemas/` with `.schema.json` extension
- Skills reference schemas by relative path from the repo root

## Data directory conventions

Skills write output relative to the user's current working directory:

- `data/` -- structured data (JSON)
- `content/` -- generated content (Markdown)

Input and output paths should be documented in each skill's SKILL.md.

## Testing a skill

1. Set up a test project directory
2. Add sample input data
3. Run the skill: `/<skill-name>`
4. Validate output against the schema
5. Read the output -- would you publish it?
