# HyDE Retrieval Pipeline

## Overview

The HyDE retrieval half of the StrongChat pipeline turns a plain-language user query into ranked Bible verse candidates across English translations. It covers pipeline steps 2-4:

1. **Intent Generation** — produce 1-5 candidate interpretations of the user's query.
2. **HyDE Generation** — generate one hypothetical biblical passage per intent.
3. **Parallel Retrieval** — embed every HyDE document and query ChromaDB verse collections.

The implemented services are located under `src/services/` and are composed by `PipelineRunner` (`src/services/pipeline/runner.py`). The CLI entry point is `src/main.py`.

This document describes the message types, service contracts, data flow, and how to run the implemented pipeline.

## Message Types and Schemas

All LLM and embedding calls are recorded as rows in the `messages` table, linked to `ref_message_types`. The four message types used by the HyDE-retrieval pipeline are:

| Message type | Model slug | Purpose |
|--------------|------------|---------|
| `intent_generation` | `meta-llama/llama-3.3-70b-instruct` | Generate structured 1-5 intent interpretations of the user query. |
| `hyde_generation` | `mistralai/mistral-small-24b-instruct-2501` | Generate one 100-200 word hypothetical Bible passage from a single intent. |
| `embedding_generation` | `openai/text-embedding-3-small` | Embed a list of texts (HyDE docs or corpus verses). |
| `corpus_ingest` | (none) | Summary audit row recorded after a full translation ingest. |

### Schemas

- `INTENT_GENERATION_SCHEMA` (`src/config/schemas.py`)
  - `query_analysis`: `original_query`, `core_questions`, `context_clues`
  - `intents`: 1-5 items, each with `intent_id`, `interpretation`, `keywords_explicit`, `keywords_inferred`, `themes`, `confidence`, `is_primary`

- `HYDE_GENERATION_SCHEMA` (`src/config/schemas.py`)
  - Single property: `hyde_document` (string, `minLength: 50`)

- `embedding_generation` and `corpus_ingest` have no JSON response schema; they are recorded as summary rows.

## Service Contracts

All services inherit from `BaseService` (`src/services/base.py`), which provides a shared `LLMWrapper`, `ChatDatabase`, and `GlobalReferenceCache`.

### IntentService (`src/services/intent/service.py`)

```python
async def generate_intents(self, query: str, session_uuid: str) -> dict:
    """Return message_uuid, query_analysis, intents."""
```

- Calls `intent_generation` through `LLMWrapper`.
- Records one `intent_generation` message.
- Validates the response against `INTENT_GENERATION_SCHEMA`.

### HydeService (`src/services/hyde/service.py`)

```python
async def generate_for_intents(
    self, intents: list[dict], session_uuid: str
) -> list[dict]:
    """Return one result dict per intent with intent_id, hyde_document, message_uuid or error."""
```

- Launches one `hyde_generation` call per intent in parallel via `asyncio.gather`.
- Sends only the allowed intent fields (`intent_id`, `interpretation`, `keywords_explicit`, `keywords_inferred`, `themes`) to the prompt; the original query is never included.
- Per-intent failures are captured; if all fail, `LLMError` is raised with details attached.

### EmbeddingService (`src/services/embeddings/service.py`)

```python
async def embed_texts(
    self,
    texts: list[str],
    session_uuid: str | None = None,
    record: bool = True,
    chunk_size: int = 256,
) -> list[list[float]]:
    """Return embedding vectors in input order."""
```

- Uses OpenRouter `/v1/embeddings` by default; accepts an injected `embed_fn` for tests.
- Chunks inputs (default 256) and submits sequentially.
- Retries transient `APITimeoutError` / `APIConnectionError` with exponential backoff.
- Records one summary `embedding_generation` message when `record=True` and `session_uuid` is set; raw vectors are never persisted.

### VerseStore (`src/services/vectordb/store.py`)

```python
def __init__(self, path: str = "data/chroma")
def get_or_create_collection(self, name: str, metadata: dict | None = None) -> Collection
def upsert_verses(self, collection_name: str, ids, documents, metadatas, embeddings) -> None
def count(self, name: str) -> int
def query(self, name: str, query_embeddings: list[list[float]], n_results: int) -> dict
```

- Wraps `chromadb.PersistentClient`.
- Default collection metadata uses cosine HNSW space.
- Upserts are idempotent (same IDs overwrite).

### RetrievalService (`src/services/retrieval/service.py`)

