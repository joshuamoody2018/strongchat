# Pipeline Implementation Status

## Current Implementation Status

### ✅ Completed Components

#### 1. LLM Framework
- **Status**: ✅ Complete
- **Location**: `src/services/llm/`
- **Components**:
  - Async LLM wrapper (`LLMWrapper`) with aiohttp
  - JSON schema validation
  - Exponential backoff retry (3 max)
  - Error routing to stderr
  - Response parser with validation (`AIMessage`, `parse_response`)
- **Audit**: JSONL log records per call (INFO timing + DEBUG prompt/response)
- **Testing**: ✅ 6/6 parser tests passing, offline/online service tests passing

#### 2. Message-type Registry (replaces former database layer)
- **Status**: ✅ Complete
- **Location**: `src/config/llm_models.py`, `src/config/registry.py`
- **Components**:
  - `@dataclass(frozen=True) MessageTypeDef` for every pipeline slug
  - Process-wide singleton `MessageTypeDefRegistry` built at import time
  - Read-only after import; GIL-safe across asyncio tasks and worker threads
- **No application database**: the former `sessions`, `messages`,
  `ref_message_types` SQLite tables are gone. Read-only data assets
  (`data/chroma/`, `data/macula_index.db`) survive; application state does
  not.

#### 3. Structured Logging
- **Status**: ✅ Complete
- **Location**: `src/config/logging.py`
- **Components**:
  - Cross-process-safe JSONL handler (`concurrent-log-handler`)
  - `JsonFormatter` emits one JSON object per line
  - Levels: `ERROR` (default when env unset), `INFO` (per-step timing),
    `DEBUG` (full audit — prompt + raw_response + bundle payloads)
  - Configurable via `STRONGCHAT_LOG_LEVEL` / `STRONGCHAT_LOG_FILE` env
- **Replaces**: every former SQLite `messages` row insert

#### 4. Configuration System
- **Status**: ✅ Complete
- **Components**:
  - JSON schemas for response validation (`schemas.py`)
  - Pipeline-agnostic prompt templates (`prompts.py`)
  - Static message-type definitions (`llm_models.py`)
  - Singleton registry (`registry.py`)
  - JSONL logging setup (`logging.py`)

#### 5. Intent Generation Service
- **Status**: ✅ Complete
- **Location**: `src/services/intent/`
- `IntentService.generate_intents(query, correlation_id)`
- `INTENT_GENERATION_SCHEMA` with 1-5 intents, `keywords_explicit`,
  `keywords_inferred`, `themes`, `is_primary`
- Emits one INFO `llm_call` + DEBUG `llm_call_audit` log records per call

#### 6. HyDE Generation Service
- **Status**: ✅ Complete
- **Location**: `src/services/hyde/`
- `HydeService.generate_for_intents(intents, correlation_id)`
- `HYDE_GENERATION_SCHEMA` (`hyde_document` string, min length 50)
- Bias-isolated prompt: receives only one serialized intent, never the
  original query
- Parallel generation via `asyncio.gather`, per-intent failure capture

#### 7. Embeddings Service
- **Status**: ✅ Complete
- **Location**: `src/services/embeddings/`
- `EmbeddingService.embed_texts(texts, correlation_id, record, chunk_size)`
- Batched OpenRouter `/v1/embeddings` calls (default chunk size 256)
- Retry/backoff for transient `APITimeoutError` / `APIConnectionError`
- Emits one INFO `embedding_generation` + DEBUG audit log record per call
  (no raw vectors in the log)

#### 8. Verse Store / Corpus Ingest
- **Status**: ✅ Complete
- **Location**: `src/services/vectordb/`, `scripts/ingest_corpus.py`
- `VerseStore` wrapper around `chromadb.PersistentClient`
- Cosine HNSW collections (`kjv_verses`, `web_verses`)
- Idempotent upsert via `create_batches` + `collection.upsert`
- One INFO `corpus_ingest` log record per translation

#### 9. Retrieval Service
- **Status**: ✅ Complete
- **Location**: `src/services/retrieval/`
- `RetrievalService.search(hyde_docs, correlation_id, top_k, translations)`
- Embeds valid HyDE docs in one `embedding_generation` call
- Fans out Chroma queries across `(doc, translation)` pairs via
  `asyncio.gather`
- Returns structured hits with `id`, `text`, `reference`, `distance`

#### 10. Pipeline Orchestrator + Serializer + MCP Server
- **Status**: ✅ Complete
- **Location**: `src/services/pipeline/`, `src/server.py`, `src/main.py`
- `PipelineRunner` composes `IntentService`, `HydeService`,
  `EmbeddingService`, `VerseStore`, `RetrievalService`,
  `ContextRetrievalService`. Stateless: each `run()` call generates a
  fresh `correlation_id` for log slicing only.
- `PipelineResult` dataclass with `session_uuid` (= correlation_id),
  `query`, per-intent `traces`, `query_analysis`.
