# LLM Framework Architecture

## Overview

The LLM Framework provides structured, validated LLM interactions with robust error handling and async support. Designed for biblical search pipeline integration with proper auditability.

## Core Components

### 1. Client Layer (`src/services/llm/client.py`)
```python
class LLMClient:
    """Async LLM client with retry logic and response validation"""
    
    Key Features:
    - Exponential backoff (3 retries: 1s → 2s → 4s)
    - aiohttp async HTTP client
    - JSON schema validation
    - Error routing to stderr
    - Type-safe response models
```

### 2. Parser Layer (`src/services/llm/parser.py`)
```python
class ResponseParser:
    """Automated JSON parsing with schema validation"""
    
    Key Features:
    - JSON extraction from markdown/plain text
    - JSON Schema validation
    - BaseResponseModel for type safety
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

### Basic Intent Disambiguation
```python
from services.llm.client import LLMClient

client = LLMClient()
response = await client.disambiguate_intent("query")
# Returns structured IntentDisambiguationResponse
```

### Custom Schema Integration
```python
response = await client.call_with_schema(
    prompt_template=INTENT_DISAMBIGUATION_PROMPT,
    response_schema=INTENT_DISAMBIGUATION_SCHEMA,
    response_model_name="intent_disambiguation",
    query="user query"
)
```

## Design Principles

1. **Pipeline Agnostic**: LLMs unaware of broader context
2. **Type Safety**: Response models provide validated data access
3. **Error Resilience**: Retry logic with graceful degradation
4. **Auditability**: Structured logging and validation
5. **Async First**: aiohttp for future web server integration

## Response Structure

### Intent Disambiguation Response
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

## Error Flow

1. **API Call** → Timeout/Connection → Retry (3x max)
2. **API Success** → JSON Parsing → Schema Validation
3. **Validation Failure** → stderr → Exception
4. **Max Retries Exceeded** → stderr → MaxRetriesExceededError

## Integration Points

- **Intent Service**: Uses framework for query disambiguation
- **Database**: Stores structured intent responses
- **Pipeline Step 2**: Provides N candidate framings for HyDE
- **Audit Trail**: All decisions logged with JSON format

## Testing

- ✅ Parser validation tests (6/6 passing)
- 🚧 Integration tests (planned)
- 🚧 Error handling tests (planned)

## Dependencies

- `aiohttp`: Async HTTP client
- `jsonschema`: Response validation
- Standard Python async/await patterns

## File Locations

- Implementation: `src/services/llm/`
- Configuration: `src/config/`
- Tests: `scripts/test_*.py`
- Documentation: `LLM_FRAMEWORK.md`