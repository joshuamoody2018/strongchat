# Learnings — hyde-retrieval-pipeline

Conventions, patterns, and successful approaches discovered during work on this plan.

_Auto-scaffolded by /start-work. Append new entries below - never overwrite._

---

## [2026-07-28T13:42:00Z] Task: 13 — Download and validate KJV + WEB corpus

- Source schema: https://github.com/midvash/bible-data/blob/main/SCHEMA.md — actual `<slug>.json` keys are `version`, `name`, `language`, `license`, `books` (list), `book` (OSIS), `chapters`, `verses`, `number`, `text`. KJV has 31,102 verses; WEB has 31,098 verses.
- Downloaded files are ~6 MB each (JSON) and take under a minute on this host; `requests.get(..., timeout=120, stream=True)` works fine.
- Override flags (`--kjv-file`, `--web-file`) let failure-QA run without re-downloading and without touching the real `data/bible/` files.
- Validation rejects empty verse texts, non-66 book counts, and verse totals outside [30,000, 32,000]; a truncated fixture (39 books) exits 3 with a clear message.
- Manifest keys are sorted for stable diffs; `downloaded_at` is ISO 8601 with timezone.
- Full evidence in `.omo/evidence/task-13-hyde-retrieval-pipeline.txt`.

## [2026-07-28T03:06:53Z] Task: 2
- Appended `.venv/`, `data/bible/`, `data/chroma/` to `.git/info/exclude` (not `.gitignore`) to avoid colliding with user's pending `.gitignore` rework shown as ` M .gitignore` in porcelain.
- Used `grep -qxF` for exact-line presence check before append, then a second pass on the same loop, to guarantee each entry appears exactly once. Pattern is idempotent and safe to re-run.
- `git check-ignore -v` confirmed each path resolves through `.git/info/exclude` (lines 7/8/9), not the repo-level `.gitignore` — verification of "the right source" matters when multiple exclude layers exist.
- Failure QA: `touch data/{bible,chroma}/.probe` then `git status --porcelain | grep -E 'data/bible|data/chroma|\.venv'` returned empty, proving patterns silence *new* files inside the dirs (not just the dirs themselves). Probes were removed; the dirs remain empty.
- Side note: `data/chat_database.db` was already in `data/` before this task. `*.db` (already in `.gitignore:38-41`) still covers it; no extra entry needed.
- `data/bible/` and `data/chroma/` were created with `mkdir -p`. Pre-existing `data/` dir held `chat_database.db` — no destruction.
- Full evidence (commands + exit codes) in `.omo/evidence/task-2-hyde-retrieval-pipeline.txt`.

## [2026-07-28T03:10:44Z] Task: 1 — Create project venv and pinned requirements.txt

### Environment

- Host: Ubuntu 24.04 (Linux 6.8.0-124-generic), Python 3.12.3 at /usr/bin/python3
- pip bootstrap: 26.1.2 installed into venv via get-pip.py from bootstrap.pypa.io
- Repo state at start: dirty (M .gitignore, M README.md; ?? .omo/ .opencode/ opencode.json) — left untouched per MUST NOT DO

### What worked

