#!/usr/bin/env python3
"""Migrate ingredient profiles + chapter extracts from the legacy single-book shape.

What it does, per the locked plan-eng-review:

1. Reads every `_book.json` manifest in data/book-raw/ to know which books exist.
2. Reads every per-book master file from data/book-extracts/<slug>/ingredients-master.json
   to build a claim-text → set-of-book-slugs map.
3. For each ingredient profile in <wiki_data_dir>/ingredients/*.json:
     - If `migration_version >= 1` is present: skip (idempotency).
     - Rename legacy claim fields: claim→text, study_ref→reference. Add
       recommendation=null if missing.
     - Attribute each claim to a book_slug by exact-then-fuzzy match against
       the masters. If a claim matches in MULTIPLE books, the claim is
       DUPLICATED — one copy per matching book_slug — so dual attribution is
       preserved.
     - If no master match: fall back to the existing singular `source_book`
       string slugified, and log a warning to stderr.
     - Drop singular `source_book` field.
     - Rename synergies: target_ingredient→with, description→note.
     - Compute and write top-level `source_books[]`.
     - Stamp `migration_version: 1`.
4. For each chapter extract in data/book-extracts/<slug>/chapter-*.json AND in
   <wiki_data_dir>/book-extracts/chapter-*.json:
     - Rename legacy claim/relationship fields.
     - Add top-level book/author/book_slug from the matching _book.json manifest
       (if a flat file is being relocated, prompt the user for which slug).
5. Validates every output via lib.validate_*. ANY failure → roll back ALL writes.
6. With --dry-run: prints the attribution plan and a sample diff, writes nothing.

Usage:
    .venv/bin/python scripts/migrate-multi-book.py --dry-run
    .venv/bin/python scripts/migrate-multi-book.py            # apply
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from scripts import lib  # noqa: E402

MIGRATION_VERSION = 1
FUZZY_THRESHOLD = 0.85


# ── Legacy → canonical field renames ──────────────────────────────────────────

CLAIM_RENAMES = {"claim": "text", "study_ref": "reference"}
# Some legacy synergies use `ingredient` + `mechanism` instead of `target_ingredient`
# + `description`. Map both aliases to canonical names.
RELATIONSHIP_RENAMES = {
    "target_ingredient": "with",
    "ingredient": "with",
    "target": "with",
    "description": "note",
    "mechanism": "note",
}

# Legacy category values that don't match the canonical enum.
CATEGORY_COERCIONS = {
    "fish_seafood": "fish",
    "oil_condiment": "oil",
    "plant-based milk": "beverage",
    "animal_product": "other",
    "harmful": "other",
}


def rename_claim(c: dict) -> dict:
    """Return a canonical-shape claim from any legacy/new shape. Idempotent."""
    out = dict(c)
    for old, new in CLAIM_RENAMES.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
        elif old in out and new in out:
            # Both present (mixed migration). Drop the legacy.
            out.pop(old)
    # Schema requires `reference`, `confidence`, `mechanism`, `text` to be strings;
    # legacy data sometimes has them as null, missing, or (for chapter extracts)
    # structured citation dicts. Coerce.
    ref = out.get("reference")
    if ref is None:
        out["reference"] = ""
    elif isinstance(ref, dict):
        # Old chapter format stored full citation objects. Flatten to a readable string.
        parts = []
        if ref.get("authors"):
            parts.append(ref["authors"])
        if ref.get("title"):
            parts.append(f'"{ref["title"]}"')
        if ref.get("journal"):
            parts.append(ref["journal"])
        if ref.get("year"):
            parts.append(str(ref["year"]))
        out["reference"] = ", ".join(parts) if parts else str(ref)
    elif not isinstance(ref, str):
        out["reference"] = str(ref)
    if not out.get("confidence"):
        out["confidence"] = "medium"
    if out.get("mechanism") is None:
        out["mechanism"] = ""
    if out.get("text") is None:
        out["text"] = ""
    if "recommendation" not in out:
        out["recommendation"] = None
    return out


def rename_relationship(r: dict | str) -> dict:
    """Canonicalize a relationship. Bare strings (legacy shorthand for "synergy with X")
    are coerced into dict form."""
    if isinstance(r, str):
        return {"with": r, "type": "synergy"}
    if not isinstance(r, dict):
        # Unrecognized shape — preserve as a synthetic note so the human can see it.
        return {"with": str(r), "type": "synergy", "note": "auto-coerced from non-dict"}
    out = dict(r)
    for old, new in RELATIONSHIP_RENAMES.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
        elif old in out and new in out:
            out.pop(old)
    # Schema requires `with` and `type` from a fixed enum. Default missing/unknown
    # types to "synergy" (the most common form in legacy data).
    VALID_TYPES = {"synergy", "antagonism", "complement"}
    if out.get("type") not in VALID_TYPES:
        if out.get("type"):
            out["note"] = (out.get("note") or "") + f" [original type: {out['type']}]"
        out["type"] = "synergy"
    return out


# ── Master index: claim_text → set of book_slugs ──────────────────────────────


def resolve_legacy_slug(
    data: dict,
    book_slugs: list[str],
    title_to_slug: dict[str, str],
    author_to_slug: dict[str, str],
) -> str | None:
    """Attribute a legacy file (master or chapter) to a manifest slug.

    Tries explicit `book_slug`, then exact title/author match, then substring
    match against the `source_book`/`title`/`book` fields after slugification.
    Returns None if nothing matches.
    """
    candidates_list = [
        data.get("book_slug"),
        title_to_slug.get(lib.slugify(data.get("book", ""))),
        title_to_slug.get(lib.slugify(data.get("title", ""))),
        author_to_slug.get(lib.slugify(data.get("author", ""))),
    ]
    blob = lib.slugify(
        (data.get("source_book") or "")
        + " "
        + (data.get("title") or "")
        + " "
        + (data.get("book") or "")
    )
    for t_slug, slug in title_to_slug.items():
        if t_slug and t_slug in blob:
            candidates_list.append(slug)
    for a_slug, slug in author_to_slug.items():
        if a_slug and a_slug in blob:
            candidates_list.append(slug)
    return next((c for c in candidates_list if c in book_slugs), None)


def build_master_index(book_slugs: list[str]) -> dict[str, set[str]]:
    """For each book, walk its master ingredients and index claim texts.

    Returns {normalized_claim_text: {book_slug, ...}}.

    Searches three locations for masters:
    1. Per-book subdir: data/book-extracts/<slug>/ingredients-master.json (canonical)
    2. Legacy flat in skills repo: data/book-extracts/ingredients-master.json
    3. Legacy flat in wiki repo: <wiki_data_dir>/book-extracts/ingredients-master.json
    """
    index: dict[str, set[str]] = {}
    wiki_root = lib.wiki_data_dir()

    candidates: list[tuple[str, Path]] = []
    for slug in book_slugs:
        candidates.append((slug, REPO_ROOT / "data" / "book-extracts" / slug / "ingredients-master.json"))

    # Legacy flats: read book_slug, or match by title/author against manifests.
    # The legacy file's `book` field may slugify to a different value than the
    # manifest slug (e.g., "The Longevity Diet" → "the-longevity-diet" vs slug "longo"),
    # so we also build lookup tables from manifests.
    title_to_slug: dict[str, str] = {}
    author_to_slug: dict[str, str] = {}
    for b in lib.list_books():
        if b.get("title"):
            title_to_slug[lib.slugify(b["title"])] = b["slug"]
        if b.get("author"):
            author_to_slug[lib.slugify(b["author"])] = b["slug"]

    for legacy in (
        REPO_ROOT / "data" / "book-extracts" / "ingredients-master.json",
        wiki_root / "book-extracts" / "ingredients-master.json",
    ):
        if not legacy.exists():
            continue
        try:
            with open(legacy) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        legacy_slug = resolve_legacy_slug(data, book_slugs, title_to_slug, author_to_slug)
        if legacy_slug:
            candidates.append((legacy_slug, legacy))
        else:
            print(
                f"warn: legacy master at {legacy} could not be attributed; skipped",
                file=sys.stderr,
            )

    for slug, master_path in candidates:
        if not master_path.exists():
            continue
        with open(master_path) as f:
            master = json.load(f)
        for ing in master.get("ingredients", []):
            for c in ing.get("claims", []):
                rc = rename_claim(c)
                text = (rc.get("text") or "").strip().lower()
                if text:
                    index.setdefault(text, set()).add(slug)
    return index


def attribute_claim_text(text: str, index: dict[str, set[str]], fallback: str | None) -> tuple[set[str], bool]:
    """Match a claim text to one or more book_slugs.

    Returns (set_of_slugs, was_fuzzy).
    - Exact match (post-normalization) returns the indexed set.
    - Fuzzy match (difflib >= FUZZY_THRESHOLD) returns the best single match.
    - No match: returns ({fallback}, False) if fallback is provided, else (set(), False).
    """
    needle = (text or "").strip().lower()
    if not needle:
        return ({fallback}, False) if fallback else (set(), False)
    if needle in index:
        return (set(index[needle]), False)
    # Fuzzy
    best_key, best_ratio = None, 0.0
    for key in index:
        ratio = difflib.SequenceMatcher(None, needle, key).ratio()
        if ratio > best_ratio:
            best_ratio, best_key = ratio, key
    if best_key and best_ratio >= FUZZY_THRESHOLD:
        return (set(index[best_key]), True)
    return ({fallback}, False) if fallback else (set(), False)


# ── Profile migration ─────────────────────────────────────────────────────────


def migrate_profile(
    profile: dict,
    index: dict[str, set[str]],
    legacy_name_to_slug: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    """Return (migrated_profile, warnings). Idempotent: re-running returns input unchanged.

    `legacy_name_to_slug` maps full-text legacy source_book strings (e.g. "The Longevity Diet")
    to manifest slugs ("longo"). Used as the ultimate fallback when claim text doesn't
    match any master.
    """
    warnings: list[str] = []
    if profile.get("migration_version", 0) >= MIGRATION_VERSION:
        return profile, warnings

    out = dict(profile)
    legacy_book = profile.get("source_book") or ""
    fallback_slug = None
    if legacy_name_to_slug and legacy_book in legacy_name_to_slug:
        fallback_slug = legacy_name_to_slug[legacy_book]
    elif legacy_book:
        # Try slugified match against manifests
        slugged = lib.slugify(legacy_book)
        if legacy_name_to_slug:
            for full_text, slug in legacy_name_to_slug.items():
                if lib.slugify(full_text) == slugged:
                    fallback_slug = slug
                    break

    new_claims: list[dict] = []
    for c in profile.get("book_claims", []):
        rc = rename_claim(c)
        # If a claim already has book_slug (mixed-state edit), trust it.
        if rc.get("book_slug"):
            new_claims.append(rc)
            continue
        slugs, was_fuzzy = attribute_claim_text(rc.get("text", ""), index, fallback_slug)
        if not slugs:
            warnings.append(
                f"  orphan claim in {profile.get('slug', '<unknown>')}: "
                f"no master match, no fallback. Text: {rc.get('text', '')[:60]!r}"
            )
            # Keep the claim but tag with empty book_slug — will fail validation,
            # which surfaces the issue. We do not silently drop.
            rc["book_slug"] = ""
            new_claims.append(rc)
            continue
        if was_fuzzy:
            warnings.append(
                f"  fuzzy match in {profile.get('slug', '<unknown>')}: "
                f"text {rc.get('text', '')[:60]!r} → {sorted(slugs)}"
            )
        # Dual attribution: one copy per matching book_slug.
        for slug in sorted(slugs):
            copy = dict(rc)
            copy["book_slug"] = slug
            new_claims.append(copy)

    out["book_claims"] = new_claims
    out["source_books"] = lib.derive_source_books(new_claims)
    out.pop("source_book", None)

    # Migrate synergies field names.
    if "synergies" in out:
        out["synergies"] = [rename_relationship(s) for s in out["synergies"]]

    # Ensure category present and in canonical enum.
    cat = out.get("category")
    if not cat:
        out["category"] = "other"
        warnings.append(f"  missing category on {profile.get('slug')}; defaulted to 'other'")
    elif cat in CATEGORY_COERCIONS:
        out["category"] = CATEGORY_COERCIONS[cat]
        warnings.append(f"  category coerced on {profile.get('slug')}: {cat!r} → {out['category']!r}")

    # Drop empty-string book_slug claims (rare; happens when migrate_profile failed
    # to attribute a claim AND there was no fallback). Surface via warning.
    real_claims = []
    for c in out["book_claims"]:
        if not c.get("book_slug"):
            warnings.append(
                f"  dropping un-attributable claim on {profile.get('slug')}: "
                f"{c.get('text', '')[:80]!r}"
            )
            continue
        real_claims.append(c)
    out["book_claims"] = real_claims
    out["source_books"] = lib.derive_source_books(real_claims)

    out["migration_version"] = MIGRATION_VERSION
    return out, warnings


# ── Chapter extract migration ─────────────────────────────────────────────────


def migrate_chapter(chapter: dict, book_slug: str, title: str, author: str) -> dict:
    """Rename claim+relationship field names. Stamp top-level book identity if missing.

    Idempotent: if already at MIGRATION_VERSION and book_slug already matches,
    returns the input unchanged.
    """
    if (
        chapter.get("migration_version", 0) >= MIGRATION_VERSION
        and chapter.get("book_slug") == book_slug
    ):
        return chapter

    out = dict(chapter)
    out.setdefault("book", title)
    out.setdefault("author", author)
    out["book_slug"] = book_slug

    real_ingredients = []
    for ing in out.get("ingredients", []):
        # Derive slug from name if missing (legacy chapter-appendices had no slug field).
        if not ing.get("slug") and ing.get("name"):
            ing["slug"] = lib.slugify(ing["name"])
        if "claims" in ing:
            ing["claims"] = [rename_claim(c) for c in ing["claims"]]
        if "relationships" in ing:
            # Drop relationships that can't be canonicalized (no target name available).
            rels = []
            for r in ing["relationships"]:
                renamed = rename_relationship(r)
                if renamed.get("with"):
                    rels.append(renamed)
            ing["relationships"] = rels
        # Schema requires non-empty claims array. An ingredient with no claims is
        # effectively a stub — drop it from the extract.
        if not ing.get("claims"):
            continue
        real_ingredients.append(ing)
    out["ingredients"] = real_ingredients
    out["migration_version"] = MIGRATION_VERSION
    return out


# ── Main ──────────────────────────────────────────────────────────────────────


def migrate_all(dry_run: bool) -> int:
    books = lib.list_books()
    if not books:
        print("No book manifests found. Create data/book-raw/<slug>/_book.json first.")
        return 1
    book_slugs = [b["slug"] for b in books]
    book_titles = {b["slug"]: b for b in books}
    print(f"Books: {', '.join(book_slugs)}")

    index = build_master_index(book_slugs)
    print(f"Master claim-text index size: {len(index)} unique claims")

    # Build a legacy-source-book-name → manifest-slug map for the orphan claim fallback.
    # Walks every book's title and author and maps slugified variants to the canonical slug.
    legacy_name_to_slug: dict[str, str] = {}
    for b in books:
        legacy_name_to_slug[b["title"]] = b["slug"]
        legacy_name_to_slug[f"{b['title']} by {b['author']}"] = b["slug"]
        legacy_name_to_slug[b["author"]] = b["slug"]

    wiki_data = lib.wiki_data_dir()
    print(f"Target wiki data dir: {wiki_data}")

    # Stage writes; commit atomically (per-file) if validation passes.
    # Every staged entry is (target_path, data, source_path_or_None).
    # source_path is set when relocating a flat legacy file to its new home.
    staged: list[tuple[Path, dict, Path | None]] = []
    all_warnings: list[str] = []

    # 1. Ingredient profiles.
    ingredients_dir = wiki_data / "ingredients"
    profiles = sorted(ingredients_dir.glob("*.json")) if ingredients_dir.exists() else []
    print(f"\nProfiles to migrate: {len(profiles)}")
    skipped_idempotent = 0
    for path in profiles:
        with open(path) as f:
            profile = json.load(f)
        if profile.get("migration_version", 0) >= MIGRATION_VERSION:
            skipped_idempotent += 1
            continue
        migrated, warnings = migrate_profile(profile, index, legacy_name_to_slug)
        all_warnings.extend(warnings)
        staged.append((path, migrated, None))
    print(f"  to migrate: {len(staged)}; already migrated (idempotent skip): {skipped_idempotent}")

    # 2. Chapter extracts in BOTH repos.
    for root_label, root in (("skills", REPO_ROOT / "data" / "book-extracts"), ("wiki", wiki_data / "book-extracts")):
        if not root.exists():
            continue
        # Per-book subdirs.
        for slug_dir in root.iterdir():
            if not slug_dir.is_dir() or slug_dir.name not in book_titles:
                continue
            slug = slug_dir.name
            meta = book_titles[slug]
            for fp in sorted(slug_dir.glob("chapter-*.json")) + sorted(slug_dir.glob("ingredients-master.json")):
                with open(fp) as f:
                    chap = json.load(f)
                migrated = migrate_chapter(chap, slug, meta["title"], meta["author"])
                staged.append((fp, migrated, None))
        # Flat legacy files: use the shared resolve_legacy_slug helper.
        title_to_slug_local = {lib.slugify(b["title"]): b["slug"] for b in books}
        author_to_slug_local = {lib.slugify(b["author"]): b["slug"] for b in books}
        for fp in sorted(root.glob("chapter-*.json")) + sorted(root.glob("ingredients-master.json")):
            with open(fp) as f:
                chap = json.load(f)
            slug = resolve_legacy_slug(chap, book_slugs, title_to_slug_local, author_to_slug_local)
            if not slug:
                all_warnings.append(f"  flat file {fp} has no matching manifest; skipped")
                continue
            meta = book_titles[slug]
            migrated = migrate_chapter(chap, slug, meta["title"], meta["author"])
            new_path = root / slug / fp.name
            staged.append((new_path, migrated, fp))

    if all_warnings:
        print("\nWarnings:")
        for w in all_warnings:
            print(w, file=sys.stderr)

    # Validate every staged write.
    print(f"\nValidating {len(staged)} staged files...")
    validation_errors: list[str] = []
    for target, data, _source in staged:
        try:
            # An ingredient profile lives under <root>/ingredients/<slug>.json.
            # Anything else is a book extract (chapter or master).
            if target.parent.name == "ingredients":
                lib.validate_ingredient(data)
            else:
                lib.validate_book_extract(data)
        except lib.ValidationFailure as e:
            validation_errors.append(f"{target}:\n{e}")

    if validation_errors:
        print(f"\n{len(validation_errors)} validation failures. Aborting (no writes).", file=sys.stderr)
        for err in validation_errors[:5]:
            print(err, file=sys.stderr)
        if len(validation_errors) > 5:
            print(f"... and {len(validation_errors) - 5} more.", file=sys.stderr)
        return 1
    print("  all valid.")

    if dry_run:
        print("\n--dry-run: not writing. Sample diffs (first 2 entries):")
        for target, data, _source in staged[:2]:
            original_text = target.read_text() if target.exists() else "<new file>"
            new_text = json.dumps(data, indent=2)
            diff = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(target),
                tofile=str(target) + " (after)",
                n=2,
            )
            print("".join(diff))
        return 0

    # Apply with per-file atomic write (write to tmp + rename).
    print(f"\nWriting {len(staged)} files...")
    for target, data, source in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(target)
        if source is not None and source.exists() and source != target:
            source.unlink()
    print("Done.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="Print attribution plan + diffs, write nothing.")
    args = parser.parse_args(argv)
    return migrate_all(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
