# hyde-retrieval-pipeline - Work Plan

## TL;DR (For humans)

**What you'll get:** A working first half of the StrongChat pipeline: type a biblical question, and the system generates several structured interpretations (with explicit keywords, inferred keywords, and themes), writes one hypothetical Bible-style passage per interpretation in parallel, and returns the most semantically similar real verses from both the King James and World English Bibles — with every AI call auditable in your database.

**Why this approach:** It builds on the database-driven LLM path you already have (which already records every call) rather than the unused documented one, and it uses OpenRouter's cheap embedding model for both the one-time ~62,000-verse corpus and per-query documents — total embedding cost is a few cents, with no heavy machine-learning dependencies on your server.

**What it will NOT do:** No answer synthesis, ranking fusion, fact-checking, or original-language grounding (pipeline steps 5–13). It will not touch your chat REPL demo, your uncommitted README/gitignore edits, or any existing data.

**Effort:** Large
**Risk:** Medium - one-time corpus ingest (~62k verses through a paid API) and live-API test loops are the moving parts; everything else is local and reversible.
**Decisions to sanity-check:** WEB as the second translation; gpt-4.1-mini for both generation steps; keyword split (explicit/inferred) + themes in the intent schema; embeddings via OpenRouter rather than a local model.

Your next move: start execution in a worker session, or request a high-accuracy review first. Full execution detail follows below.

---

> TL;DR (machine): Large effort, Medium risk — intent generation refined & live-tested, asyncio HyDE generation, OpenRouter-embedded KJV+WEB corpus in local Chroma, per-doc async retrieval, full LLM-call audit trail, offline + live tests, 20 todos / 19 commits.

