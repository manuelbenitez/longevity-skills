---
name: extract-book-knowledge
version: 0.3.0
description: |
  Extract structured food/ingredient claims from "The Path to Longevity" by Luigi Fontana.
  Reads the book as an epub (or PDF), scans all chapters, extracts health claims,
  mechanisms, consumption recommendations, ingredient relationships, and bibliography references.
  Use when asked to "extract", "process book", "book claims", "scan book", or "parse ingredients".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
---

# Extract Book Knowledge

Scan the full book and extract every food/ingredient claim into structured JSON.

## Input

An epub file at `data/book-raw/*.epub` in the current project directory.
Also accepts PDF (`data/book-raw/*.pdf`) or plain text (`data/book-raw/chapter-*.txt`).

## Output

- `data/book-extracts/ingredients-master.json` -- consolidated list of all ingredients found
- `data/book-extracts/chapter-{NN}.json` -- per-chapter extraction files
- `data/book-extracts/references.json` -- extracted bibliography references
- `data/book-extracts/_scan-plan.json` -- which chapters to process and why
- All JSON files conform to the Book Extract Schema at `schemas/book-extract.schema.json`

## Usage

```
/extract-book-knowledge
```

The skill auto-detects the input format (epub, PDF, or text files).

## How It Works

### Step 1: Detect input and extract chapter list

```bash
EPUB=$(find data/book-raw -name "*.epub" -type f 2>/dev/null | head -1)
PDF=$(find data/book-raw -name "*.pdf" -type f 2>/dev/null | head -1)
TXT_COUNT=$(find data/book-raw -name "*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "EPUB: ${EPUB:-none}"
echo "PDF: ${PDF:-none}"
echo "TXT files: $TXT_COUNT"
```

If nothing found, stop: "No book input found. Place your epub at data/book-raw/"

**For epub (preferred):** Extract the table of contents and chapter list:

```bash
python3 << 'PYEOF'
import zipfile, re, json, sys

epub_path = sys.argv[1] if len(sys.argv) > 1 else "EPUB_PATH"
epub = zipfile.ZipFile(epub_path)

# List all content files
html_files = sorted([f for f in epub.namelist() if f.endswith(('.xhtml', '.html', '.htm'))])
for f in html_files:
    size = epub.getinfo(f).file_size
    print(f"{f} ({size} bytes)")
PYEOF
```

An epub is a zip of HTML files. Each chapter is a separate .xhtml file.
No page-based reading needed. Read chapters directly by filename.

### Step 2: Read the Table of Contents

Extract the TOC from the epub to identify which chapters are about food/nutrition:

```bash
python3 << 'PYEOF'
import zipfile, re, sys

epub = zipfile.ZipFile("EPUB_PATH")
toc_raw = epub.read("OEBPS/toc.xhtml").decode("utf-8", errors="replace")
clean = re.sub(r'<[^>]+>', '\n', toc_raw)
lines = [l.strip() for l in clean.split('\n') if l.strip()]
for line in lines:
    print(line)
PYEOF
```

From the TOC, identify the food-focused chapters. For "The Path to Longevity," these are:

**Primary food chapters (process in full):**
- Chapter 4: The Science of Healthy Nutrition
- Chapter 5: Longevity Effects of Restricting Calories and Fasting
- Chapter 7: Diet Quality Matters (protein, fat, carbs, fibre)
- Chapter 8: The Mediterranean Diet
- Chapter 9: Move to the Modern Healthy Longevity Diet (the food pyramid, vegetables, herbs, spices, grains, legumes, nuts, seeds, fruit, fish, olive oil, drinks)
- Chapter 10: Foods to Eliminate or Drastically Reduce

**Secondary chapters (skim for ingredient mentions):**
- Chapter 2: Healthy Centenarians (Okinawa, Sardinia diets)
- Chapter 6: Healthy Children (nutrition in pregnancy/breastfeeding)
- Chapter 17: Preventative Action (alcohol, vitamin D)

**References:**
- References/Bibliography section (chapter 32 in epub)

Write the scan plan to `data/book-extracts/_scan-plan.json`.

### Step 3: Extract chapters one at a time

For each food-focused chapter, read the HTML content from the epub and extract text:

```bash
python3 << 'PYEOF'
import zipfile, re, sys

epub = zipfile.ZipFile("EPUB_PATH")
chapter_file = "OEBPS/chapterNN.xhtml"  # substitute actual filename

raw = epub.read(chapter_file).decode("utf-8", errors="replace")
# Strip HTML tags, keep paragraph breaks
text = re.sub(r'</(p|h[1-6]|div|li)>', '\n\n', raw)
text = re.sub(r'<[^>]+>', '', text)
text = re.sub(r'&[a-z]+;', ' ', text)
text = re.sub(r'\n{3,}', '\n\n', text).strip()
print(text)
PYEOF
```

Read the extracted text. For each chapter:

1. Identify every food, ingredient, nutrient, or compound mentioned
2. For each ingredient, extract:
   - **Claims:** specific health claims with biological mechanisms
   - **Study references:** author names, journal, year if cited inline
   - **Consumption recommendations:** amounts, frequency, preparation methods
   - **Relationships:** synergies, antagonisms, complements with other ingredients
   - **Confidence level:** high/medium/low based on evidence quality
3. Write to `data/book-extracts/chapter-{NN}.json` matching the Book Extract Schema

### Step 4: Extract bibliography/references

The references section is in `OEBPS/chapter32.xhtml` and `OEBPS/chapter32a.xhtml`.

Extract all references into `data/book-extracts/references.json`:
```json
{
  "references": [
    {
      "id": "string",
      "authors": "string",
      "title": "string",
      "journal": "string",
      "year": "number",
      "doi": "string (if available)",
      "chapter_cited_in": "string"
    }
  ]
}
```

### Step 5: Consolidate into master ingredient list

After all chapters are processed:

1. Read all `chapter-*.json` files
2. Merge duplicate ingredients across chapters (same ingredient in different chapters)
3. Normalize names to slugs ("wild blueberries" and "blueberries" -> "blueberries")
4. Cross-reference claims with full references from `references.json`
5. Write `data/book-extracts/ingredients-master.json`

The master file is the primary input for `/research-ingredient`.

### Step 6: Summary report

Print:
- Total ingredients found
- Total health claims extracted
- Chapters processed
- Top 10 most-referenced ingredients
- Ingredients with low-confidence claims needing manual review
- Any ambiguous references that couldn't be resolved

## Quality Rubric

Every health claim must include:
- **(a)** A specific mechanism of action (not "is good for you" but "inhibits NF-kB pathway, reducing chronic inflammation")
- **(b)** At least one citation: chapter reference + study from bibliography if available
- **(c)** Dosage/quantity if the book specifies one
- **(d)** A confidence level:
  - **high**: claim cites a specific study with clear mechanism
  - **medium**: claim has mechanism but no specific study, or study is observational
  - **low**: book assertion without mechanism or study. Include the raw quote for manual review.

## Failure Modes

- **Epub cannot be read:** Check it's a valid zip. `python3 -c "import zipfile; zipfile.ZipFile('file.epub')"`
- **Chapter has no food content:** Write empty ingredients array. Not an error.
- **Ingredient name ambiguity:** Flag near-matches for manual review during consolidation.
- **References section not found:** Skip Step 4, note in summary.
- **DRM-encrypted epub:** The epub must be DRM-free. If content looks like binary garbage, the DRM hasn't been removed.

## Text File Fallback

If no epub or PDF found but `data/book-raw/chapter-*.txt` files exist, process each
text file as a standalone chapter. Skip TOC scan and reference extraction.