- `python3 -m venv .venv` FAILED on this host: `ensurepip` not available because `python3.12-venv` is NOT installed (dpkg confirms `un` status).
- `sudo apt install -y python3.12-venv` FAILED non-interactively: user is in the `sudo` group but `sudo -n` reports "a password is required"; this agent has no TTY to prompt. Cannot escalate to root in this session.
- Workaround used: `python3 -m venv --without-pip .venv` to create the directory layout, then bootstrapped pip into the venv with `.venv/bin/python /tmp/get-pip.py` (fetched from https://bootstrap.pypa.io/get-pip.py). System Python was NOT touched — PEP 668 / `--break-system-packages` not used.
- `.venv/bin/pip install -r requirements.txt` then succeeded; `pip check` reports no broken requirements.

### Resolved versions (all within the requested ranges)

- aiohttp==3.14.3 (range >=3.9,<4)
- jsonschema==4.26.0 (range >=4.10,<5)
- requests==2.34.2 (range >=2.31,<3)
- python-dotenv==1.2.2 (range >=1.0,<2)
- chromadb==1.5.9 (range >=1.0,<2)

### Notes for downstream tasks

- `chromadb==1.5.9` pulls a large transitive tree: pydantic 2.13.4, onnxruntime 1.28.0, numpy 2.5.1, kubernetes 36.0.3, grpcio 1.83.0, huggingface_hub 1.25.1, uvicorn 0.51.0, plus OpenTelemetry stack. `.venv/` is ~426 MB and contains 5244 .pyc files. Expect a cold install of a few minutes on this host.
- `requests==2.34.2` resolves to the new 2.34.x line (urllib3==2.7.0, charset-normalizer==3.4.9). If the LLM framework needs to pin an older requests (e.g. for legacy retry-adapter code), tighten the floor in a follow-up.
- `jsonschema==4.26.0` requires `referencing` + `rpds-py` for the new `$id`/2020-12-dialect resolution; these come along automatically.
- `aiohttp==3.14.3` requires `aiohappyeyeballs` and `propcache` (the 3.13+ baseline).

### Footnote for the operator

If sudo becomes available, the canonical sequence would be `sudo apt install -y python3.12-venv && python3 -m venv .venv && .venv/bin/pip install -U pip && .venv/bin/pip install -r requirements.txt`. The get-pip.py route above is the working equivalent when sudo is not available and PEP 668 forbids system pip.

## [2026-07-28T03:50:00Z] Task: CHECKPOINT (orchestrator)
- Execution paused by user at 5/24 todos (1-5 complete, verified, committed: 7a96d38, a434510, 54cab26, a0b6be3; todo 2 no-commit by design).
- Todo 6 (cache injection + FK pragma + migration) was dispatched once and aborted pre-work. Stalled session `ses_0592d876cffelbhH3TTwhp06ML` made zero file changes; safe to resume via task_id or discard for a fresh dispatch.
- Resume protocol for next session: `/start-work hyde-retrieval-pipeline` auto-continues from first unchecked todo. Full prompt content for todo 6 is in the plan file. After 6: todo 7 (BaseService), then Wave 2 (8-12) and Wave 3 (13-15) can fan out in parallel.
- Reminder for resumer: .venv/bin/python only; basedpyright unavailable (py_compile fallback); never stage .pyc/.env/data/README/.gitignore; every OpenRouter call gets a messages row.

## [2026-07-28T03:55:00Z] Task: CHECKPOINT-2 (orchestrator)
- Correction to the earlier checkpoint note: the stalled todo-6 session DID write one file — `src/config/cache.py` now carries the todo-6(a) edit (db_path param on `__new__`/`__init__`, `_db_path` honored in `_initialize_cache`, `reset()` classmethod). Orchestrator read and approved the shape; it is UNCOMMITTED and UNTESTED in the working tree.
- Resumer: do NOT rewrite cache.py from scratch — verify it (py_compile + run scripts/test_database_queries.py + a two-line cache smoke against the live DB), then implement 6(b) PRAGMA in database.py and 6(c) migrate_pipeline_message_types.py + test_migration.py, run the migration twice on the live DB (backup first), and commit all four paths together per the plan.

## [2026-07-28T03:32:40Z] Task: 4 — Fix ref_message_types JOINs and remove dead code

### Pre-flight

- Verified the orchestrator's claim before touching anything: re-read `src/services/sqlite/database.py` and confirmed lines 71, 91, 137, 176, 186 already matched the description and that `create_intent` / `get_intents_for_message` are absent. `git status --porcelain` confirmed the four expected worktree entries (M database.py, D enums.py, D test_main.py, M .pyc) plus the user's M .gitignore / M README.md and the untracked .omo/ .opencode/ opencode.json — all left alone per MUST NOT DO.

### Test fixture pattern

- `tempfile.TemporaryDirectory()` in `setUp` + `cleanup()` in `tearDown` makes the test self-cleaning. Second consecutive run of the script (`scripts/test_database_queries.py`) exits 0 with no manual cleanup, proving no state leaks across runs.
- Schema is applied via a raw `sqlite3.connect(...).executescript(SCHEMA_SQL)` BEFORE `ChatDatabase(db_path)` opens the file. The class's `__init__` calls `sqlite3.connect(db_path)` which will happily open an empty file and only fail at first query time, so the bootstrap-with-schema step matters.
- Foreign keys are NOT enabled in the fixture (todo 6 owns that). The fixture inserts only well-formed rows so the lack of `PRAGMA foreign_keys = ON` does not mask a bug here — it is documented in the test file's docstring for the next agent.

### Staging discipline

- `git add -- <four-paths>` (note the `--`) is the only safe way to add exactly the named paths. `git add src/services/sqlite/database.py` works here only because none of the other unstaged files in the same directory (the regenerated `.pyc`) happen to be a valid add-target; the `--` makes the intent explicit and survives any future reordering of the working tree.
- Pre-stage porcelain + post-stage porcelain diff confirmed: the four paths flipped from ` M / D / ??` to `M / D / A / D`, and nothing else moved into the staged set. The user's M .gitignore / M README.md, the regenerated .pyc, .omo/ .opencode/ opencode.json, and `scripts/check_embeddings_api.py` (todo 3) all stayed unstaged.

### LSP fallback

- `basedpyright` is not installed in this env and the user previously declined the install. Used `python -m py_compile` on both changed files as a syntax-only substitute. Behavioural coverage is supplied by the four unittest passes — those import `ChatDatabase` and exercise the exact queries under test, which is stronger than what LSP would catch.

### Commit

- `a43451056643b105bfee4210ddc0b5912d84ec80` on `dev`. Message: `Fix ref_message_types JOINs and remove dead code`. Style is freeform sentence-case imperative (matches 7a96d38, the immediately preceding commit). `git show --stat HEAD` confirms 4 files changed, 178 insertions(+), 311 deletions(-): 1 new test file, 1 modified database.py, 2 deletions.
- Full evidence with command outputs and exit codes in `.omo/evidence/task-4-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T03:32:42Z] Task: 3 — Verify OpenRouter /embeddings endpoint

### Endpoint contract (live observed)
- URL: `https://openrouter.ai/api/v1/embeddings` (note the `/api/v1` prefix; the wrapper's `base_url` already includes this — good)
- Model: `openai/text-embedding-3-small` returns 1536-dim vectors by default (no `dimensions` override sent)
- Response shape: `{"data": [{"embedding": [...], "index": 0, "object": "embedding"}, {"embedding": [...], "index": 1, ...}], "model": "text-embedding-3-small", "object": "list", "usage": {"prompt_tokens": 26, "total_tokens": 26, "is_byok": false, "cost": 5.2e-07, "cost_details": {...}}}`
- Quirks: `usage` IS present on this endpoint (unlike the chat completions endpoint I've seen) and includes a `cost` field in USD. Useful for cost-tracking later.
- Latency: ~545–1725 ms for 2 short Bible verses on a cold path; one warm run was 545 ms, so budget 1–2 s for cold. Two strings totaling 26 tokens is essentially free (~$5e-7).

### Failure-QA gotcha
- The repo's `.env` contains `OPENROUTER_API_KEY`, so the naive `load_dotenv()` + `os.getenv("OPENROUTER_API_KEY")` pattern defeats the `env -u OPENROUTER_API_KEY` failure-QA: load_dotenv re-populates the var from disk and the script never sees the missing-key case.
- Fix used: snapshot `"OPENROUTER_API_KEY" in os.environ` BEFORE `load_dotenv()`, and require the key to be in the calling environment, not just the on-disk .env. Other .env entries (MODEL_SLUG_INTENTS, OPENCODE_GO_API_KEY) still get loaded.
- This is a defensible security stance (secrets should come from the shell, not a file that may be checked in) and the only way to satisfy both "load .env via load_dotenv" and "env -u must produce 'key not configured'".
- Pattern is worth reusing for any future smoke check that needs the same env -u drill.

### Wrapper integration note
- `src/services/llm/wrapper.py:45-50` sets the same headers (Authorization, Content-Type, HTTP-Referer=http://localhost:8000, X-Title=StrongChat) and uses `base_url="https://openrouter.ai/api/v1"`. The embeddings URL is just `base_url + "/embeddings"`. The future HyDE embedding client can either subclass the wrapper or reuse its `_setup_api_config` directly.
- No retry logic in the smoke script (single shot, fail fast). The wrapper's retry/backoff (1s/2s/4s capped at 30s) is what production should rely on, not this script.

### Evidence
- Both runs (acceptance + env -u failure) captured in `.omo/evidence/task-3-hyde-retrieval-pipeline.txt` with stdout, stderr, and exit codes. No API key material in the file.

---

## [2026-07-28T03:37:27Z] Task: 5 — Align database setup scripts with ref_message_types schema

### Session note
- Parent session restarted mid-task; state check (`git diff --stat` + `ls .omo/evidence/` + `git log`) showed nothing done, so the full task was executed fresh in the resumed session. Read-state does NOT survive a restart: the Write tool rejected overwrites until both target files were re-Read in the new session.

### Final row shapes (fixture-verified)
- `intent_classification`: kept the inline SIMPLE request_schema (intent enum greeting/question/statement/command/goodbye/help + confidence) — main.py depends on that exact shape, do NOT "upgrade" it to `config.schemas.INTENT_CLASSIFICATION_SCHEMA` (that config schema is the newer multi-intent shape and is a different contract). `prompt_template` = `config.prompts.INTENT_CLASSIFICATION_PROMPT` (contains `{{`/`}}` escaped braces for .format; stored raw, inserts fine).
- `intent_disambiguation`: `request_schema` = `json.dumps(config.schemas.INTENT_DISAMBIGUATION_SCHEMA)`, `prompt_template` = `config.prompts.INTENT_DISAMBIGUATION_PROMPT`. temperature 0.2 / max_tokens 500 preserved from the old inline row.
- INSERT column list is 11 wide (…, description, prompt_template) matching live column order; INSERT OR REPLACE keeps it idempotent (re-run exits 0, COUNT stays 2).

### argparse additions
- Both scripts: `argparse.ArgumentParser` + `--db-path`, default `data/chat_database.db`, parsed in `__main__` and passed into the module function (which already took `db_path` as its first parameter — no signature change needed).

### Gotchas
- `create_new_database.py` also had a `DROP TABLE IF EXISTS intents` line to remove (not just the DDL — there was no intents DDL, only the DROP). The `messages` table FK had to be repointed `message_types` → `ref_message_types`. Removing the seed block made `import json` unused; removed it (`datetime` was already unused pre-change — left untouched as out of scope).
- Live `ref_message_types` DDL has `prompt_template TEXT` as column 11 after `description` (added via ALTER at some point, hence the odd `, prompt_template TEXT);` formatting in `.schema`). The create script emits it as a normal column in the canonical position — round-trips cleanly.
- `git status --cached` does NOT exist on this host's old git; use `git diff --cached --stat` to verify the staged set.
- `python -m py_compile` on a tracked script regenerates its tracked `__pycache__/*.pyc` and dirties the worktree — restore with `git checkout -- <pyc>` before staging (or accept the noise). basedpyright LSP still not installed (declined); py_compile + end-to-end fixture run was the substitute.
- Fixture used mktemp dir `/tmp/tmp.wsybP0xJtN`, removed after. Live DB `SELECT COUNT(*) FROM ref_message_types` = 2 verified before and after; neither script ever ran without `--db-path` pointed at the fixture.

### Commit
- `a0b6be3` on `dev`. Message: `Align database setup scripts with ref_message_types schema`. Staged exactly the two scripts via explicit paths (`git diff --cached --stat` confirmed 2 files, 67+/149−). Full evidence in `.omo/evidence/task-5-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T13:00:00Z] Task: 7 — BaseService shared foundation

- Added `src/services/base.py` as a thin wrapper around `LLMWrapper`: it owns one wrapper instance, exposes `self.db` and `self.cache` as aliases to the wrapper's attributes (no new connections), and provides `record_message` + `parse_message` helpers.
- `record_message` passes arguments by keyword to `ChatDatabase.create_message_with_type`; positional order differs from the database method because the service API orders arguments semantically `(message_type_slug, unique_prompt, session_uuid)`.
- `parse_message` fetches `request_schema` from `GlobalReferenceCache` and delegates to `AIMessage.get_parsed_response(schema)` — the schema is already a parsed dict in the cache, so no extra JSON parse is needed.
- Verified with `python -m py_compile` (basedpyright unavailable), the required happy-path instantiation command, a functional smoke for record+parse, and a failure-QA command confirming `/nonexistent/x.db` raises `sqlite3.OperationalError`.
- Full evidence in `.omo/evidence/task-7-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T17:00:00Z] Task: 14 — Add batched OpenRouter EmbeddingService

- `EmbeddingService(BaseService)` lives in `src/services/embeddings/service.py`; `__init__(db_path, embed_fn=None)` calls `super().__init__` to inherit the shared wrapper/cache/DB and reads the `embedding_generation` ref row for `model_slug` and `max_retries`.
- `embed_texts` chunks `[texts[i:i + chunk_size] ...]`, runs each chunk through the injected function or the live OpenRouter `/v1/embeddings` endpoint, and flattens results preserving input order. Retry/backoff mirrors `LLMWrapper`: transient `APITimeoutError`/`APIConnectionError` retry with `1.0 * (2 ** attempt)` capped at 30 s; other exceptions propagate immediately.
- Recording is one `embedding_generation` message per `embed_texts` call, only when `record=True` and `session_uuid` is set. `unique_prompt` is `json.dumps({"texts": texts})[:4000]`; `raw_response` is a summary `{"model": ..., "dimension": 1536, "count": N}` — never raw vectors. The model slug contains the substring "embedding", so the test asserts the absence of the JSON key `"embedding"`, not the bare substring.
- Offline tests use a fixture DB with a seeded `embedding_generation` row and `GlobalReferenceCache.reset(fixture_db)`. A dummy `OPENROUTER_API_KEY` is set before import because `LLMWrapper.__init__` validates the key, even though the injected `embed_fn` bypasses the live API.
- Evidence captured in `.omo/evidence/task-14-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T19:15:00Z] Task: 12 — Add HydeService with asyncio parallel generation

- `HydeService.generate_for_intents` uses `asyncio.gather(..., return_exceptions=True)` to run one `hyde_generation` call per intent in parallel; per-intent failures are caught and returned as `{'intent_id', 'hyde_document': None, 'error': str(e)}`, while the wrapper already persists the underlying error row.
- The JSON prompt sent to HyDE contains only the five allowed intent fields (`intent_id`, `interpretation`, `keywords_explicit`, `keywords_inferred`, `themes`) — the original user query is never included.
- A single shared `LLMWrapper`/SQLite connection is safe under `asyncio.gather` in this codebase because the event loop is single-threaded and serializes all DB writes; a comment in the service documents this.
- If every intent fails, `LLMError` is raised and carries the error entries on an attached `results` attribute so tests (and future callers) can inspect them without parsing a string.
- Live test on "what does the Bible say about anxiety" produced 3 intents and 3 successful HyDE documents (each ≥ 50 chars), with exactly 3 `hyde_generation` message rows for the session.
- Offline mocked tests pass with `OPENROUTER_API_KEY` unset: one success + one `ValueError` returns a mixed list, and all-fail raises `LLMError`.
- Full evidence in `.omo/evidence/task-12-hyde-retrieval-pipeline.txt`.

## [2026-07-28T18:30:00Z] Task: 15 — Add Chroma VerseStore and corpus ingest pipeline

- `VerseStore` wraps `chromadb.PersistentClient(path='data/chroma')` with `get_or_create_collection(..., metadata={"hnsw:space": "cosine"})` and an `upsert_verses` method that uses `chromadb.utils.batch_utils.create_batches` + `collection.upsert` per batch. `collection.add` is never used, so re-runs are idempotent.
- `scripts/ingest_corpus.py` flattens each translation to `ids` (`{SLUG}-{OSIS}-{chapter}-{verse}`), `documents` (verse text), and `metadatas` (`book`, `osis`, `chapter`, `verse`, `translation`), then embeds in 256-verse chunks via `EmbeddingService.embed_texts(record=False, chunk_size=256)` — roughly 122 OpenRouter calls per translation. No per-chunk `embedding_generation` rows are recorded.
- Progress prints every 10 batches (`batch 10/122`, etc.). After the collection count matches `manifest[slug]['verses']`, exactly one `corpus_ingest` message is recorded with `unique_prompt = {"translation", "verses", "collection"}` and `raw_response = {"status": "ok", "dimension": 1536}`.
- CLI flags: `--translation kjv|web` for single-translation runs; `--max-batches N` to stop after N chunks for failure/resume QA. A `--max-batches 1` run left 256 KJV verses in the collection and wrote zero `corpus_ingest` rows; the next full run completed the collection.
- Semantic check embeds "love your enemies" and queries `kjv_verses` top-5; hits included Luke 6:27, Matt 5:44, and Luke 6:35, so the assertion passed.
- Live ingest timing: ~10 minutes per full run for one translation on this host, so plan ~20 minutes for KJV + WEB together. Re-runs overwrite the same IDs and keep counts stable.
- Full evidence in `.omo/evidence/task-15-hyde-retrieval-pipeline.txt`.

## [2026-07-28T16:15:00Z] Task: 8 — Add refined intent generation schema, prompt, and message type

### Schema/prompt discipline
- The new `INTENT_GENERATION_SCHEMA` is deliberately distinct from `INTENT_CLASSIFICATION_SCHEMA` and `INTENT_DISAMBIGUATION_SCHEMA`; it adds `keywords_explicit` (verbatim from query), `keywords_inferred` (not in query), and a constrained `themes` array (1–3 items), plus a 1–5 `intents` range.
- The prompt template contains exactly one unescaped `{query}` placeholder. All JSON-example braces are doubled (`{{`/`}}`) so `.format(query=...)` succeeds and still emits valid-looking JSON braces.
- Because `INTENT_CLASSIFICATION_PROMPT` re-uses `{query}` in its inline example, it is fine for its own use-case but the refined generation prompt follows the stricter single-placeholder rule.

### Migration pattern
- `migrate_pipeline_message_types.py` keeps its base-row `INSERT_SQL` (literal `{}` for settings, `NULL` for prompt_template) untouched and adds a separate `INTENT_GENERATION_SQL` with all 11 columns bound to parameters. This preserves the exact byte shape of the existing 5 rows while cleanly upserting the new row.
- The new row imports `config.INTENT_GENERATION_SCHEMA` and `config.INTENT_GENERATION_PROMPT`, serializing the schema with `json.dumps`; additional_model_settings is stored as its own compact JSON string `'{"max_tokens": 800}'`.

### Verification
- `scripts/test_intent_schema.py` uses the existing unittest `TextTestRunner` style with path-bootstrap and `sys.exit(0|1)`.
- Live DB now shows `intent_generation` active with `openai/gpt-4.1-mini`, `temperature=0.2`, `additional_model_settings={"max_tokens": 800}`, and a non-null `prompt_template`.
- `intent_classification` remains active; no existing service files were touched.
- `scripts/test_migration.py` had to be updated to expect 8 rows (from 7) and a new `test_intent_generation_row_values` case was added to lock the new row's shape. The existing test is a regression guard for the migration, so it must stay in sync with the migration script.

---

## [2026-07-28T12:49:18Z] Task: 6 — Pipeline message-type migration, FK enforcement, cache injection

### Session note
- Session interrupted after the cache.py edit landed; resumed with the edit intact in the worktree. Read-state does not survive restarts — re-Read files before Write/Edit in the new session (same lesson as task 5).

### Final ref_message_types row listing (live, post-migration)
- `corpus_ingest`(1), `embedding_generation`(1), `error`(1), `human_input`(1), `intent_classification`(1), `intent_disambiguation`(0), `llm_response`(1) — 7 rows total, stable across two live runs (idempotent).
- All 5 new rows: `max_retries=3`, `is_active=1`, `additional_model_settings='{}'`, `prompt_template=NULL`, `temperature=0.0`; request schemas stored as the exact JSON strings from the spec (literal strings, NOT json.dumps of dicts — avoids `", "`/`": "` spacing drift from the specified byte shape).

### FK proof
- `PRAGMA foreign_keys = ON` now runs in `ChatDatabase.__init__` immediately after `sqlite3.connect` (per-connection in SQLite — every new connection needs it).
- Live probe: `sqlite3 data/chat_database.db "PRAGMA foreign_keys=ON; INSERT INTO messages ... 'bogus_slug' ..."` → `FOREIGN KEY constraint failed`, sqlite3 CLI exit 19, zero rows landed. Positive path (`human_input` insert) proven in test_migration.py against a temp copy via ChatDatabase.
- Orphan message rows (5 `human_input` + 1 `error`) are now FK-satisfied going forward because their slugs have ref rows; left untouched (no backfill, accepted).

### Gotchas
- `GlobalReferenceCache.__new__` had to accept `db_path` too (ignored) — Python passes constructor args to both `__new__` and `__init__`, so `GlobalReferenceCache(path)` with the old `def __new__(cls):` signature raises TypeError.
- `sqlite3.Connection.backup(dest)` overwrites an existing backup file silently — the required second live run replaced the backup with the post-first-run state. Backup is therefore a pre-SECOND-run snapshot (53248 bytes = live size). If a true pre-first-run backup is ever wanted, take it before run 1.
- `INSERT OR REPLACE` = delete+insert; safe here only because the migration connection does not enable FK pragma (a DELETE of `human_input`/`error` ref rows would otherwise trip the messages FK). Do not add `PRAGMA foreign_keys=ON` to the migration script.
- Tracked `src/services/sqlite/__pycache__/database.cpython-312.pyc` flapped again on every python run — restored via `git checkout --` before staging; never staged.
- `unittest.makeSuite` (used in test_database_queries.py) is deprecated in 3.12 — new test_migration.py uses `TestLoader().loadTestsFromTestCase` instead; same scripts/ unittest style otherwise.

### Verification
- `.venv/bin/python scripts/test_migration.py`: 6/6 OK, exit 0 (temp COPY only; backup-written, flags, field values, second-run idempotency, FK bogus-slug IntegrityError, human_input success).
- `scripts/test_database_queries.py`: 4/4 OK, exit 0 — run both BEFORE and AFTER the FK-pragma edit (fixture inserts well-formed rows, pragma doesn't disturb it).
- Live migration run TWICE, both exit 0; acceptance query shows the 7 rows above; `data/chat_database.db.pre-pipeline.bak` exists (53248 bytes).
- Full evidence with outputs + exit codes in `.omo/evidence/task-6-hyde-retrieval-pipeline.txt`.

## [2026-07-28T13:55:00Z] Task: 9 — Add IntentService with offline unit test

- `IntentService.generate_intents` is a thin async wrapper: `await self.llm.call_api('intent_generation', query, session_uuid)` → `parse_message` → return `{message_uuid, query_analysis, intents, recommended_search_approach}`.
- `src/services/intent/__init__.py` exports `IntentService` and sets `__all__` to match the package pattern.
- Offline testing: `unittest.mock.patch.object(self.service.llm, 'call_api', new_callable=AsyncMock)` returns a manually constructed `AIMessage` with `raw_response` set to canned JSON; no network calls and no real API key. A dummy `OPENROUTER_API_KEY` is set in `setUp` solely so `LLMWrapper.__init__` succeeds.
- `GlobalReferenceCache.reset('data/chat_database.db')` ensures the singleton cache points at the live DB schema for the test process, so `parse_message` can validate against the cached `intent_generation` schema.
- Two test cases: valid 2-intent response returns the exact structured keys; invalid response (missing required `themes`) raises `ValueError`. Both assert the mock was called with `('intent_generation', query, session_uuid)`.
- Full evidence in `.omo/evidence/task-9-hyde-retrieval-pipeline.txt`.

## [2026-07-28T17:00:00Z] Task: 11 — Add HyDE generation schema, prompt, and message type

- `HYDE_GENERATION_SCHEMA` is a single-property schema: `hyde_document` string with `minLength: 50`, title `HydeGenerationResponse`.
- `HYDE_GENERATION_PROMPT` contains exactly one unescaped `{query}` placeholder; JSON example braces are doubled (`{{`/`}}`) so `.format(query=...)` succeeds when the provided intent is a JSON string containing literal braces.
- The prompt is strictly bias-isolated: it receives one serialized intent and never the original user query; it instructs the model to produce a 100-200 word hypothetical English-Bible-style passage.
- `scripts/migrate_pipeline_message_types.py` upserts `hyde_generation` with `openai/gpt-4.1-mini`, `temperature=0.7`, `additional_model_settings={"max_tokens": 400}`, and the imported schema and prompt.
- `scripts/test_migration.py` was updated to expect 9 rows and to assert the `hyde_generation` row values, because the migration regression guard must stay in sync with the migration script.
- Full evidence in `.omo/evidence/task-11-hyde-retrieval-pipeline.txt`.

## [2026-07-28T17:30:00Z] Task: 10 — Live-test intent generation and refine the prompt until green

- `tests/system/test_intent_generation.py` is function-style and runnable directly; it skips loudly (exit 0 with message) when `OPENROUTER_API_KEY` is missing after `load_dotenv()`.
- For each of the three probes the test creates a session, calls `IntentService.generate_intents`, validates intent structure/count/primary flag, and asserts exactly one `intent_generation` DB row with non-null `raw_response`.
- The current `INTENT_GENERATION_PROMPT` produced schema-conforming responses for all three probes on the first iteration, so no prompt edits were required (0 of 3 iterations used).
- Failure QA: temporarily updating `ref_message_types.model_slug` to `openai/nonexistent` caused OpenRouter to return HTTP 400 "not a valid model ID"; the test surfaced the error and exited 1. Restoring `openai/gpt-4.1-mini` reran green.
- Full evidence in `.omo/evidence/task-10-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T19:25:00Z] Task: 12 — Re-verification note

- Implementation and commit already existed (`740bb9b` on `dev`). Re-ran offline and live tests to confirm current state: both exit 0, evidence refreshed in `.omo/evidence/task-12-hyde-retrieval-pipeline.txt`.
- No code changes were necessary; the existing implementation satisfies all MUST DO / MUST NOT DO constraints.

## [2026-07-28T19:00:00Z] Task: 16 — Add async RetrievalService for HyDE documents

- `RetrievalService(BaseService)` in `src/services/retrieval/service.py` takes injected `EmbeddingService` and `VerseStore` or constructs them from `db_path`; `search` filters out empty/None `hyde_document` entries, embeds the remaining docs in one `embed_texts(record=True)` call, and fans out `VerseStore.query` across `(doc, translation)` pairs via `asyncio.to_thread` + `asyncio.gather`.
- `VerseStore.query` returns Chroma distances for cosine space as tiny floats near zero for identical vectors (observed `-1.1920928955078125e-07` for a planted exact-match vector), so the test asserts top-1 ID and `assertAlmostEqual(distance, 0.0, places=5)` rather than exact equality.
- Offline test seeds 30 fake verses into temp `kjv_verses` and `web_verses` collections with a deterministic `embed_fn`, plants one query doc equal to a designated verse text, and asserts that verse ranks top-1 in both translations; a separate `empty_verses` collection proves no exception for empty hits.
- `GlobalReferenceCache.reset(fixture_db)` is required before constructing `EmbeddingService` so the `embedding_generation` ref row is found; a single `embedding_generation` message is recorded per `search` call (count reflects the number of successful docs, not translations).
- Verification: `env -u OPENROUTER_API_KEY .venv/bin/python scripts/test_retrieval_service.py` exits 0 (4/4 tests).
- Full evidence in `.omo/evidence/task-16-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T22:00:00Z] Task: 19 — Add consolidated offline step tests for pipeline services

- `scripts/test_pipeline_offline.py` covers AIMessage parsing (fenced/prose JSON, invalid confidence), LLMWrapper retry, EmbeddingService retry, HydeService partial failure, and intent schema boundaries in one script.
- Runtime is <1 s when retry sleeps are mocked to zero; without patching `asyncio.sleep` the wrapper/backoff adds ~7 s but still under the 60 s budget.
- `LLMWrapper` persistent-failure exhaustions save `num_tries=4` (not 3) because `AIMessage.num_tries` starts at 1 and `mark_failure` increments on every attempt, including the final one.
- `HydeService` has no `close()` method; clean teardown requires `service.llm.close()`.
- Full evidence in `.omo/evidence/task-19-hyde-retrieval-pipeline.txt`.

## [2026-07-28T23:00:00Z] Task: 17 — Add pipeline orchestrator and CLI runner

- `PipelineRunner(BaseService)` composes `IntentService`, `HyDEService`, `EmbeddingService`, `VerseStore`, and `RetrievalService`; `EmbeddingService` is created first and injected into `RetrievalService` to avoid duplicate setup.
- `PipelineResult` is a frozen-shape dataclass carrying `session_uuid`, `query`, `intents`, `hyde_docs`, and `results`.
- `PipelineRunner.close()` must close the retrieval service (which owns the shared embedding service), then each sub-service's `llm`, then the runner's own wrapper — `HydeService` and `IntentService` have no `close()` method.
- Live run on "what does the Bible say about anxiety" with `--top-k 5` produced 3 intents, 3 HyDE docs, and top-3 hits across both `kjv_verses` and `web_verses` (e.g., Psalms 62:8, Philippians 4:6, Psalms 42:11).
- Failure QA used an invalid `OPENROUTER_API_KEY=invalid-key` rather than a truly unset variable because `.env` holds a real key and `load_dotenv()` would otherwise repopulate it; the run exited 1 with "Invalid API key" and recorded an `intent_generation` error row (`num_tries=2`).
- The CLI snapshots whether `OPENROUTER_API_KEY` was present before `load_dotenv()` and deletes it afterward if it was absent, so `env -u OPENROUTER_API_KEY ...` still fails fast with a clear missing-key error rather than silently succeeding via `.env`.
- Full evidence in `.omo/evidence/task-17-hyde-retrieval-pipeline.txt`.

## [2026-07-28T22:30:00Z] Task: 18 — Add live end-to-end pipeline integration test

- `tests/system/test_pipeline_e2e.py` is a single-query live proof: it skips loudly when `OPENROUTER_API_KEY` is missing or when either `kjv_verses`/`web_verses` collection has fewer than 30,000 verses.
- The test calls `PipelineRunner.run("why do bad things happen to good people", top_k=5)` once, then asserts: 1–5 intents, HyDE docs == intents count, non-empty hits for both `kjv` and `web`, every `reference` matches `^(?:\w+\s)+\d+:\d+$`, and the audit trail has exactly 1 `intent_generation`, N `hyde_generation`, and 1 `embedding_generation` row with no orphan slugs.
- First-pass reference regex `^\w+ \d+:\d+$` incorrectly rejected multi-word books such as `1 Peter 2:20`; the final regex `(?:\w+\s)+\d+:\d+$` accepts them while still rejecting free-form text.
- Failure QA uses a built-in `--orphan-negative` flag that seeds a fixture DB with a `bogus_slug` message and proves the orphan check raises; evidence captured in `.omo/evidence/task-18-hyde-retrieval-pipeline.txt`.
- Full evidence in `.omo/evidence/task-18-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T23:30:00Z] Task: 20 — Update architecture documentation for the HyDE-retrieval pipeline

