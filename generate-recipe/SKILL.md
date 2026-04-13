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

<!-- TODO: Add YAML frontmatter spec -->
