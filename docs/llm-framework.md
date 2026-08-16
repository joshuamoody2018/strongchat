# LLM Framework Architecture

## Overview

The StrongChat LLM Framework provides a structured approach to handling LLM
interactions with JSON schema validation, retry logic, and automated
response parsing. It is the canonical recorded-path LLM client for the
biblical-search pipeline. There is **no application database**; the audit
trail is JSONL log records. `LLMWrapper`
(`src/services/llm/wrapper.py`) is async, registry-driven, and the only
LLM caller used by production services.

## Architecture

### Core Components

1. **Configuration Layer** (`src/config/`)
   - `schemas.py`: JSON schemas for response validation
   - `prompts.py`: Prompt templates (pipeline-agnostic)
   - `llm_models.py`: Static, frozen-dataclass message-type definitions
     (replaces former `ref_message_types` SQLite table)
   - `registry.py`: Process-wide singleton `MessageTypeDefRegistry`
     (`DEFAULT_REGISTRY`)
   - `logging.py`: Cross-process-safe JSONL audit setup

2. **Wrapper Layer** (`src/services/llm/wrapper.py`)
   - `LLMWrapper`: Registry-driven async LLM client with retry logic
   - Reads model, temperature, prompt template, max retries from the
     `MessageTypeDef` for the slug
   - Emits INFO timing + DEBUG audit (prompt/raw_response) log records
     per call (replaces former `messages` SQLite inserts)
   - Exponential backoff (3 retries: 1s → 2s → 4s)
   - aiohttp async HTTP client
   - JSON schema validation

3. **AIMessage Layer** (`src/services/llm/aimessage.py`)
   - `AIMessage`: dataclass + strict-JSON parsing contract for LLM
     responses
   - Strict JSON-only parsing (markdown fence stripping, prose-residue
     rejection)
   - `mark_success_from_text` validates against a JSON schema and stores
     the canonical, fence-free `raw_response` for audit
   - Error handling for malformed responses

4. **Service Layer** (`src/services/`)
   - `base.py`: Shared `BaseService` foundation (owns one `LLMWrapper` +
     the process-wide `DEFAULT_REGISTRY` + a child logger)
   - `llm/exceptions.py`: Custom exception classes
   - `intent/`, `hyde/`, `embeddings/`, `vectordb/`, `retrieval/`,
     `context/`, `pipeline/`: pipeline services

### Canonical Recorded Path

`LLMWrapper` (`src/services/llm/wrapper.py`) is the canonical LLM client
for the pipeline. It is registry-driven by slug, emits INFO + DEBUG
JSONL audit records per call, and is the client inherited by
`BaseService`. Every service that needs to talk to an LLM calls
`await wrapper.call_api(...)`.

The four recorded message types used by the HyDE-retrieval pipeline are:

- `intent_generation`
- `hyde_generation`
- `embedding_generation`
- `corpus_ingest`

## Design Principles

1. **Separation of Concerns**: JSON schemas are completely separate from
   prompt templates; LLMs only know their immediate task, not pipeline
   context
2. **Type Safety**: Response models provide validated data access
3. **Error Resilience**: Exponential backoff retry (1s → 2s → 4s) with
   graceful degradation
4. **Auditability**: Every call emits INFO timing + DEBUG audit records
   to the JSONL log keyed by `correlation_id`
5. **Async First**: aiohttp for concurrently launching parallel LLM
   calls (e.g. HyDE generation across N intents)

## Usage Examples

### Basic Recorded Call

`LLMWrapper.call_api` is the only entry point for production code. It is
async, reads model/prompt/retry config from the registry for the slug,
and emits INFO + DEBUG audit log records.

```python
import asyncio
import uuid

from services.llm.wrapper import LLMWrapper


async def main():
    wrapper = LLMWrapper()
    correlation_id = str(uuid.uuid4())
    message = await wrapper.call_api(
        message_type_slug="intent_generation",
        unique_prompt="why do bad things happen",
        session_uuid=correlation_id,  # log-only correlation id
    )
    print(message.raw_response)
    wrapper.close()


asyncio.run(main())
```

