---
name: extract-book-knowledge
version: 0.2.0
description: |
  Extract structured food/ingredient claims from "The Path to Longevity" by Luigi Fontana.
  Reads the book as a PDF file, scans it in 20-page passes, extracts health claims,
  mechanisms, consumption recommendations, ingredient relationships, and appendix references.
  Use when asked to "extract", "process book", "book claims", "scan book", or "parse ingredients".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
---

# Extract Book Knowledge

Scan the full book PDF and extract every food/ingredient claim into structured JSON.

## Input

A PDF file at `data/book-raw/the-path-to-longevity.pdf` (or any `.pdf` in `data/book-raw/`).
The skill also accepts plain text files at `data/book-raw/chapter-{NN}.txt` as a fallback.

## Output

- `data/book-extracts/ingredients-master.json` -- consolidated list of all ingredients found
- `data/book-extracts/pages-{start}-{end}.json` -- per-pass extraction files
- `data/book-extracts/references.json` -- extracted appendix/bibliography references
- All JSON files conform to the Book Extract Schema at `schemas/book-extract.schema.json`

## Usage

```
/extract-book-knowledge
```

The skill auto-detects whether input is PDF or text files.

## How It Works

### Step 1: Detect input format

```bash
PDF=$(find data/book-raw -name "*.pdf" -type f 2>/dev/null | head -1)
TXT_COUNT=$(find data/book-raw -name "*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "PDF: ${PDF:-none}"
echo "TXT files: $TXT_COUNT"
```

If a PDF is found, use PDF mode. If only text files exist, use text mode (legacy).
If neither exists, stop and tell the user: "No book input found. Place your PDF at
data/book-raw/the-path-to-longevity.pdf"

### Step 2: Get page count (PDF mode)

```bash
PAGES=$(python3 -c "
import subprocess
result = subprocess.run(['pdfinfo', '$PDF'], capture_output=True, text=True)
for line in result.stdout.split('\n'):
    if line.startswith('Pages:'):
        print(line.split(':')[1].strip())
        break
" 2>/dev/null || echo "unknown")
echo "Total pages: $PAGES"
```

If pdfinfo is not available, estimate from file size or ask the user for the page count.

### Step 3: First pass -- Table of Contents scan

Read the first 10 pages of the PDF to find the table of contents:

```
Read the PDF at data/book-raw/{filename}.pdf, pages 1-10
```

From the TOC, identify:
- Which chapters cover food, nutrition, and diet (these are the primary targets)
- Where the appendix/references section starts
- Total structure of the book

Write a scan plan to `data/book-extracts/_scan-plan.json`:
```json
{
  "total_pages": N,
  "food_chapters": [
    {"chapter": "title", "estimated_pages": "start-end"}
  ],
  "appendix_pages": "start-end",
  "other_chapters": ["list of non-food chapters to skip or skim"]
}
```

### Step 4: Extract food chapters (20 pages at a time)

For each food-related chapter identified in the scan plan:

1. Read 20 pages of the PDF using: `Read tool with pages parameter (e.g., "15-34")`
2. Extract every food/ingredient mention with:
   - The specific health claim
   - The biological mechanism (required, mark "unclear" if not stated)
   - Study references cited (author, journal, year if available)
   - Consumption recommendations (amount, frequency, preparation)
   - Relationships to other ingredients (synergies, antagonisms)
   - Page numbers where discussed
3. Write the extraction to `data/book-extracts/pages-{start}-{end}.json`
4. Move to the next 20-page window

If a chapter spans a page boundary between passes, overlap by 2 pages to avoid
missing content that crosses the break.

### Step 5: Extract appendix/references

Read the appendix/bibliography section (identified in Step 3).
Extract all references into `data/book-extracts/references.json`:
```json
{
  "references": [
    {
      "id": "string (sequential or as numbered in book)",
      "authors": "string",
      "title": "string",
      "journal": "string",
      "year": "number",
      "doi": "string (if available)",
      "cited_on_pages": [N]
    }
  ]
}
```

### Step 6: Consolidate into master ingredient list

After all passes are complete, read all `pages-*.json` files and consolidate:

1. Merge duplicate ingredients across passes (same ingredient mentioned in different chapters)
2. Normalize ingredient names to slugs (e.g., "wild blueberries" and "blueberries" -> "blueberries")
3. Link claims to their full references from `references.json`
4. Write the consolidated list to `data/book-extracts/ingredients-master.json`

The master file contains every ingredient with all its claims, references, and relationships
in one place. This is the primary input for `/research-ingredient`.

### Step 7: Summary report

Print a summary:
- Total ingredients found
- Total health claims extracted
- Chapters processed
- Any ingredients with low-confidence claims that need manual review
- Any ambiguous references that couldn't be resolved

## Quality Rubric

Every health claim must include:
- **(a)** A specific mechanism of action (not "is good for you" but "inhibits NF-kB pathway, reducing chronic inflammation")
- **(b)** At least one citation: book page reference + study reference from appendix if available
- **(c)** Dosage/quantity if the book specifies one
- **(d)** A confidence level:
  - **high**: claim cites a specific study with clear mechanism
  - **medium**: claim has a mechanism but no specific study cited, or study is observational
  - **low**: book assertion without mechanism or study. Include the raw quote for manual review.

## Failure Modes

- **PDF cannot be read**: Check file permissions. Try `python3 -c "open('data/book-raw/file.pdf','rb').read(100)"` to verify.
- **No food content in a page range**: Write an empty ingredients array for that pass. Not an error.
- **Page count unknown**: Process in 20-page passes starting from page 1 until Read returns empty.
- **Appendix not found**: Skip Step 5, note in summary that references were not extracted.
- **Ingredient name ambiguity**: During consolidation, flag near-matches for manual review (e.g., "berries" vs "blueberries" vs "wild blueberries").

## Text File Fallback

If no PDF is found but `data/book-raw/chapter-*.txt` files exist, process each text file
as a standalone chapter. Skip Steps 2, 3, and 5 (no page count, no TOC scan, no appendix).
Proceed directly to extraction and consolidation.
