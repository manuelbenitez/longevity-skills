#!/usr/bin/env python3
"""
Batch-enrich ingredient profiles using Claude haiku via the Anthropic API.

Usage:
    .venv/bin/python3 research-ingredient/enrich.py [ingredient-name ...]

Without arguments: reads the latest dedup report and processes all new ingredients.
With arguments: processes only the named ingredients.
"""

import json
import os
import re
import sys
import glob
from datetime import datetime

import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

MASTER_FILE   = "data/book-extracts/ingredients-master.json"
DEDUP_GLOB    = "data/dedup/*-dedup-report.json"
OUTPUT_DIR    = "data/ingredients"
BATCH_SIZE    = 20

NON_FOOD = {
    "igf-1", "igfbp1", "insulin", "stem cells", "mitochondria", "ketone bodies",
    "blood pressure", "blood glucose", "c-reactive protein", "abdominal fat",
    "glycerol", "cholesterol", "sugar", "saturated fats", "healthy fats",
    "calories", "protein", "desserts",
}

MODEL = os.environ.get("LONGEVITY_MODEL", "claude-haiku-4-5-20251001")

# ── Helpers ───────────────────────────────────────────────────────────────────

def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def load_master() -> dict:
    with open(MASTER_FILE) as f:
        return json.load(f)

def get_book_claims(name: str, slug: str, master: dict) -> list:
    slug_map = {i["slug"]: i for i in master["ingredients"]}
    name_map = {i["name"].lower(): i for i in master["ingredients"]}
    entry = slug_map.get(slug) or name_map.get(name.lower())
    if not entry:
        return []
    claims = []
    for c in entry.get("claims", []):
        claims.append({
            "claim":      c.get("text", ""),
            "mechanism":  c.get("mechanism", ""),
            "study_ref":  str(c.get("reference", "") or ""),
            "confidence": c.get("confidence", "medium"),
        })
    return claims

def already_written() -> set:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return {f[:-5] for f in os.listdir(OUTPUT_DIR) if f.endswith(".json")}

def build_queue(requested: list[str], master: dict) -> list[dict]:
    written = already_written()
    seen: set[str] = set()
    queue = []
    for name in requested:
        if name.lower() in NON_FOOD:
            continue
        slug = slugify(name)
        if slug in written:
            print(f"  skip {slug} (already exists)")
            continue
        if name in seen:
            continue
        seen.add(name)
        claims = get_book_claims(name, slug, master)
        queue.append({"name": name, "slug": slug, "claims": claims})
    return queue

def queue_from_dedup(master: dict) -> list[dict]:
    reports = sorted(glob.glob(DEDUP_GLOB))
    if not reports:
        print("No dedup report found. Run /dedup-ingredients first.")
        sys.exit(1)
    report = json.load(open(reports[-1]))
    names = [i["extracted_name"] for i in report["new"]]
    return build_queue(names, master)

# ── Enrichment prompt ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You enrich ingredient profiles for a longevity wiki grounded in peer-reviewed science.
For each ingredient you receive, return ONLY a JSON object with these fields:
  - supplementary_research: array of 2 objects {source, url, finding, agrees_with_book}
  - flavor_profile: {taste: [], aroma: [], texture: [], culinary_category: ""}
  - culinary_pairings: array of 3 objects {ingredient, tradition, source}
  - nutrient_highlights: array of 2-3 objects {compound, amount_per_100g, bioavailability_notes}
  - synergies: array of 2-3 objects {target_ingredient, type (synergy|antagonism|complement), description}
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
            lines.append(f"   Book claims:")
            for c in ing["claims"][:3]:  # cap at 3 to keep prompt small
                lines.append(f"   - {c['claim']} ({c['confidence']})")
        else:
            lines.append("   Book claims: none (new ingredient, use general knowledge)")
    return "\n".join(lines)

# ── API call ──────────────────────────────────────────────────────────────────

def enrich_batch(batch: list[dict], client: anthropic.Anthropic) -> list[dict]:
    prompt = make_user_prompt(batch)
    print(f"  → calling {MODEL} for {len(batch)} ingredients...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        enrichments = json.loads(raw)
        if not isinstance(enrichments, list):
            raise ValueError("Expected JSON array")
        return enrichments
    except Exception as e:
        print(f"  ✗ JSON parse failed: {e}")
        print(f"  Raw response (first 500 chars): {raw[:500]}")
        # return empty enrichments — profiles will be written as book-only
        return [{} for _ in batch]

# ── Write profile ─────────────────────────────────────────────────────────────

NOW = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def write_profile(ing: dict, enrichment: dict) -> str:
    profile = {
        "name":     ing["name"],
        "slug":     ing["slug"],
        "category": enrichment.get("category", "other"),
        "aliases":  [],
        "book_claims":           ing["claims"],
        "supplementary_research": enrichment.get("supplementary_research", []),
        "flavor_profile":         enrichment.get("flavor_profile", {}),
        "culinary_pairings":      enrichment.get("culinary_pairings", []),
        "nutrient_highlights":    enrichment.get("nutrient_highlights", []),
        "synergies":              enrichment.get("synergies", []),
        "last_updated":    NOW,
        "last_researched": NOW,
        "research_status": "complete" if enrichment else "book-only",
        "source_book":     "The Longevity Diet",
    }
    path = os.path.join(OUTPUT_DIR, f"{ing['slug']}.json")
    with open(path, "w") as f:
        json.dump(profile, f, indent=2)
    return path

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    master = load_master()
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    # build queue
    if sys.argv[1:]:
        queue = build_queue(sys.argv[1:], master)
    else:
        queue = queue_from_dedup(master)

    if not queue:
        print("Nothing to process.")
        return

    print(f"\nProcessing {len(queue)} ingredients in batches of {BATCH_SIZE} using {MODEL}")
    print(f"Output: {OUTPUT_DIR}/\n")

    written = []
    for start in range(0, len(queue), BATCH_SIZE):
        batch = queue[start:start + BATCH_SIZE]
        print(f"Batch {start//BATCH_SIZE + 1}: {', '.join(i['name'] for i in batch)}")
        enrichments = enrich_batch(batch, client)

        for ing, enrichment in zip(batch, enrichments):
            path = write_profile(ing, enrichment)
            written.append(path)
            print(f"  ✓ {ing['slug']}.json")

    print(f"\nDone. {len(written)} files written.")

    # token usage hint
    print(f"\nTip: set LONGEVITY_MODEL=claude-sonnet-4-6 for higher quality on complex ingredients.")

if __name__ == "__main__":
    main()
