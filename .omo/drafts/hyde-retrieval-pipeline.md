---
slug: hyde-retrieval-pipeline
status: plan-complete
intent: clear
review_required: false
pending-action: handoff delivered; awaiting user choice — start work (e.g. /start-work hyde-retrieval-pipeline) or dual high-accuracy review first
approach: Extend the DB-driven LLMWrapper path (records every call in messages linked to ref_message_types) into per-step services; refine intent generation to emit N structured intents; add HyDE generation (asyncio parallel, M=1/intent), bulk embeddings, and local ChromaDB verse retrieval over KJV + one modern public-domain translation; orchestrator + integration/step tests; one commit per todo.
---

# Draft: hyde-retrieval-pipeline

## Components (topology ledger)
<!-- id | outcome (one line) | status | evidence path -->
- C1 groundwork-env | pip/venv decided; dependency manifest exists; chromadb installed; .git/info/exclude covers new data dirs (never .gitignore — user-dirty) | active | no requirements/pyproject anywhere (conventions report §1)
- C2 data-layer-repair | message-type table naming unified (ref_message_types); JOIN bugs fixed; ref rows seeded for all slugs in use + new pipeline steps; enums.py dead-code bug resolved | active | src/services/sqlite/database.py:136,175,185 JOIN on `message_types` but live table is `ref_message_types`
- C3 intent-generation | refined intent schema+prompt live-tested end-to-end; emits N structured intents ready to prompt HyDE; call recorded in messages | active | src/config/schemas.py:3-64 (INTENT_CLASSIFICATION_SCHEMA), :66-121 (INTENT_DISAMBIGUATION_SCHEMA); live DB seeds = trivial greeting/question schema
- C4 hyde-generation | hyde service generates 1 HyDE doc per intent via asyncio.gather; each call recorded as its own messages row with hyde slug | active | src/services/hyde/ ABSENT; prompts.py:44-47 commented stub only
- C5 bible-corpus-embeddings | KJV + second translation downloaded, verse-count-validated, embedded per-verse, ingested into local Chroma PersistentClient | active | midvash/bible-data verified (github.com/midvash/bible-data: en/kjv + en/web, public domain, JSON/SQLite, OSIS)
- C6 retrieval-orchestrator-tests | per-HyDE-doc async queries against both translation collections, top-K results; orchestrator runs C3→C4→C6 for one query; integration + step tests green | active | no orchestrator exists; tests/system/* pattern is the live-test convention

## Open assumptions (announced defaults)
<!-- assumption | adopted default | rationale | reversible? -->
- Canonical LLM path | LLMWrapper (DB-driven) canonical; extract shared base class per user's abstraction request; LLMClient (client.py) stays unused/deprecated | only wrapper records messages (user requirement); client.py already unused by production | yes
- Second translation | WEB (World English Bible 2000) alongside KJV | public domain, modern English (better embedding match), same midvash source/schema as KJV | yes (re-ingest another translation)
- Model per step | openai/gpt-4.1-mini for intent_generation and hyde_generation ref rows | user already set MODEL_SLUG_INTENTS=openai/gpt-4.1-mini in .env:3; cheap; changeable per DB row | yes
- N and M | N model-decided 1-5 per schema maxItems; M=1 HyDE doc per intent | user explicitly said "1 hyde document for each intent"; schemas.py:56 maxItems 5 | yes
- Chroma layout | one collection per translation (kjv_verses, web_verses), cosine HNSW, metadata book/chapter/verse/translation/osis | clean per-translation querying; librarian research; 31k vectors trivial for HNSW | yes
- Data locations | data/bible/ (raw texts), data/chroma/ (vector store), both excluded via .git/info/exclude (NOT .gitignore, which carries uncommitted user changes) | data/ already holds chat_database.db; *.db ignored at .gitignore:38-41 but new dirs need entries | yes
- Orchestrator home | new src/services/pipeline/ + scripts/run_pipeline.py CLI; main.py untouched | matches one-package-per-service layout; avoids destabilizing the REPL demo | yes
- messages schema | reuse existing 9 columns (no DDL change); record request payload text in unique_prompt, raw API content in raw_response | current schema already satisfies "record every call linked to ref_message_type" | yes
- Commit cadence | one commit per todo, freeform sentence-case style matching git log | user: "commit each step"; git log shows freeform style | n/a

## Findings (cited - path:lines)
- Two parallel LLM clients exist: LLMClient (src/services/llm/client.py:20, pure HTTP, hardcoded gpt-3.5-turbo default at :125, NO DB persistence, not exported in services/llm/__init__.py, unused by production) vs LLMWrapper (src/services/llm/wrapper.py:20, DB-driven model/temperature/settings from ref_message_types, records every call via create_message_with_type at :105,:125,:138, used by src/main.py:10,29,99).
- Live DB (data/chat_database.db): 3 tables — sessions, ref_message_types (11 cols incl. prompt_template added out-of-band), messages (9 cols). 2 ref rows: intent_classification (trivial greeting/question/confidence schema, has prompt_template), intent_disambiguation (rich 2-5 framings schema, prompt_template NULL). 30 messages, 11 sessions, all test data.
- Bugs: (1) database.py:136,175,185 JOIN `message_types` — table is `ref_message_types` (wrong-table JOIN). (2) scripts/create_new_database.py:33 and scripts/populate_message_types.py:120 create/insert `message_types`, not `ref_message_types` — re-running them breaks the runtime. (3) src/config/enums.py:22-25 LEGACY_MESSAGE_MAPPING references MessageType.INITENT_CLASSIFICATION (typo) → AttributeError at import; file imported nowhere (grep-verified) so latent. (4) scripts/test_main.py:13 imports get_message_intent/call_openrouter_api — removed from main.py; broken. (5) intents table referenced by database.py:243,299 but absent in live DB. (6) FK pragma OFF; orphan slugs human_input/llm_response/error written by main.py:136-165 without ref rows.
- Prompt propagation is OK on the wrapper path: GlobalReferenceCache loads via get_active_message_types (database.py:210-241) which DOES return prompt_template (cache.py:35-40). db.get_message_type (singular, :60-91) omits prompt_template but is not on the cache path.
- .env (gitignored): OPENROUTER_API_KEY set; MODEL_SLUG_INTENTS=openai/gpt-4.1-mini set but never read in code (grep-verified); DB rows currently point at openai/gpt-3.5-turbo.
- No requirements.txt/pyproject/venv; deps via apt (aiohttp 3.9.1, jsonschema 4.10.3, requests); pytest, python-dotenv, chromadb, sentence-transformers NOT installed; Python 3.12.3; sqlite3 CLI 3.45.1 present; node ABSENT; bun present.
- Tests: scripts/ unittest-as-script (test_parser.py green no-key, test_llm_framework.py green mocked, test_main.py broken); tests/ TestCase style + tests/system/* live-API tests (need key). No pytest installed despite tests/README.md documenting it.
- Git: branch dev; dirty worktree (.gitignore +43 lines modified, README.md rewritten, untracked .omo/, .opencode/, opencode.json) — record as dirty_worktree risk; user's uncommitted changes must NOT be overwritten; additive-only .gitignore edits.
- External (librarian, URLs in research notes): Chroma PersistentClient is sync-only → wrap in asyncio.to_thread; chromadb.utils.batch_utils.create_batches for bulk adds; HNSW cosine config; midvash/bible-data VERIFIED by direct fetch (en/kjv, en/web public domain, JSON+SQLite, OSIS, 66 books); fallback scrollmapper/bible_databases. Embedding options: chromadb built-in ONNX MiniLM-L6-v2 (zero extra heavy deps), sentence-transformers bge-small (quality, torch dep), OpenRouter embeddings API (batch input, ~$0.03 for corpus).

## Decisions (with rationale)
- D1 intent schema = ONE refined `intent_generation` message type. Per-intent fields: intent_id, interpretation, keywords_explicit (verbatim from prompt), keywords_inferred (model-inferred), themes, confidence, is_primary; plus query_analysis block; minItems 1 / maxItems 5. User-directed additions: split keywords explicit/inferred, add themes. Evolves INTENT_CLASSIFICATION_SCHEMA; supersedes INTENT_DISAMBIGUATION_SCHEMA (legacy, kept unused). One LLM call → one recorded message.
- D2 embeddings = OpenRouter `openai/text-embedding-3-small` (1536-dim) via existing OpenRouter account, batch input arrays. Cost verified negligible (~$0.06 corpus one-time, fractions of a cent per query). User chose this over local; chromadb built-in ONNX MiniLM documented as fallback only (not built). Corpus ingest and query-time embedding MUST use this same model.
- D3 install = project venv `.venv` + pinned `requirements.txt`; all run/test commands use `.venv/bin/python`; first todo verifies python3-venv/pip availability (apt python3.12-venv if missing).
- D4 tests = tests-after in same todo; offline unittest-style tests (scripts/ pattern) + live system tests (tests/system/ pattern) run with `.venv/bin/python`; no pytest.
- D5 LLM-call recording rule: every query-time OpenRouter call (intent ×1, hyde ×N, embedding ×1) recorded as its own messages row with its ref_message_types slug, sharing the query's session_uuid. One-time corpus ingest batch recorded as ONE summary row (slug `corpus_ingest`), not 62k rows. embedding_generation rows store a SUMMARY (model, dim, count, input texts) in raw_response — never raw vectors (~100KB+/query bloat, Metis #10).
- D6 (Metis folds): (a) intent_classification stays is_active=1 — main.py:99-103 depends on it (Metis #2); intent_disambiguation set is_active=0 (superseded, zero callers). (b) Migration split: W2 seeds only human_input/llm_response/error/embedding_generation/corpus_ingest; intent_generation upserted in the W3 schema todo, hyde_generation in the W4 schema todo (Metis #1). (c) FK pragma + orphan-slug seeds land in ONE commit; legacy orphan rows accepted, no backfill (Metis #7). (d) sqlite3 .backup of chat_database.db before any migration (Metis #4). (e) GlobalReferenceCache gains optional db_path + reset() for fixture tests; refresh_cache() after migrations (Metis #6). (f) Corpus ingest uses collection.upsert for idempotent re-runs; summary row only after count verification (Metis #9). (g) Prompt templates must contain only `{query}`; literal braces doubled `{{`/`}}` (Metis #11). (h) New ignore entries go to .git/info/exclude, never the dirty .gitignore (Metis #3). (i) Offline retrieval tests use an injected deterministic embedding stub + fixture DB (Metis #8).

## Scope IN
- Test + refine intent generation to emit N structured intents (C3)
- HyDE generation service, asyncio parallel, 1 doc per intent (C4)
- Bulk embeddings for HyDE docs and for the verse corpus (C5)
- Local ChromaDB: install, ingest KJV + one more English translation per-verse, query per HyDE doc (C5, C6)
- Every LLM call recorded in messages linked to ref_message_types (C2, all services)
- Data-layer repair needed to support the above (C2)
- Dependency manifest + install (C1)
- Integration tests for the pipeline + step tests where they pay for themselves (C3-C6)
- One commit per todo

## Scope OUT (Must NOT have)
- RRF levels 1-2, Macula, graph expansion, synthesis, evaluator, validator (pipeline steps 5-13)
- Reranking/cross-encoder
- Web server / Quart API
- User conversation history in prompts (each LLM call gets only its own task context)
- Migrating/rewriting main.py REPL demo (left as-is)
- Deleting or rewriting user's uncommitted README/.gitignore changes (dirty_worktree guard)
- GPU/torch-heavy infra unless user picks sentence-transformers
- Production hardening: caching TTL, rate limiting, monitoring (todo.md deferred list)

## Open questions
(none — all resolved: D1-D4)

## Approval gate
status: approved → plan written
plan: .omo/plans/hyde-retrieval-pipeline.md (20 implementation todos + F1-F4; structural self-check passed: headers in template order, all rows column-zero, 20/20 acceptance+QA+evidence+commit fields)
metis: 11 findings, all folded (see D6)
next workflow action: user picks start-work vs high-accuracy review.
