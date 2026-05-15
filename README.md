# longevity-skills

Claude Code skills for generating science-backed longevity food content from
peer-reviewed books. A content pipeline that turns multi-book knowledge into
structured ingredient profiles, wiki entries, and chef-quality recipes.

**Multi-book aware.** Every claim is tagged with the book it came from. Two books
talking about the same ingredient produce one merged profile with provenance
preserved. Add a third book without touching the existing data.

Books currently processed:
- "The Path to Longevity" by Luigi Fontana
- "The Longevity Diet" by Valter Longo

## Skills

| Skill | What it does | Input | Output |
|-------|-------------|-------|--------|
| `/extract-book-knowledge` | Extract food claims from book chapters | `data/book-raw/<slug>/` | `data/book-extracts/<slug>/*.json` |
| `/expand-ingredient-groups` | Split category entries into members | `data/book-extracts/<slug>/ingredients-master.json` | same path, in-place |
| `/dedup-ingredients` | Bucket extract vs wiki: new / new-to-book / existing-same-book / fuzzy | per-book master + wiki ingredients | `data/dedup/<slug>-dedup-report.json` |
| `/research-ingredient` | Enrich with web research (PubMed, Examine) | dedup report | `<wiki_data_dir>/ingredients/*.json` |
| `/generate-wiki-entry` | Write readable wiki articles | ingredient profile | `content/wiki/*.md` |
| `/generate-recipe` | Create chef-quality recipes | 2-3 ingredient slugs | `content/recipes/*.md` |
| `/batch-recipes` | Generate 10 recipes targeting under-represented meal types | ingredients dir | `content/recipes/en/_drafts/*.md` |

## Installation

```bash
git clone <repo-url> ~/.claude/skills/longevity-skills
cd ~/.claude/skills/longevity-skills
./setup
```

For development (running tests, the migration script, etc.):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

## Adding a book

```bash
# 1. Pick a slug (kebab-case). For "Outlive" by Peter Attia → attia-outlive.
mkdir -p data/book-raw/attia-outlive
cat > data/book-raw/attia-outlive/_book.json <<EOF
{"slug": "attia-outlive", "title": "Outlive", "author": "Peter Attia"}
EOF

# 2. Drop the source file in.
cp ~/Downloads/outlive.epub data/book-raw/attia-outlive/

# 3. Run the pipeline.
/extract-book-knowledge attia-outlive
/expand-ingredient-groups attia-outlive
/dedup-ingredients attia-outlive
/research-ingredient --book attia-outlive
```

After that, ingredient profiles in `<wiki_data_dir>/ingredients/` will carry
claims tagged with `attia-outlive` alongside whatever was there before.

## Canonical claim shape

Every claim everywhere in the pipeline uses these field names:

```json
{
  "text": "Walnuts lower LDL cholesterol in adults at risk.",
  "mechanism": "Omega-3 ALA reduces hepatic VLDL output.",
  "recommendation": "1 ounce daily",
  "reference": "Estruch et al. 2018",
  "confidence": "high",
  "book_slug": "fontana"
}
```

`book_slug` is required on ingredient-profile claims; on chapter extracts it's
inferred from the top-level `book_slug` field. The validator at write time
rejects any other shape — earlier versions silently renamed `claim`/`study_ref`
on read, which masked drift across books. That's gone.

## Validating your data

```bash
python3 scripts/lib.py validate book-extract data/book-extracts/longo/chapter-04.json
python3 scripts/lib.py validate ingredient ~/Development/my-longevity-wiki/data/ingredients/walnuts.json
python3 scripts/lib.py validate-all data/   # everything under the root
```

Invalid files are written to `data/.invalid/<slug>-<timestamp>.json` with the
field diff appended.

## Configuration

`.longevity-skills.json` (gitignored, project-local):

```json
{
  "wiki_data_dir": "~/Development/my-longevity-wiki/data",
  "models": {
    "extraction": "sonnet",
    "research": "sonnet",
    "wiki": "haiku",
    "recipe": "sonnet"
  }
}
```

Or set the env var `LONGEVITY_WIKI_DATA_DIR` to override the wiki dir explicitly.
Valid model values: `sonnet`, `haiku`, `opus`.

## Testing

```bash
pytest tests/ -v
```

47 tests covering slugify, schema validation, migration logic, and enrich merge
semantics. The 5 IRON-RULE regressions encoded in the suite:

1. Migration produces schema-valid output for every wiki profile.
2. Migration is idempotent.
3. Canonical shape flows end-to-end (no hidden `claim`/`study_ref` rename).
4. Validator rejects the legacy singular `source_book` string.
5. Second-book merge preserves first-book `supplementary_research` byte-identical.

CI runs the suite on every push and PR (`.github/workflows/test.yml`).

## Examples

`examples/` contains realistic sample outputs for each step of the pipeline.

## License

MIT
