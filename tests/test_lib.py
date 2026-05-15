"""Unit tests for scripts/lib.py.

Covers IRON-RULE regressions:
- Validator rejects the legacy singular `source_book` string shape.
- Canonical-shape book extracts pass validation.
"""

import json
from pathlib import Path

import pytest

from scripts import lib


# ── slugify ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("The Path to Longevity", "the-path-to-longevity"),
        ("Longo's Diet", "longo-s-diet"),
        ("Café Bistro", "caf-bistro"),
        ("  spaces  ", "spaces"),
        ("UPPER", "upper"),
        ("a", "a"),
        ("", ""),
    ],
)
def test_slugify(text, expected):
    assert lib.slugify(text) == expected


# ── derive_source_books ───────────────────────────────────────────────────────


def test_derive_source_books_sorts_and_dedups():
    claims = [
        {"book_slug": "longo"},
        {"book_slug": "fontana"},
        {"book_slug": "longo"},
        {"book_slug": "fontana"},
    ]
    assert lib.derive_source_books(claims) == ["fontana", "longo"]


def test_derive_source_books_empty():
    assert lib.derive_source_books([]) == []
    assert lib.derive_source_books([{"text": "x"}]) == []


# ── validate_book_extract ─────────────────────────────────────────────────────


def _valid_extract() -> dict:
    return {
        "book": "The Path to Longevity",
        "author": "Luigi Fontana",
        "book_slug": "the-path-to-longevity",
        "chapter": "Chapter 1",
        "page_range": "1-30",
        "ingredients": [
            {
                "name": "Walnuts",
                "slug": "walnuts",
                "claims": [
                    {
                        "text": "Walnuts lower LDL.",
                        "mechanism": "Omega-3 ALA reduces inflammation.",
                        "recommendation": "1 ounce daily",
                        "reference": "Ref 5 in book",
                        "confidence": "high",
                    }
                ],
            }
        ],
    }


def test_validate_book_extract_happy():
    lib.validate_book_extract(_valid_extract())


def test_validate_book_extract_missing_book_slug():
    data = _valid_extract()
    del data["book_slug"]
    with pytest.raises(lib.ValidationFailure):
        lib.validate_book_extract(data)


def test_validate_book_extract_legacy_claim_shape_fails():
    """Regression: a claim with legacy `claim` field instead of `text` must fail."""
    data = _valid_extract()
    data["ingredients"][0]["claims"][0] = {
        "claim": "Walnuts lower LDL.",  # legacy
        "study_ref": "Ref 5",  # legacy
        "mechanism": "x",
        "confidence": "high",
    }
    with pytest.raises(lib.ValidationFailure):
        lib.validate_book_extract(data)


# ── validate_ingredient ───────────────────────────────────────────────────────


def _valid_profile() -> dict:
    return {
        "name": "Walnuts",
        "slug": "walnuts",
        "category": "nut",
        "aliases": [],
        "source_books": ["fontana"],
        "book_claims": [
            {
                "text": "Walnuts lower LDL.",
                "mechanism": "ALA reduces inflammation.",
                "recommendation": "1 oz daily",
                "reference": "Ref 5",
                "confidence": "high",
                "book_slug": "fontana",
            }
        ],
        "research_status": "complete",
    }


def test_validate_ingredient_happy():
    lib.validate_ingredient(_valid_profile())


def test_validate_ingredient_rejects_legacy_source_book_string():
    """IRON-RULE regression: singular `source_book` string must be rejected."""
    data = _valid_profile()
    # Singular source_book (legacy): replace the required array shape with a string,
    # and drop the required array. Schema requires `source_books` (plural array).
    del data["source_books"]
    data["source_book"] = "The Longevity Diet"  # legacy singular
    with pytest.raises(lib.ValidationFailure):
        lib.validate_ingredient(data)


def test_validate_ingredient_rejects_missing_book_slug_on_claim():
    """Every claim must carry book_slug for provenance (Decision 1D)."""
    data = _valid_profile()
    del data["book_claims"][0]["book_slug"]
    with pytest.raises(lib.ValidationFailure):
        lib.validate_ingredient(data)


def test_validate_ingredient_recommendation_nullable():
    """Legacy profiles without recommendation should still validate."""
    data = _valid_profile()
    data["book_claims"][0]["recommendation"] = None
    lib.validate_ingredient(data)


def test_validate_ingredient_category_enum():
    data = _valid_profile()
    data["category"] = "not-a-real-category"
    with pytest.raises(lib.ValidationFailure):
        lib.validate_ingredient(data)


# ── tray_invalid ──────────────────────────────────────────────────────────────


def test_tray_invalid_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "INVALID_DIR", tmp_path / ".invalid")
    p = lib.tray_invalid({"foo": "bar"}, "test error", "walnuts")
    assert p.exists()
    payload = json.loads(p.read_text())
    assert payload["error"] == "test error"
    assert payload["data"] == {"foo": "bar"}


# ── wiki_data_dir ─────────────────────────────────────────────────────────────


def test_wiki_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LONGEVITY_WIKI_DATA_DIR", str(tmp_path))
    result = lib.wiki_data_dir()
    assert result == tmp_path.resolve()


# ── read_book_manifest ────────────────────────────────────────────────────────


def test_read_book_manifest_happy(tmp_path, monkeypatch):
    book_raw = tmp_path / "book-raw" / "test-book"
    book_raw.mkdir(parents=True)
    (book_raw / "_book.json").write_text(
        json.dumps({"slug": "test-book", "title": "Test", "author": "Tester"})
    )
    monkeypatch.setattr(lib, "BOOK_RAW_DIR", tmp_path / "book-raw")
    m = lib.read_book_manifest("test-book")
    assert m["slug"] == "test-book"
    assert m["title"] == "Test"


def test_read_book_manifest_slug_mismatch_raises(tmp_path, monkeypatch):
    book_raw = tmp_path / "book-raw" / "actual-slug"
    book_raw.mkdir(parents=True)
    (book_raw / "_book.json").write_text(
        json.dumps({"slug": "different-slug", "title": "Test", "author": "Tester"})
    )
    monkeypatch.setattr(lib, "BOOK_RAW_DIR", tmp_path / "book-raw")
    with pytest.raises(lib.ManifestError):
        lib.read_book_manifest("actual-slug")


def test_read_book_manifest_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "BOOK_RAW_DIR", tmp_path / "book-raw")
    with pytest.raises(lib.ManifestError):
        lib.read_book_manifest("nope")


# ── load_book_metadata_from_report ────────────────────────────────────────────


def test_load_book_metadata_from_report_happy(tmp_path):
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"book_slug": "x", "book_title": "X", "author": "Y", "new": []}))
    meta = lib.load_book_metadata_from_report(p)
    assert meta == {"book_slug": "x", "book_title": "X", "author": "Y"}


def test_load_book_metadata_from_report_missing_field(tmp_path):
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"new": []}))  # No book metadata
    with pytest.raises(ValueError):
        lib.load_book_metadata_from_report(p)
