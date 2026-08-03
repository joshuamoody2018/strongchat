# StrongChat Pipeline Architecture

## 13-Step Pipeline Overview

1. **Input** — User's raw text
2. ✅ **Intent Generation** — LLM produces N candidate topic/theme framings (auditable inference point)
3. ✅ **HyDE Generation** — M hypothetical passages per intent (N×M total documents)
4. ✅ **Parallel Retrieval** — Embed each HyDE doc, search against English translations, top-K per doc
5. **RRF Level 1** — Merge/rerank M result sets within each intent → one ranked list per intent
6. **RRF Level 2** — Merge/rerank N per-intent lists → single candidate verse set
7. ✅ **Macula Lookup** — Pull lemma/Strong's data for candidate set (NT: Macula Greek, OT: TBD)
8. **Graph Expansion** — Lemma-based/verse-graph traversal for cross-references
9. ✅ **Re-rank/Organize** — Consolidate steps 6-8 into structured retrieval set
10. **Synthesis** — Frontier model answers using retrieval + original prompt, citations linked
11. **Evaluator** — Fresh LLM checks completeness, loops back to step 2/3 if insufficient
12. **Validator** — Programmatic + Bible-trained LLM fact-check, strips unsupported claims
13. **Response** — Final response to user

## Core Principle

**English carries semantic search (steps 3-6), original language carries support/grounding (steps 7-8)** — not the other way around.

## Implementation Status

### ✅ Implemented Components

#### LLM Framework (`src/services/llm/`)
- **Status**: ✅ Complete
- **Location**: `src/services/llm/`
- **Components**:
  - Async LLM wrapper (`LLMWrapper`) with aiohttp
  - JSON schema validation
  - Exponential backoff retry (3 max)
  - Error routing to stderr
  - Response parser with validation (`AIMessage`, `parse_response`)
- **Testing**: ✅ 6/6 parser tests passing, offline/online service tests passing
- **Documentation**: ✅ Comprehensive docs in `LLM_FRAMEWORK.md`

#### Database Layer (`src/services/sqlite/`)
- **Status**: ✅ Complete
- **Location**: `src/services/sqlite/`
- **Components**:
  - Chat session management
  - Message storage with `ref_message_types` FK
  - Intent tracking (structured)
  - Foreign-key enforcement enabled per connection
- **Testing**: ✅ CRUD operations validated, migration tests passing
- **Database**: ✅ Schema implemented and tested

#### Configuration System
- **Status**: ✅ Complete
- **Location**: `src/config/`
- **Components**:
  - JSON schemas for response validation (`schemas.py`)
  - Pipeline-agnostic prompt templates (`prompts.py`)
  - Centralized configuration management

#### Intent Generation Service (`src/services/intent/`)
- **Status**: ✅ Complete
- **Location**: `src/services/intent/`, `src/config/schemas.py`, `src/config/prompts.py`
- **Components**:
  - `IntentService.generate_intents(query, session_uuid)`
  - `INTENT_GENERATION_SCHEMA` with 1-5 intents, `keywords_explicit`, `keywords_inferred`, `themes`, `is_primary`
  - Records one `intent_generation` message per call
- **Testing**: ✅ Offline mocked test + live system test passing

#### HyDE Generation Service (`src/services/hyde/`)
- **Status**: ✅ Complete
- **Location**: `src/services/hyde/`
- **Components**:
  - `HydeService.generate_for_intents(intents, session_uuid)`
  - `HYDE_GENERATION_SCHEMA` (`hyde_document` string, min length 50)
  - Bias-isolated prompt: receives only one serialized intent, never the original query
  - Parallel generation via `asyncio.gather`, per-intent failure capture
- **Testing**: ✅ Offline and live tests passing

