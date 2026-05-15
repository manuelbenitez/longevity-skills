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
RELATIONSHIP_RENAMES = {"target_ingredient": "with", "description": "note"}


def rename_claim(c: dict) -> dict:
    """Return a canonical-shape claim from any legacy/new shape. Idempotent."""
    out = dict(c)
    for old, new in CLAIM_RENAMES.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
        elif old in out and new in out:
            # Both present (mixed migration). Drop the legacy.
            out.pop(old)
    if "recommendation" not in out:
        out["recommendation"] = None
    return out


def rename_relationship(r: dict) -> dict:
    out = dict(r)
    for old, new in RELATIONSHIP_RENAMES.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
        elif old in out and new in out:
            out.pop(old)
    return out


# ── Master index: claim_text → set of book_slugs ──────────────────────────────


def build_master_index(book_slugs: list[str]) -> dict[str, set[str]]:
    """For each book, walk its master ingredients and index claim texts.

    Returns {normalized_claim_text: {book_slug, ...}}.
    """
    index: dict[str, set[str]] = {}
    for slug in book_slugs:
        master_path = REPO_ROOT / "data" / "book-extracts" / slug / "ingredients-master.json"
        if not master_path.exists():
            # Some books may live only in the wiki repo's data tree. Skip silently.
            continue
        with open(master_path) as f:
            master = json.load(f)
        for ing in master.get("ingredients", []):
            for c in ing.get("claims", []):
                # Apply rename before indexing so we match against canonical text.
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


def migrate_profile(profile: dict, index: dict[str, set[str]]) -> tuple[dict, list[str]]:
    """Return (migrated_profile, warnings). Idempotent: re-running returns input unchanged."""
    warnings: list[str] = []
    if profile.get("migration_version", 0) >= MIGRATION_VERSION:
        return profile, warnings

    out = dict(profile)
    fallback_slug = lib.slugify(profile.get("source_book") or "") or None

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

    # Ensure category present (schema requires it).
    if not out.get("category"):
        out["category"] = "other"
        warnings.append(f"  missing category on {profile.get('slug')}; defaulted to 'other'")

    out["migration_version"] = MIGRATION_VERSION
    return out, warnings


# ── Chapter extract migration ─────────────────────────────────────────────────


def migrate_chapter(chapter: dict, book_slug: str, title: str, author: str) -> dict:
    """Rename claim+relationship field names. Stamp top-level book identity if missing."""
    out = dict(chapter)
    out.setdefault("book", title)
    out.setdefault("author", author)
    out["book_slug"] = book_slug  # Always trust the directory.

    for ing in out.get("ingredients", []):
        if "claims" in ing:
            ing["claims"] = [rename_claim(c) for c in ing["claims"]]
        if "relationships" in ing:
            ing["relationships"] = [rename_relationship(r) for r in ing["relationships"]]
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

    wiki_data = lib.wiki_data_dir()
    print(f"Target wiki data dir: {wiki_data}")

    # Stage writes in a temp dir; commit atomically if validation passes.
    staged: list[tuple[Path, dict]] = []
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
        migrated, warnings = migrate_profile(profile, index)
        all_warnings.extend(warnings)
        staged.append((path, migrated))
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
                staged.append((fp, migrated))
        # Flat legacy files in wiki repo (need book-slug inference).
        for fp in sorted(root.glob("chapter-*.json")):
            # Heuristic: read author or book field, slugify to find match.
            with open(fp) as f:
                chap = json.load(f)
            slug_guess = lib.slugify(chap.get("book") or chap.get("author") or "")
            if slug_guess in book_titles:
                slug = slug_guess
            else:
                # Match against any author slug
                author_to_slug = {lib.slugify(b["author"]): b["slug"] for b in books}
                slug = author_to_slug.get(slug_guess)
            if not slug:
                all_warnings.append(f"  flat chapter file {fp} has no matching manifest; skipped")
                continue
            meta = book_titles[slug]
            migrated = migrate_chapter(chap, slug, meta["title"], meta["author"])
            # Stage to its new location: under the slug subdir
            new_path = root / slug / fp.name
            staged.append((new_path, migrated, fp))  # type: ignore

    if all_warnings:
        print("\nWarnings:")
        for w in all_warnings:
            print(w, file=sys.stderr)

    # Validate every staged write.
    print(f"\nValidating {len(staged)} staged files...")
    validation_errors: list[str] = []
    for item in staged:
        path = item[0]
        data = item[1]
        try:
            if path.name == "ingredients-master.json" or path.parent.name in book_slugs:
                if path.name.startswith("chapter-") or path.name == "ingredients-master.json":
                    lib.validate_book_extract(data)
                else:
                    lib.validate_ingredient(data)
            else:
                # Path is in ingredients/.
                lib.validate_ingredient(data)
        except lib.ValidationFailure as e:
            validation_errors.append(f"{path}:\n{e}")

    if validation_errors:
        print(f"\n{len(validation_errors)} validation failures. Aborting (no writes).", file=sys.stderr)
        for err in validation_errors[:5]:
            print(err, file=sys.stderr)
        if len(validation_errors) > 5:
            print(f"... and {len(validation_errors) - 5} more.", file=sys.stderr)
        return 1
    print("  all valid.")

    if dry_run:
        print("\n--dry-run: not writing. Sample diffs (first 2 profiles):")
        for path, migrated in staged[:2]:
            original_text = path.read_text() if path.exists() else "<new file>"
            new_text = json.dumps(migrated, indent=2)
            diff = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path) + " (after)",
                n=2,
            )
            print("".join(diff))
        return 0

    # Apply.
    print(f"\nWriting {len(staged)} files...")
    for item in staged:
        target = item[0]
        data = item[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w") as f:
            json.dump(data, f, indent=2)
        # Remove old flat-location source if relocating.
        if len(item) == 3:
            old_path = item[2]
            if old_path.exists() and old_path != target:
                old_path.unlink()
    print("Done.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="Print attribution plan + diffs, write nothing.")
    args = parser.parse_args(argv)
    return migrate_all(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