## Scope
### Must have
- Project `.venv` + pinned `requirements.txt` (aiohttp, jsonschema, requests, python-dotenv, chromadb); all run/test commands use `.venv/bin/python`
- New data dirs `data/bible/`, `data/chroma/` excluded via `.git/info/exclude` (never `.gitignore`)
- Data-layer repairs: fix wrong-table JOINs (`message_types` → `ref_message_types`), `prompt_template` in `get_message_type`, dead-code removal (`enums.py`, `create_intent`/`get_intents_for_message`, broken `scripts/test_main.py`), setup scripts aligned to `ref_message_types`, `GlobalReferenceCache` db_path injection, `PRAGMA foreign_keys = ON`, idempotent migration with pre-backup seeding all message-type slugs
- Refined `INTENT_GENERATION_SCHEMA` + prompt: 1–5 intents, each `intent_id`, `interpretation`, `keywords_explicit`, `keywords_inferred`, `themes`, `confidence`, `is_primary`; live-tested against OpenRouter until all probes pass
- `BaseService` + `IntentService`, `HydeService` (asyncio.gather, 1 doc per intent, bias-isolated per-call context), `EmbeddingService` (batched OpenRouter `openai/text-embedding-3-small`), `VerseStore` (chromadb PersistentClient, one cosine collection per translation), `RetrievalService`, `PipelineRunner` + `scripts/run_pipeline.py`
- KJV + WEB corpus download from midvash/bible-data with 66-book / verse-count validation + manifest; per-verse embedding ingest into Chroma with book/chapter/verse/translation metadata (idempotent upsert)
- Every query-time OpenRouter call recorded in `messages` linked to its `ref_message_types` slug (1 `intent_generation` + N `hyde_generation` + 1 `embedding_generation` per query); corpus ingest = one `corpus_ingest` summary row per translation; embedding rows store summaries, never raw vectors
- Offline unit/step tests (scripts/ unittest style) + live system tests (tests/system/ style) incl. one end-to-end pipeline test; docs updates; one commit per todo
### Must NOT have (guardrails, anti-slop, scope boundaries)
- NO pipeline steps 5–13: RRF, Macula lookup, graph expansion, synthesis, evaluator, validator, final response
- NO reranking, cross-encoders, hybrid/BM25 search, M>1 HyDE docs per intent
- NO behavior changes to `src/main.py`; `intent_classification` ref row stays `is_active=1` (main.py depends on it)
- NO edits to `.gitignore` or `README.md` (user's uncommitted changes); no committing `.env`, `data/*.db`, `data/bible/`, `data/chroma/`, `.venv/`, `.omo/`, `.opencode/`, `opencode.json`
- NO pytest adoption, NO `pip --break-system-packages`, NO apt for Python deps, NO torch/GPU/sentence-transformers
- NO raw embedding vectors in `messages` (summaries only); NO per-chunk rows during ingest
- NO removal of `INTENT_CLASSIFICATION_SCHEMA`/`INTENT_DISAMBIGUATION_SCHEMA` or legacy `create_message`/`get_messages` (still referenced by old tests); NO backfill of legacy orphan message rows (accepted as-is)
- NO destructive script runs against `data/chat_database.db` (create_new_database.py drops tables — fixture paths only); NO web server / Quart

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: **tests-after** (user-confirmed), implementation + test in ONE todo. Framework: stdlib `unittest`, matching the two existing conventions — runnable scripts under `scripts/` (custom TextTestRunner, `sys.exit(0|1)`, path-bootstrap `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))`) and function/TestCase files under `tests/system/` for live-API tests. All invocations use `.venv/bin/python`. Live tests skip loudly (print reason, exit 0) when `OPENROUTER_API_KEY` is unset. Offline tests must pass with the key unset.
- DB assertions via `sqlite3 data/chat_database.db "<sql>"` CLI; Chroma assertions via `.venv/bin/python -c` one-liners; corpus validation via the download script's own checks.
- Evidence: `.omo/evidence/task-<N>-hyde-retrieval-pipeline.txt` — each todo's QA command outputs (stdout+stderr+exit code) are tee'd to its evidence file.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

- **Wave 1 — Groundwork & data layer (todos 1–7).** Sequential spine with 1‖2 at the start and 3‖4‖5 after todo 1. Todo 6 (migration) needs 4+5; todo 7 (BaseService) needs 6. Everything later depends on this wave.
- **Wave 2 — Intent + HyDE services (todos 8–12).** After todo 7: 8 → 9 → 10 (intent chain, includes the live prompt-refinement loop); 11 after 8; 12 after 10+11.
- **Wave 3 — Corpus + embeddings + vector store (todos 13–15).** Runs **in parallel with Wave 2** (both gated only on Wave 1): 13 after 1; 14 after 3+7; 15 after 13+14. This is the wave to hand to a second implementation agent while Wave 2 proceeds.
- **Wave 4 — Retrieval, orchestrator, tests, docs (todos 16–20).** 16 after 12+14+15; 17 after 16; 18 after 17; 19 after 12+15 (can parallel 16–17); 20 last.
- Multi-agent note (user-requested): Wave 1 must complete first (shared foundation). After that, Wave 2 and Wave 3 are independent and SHOULD be dispatched to two parallel agents; Wave 4 integration work follows, with todo 19 parallelizable against 16–17.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1. venv + requirements.txt | — | 3,4,5,13 (everything) | 2 |
| 2. .git/info/exclude + data dirs | — | none | 1, all |
| 3. OpenRouter embeddings smoke | 1 | 14 | 4,5 |
| 4. database.py repairs + dead-code removal | 1 | 6 | 3,5 |
| 5. Setup scripts aligned to ref_message_types | 1 | 6 | 3,4 |
| 6. Cache injection + FK pragma + message-type migration | 4,5 | 7 | — |
| 7. BaseService | 6 | 8,11,14,15,16,17 | — |
| 8. Refined intent schema + prompt + ref row | 7 | 9,11 | 13,14,15 |
| 9. IntentService + offline unit test | 8 | 10 | 13,14,15 |
| 10. Live intent generation test + prompt refinement | 9 | 12 | 13,14,15 |
| 11. HYDE schema + prompt + ref row | 7,8 (field contract) | 12 | 9,10,13,14,15 |
| 12. HydeService (async gather) + live test | 10,11 | 16 | 13,14,15 |
| 13. Corpus download + validation + manifest | 1 | 15 | 8,9,10,11,12,14 |
| 14. EmbeddingService (batched OpenRouter) | 3,7 | 15,16 | 8,9,10,11,12,13 |
| 15. VerseStore + corpus ingest | 13,14 | 16 | 8,9,10,11,12 |
| 16. RetrievalService + offline test | 12,14,15 | 17 | 19 |
| 17. Pipeline orchestrator + CLI | 16 | 18 | 19 |
| 18. Live end-to-end integration test | 17 | 20 | 19 |
| 19. Offline step tests consolidation | 12,15 | none | 16,17,18 |
| 20. Architecture docs update | 18 | none | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Create project venv and pinned requirements.txt
  What to do / Must NOT do: Verify venv support (`python3 -m venv .venv`; if it fails, run `sudo apt install -y python3.12-venv` then retry). Write `requirements.txt` at repo root with exactly these pins: `aiohttp>=3.9,<4`, `jsonschema>=4.10,<5`, `requests>=2.31,<3`, `python-dotenv>=1.0,<2`, `chromadb>=1.0,<2`. Then `.venv/bin/pip install --upgrade pip` and `.venv/bin/pip install -r requirements.txt`. Must NOT use `--break-system-packages`, apt for Python packages, pyproject.toml (requirements.txt is the decided manifest), or commit `.venv/`.
  Parallelization: Wave 1 | Blocked by: — | Blocks: 3,4,5,13 (all later waves)
  References (executor has NO interview context - be exhaustive): no requirements/pyproject/venv exists (verified); system deps are apt-only (aiohttp 3.9.1, jsonschema 4.10.3, requests 2.31.0 per `dpkg -l`); Python 3.12.3; Ubuntu PEP 668 blocks system pip; chromadb install docs https://docs.trychroma.com/docs/overview/getting-started
  Acceptance criteria (agent-executable): `.venv/bin/python -c "import aiohttp, jsonschema, requests, dotenv, chromadb; print('chromadb', chromadb.__version__)"` exits 0.
  QA scenarios (name the exact tool + invocation): happy = the acceptance import command → tee output to `.omo/evidence/task-1-hyde-retrieval-pipeline.txt`. failure = `grep -cE '^(aiohttp|jsonschema|requests|python-dotenv|chromadb)[><=]' requirements.txt` returns 5 AND `.venv/bin/pip check` exits 0 (no dependency conflicts) → append to same evidence file.
  Commit: Y | "Add project venv and pinned requirements.txt" (stage only `requirements.txt`)

- [x] 2. Exclude new data dirs via .git/info/exclude and scaffold data directories
  What to do / Must NOT do: `mkdir -p data/bible data/chroma`; append these three lines to `.git/info/exclude` (create if missing): `.venv/`, `data/bible/`, `data/chroma/`. Must NOT edit `.gitignore` (carries user's uncommitted changes), must NOT add `.omo/`/`.opencode/` (out of scope), must NOT commit anything (`.git/info/exclude` is not versioned).
  Parallelization: Wave 1 | Blocked by: — | Blocks: none
  References: `git status` shows ` M .gitignore` (user's pending rework); `.gitignore:38-41` already ignores `*.db` but not the new dirs; decision D6(h) in `.omo/drafts/hyde-retrieval-pipeline.md`.
  Acceptance criteria: `git check-ignore -v .venv data/bible data/chroma` prints three matches sourced from `.git/info/exclude`.
  QA scenarios: happy = acceptance command → `.omo/evidence/task-2-hyde-retrieval-pipeline.txt`. failure = `touch data/bible/.probe data/chroma/.probe .venv-probe 2>/dev/null; git status --porcelain | grep -E 'data/bible|data/chroma|\.venv'` returns EMPTY (clean up probes after) → evidence file.
  Commit: N (no versioned file changes)

- [x] 3. Verify OpenRouter embeddings endpoint with a live smoke script
  What to do / Must NOT do: Create `scripts/check_embeddings_api.py`: path-bootstrap `src`, load `.env` via `dotenv.load_dotenv()`, POST `https://openrouter.ai/api/v1/embeddings` with `requests` (timeout 60) payload `{"model": "openai/text-embedding-3-small", "input": ["In the beginning God created the heaven and the earth.", "For God so loved the world, that he gave his only begotten Son"]}`, headers mirroring `src/services/llm/wrapper.py:45-50`. Assert HTTP 200, `len(data)==2`, `len(data[0]['embedding'])==1536`; print latency and `usage` if present; exit non-zero with clear stderr on any failure (missing key → explicit message). Must NOT record anything in the DB (pure endpoint check), must NOT print the API key.
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 14
  References: OpenRouter embeddings API https://openrouter.ai/docs/api/reference/embeddings (batched `input` array supported); header pattern `src/services/llm/wrapper.py:45-50`; `.env` contains `OPENROUTER_API_KEY` (never quote the value); `python-dotenv` usage pattern `src/main.py:15-24`.
  Acceptance criteria: `.venv/bin/python scripts/check_embeddings_api.py` exits 0 and prints `dim=1536`.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-3-hyde-retrieval-pipeline.txt`. failure = `env -u OPENROUTER_API_KEY .venv/bin/python scripts/check_embeddings_api.py` exits NON-zero with a "key not configured" stderr message → evidence file.
  Commit: Y | "Add OpenRouter embeddings API smoke check script"

- [x] 4. Repair database.py query bugs and remove dead code
  What to do / Must NOT do: In `src/services/sqlite/database.py`: (a) replace `message_types` with `ref_message_types` in the three JOINs (lines ~136, ~175, ~185); (b) add `prompt_template` to the `get_message_type` SELECT list and returned dict; (c) delete `create_intent` (lines ~243-259) and `get_intents_for_message` (lines ~299-309) — the `intents` table is absent from the live DB. Delete `src/config/enums.py` entirely (imported nowhere; has an import-time `AttributeError` via `MessageType.INITENT_CLASSIFICATION` typo). Delete `scripts/test_main.py` (broken: imports `get_message_intent`/`call_openrouter_api` removed from main.py). Create `scripts/test_database_queries.py` (scripts/ unittest style): build a fixture DB in a temp dir with the live schema (sessions; ref_message_types incl. prompt_template; messages), insert one ref row + one session + one message, assert `get_message_by_uuid` returns non-null `step_name` and a `prompt_template` key, and `get_messages_by_session_and_type` returns the joined row. Must NOT remove deprecated `create_message`/`get_messages` (still referenced by `tests/test_*.py`); must NOT run any create/populate script against `data/chat_database.db`; must NOT enable the FK pragma here (lands in todo 6 with the seeds).
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 6
  References: `src/services/sqlite/database.py:136,175,185` (wrong-table JOINs), `:60-91` (get_message_type), `:243-259,:299-309` (dead methods); live schema quoted in `.omo/drafts/hyde-retrieval-pipeline.md` Findings; `src/config/enums.py:22-25` (typo); `scripts/test_main.py:13` (broken imports); grep-verified zero `enums` imports across `*.py`.
  Acceptance criteria: `.venv/bin/python scripts/test_database_queries.py` exits 0 AND `grep -n "JOIN message_types" src/services/sqlite/database.py` returns nothing AND `grep -rn "from config.enums\|import enums" src/ scripts/ tests/` returns nothing.
  QA scenarios: happy = acceptance commands → `.omo/evidence/task-4-hyde-retrieval-pipeline.txt`. failure = in the new test, point `get_message_type` at a slug missing from the fixture → assert returns `None` (no exception) → evidence file.
  Commit: Y | "Fix ref_message_types JOINs and remove dead code"

- [x] 5. Align database setup scripts with the live ref_message_types schema
  What to do / Must NOT do: In `scripts/create_new_database.py`: rename table `message_types` → `ref_message_types`, add `prompt_template TEXT` column, drop the `intents` table DDL, remove its seed block (seeding is the migration script's job, todo 6). In `scripts/populate_message_types.py`: rename table → `ref_message_types`, add `prompt_template` to the INSERT; source the disambiguation schema/prompt from `config.schemas.INTENT_DISAMBIGUATION_SCHEMA` / `config.prompts.INTENT_DISAMBIGUATION_PROMPT` (import via the scripts/ path-bootstrap); keep the simple `intent_classification` row (main.py depends on it) but set its `prompt_template` from `config.prompts.INTENT_CLASSIFICATION_PROMPT`. Both scripts already accept `db_path` — keep that. Must NOT run either against `data/chat_database.db` (create script DROPS tables); must NOT seed `intent_generation`/`hyde_generation` here (todos 8/11).
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 6
  References: `scripts/create_new_database.py:32-62` (table DDL), `:67-119` (seed); `scripts/populate_message_types.py:118-135` (INSERT); live DB has `ref_message_types` with 11 columns incl. `prompt_template` (draft Findings); `src/config/prompts.py:16-42`, `src/config/schemas.py:66-121`.
  Acceptance criteria: `tmp=$(mktemp -d); .venv/bin/python scripts/create_new_database.py` modified/invoked with `--db-path $tmp/fixture.db` (add argparse if absent) then `.venv/bin/python scripts/populate_message_types.py --db-path $tmp/fixture.db`; `sqlite3 $tmp/fixture.db ".schema ref_message_types"` shows `prompt_template`; `sqlite3 $tmp/fixture.db "SELECT slug, prompt_template IS NOT NULL FROM ref_message_types"` shows both rows with 1; re-run populate → idempotent (INSERT OR REPLACE).
  QA scenarios: happy = acceptance sequence → `.omo/evidence/task-5-hyde-retrieval-pipeline.txt`. failure = `sqlite3 $tmp/fixture.db "SELECT name FROM sqlite_master WHERE name IN ('message_types','intents')"` returns EMPTY → evidence file.
  Commit: Y | "Align database setup scripts with ref_message_types schema"

- [x] 6. Add cache db_path injection, FK enforcement, and the pipeline message-type migration (ONE commit)
  What to do / Must NOT do: (a) `src/config/cache.py`: `GlobalReferenceCache.__init__(self, db_path: Optional[str] = None)` used only on first init (store path, pass to `ChatDatabase(db_path or 'data/chat_database.db')`); add classmethod `reset(cls, db_path: Optional[str] = None)` that drops the singleton and re-initializes (for fixture tests); keep `refresh_cache()`. (b) `src/services/sqlite/database.py` `ChatDatabase.__init__`: `self.conn.execute("PRAGMA foreign_keys = ON")` immediately after connect. (c) Create `scripts/migrate_pipeline_message_types.py` (argparse `--db-path`, default `data/chat_database.db`): step 0 = backup via `sqlite3.Connection.backup` to `<db>.pre-pipeline.bak`; then `INSERT OR REPLACE` these rows (all `max_retries=3`, `is_active=1`, `additional_model_settings='{}'`, `prompt_template=NULL`, `request_schema` as noted): `human_input` (creator_type `human`, schema `{"type":"object"}`), `llm_response` (creator_type `llm`, schema `{"type":"object"}`), `error` (creator_type `programmatic`, schema `{"type":"object"}`), `embedding_generation` (creator_type `programmatic`, model_slug `openai/text-embedding-3-small`, temperature 0.0, schema for a SUMMARY: `{"type":"object","properties":{"model":{"type":"string"},"dimension":{"type":"integer"},"count":{"type":"integer"}},"required":["model","dimension","count"]}`), `corpus_ingest` (creator_type `programmatic`, model_slug `n/a`, schema `{"type":"object","properties":{"translation":{"type":"string"},"verses":{"type":"integer"},"status":{"type":"string"}},"required":["translation","verses","status"]}`); then `UPDATE ref_message_types SET is_active=0 WHERE slug='intent_disambiguation'`. Run the migration TWICE to prove idempotency. Create `scripts/test_migration.py`: rerun → same row counts; FK insert with bogus slug raises `sqlite3.IntegrityError`; insert with `human_input` slug succeeds. Must NOT touch `intent_classification` (main.py depends, stays active); NO backfill of the 6 legacy orphan rows (accepted, record in test comments); must NOT seed `intent_generation`/`hyde_generation` here.
  Parallelization: Wave 1 | Blocked by: 4,5 | Blocks: 7
  References: `src/config/cache.py:18-40` (init/load), `src/services/sqlite/database.py:12-20` (connect site), live orphan slugs `human_input`/`error`/`llm_response` (draft Findings §5.4), `src/main.py:99-103` (intent_classification dependency), Metis findings 1/2/4/5/6/7 (draft D6).
  Acceptance criteria: `.venv/bin/python scripts/migrate_pipeline_message_types.py` run twice exits 0 both times; `sqlite3 data/chat_database.db "SELECT slug,is_active FROM ref_message_types ORDER BY slug"` lists `corpus_ingest, embedding_generation, error, human_input, intent_classification(1), intent_disambiguation(0), llm_response`; `ls data/chat_database.db.pre-pipeline.bak` exists; `.venv/bin/python scripts/test_migration.py` exits 0.
  QA scenarios: happy = acceptance sequence → `.omo/evidence/task-6-hyde-retrieval-pipeline.txt`. failure = inside `test_migration.py`, attempt `create_message_with_type(session, 'bogus_slug', 'x')` → expect `sqlite3.IntegrityError` (proves pragma live) → evidence file.
  Commit: Y | "Add pipeline message-type migration, FK enforcement, and cache injection"

- [x] 7. Add BaseService shared foundation
  What to do / Must NOT do: Create `src/services/base.py`: `class BaseService` with `__init__(self, db_path: str = 'data/chat_database.db')` that owns ONE `LLMWrapper(db_path)` as `self.llm` and exposes `self.db` (alias to `self.llm.db`), `self.cache` (alias to `self.llm.cache`), `record_message(message_type_slug, unique_prompt, session_uuid, raw_response=None, error_text=None, num_tries=1) -> str` (delegates to `db.create_message_with_type`), and `parse_message(aimessage, message_type_slug) -> Dict[str, Any]` (uses `cache.get_message_type(slug)['request_schema']` with `aimessage.get_parsed_response`). Must NOT modify `LLMWrapper` (chat-completions path works as-is); must NOT duplicate DB connections beyond the wrapper's own; no new dependencies.
  Parallelization: Wave 1 | Blocked by: 6 | Blocks: 8,11,14,15,16,17
  References: `src/services/llm/wrapper.py:20-35` (init), `:52-147` (call_api records rows itself), `src/services/llm/aimessage.py:24-42` (get_parsed_response), `src/config/cache.py:42-44` (get_message_type after todo 6 injection).
  Acceptance criteria: `.venv/bin/python -c "import sys; sys.path.insert(0,'src'); from services.base import BaseService; s=BaseService(); print(type(s.llm).__name__, type(s.db).__name__)"` prints `LLMWrapper ChatDatabase` and exits 0 (requires OPENROUTER_API_KEY in env — run with `.env` loaded or `set -a; . ./.env; set +a`).
  QA scenarios: happy = acceptance command → `.omo/evidence/task-7-hyde-retrieval-pipeline.txt`. failure = `BaseService(db_path='/nonexistent/x.db')` raises an exception from sqlite (no silent fallback) → evidence file.
  Commit: Y | "Add BaseService shared foundation for pipeline services"

- [x] 8. Add refined INTENT_GENERATION_SCHEMA, prompt, and ref row
  What to do / Must NOT do: In `src/config/schemas.py` add `INTENT_GENERATION_SCHEMA` (title `IntentGenerationResponse`): `query_analysis` {`original_query` str, `core_questions` str[], `context_clues` str[]} (all required); `intents` array minItems 1 maxItems 5 of {`intent_id` str, `interpretation` str, `keywords_explicit` str[] (terms appearing verbatim in the user query), `keywords_inferred` str[] (related terms NOT in the query), `themes` str[] (1–3 short theme labels), `confidence` 0–1, `is_primary` bool} (all required); `recommended_search_approach` str; top-level required all three. In `src/config/prompts.py` add `INTENT_GENERATION_PROMPT`: ONLY placeholder `{query}`; any literal braces in the JSON example doubled (`{{`/`}}` per wrapper `.format`, see `src/services/llm/wrapper.py:78`); instruct: plain-language analysis, NO biblical vocabulary in the analysis, keywords_explicit must be verbatim from the query, keywords_inferred must NOT appear in the query, 1–3 themes per intent, 1–5 intents covering distinct plausible readings, exactly one `is_primary: true`. Export both from `src/config/__init__.py`. Extend `scripts/migrate_pipeline_message_types.py` to upsert ref row `intent_generation` (creator_type `programmatic`, model_slug `openai/gpt-4.1-mini`, temperature 0.2, `additional_model_settings={"max_tokens":800}`, prompt_template = `INTENT_GENERATION_PROMPT` imported from config, request_schema = `INTENT_GENERATION_SCHEMA` imported from config); rerun migration. Create `scripts/test_intent_schema.py`: valid fixture passes; fixtures missing `themes`, missing `keywords_inferred`, 0 intents, 6 intents, confidence 1.5 each FAIL validation; prompt formats via `.format(query='test')` without exception.
  Parallelization: Wave 2 | Blocked by: 7 | Blocks: 9,11
  References: user decision D1 (draft): split keywords explicit/inferred + themes; `src/config/schemas.py:3-64` (style precedent), `src/config/prompts.py:16-42` (brace-doubling precedent), model choice `openai/gpt-4.1-mini` from `.env` `MODEL_SLUG_INTENTS` (user-confirmed default).
  Acceptance criteria: `.venv/bin/python scripts/test_intent_schema.py` exits 0; `sqlite3 data/chat_database.db "SELECT slug, model_slug, prompt_template IS NOT NULL, is_active FROM ref_message_types WHERE slug='intent_generation'"` returns `intent_generation|openai/gpt-4.1-mini|1|1`.
  QA scenarios: happy = acceptance commands → `.omo/evidence/task-8-hyde-retrieval-pipeline.txt`. failure = the 5 invalid fixtures each raise validation errors in the test (assert specific messages) → evidence file.
  Commit: Y | "Add refined intent generation schema, prompt, and message type"

- [x] 9. Add IntentService with offline unit test
  What to do / Must NOT do: Create `src/services/intent/__init__.py` (exports `IntentService`, `__all__`) and `src/services/intent/service.py`: `class IntentService(BaseService)` with `async def generate_intents(self, query: str, session_uuid: str) -> Dict[str, Any]` → `aimessage = await self.llm.call_api('intent_generation', query, session_uuid)` → `parsed = self.parse_message(aimessage, 'intent_generation')` → return `{'message_uuid': aimessage.uuid, 'query_analysis': parsed['query_analysis'], 'intents': parsed['intents'], 'recommended_search_approach': parsed['recommended_search_approach']}`. Create `scripts/test_intent_service.py` (offline, `unittest.mock`): patch `LLMWrapper.call_api` to return an `AIMessage` whose `raw_response` is a canned valid JSON (2 intents) → assert parsed structure; canned invalid JSON (missing `themes`) → assert `ValueError`; also assert the mock was called with slug `intent_generation` and the raw query unchanged. Must NOT make live API calls in this test; must NOT modify `LLMWrapper`.
  Parallelization: Wave 2 | Blocked by: 8 | Blocks: 10
  References: todo 7 BaseService; `src/services/llm/wrapper.py:52-70` (call_api contract); `src/services/llm/aimessage.py:24-42` (parsing incl. markdown-fence extraction); service `__init__.py` export pattern `src/services/llm/__init__.py:1-6`.
  Acceptance criteria: `.venv/bin/python scripts/test_intent_service.py` exits 0 with OPENROUTER_API_KEY unset (proves offline).
  QA scenarios: happy = acceptance run (valid + invalid fixtures) → `.omo/evidence/task-9-hyde-retrieval-pipeline.txt`. failure = invalid fixture raises `ValueError` mentioning `themes` (assert in test) → evidence file.
  Commit: Y | "Add intent generation service with offline tests"

- [x] 10. Live-test intent generation and refine the prompt until green
  What to do / Must NOT do: Create `tests/system/test_intent_generation.py` (function-style, runnable directly, matching `tests/system/test_intent.py` convention): skip loudly (exit 0 with message) if `OPENROUTER_API_KEY` unset. For each of 3 probes — "why do bad things happen to good people", "how do I deal with anxiety about the future", "what does the Bible say about forgiving someone who hurt me" — create a session (`db.create_session(f"intent-test: {probe[:50]}", created_by="test")`), call `IntentService.generate_intents`, assert: 1 ≤ len(intents) ≤ 5; every intent has non-empty `interpretation`, `keywords_explicit`, `keywords_inferred`, `themes`; at least one `is_primary` is True; `sqlite3`-equivalent query via `db.get_messages_by_session_and_type(session, 'intent_generation')` returns exactly 1 row with non-null `raw_response`. If any assertion fails, iterate `INTENT_GENERATION_PROMPT` (max 3 documented iterations, log each attempt to evidence) until green. Must NOT change the schema to make tests pass (prompt-only refinement); must NOT deactivate `intent_classification`.
  Parallelization: Wave 2 | Blocked by: 9 | Blocks: 12
  References: `tests/system/test_intent.py` (live-test convention); decision D1; architecture zero-biblical-vocabulary principle (`architecture/README.md` Intent Disambiguation requirements).
  Acceptance criteria: `set -a; . ./.env; set +a; .venv/bin/python tests/system/test_intent_generation.py` exits 0 with all 3 probes passing.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-10-hyde-retrieval-pipeline.txt`. failure = temporarily `UPDATE ref_message_types SET model_slug='openai/nonexistent' WHERE slug='intent_generation'`, rerun → script surfaces API error and exits NON-zero; restore row and rerun green → evidence file (both runs).
  Commit: Y | "Add live intent generation system test"

- [x] 11. Add HYDE_GENERATION_SCHEMA, prompt, and ref row
  What to do / Must NOT do: In `src/config/schemas.py` add `HYDE_GENERATION_SCHEMA`: `{"type":"object","properties":{"hyde_document":{"type":"string","minLength":50}},"required":["hyde_document"]}` (title `HydeGenerationResponse`). In `src/config/prompts.py` add `HYDE_GENERATION_PROMPT`: ONLY placeholder `{query}` (it receives ONE intent serialized as JSON — the bias-isolation contract; the original user query is NEVER included); literal braces doubled; instruct: given this single intent (interpretation, keywords, themes), write a 100–200 word hypothetical passage in the style of an English Bible (modern English prose with biblical cadence) that would contain the answer; respond with JSON only. Export both from `src/config/__init__.py`. Extend `scripts/migrate_pipeline_message_types.py` to upsert `hyde_generation` (creator_type `programmatic`, model_slug `openai/gpt-4.1-mini`, temperature 0.7, `additional_model_settings={"max_tokens":400}`, prompt_template and request_schema imported from config); rerun migration. Create `scripts/test_hyde_schema.py`: valid fixture passes; 20-char doc fails minLength; missing `hyde_document` fails; prompt `.format(query=<sample intent JSON containing braces>)` succeeds.
  Parallelization: Wave 2 | Blocked by: 7,8 (intent field contract) | Blocks: 12
  References: user rule "each LLM call gets only what it needs, no extra context to prevent bias"; intent fields from todo 8; Metis #11 brace rule (`src/services/llm/wrapper.py:78`).
  Acceptance criteria: `.venv/bin/python scripts/test_hyde_schema.py` exits 0; `sqlite3 data/chat_database.db "SELECT slug, temperature, is_active FROM ref_message_types WHERE slug='hyde_generation'"` returns `hyde_generation|0.7|1`.
  QA scenarios: happy = acceptance commands → `.omo/evidence/task-11-hyde-retrieval-pipeline.txt`. failure = invalid fixtures (short doc, missing key) raise validation errors with asserted messages → evidence file.
  Commit: Y | "Add HyDE generation schema, prompt, and message type"

- [x] 12. Add HydeService with asyncio parallel generation and live test
  What to do / Must NOT do: Create `src/services/hyde/__init__.py` and `src/services/hyde/service.py`: `class HydeService(BaseService)` with `async def generate_for_intents(self, intents: List[Dict[str, Any]], session_uuid: str) -> List[Dict[str, Any]]` → `asyncio.gather(*[self._generate_one(i, session_uuid) for i in intents], return_exceptions=True)`; `_generate_one` serializes ONLY `{intent_id, interpretation, keywords_explicit, keywords_inferred, themes}` to JSON as `unique_prompt`, calls `self.llm.call_api('hyde_generation', intent_json, session_uuid)`, parses via `self.parse_message`, returns `{'intent_id', 'hyde_document', 'message_uuid'}`. Exceptions per intent: log, mark result `{'intent_id', 'hyde_document': None, 'error': str(e)}` (the wrapper already wrote the error row); after gather, if ZERO successes raise `LLMError`, else return list. Live test `tests/system/test_hyde_generation.py` (skip loudly without key): run real `IntentService.generate_intents` on "what does the Bible say about anxiety", feed intents to `HydeService`, assert docs count == intents count, each successful doc ≥ 50 chars, and `hyde_generation` message rows for the session == number of attempted intents. Must NOT pass the original user query into HyDE calls; must NOT create aiohttp sessions outside the wrapper; note in a comment that the shared wrapper/sqlite connection is safe under `asyncio.gather` (single-threaded event loop serializes writes).
  Parallelization: Wave 2 | Blocked by: 10,11 | Blocks: 16
  References: `src/services/llm/wrapper.py:91-147` (retry + record behavior), asyncio.gather partial-failure pattern; decision M=1 per intent (user); D5 recording rule.
  Acceptance criteria: `set -a; . ./.env; set +a; .venv/bin/python tests/system/test_hyde_generation.py` exits 0; offline portion: `scripts/test_hyde_service.py` (mocked call_api: 1 success + 1 raising → 1 doc + 1 error entry, no raise; all-fail → `LLMError`) exits 0 with key unset.
  QA scenarios: happy = live + offline runs → `.omo/evidence/task-12-hyde-retrieval-pipeline.txt`. failure = offline all-fail case raises `LLMError` and `error` entries recorded (assert) → evidence file.
  Commit: Y | "Add HyDE generation service with asyncio parallel calls"

- [x] 13. Download and validate the KJV + WEB corpus
  What to do / Must NOT do: Create `scripts/download_bible_corpus.py` (argparse `--kjv-file`/`--web-file` overrides for testing): fetch `https://raw.githubusercontent.com/midvash/bible-data/main/versions/en/kjv/kjv.json` and `https://raw.githubusercontent.com/midvash/bible-data/main/versions/en/web/web.json` with `requests` (timeout 120) into `data/bible/kjv.json` and `data/bible/web.json`. Parse each; expected shape per repo README/SCHEMA.md: top-level object with a `books` list, each book with an OSIS identifier + `chapters`, each chapter with `verses` (number/text) — the implementer MUST confirm actual keys from the downloaded file and adapt, failing loudly with the actual top-level keys if the shape differs (cite https://github.com/midvash/bible-data/blob/main/SCHEMA.md in a comment). Validate per translation: exactly 66 books; total verses in [30000, 32000]; zero empty verse texts. Write `data/bible/manifest.json`: `{<slug>: {file, books, verses, source_url, license: "public-domain", downloaded_at}}` for `kjv` and `web`. Must NOT commit `data/bible/` contents (excluded in todo 2); no other translations.
  Parallelization: Wave 3 | Blocked by: 1 | Blocks: 15
  References: midvash/bible-data repo (verified live): README quick-start + version table (en/kjv 1769, en/web 2000, both public-domain); canonical KJV verse count 31,102.
  Acceptance criteria: `.venv/bin/python scripts/download_bible_corpus.py` exits 0; `.venv/bin/python -c "import json; m=json.load(open('data/bible/manifest.json')); assert m['kjv']['books']==66 and m['web']['books']==66 and all(30000<=m[t]['verses']<=32000 for t in ('kjv','web')); print(m)"` prints the manifest.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-13-hyde-retrieval-pipeline.txt`. failure = truncate a copy of kjv.json in a temp dir, run with `--kjv-file <truncated>` → non-zero exit with a JSON/validation error message → evidence file.
  Commit: Y | "Add Bible corpus download and validation script"

- [x] 14. Add EmbeddingService with batched OpenRouter embeddings
  What to do / Must NOT do: Create `src/services/embeddings/__init__.py` and `src/services/embeddings/service.py`: `class EmbeddingService(BaseService)` with `__init__(self, db_path='data/chat_database.db', embed_fn=None)` — `embed_fn` injectable for tests (signature `(texts: List[str]) -> List[List[float]]`); default None = live OpenRouter. `async def embed_texts(self, texts: List[str], session_uuid: Optional[str]=None, record: bool=True, chunk_size: int=256) -> List[List[float]]`: chunk inputs; per chunk POST `https://openrouter.ai/api/v1/embeddings` payload `{"model": <model_slug from the embedding_generation ref row>, "input": chunk}` via `aiohttp` with the same retry/backoff policy as `LLMWrapper` (max_retries from ref row, backoff 1s→2s→4s, `APITimeoutError`/`APIConnectionError`/`APIResponseError` semantics); preserve input order. When `record=True` and `session_uuid` set: ONE `embedding_generation` message per `embed_texts` call (not per chunk) via `self.record_message`: `unique_prompt` = `json.dumps({"texts": texts})` truncated to 4000 chars, `raw_response` = summary JSON `{model, dimension, count}` — NEVER raw vectors. Ingest mode: `record=False`. Create `scripts/test_embedding_service.py` (offline): fake `embed_fn` (deterministic hash-seeded 1536-dim vectors, counts calls) → 600 texts produce 3 chunked calls with order preserved; injected `APIConnectionError` twice then success → retry path works; recording path against a fixture DB (`GlobalReferenceCache.reset(fixture_db)` from todo 6, fixture seeded with the `embedding_generation` row) asserts `raw_response` contains `"dimension"` and does NOT contain `"embedding"`. Must NOT store vectors in the DB; must NOT use the chat-completions endpoint.
  Parallelization: Wave 3 | Blocked by: 3,7 | Blocks: 15,16
  References: todo 3 (endpoint + 1536-dim verified); `src/services/llm/wrapper.py:115-133` (retry/backoff to mirror); OpenRouter embeddings docs; D5/D6 summary-recording rule (Metis #10).
  Acceptance criteria: `.venv/bin/python scripts/test_embedding_service.py` exits 0 with OPENROUTER_API_KEY unset.
  QA scenarios: happy = acceptance run (chunking, order, retry, recording-summary assertions) → `.omo/evidence/task-14-hyde-retrieval-pipeline.txt`. failure = fake `embed_fn` raising persistently → `MaxRetriesExceededError` and an `error_text` row in the fixture DB → evidence file.
  Commit: Y | "Add batched OpenRouter embedding service"

- [x] 15. Add Chroma VerseStore and corpus ingest pipeline
  What to do / Must NOT do: Create `src/services/vectordb/__init__.py` and `src/services/vectordb/store.py`: `class VerseStore` wrapping `chromadb.PersistentClient(path='data/chroma')`; `get_or_create_collection(name, metadata={"hnsw:space": "cosine"})`; `upsert_verses(collection_name, ids, documents, metadatas, embeddings)` using `chromadb.utils.batch_utils.create_batches(api=self.client, ids=..., documents=..., metadatas=..., embeddings=...)` and `collection.upsert(...)` per batch (idempotent re-runs); `count(name)`; `query(name, query_embeddings, n_results)`. Create `scripts/ingest_corpus.py`: for each translation in `data/bible/manifest.json`: flatten verses to `ids` (`{SLUG}-{OSIS}-{chapter}-{verse}`, e.g. `KJV-Gen-1-1`), `documents` (verse text), `metadatas` (`{book, osis, chapter:int, verse:int, translation}`); embed via `EmbeddingService.embed_texts(record=False, chunk_size=256)`; `upsert_verses`; assert `store.count(coll) == manifest[slug]['verses']`; only then write ONE `corpus_ingest` message via `BaseService.record_message` (dedicated session `db.create_session('corpus-ingest', created_by='pipeline')`, `unique_prompt` = JSON `{translation, verses, collection}`, `raw_response` = `{status:"ok", dimension:1536}`). Support `--translation kjv` flag for single-translation runs and `--max-batches N` for failure testing. Must NOT use `collection.add` (duplicate-id errors on re-run); no per-chunk message rows; expect ~243 embedding calls (~62k verses/256) — print progress every 10 batches.
  Parallelization: Wave 3 | Blocked by: 13,14 | Blocks: 16
  References: chroma batching https://cookbook.chromadb.dev/strategies/batching/ (`create_batches`, `client.max_batch_size`), HNSW config https://cookbook.chromadb.dev/core/configuration/; manifest from todo 13; D6(f) upsert idempotency (Metis #9).
  Acceptance criteria: `.venv/bin/python scripts/ingest_corpus.py` exits 0; `.venv/bin/python -c "import chromadb; c=chromadb.PersistentClient(path='data/chroma'); print(c.get_collection('kjv_verses').count(), c.get_collection('web_verses').count())"` prints the two manifest counts; RE-RUN ingest → counts unchanged; `sqlite3 data/chat_database.db "SELECT message_type_slug, COUNT(*) FROM messages WHERE message_type_slug='corpus_ingest' GROUP BY 1"` shows one row per successful ingest run; semantic check: embed "love your enemies" via the service, query `kjv_verses` top-5 → assert any of Matthew 5:44, Luke 6:27, Luke 6:35 among hits (print all 5 references).
  QA scenarios: happy = full acceptance sequence → `.omo/evidence/task-15-hyde-retrieval-pipeline.txt`. failure = `--max-batches 1` run → NO new `corpus_ingest` row and partial count; then full re-run → count complete (proves resume) → evidence file.
  Commit: Y | "Add Chroma verse store and corpus ingest pipeline"

- [x] 16. Add RetrievalService with async multi-collection queries and offline test
  What to do / Must NOT do: Create `src/services/retrieval/__init__.py` and `src/services/retrieval/service.py`: `class RetrievalService(BaseService)` taking `embedding_service` and `verse_store` via constructor. `async def search(self, hyde_docs: List[Dict[str, Any]], session_uuid: str, top_k: int=10, translations=('kjv','web')) -> List[Dict[str, Any]]`: (a) one `embedding_service.embed_texts([d['hyde_document'] for d in hyde_docs if d['hyde_document']], session_uuid=session_uuid, record=True)` call (ONE `embedding_generation` row); (b) for each (doc, translation) pair, `await asyncio.to_thread(self.store.query, f"{t}_verses", [emb], top_k)` via `asyncio.gather`; (c) return `[{'intent_id', 'doc_index', 'translation', 'hits': [{'id', 'text', 'reference': f"{book} {chapter}:{verse}", 'distance'}]}]` sorted by distance ascending. Offline test `scripts/test_retrieval_service.py`: temp-dir Chroma with 30 fake verses embedded via deterministic stub `embed_fn` (craft it so a designated query doc hashes to the same vector as a designated verse → that verse must rank top-1); fixture DB via `GlobalReferenceCache.reset(...)`; assert result structure, reference formatting, and ordering; MUST pass with OPENROUTER_API_KEY unset (proves no network). Must NOT implement any RRF/rerank/merge logic (out of scope); must NOT call the live API in the offline test.
  Parallelization: Wave 4 | Blocked by: 12,14,15 | Blocks: 17
  References: chroma sync-client + `asyncio.to_thread` pattern (librarian research; https://cookbook.chromadb.dev/core/clients/); hyde doc shape from todo 12; Metis #8 stub strategy.
  Acceptance criteria: `.venv/bin/python scripts/test_retrieval_service.py` exits 0 with OPENROUTER_API_KEY unset, including the top-1 planted-match assertion.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-16-hyde-retrieval-pipeline.txt`. failure = query against an empty fixture collection → service returns empty hits list (no exception) → evidence file.
  Commit: Y | "Add async retrieval service for HyDE documents"

- [x] 17. Add pipeline orchestrator and CLI runner
  What to do / Must NOT do: Create `src/services/pipeline/__init__.py` and `src/services/pipeline/runner.py`: `@dataclass PipelineResult {session_uuid, query, intents, hyde_docs, results}`; `class PipelineRunner(BaseService)` composing `IntentService`, `HydeService`, `EmbeddingService`, `VerseStore`, `RetrievalService` (shared `db_path`); `async def run(self, query: str, top_k: int=10) -> PipelineResult`: create session (`db.create_session(f"pipeline: {query[:60]}", created_by="pipeline")`) → `generate_intents` → `generate_for_intents` → `search` → return result; print a summary (intents count, docs count, top-3 hits per doc per translation with references). Create `scripts/run_pipeline.py`: argparse positional `query`, `--top-k` (default 10), `--translations` (default `kjv,web`); `dotenv.load_dotenv()`; `asyncio.run(...)`; non-zero exit on pipeline failure. Must NOT modify `main.py`; must NOT use `sync_call_api`/`get_event_loop().run_until_complete` inside `asyncio.run` (call the async methods directly).
  Parallelization: Wave 4 | Blocked by: 16 | Blocks: 18
  References: todos 9,12,14,15,16 service contracts; `src/services/llm/wrapper.py:201-216` (the sync anti-pattern to avoid); session creation pattern `src/main.py:43-54`.
  Acceptance criteria: `set -a; . ./.env; set +a; .venv/bin/python scripts/run_pipeline.py "what does the Bible say about anxiety" --top-k 5` exits 0 and prints intents, hyde count, and verse references from BOTH translations.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-17-hyde-retrieval-pipeline.txt`. failure = run with `OPENROUTER_API_KEY` unset → non-zero exit, clear error, and an `error`-recorded message row for the intent call (verify via sqlite3) → evidence file.
  Commit: Y | "Add pipeline orchestrator and CLI runner"

- [x] 18. Add live end-to-end pipeline integration test
  What to do / Must NOT do: Create `tests/system/test_pipeline_e2e.py` (skip loudly without key or when `data/chroma` collections have < 30000 verses): run `PipelineRunner.run("why do bad things happen to good people", top_k=5)`; assert: (a) 1–5 intents; (b) hyde docs == intents count; (c) results non-empty for BOTH `kjv` and `web`; (d) every hit `reference` matches `r"^\w+ \d+:\d+$"`; (e) session message audit via `db.get_messages_by_session_and_type(session_uuid)`: exactly 1 `intent_generation` row, N `hyde_generation` rows, 1 `embedding_generation` row, and ZERO rows whose slug is absent from `ref_message_types` (orphan check); (f) print the top hit per translation as evidence. Must NOT mock anything (this is the live proof); no second query (cost discipline).
  Parallelization: Wave 4 | Blocked by: 17 | Blocks: 20
  References: D5 recording rule; `src/services/sqlite/database.py:159-208` (message audit query); todo 15 (collection counts).
  Acceptance criteria: `set -a; . ./.env; set +a; .venv/bin/python tests/system/test_pipeline_e2e.py` exits 0.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-18-hyde-retrieval-pipeline.txt`. failure = the orphan-check assertion is exercised by construction (any FK-off regression or unseeded slug fails the test) — plus a deliberate negative: point the audit at a session containing a seeded bogus row in a fixture DB and assert the check flags it → evidence file.
  Commit: Y | "Add end-to-end pipeline integration test"

- [x] 19. Add consolidated offline step tests for pipeline services
  What to do / Must NOT do: Create `scripts/test_pipeline_offline.py` covering: (a) `AIMessage.get_parsed_response` against both new schemas with markdown-fenced JSON, leading/trailing prose, and `confidence: 1.5` (must fail); (b) `LLMWrapper` retry with mocked `_call_api_async`: 2 failures then success → `num_tries == 3` and one success row; persistent failure → `MaxRetriesExceededError` + error row (fixture DB via cache reset); (c) `EmbeddingService` retry equivalence; (d) HyDE partial-failure: one intent raises, others succeed → results contain error entry, no exception, error row present; (e) intent schema boundary: 1-intent and 5-intent fixtures pass, 0 and 6 fail. All offline (key unset), fixture DBs/collections in temp dirs. Must NOT duplicate the live tests; keep runtime < 60s.
  Parallelization: Wave 4 | Blocked by: 12,15 | Blocks: none
  References: `src/services/llm/aimessage.py:44-69` (extraction branches); `scripts/test_llm_framework.py` (mocking precedent); todos 8,11,12,14 contracts.
  Acceptance criteria: `.venv/bin/python scripts/test_pipeline_offline.py` exits 0 with OPENROUTER_API_KEY unset.
  QA scenarios: happy = acceptance run → `.omo/evidence/task-19-hyde-retrieval-pipeline.txt`. failure = each negative fixture (invalid confidence, 0/6 intents, persistent retry failure) fails in the asserted way (the test itself encodes them) → evidence file.
  Commit: Y | "Add consolidated offline step tests for pipeline services"

- [x] 20. Update architecture documentation for the new pipeline
  What to do / Must NOT do: Update `architecture/implementation-status.md` (intent generation ✅, HyDE ✅, embeddings ✅, retrieval ✅ with locations), `architecture/README.md` (pipeline steps 2–4 marked implemented; directory structure adds `services/base.py`, `services/intent/`, `services/hyde/`, `services/embeddings/`, `services/vectordb/`, `services/retrieval/`, `services/pipeline/`), create `architecture/pipeline-hyde-retrieval.md` (component doc: message types + schemas, service contracts, data flow query→intents→hyde→embeddings→chroma results, commands to run tests/CLI, cost notes), `todo.md` (check off completed Phase 2/5 items: intent service, HYDE schema+prompt; leave the rest), `LLM_FRAMEWORK.md` (note `LLMWrapper` is the canonical recorded path; list the 4 new message types), `AGENTS.md` Code Structure section (new services). Must NOT edit `README.md` (user's uncommitted rework); must NOT mark steps 5–13 as done.
  Parallelization: Wave 4 | Blocked by: 18 | Blocks: none
  References: `architecture/implementation-status.md`, `architecture/README.md`, `todo.md:13-35`, `LLM_FRAMEWORK.md`, `AGENTS.md` (Code Structure section).
  Acceptance criteria: `grep -l "hyde_generation" architecture/*.md LLM_FRAMEWORK.md` returns at least 2 files; `grep -l "RetrievalService\|retrieval" architecture/implementation-status.md` non-empty; docs name all 6 new service modules.
  QA scenarios: happy = acceptance greps → `.omo/evidence/task-20-hyde-retrieval-pipeline.txt`. failure = `git diff --name-only` for this commit contains ONLY the 6 doc files (no code, no README.md) → evidence file.
  Commit: Y | "Document HyDE retrieval pipeline architecture"

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit
- [x] F2. Code quality review
- [x] F3. Real manual QA
- [x] F4. Scope fidelity

## Commit strategy
- **One commit per todo** (user requirement: "commit each step"), made only after that todo's acceptance criteria AND both QA scenarios pass with evidence written.
- **Stage explicit paths only**: `git add -- requirements.txt` style. FORBIDDEN: `git add -A`, `git add .`, `git commit -a`.
- **Never stage**: `.env`, `data/*.db`, `data/bible/`, `data/chroma/`, `.venv/`, `README.md`, `.gitignore` (both carry the user's uncommitted changes), `.omo/`, `.opencode/`, `opencode.json`.
- **Message style**: freeform sentence-case imperative matching `git log` (e.g. "Add HyDE generation service with asyncio parallel calls", "Fix ref_message_types JOINs and remove dead code"). No conventional-commit prefixes.
- Todo 2 produces no commit (no versioned file changes). All other todos = exactly 1 commit.
- The pre-existing dirty worktree (`.gitignore`, `README.md` modified; `.omo/`, `.opencode/`, `opencode.json` untracked) is the user's pending work: leave it untouched and uncommitted throughout.

## Success criteria
1. **End-to-end**: `.venv/bin/python scripts/run_pipeline.py "<biblical question>"` prints 1–5 structured intents, one HyDE document per intent, and top-K verse references from BOTH the KJV and WEB collections, exiting 0 (proven live in todo 17 and re-proven in todo 18).
2. **Recording**: for any pipeline session, `messages` contains exactly 1 `intent_generation` + N `hyde_generation` + 1 `embedding_generation` rows, all FK-linked to seeded `ref_message_types` slugs, zero orphan slugs (todo 18 audit).
3. **Corpus**: `data/bible/manifest.json` validates 66 books and 30,000–32,000 verses per translation; Chroma `kjv_verses`/`web_verses` counts match the manifest exactly; re-running ingest changes nothing (idempotent upsert); the "love your enemies" semantic check returns a Synoptic parallel (Matt 5:44 / Luke 6:27 / Luke 6:35) in the top 5.
4. **Tests green**: every `scripts/test_*.py` offline suite passes with `OPENROUTER_API_KEY` unset; every `tests/system/` live test passes with the key loaded; `scripts/test_parser.py` and `scripts/test_llm_framework.py` (pre-existing) still pass.
5. **Data layer**: no `JOIN message_types` remains in `database.py`; `PRAGMA foreign_keys = ON` is active (bogus-slug insert raises `IntegrityError`); `data/chat_database.db.pre-pipeline.bak` exists; `main.py` REPL still runs against the unchanged `intent_classification` row.
6. **Commits**: `git log --oneline` shows one freeform commit per completed todo; `git status` shows the user's pre-existing changes preserved and none of the forbidden paths staged.
7. **Final verification wave**: F1–F4 all APPROVE before completion is declared.
