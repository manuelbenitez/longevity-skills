# longevity-skills

Claude Code skills for generating science-backed longevity food content. A content pipeline that turns book knowledge into structured ingredient profiles, wiki entries, and chef-quality recipes.

Grounded in "The Path to Longevity" by Luigi Fontana.

## Skills

| Skill | What it does | Input | Output |
|-------|-------------|-------|--------|
| `/extract-book-knowledge` | Extract food claims from book chapters | `data/book-raw/*.txt` | `data/book-extracts/*.json` |
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
/extract-book-knowledge        # Scan full book PDF, extract all ingredients
/research-ingredient turmeric  # Enrich one ingredient
/generate-recipe turmeric black-pepper chickpeas  # Create a recipe
/generate-wiki-entry turmeric  # Write the wiki article
```

## Pipeline

```
Book chapters (text) -> Extract -> Research -> Wiki entries
                                           -> Recipes
```

Each skill reads from the previous skill's output directory. See `CLAUDE.md` for the full data flow diagram.

## Examples

The `examples/` directory contains realistic sample outputs for each skill, using turmeric as the reference ingredient.

## License

MIT