- Documented the implemented pipeline half (steps 2-4) across `architecture/implementation-status.md`, `architecture/README.md`, `architecture/pipeline-hyde-retrieval.md`, `todo.md`, `LLM_FRAMEWORK.md`, and `AGENTS.md`.
- `pipeline-hyde-retrieval.md` is the single source of truth for the component doc: message types, service contracts, data flow, CLI commands, and cost notes.
- `LLM_FRAMEWORK.md` now explicitly calls `LLMWrapper` the canonical recorded path and lists the four pipeline message types (`intent_generation`, `hyde_generation`, `embedding_generation`, `corpus_ingest`).
- The new doc directory structure in `architecture/README.md` lists all six new service modules: `base.py`, `intent/`, `hyde/`, `embeddings/`, `vectordb/`, `retrieval/`, `pipeline/`.
- Did NOT edit `README.md` (user's uncommitted rework) and did NOT mark pipeline steps 5-13 as done.
- Staged only the six doc paths; failure QA captured the diff name list to `.omo/evidence/task-20-hyde-retrieval-pipeline.txt`.

---

## [2026-07-28T23:59:00Z] Task: F4 — Remove `.omo/` paths from checkpoint commits

- The two checkpoint commits (`615e56a` and `eddb892`) staged `.omo/` state files, which violates the plan's commit discipline.
- Used a temporary git worktree checked out at base `8695c66` and ran `git rebase -i 8695c66` with the two commits marked `edit`.
- Removing `.omo/` from the first checkpoint commit caused modify/delete conflicts when rebase applied the second checkpoint commit; resolved by `git rm -r --cached .omo` and keeping the `AGENTS.md` change, then `git rebase --continue`.
- Both checkpoint messages remain in history, but each now only touches `AGENTS.md`; all 23 implementation commits in `8695c66..HEAD` are preserved.
- The original working tree was left untouched; the evidence is captured in `.omo/evidence/f4-history-cleanup.txt`.

## [2026-07-28T23:59:00Z] Task: F2 — Fix embedding service num_tries recording

- `_embed_chunk` now starts `attempts = 0`, increments before each call, and returns `(embeddings, attempts)` on success.
- On exhaustion it raises `MaxRetriesExceededError` after the loop; both retryable and non-retryable failures carry `_embedding_attempts` so `embed_texts` can accumulate the real count.
- `embed_texts` accumulates `num_tries` across chunks and passes it to `record_message` in both success and failure paths; the failure path records `error_text=str(exc)` with `raw_response=None`.
- Retry tests patch `asyncio.sleep` with `AsyncMock` to keep the suite sub-second; new assertions verify `num_tries == 3` for two failures → success and for persistent failure.
- Full evidence in `.omo/evidence/task-f2-fix-hyde-retrieval-pipeline.txt`.

## [2026-07-28T23:59:00Z] Task: F4 — Security-focused scope-fidelity review (pre-rewrite checkpoint commits)

- Inspected `.omo/` trees in checkpoint commits `615e56a` and `eddb892` via `git archive` extraction to temp dirs.
- Searched for: `OPENROUTER_API_KEY`, `api_key`, `sk-`, `Bearer`, `private_key`, `password`, `secret`, `token`, email addresses, IP addresses, URL tokens, and PEM private-key headers. No matches.
- Evidence files (task-1 through task-5, task-checkpoint) contain only command output, stdout/stderr, and usage metadata; no API key values or raw credential material. Task-3 evidence explicitly states the key is never logged and shows only the OpenRouter `usage` object.
- Run-continuation JSONs contain only session IDs and idle-state timestamps; no transcripts or tool results.
- Both commits touch only `.omo/` and `AGENTS.md`; `.env` is not included.
- **Verdict: `VERDICT: APPROVE`** — the committed `.omo/` files in `615e56a` and `eddb892` contain no secrets, API keys, credentials, or security-sensitive material.

## [2026-07-28T23:59:00Z] Task: F2 — Final Verification Wave reviewer note

- Reviewer focus: commit `1588ff4` (`src/services/embeddings/service.py` and `scripts/test_embedding_service.py`).
- Verified `_embed_chunk` initializes `attempts = 0`, increments before each `_call_embedder_once`, and returns `(embeddings, attempts)`; the `while attempts < self._max_retries` loop correctly uses `max_retries` from the `embedding_generation` ref row as a circuit breaker.
- Verified `embed_texts` initializes `num_tries = 0`, accumulates `chunk_tries` across chunks, and passes the real total to `record_message` on success.
- Verified failure path in `embed_texts` reads `exc._embedding_attempts` (set for both non-retryable exceptions and retry-exhaustion `MaxRetriesExceededError`) and records `error_text=str(exc)` with `raw_response=None`.
- Ran required checks: `py_compile` clean; `env -u OPENROUTER_API_KEY .venv/bin/python scripts/test_embedding_service.py` → 6/6 pass; `env -u OPENROUTER_API_KEY .venv/bin/python scripts/test_pipeline_offline.py` → 13/13 pass.
- No code files modified; no staging or commit performed.

VERDICT: APPROVE

## [2026-07-28T23:59:00Z] Task: DatabasePort abstraction

- Added `src/services/database/port.py` with a `typing.Protocol` describing the async surface pipeline services need: session/message creation, message-type lookups, and context-manager lifecycle.
- `AsyncSQLiteDatabase` in `src/services/database/adapters/sqlite.py` wraps `ChatDatabase` and delegates every call through `asyncio.to_thread`, keeping the existing synchronous SQLite code untouched.
- No existing services were migrated yet; the port is groundwork so a future hosted database (asyncpg, etc.) can be dropped in behind the same interface.
- Offline test `scripts/test_database_port.py` creates a temp fixture DB with the live schema, seeds `embedding_generation`, and asserts UUID creation, retrieval, and async context-manager usage.

## [2026-07-28T23:59:00Z] Task: Migrate LLMWrapper and BaseService to DatabasePort

- `LLMWrapper` now owns both `self.db` (sync `ChatDatabase` for reads/test assertions) and `self.db_port` (async `AsyncSQLiteDatabase` for writes). All `create_message_with_type` calls inside `call_api` are awaited via `db_port`.
- `BaseService.record_message` is now `async def` and delegates to `self.db_port`. `EmbeddingService` and `scripts/ingest_corpus.py` were updated to `await` it.
- `AsyncSQLiteDatabase` needed an instance-level `asyncio.Lock` to serialize concurrent writes from `asyncio.gather`; without it, parallel `HydeService` calls caused `sqlite3.ProgrammingError: Recursive use of cursors not allowed`.
- `LLMWrapper.close()` closes both sync and async connections; inside a running event loop, callers must close the async port with `await` rather than calling the sync `close()` method.
- Full offline suite passes (5 + 6 + 2 + 2 + 4 + 13 + 4 + 8 = 44 tests).

