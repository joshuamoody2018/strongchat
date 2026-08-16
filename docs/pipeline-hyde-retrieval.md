# HyDE Retrieval Pipeline

## Overview

The HyDE retrieval half of the StrongChat pipeline turns a plain-language
user query into ranked Bible verse candidates across English translations.
It covers pipeline steps 2-4:

1. **Intent Generation** — produce 1-5 candidate interpretations of the
   user's query.
2. **HyDE Generation** — generate one hypothetical biblical passage per
   intent.
3. **Parallel Retrieval** — embed every HyDE document and query ChromaDB
   verse collections.

The implemented services are located under `src/services/` and are composed
by `PipelineRunner` (`src/services/pipeline/runner.py`). The MCP server
entry point is `src/server.py`; the dev/debug CLI smoke-test is
`src/main.py`. Each pipeline run is stateless —
`PipelineRunner.run()` generates a fresh correlation id, threads it through
the services for log correlation only, and returns a `PipelineResult`
dataclass that is serialized into a JSON bundle the calling agent carries
across the retrieve → synthesize → validate loop.

There is **no application database**. The audit trail is JSONL log records
keyed by `correlation_id` (see `src/config/logging.py` and
`docs/database.md`).

## Message Types and Schemas

All LLM and embedding calls emit one INFO timing log record + one DEBUG
audit log record. The four message types used by the HyDE-retrieval
pipeline are:

| Message type | Model slug | Purpose |
|--------------|------------|---------|
| `intent_generation` | `meta-llama/llama-3.3-70b-instruct` | Generate structured 1-5 intent interpretations of the user query. |
| `hyde_generation` | `mistralai/mistral-small-24b-instruct-2501` | Generate one 100-200 word hypothetical Bible passage from a single intent. |
| `embedding_generation` | `openai/text-embedding-3-small` | Embed a list of texts (HyDE docs or corpus verses). |
| `corpus_ingest` | `openai/text-embedding-3-small` | Summary audit record emitted after a full translation ingest. |

### Schemas

- `INTENT_GENERATION_SCHEMA` (`src/config/schemas.py`)
  - `query_analysis`: `original_query`, `core_questions`, `context_clues`
  - `intents`: 1-5 items, each with `intent_id`, `interpretation`,
    `keywords_explicit`, `keywords_inferred`, `themes`, `confidence`,
    `is_primary`

- `HYDE_GENERATION_SCHEMA` (`src/config/schemas.py`)
  - Single property: `hyde_document` (string, `minLength: 50`)

- `embedding_generation` and `corpus_ingest` have no JSON response schema;
  they are recorded as summary rows (logged via INFO + DEBUG JSONL records).

## Service Contracts

All services inherit from `BaseService` (`src/services/base.py`), which
provides a shared `LLMWrapper` and the process-wide
`MessageTypeDefRegistry`. `BaseService.record_message` is a thin logger
shim so the existing service call sites need minimal signature churn — the
audit payload lands in the JSONL log instead of a SQLite row.

### IntentService (`src/services/intent/service.py`)

```python
async def generate_intents(self, query: str, correlation_id: str) -> dict:
    """Return message_uuid, query_analysis, intents."""
```

- Calls `intent_generation` through `LLMWrapper`.
- Emits one INFO `llm_call` + DEBUG `llm_call_audit` record.
- Validates the response against `INTENT_GENERATION_SCHEMA`.

### HydeService (`src/services/hyde/service.py`)

```python
async def generate_for_intents(
    self, intents: list[dict], correlation_id: str
) -> list[dict]:
    """Return one result dict per intent with intent_id, hyde_document, message_uuid or error."""
```

- Launches one `hyde_generation` call per intent in parallel via
  `asyncio.gather`.
- Sends only the allowed intent fields (`intent_id`, `interpretation`,
  `keywords_explicit`, `keywords_inferred`, `themes`) to the prompt; the
  original query is never included.
- Per-intent failures are captured; if all fail, `LLMError` is raised with
  details attached.

### EmbeddingService (`src/services/embeddings/service.py`)

```python
async def embed_texts(
    self,
    texts: list[str],
    correlation_id: str | None = None,
    record: bool = True,
    chunk_size: int = 256,
) -> list[list[float]]:
    """Return embedding vectors in input order."""
```

- Uses OpenRouter `/v1/embeddings` by default; accepts an injected
  `embed_fn` for tests.
- Chunks inputs (default 256) and submits sequentially.
- Retries transient `APITimeoutError` / `APIConnectionError` with
  exponential backoff.