```python
async def search(
    self,
    hyde_docs: list[dict],
    session_uuid: str,
    top_k: int = 10,
    translations: tuple[str, ...] = ("kjv", "web"),
) -> list[dict]:
    """Return structured hits per (doc, translation) pair."""
```

- Filters out empty/null HyDE documents.
- Embeds valid documents in one `embedding_generation` call.
- Queries every requested translation collection in parallel via `asyncio.to_thread` + `asyncio.gather`.
- Each hit contains `id`, `text`, `reference`, and `distance`.

### PipelineRunner (`src/services/pipeline/runner.py`)

```python
class PipelineRunner(BaseService):
    async def run(
        self, query: str, top_k: int = 10, translations=("kjv", "web")
    ) -> PipelineResult
```

- Composes `IntentService`, `HydeService`, `EmbeddingService`, `VerseStore`, and `RetrievalService`.
- Creates a session, runs intent → HyDE → retrieval, and returns a `PipelineResult`.
- Owns one shared `EmbeddingService` that is injected into `RetrievalService`.

## Data Flow

```
User query
    │
    ▼
┌─────────────────┐
│ IntentService   │ ──intent_generation──► messages (ref_message_types)
│                 │ ◄──1-5 intents────────┘
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ HydeService     │ ──hyde_generation (parallel)──► messages
│                 │ ◄──1 hyde_document per intent──┘
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ RetrievalService│
│  - embed_texts  │ ──embedding_generation──► messages
│  - store.query  │
│                 │ ◄──Chroma results per (doc, translation)
└─────────────────┘
    │
    ▼
PipelineResult(intents, hyde_docs, results)
```

1. `PipelineRunner.run(query)` creates a session.
2. `IntentService.generate_intents` returns parsed intents.
3. `HydeService.generate_for_intents` returns one HyDE document per intent.
4. `RetrievalService.search` embeds the HyDE documents and queries `kjv_verses` and `web_verses` collections.
5. Results are returned as a `PipelineResult` dataclass.

## Commands

### Run the full pipeline CLI

```bash
.venv/bin/python src/main.py "what does the Bible say about anxiety"
```

The query is a positional argument; `top_k`, translations, and other settings are read from `PipelineRunner`'s defaults (override by editing the runner or by calling `PipelineRunner.run(...)` directly from Python).

### Ingest the Bible corpus

Prerequisite: download the corpus first.

```bash
.venv/bin/python scripts/download_bible_corpus.py
.venv/bin/python scripts/ingest_corpus.py
```

Ingest one translation only:

```bash
.venv/bin/python scripts/ingest_corpus.py --translation kjv
```

Limit batches for a smoke test:

```bash
.venv/bin/python scripts/ingest_corpus.py --max-batches 1
```

### Run tests

Offline service tests:

```bash
.venv/bin/python scripts/test_intent_service.py
.venv/bin/python scripts/test_hyde_service.py
.venv/bin/python scripts/test_embedding_service.py
.venv/bin/python scripts/test_retrieval_service.py
.venv/bin/python scripts/test_pipeline_offline.py
```

Live system tests (require `OPENROUTER_API_KEY` and an ingested corpus):

```bash
.venv/bin/python tests/system/test_intent_generation.py
.venv/bin/python tests/system/test_pipeline_e2e.py
```

### Run the database migration

```bash
.venv/bin/python scripts/migrate_pipeline_message_types.py
```

## Cost Notes

Approximate OpenRouter calls:

- **Corpus ingest**: ~31,000 verses per translation, embedded in 256-verse chunks.
  - ~122 `embedding_generation` calls per translation.
  - ~244 calls total for KJV + WEB.
  - One-time cost per environment; re-runs are idempotent.

- **Per query**:
  - 1 `intent_generation` call.
  - N `hyde_generation` calls, where N = number of intents (1-5, typically 3).
  - 1 `embedding_generation` call for all valid HyDE documents combined.
  - Example: a query producing 3 intents costs 1 intent + 3 HyDE + 1 embedding call.

Embedding calls are cheap (~$5e-7 per 26-token sample observed). HyDE and intent calls use the open-weight models above and are the dominant per-query cost.

## Next Steps

The HyDE-retrieval half is complete. Remaining pipeline work:

1. **RRF** (steps 5-6): intra-intent and cross-intent ranking fusion.
2. **Macula integration** (step 7): original-language lookup.
3. **Graph expansion** (step 8): lemma/verse-graph traversal.
4. **Synthesis, evaluator, validator** (steps 10-13): generate and verify the final answer.
