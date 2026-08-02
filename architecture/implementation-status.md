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
- **Testing**: ✅ 6/6 parser tests passing, offline/online service tests passing
- **Documentation**: ✅ Comprehensive docs in `LLM_FRAMEWORK.md`

#### 2. Database Layer
- **Status**: ✅ Complete
- **Location**: `src/services/sqlite/`
- **Components**:
  - Chat session management
  - Message storage with `ref_message_types` FK
  - Intent tracking (structured)
  - Foreign-key enforcement enabled per connection
- **Testing**: ✅ CRUD operations validated, migration tests passing
- **Database**: ✅ Schema implemented and tested

#### 3. Configuration System
- **Status**: ✅ Complete
- **Location**: `src/config/`
- **Components**:
  - JSON schemas for response validation (`schemas.py`)
  - Pipeline-agnostic prompt templates (`prompts.py`)
  - Centralized configuration management

#### 4. Intent Generation Service
- **Status**: ✅ Complete
- **Location**: `src/services/intent/`, `src/config/schemas.py`, `src/config/prompts.py`
- **Components**:
  - `IntentService.generate_intents(query, session_uuid)`
  - `INTENT_GENERATION_SCHEMA` with 1-5 intents, `keywords_explicit`, `keywords_inferred`, `themes`, `is_primary`
  - Records one `intent_generation` message per call
- **Testing**: ✅ Offline mocked test + live system test passing

#### 5. HyDE Generation Service
- **Status**: ✅ Complete
- **Location**: `src/services/hyde/`
- **Components**:
  - `HydeService.generate_for_intents(intents, session_uuid)`
  - `HYDE_GENERATION_SCHEMA` (`hyde_document` string, min length 50)
  - Bias-isolated prompt: receives only one serialized intent, never the original query
  - Parallel generation via `asyncio.gather`, per-intent failure capture
- **Testing**: ✅ Offline and live tests passing

#### 6. Embeddings Service
- **Status**: ✅ Complete
- **Location**: `src/services/embeddings/`
- **Components**:
  - `EmbeddingService.embed_texts(texts, session_uuid, record, chunk_size)`
  - Batched OpenRouter `/v1/embeddings` calls (default chunk size 256)
  - Retry/backoff for transient `APITimeoutError` / `APIConnectionError`
  - Records one summary `embedding_generation` message per call (no raw vectors)
- **Testing**: ✅ Offline tests passing

#### 7. Verse Store / Corpus Ingest
- **Status**: ✅ Complete
- **Location**: `src/services/vectordb/`, `scripts/ingest_corpus.py`
- **Components**:
  - `VerseStore` wrapper around `chromadb.PersistentClient`
  - Cosine HNSW collections (`kjv_verses`, `web_verses`)
  - Idempotent upsert via `create_batches` + `collection.upsert`
  - `corpus_ingest` summary message recorded after each translation ingest
- **Testing**: ✅ Full KJV + WEB ingest verified, semantic check passes

#### 8. Retrieval Service
- **Status**: ✅ Complete
- **Location**: `src/services/retrieval/`
- **Components**:
  - `RetrievalService.search(hyde_docs, session_uuid, top_k, translations)`
  - Embeds valid HyDE docs in one `embedding_generation` call
  - Fans out Chroma queries across `(doc, translation)` pairs via `asyncio.gather`
  - Returns structured hits with `id`, `text`, `reference`, `distance`
- **Testing**: ✅ Offline tests passing

#### 9. Pipeline Orchestrator
- **Status**: ✅ Complete
- **Location**: `src/services/pipeline/`, `scripts/run_pipeline.py`
- **Components**:
  - `PipelineRunner` composes `IntentService`, `HydeService`, `EmbeddingService`, `VerseStore`, `RetrievalService`
  - `PipelineResult` dataclass with `session_uuid`, `query`, `intents`, `hyde_docs`, `results`
  - CLI runner: `scripts/run_pipeline.py`
- **Testing**: ✅ Live end-to-end test passing

