# StrongChat Architecture

## Overview

StrongChat is a biblical search system using LLMs with two-level RRF (Reciprocal Rank Fusion) and an evaluator loop for comprehensive verse retrieval and answer synthesis.

## Pipeline Architecture

### 13-Step Pipeline

1. **Input** — User's raw text
2. ✅ **Intent Generation** — LLM produces N candidate topic/theme framings (auditable inference point)
3. ✅ **HyDE Generation** — M hypothetical passages per intent (N×M total documents)
4. ✅ **Parallel Retrieval** — Embed each HyDE doc, search against English translations, top-K per doc
5. **RRF Level 1** — Merge/rerank M result sets within each intent → one ranked list per intent
6. **RRF Level 2** — Merge/rerank N per-intent lists → single candidate verse set
7. ✅ **Macula Lookup** — Pull lemma/Strong's data for candidate set (NT: Macula Greek, OT: Macula Hebrew WLC)
8. **Graph Expansion** — Lemma-based/verse-graph traversal for cross-references
9. ✅ **Re-rank/Organize** — Consolidate steps 6-8 into structured retrieval set
10. **Synthesis** — Frontier model answers using retrieval + original prompt, citations linked
11. **Evaluator** — Fresh LLM checks completeness, loops back to step 2/3 if insufficient
12. **Validator** — Programmatic + Bible-trained LLM fact-check, strips unsupported claims
13. **Response** — Final response to user

## Core Principle

**English carries semantic search (steps 3-6), original language carries support/grounding (steps 7-8)** — not the other way around.

## Current Implementation Status

### ✅ Implemented Components

#### LLM Framework (`src/services/llm/`)
- **Purpose**: Structured LLM interactions with JSON validation
- **Key Features**:
  - Exponential backoff retry logic (3 max retries)
  - Async support with aiohttp
  - JSON schema validation for responses
  - Error routing to stderr
  - Type-safe response models
- **Location**: `/llm-framework.md`
- **Test Status**: ✅ Parser tests passing

#### Database Layer (`src/services/sqlite/`)
- **Purpose**: SQLite database operations
- **Components**:
  - Chat session management
  - Message storage
  - Foreign-key enforcement
  - Intent tracking (structured)
- **Location**: `services/sqlite/database.py`

#### Configuration (`src/config/`)
- **Purpose**: Centralized schemas and prompts
- **Components**:
  - JSON schemas for response validation
  - Pipeline-agnostic prompt templates
- **Location**: `/llm-framework.md`

#### Intent Generation Service (`src/services/intent/`)
- **Purpose**: Plain-language query disambiguation (step 2)
- **Status**: ✅ Implemented
- **Key Files**: `src/services/intent/service.py`, `src/config/schemas.py`, `src/config/prompts.py`
- **Key Requirements**:
  - Zero biblical vocabulary in intent analysis
  - Multiple interpretive framings per query
  - Structured output for HyDE generation

#### HyDE Generation Service (`src/services/hyde/`)
- **Purpose**: Hypothetical document generation (step 3)
- **Status**: ✅ Implemented
- **Key File**: `src/services/hyde/service.py`
- **Requirements**:
  - Biblical prose generation
  - N×M structure (N intents × M passages each)
  - Bias-isolated prompts (only intent data, never the original query)

#### Embeddings Service (`src/services/embeddings/`)
- **Purpose**: Batched embedding generation for HyDE docs and corpus
- **Status**: ✅ Implemented
- **Key File**: `src/services/embeddings/service.py`
- **Key Features**:
  - Batched OpenRouter `/v1/embeddings` calls
  - Retry/backoff for transient errors
  - Summary-only recording (no raw vectors persisted)

#### Verse Store / Corpus Ingest (`src/services/vectordb/`, `scripts/ingest_corpus.py`)
- **Purpose**: ChromaDB-backed storage for Bible verse embeddings
- **Status**: ✅ Implemented
- **Key Files**: `src/services/vectordb/store.py`, `scripts/ingest_corpus.py`
- **Key Features**:
  - Persistent ChromaDB collections (`kjv_verses`, `web_verses`)
  - Cosine HNSW indexing
  - Idempotent upserts

#### Retrieval Service (`src/services/retrieval/`)
- **Purpose**: Embed HyDE docs and query verse collections (step 4)
- **Status**: ✅ Implemented
- **Key File**: `src/services/retrieval/service.py`
- **Key Features**:
  - Single `embedding_generation` call per HyDE set
  - Parallel Chroma queries across `(doc, translation)` pairs
  - Structured hits with reference and distance

#### Pipeline Orchestrator (`src/services/pipeline/`, `src/main.py`)
- **Purpose**: Compose intent → HyDE → retrieval into one runnable flow
- **Status**: ✅ Implemented
- **Key Files**: `src/services/pipeline/runner.py`, `src/main.py`
- **Key Features**:
  - Shared `EmbeddingService` injected into retrieval
  - `PipelineResult` dataclass
  - CLI runner

