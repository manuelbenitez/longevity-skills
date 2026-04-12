---
name: generate-wiki-entry
version: 0.1.0
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
---

# Generate Wiki Entry

Transform an ingredient profile into a readable, publishable wiki entry.

## Input

JSON file at `data/ingredients/{ingredient-slug}.json` (output of /research-ingredient).

## Output

Markdown file at `content/wiki/{ingredient-slug}.md` with YAML frontmatter for the website.

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

<!-- TODO: Implement full skill logic — JSON reading, article generation, frontmatter, quality checks -->
