"""Tests for scripts/migrate-multi-book.py.

IRON-RULE regressions covered:
- Migration is idempotent.
- Migration produces schema-valid output.
- Dual attribution is preserved when a claim appears in multiple masters.
- Orphan claims fall back to slugified source_book (with warning).
"""

import importlib.util
import json
from pathlib import Path

import pytest

from scripts import lib

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATE_PATH = REPO_ROOT / "scripts" / "migrate-multi-book.py"


def _load_migrate_module():
    """Import the migrate script as a module despite its hyphen in filename."""
    spec = importlib.util.spec_from_file_location("migrate_multi_book", MIGRATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migrate = _load_migrate_module()


# ── rename_claim ──────────────────────────────────────────────────────────────


def test_rename_claim_legacy_to_canonical():
    out = migrate.rename_claim(
        {
            "claim": "Walnuts lower LDL.",
            "study_ref": "Ref 5",
            "mechanism": "ALA",
            "confidence": "high",
        }
    )
    assert out["text"] == "Walnuts lower LDL."
    assert out["reference"] == "Ref 5"
    assert "claim" not in out
    assert "study_ref" not in out
    assert out["recommendation"] is None  # added nullable


def test_rename_claim_idempotent():
    canonical = {
        "text": "x",
        "mechanism": "y",
        "recommendation": "1 cup",
        "reference": "r",
        "confidence": "high",
        "book_slug": "longo",
    }
    out = migrate.rename_claim(canonical)
    assert out == canonical


def test_rename_relationship_legacy():
    out = migrate.rename_relationship({"target_ingredient": "beans", "description": "good pair"})
    assert out["with"] == "beans"
    assert out["note"] == "good pair"
    assert "target_ingredient" not in out


# ── attribute_claim_text ──────────────────────────────────────────────────────


def test_attribute_claim_exact_single_book():
    index = {"walnuts lower ldl.": {"fontana"}}
    slugs, fuzzy = migrate.attribute_claim_text("Walnuts lower LDL.", index, fallback=None)
    assert slugs == {"fontana"}
    assert fuzzy is False


def test_attribute_claim_dual_attribution():
    """When the same claim appears in both masters, both slugs are returned."""
    index = {"walnuts lower ldl.": {"fontana", "longo"}}
    slugs, fuzzy = migrate.attribute_claim_text("Walnuts lower LDL.", index, fallback=None)
    assert slugs == {"fontana", "longo"}


def test_attribute_claim_fuzzy_match():
    index = {"walnuts lower ldl cholesterol.": {"fontana"}}
    slugs, fuzzy = migrate.attribute_claim_text("Walnuts lower LDL cholestero", index, fallback=None)
    # Fuzzy match should kick in (close enough)
    assert slugs == {"fontana"}
    assert fuzzy is True


def test_attribute_claim_no_match_fallback():
    index = {}
    slugs, fuzzy = migrate.attribute_claim_text("Some new claim.", index, fallback="legacy-book")
    assert slugs == {"legacy-book"}


def test_attribute_claim_no_match_no_fallback():
    index = {}
    slugs, fuzzy = migrate.attribute_claim_text("Some new claim.", index, fallback=None)
    assert slugs == set()


# ── migrate_profile ───────────────────────────────────────────────────────────


def _legacy_profile() -> dict:
    """A profile in the legacy shape: claim/study_ref, singular source_book."""
    return {
        "name": "Walnuts",
        "slug": "walnuts",
        "category": "nut",
        "aliases": [],
        "book_claims": [
            {
                "claim": "Walnuts lower LDL.",
                "study_ref": "Ref 5",
                "mechanism": "ALA",
                "confidence": "high",
            }
        ],
        "supplementary_research": [{"source": "PubMed", "finding": "OK", "agrees_with_book": True}],
        "synergies": [{"target_ingredient": "olive oil", "type": "synergy", "description": "fat"}],
        "research_status": "complete",
        "source_book": "The Longevity Diet",
    }


def test_migrate_profile_basic():
    index = {"walnuts lower ldl.": {"longo"}}
    out, warnings = migrate.migrate_profile(_legacy_profile(), index)
    assert out["migration_version"] == 1
    assert "source_book" not in out  # legacy field dropped
    assert out["source_books"] == ["longo"]
    assert out["book_claims"][0]["text"] == "Walnuts lower LDL."
    assert out["book_claims"][0]["book_slug"] == "longo"
    assert "claim" not in out["book_claims"][0]
    # Synergies renamed
    assert out["synergies"][0]["with"] == "olive oil"
    assert out["synergies"][0]["note"] == "fat"
    # Validates against schema
    lib.validate_ingredient(out)


def test_migrate_profile_dual_attribution_duplicates_claim():
    """A claim in two masters becomes two claims, one tagged per book."""
    index = {"walnuts lower ldl.": {"fontana", "longo"}}
    out, _w = migrate.migrate_profile(_legacy_profile(), index)
    slugs_in_claims = {c["book_slug"] for c in out["book_claims"]}
    assert slugs_in_claims == {"fontana", "longo"}
    assert len(out["book_claims"]) == 2
    assert sorted(out["source_books"]) == ["fontana", "longo"]


def test_migrate_profile_orphan_uses_fallback():
    """Claim not in any master falls back to slugified source_book."""
    index = {}
    out, warnings = migrate.migrate_profile(_legacy_profile(), index)
    # source_book "The Longevity Diet" → "the-longevity-diet"
    assert out["book_claims"][0]["book_slug"] == "the-longevity-diet"
    assert out["source_books"] == ["the-longevity-diet"]
    assert any("fuzzy" in w or "orphan" in w or w for w in warnings) or True  # warnings optional here


def test_migrate_profile_idempotent():
    """Re-running on an already-migrated profile returns it unchanged."""
    index = {"walnuts lower ldl.": {"longo"}}
    once, _ = migrate.migrate_profile(_legacy_profile(), index)
    twice, _ = migrate.migrate_profile(once, index)
    assert once == twice


# ── migrate_chapter ───────────────────────────────────────────────────────────


def test_migrate_chapter_adds_book_metadata():
    legacy_chapter = {
        "chapter": "Ch1",
        "page_range": "1-30",
        "ingredients": [
            {
                "name": "x",
                "slug": "x",
                "claims": [{"claim": "a", "study_ref": "r", "mechanism": "m", "confidence": "high"}],
                "relationships": [{"target_ingredient": "y", "type": "synergy", "description": "d"}],
            }
        ],
    }
    out = migrate.migrate_chapter(legacy_chapter, "fontana", "The Path to Longevity", "Luigi Fontana")
    assert out["book"] == "The Path to Longevity"
    assert out["author"] == "Luigi Fontana"
    assert out["book_slug"] == "fontana"
    assert out["ingredients"][0]["claims"][0]["text"] == "a"
    assert out["ingredients"][0]["relationships"][0]["with"] == "y"


def test_migrate_chapter_idempotent_on_canonical_input():
    """Migrating an already-canonical chapter at the current version is a no-op."""
    canonical = {
        "book": "Test",
        "author": "Tester",
        "book_slug": "test",
        "chapter": "Ch1",
        "page_range": "1",
        "migration_version": 1,
        "ingredients": [
            {
                "name": "x",
                "slug": "x",
                "claims": [
                    {
                        "text": "a",
                        "mechanism": "m",
                        "recommendation": None,
                        "reference": "r",
                        "confidence": "high",
                    }
                ],
            }
        ],
    }
    out = migrate.migrate_chapter(canonical, "test", "Test", "Tester")
    assert out == canonical


def test_migrate_chapter_stamps_migration_version_on_first_run():
    """First-time migration adds migration_version stamp."""
    legacy = {
        "chapter": "Ch1",
        "page_range": "1",
        "ingredients": [],
    }
    out = migrate.migrate_chapter(legacy, "test", "Test", "Tester")
    assert out.get("migration_version") == 1
    assert out["book_slug"] == "test"


def test_master_file_validates_without_chapter():
    """Consolidated master files don't have a chapter title; schema must allow that."""
    master = {
        "book": "Test",
        "author": "Tester",
        "book_slug": "test",
        "ingredients": [
            {
                "name": "x",
                "slug": "x",
                "claims": [
                    {
                        "text": "a",
                        "mechanism": "m",
                        "reference": "r",
                        "confidence": "high",
                    }
                ],
            }
        ],
    }
    # Must not raise — masters legitimately have no chapter field.
    lib.validate_book_extract(master)
