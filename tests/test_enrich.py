"""Tests for research-ingredient/enrich.py merge logic.

IRON-RULE regressions covered:
- Canonical shape flows end-to-end (text/reference, not claim/study_ref).
- Second-book merge preserves first-book supplementary_research byte-identical.
- new bucket → fresh profile; new-to-book → append-claims; existing-same-book → skip.
- Per-ingredient validation: one bad output doesn't tray the whole batch.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from scripts import lib

REPO_ROOT = Path(__file__).resolve().parent.parent
ENRICH_PATH = REPO_ROOT / "research-ingredient" / "enrich.py"


def _load_enrich_module():
    """Import enrich.py despite the hyphen in its parent dir."""
    spec = importlib.util.spec_from_file_location("enrich", ENRICH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


enrich = _load_enrich_module()


# ── get_book_claims: canonical-shape end-to-end ────────────────────────────────


def test_get_book_claims_returns_canonical_text_not_claim():
    """IRON-RULE: enrich.py:55-58's legacy rename is GONE. text stays text."""
    master = {
        "ingredients": [
            {
                "name": "Walnuts",
                "slug": "walnuts",
                "claims": [
                    {
                        "text": "Walnuts lower LDL.",
                        "mechanism": "ALA",
                        "recommendation": "1 oz daily",
                        "reference": "Ref 5",
                        "confidence": "high",
                    }
                ],
            }
        ]
    }
    claims = enrich.get_book_claims("Walnuts", "walnuts", master, "longo")
    assert len(claims) == 1
    assert claims[0]["text"] == "Walnuts lower LDL."
    assert claims[0]["reference"] == "Ref 5"
    assert claims[0]["book_slug"] == "longo"
    # Legacy field names must NOT be present
    assert "claim" not in claims[0]
    assert "study_ref" not in claims[0]


def test_get_book_claims_name_normalization():
    """'Beans / Legumes' should match 'beans-legumes' via slugify on both sides."""
    master = {
        "ingredients": [
            {
                "name": "Beans / Legumes",
                "slug": "beans-legumes",
                "claims": [
                    {
                        "text": "Beans are great.",
                        "mechanism": "fiber",
                        "reference": "Ref 1",
                        "confidence": "high",
                    }
                ],
            }
        ]
    }
    claims = enrich.get_book_claims("Beans / Legumes", "beans-legumes", master, "fontana")
    assert len(claims) == 1


def test_get_book_claims_missing_returns_empty():
    claims = enrich.get_book_claims("Nope", "nope", {"ingredients": []}, "x")
    assert claims == []


# ── merge_or_skip: the three bucket actions ───────────────────────────────────


def _make_ing(slug: str = "walnuts", book_slug: str = "longo") -> dict:
    return {
        "name": "Walnuts",
        "slug": slug,
        "claims": [
            {
                "text": "Walnuts lower LDL.",
                "mechanism": "ALA",
                "recommendation": None,
                "reference": "Ref 5",
                "confidence": "high",
                "book_slug": book_slug,
            }
        ],
        "bucket": "new",
    }


def _make_enrichment() -> dict:
    return {
        "category": "nut",
        "supplementary_research": [{"source": "PubMed", "finding": "OK", "agrees_with_book": True}],
        "flavor_profile": {"taste": ["earthy"], "aroma": [], "texture": [], "culinary_category": "nut"},
        "culinary_pairings": [],
        "nutrient_highlights": [{"compound": "ALA"}],
        "synergies": [],
    }


def test_merge_or_skip_new_writes_fresh_profile(tmp_path):
    ing = _make_ing()
    action, path = enrich.merge_or_skip(ing, _make_enrichment(), "longo", tmp_path)
    assert action == "wrote-new"
    written = json.loads(path.read_text())
    assert written["source_books"] == ["longo"]
    assert written["book_claims"][0]["book_slug"] == "longo"
    # Validates against schema
    lib.validate_ingredient(written)