#### 10. Context Retrieval
- **Status**: ✅ Complete (committed 2026-08-02)
- **Location**: `src/services/context/`
- **Message type**: `context_retrieval` (programmatic, summary schema)
- **Test files**: `tests/scripts/test_context_retrieval_service.py`, `tests/scripts/test_context_retrieval_offline.py`, `tests/system/test_context_retrieval_e2e.py`
- **Score formula**: cite `composite_score(pos_weight, frequency_count, sense_count) = pos_weight * log1p(1/frequency_count) * log1p(sense_count)` from `src/config/context_constants.py`
- **KNOWN LIMITATION**: the `gloss` field on each kept_word is empty because todo 3's `macula_tokens` SQLite schema does not include the `gloss` column from the canonical TSV. Flagged for a follow-up "fix macula schema" plan.

### 📋 Planned Components

#### 1. RRF Implementation
- **Status**: 📋 Planned
- **Location**: `src/services/rrf/` (planned)
- **Requirements**:
  - Intra-intent ranking (step 5)
  - Cross-intent merging (step 6)
  - Score normalization and fusion

#### 2. Macula Integration
- **Status**: 📋 Planned
- **Requirements**:
  - NT: Macula Greek lookup (step 7)
  - OT: Macula Hebrew lookup (TBD)
  - Strong's concordance integration

#### 3. Synthesis, Evaluation, and Validation
- **Status**: 📋 Planned
- **Requirements**:
  - Response synthesis (step 10)
  - Evaluator loop (step 11)
  - Fact validation (step 12)
  - Final response (step 13)

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
- 📋 Macula integration
- 📋 Synthesis / evaluator / validator

### todo-deferred.md
- Error handling improvements
- Async database operations
- Performance optimizations
- Production readiness features
- Testing infrastructure expansion
- Deployment automation

## Critical Dependencies

### 1. Intent Generation → HyDE Generation
- Intent service output required for HyDE input
- Structured intents with `intent_id`, `interpretation`, `keywords_*`, `themes` needed for N×M generation

### 2. HyDE Generation → Embeddings → Retrieval
- HyDE documents feed `EmbeddingService.embed_texts`
- `RetrievalService` queries `VerseStore` per `(doc, translation)` pair

### 3. LLM Framework → All LLM Services
- `LLMWrapper` provides validated, retry-aware LLM calls
- Error handling and audit logging essential

### 4. Database → All Services
- `ChatDatabase` stores session and messages
- `GlobalReferenceCache` loads `ref_message_types` rows
- `BaseService` exposes shared wrapper, cache, and DB to every service

## Risk Assessment

### Low Risk
- Database schema evolution
- LLM framework integration
- Configuration management
- Intent/HyDE/retrieval pipeline

### Medium Risk
- JSON schema validation edge cases
- Error handling robustness
- RRF algorithm implementation

### High Risk
- Macula external dependencies
- Synthesis/evaluator loop convergence
- Pipeline step 5-13 integration timing

## Success Metrics

### Technical Metrics
- ✅ Framework test coverage: 100%
- ✅ Integration test coverage: live pipeline end-to-end passing
- ✅ Pipeline step completion: 4/13 implemented (input, intent generation, HyDE generation, retrieval)

### Functional Metrics
- ✅ Database operations: All working
- ✅ Intent generation: Working and audited
- ✅ HyDE generation: Working and audited
- ✅ Embeddings: Working and audited
- ✅ Retrieval: Working and audited
- 📋 End-to-end synthesis: In progress

## Next Milestones

### Short Term (1-2 weeks)
1. Implement RRF ranking (steps 5-6)
2. Update retrieval service to feed ranked results into synthesis

### Medium Term (1-2 months)
1. Add Macula integration (step 7)
2. Implement response synthesis (step 10)
3. Add evaluator loop (step 11)

### Long Term (3-6 months)
1. Complete full pipeline integration (steps 5-13)
2. Add production monitoring
3. Optimize performance and scalability
