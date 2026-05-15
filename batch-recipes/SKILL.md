---
name: batch-recipes
version: 0.2.0
description: |
  Batch-generate 10 chef-quality recipes in one invocation. Picks ingredient
  combinations deterministically using synergies, culinary pairings, and usage
  gaps in the existing catalog. Biases toward under-represented meal types
  (breakfast, snack, drink). Writes drafts to `content/recipes/en/_drafts/`
  for manual review via git mv / rm.
  Use when asked to "batch recipes", "generate 10 recipes", "expand the recipe
  catalog", or "close the recipe gap".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Agent
  - AskUserQuestion
---

# Batch Recipes

Orchestrate the generation of 10 recipes per run, biased toward meal types and
ingredients the catalog is thin on. Each recipe is written by a sub-agent using
the same style guide as `/generate-recipe`. Drafts land in `_drafts/`; you review
and promote with `git mv`.

## Model Config

```bash
_MODEL=$(python3 -c "import json; d=json.load(open('.longevity-skills.json')); print(d['models'].get('recipe','sonnet'))" 2>/dev/null || echo "sonnet")
echo "MODEL: $_MODEL (recipe)"
```

Default: sonnet. Same model as `/generate-recipe` — quality matters more here
than cost, because bad drafts waste your review time, not just tokens.

## Paths

