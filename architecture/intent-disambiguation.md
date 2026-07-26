# Intent Disambiguation Architecture

## Overview

Intent disambiguation service (Pipeline Step 2) for plain-language query analysis. Generates multiple interpretive framings to guide HyDE generation without biblical vocabulary.

## Purpose

**Disambiguate user queries** before committing to biblical framing. Raw questions like "why do bad things happen" could mean:
- Theodicy (theological)
- Job narrative (specific story)
- Pastoral comfort (practical)
- Doctrinal sovereignty (theological)

## Core Requirements

### 1. Plain-Language Analysis Only
- **Zero biblical vocabulary**: No "sin", "grace", "salvation", etc.
- **Secular interpretation**: Focus on what user is actually asking
- **Disambiguation**: Identify ambiguous elements and multiple meanings

### 2. Structured Output
- **Multiple framings**: 2-5 interpretations per query
- **Keywords**: Secular terms for embedding search
- **Confidence scores**: 0.0-1.0 likelihood estimates
- **Recommendation**: Most likely interpretation

### 3. Auditability
- **Separate from HyDE**: Isolated step for failure analysis
- **Logged decisions**: All framings stored in database
- **Model routing**: Cheap intent model vs expensive HyDE model

## Current Implementation Status

### Framework Ready ✅
- LLM client with JSON validation
- Response parser with schema
- Error handling and retry logic
- Type-safe response models

### Service Integration 🚧
- Database schema update for structured intent storage
- Main application integration
- Fallback logic for API failures

## Response Structure

```json
{
  "query_analysis": {
    "original_query": "why do bad things happen",
    "ambiguous_elements": ["bad things"],
    "core_question": "Why does suffering occur?",
    "context_clues": ["suffering", "pain"]
  },
  "interpretive_framings": [
    {
      "framing_id": "theodicy",
      "interpretation": "Understanding why suffering exists in world",
      "keywords": ["suffering", "evil", "existence", "problem"],
      "disambiguation_note": "Focuses on philosophical problem of evil",
      "confidence": 0.8
    },
    {
      "framing_id": "narrative",
      "interpretation": "Looking for biblical stories about suffering",
      "keywords": ["story", "biblical", "account", "example"],
      "disambiguation_note": "Focuses on narrative examples",
      "confidence": 0.6
    }
  ],
  "recommended_framing": "theodicy"
}
```

## Integration Points

### 1. LLM Framework Usage
```python
from services.llm.client import LLMClient

client = LLMClient()
response = await client.disambiguate_intent("query")
# Returns structured IntentDisambiguationResponse
```

### 2. Database Storage
```python
# Store structured intent data
db.create_intent(
    message_uuid,
    json.dumps(response.to_dict())
)
```

### 3. HyDE Generation Input
```python
# Use framings for HyDE generation
for framing in response.interpretive_framings:
    hyde_passages = generate_hyde(
        framing['interpretation'],
        framing['keywords']
    )
```

## Error Handling

### API Failures
- **Retry logic**: 3 attempts with exponential backoff
- **Fallback**: Simple keyword-based disambiguation
- **Error routing**: stderr logging for debugging

### Validation Failures
- **Schema validation**: JSON structure enforcement
- **Confidence scores**: Range validation (0.0-1.0)
- **Framing requirements**: Minimum 2 framings

## Design Decisions

### 1. Separation from HyDE
- **Why**: Isolate failure points for debugging
- **Benefit**: Know if problem is intent understanding vs HyDE generation
- **Implementation**: Separate services with clear interfaces

### 2. Model Routing
- **Intent model**: Cheap/fast (e.g., gpt-3.5-turbo)
- **HyDE model**: Expensive/fluent (e.g., gpt-4)
- **Benefit**: Cost optimization and performance

### 3. Pipeline Agnostic
- **LLM ignorance**: No knowledge of biblical context
- **Plain language**: Focus on user intent, not theological framing
- **Benefit**: Reusable for non-biblical applications

## Testing Strategy

### Unit Tests
- Query parsing and disambiguation
- Response validation against schema
- Error handling scenarios

### Integration Tests
- LLM framework integration
- Database storage and retrieval
- End-to-end query processing

### Performance Tests
- API call timing and retry behavior
- Response parsing performance
- Concurrent query handling

## File Locations

- **Framework**: `src/services/llm/`
- **Service**: `src/services/intent/` (planned)
- **Schema**: `src/config/schemas.py`
- **Prompt**: `src/config/prompts.py`
- **Tests**: `scripts/test_*.py`

## Dependencies

- **LLM Framework**: Provides validated API interactions
- **Database**: Stores structured intent data
- **Configuration**: Schema and prompt definitions

## Next Steps

1. Complete service implementation
2. Update database schema for JSON storage
3. Integrate with main application
4. Add comprehensive testing
5. Implement fallback mechanisms