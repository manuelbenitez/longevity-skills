# longevity-skills

A set of Claude Code skills for generating science-backed longevity food content. Grounded in "The Path to Longevity" by Luigi Fontana.

## Skill routing

When the user's request matches an available skill, invoke it using the Skill tool
as your FIRST action. Do NOT answer directly when a skill exists for the task.

- "extract", "process chapter", "book claims", "parse" -> invoke extract-book-knowledge
- "research", "enrich", "look up ingredient", "studies" -> invoke research-ingredient
- "wiki", "article", "entry", "write about" -> invoke generate-wiki-entry
- "recipe", "cook", "meal", "dish" -> invoke generate-recipe

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
/research-ingredient
       |
       v
data/ingredients/*.json      (enriched profiles with web research)
       |                |
       v                v
/generate-wiki-entry   /generate-recipe
       |                |
       v                v
content/wiki/*.md      content/recipes/*.md
```

## Data directory conventions

Skills write output relative to the current working directory:

- `data/book-raw/` -- book PDF or plain text chapter files (user provides these)
- `data/book-extracts/` -- book extract JSON (output of /extract-book-knowledge)
- `data/ingredients/` -- ingredient profile JSON (output of /research-ingredient)
- `content/wiki/` -- wiki entry Markdown (output of /generate-wiki-entry)
- `content/recipes/` -- recipe Markdown (output of /generate-recipe)

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
