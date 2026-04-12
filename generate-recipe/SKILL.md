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
---

# Generate Recipe

Generate a chef-quality recipe that combines longevity ingredients with real culinary technique.

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

<!-- TODO: Implement full skill logic — ingredient reading, synergy identification, recipe generation, frontmatter -->
