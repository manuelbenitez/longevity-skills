# longevity-skills

A set of Claude Code skills for generating science-backed longevity food content. Grounded in "The Path to Longevity" by Luigi Fontana.

## Copyright — what MUST stay local

This repo is public. The source books are copyrighted. **Never commit, push, or
otherwise publish book-derived content.** Doing so will break the project.

**Never commit** (stays local only):
- `data/book-raw/` — the book itself (epub, PDF, chapter text)
- `data/book-extracts/` — extracted claims, quotes, references, page numbers
- `data/dedup/` — dedup reports derived from book extracts

**Safe to commit** (final outputs with cited references, not reproductions):
- `data/ingredients/` — enriched ingredient profiles (web research + brief cited claims)
- `content/wiki/` — wiki entries
- `content/recipes/` — recipes

The gitignore enforces this, but still verify before any `git add`. If a file
contains verbatim book passages, long quotes, or chapter text, it does not belong
in a commit — no matter which directory it lives in.

## Skill routing

When the user's request matches an available skill, invoke it using the Skill tool
as your FIRST action. Do NOT answer directly when a skill exists for the task.

- "extract", "process chapter", "book claims", "parse" -> invoke extract-book-knowledge
- "expand groups", "split categories", "atomise ingredients" -> invoke expand-ingredient-groups
- "check duplicates", "compare ingredients", "what's new", "dedup" -> invoke dedup-ingredients
- "research", "enrich", "look up ingredient", "studies" -> invoke research-ingredient
- "wiki", "article", "entry", "write about" -> invoke generate-wiki-entry
- "recipe", "cook", "meal", "dish" -> invoke generate-recipe (single recipe, 2-3 slug input)
- "batch recipes", "10 recipes", "expand recipe catalog", "close the recipe gap" -> invoke batch-recipes (orchestrates 10 drafts in one run)

## Pipeline order

```
data/book-raw/*.txt          (user input: book chapter text)
       |
       v
/extract-book-knowledge
       |
       v
data/book-extracts/*.json    (structured claims per chapter)
       |
       v
/expand-ingredient-groups
       |
       v
data/book-extracts/ingredients-master.json  (groups expanded, members linked)
       |
       v
/dedup-ingredients
       |
       v
data/dedup/*.json            (new / fuzzy / existing buckets)
       |
       v
/research-ingredient
       |
       v
data/ingredients/*.json      (enriched profiles with web research)
       |                |
       v                v
/generate-wiki-entry   /generate-recipe   /batch-recipes
       |                |                  |
       v                v                  v
content/wiki/*.md      content/recipes/*.md   content/recipes/en/_drafts/*.md
                                                 |
                                                 v (user: git mv keepers / rm rejects)
                                               content/recipes/en/*.md
```

Note on `/batch-recipes`: it runs from the **my-longevity-wiki** repo root, reads
ingredient JSONs from this repo via `$LONGEVITY_SKILLS_DIR` (defaults to
`~/Development/longevity-skills`), and writes drafts to a `_drafts/` subfolder
inside the wiki's content tree. The wiki's data loader filters by
`.endsWith(".md")` on `readdirSync`, so a `_drafts/` directory is invisible to the
build — safe to leave drafts in place between sessions.

## Data directory conventions

Skills write output relative to the current working directory:

- `data/book-raw/` -- book epub, PDF, or plain text chapter files (user provides these)
- `data/book-extracts/` -- book extract JSON (output of /extract-book-knowledge)
- `data/dedup/` -- dedup reports (output of /dedup-ingredients)
- `data/ingredients/` -- ingredient profile JSON (output of /research-ingredient)
- `content/wiki/` -- wiki entry Markdown (output of /generate-wiki-entry)
- `content/recipes/` -- recipe Markdown (output of /generate-recipe)
- `content/recipes/en/_drafts/` -- unreviewed drafts from /batch-recipes (lives in the my-longevity-wiki repo, not here; user promotes with `git mv`)

## Schemas

JSON Schemas are in the `schemas/` directory of this repo:
- `schemas/book-extract.schema.json` -- Book Extract format
- `schemas/ingredient.schema.json` -- Ingredient Profile format

## Quality rubric

Every health claim must include:
1. A specific mechanism of action
2. At least one citation (book page ref, PubMed ID, or "book-assertion")
3. Dosage/quantity if specified
4. A confidence level (high/medium/low)
