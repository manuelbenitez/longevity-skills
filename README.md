# longevity-skills

Claude Code skills for generating science-backed longevity food content. A content pipeline that turns book knowledge into structured ingredient profiles, wiki entries, and chef-quality recipes.

Grounded in "The Path to Longevity" by Luigi Fontana.

## Skills

| Skill | What it does | Input | Output |
|-------|-------------|-------|--------|
| `/extract-book-knowledge` | Extract food claims from book chapters | `data/book-raw/*` (epub, PDF, or txt) | `data/book-extracts/*.json` |
| `/expand-ingredient-groups` | Split category entries (e.g. "cruciferous vegetables") into individual members, inheriting parent claims | `data/book-extracts/ingredients-master.json` | updates same file in-place |
| `/dedup-ingredients` | Compare extracted ingredients against an existing wiki to bucket them as existing / fuzzy / new | `ingredients-master.json` + wiki dir | `data/dedup/*-dedup-report.json` |
| `/research-ingredient` | Enrich with web research (PubMed, Examine) | ingredient name | `data/ingredients/*.json` |
| `/generate-wiki-entry` | Write readable wiki articles | ingredient JSON | `content/wiki/*.md` |
| `/generate-recipe` | Create chef-quality recipes | 2-3 ingredient slugs | `content/recipes/*.md` |

## Installation

```bash
git clone <repo-url> ~/.claude/skills/longevity-skills
cd ~/.claude/skills/longevity-skills
./setup
```

The setup script registers all skills with Claude Code. No dependencies required.

## Usage

### 1. Set up a content project

```bash
mkdir my-longevity-wiki && cd my-longevity-wiki
mkdir -p data/book-raw
```

### 2. Add the book

Drop the epub (or PDF) into your project:

```bash
cp ~/Downloads/the-path-to-longevity.epub data/book-raw/
```

The skill reads the epub directly (each chapter is an HTML file inside the zip).
It scans the table of contents, identifies food chapters, extracts claims,
and pulls references from the bibliography. No copy-pasting needed.

Plain text files (`data/book-raw/chapter-*.txt`) also work as a fallback.

### 3. Run the pipeline

```bash
# In Claude Code, inside your content project:
/extract-book-knowledge        # Scan full book, extract all ingredients + claims
/expand-ingredient-groups      # Split "nuts", "leafy greens", etc. into members
/dedup-ingredients             # Bucket against existing wiki: existing / fuzzy / new
/research-ingredient turmeric  # Enrich one ingredient with web research
/generate-wiki-entry turmeric  # Write the wiki article
/generate-recipe turmeric black-pepper chickpeas  # Create a recipe
```

## Pipeline

```
Book (epub/PDF/txt) -> Extract -> Expand groups -> Dedup -> Research -> Wiki entries
                                                                    -> Recipes
```

Each skill reads from the previous skill's output directory. See `CLAUDE.md` for the full data flow diagram.

## Model Configuration

By default, skills use the cheapest model that can handle the task well:

| Skill | Default model | Why |
|-------|--------------|-----|
| `/extract-book-knowledge` | sonnet | Needs to catch subtle mechanisms and apply quality rubric |
| `/expand-ingredient-groups` | (n/a — deterministic) | Taxonomy lookup + string matching, no inference needed |
| `/dedup-ingredients` | (n/a — deterministic) | Slug/alias index lookup and fuzzy string match |
| `/research-ingredient` | sonnet | Judges conflicting sources, spots `agrees_with_book` mismatches |
| `/generate-wiki-entry` | haiku | Template-filling from structured JSON — Haiku is sufficient |
| `/generate-recipe` | sonnet | Culinary voice + science integration benefits from a stronger model |

To override, copy the example config into your content project and edit:

```bash
cp ~/.claude/skills/longevity-skills/.longevity-skills.json.example .longevity-skills.json
```

`.longevity-skills.json`:
```json
{
  "models": {
    "extraction": "sonnet",
    "research": "sonnet",
    "wiki": "haiku",
    "recipe": "sonnet"
  }
}
```

The file is gitignored — it stays local to each project. Valid values: `sonnet`, `haiku`, `opus`.

## Examples

The `examples/` directory contains realistic sample outputs for each skill, using turmeric as the reference ingredient.

## License

MIT
