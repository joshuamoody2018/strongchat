# Database Architecture

> There is **no application database** in the MCP era. This document covers
> the read-only data assets and the JSONL audit log that replaces the
> former SQLite `sessions` / `messages` / `ref_message_types` tables.

## Overview

StrongChat is a stateless MCP server. Nothing persists between calls. The
audit trail is a JSONL log file (cross-process safe via
`concurrent-log-handler`); the returned `PipelineResult` bundle IS the
auditable artifact for the calling agent. Two read-only data assets are
NOT stripped because they are corpus/data, not application state.

## Read-only data assets

### `data/chroma/` — ChromaDB persistent verse vectors

- **Collections**: `kjv_verses`, `web_verses` (cosine HNSW space).
- **Content**: ~31,000 verse rows per translation, each with `text`,
  `book` (English name), `osis`, `chapter`, `verse`, `translation`
  metadata, and the verse embedding vector.
- **Read path**: `VerseStore` (`src/services/vectordb/store.py`) wraps
  `chromadb.PersistentClient`.
- **Ingest**: `scripts/ingest_corpus.py`. Idempotent upsert;
  re-running overwrites existing IDs.

### `data/macula_index.db` — Macula Greek + Hebrew original-language index

A single SQLite database (read-only at runtime), built by the setup
script from the Macula Greek (SBLGNT) and Macula Hebrew (WLC) corpora and
the STEPBible TBESG / LSJ / TBESH lexicons.

#### `macula_tokens`
- **Schema**: `row_id, book_num, book_osis, chapter, verse, word_pos,
  surface, lemma, strongs, morph, pos, gloss`
- **Content**: ~137k NT Greek tokens (book_num ≥ 40) + ~80 MB OT Hebrew
  tokens (book_num < 40)
- **Source**: `scripts/build_macula_index.py --testament {greek,hebrew}`
- **License**: CC BY 4.0 (Macula Greek, Macula Hebrew WLC)

#### `strongs_frequency`
- **Schema**: `strongs_number TEXT PRIMARY KEY, occurrence_count INTEGER,
  testament TEXT NOT NULL` (`testament` is `'NT'` or `'OT'`)
- **Content**: Strong's number → corpus occurrence count, partitioned by
  testament so Greek and Hebrew bare-int keys don't collide.
- **Source**: `scripts/build_strongs_frequency.py --testament {greek,hebrew}`

#### `lexicon_definitions`
- **Schema**: `strongs_number, lexicon_source, sense_index, definition`
  (PK on the triple)
- **Content**:
  - Greek NT: `tbESG` (Tyndale Brief Extended Greek) + `lsj` (Liddell-Scott
    Jones) — union of both, concatenated per sense.
  - Hebrew OT: `tbESH` (Tyndale Brief Extended Hebrew)
- **Source**: `scripts/build_lexicon_index.py --testament {greek,hebrew,both}`
- **License**: CC BY 4.0 (STEPBible)

The `ContextRetrievalService` reads these tables via per-call short-lived
`sqlite3.connect` (per-call to avoid cross-thread issues; opens in <1ms).
The service derives language ('greek' / 'hebrew') from each hit's first
token's `book_num` and routes frequency / lexicon / occurrence-cache
lookups by testament so Greek and Hebrew bare-int Strong's keys do not
conflate.

## Audit trail — JSONL log (no application DB)

The audit trail is the JSONL log file under `data/logs/strongchat.log`
(10 MB rotation × 5 backups). Each record is one JSON object per line,
keyed by `correlation_id` (a per-call UUID used only for log slicing).

### Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `STRONGCHAT_LOG_LEVEL` | `ERROR` (if unset) | One of `ERROR`, `INFO`, `DEBUG` |
| `STRONGCHAT_LOG_FILE` | `data/logs/strongchat.log` | JSONL log path (dir auto-created) |

### Levels

| Level | What lands |
|---|---|
| `ERROR` (default) | exceptions, retry-exhausted, API hard failures |
| `INFO` | one record per pipeline step with `event`, `elapsed_ms`, `status` |
| `DEBUG` | INFO + full audit: `prompt`, `raw_response`, embedded texts, context bundle payloads (same field set as the former `messages` table) |

### Record shape

```json
{"ts":"2026-08-16T12:00:00.123Z","level":"INFO","event":"llm_call","correlation_id":"8f3e...","slug":"intent_generation","attempts":1,"elapsed_ms":420,"status":"ok"}
```

DEBUG-level audit records add `prompt` + `raw_response` fields (the same
`unique_prompt` + `raw_response` columns the former SQLite `messages` table
held). `grep <correlation_id>` or `jq` on a DEBUG log reconstructs the old
audit table per pipeline run.

### Cross-process safety

`ConcurrentRotatingFileHandler` from `concurrent-log-handler` uses
`fcntl` advisory locking + atomic rotation rename. Multiple MCP server
instances (or any parallel Python process) can append safely to the same
JSONL log file regardless of record size.

### Where logging replaces each former DB write

| Former DB write site | Now |
|---|---|
| `LLMWrapper.call_api` success | INFO `llm_call` + DEBUG `llm_call_audit` records |
| `LLMWrapper.call_api` final failure | ERROR `llm_call` record with `error` field |
| `EmbeddingService.embed_texts` INFO summary | INFO `embedding_generation` + DEBUG audit record |
| `ContextRetrievalService._process_intent` summary | INFO `context_retrieval` (intent_id, hit_count, kept_word_count, elapsed_ms, status) + DEBUG audit row carrying full bundles payload |
| `PipelineRunner.run` `create_session` | INFO `pipeline_start` + `pipeline_end` records keyed by `correlation_id` |
| `scripts/ingest_corpus.py` `corpus_ingest` row | INFO `corpus_ingest` record (translation, verse_count, batch_count, elapsed_ms) |

## Static message-type config (no `ref_message_types` table)

The former `ref_message_types` SQLite table is replaced by an in-process
registry of frozen dataclasses:

- `src/config/llm_models.py` — `@dataclass(frozen=True) MessageTypeDef` for
  `intent_generation`, `hyde_generation`, `embedding_generation`,
  `context_retrieval`, `corpus_ingest`, `human_input`.
- `src/config/registry.py` — `MessageTypeDefRegistry` with a process-wide
  singleton built at import time (`DEFAULT_REGISTRY`).

Read-only after import; safe to share across asyncio tasks and worker
threads without locking. Tests that need a fixture registry construct a
new `MessageTypeDefRegistry` (or call `DEFAULT_REGISTRY.reset([...])`).

## Performance considerations

- The `ContextRetrievalService` SQLite reads use per-call short-lived
  connections (each helper opens, queries, closes). SQLite opens in <1ms
  on local disk and the OS-level file lock handles serialization across
  parallel `asyncio.to_thread` calls.
- Embedding vectors are dropped from the serialized bundle returned to the
  agent (too large, redundant downstream of retrieval).
- No SQLite writes per pipeline run (the former one session + N hyde +
  1 embedding + N context inserts per run are gone).

## File Locations

- Config source of truth: `src/config/llm_models.py`, `src/config/registry.py`
- Logging setup: `src/config/logging.py`
- JSONL log file: `data/logs/strongchat.log` (path configurable)
- Chroma assets: `data/chroma/`
- Macula assets: `data/macula_index.db`, `data/macula/*.tsv`
- Macula build scripts: `scripts/build_macula_index.py`,
  `scripts/build_strongs_frequency.py`, `scripts/build_lexicon_index.py`
- Corpus ingest: `scripts/ingest_corpus.py`