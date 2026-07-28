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
     - `wrapper.py`: Canonical recorded-path LLM client with async support
     - `client.py`: Original LLM client (kept for compatibility)
     - `aimessage.py`: JSON response parser and validation
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

`LLMWrapper` (`src/services/llm/wrapper.py`) is the canonical LLM client for the pipeline. It records every call in the `messages` table and is the client inherited by `BaseService`. The older `LLMClient` (`src/services/llm/client.py`) is kept for compatibility but is not used by new services.

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

### Basic Intent Disambiguation

```python
from services.llm.client import LLMClient
import asyncio

async def main():
    client = LLMClient()
    
    try:
        response = await client.disambiguate_intent("why do bad things happen")
        print(f"Recommended framing: {response.recommended_framing}")
        for framing in response.interpretive_framings:
            print(f"- {framing['framing_id']}: {framing['interpretation']}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
```

### Custom Schema and Prompt

```python
from services.llm.client import LLMClient
from config.schemas import INTENT_DISAMBIGUATION_SCHEMA

async def custom_intent_analysis(query: str):
    client = LLMClient()
    
    response = await client.call_with_schema(
        prompt_template=INTENT_DISAMBIGUATION_PROMPT,
        response_schema=INTENT_DISAMBIGUATION_SCHEMA,
        response_model_name="intent_disambiguation",
        query=query
    )
    
    return response
```

## Configuration

### Environment Variables

```bash
OPENROUTER_API_KEY=your_api_key_here
MODEL_SLUG_INTENTS=openai/gpt-3.5-turbo
```

### Model Configuration

```python
model_config = {
    "max_retries": 3,
    "initial_backoff": 1.0,
    "max_backoff": 30.0,
    "timeout": 30.0
}

client = LLMClient(model_config)
```

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
try:
    response = await client.disambiguate_intent(query)
except MaxRetriesExceededError:
    # Handle API failure after 3 retries
    print("API temporarily unavailable, using fallback logic")
    response = fallback_logic(query)
except ResponseValidationError:
    # Handle malformed response
    print("Response validation failed, check logs")
```

## JSON Schema Structure

### Intent Disambiguation Schema

```json
{
  "query_analysis": {
    "original_query": "string",
    "ambiguous_elements": ["string"],
    "core_question": "string",
    "context_clues": ["string"]
  },
  "interpretive_framings": [
    {
      "framing_id": "string",
      "interpretation": "string",
      "keywords": ["string"],
      "disambiguation_note": "string",
      "confidence": 0.0-1.0
    }
  ],
  "recommended_framing": "string"
}
```

## Testing

### Running Tests

```bash
# Test parser functionality
python3 scripts/test_parser.py

# Test full LLM framework (requires API key)
python3 scripts/test_llm_framework.py
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
2. Create corresponding response model in `src/services/llm/parser.py`
3. Update client parsers in `src/services/llm/client.py`

### Adding New Prompts

1. Add prompt template to `src/config/prompts.py`
2. Ensure prompt is pipeline-agnostic
3. Test with schema validation

### Error Handling

1. Add new exception types to `src/services/llm/exceptions.py`
2. Update error handlers in client
3. Add comprehensive error logging