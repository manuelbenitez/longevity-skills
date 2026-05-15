"""Shared utilities for longevity-skills.

Single source of truth for:
- slugify() — kebab-case conversion
- read_book_manifest() / list_books() — _book.json manifest helpers
- load_book_metadata_from_report() — pulls book identity from a dedup report
- validate_book_extract() / validate_ingredient() — JSON schema validation
- derive_source_books() — denormalized array recomputation
- wiki_data_dir() — resolves the wiki repo's data dir from config or env
- tray_invalid() — writes rejected JSON to data/.invalid/ for forensics

CLI usage:
    python scripts/lib.py validate <book-extract|ingredient> <file.json>
    python scripts/lib.py slugify "The Path to Longevity"
    python scripts/lib.py books
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"
BOOK_RAW_DIR = REPO_ROOT / "data" / "book-raw"
INVALID_DIR = REPO_ROOT / "data" / ".invalid"
CONFIG_FILE = REPO_ROOT / ".longevity-skills.json"


# ── Slugify ───────────────────────────────────────────────────────────────────


def slugify(s: str) -> str:
    """Kebab-case conversion. Lowercase, alphanumerics, hyphens only."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ── Book manifests (data/book-raw/<slug>/_book.json) ─────────────────────────


class ManifestError(Exception):
    pass


def read_book_manifest(slug: str) -> dict:
    """Load and validate a book manifest.

    Manifest format: {"slug": "...", "title": "...", "author": "..."}
    Slug in manifest must match the directory name.
    """
    path = BOOK_RAW_DIR / slug / "_book.json"
    if not path.exists():
        raise ManifestError(f"No manifest at {path}. Create it before extracting.")
    with open(path) as f:
        data = json.load(f)
    for key in ("slug", "title", "author"):
        if key not in data or not isinstance(data[key], str) or not data[key].strip():
            raise ManifestError(f"Manifest {path} missing required string field: {key}")
    if data["slug"] != slug:
        raise ManifestError(
            f"Manifest slug ({data['slug']!r}) disagrees with directory name ({slug!r}). "
            f"Reconcile manually."
        )
    return data


def list_books() -> list[dict]:
    """Scan data/book-raw/*/_book.json and return all manifests, sorted by slug."""
    if not BOOK_RAW_DIR.exists():
        return []
    manifests = []
    for child in sorted(BOOK_RAW_DIR.iterdir()):
        manifest_path = child / "_book.json"
        if child.is_dir() and manifest_path.exists():
            try:
                manifests.append(read_book_manifest(child.name))
            except ManifestError as e:
                print(f"warn: skipping {child.name}: {e}", file=sys.stderr)
    return manifests


def load_book_metadata_from_report(report_path: str | Path) -> dict:
    """Pull {book_slug, book_title, author} from a dedup report header."""
    with open(report_path) as f:
        report = json.load(f)
    for key in ("book_slug", "book_title", "author"):
        if key not in report:
            raise ValueError(
                f"Dedup report {report_path} is missing required header field: {key}. "
                f"Re-run /dedup-ingredients with the new schema."
            )
    return {
        "book_slug": report["book_slug"],
        "book_title": report["book_title"],
        "author": report["author"],
    }


# ── Validation ────────────────────────────────────────────────────────────────


_SCHEMA_CACHE: dict[str, dict] = {}


def _load_schema(name: str) -> dict:
    if name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[name]
    path = SCHEMAS_DIR / f"{name}.schema.json"
    with open(path) as f:
        schema = json.load(f)
    _SCHEMA_CACHE[name] = schema
    return schema