### 📋 Planned Components

#### RRF Implementation
- **Purpose**: Two-level ranking fusion (steps 5-6)
- **Location**: `src/services/rrf/` (planned)
- **Requirements**:
  - Intra-intent ranking
  - Cross-intent merging
  - Score normalization

#### Macula Integration
- **Purpose**: Original language data lookup (step 7)
- **Greek**: `scripts/download_macula_greek.py` → `scripts/build_macula_index.py --testament greek` (Macula Greek SBLGNT, CC BY 4.0)
- **Hebrew**: `scripts/download_macula_hebrew.py` → `scripts/build_macula_index.py --testament hebrew` (Macula Hebrew WLC, CC BY 4.0)
- **Lexicons**: `scripts/build_lexicon_index.py --testament both` ingests Greek TBESG+LSJ and Hebrew TBESH (all STEPBible CC BY 4.0)
- **Frequencies**: `scripts/build_strongs_frequency.py --testament {greek,hebrew}` writes `strongs_frequency` rows partitioned by `testament='NT'` or `'OT'`
- **Status**: Both testaments implemented and tested end-to-end (offline integration tests under `tests/scripts/test_hebrew_ingest_integration.py` and `tests/scripts/test_context_retrieval_hebrew.py`; live NT context-retrieval regression under `tests/system/test_context_retrieval_e2e.py`)
- **Runtime routing**: `ContextRetrievalService._build_bundle_for_hit` derives `language` from the first token's `book_num` (< 40 Hebrew, >= 40 Greek) and routes all downstream lookups (POS weights, frequency filter, lexicon source filter, occurrence cache) accordingly. See `docs/pipeline-context-retrieval.md` for the routing table.

#### Synthesis, Evaluator, Validator, and Final Response
- **Purpose**: Generate and verify the final answer (steps 10-13)
- **Location**: TBD
- **Status**: 📋 Planned

## Directory Structure

```
src/
├── config/                    # Centralized configuration
│   ├── schemas.py           # JSON schemas
│   └── prompts.py           # Prompt templates
├── services/
│   ├── base.py              # Shared BaseService foundation
│   ├── llm/                 # LLM framework
│   │   ├── wrapper.py       # Async, database-driven LLM client (canonical)
│   │   ├── aimessage.py     # JSON response parser + AIMessage dataclass
│   │   └── exceptions.py    # Error handling
│   ├── sqlite/              # Database operations
│   ├── intent/              # Intent generation service
│   ├── hyde/                # HyDE generation service
│   ├── embeddings/          # Batched embedding service
│   ├── vectordb/            # ChromaDB verse store
│   ├── retrieval/           # HyDE → verse retrieval service
│   ├── context/             # Original-language context retrieval service
│   └── pipeline/            # Pipeline orchestrator
└── main.py                  # Application entry point

data/
└── chat_database.db         # SQLite database

scripts/
├── ingest_corpus.py         # Bible corpus ingest into ChromaDB
└── create_new_database.py   # Database schema creation + ref_message_types seeding

architecture/
├── high-level.md            # This document
├── llm-framework.md         # LLM framework details
├── implementation-status.md # Current progress tracking
└── [component-specific docs]
```

## Key Design Decisions

### 1. Separation of Concerns
- **Schemas vs Prompts**: Completely separate JSON schemas from prompt templates
- **LLM Ignorance**: LLMs only know immediate task, not pipeline context
- **Modular Services**: Each pipeline step is a separate service

### 2. Error Handling Strategy
- **Exponential Backoff**: 3 retries with 1s → 2s → 4s backoff
- **Error Routing**: Validation errors → stderr, API failures → retry → error handler
- **Graceful Degradation**: Fallback logic when API unavailable

### 3. Auditability
- **Structured Logging**: All intent decisions logged with JSON format
- **Separate Steps**: Intent disambiguation separate from HyDE generation
- **Response Models**: Type-safe objects for data consistency

## Next Steps

1. **RRF Implementation** - Two-level ranking system (steps 5-6)
2. **Macula Integration** - Original language data lookup (step 7)
3. **Graph Expansion** - Lemma-based/verse-graph traversal (step 8)
4. **Re-rank/Organize** - Consolidate retrieval set (step 9)
5. **Synthesis** - Frontier model answers with citations (step 10)
6. **Evaluator Loop** - Fresh LLM completeness check (step 11)
7. **Validator** - Programmatic + LLM fact-check (step 12)
8. **Final Response** - Return answer to user (step 13)

## References

- [LLM Framework Documentation](llm-framework.md)
- [High-Level Pipeline Overview](high-level.md)
- [Implementation Status](todo.md)