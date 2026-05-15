#!/usr/bin/env python3
"""Batch-enrich ingredient profiles using Claude via the Anthropic API.

Reads a per-book dedup report, looks up book metadata from its header, and
enriches every ingredient that needs new research. Multi-book aware:
- New ingredients get a fresh profile with claims tagged by book_slug.
- Existing ingredients whose claims don't yet include this book get their
  claims appended (book_slug-tagged) WITHOUT a new LLM call. Existing
  research is preserved byte-identical.
- Ingredients already cited from this book are skipped.

Usage:
    .venv/bin/python research-ingredient/enrich.py [--book <slug>] [ingredient-name ...]

Without --book: reads the most recent dedup report and uses its book header.
With --book <slug>: loads data/dedup/<slug>-dedup-report.json explicitly.

Configuration:
    LONGEVITY_MODEL              override model (default: claude-haiku-4-5-20251001)
    LONGEVITY_WIKI_DATA_DIR      override wiki repo's data dir (overrides config)
    ANTHROPIC_API_KEY            required for live API calls
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

# Make `scripts/lib.py` importable when run from anywhere in the repo.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from scripts import lib  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────

DEDUP_GLOB = REPO_ROOT / "data" / "dedup" / "*-dedup-report.json"
BATCH_SIZE = 20
MAX_TOKENS = 16384  # was 4096; truncated batches of 20 silently. See plan eng-review.
NON_FOOD_FILE = REPO_ROOT / "data" / "non-food-terms.txt"
RETRY_DELAY_SECONDS = 5

MODEL = os.environ.get("LONGEVITY_MODEL", "claude-haiku-4-5-20251001")


def load_non_food_terms() -> set[str]:
    """Load the shared non-food-terms file. Returns empty set if missing."""
    if not NON_FOOD_FILE.exists():
        return set()
    terms = set()
    with open(NON_FOOD_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            terms.add(line.lower())
    return terms


NON_FOOD = load_non_food_terms()


# ── Dedup report loading ──────────────────────────────────────────────────────


def latest_dedup_report() -> Path:
    reports = sorted(glob.glob(str(DEDUP_GLOB)))
    if not reports:
        print("No dedup report found. Run /dedup-ingredients first.", file=sys.stderr)
        sys.exit(1)
    return Path(reports[-1])


def load_dedup_report(book_slug: str | None) -> tuple[Path, dict]:
    """Returns (report_path, parsed_report). Raises SystemExit if not found."""
    if book_slug:
        path = REPO_ROOT / "data" / "dedup" / f"{book_slug}-dedup-report.json"
        if not path.exists():
            print(f"No dedup report at {path}. Run /dedup-ingredients for {book_slug} first.", file=sys.stderr)
            sys.exit(1)
    else:
        path = latest_dedup_report()
    with open(path) as f:
        return path, json.load(f)


# ── Master file loading ───────────────────────────────────────────────────────


def load_master(book_slug: str) -> dict:
    """Load the per-book master file from data/book-extracts/<slug>/ingredients-master.json."""
    master_path = REPO_ROOT / "data" / "book-extracts" / book_slug / "ingredients-master.json"
    if not master_path.exists():
        print(
            f"No master file at {master_path}. Run /expand-ingredient-groups for {book_slug} first.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(master_path) as f:
        return json.load(f)


# ── Claim lookup (no field rename — canonical shape end-to-end) ───────────────


def get_book_claims(name: str, slug: str, master: dict, book_slug: str) -> list[dict]:
    """Return canonical-shape claims tagged with book_slug.

    Looks up the ingredient by slug (preferred) or by slugified name.
    Returns [] if not found.
    """
    slug_map = {i["slug"]: i for i in master.get("ingredients", [])}
    # Normalize name lookup via slugify both sides so "Beans / Legumes" matches "beans-legumes"
    name_map = {lib.slugify(i["name"]): i for i in master.get("ingredients", [])}

    entry = slug_map.get(slug) or name_map.get(lib.slugify(name))
    if not entry:
        return []

    claims = []
    for c in entry.get("claims", []):
        claims.append(
            {
                "text": c.get("text", ""),
                "mechanism": c.get("mechanism", ""),
                "recommendation": c.get("recommendation"),
                "reference": c.get("reference", ""),
                "confidence": c.get("confidence", "medium"),
                "book_slug": book_slug,
            }
        )
    return claims


# ── Output dir ────────────────────────────────────────────────────────────────


def ingredients_dir() -> Path:
    """Resolve the target dir via lib.wiki_data_dir() and ensure it exists."""
    target = lib.wiki_data_dir() / "ingredients"
    target.mkdir(parents=True, exist_ok=True)
    return target


# ── Queue building (four-bucket dedup) ────────────────────────────────────────


def build_queue_from_dedup(report: dict, master: dict, book_slug: str) -> list[dict]:
    """Build the enrichment queue from the dedup report.

    Reads both `new` and `new-to-book` buckets. `existing-same-book` and `fuzzy`
    are intentionally skipped.

    For each entry, returns: {"name", "slug", "claims", "bucket"}
    where claims are canonical-shape and tagged with the current book_slug.
    """
    queue: list[dict] = []
    seen_slugs: set[str] = set()

    for bucket_name in ("new", "new-to-book"):
        for entry in report.get(bucket_name, []):
            name = entry.get("extracted_name") or entry.get("name")
            if not name:
                continue
            if name.lower() in NON_FOOD:
                continue
            slug = entry.get("slug") or lib.slugify(name)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            claims = get_book_claims(name, slug, master, book_slug)
            queue.append(
                {
                    "name": name,
                    "slug": slug,
                    "claims": claims,
                    "bucket": bucket_name,
                }
            )
    return queue


def build_queue_from_args(names: list[str], master: dict, book_slug: str) -> list[dict]:
    """Manual mode: enrich the named ingredients regardless of dedup state."""
    queue: list[dict] = []
    seen: set[str] = set()
    for name in names:
        if name.lower() in NON_FOOD:
            print(f"  skip {name} (non-food)", file=sys.stderr)
            continue
        slug = lib.slugify(name)
        if slug in seen:
            continue
        seen.add(slug)
        claims = get_book_claims(name, slug, master, book_slug)
        # Mark as 'new' so the LLM is called; merge_or_skip will adapt at write time.
        queue.append({"name": name, "slug": slug, "claims": claims, "bucket": "new"})
    return queue


# ── Enrichment prompt ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You enrich ingredient profiles for a longevity wiki grounded in peer-reviewed science.
For each ingredient you receive, return ONLY a JSON object with these fields:
  - supplementary_research: array of 2 objects {source, url, finding, agrees_with_book}
  - flavor_profile: {taste: [], aroma: [], texture: [], culinary_category: ""}
  - culinary_pairings: array of 3 objects {ingredient, tradition, source}
  - nutrient_highlights: array of 2-3 objects {compound, amount_per_100g, bioavailability_notes}
  - synergies: array of 2-3 objects {with, type (synergy|antagonism|complement), note}
  - category: one word from: fish|vegetable|fruit|grain|legume|nut|seed|oil|dairy|egg|meat|supplement|nutrient|beverage|spice|herb|mushroom|shellfish|other

Rules:
- supplementary_research: use real PubMed PMIDs where you know them (url: https://pubmed.ncbi.nlm.nih.gov/PMID/)
- If research contradicts the book claim, set agrees_with_book: false and explain
- Be concise — this is a wiki, not a textbook
- Longevity framing throughout: mechanisms, aging, disease prevention
- Return a JSON ARRAY — one object per ingredient, same order as input
- No markdown, no explanation — raw JSON array only\
"""


