# LLM Framework Architecture

## Overview

The LLM Framework provides structured, validated LLM interactions with robust error handling and async support. `LLMWrapper` (`src/services/llm/wrapper.py`) is the canonical recorded-path client — database-driven, async, and the only LLM caller used by production services.

## Core Components

### 1. Wrapper Layer (`src/services/llm/wrapper.py`)
```python
class LLMWrapper:
    """Database-driven async LLM client with retry logic"""

    Key Features:
    - Reads model, temperature, max_tokens from ref_message_types
    - Records every call in the messages table
    - Exponential backoff (3 retries: 1s -> 2s -> 4s)
    - aiohttp async HTTP client
    - JSON schema validation
```

### 2. AIMessage Layer (`src/services/llm/aimessage.py`)
```python
class AIMessage:
    """Pydantic model + strict-JSON parsing contract for LLM responses."""

    Key Features:
    - Strict JSON-only parsing (no markdown fence extraction)
    - Pydantic v2 validation against `response_schema`
    - Records raw_response verbatim for auditability
    - Error handling for malformed responses
```

### 3. Configuration Layer (`src/config/`)
```python
# schemas.py - JSON response validation
# prompts.py - Pipeline-agnostic prompts
```

### 4. Error Handling (`src/services/llm/exceptions.py`)
```python
Custom Exceptions:
- MaxRetriesExceededError: API failures after 3 retries
- ResponseValidationError: Schema validation failures
- ResponseParsingError: JSON parsing failures
- APIConnectionError: Network issues
```

## Usage Patterns

### Basic Intent Generation
```python
from services.llm.wrapper import LLMWrapper
import asyncio

async def main():
    wrapper = LLMWrapper()
    message = await wrapper.call_api(
        message_type_slug="intent_generation",
        unique_prompt="why do bad things happen",
        session_uuid=session_uuid
    )
    print(message.raw_response)

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

## Design Principles

1. **Pipeline Agnostic**: LLMs unaware of broader context
2. **Type Safety**: Response models provide validated data access
3. **Error Resilience**: Retry logic with graceful degradation
4. **Auditability**: Every call recorded in the database
5. **Async First**: aiohttp for future web server integration

## Response Structure

### Intent Generation Response
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

## Error Flow

1. **API Call** -> Timeout/Connection -> Retry (3x max)
2. **API Success** -> JSON Parsing -> Schema Validation
3. **Validation Failure** -> stderr -> Exception
4. **Max Retries Exceeded** -> stderr -> MaxRetriesExceededError

## Integration Points

- **Intent Service**: Uses wrapper for structured intent generation
- **HyDE Service**: Uses wrapper for hypothetical passage generation
- **Database**: Stores every message and its message type
- **Pipeline Steps 2-3**: Provide intents and HyDE documents for retrieval
- **Audit Trail**: All calls logged in the messages table

## Testing

- Parser validation tests
- LLM wrapper retry tests
- Embedding service retry tests

## Dependencies

- `aiohttp`: Async HTTP client
- `jsonschema`: Response validation
- Standard Python async/await patterns

## File Locations

- Implementation: `src/services/llm/`
- Configuration: `src/config/`
- Tests: `tests/scripts/test_*.py`, `tests/test_*.py`
- Documentation: `LLM_FRAMEWORK.md`