### Custom Schema Integration

`LLMWrapper.call_api` reads its schema from the registered
`MessageTypeDef` for the slug and validates the response through
`AIMessage.get_parsed_response`. No subclassing or client-side schema
wiring is required:

```python
import asyncio
import uuid

from config import DEFAULT_REGISTRY
from services.llm.wrapper import LLMWrapper


async def main():
    wrapper = LLMWrapper()
    correlation_id = str(uuid.uuid4())

    intent_config = DEFAULT_REGISTRY.get("intent_generation")
    message = await wrapper.call_api(
        message_type_slug="intent_generation",
        unique_prompt="user query",
        session_uuid=correlation_id,
    )
    parsed = message.get_parsed_response(intent_config.request_schema)
    print(parsed)


asyncio.run(main())
```

## Configuration

### Environment Variables

```bash
OPENROUTER_API_KEY=your_api_key_here

# Optional logging knobs
STRONGCHAT_LOG_LEVEL=ERROR            # default if unset; INFO or DEBUG
STRONGCHAT_LOG_FILE=data/logs/strongchat.log  # default
```

### Model Configuration (Registry-Driven)

`LLMWrapper` does not take `model_config` in code — model, temperature,
prompt template, and max retries are all stored on the
`MessageTypeDef` dataclass instances defined in
`src/config/llm_models.py`. To tune a message type, edit the dataclass
instance; every subsequent `call_api` picks it up through the
`DEFAULT_REGISTRY` singleton built at import time. Tests that need a
fixture registry can construct a fresh `MessageTypeDefRegistry` or call
`DEFAULT_REGISTRY.reset([...])`.

## Error Handling

### Exception Types

```python
from services.llm.exceptions import (
    LLMError,
    APITimeoutError,
    APIConnectionError,
    APIResponseError,
    MaxRetriesExceededError,
    ConfigurationError,
    ModelNotFoundError
)
```

### Error Flow

1. **API Call** → Timeout / Connection → Retry (3× max)
2. **API Success** → JSON Parsing → Schema Validation
3. **Validation Failure** → ValueError → APIResponseError → retry or
   raise
4. **Max Retries Exceeded** → ERROR `llm_call` log record →
   `MaxRetriesExceededError`

### Error Recovery

```python
import asyncio
import uuid

from services.llm.wrapper import LLMWrapper
from services.llm.exceptions import MaxRetriesExceededError


async def generate(query: str, correlation_id: str) -> str | None:
    wrapper = LLMWrapper()
    try:
        message = await wrapper.call_api(
            message_type_slug="intent_generation",
            unique_prompt=query,
            session_uuid=correlation_id,
        )
        return message.raw_response
    except MaxRetriesExceededError:
        # API failed after the configured number of retries.
        print("API temporarily unavailable, using fallback logic")
        return fallback_logic(query)
```

## JSON Schema Structure

### Intent Generation Schema

```json
{
  "query_analysis": {
    "original_query": "string",
    "core_questions": ["string"],
    "context_clues": ["string"]
  },
  "intents": [
    {
      "intent_id": "string",
      "interpretation": "string",
      "keywords_explicit": ["string"],
      "keywords_inferred": ["string"],
      "themes": ["string"],
      "confidence": 0.0-1.0,
      "is_primary": true
    }
  ]
}
```

## Testing

### Running Tests

```bash
# AIMessage parsing + retry retry/parsing/fixture tests
.venv/bin/python tests/scripts/test_pipeline_offline.py

# LLMWrapper-only retry tests
.venv/bin/python tests/scripts/test_embedding_service.py
.venv/bin/python tests/scripts/test_intent_service.py
.venv/bin/python tests/scripts/test_hyde_service.py

# MCP server tool tests
.venv/bin/python tests/scripts/test_mcp_server.py

# JSONL formatter / configure tests
.venv/bin/python tests/scripts/test_logging.py
```

