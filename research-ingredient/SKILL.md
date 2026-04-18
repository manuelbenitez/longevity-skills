---
name: research-ingredient
version: 0.3.0
description: |
  Enrich ingredient profiles from a book extract into wiki-ready JSON files.
  Claude Code does all enrichment inline — no external API key needed.
  Batched: up to 20 ingredients per LLM response. Prompts user for quality level first.
  Use when asked to "research", "enrich", "look up ingredient", or "generate profiles".
allowed-tools:
  - Bash
  - Read
  - Write
---

# Research Ingredient

Generate enriched ingredient JSON profiles from book extract data.

## Design principles

- **Inline enrichment**: Claude Code does the LLM work directly — no external API key required.
- **Batched**: Process up to 20 ingredients per response, not one at a time.
- **User chooses quality**: Prompt the user to pick fast (concise) or thorough (detailed) before starting.
- **No subagents**: Everything runs in a single skill invocation.

## Input

- `data/book-extracts/ingredients-master.json` — from /extract-book-knowledge
- `data/dedup/*-dedup-report.json` — from /dedup-ingredients (to know which are new)
- Optional: ingredient name(s) as argument to process a specific subset

## Output

`data/ingredients/{slug}.json` per ingredient, matching `schemas/ingredient.schema.json`

## Usage

```
/research-ingredient                    # process all new ingredients from dedup report
/research-ingredient salmon             # single ingredient
/research-ingredient salmon kale eggs   # specific list
```

## How It Works

### Step 1: Determine which ingredients to process

```bash
python3 << 'PYEOF'
import json, os, re, sys, glob

def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

master = json.load(open('data/book-extracts/ingredients-master.json'))
slug_map = {i['slug']: i for i in master['ingredients']}
name_map = {i['name'].lower(): i for i in master['ingredients']}

NON_FOOD = {'igf-1','igfbp1','insulin','stem cells','mitochondria','ketone bodies',
            'blood pressure','blood glucose','c-reactive protein','abdominal fat',
            'glycerol','cholesterol','sugar','saturated fats','healthy fats',
            'calories','protein','desserts'}

written = {f[:-5] for f in os.listdir('data/ingredients') if f.endswith('.json')}

args = sys.argv[1:]
if args:
    targets = args
else:
    reports = glob.glob('data/dedup/*-dedup-report.json')
    if not reports:
        print("ERROR: No dedup report found. Run /dedup-ingredients first.")
        sys.exit(1)
    report = json.load(open(sorted(reports)[-1]))
    targets = [i['extracted_name'] for i in report['new']]

queue = []
seen = set()
for name in targets:
    if name.lower() in NON_FOOD: continue
    slug = slugify(name)
    if slug in written: continue
    if name in seen: continue
    seen.add(name)
    entry = slug_map.get(slug) or name_map.get(name.lower())
    claims = []
    if entry:
        for c in entry.get('claims', [])[:3]:
            claims.append({
                'claim': c.get('text', ''),
                'mechanism': c.get('mechanism', ''),
                'confidence': c.get('confidence', 'medium'),
            })
    queue.append({'name': name, 'slug': slug, 'claims': claims})

print(json.dumps(queue))
PYEOF
```

If queue is empty, print "All ingredients already written." and stop.

### Step 2: Prompt user for quality level

Print this message and wait for the user to reply before continuing:

```
Found {N} ingredients to enrich.

Quality level:
  1 — Fast    (concise, ~50 tokens/ingredient, best for large batches)
  2 — Standard (detailed, ~150 tokens/ingredient, better research depth)

Enter 1 or 2:
```

Default to **1** if the user just presses enter or types anything other than 2.
Set `QUALITY` to either `fast` or `standard` based on the response.

### Step 3: Enrich in batches of 20

For each batch of up to 20 ingredients from the queue, generate the enrichment
**inline** (Claude Code, the current model, produces the JSON directly).

Use this prompt structure internally for each batch:

---
For QUALITY=fast:
> Enrich these {N} ingredients for a longevity wiki. Be maximally concise.
> Return a raw JSON array (no markdown), one object per ingredient, same order.
> Each object: supplementary_research (2 items: {source, url, finding, agrees_with_book}),
> flavor_profile ({taste:[], aroma:[], texture:[], culinary_category:""}),
> culinary_pairings (3 items: {ingredient, tradition, source}),
> nutrient_highlights (2 items: {compound, amount_per_100g, bioavailability_notes}),
> synergies (2 items: {target_ingredient, type, description}),
> category (one of: fish|vegetable|fruit|grain|legume|nut|seed|oil|dairy|egg|meat|supplement|nutrient|beverage|spice|herb|mushroom|shellfish|other).
> Ingredients: [list]

For QUALITY=standard:
> Enrich these {N} ingredients for a longevity wiki. Use real PubMed PMIDs where known.
> Return a raw JSON array (no markdown), one object per ingredient, same order.
> Each object: supplementary_research (2 items: {source, url, finding, agrees_with_book}),
> flavor_profile ({taste:[], aroma:[], texture:[], culinary_category:""}),
> culinary_pairings (3 items: {ingredient, tradition, source}),
> nutrient_highlights (2-3 items: {compound, amount_per_100g, bioavailability_notes}),
> synergies (2-3 items: {target_ingredient, type, description}),
> category (one of: fish|vegetable|fruit|grain|legume|nut|seed|oil|dairy|egg|meat|supplement|nutrient|beverage|spice|herb|mushroom|shellfish|other).
> Longevity framing: mechanisms, aging, disease prevention. Ingredients: [list]
---

Include the book claims for each ingredient in the prompt (cap at 3 per ingredient).

### Step 4: Write files

For each ingredient + enrichment pair, write `data/ingredients/{slug}.json`:

```python
import json
from datetime import datetime

NOW = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def write_profile(ing, enrichment):
    profile = {
        "name":     ing["name"],
        "slug":     ing["slug"],
        "category": enrichment.get("category", "other"),
        "aliases":  [],
        "book_claims":            ing["claims"],
        "supplementary_research": enrichment.get("supplementary_research", []),
        "flavor_profile":         enrichment.get("flavor_profile", {}),
        "culinary_pairings":      enrichment.get("culinary_pairings", []),
        "nutrient_highlights":    enrichment.get("nutrient_highlights", []),
        "synergies":              enrichment.get("synergies", []),
        "last_updated":    NOW,
        "last_researched": NOW,
        "research_status": "complete" if enrichment else "book-only",
        "source_book":     "The Longevity Diet",
    }
    path = f"data/ingredients/{ing['slug']}.json"
    with open(path, 'w') as f:
        json.dump(profile, f, indent=2)
    print(f"  ✓ {ing['slug']}.json")
```

### Step 5: Print summary

```
Done.
Processed: XX ingredients
Written:   XX files
Skipped:   XX (already existed)
Quality:   fast | standard
```

## Token budget guidance

| Batch size | Fast (~50 tok/ing) | Standard (~150 tok/ing) |
|------------|-------------------|--------------------------|
| 20 ingredients | ~1k tokens | ~3k tokens |
| 100 ingredients | ~5k tokens | ~15k tokens |

No external API key needed — Claude Code handles all enrichment inline.

## Failure modes

- **Malformed JSON in response**: retry the batch once with a stricter prompt. If still broken,
  write skeleton profiles with `research_status: "partial"` and continue.
- **Ingredient not in master**: write with empty `book_claims`, still enrich from knowledge.
- **Batch too large / response truncated**: split to batches of 10 and retry.