The skill assumes it runs from the **my-longevity-wiki** repo root, because that
is where `content/recipes/en/` lives. The ingredient JSON profiles live in the
flat `<wiki_data_dir>/ingredients/` dir (the wiki repo's data). Each profile carries
a top-level `source_books[]` array — when citing an ingredient in a recipe, prefer
to mention all books that cite it rather than picking one. If the env var
`LONGEVITY_SKILLS_DIR` is set, ingredient JSONs are read from there:

```bash
LONGEVITY_SKILLS_DIR="${LONGEVITY_SKILLS_DIR:-$HOME/Development/longevity-skills}"
INGREDIENTS_DIR="$LONGEVITY_SKILLS_DIR/data/ingredients"
RECIPES_DIR="content/recipes/en"
DRAFTS_DIR="$RECIPES_DIR/_drafts"
```

Validate before proceeding:
```bash
[ -d "$INGREDIENTS_DIR" ] || { echo "ERROR: $INGREDIENTS_DIR not found"; exit 1; }
[ -d "$RECIPES_DIR" ] || { echo "ERROR: $RECIPES_DIR not found — are you in my-longevity-wiki root?"; exit 1; }
mkdir -p "$DRAFTS_DIR"
```

## Step 1 — Scan the catalog

Compute meal-type distribution and ingredient usage gaps. This runs in a single
Python block to avoid bash loop fragility.

```bash
python3 << 'PYEOF'
import json, glob, os, re, sys
from pathlib import Path

recipes_dir = Path("content/recipes/en")
skills_dir = Path(os.environ.get("LONGEVITY_SKILLS_DIR", os.path.expanduser("~/Development/longevity-skills")))
ingredients_dir = skills_dir / "data" / "ingredients"

meal_type_counts = {"breakfast": 0, "lunch": 0, "dinner": 0, "snack": 0, "drink": 0, "sauce": 0}
ingredient_usage = {}

for md in recipes_dir.glob("*.md"):
    text = md.read_text()
    m = re.search(r"^meal_type:\s*\[([^\]]+)\]", text, re.MULTILINE)
    if m:
        for tok in m.group(1).split(","):
            tok = tok.strip().strip('"').strip("'")
            if tok in meal_type_counts:
                meal_type_counts[tok] += 1
    m = re.search(r"^longevity_ingredients:\s*\[([^\]]+)\]", text, re.MULTILINE)
    if m:
        for slug in m.group(1).split(","):
            slug = slug.strip().strip('"').strip("'")
            if slug:
                ingredient_usage[slug] = ingredient_usage.get(slug, 0) + 1

# Cookable ingredients (exclude pure supplements/nutrients)
NONCOOK_SUBSTR = ["supplement", "micronutrient", "mineral nutrient", "amino acid"]
cookable = []
for jf in sorted(ingredients_dir.glob("*.json")):
    with open(jf) as f:
        d = json.load(f)
    cat = (d.get("flavor_profile") or {}).get("culinary_category", "") or ""
    cat_l = cat.lower()
    if any(s in cat_l for s in NONCOOK_SUBSTR) and "/" not in cat:
        continue
    cookable.append({
        "slug": d["slug"],
        "name": d["name"],
        "category": cat,
        "usage": ingredient_usage.get(d["slug"], 0),
    })

untouched = [c for c in cookable if c["usage"] == 0]
low = [c for c in cookable if c["usage"] in (1, 2)]

result = {
    "meal_type_counts": meal_type_counts,
    "total_recipes": sum(1 for _ in recipes_dir.glob("*.md")),
    "cookable_count": len(cookable),
    "untouched_count": len(untouched),
    "low_usage_count": len(low),
    "untouched_sample": [c["name"] for c in untouched[:10]],
}
print(json.dumps(result, indent=2))
PYEOF
```

Read the output. Identify meal types where count < 5 — these are "thin." Print
a one-line summary for the user.

## Step 2 — Ask the user which meal type to target

Use AskUserQuestion. Pre-populate options with thin meal types from Step 1.

Format:
- Question: "Which meal type should this batch target?"
- Header: "Meal type"
- Options (up to 4): one per thin meal-type detected, plus "Mix — 2-3 thin types evenly"
- Recommendation: thinnest meal type with `Completeness: 10/10`

STOP after the question. Wait for the user's answer.

## Step 3 — Pick 10 ingredient combinations

Run the pairing algorithm. Deterministic, not LLM-driven.

**Dedup rule:** a candidate combo is rejected if its Jaccard similarity against
any existing recipe's `longevity_ingredients` OR any combo already picked in this
batch is ≥ 0.5. Jaccard = |intersection| / |union|. Two recipes sharing 2 of 3
slugs score 2/4 = 0.5 and are rejected — that's the "basically the same dish"
threshold. Lower the threshold if drift is still a problem after a few runs.

**Meal-type eligibility rule (don't force-fit):** an anchor is eligible for a
target meal type only if its `culinary_category` matches that meal type's
keyword list (`MEAL_TYPE_KEYWORDS` in the code below). Combos whose ingredients
match NO target meal type are **skipped** rather than shoehorned into the
default bucket. Learned from batch 1: farro got force-fit into breakfast and
produced a "pepper farro bowl" that the user rejected. The fix is to skip
farro this batch instead, and let a future lunch/dinner batch pick it up.

**Partner eligibility rule (target-specific whitelist):** the anchor's synergies
and culinary_pairings include pairings across all meal types. A drink-anchor
like milk legitimately pairs with cheese for a sauce but NOT for a drink. So
when a meal type has a `PARTNER_CATEGORY_WHITELIST` entry, partners are
filtered to categories appropriate for that meal type. Learned from batch 2:
dispatch was aborted because the first-pass generated "Pasta + cooking wine",
"Peas + black tea", and "Milk + almond milk + feta cheese" as drink combos.
The fix is a per-meal-type partner whitelist so milk's partner options in a
drink context are lemon/ginger/cocoa/honey, not cheese.

```bash
TARGET_MEAL_TYPE="<user's answer>"  # single value, or comma-separated for "mix"

python3 << PYEOF
import json, os, random
from pathlib import Path

skills_dir = Path(os.environ.get("LONGEVITY_SKILLS_DIR", os.path.expanduser("~/Development/longevity-skills")))
ingredients_dir = skills_dir / "data" / "ingredients"
target_meals = "$TARGET_MEAL_TYPE".split(",")

# Reload the same cookable filter from Step 1
NONCOOK_SUBSTR = ["supplement", "micronutrient", "mineral nutrient", "amino acid"]
profiles = {}
for jf in sorted(ingredients_dir.glob("*.json")):
    with open(jf) as f:
        d = json.load(f)
    cat = ((d.get("flavor_profile") or {}).get("culinary_category") or "").lower()
    if any(s in cat for s in NONCOOK_SUBSTR) and "/" not in cat:
        continue
    profiles[d["slug"]] = d

# Load usage from catalog (repeated from Step 1 — fine, it's fast)
import re
recipes_dir = Path("content/recipes/en")
usage = {}
for md in recipes_dir.glob("*.md"):
    m = re.search(r"^longevity_ingredients:\s*\[([^\]]+)\]", md.read_text(), re.MULTILINE)
    if m:
        for slug in m.group(1).split(","):
            s = slug.strip().strip('"').strip("'")
            if s: usage[s] = usage.get(s, 0) + 1

def score_anchor(slug):
    # Lower score = better anchor. Untouched beats low-usage.
    return usage.get(slug, 0)

anchors = sorted(profiles.keys(), key=score_anchor)

# Meal-type category map. Explicit keyword matches against `culinary_category`
# from the ingredient JSON. An anchor is ELIGIBLE for a meal type only if its
# category matches that meal type's keywords. Anchors whose category matches
# NO target meal type are skipped for this batch — this prevents force-fitting
# (e.g., farro into breakfast, salmon into snack).
MEAL_TYPE_KEYWORDS = {
    "drink": ["beverage", "milk", "tea", "drink", "base/liquid"],
    # "liquid" removed — too loose, catches "cooking liquid" (wine, stock bases).
    "breakfast": ["breakfast", "yogurt", "fermented dairy", "dairy beverage",
                  "stone fruit", "fresh fruit", "fresh tropical fruit",
                  "dried fruit", "berry", "breakfast grain", "whole grain",
                  "grain staple", "oat", "cereal", "ancient grain",
                  "pseudocereal", "preserve", "spread", "natural sweetener"],
    "snack": ["cracker", "crispbread", "nut", "tree nut", "seed", "olive",
              "cheese", "brined fresh cheese", "aged hard cheese",
              "condiment", "umami", "delicacy", "garnish", "topping",
              "raw or roasted vegetable", "vegetable / side",
              "Italian flatbread", "flatbread", "bivalve", "shellfish",
              "small oily fish", "oily fish", "legume", "cooked legume",
              "hummus", "dip"],
    "sauce": ["condiment", "dip", "spread", "paste", "sauce", "hummus",
              "legume", "cooked legume", "nut", "tree nut", "seed",
              "olive", "vegetable", "roasted vegetable", "fermented dairy",
              "yogurt", "small oily fish", "fish"],
    "lunch": ["protein", "main", "vegetable", "legume", "grain",
              "fish", "shellfish", "oil", "dressing", "pasta", "bread"],
    "dinner": ["protein", "main", "vegetable", "legume", "grain",
               "fish", "shellfish", "oil", "pasta", "starchy",
               "cruciferous", "leafy green", "mushroom"],
}

def eligible_meal_types(slugs):
    """Return the set of meal types whose keywords match any slug's category."""
    eligible = set()
    for slug in slugs:
        cat = ((profiles[slug].get("flavor_profile") or {}).get("culinary_category") or "").lower()
        if not cat: continue
        for mt, keywords in MEAL_TYPE_KEYWORDS.items():
            if any(k in cat for k in keywords):
                eligible.add(mt)
    return eligible

# Per-meal-type partner whitelist. When a target meal type has an entry here,
# partners are filtered to categories appropriate for that meal type. Prevents
# the "milk + feta cheese for a drink" class of failure where the anchor is
# meal-type-appropriate but its pairings drag in wrong-context partners.
PARTNER_CATEGORY_WHITELIST = {
    "drink": ["beverage", "milk", "tea", "base/liquid",
              "natural sweetener", "preserve", "honey",
              "fresh fruit", "fresh tropical fruit", "stone fruit",
              "berry", "dried fruit", "citrus",
              "fresh herb", "aromatic", "spice",
              "cocoa", "chocolate", "coffee",
              "medicinal mushroom"],
    "breakfast": ["yogurt", "fermented dairy", "dairy beverage", "milk",
                  "stone fruit", "fresh fruit", "fresh tropical fruit",
                  "dried fruit", "berry", "citrus",
                  "breakfast grain", "whole grain", "grain staple",
                  "oat", "cereal", "ancient grain", "pseudocereal",
                  "preserve", "spread", "natural sweetener", "honey",
                  "tree nut", "nut", "seed",
                  "cocoa", "chocolate", "coffee",
                  "egg"],
    "sauce": ["legume", "cooked legume", "nut", "tree nut", "seed",
              "olive", "vegetable", "roasted vegetable", "pepper",
              "fermented dairy", "yogurt", "brined fresh cheese",
              "small oily fish", "fish", "shellfish",
              "fresh herb", "aromatic", "spice", "citrus",
              "oil", "condiment", "preserve"],
}

# Categories that should be rejected as partners even if they match whitelist
# keywords. Prevents pesto ("Italian herb sauce / condiment") from slipping in
# via "herb" when what we want is "fresh herb" alone. For breakfast, blocks
# savory mains and sauces from pairing with yogurt/fruit anchors.
PARTNER_CATEGORY_EXCLUDE = {
    "drink": ["sauce", "condiment", "dip", "dressing", "topping",
              "garnish", "hummus", "flatbread"],
    "breakfast": ["sauce", "condiment", "dip", "dressing", "topping",
                  "garnish", "hummus", "flatbread",
                  "cooked legume", "legume", "pasta", "bread pasta",
                  "main", "fish", "shellfish", "aged hard cheese",
                  "cooking liquid", "base/liquid",
                  "bell pepper", "cruciferous", "leafy green"],
}

def partner_ok(slug, meal_type):
    """If the target meal type has a partner whitelist, partner's category must
    match AND must not hit the exclusion list."""
    wl = PARTNER_CATEGORY_WHITELIST.get(meal_type)
    if not wl: return True
    cat = ((profiles[slug].get("flavor_profile") or {}).get("culinary_category") or "").lower()
    if not cat: return False
    excl = PARTNER_CATEGORY_EXCLUDE.get(meal_type, [])
    if any(k in cat for k in excl): return False
    return any(k in cat for k in wl)

def assign_meal_type(combo_slugs, target_meals, filled_counts, target_counts):
    """Pick the best target meal type that (a) the combo is eligible for and
    (b) still has an open slot. Returns None if no target meal type fits.

    Preference order: fewest already-filled slots first (to spread the batch)."""
    elig = eligible_meal_types(combo_slugs)
    candidates = [t for t in target_meals
                  if t in elig and filled_counts.get(t, 0) < target_counts.get(t, 0)]
    if not candidates:
        return None
    # Prefer the meal type with the most open slots remaining
    return max(candidates, key=lambda t: target_counts[t] - filled_counts[t])

def pick_partners(anchor_slug, k=2, meal_type=None):
    """Return 1-2 partner slugs for this anchor, preferring synergy matches.
    If meal_type has a PARTNER_CATEGORY_WHITELIST entry, partners are filtered."""
    anchor = profiles[anchor_slug]
    partners = []
    # Synergies: target_ingredient is a slug
    for s in anchor.get("synergies", []) or []:
        t = s.get("target_ingredient")
        if t and t in profiles and t != anchor_slug:
            partners.append(t)
    # Culinary pairings: ingredient is free text, try to resolve to a slug
    for cp in anchor.get("culinary_pairings", []) or []:
        name = (cp.get("ingredient") or "").lower()
        for slug in profiles:
            if slug == anchor_slug: continue
            if slug.replace("-", " ") == name or profiles[slug]["name"].lower() == name:
                partners.append(slug)
    # Deduplicate, apply meal-type partner filter, prefer low-usage partners
    seen, ranked = set(), []
    for p in partners:
        if p in seen: continue
        seen.add(p)
        if meal_type and not partner_ok(p, meal_type): continue
        ranked.append((usage.get(p, 0), p))
    ranked.sort()
    return [p for _, p in ranked[:k]]

# Existing catalog combos (for dedup)
existing_combos = []
for md in recipes_dir.glob("*.md"):
    m = re.search(r"^longevity_ingredients:\s*\[([^\]]+)\]", md.read_text(), re.MULTILINE)
    if m:
        slugs = [s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip()]
        if slugs:
            existing_combos.append(set(slugs))

def jaccard(a, b):
    a, b = set(a), set(b)
    u = a | b
    return len(a & b) / len(u) if u else 0.0

def too_similar(candidate, all_combos, threshold=0.5):
    return any(jaccard(candidate, c) >= threshold for c in all_combos)

# Decide per-meal-type slot counts from target_meals (even split, 10 total)
n = len(target_meals)
base, extra = divmod(10, n)
target_counts = {t: base + (1 if i < extra else 0) for i, t in enumerate(target_meals)}
filled_counts = {t: 0 for t in target_meals}

combos = []  # list of dicts: {slugs, meal_type, anchor_synergy}
used_in_batch = set()
rng = random.Random(42)

# First pass: walk anchors in usage order. For each, decide the target meal type
# (must be eligible, must still have an open slot), then pick partners filtered
# for that meal type.
for anchor in anchors:
    if len(combos) >= 10: break
    if anchor in used_in_batch: continue
    # Which target meal types is THIS anchor eligible for, with open slots?
    anchor_elig = eligible_meal_types([anchor]) & set(target_meals)
    open_meals = [t for t in anchor_elig if filled_counts.get(t, 0) < target_counts[t]]
    if not open_meals: continue
    # Try meal types with the most open slots first (spread the batch)
    open_meals.sort(key=lambda t: -(target_counts[t] - filled_counts[t]))
    picked = False
    for mt in open_meals:
        partners = pick_partners(anchor, k=2, meal_type=mt)
        if not partners: continue
        combo = [anchor] + partners[:1 if rng.random() < 0.5 else 2]
        picked_sets = [set(c["slugs"]) for c in combos]
        if too_similar(set(combo), existing_combos + picked_sets):
            continue
        anchor_syn = ""
        for s in (profiles[anchor].get("synergies") or []):
            if s.get("target_ingredient") in combo[1:]:
                anchor_syn = s.get("description", "")
                break
        combos.append({"slugs": combo, "meal_type": mt, "anchor_synergy": anchor_syn})
        used_in_batch.update(combo)
        filled_counts[mt] += 1
        picked = True
        break

# Backfill if < 10: anchors with no filtered-partner matches get a random
# partner from the whitelist pool (if the meal type has one) or any pool
# (if not). Still respects dedup AND meal-type eligibility.
backfill_attempts = 0
while len(combos) < 10 and backfill_attempts < 500:
    backfill_attempts += 1
    made_progress = False
    for anchor in anchors:
        if len(combos) >= 10: break
        if anchor in used_in_batch: continue
        anchor_elig = eligible_meal_types([anchor]) & set(target_meals)
        open_meals = [t for t in anchor_elig if filled_counts.get(t, 0) < target_counts[t]]
        if not open_meals: continue
        mt = max(open_meals, key=lambda t: target_counts[t] - filled_counts[t])
        pool = [s for s in profiles
                if s != anchor and s not in used_in_batch and partner_ok(s, mt)]
        if not pool: continue
        combo = [anchor, rng.choice(pool)]
        picked_sets = [set(c["slugs"]) for c in combos]
        if too_similar(set(combo), existing_combos + picked_sets):
            continue
        combos.append({"slugs": combo, "meal_type": mt, "anchor_synergy": ""})
        used_in_batch.update(combo)
        filled_counts[mt] += 1
        made_progress = True
    if not made_progress:
        break  # exhausted — accept fewer than 10 rather than violate eligibility

# Emit combos with per-combo meal_type already assigned
out = []
for c in combos[:10]:
    slugs = c["slugs"]
    out.append({
        "slugs": slugs,
        "names": [profiles[s]["name"] for s in slugs],
        "meal_type": c["meal_type"],
        "anchor_synergy": c["anchor_synergy"],
    })

with open("/tmp/batch-recipes-combos.json", "w") as f:
    json.dump(out, f, indent=2)
print(f"Wrote {len(out)} combos to /tmp/batch-recipes-combos.json")
print(f"Distribution: {filled_counts}")
for i, c in enumerate(out, 1):
    print(f"  {i:2d}. [{c['meal_type']:9s}] {' + '.join(c['names'])}")
PYEOF
```

## Step 4 — Dispatch 10 parallel sub-agents

For each combo, use the Agent tool with `model: <_MODEL>`. Issue all 10 calls
in a single message (parallel execution). Each sub-agent receives:

1. The 2-3 ingredient slugs
2. Extracted ingredient context (same shape as `/generate-recipe` — use the same
   extraction Python, only keep `name`, `flavor_profile`, `culinary_pairings`,
   `synergies`, high/medium confidence `book_claims`, `consumption`)
3. The target meal_type(s)
4. The anchor synergy description (to weave into the recipe's science note)
5. The Recipe Style Guide from `/generate-recipe/SKILL.md` (Recipe Style Guide section)
6. The YAML Frontmatter Spec from `/generate-recipe/SKILL.md` (YAML Frontmatter Spec section — with `meal_type` strictly from the target)

Instruct the sub-agent to return only the recipe markdown file contents
(frontmatter + body). Do NOT have the sub-agent write the file — the orchestrator
writes, so we can check for slug collisions first.

## Step 5 — Write drafts

For each sub-agent response:

1. Parse frontmatter to extract `slug`.
2. Check collisions:
   - If `content/recipes/en/{slug}.md` exists, append `-v2` (then `-v3`, etc.)
   - If `content/recipes/en/_drafts/{slug}.md` exists, same suffix rule
3. Write to `content/recipes/en/_drafts/{final-slug}.md`.
4. Validate frontmatter (reuse validation from `/generate-recipe`): `title`,
   `slug`, `servings`, `prep_time`, `cook_time`, `difficulty`,
   `longevity_ingredients`, `tags`, `meal_type` all present; `meal_type` array
   non-empty.
5. If validation fails, write anyway but flag in summary with `[INVALID]`.

## Step 6 — Summary

Print a table:

```
BATCH COMPLETE — 10 drafts in content/recipes/en/_drafts/

  # | TITLE                                | MEAL           | INGREDIENTS
 ---|--------------------------------------|----------------|----------------
  1 | Ligurian Chickpea Flatbread          | snack          | garbanzo-bean-flour + rosemary
  2 | ...

Next: review drafts in your editor. Keepers:
    git mv content/recipes/en/_drafts/{slug}.md content/recipes/en/
Rejects:
    rm content/recipes/en/_drafts/{slug}.md
```

No interactive prompt after the summary. The user takes it from here.

## What NOT to do

- Do NOT write to `content/recipes/en/` directly. Only `_drafts/`.
- Do NOT delete or modify existing recipes.
- Do NOT translate to `content/recipes/es/`. English only, v1.
- Do NOT run `/generate-recipe` as a sub-skill — the dispatch is native to this skill for parallelism.
- Do NOT ask the user to confirm each of the 10 generations individually. One question (meal type) upfront, then silence until summary.

## Failure modes

- **Sub-agent returns invalid frontmatter:** write the draft with `[INVALID]` prefix in the summary line. User can still review and fix manually.
- **Fewer than 10 anchors have pairing signal:** backfill with random partners (see Step 3 backfill loop). Log the count to summary.
- **Slug collision with existing recipe:** auto-suffix `-v2`. Mention in summary.
- **`LONGEVITY_SKILLS_DIR` or `content/recipes/en/` missing:** exit 1 in Step 1 bash. Do not proceed.

## Tuning knobs (future)

- Accept rate tuning: if users report <30% accept rate after a few runs, tighten pairing (require both synergy AND culinary_pairings match, not OR).
- Meal-type weights: expose weights for "mix" mode so a user can say "70% breakfast, 30% drink."
- Ingredient diversity: track `used_in_batch` across runs (persist to `.longevity-skills.state.json`) so sequential batches don't rediscover the same anchors.

These are v2 concerns. Don't build them into v1.
