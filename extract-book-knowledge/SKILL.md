---
name: extract-book-knowledge
version: 0.4.0
description: |
  Extract structured food/ingredient claims from a longevity/health book.
  Reads an epub, PDF, or plain-text chapter files; identifies the book by manifest;
  emits canonical-shape JSON tagged with the book's slug so multiple books can be
  processed without collision.
  Use when asked to "extract", "process book", "book claims", "scan book", or "parse ingredients".
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
---

# Extract Book Knowledge

Scan a book and extract every food/ingredient claim into canonical-shape JSON.
**Book identity is required.** Every chapter JSON carries `book`, `author`, and
`book_slug` at the top level so downstream skills can attribute claims correctly
when multiple books are in the dataset.

## Step 0: Book identity (mandatory before any extraction)

Every book gets a slug, declared once in a manifest file. The slug is the primary
key that propagates through every downstream skill — never re-derive it.

```bash
ls data/book-raw/*/_book.json 2>/dev/null && echo "MANIFESTS_EXIST" || echo "NO_MANIFESTS"
```

If the user is extracting a new book, ask: book title and author. Then write the
manifest before reading any chapter content:

```bash
SLUG=$(python3 scripts/lib.py slugify "BOOK TITLE")
mkdir -p data/book-raw/$SLUG
cat > data/book-raw/$SLUG/_book.json <<EOF
{
  "slug": "$SLUG",
  "title": "BOOK TITLE",
  "author": "AUTHOR FULL NAME"
}
EOF
```

After this, move the source file(s) into `data/book-raw/$SLUG/`. If a manifest
already exists for this book, reuse the existing slug — never re-derive from
typed title.

To list known books:

```bash
python3 scripts/lib.py books
```

## Model Config

```bash
_MODEL=$(python3 -c "import json; d=json.load(open('.longevity-skills.json')); print(d['models'].get('extraction','sonnet'))" 2>/dev/null || echo "sonnet")
echo "MODEL: $_MODEL (extraction)"
```

## Inputs and outputs

Per-book layout. Substitute `<slug>` with the value from `_book.json`:

- Inputs: `data/book-raw/<slug>/*.epub` (preferred), `*.pdf`, or `chapter-*.txt`
- Outputs:
  - `data/book-extracts/<slug>/chapter-NN.json` — one per chapter
  - `data/book-extracts/<slug>/ingredients-master.json` — consolidated list
  - `data/book-extracts/<slug>/references.json` — bibliography
  - `data/book-extracts/<slug>/_scan-plan.json` — which chapters to process

All chapter and master JSONs MUST conform to `schemas/book-extract.schema.json`.

## Canonical claim shape (CRITICAL)

Every claim MUST use these exact field names — `text`/`reference`/`mechanism`/
`recommendation`/`confidence`. Do NOT emit `claim` or `study_ref` (legacy).
The validator at write-time will reject the legacy shape.

```json
{
  "text": "Walnuts lower LDL cholesterol in adults at risk.",
  "mechanism": "Omega-3 ALA reduces hepatic VLDL output.",
  "recommendation": "1 ounce daily",
  "reference": "Estruch et al. 2018",
  "confidence": "high"
}
```

Every relationship MUST use `with`/`type`/`note`:

```json
{ "with": "olive oil", "type": "synergy", "note": "ALA + MUFA pair well." }
```

Every chapter JSON must have top-level `book`, `author`, `book_slug`,
`chapter`, `page_range`, `ingredients`. Validate before writing:

```bash
python3 scripts/lib.py validate book-extract data/book-extracts/<slug>/chapter-04.json
```

Invalid files are written to `data/.invalid/` and the skill exits non-zero —
fix the prompt or hand-edit before continuing.

## Step 1: Detect input

```bash
SLUG="<from_book.json>"
EPUB=$(find data/book-raw/$SLUG -name "*.epub" -type f 2>/dev/null | head -1)
PDF=$(find data/book-raw/$SLUG -name "*.pdf" -type f 2>/dev/null | head -1)
TXT_COUNT=$(find data/book-raw/$SLUG -name "chapter-*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "EPUB: ${EPUB:-none}  PDF: ${PDF:-none}  TXT: $TXT_COUNT"
```

If nothing found, stop with a clear error.

## Step 2: Build the scan plan

Identify food-relevant chapters from the TOC. Write `data/book-extracts/<slug>/_scan-plan.json`:

```json
{
  "book_slug": "<slug>",
  "primary_chapters": [{"number": 4, "title": "...", "file": "OEBPS/chapter04.xhtml"}],
  "secondary_chapters": [],
  "references_file": "OEBPS/references.xhtml"
}
```

## Step 3: Extract each chapter

For each chapter in the scan plan, read the text, identify every food/ingredient
mentioned, and emit a canonical-shape chapter JSON. Every chapter object has these
required top-level fields:

```json
{
  "book": "<from manifest>",
  "author": "<from manifest>",
  "book_slug": "<slug>",
  "chapter": "Chapter 4: The Science of Healthy Nutrition",
  "chapter_number": 4,
  "page_range": "estimated",
  "ingredients": [ ... ]
}
```

For each ingredient, populate `claims` (with canonical field names!), optionally
`consumption` and `relationships`. Validate before writing.

## Step 4: Extract references

Bibliography goes to `data/book-extracts/<slug>/references.json`. This file isn't
schema-validated (its shape is up to you).

## Step 5: Consolidate to ingredients-master.json

Walk every chapter JSON, merge duplicate ingredients (same name across chapters),
inherit claims to the master. The master file itself conforms to the Book Extract
schema (same `book`/`author`/`book_slug` headers, single `ingredients[]` array).

```bash
python3 scripts/lib.py validate book-extract data/book-extracts/<slug>/ingredients-master.json
```

## Step 6: Summary report

Print total ingredients, total claims, chapters processed, top 10 most-cited
ingredients, low-confidence claims needing review.

## Failure modes

- **Manifest missing:** Stop. Ask the user for book title+author, write the manifest.
- **Validator rejects a chapter:** The chapter JSON went to `data/.invalid/`. Read
  the error, fix the prompt or hand-edit, re-run.
- **DRM-encrypted epub:** Content looks like binary garbage. Stop — the user
  needs to strip DRM before this skill can read it.
- **Chapter has no food content:** Write an empty `ingredients` array. Not an error.

## Quality rubric

Every claim must include:
- A specific mechanism of action (not "is good for you" — "inhibits NF-kB pathway").
- At least one reference (chapter+page or study citation or "book-assertion").
- Recommendation field populated if the book specifies amount/frequency/preparation;
  null if no actionable guidance attached to this specific claim.
- A confidence level: high / medium / low.
