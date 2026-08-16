# StrongChat Pipeline Architecture

## 13-Step Pipeline Overview

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

## MCP entry, stateless

The pipeline is exposed as a **stateless MCP server** (`src/server.py`,
FastMCP stdio). The agent (Claude Desktop / opencode / any MCP-compatible
client) drives the retrieve → synthesize → validate loop itself:

1. Agent calls `retrieve_context(query, top_k, translations)` → gets back
   a structured JSON bundle (`correlation_id`, `query`, `query_analysis`,
   per-intent `traces` with `intent_data`, `hyde_document`, per-translation
   `hits` each carrying `reference/text/distance/context_bundle`).
2. Agent synthesizes an answer using that bundle + its own model.
3. Agent calls `validate_answer(answer, context=<same bundle from step 1>)`
   — the server re-checks the answer against that exact context (fact-check,
   strip unsupported claims, completeness).
4. If validation fails: the agent gets back structured feedback
   (`unsupported_claims`, `missing_coverage`, `suggested_refinement`) and
   decides whether to re-call `retrieve_context` with refined/expanded
   intents, then re-synthesize, then re-validate.

Nothing server-side needs to remember anything between calls — each call is
a pure function of its inputs. The agent's context window is what threads
state across the loop; the server doesn't need session storage or
correlation by id (a per-call `correlation_id` is generated for log slicing
only).

## Read-only data assets (NOT application DB)

* `data/chroma/` — ChromaDB persistent verse vectors (`kjv_verses`,
  `web_verses`). Read by `VerseStore`.
* `data/macula_index.db` — Macula Greek + Hebrew tokens, Strong's
  frequency, lexicon definitions. Read via per-call short-lived
  `sqlite3.connect` from `ContextRetrievalService` (per-call to avoid
  cross-thread connection issues; opens in <1ms on local disk).

These are data assets, not application state. There is no application
database; the audit trail is the JSONL log at `data/logs/strongchat.log`
(cross-process safe via `concurrent-log-handler`).

## Implementation Status

### ✅ Implemented Components

#### LLM Framework (`src/services/llm/`)
- **Status**: ✅ Complete
- **Components**: async LLM wrapper with aiohttp, JSON schema validation,
  exponential backoff retry (3 max), error routing to stderr, response parser
- **Audit**: JSONL log records per call (INFO timing + DEBUG prompt/response),
  replacing the former SQLite `messages` table rows
- **Config**: registry-driven via `src/config/registry.py:DEFAULT_REGISTRY`
  (frozen dataclasses in `src/config/llm_models.py`)

#### Configuration System (`src/config/`)
- **Status**: ✅ Complete
- **Components**:
  - JSON schemas for response validation (`schemas.py`)
  - Pipeline-agnostic prompt templates (`prompts.py`)
  - Static message-type definitions as frozen dataclasses (`llm_models.py`)
  - Process-wide singleton `MessageTypeDefRegistry` (`registry.py`)
  - Cross-process-safe JSONL logging setup (`logging.py`)

#### Intent Generation Service (`src/services/intent/`)
- **Status**: ✅ Complete
- `IntentService.generate_intents(query, correlation_id)`
- `INTENT_GENERATION_SCHEMA` with 1-5 intents, `keywords_explicit`,
  `keywords_inferred`, `themes`, `is_primary`
- Emits one INFO `llm_call` log record + DEBUG `llm_call_audit` record

#### HyDE Generation Service (`src/services/hyde/`)
- **Status**: ✅ Complete
- `HydeService.generate_for_intents(intents, correlation_id)`
- `HYDE_GENERATION_SCHEMA` (`hyde_document` string, min length 50)
- Bias-isolated prompt: receives only one serialized intent, never the
  original query
- Parallel generation via `asyncio.gather`, per-intent failure capture

#### Embeddings Service (`src/services/embeddings/`)
- **Status**: ✅ Complete
- `EmbeddingService.embed_texts(texts, correlation_id, record, chunk_size)`
- Batched OpenRouter `/v1/embeddings` calls (default chunk size 256)
- Retry/backoff for transient `APITimeoutError` / `APIConnectionError`
- Emits INFO `embedding_generation` + DEBUG audit record per call (no raw
  vectors in the log)

#### Verse Store / Corpus Ingest (`src/services/vectordb/`, `scripts/ingest_corpus.py`)
- **Status**: ✅ Complete
- `VerseStore` wrapper around `chromadb.PersistentClient`
- Cosine HNSW collections (`kjv_verses`, `web_verses`)
- Idempotent upsert via `create_batches` + `collection.upsert`
- One INFO `corpus_ingest` log record per translation

#### Retrieval Service (`src/services/retrieval/`)
- **Status**: ✅ Complete
- `RetrievalService.search(hyde_docs, correlation_id, top_k, translations)`
- Embeds valid HyDE docs in one `embedding_generation` call
- Fans out Chroma queries across `(doc, translation)` pairs via
  `asyncio.gather`
- Returns structured hits with `id`, `text`, `reference`, `distance`

#### Pipeline Orchestrator + Serializer (`src/services/pipeline/`, `src/server.py`)
- **Status**: ✅ Complete
- `PipelineRunner` composes `IntentService`, `HydeService`,
  `EmbeddingService`, `VerseStore`, `RetrievalService`,
  `ContextRetrievalService`. Stateless: each `run()` call generates a fresh
  `correlation_id` for log slicing only.
- `PipelineResult` dataclass with `session_uuid` (= correlation_id),
  `query`, per-intent `traces`, `query_analysis`.
- `pipeline_result_to_bundle(result) -> dict` serializes the result to a
  JSON-safe bundle (embeddings dropped) that the agent carries across the
  retrieve → synthesize → validate loop.
- MCP entry point: `src/server.py` (`FastMCP` stdio) exposes
  `retrieve_context` + a `validate_answer` stub.

#### Context Retrieval (`src/services/context/`)
- **Status**: ✅ Complete
- Per-intent original-language enrichment (Greek NT or Hebrew OT, routed
  by `book_num < 40` vs `>= 40`)
- Score formula: `composite_score(pos_weight, frequency_count, sense_count) =
  pos_weight * log1p(1/frequency_count) * log1p(sense_count)`
- Bundle attached in-place to each hit's `context_bundle`
- Per-intent INFO `context_retrieval` + DEBUG audit log record (full bundles
  payload serialized to `raw_response`)

### 📋 Planned Components

#### RRF Implementation (steps 5-6)
- Intra-intent ranking + cross-intent merging + score normalization

#### Synthesis, Evaluation, and Validation (steps 10-13)
- `validate_answer` MCP tool implementation (today: stub raises
  `NotImplementedError`; contract locked in)
- Response synthesis (step 10), evaluator loop (step 11), final response (13)

## Setup

```bash
bash scripts/setup_environment.sh
```

No application DB to create. The setup script installs Python deps, downloads
and ingests Macula Greek + Hebrew + lexicons, and ingests KJV + WEB into
ChromaDB.

## Detailed Documentation

- [Reference Guide](reference.md) - Agent workflow and integration
- [LLM Framework](llm-framework.md) - LLM wrapper + registry + JSONL audit
- [Database](database.md) - Read-only data assets + JSONL audit (no app DB)
- [HyDE Retrieval Pipeline](pipeline-hyde-retrieval.md) - HyDE + retrieval (steps 2-4)
- [Context Retrieval Pipeline](pipeline-context-retrieval.md) - Context (steps 7, 9)
- [Implementation Status](implementation-status.md) - Current progress tracking
- [Architecture Diagrams](architecture-diagram.md) - Mermaid top-level + retrieval detail