def test_merge_or_skip_existing_same_book_skips(tmp_path):
    """Profile already cites this book → no write."""
    existing = {
        "name": "Walnuts",
        "slug": "walnuts",
        "category": "nut",
        "aliases": [],
        "source_books": ["longo"],
        "book_claims": [
            {
                "text": "old claim",
                "mechanism": "m",
                "recommendation": None,
                "reference": "r",
                "confidence": "high",
                "book_slug": "longo",
            }
        ],
        "supplementary_research": [{"source": "X", "finding": "Y"}],
        "research_status": "complete",
    }
    target = tmp_path / "walnuts.json"
    target.write_text(json.dumps(existing))

    action, _ = enrich.merge_or_skip(_make_ing(), _make_enrichment(), "longo", tmp_path)
    assert action == "skipped-same-book"
    # File unchanged
    assert json.loads(target.read_text()) == existing


def test_merge_or_skip_new_book_appends_preserves_research(tmp_path):
    """IRON-RULE regression: second-book merge preserves supplementary_research byte-identical."""
    research = [{"source": "PubMed", "finding": "Important finding", "agrees_with_book": True}]
    existing = {
        "name": "Walnuts",
        "slug": "walnuts",
        "category": "nut",
        "aliases": [],
        "source_books": ["fontana"],
        "book_claims": [
            {
                "text": "Walnuts are heart-healthy.",
                "mechanism": "ALA",
                "recommendation": None,
                "reference": "Ref Fontana",
                "confidence": "high",
                "book_slug": "fontana",
            }
        ],
        "supplementary_research": research,
        "flavor_profile": {"culinary_category": "nut"},
        "research_status": "complete",
    }
    target = tmp_path / "walnuts.json"
    target.write_text(json.dumps(existing))

    # Now add a claim from longo
    ing = _make_ing(book_slug="longo")
    action, path = enrich.merge_or_skip(ing, {}, "longo", tmp_path)
    assert action == "appended-claims"
    written = json.loads(path.read_text())
    # supplementary_research preserved byte-identical
    assert written["supplementary_research"] == research
    # source_books has both
    assert written["source_books"] == ["fontana", "longo"]
    # book_claims has both
    assert len(written["book_claims"]) == 2
    book_slugs = {c["book_slug"] for c in written["book_claims"]}
    assert book_slugs == {"fontana", "longo"}
    # Schema-valid
    lib.validate_ingredient(written)


def test_merge_or_skip_invalid_enrichment_raises(tmp_path):
    """If enrichment doesn't produce a valid profile, raise ValidationFailure."""
    # Empty enrichment + claims without recommendation should still be valid
    # (recommendation is nullable). The truly invalid case: missing required fields.
    ing = _make_ing()
    # Mutate the ing claims to have an invalid confidence value
    ing["claims"][0]["confidence"] = "ultra-mega"
    with pytest.raises(lib.ValidationFailure):
        enrich.merge_or_skip(ing, _make_enrichment(), "longo", tmp_path)


# ── build_queue_from_dedup: four-bucket model ─────────────────────────────────


def test_build_queue_reads_new_and_new_to_book_buckets():
    """enrich.py must read BOTH the `new` and `new-to-book` buckets (Decision ARCH-2)."""
    master = {
        "ingredients": [
            {
                "name": "x",
                "slug": "x",
                "claims": [{"text": "a", "mechanism": "m", "reference": "r", "confidence": "high"}],
            },
            {
                "name": "y",
                "slug": "y",
                "claims": [{"text": "b", "mechanism": "m", "reference": "r", "confidence": "high"}],
            },
        ]
    }
    report = {
        "new": [{"extracted_name": "x", "slug": "x"}],
        "new-to-book": [{"extracted_name": "y", "slug": "y"}],
        "existing-same-book": [{"extracted_name": "z", "slug": "z"}],
        "fuzzy": [],
    }
    queue = enrich.build_queue_from_dedup(report, master, "longo")
    slugs = {q["slug"] for q in queue}
    assert slugs == {"x", "y"}  # z is skipped (existing-same-book)
    buckets = {q["slug"]: q["bucket"] for q in queue}
    assert buckets["x"] == "new"
    assert buckets["y"] == "new-to-book"


def test_build_queue_filters_non_food(monkeypatch):
    monkeypatch.setattr(enrich, "NON_FOOD", {"protein"})
    master = {"ingredients": []}
    report = {"new": [{"extracted_name": "Protein"}], "new-to-book": []}
    queue = enrich.build_queue_from_dedup(report, master, "longo")
    assert queue == []
