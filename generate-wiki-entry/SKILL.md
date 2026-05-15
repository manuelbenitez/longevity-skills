---
name: generate-wiki-entry
version: 0.2.0
description: |
  Generate readable wiki entries from ingredient profiles. Transforms structured
  JSON ingredient data into compelling Markdown articles written for a general
  audience with the depth of a good food science article.
  Use when asked to "generate wiki", "write article", "create entry", or "wiki page".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Agent
---

# Generate Wiki Entry

Transform an ingredient profile into a readable, publishable wiki entry.

## Model Config

```bash
_MODEL=$(python3 -c "import json; d=json.load(open('.longevity-skills.json')); print(d['models'].get('wiki','haiku'))" 2>/dev/null || echo "haiku")
echo "MODEL: $_MODEL (wiki)"
```

Default: haiku. Content generation from structured JSON — template-filling work where
Haiku is sufficient. Override to "sonnet" in `.longevity-skills.json` if output quality
needs improvement.

**When generating the wiki entry, use the Agent tool with `model: "<value of _MODEL>"`.**
This dispatches the writing work to the configured model, not the orchestrating model.

## Input

JSON file at `<wiki_data_dir>/ingredients/{ingredient-slug}.json` (output of /research-ingredient).
Profiles carry per-claim `book_slug` and a denormalized `source_books[]` array —
both books and individual claims are first-class.

## Output

Markdown file at `content/wiki/{ingredient-slug}.md` with YAML frontmatter for the website.

## Multi-book rendering

When `source_books[]` contains more than one slug, surface that in the byline and
group `book_claims` by `book_slug` in the references section. For each book, write
a sub-section showing the claims that book asserts. If two claims have similar
`text` but different `mechanism` (cross-book disagreement), surface them in a
"What the books disagree on" callout below the main claims section.

Look up each book_slug → human name via `data/book-raw/<slug>/_book.json`:

```bash
python3 scripts/lib.py books
```

## Usage

```
/generate-wiki-entry turmeric
```

## Article Structure

1. **What It Is** — Brief introduction
2. **Why It Matters for Longevity** — Key health claims with mechanisms
3. **How to Use It** — Preparation methods, consumption recommendations
4. **What to Pair It With** — Synergies and culinary pairings
5. **The Science** — Detailed claims with citations

## Dispatch Pattern

After reading the ingredient JSON, dispatch the article writing to a sub-agent:

```
Use the Agent tool with:
  model: <value of _MODEL read from config>
  prompt: "Write a wiki entry for [ingredient]. Here is the full ingredient profile:
           [paste the JSON]. Follow this structure: [article structure above].
           Quality bar: every health claim must include its mechanism of action and
           at least one citation. Conversational but scientifically precise tone."
```

Write the sub-agent's output directly to `content/wiki/{ingredient-slug}.md`.

<!-- TODO: Add YAML frontmatter spec, quality-check pass after generation -->