- Emits one INFO `embedding_generation` + DEBUG audit log record when
  `record=True` and `correlation_id` is set; raw vectors are NEVER persisted
  (only the summary `{model, dimension, count}` is logged).

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
    correlation_id: str,
    top_k: int = 10,
    translations: tuple[str, ...] = ("kjv", "web"),
) -> list[dict]:
    """Return structured hits per (doc, translation) pair."""
```

- Filters out empty/null HyDE documents.
- Embeds valid documents in one `embedding_generation` call.
- Queries every requested translation collection in parallel via
  `asyncio.to_thread` + `asyncio.gather`.
- Each hit contains `id`, `text`, `reference`, and `distance`.

### PipelineRunner (`src/services/pipeline/runner.py`)

```python
class PipelineRunner(BaseService):
    async def run(
        self, query: str, top_k: int = 10, translations=("kjv", "web")
    ) -> PipelineResult
```

- Composes `IntentService`, `HydeService`, `EmbeddingService`, `VerseStore`,
  `RetrievalService`, `ContextRetrievalService`.
- Stateless: each `run()` call generates a fresh `correlation_id`, threads
  it through for log correlation only, and returns a `PipelineResult`. No
  session row, no message rows — the audit trail is the JSONL log keyed by
  `correlation_id`.
- Owns one shared `EmbeddingService` that is injected into
  `RetrievalService`.

## Data Flow

```
User query
    │
    ▼
┌─────────────────┐
│ IntentService    │ ──INFO llm_call + DEBUG llm_call_audit──► JSONL log
│                  │ ◄──1-5 intents──────────────────────────┘
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ HydeService      │ ──parallel hyde_generation (audited same way)──► JSONL log
│                  │ ◄──1 hyde_document per intent──────────────────┘
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ RetrievalService │
│  - embed_texts   │ ──INFO embedding_generation + DEBUG audit──► JSONL log
│  - store.query   │
│                  │ ◄──Chroma results per (doc, translation)
└─────────────────┘
    │
    ▼
PipelineResult (session_uuid = correlation_id, intents, hyde_docs, results)
    │
    ▼  (when called through the MCP server / CLI smoke-test)
pipeline_result_to_bundle(result) -> dict
    │
    ▼
JSON bundle returned to the agent (embeddings dropped)
```

## Commands

### Run the MCP server (production entry point)

```bash
.venv/bin/python src/server.py
```

### Run the CLI smoke-test (dev/debug)

```bash
.venv/bin/python src/main.py "what does the Bible say about anxiety"
```

Prints the JSON bundle the MCP `retrieve_context` tool would return.

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

Offline script-style tests (no network, dummy key):

```bash
.venv/bin/python tests/scripts/test_intent_service.py
.venv/bin/python tests/scripts/test_hyde_service.py
.venv/bin/python tests/scripts/test_embedding_service.py
.venv/bin/python tests/scripts/test_retrieval_service.py
.venv/bin/python tests/scripts/test_pipeline_offline.py
.venv/bin/python tests/scripts/test_mcp_server.py
.venv/bin/python tests/scripts/test_logging.py
```

Live system tests (require `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` and an ingested corpus):

```bash
.venv/bin/python tests/system/test_intent_generation.py
.venv/bin/python tests/system/test_pipeline_e2e.py
```

## Cost Notes

Approximate OpenRouter calls:

- **Corpus ingest**: ~31,000 verses per translation, embedded in 256-verse
  chunks.
  - ~122 `embedding_generation` calls per translation.
  - ~244 calls total for KJV + WEB.
  - One-time cost per environment; re-runs are idempotent.

- **Per query**:
  - 1 `intent_generation` call.
  - N `hyde_generation` calls, where N = number of intents (1-5, typically 3).
  - 1 `embedding_generation` call for all valid HyDE documents combined.
  - Example: a query producing 3 intents costs 1 intent + 3 HyDE + 1 embedding call.

Embedding calls are cheap. HyDE and intent calls use open-weight models and
are the dominant per-query cost.

## Next Steps

The HyDE-retrieval half is complete. Remaining pipeline work:

1. **RRF** (steps 5-6): intra-intent and cross-intent ranking fusion.
2. **Graph expansion** (step 8): lemma/verse-graph traversal.
3. **`validate_answer` MCP tool implementation** (step 12): contract is
   locked in today but is a stub.
4. **Synthesis, evaluator** (steps 10-11): generate and verify the final
   answer (typically agent-side, not server-side).