---
name: extract-book-knowledge
version: 0.1.0
description: |
  Extract structured food/ingredient claims from book chapters. Reads plain text
  chapter files from data/book-raw/ and produces structured JSON with health claims,
  mechanisms, consumption recommendations, and ingredient relationships. Grounded in
  "The Path to Longevity" by Luigi Fontana.
  Use when asked to "extract", "process chapter", "book claims", or "parse ingredients".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
---

# Extract Book Knowledge

Extract structured food and ingredient claims from book chapters into validated JSON.

## Input

Plain text files at `data/book-raw/chapter-{NN}.txt` in the current project directory.
One file per chapter. Expected length: 500-8,000 words per file.

## Output

JSON files at `data/book-extracts/{chapter-slug}.json` conforming to the Book Extract Schema
at `schemas/book-extract.schema.json` in the longevity-skills repo.

## Usage

```
/extract-book-knowledge
```

The skill will scan `data/book-raw/` for chapter files and process them one at a time.

## Quality Rubric

Every health claim must include:
- A specific mechanism of action (not "is good for you" but "inhibits NF-kB pathway")
- At least one citation: book page reference, PubMed ID, or "book-assertion"
- Dosage/quantity if specified in the book
- A confidence level (high/medium/low)

<!-- TODO: Implement full skill logic — chapter reading, claim extraction, JSON validation, cross-chapter normalization -->
