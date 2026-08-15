# LLM Framework Architecture

## Overview

The StrongChat LLM Framework provides a structured approach to handling LLM interactions with JSON schema validation, retry logic, and automated response parsing. It is designed to support the biblical search pipeline with proper error handling and auditability. `LLMWrapper` (`src/services/llm/wrapper.py`) is the canonical recorded-path client — database-driven, async, and the only LLM caller used by production services.

## Architecture

### Core Components

1. **Configuration Layer** (`src/config/`)
   - `schemas.py`: JSON schemas for response validation
   - `prompts.py`: Prompt templates (pipeline-agnostic)

2. **Wrapper Layer** (`src/services/llm/wrapper.py`)
   - `LLMWrapper`: Database-driven async LLM client with retry logic
   - Reads model, temperature, prompt template, max retries from `ref_message_types`
   - Records every call in the `messages` table
   - Exponential backoff (3 retries: 1s → 2s → 4s)
   - aiohttp async HTTP client
   - JSON schema validation

3. **AIMessage Layer** (`src/services/llm/aimessage.py`)
   - `AIMessage`: Pydantic model + strict-JSON parsing contract for LLM responses
   - Strict JSON-only parsing (no markdown fence extraction)
   - Pydantic v2 validation against `response_schema`
   - Records `raw_response` verbatim for auditability
   - Error handling for malformed responses

4. **Service Layer** (`src/services/`)
   - `base.py`: Shared `BaseService` foundation (owns one `LLMWrapper`, DB, and cache)
   - `llm/parser.py`: Standalone JSON schema validator (used by tests; the wrapper uses `aimessage.py`)
   - `llm/exceptions.py`: Custom exception classes
   - `intent/`, `hyde/`, `embeddings/`, `vectordb/`, `retrieval/`, `context/`, `pipeline/`: pipeline services

5. **Data Layer** (`data/`)
   - SQLite database for structured message storage

### Canonical Recorded Path

`LLMWrapper` (`src/services/llm/wrapper.py`) is the canonical LLM client for the pipeline. It records every call in the `messages` table, reads its configuration from `ref_message_types` (model, temperature, prompt template, max retries), and is the client inherited by `BaseService`. Every service that needs to talk to an LLM calls `await wrapper.call_api(...)`.

The four recorded message types used by the HyDE-retrieval pipeline are:

- `intent_generation`
- `hyde_generation`
- `embedding_generation`
- `corpus_ingest`

## Design Principles

1. **Separation of Concerns**: JSON schemas are completely separate from prompt templates; LLMs only know their immediate task, not pipeline context
2. **Type Safety**: Response models provide validated data access
3. **Error Resilience**: Exponential backoff retry (1s → 2s → 4s) with graceful degradation
4. **Auditability**: Every call recorded in the `messages` table linked to `ref_message_types`
5. **Async First**: aiohttp for future web server integration

## Usage Examples

### Basic Recorded Call

`LLMWrapper.call_api` is the only entry point for production code. It is async, reads model/prompt/retry config from the `ref_message_types` table (slug-driven), and persists the call to the `messages` table.

```python
import asyncio

from services.llm.wrapper import LLMWrapper


async def main():
    wrapper = LLMWrapper()
    message = await wrapper.call_api(
        message_type_slug="intent_generation",
        unique_prompt="why do bad things happen",
        session_uuid=session_uuid,
    )
    print(message.raw_response)
    wrapper.close()


asyncio.run(main())
```

### Custom Schema Integration

`LLMWrapper.call_api` reads its schema from `ref_message_types[slug].request_schema` and validates the response through `AIMessage.get_parsed_response`. No subclassing or client-side schema wiring is required:

```python
import asyncio

from config.cache import GlobalReferenceCache
from services.llm.wrapper import LLMWrapper


async def main():
    cache = GlobalReferenceCache()
    wrapper = LLMWrapper()

    intent_config = cache.get_message_type("intent_generation")
    message = await wrapper.call_api(
        message_type_slug="intent_generation",
        unique_prompt="user query",
        session_uuid=session_uuid,
    )
    parsed = message.get_parsed_response(intent_config["request_schema"])
    print(parsed)


asyncio.run(main())
```

