# StrongChat LLM Framework Documentation

## Overview

The StrongChat LLM Framework provides a structured approach to handling LLM interactions with JSON schema validation, retry logic, and automated response parsing. This framework is designed to support the biblical search pipeline with proper error handling and auditability.

## Architecture

### Core Components

1. **Configuration Layer** (`src/config/`)
   - `schemas.py`: JSON schemas for response validation
   - `prompts.py`: Prompt templates (pipeline-agnostic)
   - `models.py`: Model configurations

2. **Service Layer** (`src/services/`)
   - `base.py`: Shared `BaseService` foundation (owns one `LLMWrapper`, DB, and cache)
   - `llm/`: LLM client and utilities
     - `wrapper.py`: Canonical async LLM client with database-driven config and retry logic
     - `aimessage.py`: JSON response parser and validation
     - `parser.py`: Standalone JSON schema validator (used by tests; the wrapper uses `aimessage.py`)
     - `exceptions.py`: Custom exception classes
   - `intent/`: Intent generation service
   - `hyde/`: HyDE generation service
   - `embeddings/`: Batched embedding service
   - `vectordb/`: ChromaDB verse store
   - `retrieval/`: HyDE → verse retrieval service
   - `pipeline/`: Pipeline orchestrator

3. **Data Layer** (`data/`)
   - SQLite database for structured intent storage

### Canonical Recorded Path

`LLMWrapper` (`src/services/llm/wrapper.py`) is the canonical LLM client for the pipeline. It records every call in the `messages` table, reads its configuration from `ref_message_types` (model, temperature, prompt template, max retries), and is the client inherited by `BaseService`. Every service that needs to talk to an LLM calls `await wrapper.call_api(...)`.

The four recorded message types used by the HyDE-retrieval pipeline are:

- `intent_generation`
- `hyde_generation`
- `embedding_generation`
- `corpus_ingest`

## Design Decisions

### 1. Separation of Concerns

- **Schemas vs Prompts**: JSON schemas are completely separate from prompt templates
- **LLM Ignorance**: LLMs only know their immediate task, not pipeline context
- **Response Models**: Type-safe Python objects for parsed responses

### 2. Error Handling Strategy

- **Exponential Backoff**: 3 retries with 1s → 2s → 4s backoff
- **Error Routing**: Validation errors go to stderr (as requested)
- **Graceful Degradation**: API failures trigger error handling after max retries

### 3. Async Architecture

- **aiohttp**: True async HTTP client for performance
- **Async First**: All API calls are async-compatible
- **Future Ready**: Designed for Quart web server integration

### 4. Auditability

- **Structured Logging**: All intent disambiguation decisions are logged
- **JSON Schema Validation**: Ensures response consistency
- **Separate Steps**: Intent disambiguation is separate from HyDE generation

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

## Configuration

### Environment Variables

```bash
OPENROUTER_API_KEY=your_api_key_here
MODEL_SLUG_INTENTS=mistralai/mistral-small-24b-instruct-2501
```

### Model Configuration (Database-Driven)

`LLMWrapper` does not take `model_config` in code — model, temperature, prompt template, and max retries are all stored in the `ref_message_types` table. To tune a message type, update its row (or seed via `scripts/migrate_pipeline_message_types.py`); every subsequent `call_api` picks it up through the cache.

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
  ],
  "recommended_search_approach": "string"
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

### Common Issues

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