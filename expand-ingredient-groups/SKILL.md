---
name: expand-ingredient-groups
version: 0.1.0
description: |
  Expand grouped/category ingredients into individual members before dedup.
  Detects entries like "cruciferous vegetables", "oily fish", "nuts", "legumes",
  "berries", "leafy greens" and splits them into atomised ingredients.
  Each child inherits the parent group's claims. The group entry is kept but
  marked as a category so downstream skills know it's a container, not a leaf.
  Use when asked to "expand groups", "split categories", "atomise ingredients".
allowed-tools:
  - Bash
  - Read
  - Write
---

# Expand Ingredient Groups

Detect category-level ingredients in the master extract and expand them into
individual leaf ingredients before the dedup step.

## Input

`data/book-extracts/ingredients-master.json` — output of /extract-book-knowledge

## Output

`data/book-extracts/ingredients-master.json` — updated in-place:
- Group entries get `"is_group": true` and a `"members": [...]` list added
- Each member is inserted as a new top-level ingredient with:
  - Its own slug
  - Claims inherited from the parent group (with `"inherited_from"` set to the group slug)
  - Any extra claims specific to that member that the book mentions

## Usage

```
/expand-ingredient-groups
```

## How It Works

### Step 1: Detect group ingredients

Read `ingredients-master.json`. For each ingredient, decide if it is a group.

A group is any ingredient whose name matches one of these patterns:

**Priority 1 — exact taxonomy match** (most reliable): name lowercased is a key in TAXONOMY.

**Priority 2 — keyword heuristic** (only if not an exact taxonomy match):
- The *entire* name is a category word (e.g. name == "nuts", "fish", "vegetables"), not
  a compound like "walnuts", "swordfish", "pine nuts" — those are leaf ingredients.
- Starts with a modifier + category word: "oily fish", "leafy greens", "whole grains",
  "cruciferous vegetables", "dark chocolate" — check that the category word is the
  *last* token and the full name isn't a known specific ingredient.
- Is explicitly a category in the book text (e.g. "dark leafy greens such as...")

**Never flag as a group:**
- Names where the category word is a suffix of a compound word (walnuts, hazelnuts,
  swordfish, starfish, peanuts, sunflower seeds used as a specific item, etc.)
- Names already in the taxonomy as leaf members of another group

Print every detected group with its current claims count so the user can see what
will be expanded.

### Step 2: Look up members for each group

For each detected group, determine its members using two sources:

**Built-in taxonomy** (use this first — it's fast and deterministic):

```python
TAXONOMY = {
    "cruciferous vegetables": ["broccoli", "cauliflower", "cabbage", "kale", "brussels sprouts", "bok choy", "arugula", "radishes", "turnips"],
    "oily fish": ["salmon", "sardines", "mackerel", "anchovies", "trout", "herring", "tuna"],
    "fatty fish": ["salmon", "sardines", "mackerel", "anchovies", "trout", "herring"],
    "leafy greens": ["spinach", "kale", "swiss chard", "arugula", "romaine lettuce", "collard greens", "watercress"],
    "dark leafy greens": ["spinach", "kale", "swiss chard", "collard greens", "watercress"],
    "nuts": ["walnuts", "almonds", "hazelnuts", "cashews", "pistachios", "brazil nuts", "pecans", "macadamia nuts"],
    "seeds": ["flaxseeds", "chia seeds", "hemp seeds", "pumpkin seeds", "sunflower seeds", "sesame seeds"],
    "legumes": ["lentils", "chickpeas", "black beans", "kidney beans", "navy beans", "soybeans", "peas", "fava beans"],
    "berries": ["blueberries", "strawberries", "raspberries", "blackberries", "goji berries", "acai berries"],
    "whole grains": ["oats", "barley", "brown rice", "quinoa", "farro", "rye", "buckwheat", "millet", "whole wheat"],
    "citrus fruits": ["oranges", "lemons", "limes", "grapefruit", "tangerines"],
    "alliums": ["garlic", "onion", "leeks", "shallots", "chives"],
    "nightshades": ["tomatoes", "bell peppers", "eggplant", "chili peppers"],
    "brassicas": ["broccoli", "cauliflower", "cabbage", "kale", "brussels sprouts", "bok choy"],
    "fermented foods": ["yogurt", "kefir", "kimchi", "sauerkraut", "miso", "tempeh", "kombucha"],
    "herbs": ["rosemary", "thyme", "oregano", "basil", "parsley", "sage", "mint"],
    "spices": ["turmeric", "ginger", "cinnamon", "black pepper", "cumin", "coriander"],
    "mushrooms": ["shiitake", "maitake", "oyster mushrooms", "reishi", "portobello", "cremini"],
    "shellfish": ["clams", "mussels", "oysters", "shrimp", "scallops", "crab"],
    "fish": ["salmon", "sardines", "anchovies", "cod", "sea bream", "trout", "mackerel", "herring"],
    "vegetables": ["broccoli", "spinach", "carrots", "tomatoes", "sweet potatoes", "bell peppers", "zucchini", "cabbage"],
    "animal protein": ["chicken", "turkey", "eggs", "fish", "lean beef"],
    "dairy": ["yogurt", "milk", "cheese", "kefir"],
    "oils": ["olive oil", "flaxseed oil", "coconut oil", "avocado oil"],
}
```

**Contextual inference from book extract**: if the group name isn't in the taxonomy,
look at the book extract text — the book often lists members inline
("cruciferous vegetables such as broccoli, cauliflower, and kale"). Parse the
ingredient's `raw_quote` fields or claims text for "such as", "including",
"like", "e.g." patterns to find explicit member lists.

If neither source gives members, flag the group as `"members_unknown": true` and
skip expansion. Do not invent members.

### Step 3: Cross-check members against the extract

Before adding a member, check if it already exists in the extract as its own entry.
- If it already exists: skip adding it (it's already there), but add `"also_member_of": ["group-slug"]` to the existing entry.
- If it doesn't exist: add it as a new ingredient with claims inherited from the group.

### Step 4: Build inherited claims

For each new member ingredient:

```python
def inherit_claims(member_name, group_claims):
    inherited = []
    for claim in group_claims:
        inherited.append({
            **claim,
            "inherited_from": group_slug,
            "text": claim["text"],  # keep original group claim text
            "note": f"Claim applies to {member_name} as a member of '{group_name}'"
        })
    return inherited
```

### Step 5: Update the master file

Rewrite `ingredients-master.json` with:
1. Group entries updated: `is_group: true`, `members: [list of slugs]`
2. New member entries appended (only those not already in the extract)
3. Existing entries that are members: `also_member_of` field added
4. Updated `total_ingredients` and `total_claims` counts

### Step 6: Print expansion report

```
=== EXPANSION REPORT ===

Groups detected: XX
Groups expanded: XX
Groups skipped (unknown members): XX

Expansions:
  cruciferous vegetables (4 claims) → broccoli, cauliflower, kale, cabbage, ...
    + 3 new ingredients added
    + 2 already existed in extract (linked)

  oily fish (3 claims) → salmon, sardines, mackerel, anchovies, trout
    + 4 new ingredients added
    + 1 already existed (salmon)

  ...

Total new ingredients added: XX
Updated master: data/book-extracts/ingredients-master.json
```

## Failure Modes

- **Group with no known members:** Mark `members_unknown: true`, skip, warn.
- **Circular group** (a group whose member is also a group): expand one level only.
- **All members already exist:** Still mark group as `is_group: true`, no new entries added.
