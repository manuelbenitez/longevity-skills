---
name: research-ingredient
version: 0.1.0
description: |
  Enrich ingredient profiles with web research. Combines book-extracted claims
  with PubMed, Examine.com, and culinary sources to produce comprehensive
  ingredient profiles with flavor data, pairings, and synergies.
  Use when asked to "research", "enrich", "look up ingredient", or "find studies".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - WebSearch
---

# Research Ingredient

Enrich an ingredient profile by combining book-extracted claims with web research.

## Input

An ingredient name (passed as argument). The skill reads book extract data from
`data/book-extracts/*.json` to find claims about this ingredient.

## Output

JSON file at `data/ingredients/{ingredient-slug}.json` conforming to the Ingredient Profile
Schema at `schemas/ingredient.schema.json` in the longevity-skills repo.

## Usage

```
/research-ingredient turmeric
```

## Research Protocol

1. Read all book extract files, collect claims for this ingredient
2. Search Examine.com for the ingredient (1 web query)
3. Search PubMed for "[ingredient] longevity OR healthspan" (1 web query)
4. Search culinary sources for flavor/pairing info (1 web query)
5. Minimum 2 corroborating sources beyond the book per health claim

## Caching

Results stored in the output JSON with a `last_researched` timestamp. Re-running
only re-fetches if `research_status` is "partial"/"book-only" or data is >30 days old.

<!-- TODO: Implement full skill logic — book extract reading, web research, profile assembly, caching -->