- `pipeline_result_to_bundle(result) -> dict` serializes a
  JSON-safe bundle (embeddings dropped) that the agent carries across the
  retrieve → synthesize → validate loop.
- MCP entry point: `src/server.py` (`FastMCP` stdio) exposes
  `retrieve_context` + a `validate_answer` stub.
- CLI smoke-test: `src/main.py` calls the same `retrieve_context` body and
  prints the bundle as JSON.

#### 11. Context Retrieval
- **Status**: ✅ Complete
- **Location**: `src/services/context/`
- Per-intent original-language enrichment (Greek NT or Hebrew OT, routed
  by `book_num < 40` vs `>= 40`)
- Score formula: `composite_score(pos_weight, frequency_count, sense_count)
  = pos_weight * log1p(1/frequency_count) * log1p(sense_count)`
- Bundle attached in-place to each hit's `context_bundle`
- Per-intent INFO `context_retrieval` (with `intent_id`, `translation_count`,
  `hit_count`, `scored_word_count`, `kept_word_count`, `elapsed_ms`,
  `status`) + DEBUG audit log record (full `bundles` payload serialized as
  `raw_response`)

### 📋 Planned Components

#### 1. RRF Implementation (steps 5-6)
- Intra-intent ranking + cross-intent merging + score normalization
- **Location**: `src/services/rrf/` (planned)

#### 2. Synthesis, Evaluation, and Validation (steps 10-13)
- **Status**: 📋 Planned
- **Requirements**:
  - `validate_answer` MCP tool implementation (today: stub raises
    `NotImplementedError`; contract locked in)
  - Response synthesis (step 10), evaluator loop (step 11), final response
    (13)

## Task Tracking

### todo-next.md
- ✅ Framework implementation
- ✅ Intent service integration
- ✅ HyDE schema + prompt
- ✅ Embeddings service
- ✅ Retrieval service
- ✅ Corpus/vector store
- ✅ Pipeline orchestrator
- 📋 RRF implementation
- 📋 Synthesis / evaluator / validator
- 📋 `validate_answer` MCP tool implementation

### todo-deferred.md
- RRF (steps 5-6)
- Graph expansion (step 8)
- Synthesis / evaluator / validator (steps 10-13)
- HTTP/SSE MCP transport (if ever needed beyond stdio)
- Production monitoring

## Critical Dependencies

### 1. Intent Generation → HyDE Generation
- Intent service output required for HyDE input
- Structured intents with `intent_id`, `interpretation`, `keywords_*`,
  `themes` needed for N×M generation

### 2. HyDE Generation → Embeddings → Retrieval
- HyDE documents feed `EmbeddingService.embed_texts`
- `RetrievalService` queries `VerseStore` per `(doc, translation)` pair

### 3. LLM Framework → All LLM Services
- `LLMWrapper` provides validated, retry-aware LLM calls
- JSONL audit is the only side-effect; there is no application DB

### 4. Registry → All Services
- `MessageTypeDefRegistry` (`DEFAULT_REGISTRY`) provides immutable config
- Built once at import time; safe to share across tasks/threads
- Tests can construct a fixture registry or call `DEFAULT_REGISTRY.reset([...])`

## Risk Assessment

### Low Risk
- Registry evolution (frozen dataclasses are easy to extend)
- LLM framework integration
- Configuration management
- Intent/HyDE/retrieval pipeline

### Medium Risk
- JSON schema validation edge cases
- Error handling robustness
- RRF algorithm implementation

### High Risk
- Macula external dependencies (~80 MB TSV for Hebrew)
- Synthesis/evaluator loop convergence
- `validate_answer` structured-feedback design (drives agent behaviour)

## Success Metrics

### Technical Metrics
- ✅ Framework test coverage: 100%
- ✅ Integration test coverage: live pipeline end-to-end passing
- ✅ Pipeline step completion: 7/13 implemented (input, intent generation,
  HyDE generation, retrieval, Macula lookup, context retrieval,
  re-rank/organize)
- ✅ MCP server: `retrieve_context` live; `validate_answer` contract locked in

### Functional Metrics
- ✅ Intent generation: Working and audited
- ✅ HyDE generation: Working and audited
- ✅ Embeddings: Working and audited
- ✅ Retrieval: Working and audited
- ✅ Context retrieval: Working and audited
- 📋 End-to-end synthesis: In progress (agent-side, not server-side)

## Next Milestones

### Short Term
1. Implement `validate_answer` MCP tool (step 12) with structured
   `unsupported_claims` / `missing_coverage` / `suggested_refinement`
   feedback
2. Update retrieval service to feed ranked results into synthesis (after RRF)

### Medium Term
1. Implement RRF ranking (steps 5-6)
2. Implement response synthesis (step 10) — typically agent-side
3. Add evaluator loop (step 11)

### Long Term
1. Complete full pipeline integration (steps 5-13)
2. Add production monitoring
3. Evaluate whether the agent harness / state-management wrapper is its own repo