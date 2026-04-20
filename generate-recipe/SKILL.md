---
name: generate-recipe
version: 0.1.0
description: |
  Generate chef-quality recipes combining longevity ingredients. Reads ingredient
  profiles, identifies synergies, and produces recipes with both scientific backing
  and real culinary technique. Written like a Serious Eats article.
  Use when asked to "generate recipe", "create recipe", "cook with", or "meal idea".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Agent
---

# Generate Recipe

Generate a chef-quality recipe that combines longevity ingredients with real culinary technique.

## Model Config

```bash
_MODEL=$(python3 -c "import json; d=json.load(open('.longevity-skills.json')); print(d['models'].get('recipe','sonnet'))" 2>/dev/null || echo "sonnet")
echo "MODEL: $_MODEL (recipe)"
```

Default: sonnet. Recipe generation requires culinary voice + science integration.
Set to "haiku" in `.longevity-skills.json` to experiment with cheaper generation —
review output quality carefully before publishing.

**When generating the recipe, use the Agent tool with `model: "<value of _MODEL>"`.**

## Input

2-3 ingredient slugs passed as arguments. The skill reads corresponding JSON profiles
from `data/ingredients/`.

## Output

Markdown file at `content/recipes/{recipe-slug}.md` with YAML frontmatter.

## Usage

```
/generate-recipe turmeric black-pepper chickpeas
```

## Recipe Style Guide

- Explain the science behind each technique step
- Use conversational tone like teaching a friend
- Include "what can go wrong" tips
- Name specific techniques (e.g., "bloom the spices in oil for 30 seconds")
- Reference chef influences or technique traditions
- Include prep/cook times, servings, difficulty

## Validation

The skill checks that JSON profiles exist for all specified ingredients before proceeding.
If a profile is missing, it errors with "Run /research-ingredient {name} first."

## Dispatch Pattern

After reading all ingredient JSONs, pre-extract just the data the agent needs:

```bash
# Build a focused context file — don't dump the full profiles, extract the relevant fields
python3 << 'PYEOF'
import json, sys

slugs = sys.argv[1:]
context = {}
for slug in slugs:
    with open(f"data/ingredients/{slug}.json") as f:
        d = json.load(f)
    context[slug] = {
        "name": d["name"],
        "flavor_profile": d.get("flavor_profile", {}),
        "culinary_pairings": d.get("culinary_pairings", []),
        "synergies": d.get("synergies", []),
        "book_claims": [c for c in d.get("book_claims", []) if c.get("confidence") in ("high", "medium")],
        "consumption": d.get("consumption", {}),
    }
print(json.dumps(context, indent=2))
PYEOF
```

Dispatch the recipe writing to a sub-agent:

```
Use the Agent tool with:
  model: <value of _MODEL read from config>
  prompt: "Generate a chef-quality recipe using these ingredients: [list].
           Here is the focused ingredient context: [extracted context JSON].
           Follow the recipe style guide: [style guide from above].
           Include: ingredient synergies (scientific + flavor), technique steps with
           explanations, 'what can go wrong' tips, prep/cook time, difficulty."
```

Write the sub-agent's output to `content/recipes/{recipe-slug}.md`.

## YAML Frontmatter Spec

Every recipe MUST include the following frontmatter fields. The downstream
`my-longevity-wiki` consumer relies on all of them; missing fields (especially
`meal_type`) break filtering and require manual backfill.

```yaml
---
title: <Human Title Case — what appears on the card and page>
slug: <kebab-case matches filename>
servings: <integer>
prep_time: <"N min" — allow "(+ Nh rest)" for recipes that need resting>
cook_time: <"N min" — "0 min" for no-cook recipes>
difficulty: <easy | medium | hard>
longevity_ingredients: [<ingredient slugs from data/ingredients/>]
tags: [<free-form keywords: cuisine, diet, technique — NOT meal type>]
meal_type: [<1+ of: breakfast, lunch, dinner, snack, drink>]
source_book: <book name when the recipe is book-derived; omit otherwise>
---
```

**`meal_type` is mandatory and must be an array of 1+ values.** Pick from the
closed vocabulary: `breakfast`, `lunch`, `dinner`, `snack`, `drink`. Most Mediterranean
mains fit `[lunch, dinner]`. A smoothie is `[breakfast, drink]`. A crumble or farinata
is `[snack]` (no `dessert` value exists — use `snack`). If the dish genuinely serves
multiple roles, list them all; the `/recipes` filter surfaces it under every match.

Do NOT put meal-type tokens into `tags`. `tags` is for free-form cuisine/diet/technique
labels ("mediterranean", "anti-inflammatory", "one-pot"). `meal_type` is the structural
field consumed by the UI filter.

When dispatching to the sub-agent, include in the prompt: "Assign `meal_type` based
on when this dish is typically eaten. Use the closed vocabulary; use an array if the
dish fits more than one time of day."