def make_user_prompt(batch: list[dict]) -> str:
    lines = [f"Enrich these {len(batch)} ingredients:\n"]
    for i, ing in enumerate(batch, 1):
        lines.append(f"{i}. {ing['name']}")
        if ing["claims"]:
            lines.append("   Book claims:")
            for c in ing["claims"][:3]:  # cap at 3 to keep prompt small
                lines.append(f"   - {c['text']} ({c['confidence']})")
        else:
            lines.append("   Book claims: none (new ingredient, use general knowledge)")
    return "\n".join(lines)


# ── API call with retry ───────────────────────────────────────────────────────


def enrich_batch(batch: list[dict], client: anthropic.Anthropic) -> list[dict]:
    """Call the API once with retry-on-transient. Returns list aligned with batch.

    On JSON parse failure, raises — caller is expected to handle. Individual
    ingredients in the returned list may be empty dicts if the LLM produced
    nothing useful for that slot.
    """
    prompt = make_user_prompt(batch)
    print(f"  → calling {MODEL} for {len(batch)} ingredients...")

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except (anthropic.APIStatusError, anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            last_error = e
            if attempt == 1:
                print(f"  ⚠ transient API error ({type(e).__name__}); retrying in {RETRY_DELAY_SECONDS}s")
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            print(f"  ✗ API failed twice: {e}", file=sys.stderr)
            raise
    else:
        raise RuntimeError(f"unreachable, last_error={last_error}")

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present.
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    enrichments = json.loads(raw)
    if not isinstance(enrichments, list):
        raise ValueError("Expected JSON array from API; got non-list")
    return enrichments


# ── Profile merge/write ───────────────────────────────────────────────────────


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_or_skip(
    ing: dict,
    enrichment: dict,
    book_slug: str,
    out_dir: Path,
) -> tuple[str, Path | None]:
    """Decide what to do for one ingredient and execute it.

    Returns (action, path_or_None). Actions:
      - "wrote-new"      : created fresh profile
      - "appended-claims": existing profile, added new book's claims
      - "skipped-same-book": existing profile already cites this book
    """
    slug = ing["slug"]
    target = out_dir / f"{slug}.json"

    if target.exists():
        with open(target) as f:
            existing = json.load(f)
        existing_books = set(existing.get("source_books", []))
        # Belt-and-suspenders: also check per-claim book_slug in case source_books drifted.
        for c in existing.get("book_claims", []):
            if c.get("book_slug"):
                existing_books.add(c["book_slug"])
        if book_slug in existing_books:
            return ("skipped-same-book", target)
        # Append new claims, preserve research, recompute denormalized array.
        merged_claims = list(existing.get("book_claims", [])) + ing["claims"]
        existing["book_claims"] = merged_claims
        existing["source_books"] = lib.derive_source_books(merged_claims)
        existing["last_updated"] = utcnow_iso()
        # If this was previously "book-only" and we just added new claims, leave research_status.
        lib.validate_ingredient(existing)
        with open(target, "w") as f:
            json.dump(existing, f, indent=2)
        return ("appended-claims", target)

    # Fresh profile.
    profile = {
        "name": ing["name"],
        "slug": slug,
        "category": enrichment.get("category", "other"),
        "aliases": [],
        "book_claims": ing["claims"],
        "source_books": lib.derive_source_books(ing["claims"]),
        "supplementary_research": enrichment.get("supplementary_research", []),
        "flavor_profile": enrichment.get("flavor_profile", {}),
        "culinary_pairings": enrichment.get("culinary_pairings", []),
        "nutrient_highlights": enrichment.get("nutrient_highlights", []),
        "synergies": enrichment.get("synergies", []),
        "last_updated": utcnow_iso(),
        "last_researched": utcnow_iso(),
        "research_status": "complete" if enrichment else "book-only",
    }
    lib.validate_ingredient(profile)
    with open(target, "w") as f:
        json.dump(profile, f, indent=2)
    return ("wrote-new", target)


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--book", help="Book slug. Defaults to the most recent dedup report.")
    parser.add_argument("names", nargs="*", help="Manual override: enrich these names.")
    args = parser.parse_args(argv)

    report_path, report = load_dedup_report(args.book)
    book_meta = lib.load_book_metadata_from_report(report_path)
    book_slug = book_meta["book_slug"]
    print(f"Using dedup report: {report_path}")
    print(f"Book: {book_meta['book_title']} ({book_meta['author']})  slug={book_slug}")

    master = load_master(book_slug)
    out_dir = ingredients_dir()
    print(f"Output dir: {out_dir}\n")

    queue = build_queue_from_args(args.names, master, book_slug) if args.names else build_queue_from_dedup(report, master, book_slug)
    if not queue:
        print("Nothing to process.")
        return 0

    # Fast path: new-to-book buckets need no LLM call (Decision ARCH-1).
    fast_path = [q for q in queue if q["bucket"] == "new-to-book"]
    slow_path = [q for q in queue if q["bucket"] != "new-to-book"]
    print(f"Queue: {len(slow_path)} new (need enrichment), {len(fast_path)} new-to-book (append-only)")

    summary = {"wrote-new": 0, "appended-claims": 0, "skipped-same-book": 0, "invalid": 0}

    # Fast path first: cheap and isolates failures.
    for ing in fast_path:
        try:
            action, _path = merge_or_skip(ing, {}, book_slug, out_dir)
            summary[action] += 1
            print(f"  ✓ {ing['slug']} → {action}")
        except lib.ValidationFailure as e:
            invalid_path = lib.tray_invalid({"ingredient": ing}, e, ing["slug"])
            summary["invalid"] += 1
            print(f"  ✗ {ing['slug']} → validation failed, trayed at {invalid_path}", file=sys.stderr)

    # Slow path: LLM enrichment, per-ingredient validation.
    if slow_path:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        for start in range(0, len(slow_path), BATCH_SIZE):
            batch = slow_path[start : start + BATCH_SIZE]
            print(f"\nBatch {start // BATCH_SIZE + 1}: {', '.join(i['name'] for i in batch)}")
            try:
                enrichments = enrich_batch(batch, client)
            except (json.JSONDecodeError, ValueError) as e:
                # Tray the whole batch and continue; do not blank-write profiles.
                print(f"  ✗ batch failed to parse: {e}; trayed.", file=sys.stderr)
                lib.tray_invalid({"batch_names": [i["name"] for i in batch], "error": str(e)}, e, f"batch-{start}")
                summary["invalid"] += len(batch)
                continue

            for ing, enrichment in zip(batch, enrichments):
                try:
                    action, _path = merge_or_skip(ing, enrichment or {}, book_slug, out_dir)
                    summary[action] += 1
                    print(f"  ✓ {ing['slug']} → {action}")
                except lib.ValidationFailure as e:
                    invalid_path = lib.tray_invalid(
                        {"ingredient": ing, "enrichment": enrichment}, e, ing["slug"]
                    )
                    summary["invalid"] += 1
                    print(f"  ✗ {ing['slug']} → invalid, trayed at {invalid_path}", file=sys.stderr)

    print("\n── Summary ──")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print()
    print("Tip: set LONGEVITY_MODEL=claude-sonnet-4-6 for higher quality on complex ingredients.")
    # Exit non-zero if any invalid (signals to the human that the tray needs attention).
    return 1 if summary["invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())