### Test Coverage

- JSON extraction from various formats (fenced / prose / pure JSON)
- Schema validation
- Error handling and retry scenarios
- Response parsing lifecycle (success / failure / max retries)
- JSONL formatter output shape

## Integration Points

- **Intent Service**: Uses wrapper for structured intent generation
- **HyDE Service**: Uses wrapper for hypothetical passage generation
- **Embeddings / Retrieval**: LLM + ChromaDB for verse retrieval
- **Message-type Registry**: Static config source of truth
- **JSONL Audit**: All calls recorded to `data/logs/strongchat.log`
  keyed by `correlation_id`

## Future Extensions

### Pipeline Steps

1. **Intent Generation** ✅
2. **HyDE Generation** ✅
3. **Embeddings / Retrieval** ✅
4. **Response Synthesis** — typically agent-side, not server-side
5. **Validation (`validate_answer` MCP tool)** — contract locked in
   today; implementation is the next major milestone

### Performance Optimizations

- Response caching with TTL (per slug + prompt hash)
- Connection pooling at the aiohttp ClientSession level
- Request batching
- Streaming responses

## Deployment

### Dependencies

`requirements.txt`:

```
aiohttp
jsonschema
requests
python-dotenv
chromadb
mcp
concurrent-log-handler
```

### Environment Setup

```bash
export OPENROUTER_API_KEY=your_api_key_here
# Optional logging:
export STRONGCHAT_LOG_LEVEL=ERROR  # default if unset; INFO or DEBUG
```

## Troubleshooting

1. **API Key Not Configured**
   ```
   ConfigurationError: OpenRouter API key not configured
   ```
   Solution: Set `OPENROUTER_API_KEY` environment variable.

2. **JSON Parsing Errors**
   ```
   ValueError: Response is not valid JSON: ...
   ```
   Solution: Check LLM response format against the registered schema for
   the slug.

3. **API Timeouts**
   ```
   APITimeoutError: API call timed out after 30.0s
   ```
   Solution: Check network connectivity; the wrapper retries transient
   timeout errors up to `max_retries` times.

4. **Max Retries Exceeded**
   ```
   MaxRetriesExceededError: API call failed after 3 attempts: ...
   ```
   Solution: Check OpenRouter status and implement fallback logic for
   transient outages; consider raising `max_retries` on the affected
   `MessageTypeDef` instance.

5. **No correlation id in logs**
   The `correlation_id` field on a log record is the per-pipeline-run UUID
   generated by `PipelineRunner.run()`. Slice a single pipeline run with
   `grep <correlation_id> data/logs/strongchat.log | jq .`.

## Contributing

### Adding New Schemas

1. Add schema to `src/config/schemas.py`
2. The wrapper auto-validates responses against the registered
   `MessageTypeDef.request_schema` via `AIMessage.get_parsed_response`; no
   manual parser wiring required.
3. Add comprehensive error logging.

### Adding New Message Types

1. Add a new `MessageTypeDef(...)` instance in
   `src/config/llm_models.py` and register it in `DEFAULT_MESSAGE_TYPES`.
2. `DEFAULT_REGISTRY` picks it up at import time automatically.

### Adding New Prompts

1. Add the prompt template to `src/config/prompts.py` and reference it
   on the corresponding `MessageTypeDef.prompt_template` field.
2. Ensure the prompt is pipeline-agnostic (no leakage of the user query
   into HyDE).
3. Test with schema validation.

### Error Handling

1. Add new exception types to `src/services/llm/exceptions.py`.
2. Wrap `wrapper.call_api(...)` calls in
   `try / except MaxRetriesExceededError` (or `APIResponseError` if you
   parse the response yourself).