class ValidationFailure(Exception):
    """Raised when JSON fails schema validation. .errors is a list of pretty diffs."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def _format_error(err: jsonschema.ValidationError) -> str:
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"  at {path}: {err.message}"


def _validate(name: str, data: Any) -> None:
    schema = _load_schema(name)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        raise ValidationFailure([_format_error(e) for e in errors])


def validate_book_extract(data: Any) -> None:
    """Raise ValidationFailure if data is not a conforming book extract."""
    _validate("book-extract", data)


def validate_ingredient(data: Any) -> None:
    """Raise ValidationFailure if data is not a conforming ingredient profile."""
    _validate("ingredient", data)


# ── Denormalized source_books[] ───────────────────────────────────────────────


def derive_source_books(book_claims: list[dict]) -> list[str]:
    """Compute the unique, sorted list of book_slugs from a claims array."""
    slugs = {c.get("book_slug") for c in book_claims if c.get("book_slug")}
    return sorted(slugs)


# ── Wiki data dir resolution ──────────────────────────────────────────────────


def wiki_data_dir() -> Path:
    """Resolve the wiki repo's data dir, in priority order:

    1. LONGEVITY_WIKI_DATA_DIR environment variable
    2. .longevity-skills.json `wiki_data_dir` key
    3. ./data (relative to CWD — legacy fallback)
    """
    env = os.environ.get("LONGEVITY_WIKI_DATA_DIR")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            if "wiki_data_dir" in cfg:
                return Path(os.path.expanduser(cfg["wiki_data_dir"])).resolve()
        except (json.JSONDecodeError, OSError):
            pass
    return Path("data").resolve()


# ── Invalid tray ──────────────────────────────────────────────────────────────


def tray_invalid(data: Any, error: str | Exception, label: str) -> Path:
    """Write rejected JSON + error message to data/.invalid/<label>-<timestamp>.json.

    Returns the path written. The label should be slug-safe (e.g. ingredient slug,
    chapter name). Caller is responsible for raising/exiting after this returns.
    """
    INVALID_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = slugify(label) or "unknown"
    path = INVALID_DIR / f"{safe_label}-{timestamp}.json"
    payload = {
        "error": str(error),
        "data": data,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


# ── CLI ───────────────────────────────────────────────────────────────────────


def _cmd_validate(args: argparse.Namespace) -> int:
    with open(args.file) as f:
        data = json.load(f)
    fn = {"book-extract": validate_book_extract, "ingredient": validate_ingredient}[args.kind]
    try:
        fn(data)
    except ValidationFailure as e:
        print(f"INVALID: {args.file}", file=sys.stderr)
        for err in e.errors:
            print(err, file=sys.stderr)
        return 1
    print(f"OK: {args.file}")
    return 0


def _cmd_validate_all(args: argparse.Namespace) -> int:
    root = Path(args.root)
    extract_files = list((root / "book-extracts").glob("**/chapter-*.json")) if (root / "book-extracts").exists() else []
    extract_files += list((root / "book-extracts").glob("**/ingredients-master.json")) if (root / "book-extracts").exists() else []
    ingredient_files = list((root / "ingredients").glob("*.json")) if (root / "ingredients").exists() else []

    failures = 0
    for f in extract_files:
        try:
            with open(f) as fh:
                validate_book_extract(json.load(fh))
            print(f"OK   {f}")
        except (ValidationFailure, json.JSONDecodeError) as e:
            print(f"FAIL {f}: {e}", file=sys.stderr)
            failures += 1
    for f in ingredient_files:
        try:
            with open(f) as fh:
                validate_ingredient(json.load(fh))
            print(f"OK   {f}")
        except (ValidationFailure, json.JSONDecodeError) as e:
            print(f"FAIL {f}: {e}", file=sys.stderr)
            failures += 1
    if failures:
        print(f"\n{failures} files failed validation.", file=sys.stderr)
        return 1
    print(f"\nAll {len(extract_files) + len(ingredient_files)} files valid.")
    return 0


def _cmd_slugify(args: argparse.Namespace) -> int:
    print(slugify(args.text))
    return 0


def _cmd_books(args: argparse.Namespace) -> int:
    books = list_books()
    if not books:
        print("No books found. Create data/book-raw/<slug>/_book.json.")
        return 0
    for b in books:
        print(f"{b['slug']:30}  {b['title']} ({b['author']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lib.py", description=__doc__.split("\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_validate = sub.add_parser("validate", help="Validate one JSON file")
    p_validate.add_argument("kind", choices=["book-extract", "ingredient"])
    p_validate.add_argument("file")
    p_validate.set_defaults(func=_cmd_validate)

    p_validate_all = sub.add_parser("validate-all", help="Validate every JSON under a data root")
    p_validate_all.add_argument("root", help="Path to a data/ dir (skills or wiki repo)")
    p_validate_all.set_defaults(func=_cmd_validate_all)

    p_slug = sub.add_parser("slugify", help="kebab-case a string")
    p_slug.add_argument("text")
    p_slug.set_defaults(func=_cmd_slugify)

    p_books = sub.add_parser("books", help="List books with manifests")
    p_books.set_defaults(func=_cmd_books)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
