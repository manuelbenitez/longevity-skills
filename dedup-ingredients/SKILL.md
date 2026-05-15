---
name: dedup-ingredients
version: 0.2.0
description: |
  Compare a book extract's ingredient list against the wiki's existing ingredients
  to find duplicates, fuzzy matches, ingredients new to this book, and genuinely
  new ingredients. Outputs a four-bucket dedup report so /research-ingredient knows
  exactly which action to take per ingredient.
  Use when asked to "check duplicates", "compare ingredients", "what's new", or "dedup".
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
---

# Dedup Ingredients

Compare a per-book ingredients-master.json against the flat wiki ingredient profiles.
Multi-book aware: an ingredient may already exist in the wiki (cited by a different
book) without yet being cited by the current book. That's a meaningful state.

## Four-bucket model

Every ingredient lands in exactly one bucket. The bucket determines what
/research-ingredient does next:

| Bucket               | Meaning                                                  | enrich.py action       |
|----------------------|----------------------------------------------------------|------------------------|
| `new`                | Not in the wiki ingredients dir at all                   | Full enrich, write profile |
| `new-to-book`        | In the wiki dir, but no claim has the current book_slug  | Append claims, preserve research, NO new LLM call |
| `existing-same-book` | In the wiki dir, current book_slug already in some claim | Skip entirely          |
| `fuzzy`              | Name fuzzy-matches an existing slug; needs human review  | Skip — surface in report |

## Input

- `data/book-extracts/<slug>/ingredients-master.json` — output of /expand-ingredient-groups
- Wiki ingredient profiles dir, resolved via `lib.wiki_data_dir()` (env override
  `LONGEVITY_WIKI_DATA_DIR`, or `.longevity-skills.json[wiki_data_dir]`)
- The book manifest at `data/book-raw/<slug>/_book.json` (for the report header)

## Output

- `data/dedup/<slug>-dedup-report.json` — machine-readable, stamped with book metadata
- Printed summary table

## Usage

```
/dedup-ingredients <book-slug>
```

If no slug is given, list available manifests and ask the user to pick one:

```bash
python3 scripts/lib.py books
```

## How It Works

### Step 1: Load inputs

```bash
SLUG="<the book slug>"
EXTRACT="data/book-extracts/$SLUG/ingredients-master.json"
WIKI_DIR=$(python3 -c "from scripts import lib; print(lib.wiki_data_dir() / 'ingredients')")
echo "Extract: $EXTRACT  Wiki dir: $WIKI_DIR"
```

Verify the manifest, extract, and wiki dir exist. Otherwise stop with a clear error.

### Step 2: Build the wiki index

Read every `<slug>.json` in the wiki dir. For each profile, index by:
- Filename stem (slug)
- `name` field
- Every entry in `aliases[]`

Each indexed key maps to a record: `{wiki_slug, source_books: [...]}`. The
`source_books` array drives the new-to-book vs existing-same-book decision.

```python
import json, os
from scripts import lib

wiki_dir = lib.wiki_data_dir() / "ingredients"
index = {}  # normalized_key -> {wiki_slug, source_books}

def norm(s):
    return lib.slugify(s)

for path in wiki_dir.glob("*.json"):
    with open(path) as f:
        data = json.load(f)
    record = {"wiki_slug": path.stem, "source_books": data.get("source_books", [])}
    index[norm(path.stem)] = record
    if "name" in data:
        index[norm(data["name"])] = record
    for alias in data.get("aliases", []):
        index[norm(alias)] = record
```

### Step 3: Match each extracted ingredient

For each ingredient in `ingredients-master.json`:

1. **Exact match by normalized name/slug/alias:**
   - Hit in `index` → check `source_books`:
     - Current `<slug>` IS in `source_books` → bucket `existing-same-book`
     - Current `<slug>` is NOT in `source_books` → bucket `new-to-book`
2. **Fuzzy match:** No exact hit, but difflib similarity >= 0.90 against an indexed
   key. Use 0.90 (NOT 0.85) and reject pure substring matches like "salt" vs "salts"
   to avoid silly false positives. Bucket `fuzzy`.
3. **No match at all:** Bucket `new`.

### Step 4: Write the dedup report

The report MUST start with book metadata so research-ingredient can read it without
being passed extra args:

```json
{
  "book_slug": "the-longevity-diet",
  "book_title": "The Longevity Diet",
  "author": "Valter Longo",
  "generated_at": "YYYY-MM-DDTHH:MM:SSZ",
  "wiki_ingredients_dir": "/path/used",
  "summary": {
    "total_extracted": 208,
    "new": 42,
    "new-to-book": 30,
    "existing-same-book": 130,
    "fuzzy": 6
  },
  "new": [{"extracted_name": "...", "slug": "...", "claims_count": 7}],
  "new-to-book": [{"extracted_name": "...", "slug": "...", "wiki_slug": "..."}],
  "existing-same-book": [{"extracted_name": "...", "slug": "...", "wiki_slug": "..."}],
  "fuzzy": [{"extracted_name": "...", "slug": "...", "wiki_slug": "...", "similarity": 0.91}]
}
```

Pull `book_slug`, `book_title`, `author` from the manifest, not from the extract
(the extract may have drifted). This makes the dedup report self-describing.

### Step 5: Print summary

```
=== DEDUP REPORT: The Longevity Diet (longo) ===

NEW (full enrich):              42 ingredients
NEW-TO-BOOK (append claims):    30 ingredients
EXISTING-SAME-BOOK (skip):     130 ingredients
FUZZY (human review):            6 ingredients

Top NEW by claim count:
  1. fasting-mimicking-diet (7 claims)
  ...

Fuzzy matches needing review:
  extracted: salmon → wiki: salmon-fillet (similarity 0.92)
  ...

Run /research-ingredient --book <slug> to enrich. The dedup report tells
enrich.py which ingredients are in which bucket — no extra flags needed.
```

## Failure Modes

- **No manifest for slug:** Stop, point user at `python3 scripts/lib.py books`.
- **No master file:** Tell user to run /extract-book-knowledge then /expand-ingredient-groups first.
- **Wiki dir doesn't exist:** Print the resolved path and stop.
- **Empty wiki dir:** All ingredients are "new" — that's valid on first book.
- **Malformed wiki JSON:** Skip that file, warn, continue.
