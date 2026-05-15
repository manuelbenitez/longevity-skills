# TODOS

Deferred work captured from /plan-eng-review on 2026-05-14.

## Eng — Scripted LLM eval suite

**What:** `scripts/eval.py` automates the manual LLM eval (re-run `extract-book-knowledge` on chapter-04 of each book post-change; validator must pass). Loops over `data/book-raw/*/_book.json`, runs the extraction prompt against a fixed chapter, validates output, reports pass/fail.

**Why:** Decision T-2 in the 2026-05-14 eng review chose manual eval — human discipline catches prompt drift when a new book is added. Automating it would catch drift on every PR (or on a scheduled run), not just at the next book-add. Useful if the third book + future books keep arriving.

**Pros:** Reproducible eval; could gate CI; catches prompt regressions early. Already documented procedure can become a script literally translating the same checklist.

**Cons:** ~$0.50 in API tokens per run; another ~100 LOC of script + maintenance; runs in CI mean a real Anthropic API key in GitHub secrets.

**Context:** The manual procedure is in CLAUDE.md (added in PR1 of the multi-book work). The script is a straightforward port: read book manifest → call extract prompt → run `lib.validate_book_extract` → emit pass/fail. The interesting design question is whether to fold it into the existing `tests/` directory under `tests/eval/` (marked `@pytest.mark.eval`, skipped without `--eval` flag) or to keep it as a separate top-level script. Recommend `tests/eval/test_extract_prompt.py` so it lives alongside other tests.

**Depends on / blocked by:** Plan-eng-review PR1 must merge first (validator + book manifests must exist). Not urgent unless a third book is added and prompt drift surfaces during that work.