#### Embeddings Service (`src/services/embeddings/`)
- **Status**: ✅ Complete
- **Location**: `src/services/embeddings/`
- **Components**:
  - `EmbeddingService.embed_texts(texts, session_uuid, record, chunk_size)`
  - Batched OpenRouter `/v1/embeddings` calls (default chunk size 256)
  - Retry/backoff for transient `APITimeoutError` / `APIConnectionError`
  - Records one summary `embedding_generation` message per call (no raw vectors)
- **Testing**: ✅ Offline tests passing

#### Verse Store / Corpus Ingest (`src/services/vectordb/`, `scripts/ingest_corpus.py`)
- **Status**: ✅ Complete
- **Location**: `src/services/vectordb/`, `scripts/ingest_corpus.py`
- **Components**:
  - `VerseStore` wrapper around `chromadb.PersistentClient`
  - Cosine HNSW collections (`kjv_verses`, `web_verses`)
  - Idempotent upsert via `create_batches` + `collection.upsert`
  - `corpus_ingest` summary message recorded after each translation ingest
- **Testing**: ✅ Full KJV + WEB ingest verified, semantic check passes

#### Retrieval Service (`src/services/retrieval/`)
- **Status**: ✅ Complete
- **Location**: `src/services/retrieval/`
- **Components**:
  - `RetrievalService.search(hyde_docs, session_uuid, top_k, translations)`
  - Embeds valid HyDE docs in one `embedding_generation` call
  - Fans out Chroma queries across `(doc, translation)` pairs via `asyncio.gather`
  - Returns structured hits with `id`, `text`, `reference`, `distance`
- **Testing**: ✅ Offline tests passing

#### Pipeline Orchestrator (`src/services/pipeline/`, `src/main.py`)
- **Status**: ✅ Complete
- **Location**: `src/services/pipeline/`, `src/main.py`
- **Components**:
  - `PipelineRunner` composes `IntentService`, `HydeService`, `EmbeddingService`, `VerseStore`, `RetrievalService`
  - `PipelineResult` dataclass with `session_uuid`, `query`, `intents`, `hyde_docs`, `results`
  - CLI runner: `src/main.py`
- **Testing**: ✅ Live end-to-end test passing

#### Context Retrieval (`src/services/context/`)
- **Status**: ✅ Complete (committed 2026-08-02)
- **Location**: `src/services/context/`
- **Message type**: `context_retrieval` (programmatic, summary schema)
- **Test files**: `tests/scripts/test_context_retrieval_service.py`, `tests/scripts/test_context_retrieval_offline.py`, `tests/system/test_context_retrieval_e2e.py`
- **Score formula**: `composite_score(pos_weight, frequency_count, sense_count) = pos_weight * log1p(1/frequency_count) * log1p(sense_count)`
- **KNOWN LIMITATION**: the `gloss` field on each kept_word is empty because the `macula_tokens` SQLite schema does not include the `gloss` column from the canonical TSV.

### 📋 Planned Components

#### RRF Implementation
- **Status**: 📋 Planned
- **Location**: `src/services/rrf/` (planned)
- **Requirements**:
  - Intra-intent ranking (step 5)
  - Cross-intent merging (step 6)
  - Score normalization and fusion

#### Synthesis, Evaluation, and Validation
- **Status**: 📋 Planned
- **Requirements**:
  - Response synthesis (step 10)
  - Evaluator loop (step 11)
  - Fact validation (step 12)
  - Final response (step 13)

## Setup

Run the setup script to create a Python environment and ingest all data:

```bash
bash scripts/setup_environment.sh
```

## Detailed Documentation

See [architecture reference](reference.md) for component details and integration points.

- [LLM Framework](llm-framework.md) - Structured LLM interactions
- [Database](database.md) - Data storage and operations
- [HyDE Retrieval Pipeline](pipeline-hyde-retrieval.md) - HyDE + retrieval pipeline (steps 2-4)
- [Context Retrieval Pipeline](pipeline-context-retrieval.md) - Context retrieval pipeline (steps 7, 9)
- [Implementation Status](implementation-status.md) - Current progress tracking
- [Reference Guide](reference.md) - Agent workflow and integration