## Configuration

### Environment Variables

```bash
OPENROUTER_API_KEY=your_api_key_here
MODEL_SLUG_INTENTS=mistralai/mistral-small-24b-instruct-2501
```

### Model Configuration (Database-Driven)

`LLMWrapper` does not take `model_config` in code — model, temperature, prompt template, and max retries are all stored in the `ref_message_types` table. To tune a message type, update its row (or reseed via `scripts/create_new_database.py`); every subsequent `call_api` picks it up through the cache.

## Error Handling

### Exception Types

```python
from services.llm.exceptions import (
    LLMError,
    APITimeoutError,
    APIConnectionError,
    APIResponseError,
    ResponseValidationError,
    ResponseParsingError,
    MaxRetriesExceededError,
    ConfigurationError,
    ModelNotFoundError
)
```

### Error Flow

1. **API Call** → Timeout/Connection → Retry (3x max)
2. **API Success** → JSON Parsing → Schema Validation
3. **Validation Failure** → stderr → Exception
4. **Max Retries Exceeded** → stderr → `MaxRetriesExceededError`

### Error Recovery

```python
import asyncio

from services.llm.wrapper import LLMWrapper
from services.llm.exceptions import MaxRetriesExceededError


async def generate(query: str, session_uuid: str) -> str | None:
    wrapper = LLMWrapper()
    try:
        message = await wrapper.call_api(
            message_type_slug="intent_generation",
            unique_prompt=query,
            session_uuid=session_uuid,
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
# Test parser functionality
.venv/bin/python tests/scripts/test_parser.py

# Test offline wrapper behavior (retry, parsing, fixtures)
.venv/bin/python tests/scripts/test_pipeline_offline.py
```

### Test Coverage

- JSON extraction from various formats
- Schema validation
- Error handling scenarios
- Response parsing

## Integration Points

- **Intent Service**: Uses wrapper for structured intent generation
- **HyDE Service**: Uses wrapper for hypothetical passage generation
- **Embeddings / Retrieval**: LLM + ChromaDB for verse retrieval
- **Database**: Stores every message and its message type
- **Audit Trail**: All calls logged in the `messages` table

## Future Extensions

### Pipeline Steps

1. **Intent Generation** ✅
2. **HyDE Generation** ✅
3. **Embeddings / Retrieval** ✅
4. **Response Synthesis** - Combine retrieved passages with original query
5. **Validation** - Fact-check responses against biblical text

### Performance Optimizations

- Response caching with TTL
- Connection pooling
- Request batching
- Streaming responses

## Deployment

### Dependencies

```bash
sudo apt install python3-aiohttp python3-jsonschema python3-requests
```

### Environment Setup

```bash
export OPENROUTER_API_KEY=your_api_key_here
export MODEL_SLUG_INTENTS=openai/gpt-3.5-turbo
```

## Troubleshooting

1. **API Key Not Configured**
   ```
   ConfigurationError: OpenRouter API key not configured
   ```
   Solution: Set `OPENROUTER_API_KEY` environment variable

2. **JSON Parsing Errors**
   ```
   ResponseValidationError: Schema validation error
   ```
   Solution: Check LLM response format against schema

3. **API Timeouts**
   ```
   APITimeoutError: API call timed out
   ```
   Solution: Check network connectivity and increase timeout

4. **Max Retries Exceeded**
   ```
   MaxRetriesExceededError: API call failed after 3 attempts
   ```
   Solution: Check API status and implement fallback logic

## Contributing

### Adding New Schemas

1. Add schema to `src/config/schemas.py`
2. The wrapper auto-validates responses against `ref_message_types[slug].request_schema` via `AIMessage.get_parsed_response`; no manual parser wiring required.
3. Add comprehensive error logging

### Adding New Prompts

1. Add prompt template to `src/config/prompts.py` and reference it from the corresponding `ref_message_types.prompt_template` row
2. Ensure prompt is pipeline-agnostic
3. Test with schema validation

### Error Handling

1. Add new exception types to `src/services/llm/exceptions.py`
2. Wrap `wrapper.call_api(...)` calls in `try/except MaxRetriesExceededError` (or `ResponseValidationError` if you parse the response yourself)
