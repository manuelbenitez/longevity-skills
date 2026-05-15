# longevity-skills

A set of Claude Code skills for generating science-backed longevity food content
from peer-reviewed books. Multi-book aware: every claim is tagged with the book
it came from, so two books talking about the same ingredient produce one merged
profile with provenance preserved.

Books currently processed:
- "The Path to Longevity" by Luigi Fontana
- "The Longevity Diet" by Valter Longo

## Copyright — what MUST stay local

This repo is public. The source books are copyrighted. **Never commit, push, or
otherwise publish book-derived content.** Doing so will break the project.

**Never commit** (stays local only):
- `data/book-raw/<slug>/` — the book itself (epub, PDF, chapter text). The
  `_book.json` manifest inside each book dir IS safe; the source file is not.
- `data/book-extracts/<slug>/` — extracted claims, quotes, references
- `data/dedup/` — dedup reports derived from book extracts
- `data/.invalid/` — validator forensics tray

**Safe to commit** (final outputs with cited references, not reproductions):
- Ingredient profiles in the wiki repo at `<wiki_data_dir>/ingredients/`
- `content/wiki/` — wiki entries
- `content/recipes/` — recipes

The gitignore enforces this, but still verify before any `git add`. If a file
contains verbatim book passages, long quotes, or chapter text, it does not belong
in a commit — no matter which directory it lives in.

## Skill routing

When the user's request matches an available skill, invoke it using the Skill tool
as your FIRST action. Do NOT answer directly when a skill exists for the task.

- "extract", "process chapter", "book claims", "parse" → invoke extract-book-knowledge
- "expand groups", "split categories", "atomise ingredients" → invoke expand-ingredient-groups
- "check duplicates", "compare ingredients", "what's new", "dedup" → invoke dedup-ingredients
- "research", "enrich", "look up ingredient", "studies" → invoke research-ingredient
- "wiki", "article", "entry", "write about" → invoke generate-wiki-entry
- "recipe", "cook", "meal", "dish" → invoke generate-recipe (single recipe, 2-3 slug input)
- "batch recipes", "10 recipes", "expand recipe catalog", "close the recipe gap" → invoke batch-recipes

## Pipeline (multi-book)

```
                  data/book-raw/<slug>/_book.json
                  { slug, title, author }  ← user provides once
                              |
                              v
            data/book-raw/<slug>/*.{epub,pdf,txt}
                              |
                              v
                  /extract-book-knowledge <slug>
                              |
                              v
    data/book-extracts/<slug>/chapter-*.json   (validated against schema)
                              |
                              v
                  /expand-ingredient-groups <slug>
                              |
                              v
    data/book-extracts/<slug>/ingredients-master.json
                              |
                              v
                  /dedup-ingredients <slug>
                              |   reads:  <wiki_data_dir>/ingredients/*.json
                              v
    data/dedup/<slug>-dedup-report.json   (header: book_slug, title, author)
       four buckets: new | new-to-book | existing-same-book | fuzzy
                              |
                              v
                  /research-ingredient --book <slug>
                              |   per-bucket actions:
                              |     new           → full enrich + write
                              |     new-to-book   → append claims (no LLM)
                              |     existing-same → skip
                              |     fuzzy         → human review
                              v
    <wiki_data_dir>/ingredients/<slug>.json   (validated; .invalid/ on failure)
    each claim tagged with book_slug; top-level source_books[] denormalized
                              |
                              |
                              v
            /generate-wiki-entry   /generate-recipe   /batch-recipes
                  cite all source_books[]; group claims by book in references
```

## Adding a new book

1. Pick a slug (e.g. `attia-outlive`). Use `python3 scripts/lib.py slugify "Title"`
   if you want a deterministic hint, but the slug is yours to choose and freeze.
2. Create `data/book-raw/<slug>/_book.json`:
   ```json
   {"slug": "attia-outlive", "title": "Outlive", "author": "Peter Attia"}
   ```
3. Place the source file (epub/PDF/txt) under `data/book-raw/<slug>/`.
4. Run the pipeline:
   ```
   /extract-book-knowledge attia-outlive
   /expand-ingredient-groups attia-outlive
   /dedup-ingredients attia-outlive
   /research-ingredient --book attia-outlive
   ```
5. Run the validator on the new book's outputs:
   ```
   python3 scripts/lib.py validate-all data/
   ```

## Data directory conventions

Per-book directories under the skills repo:
- `data/book-raw/<slug>/` — sources + manifest (gitignored except CLAUDE.md notes)
- `data/book-extracts/<slug>/` — chapter JSONs + master + scan plan
- `data/dedup/<slug>-dedup-report.json` — one report per book
- `data/.invalid/` — validator tray (gitignored)

Cross-repo:
- `<wiki_data_dir>/ingredients/` — flat dir of profiles. One profile may cite
  multiple books. Resolved via `LONGEVITY_WIKI_DATA_DIR` env or
  `.longevity-skills.json[wiki_data_dir]`.

## Schemas

- `schemas/book-extract.schema.json` — Book Extract format
- `schemas/ingredient.schema.json` — Ingredient Profile format

**Canonical claim shape** (NEVER deviate; the validator rejects legacy shapes):

```json
{
  "text": "string — the claim itself",
  "mechanism": "string",
  "recommendation": "string|null — dosing/preparation",
  "reference": "string — study or 'book-assertion'",
  "confidence": "high|medium|low",
  "book_slug": "string — required on ingredient profiles, set on chapter JSONs"
}
```

Validate any JSON: `python3 scripts/lib.py validate {book-extract|ingredient} <file>`
Validate everything under a data root: `python3 scripts/lib.py validate-all data/`

## LLM eval procedure (manual; documented as a TODO for automation)

After significant prompt changes to extract-book-knowledge or research-ingredient,
re-run on chapter-04 of each book in `data/book-raw/<slug>/`. The validator must
pass. If a regression appears, fix the prompt — do not bypass the validator.

## Testing

Run `pytest tests/ -v` from the repo root. The suite covers slugify, validator,
migration logic, and enrich merge semantics. The 5 IRON-RULE regressions are:

1. Migration produces schema-valid output for every wiki profile
2. Migration is idempotent (re-running is a no-op)
3. Canonical shape flows end-to-end (no `claim`/`study_ref` rename)
4. Validator rejects the legacy singular `source_book` string
5. Second-book merge preserves first-book `supplementary_research` byte-identical

CI: `.github/workflows/test.yml` runs the suite on push + PR.

## Quality rubric

Every health claim must include:
1. A specific mechanism of action
2. At least one reference (book page, PubMed ID, or "book-assertion")
3. A `recommendation` field if the book specifies dosing; null otherwise
4. A confidence level (high/medium/low)
5. A `book_slug` identifying its source book
