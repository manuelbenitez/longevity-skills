# Changelog

All notable changes to longevity-skills.

## [0.2.0] - 2026-05-15

### Added
- Multi-book support across the entire pipeline. Add a third book without
  touching existing data — claims are tagged with `book_slug`, profiles
  aggregate from multiple sources, and `source_books[]` is recomputed on every
  write.
- `data/book-raw/<slug>/_book.json` manifest: user-provided slug, title, and
  author per book. The slug is the primary key downstream — never re-derived.
- Per-book subdirectories: `data/book-raw/<slug>/`, `data/book-extracts/<slug>/`,
  `data/dedup/<slug>-dedup-report.json`. Ingredient profiles stay flat — one
  profile may cite multiple books.
- Four-bucket dedup model: `new`, `new-to-book`, `existing-same-book`, `fuzzy`.
  The bucket drives enrich.py behavior — full enrich, append-only fast path,
  skip, or human review.
- Append-claims merge: when an ingredient is in the wiki but the current book
  isn't cited, claims are appended without a new LLM call and
  `supplementary_research` is preserved byte-identical.
- `scripts/lib.py` shared library: `slugify`, `validate_book_extract`,
  `validate_ingredient`, `read_book_manifest`, `list_books`,
  `load_book_metadata_from_report`, `derive_source_books`, `wiki_data_dir`,
  `tray_invalid`.
- `scripts/migrate-multi-book.py` one-shot migration: renames legacy field
  names (`claim`→`text`, `study_ref`→`reference`, etc.), re-attributes claims
  to the correct book by master-file lookup, preserves dual attribution when a
  claim appears in two masters, validates every output, supports `--dry-run`.
- JSON schema validation at write time. Invalid output goes to `data/.invalid/`
  with the field diff — no more silent drift.
- `tests/` directory with 47 pytest cases covering slugify, schema validation,
  migration logic, and enrich merge semantics. CI runs the suite on every push.
- `.github/workflows/test.yml` — pytest + validator on every PR.
- `data/non-food-terms.txt` — shared filter list, editable without code changes.
- `LONGEVITY_WIKI_DATA_DIR` env override and `wiki_data_dir` config key for
  explicit cross-repo path resolution.

### Changed
- Canonical claim shape is now `{text, mechanism, recommendation, reference,
  confidence, book_slug}`. The legacy field rename at `enrich.py:55-58`
  (`text→claim`, `reference→study_ref`) is gone — the contract is honest end
  to end.
- `book_claims[].recommendation` is nullable for legacy profiles without
  per-claim dosing.
- `relationships`/`synergies` use `with`/`note` field names (was
  `target_ingredient`/`description`).
- `ingredient.schema.json` adds required fields: `category` (enum), `aliases`,
  `source_books` (array of slugs, recomputed on every write).
- All seven SKILL.md descriptions: removed hardcoded book names. Skills now
  describe themselves as generic pipeline steps that take a `<book-slug>` arg.
- `examples/` regenerated using walnuts (appears in both books) to demonstrate
  dual-book provenance, per-claim `book_slug`, and the canonical shape.
- CLAUDE.md pipeline diagram redrawn for multi-book; README de-Fontana-ified.

### Fixed
- `research-ingredient/enrich.py:134` — `max_tokens` raised from 4096 to 16384.
  Earlier versions silently truncated batches of 20 around ingredient 7 and
  wrote downstream entries as `research_status=book-only`. This is the
  pre-existing bug that made "fast" enrichment quietly produce empty profiles.
- `enrich.py:49` — name lookup now normalizes via `slugify` on both sides, so
  "Beans / Legumes" correctly matches "beans-legumes" from the CLI.
- `enrich.py:89, 43` — file handle leaks (`json.load(open(...))`) replaced with
  `with` blocks.
- `enrich.py:157` — `datetime.utcnow()` (deprecated in Python 3.12+) replaced
  with `datetime.now(timezone.utc)`.
- `enrich.py` Anthropic 5xx/timeouts now retry once with a 5-second backoff
  before failing.
- Hardcoded `"source_book": "The Longevity Diet"` removed from `enrich.py:174`
  and `research-ingredient/SKILL.md:177`. Book metadata is now read from the
  dedup report header.

### Removed
- Singular `source_book` string from the ingredient schema. Replaced by
  per-claim `book_slug` + denormalized `source_books[]` array. The migration
  script handles existing profiles.
