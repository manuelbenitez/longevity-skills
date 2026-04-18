---
name: dedup-ingredients
version: 0.1.0
description: |
  Compare a book extract's ingredient list against the wiki's existing ingredients
  to find duplicates, fuzzy matches, and genuinely new ingredients.
  Outputs a dedup report so you know exactly what to skip, enrich, or add.
  Use when asked to "check duplicates", "compare ingredients", "what's new", or "dedup".
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
---

# Dedup Ingredients

Compare freshly extracted book ingredients against the wiki's existing ingredient profiles.
Produces three buckets: exact matches (skip), fuzzy matches (enrich), and new ingredients (add).

## Input

- `data/book-extracts/ingredients-master.json` — output of /extract-book-knowledge
- Wiki ingredient profiles at the path configured in `.longevity-skills.json` under `wiki_ingredients_dir`
  (default: `../my-longevity-wiki/data/ingredients/`)

## Output

- `data/dedup/{book-slug}-dedup-report.json` — machine-readable dedup report
- Printed summary table

## Usage

```
/dedup-ingredients
```

## How It Works

### Step 1: Load inputs

```bash
EXTRACT="data/book-extracts/ingredients-master.json"
WIKI_DIR=$(python3 -c "
import json
try:
    d = json.load(open('.longevity-skills.json'))
    print(d.get('wiki_ingredients_dir', '../my-longevity-wiki/data/ingredients/'))
except:
    print('../my-longevity-wiki/data/ingredients/')
" 2>/dev/null)

echo "Extract: $EXTRACT"
echo "Wiki dir: $WIKI_DIR"
ls "$WIKI_DIR" | wc -l | xargs echo "Existing wiki ingredients:"
```

If `ingredients-master.json` doesn't exist, stop: "Run /extract-book-knowledge first."
If wiki dir doesn't exist, stop: "Wiki ingredients dir not found. Check wiki_ingredients_dir in .longevity-skills.json"

### Step 2: Build the wiki slug index

Read every `{slug}.json` file in the wiki dir. For each, collect:
- The filename stem as the primary slug (e.g. `extra-virgin-olive-oil`)
- The `name` field from the JSON
- Any `aliases` array from the JSON

Build a flat lookup: every slug, name variant, and alias → canonical wiki slug.

```python
import json, os, re

wiki_dir = "WIKI_DIR"
index = {}  # normalized_name -> canonical_slug

def normalize(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

for fname in os.listdir(wiki_dir):
    if not fname.endswith('.json'):
        continue
    slug = fname[:-5]
    try:
        data = json.load(open(os.path.join(wiki_dir, fname)))
    except:
        continue
    # index by slug
    index[normalize(slug)] = slug
    # index by name field
    if 'name' in data:
        index[normalize(data['name'])] = slug
    # index by aliases
    for alias in data.get('aliases', []):
        index[normalize(alias)] = slug

print(json.dumps(index, indent=2))
```

### Step 3: Match each extracted ingredient

For each ingredient in `ingredients-master.json`:

1. **Exact match** — normalized name or any alias hits the wiki index directly → bucket: `existing`
2. **Fuzzy match** — no exact hit, but one of these substring rules fires:
   - Extracted slug contains a wiki slug (e.g. `wild-salmon` contains `salmon` → wiki has `fish`)
   - Wiki slug contains the extracted slug
   - Edit distance ≤ 2 between normalized names (use difflib.SequenceMatcher ratio ≥ 0.85)
   → bucket: `fuzzy`, include `wiki_match` and `match_reason`
3. **New** — no match at all → bucket: `new`

### Step 4: Write the dedup report

Write to `data/dedup/{book-slug}-dedup-report.json`:

```json
{
  "book": "The Longevity Diet",
  "author": "Valter Longo PhD",
  "generated_at": "YYYY-MM-DD",
  "wiki_ingredients_dir": "path/used",
  "summary": {
    "total_extracted": 208,
    "exact_matches": 0,
    "fuzzy_matches": 0,
    "new_ingredients": 0
  },
  "existing": [
    {
      "extracted_name": "olive oil",
      "extracted_slug": "olive-oil",
      "wiki_slug": "extra-virgin-olive-oil",
      "match_type": "exact",
      "new_claims_count": 3
    }
  ],
  "fuzzy": [
    {
      "extracted_name": "salmon",
      "extracted_slug": "salmon",
      "wiki_slug": "fish",
      "match_type": "fuzzy",
      "match_reason": "wiki slug 'fish' is parent category",
      "new_claims_count": 2,
      "recommendation": "enrich existing 'fish' entry or create 'salmon' as sub-entry"
    }
  ],
  "new": [
    {
      "extracted_name": "fasting-mimicking diet",
      "extracted_slug": "fasting-mimicking-diet",
      "claims_count": 7,
      "recommendation": "create new wiki entry"
    }
  ]
}
```

Also include `new_claims_count` for existing/fuzzy matches — the number of claims from the
extract that don't already appear in the wiki profile (by text similarity check).

### Step 5: Print summary

Print a human-readable summary:

```
=== DEDUP REPORT: The Longevity Diet ===

EXACT MATCHES (skip or enrich): XX ingredients
FUZZY MATCHES (review + enrich): XX ingredients
NEW INGREDIENTS (add to wiki):   XX ingredients

Top new ingredients by claim count:
  1. ingredient-name (N claims)
  ...

Fuzzy matches needing review:
  extracted: salmon  →  wiki: fish  (reason: parent category)
  ...

Run /research-ingredient <name> to enrich any ingredient.
```

## Failure Modes

- **Wiki dir missing:** Print path tried and stop.
- **ingredients-master.json missing:** Tell user to run /extract-book-knowledge first.
- **Empty wiki dir:** All ingredients will be "new" — that's valid on first run.
- **Malformed wiki JSON:** Skip that file, warn, continue.
