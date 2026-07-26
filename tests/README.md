# Integration Tests for LLM Message System

This directory contains integration tests for the new database-driven LLM message system. Tests are designed to verify the complete workflow from database setup to API calls and message tracking.

## Test Philosophy

- **Message-level testing**: Tests focus on complete message workflows rather than individual components
- **Integration-first**: Tests verify that components work together correctly
- **Schema-driven**: Tests validate that the database schema drives the system behavior
- **Error handling**: Tests cover both successful and failure scenarios

## Test Structure

### 1. Database Setup Tests (`test_database_setup.py`)
- Verify new database schema creation
- Test message types table population
- Validate foreign key relationships

### 2. Message Workflow Tests (`test_message_workflow.py`)
- Complete message lifecycle: creation → API call → parsing → storage
- Test retry logic and error handling
- Validate response parsing with schemas

### 3. LLM Wrapper Tests (`test_llm_wrapper.py`)
- API integration with retry logic
- Configuration loading from database
- Error handling and retry counting

### 4. Integration Tests (`test_integration.py`)
- End-to-end workflow tests
- Session management with multiple messages
- Message type routing and validation

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_message_workflow.py -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=html
```

## Test Data

### Mock API Responses
Tests use mock API responses to avoid real API calls during testing:

```python
MOCK_RESPONSES = {
    "intent_classification": {
        "intent": "question",
        "confidence": 0.95
    },
    "intent_disambiguation": {
        "query_analysis": {...},
        "interpretive_framings": [...],
        "recommended_framing": "framing_1"
    }
}
```

### Test Database
Tests use a separate test database (`data/test_chat_database.db`) to avoid interfering with production data.

## Test Scenarios

### Success Scenarios
1. **Basic message workflow**: User input → Intent classification → AI response → Storage
2. **Multiple message types**: Different configurations per message type
3. **Session management**: Multiple messages in a single session
4. **Response parsing**: JSON extraction and schema validation

### Error Scenarios
1. **API timeout**: Retry logic triggers
2. **API connection error**: Max retries exceeded
3. **Invalid response**: Schema validation fails
4. **Missing message type**: Configuration not found

### Edge Cases
1. **Empty responses**: Handle malformed API responses
2. **Max retry scenarios**: Verify proper error handling
3. **Database connection issues**: Graceful degradation

## Test Utilities

### Mock API Server
For testing API integration, tests include a mock API server that simulates different response scenarios.

### Database Helper Functions
Common database operations are abstracted into helper functions:

```python
def setup_test_database():
    """Create fresh test database with initial data"""
    
def get_test_message_type(slug):
    """Get message type from test database"""
    
def assert_message_saved(message_uuid, expected_fields):
    """Verify message was saved with correct fields"""
```

## Continuous Integration

These tests are designed to run in CI environments:
- No external dependencies (except test requirements)
- Fast execution with mocked API calls
- Deterministic results with seeded data

## Adding New Tests

When adding new message types or pipeline steps:

1. **Add to message_types table**: Update `populate_message_types.py`
2. **Create test scenario**: Add to appropriate test file
3. **Verify integration**: Test complete workflow
4. **Document**: Update this README with new test patterns

## Test Requirements

```txt
pytest>=7.0.0
pytest-asyncio>=0.21.0
pytest-cov>=4.0.0
aiohttp>=3.8.0
```

## Test Environment Setup

```bash
# Create test database
python scripts/create_new_database.py --db-path data/test_chat_database.db

# Populate test data
python scripts/populate_message_types.py --db-path data/test_chat_database.db

# Run tests
python -m pytest tests/ -v
```

## Debugging Tests

If tests fail:

1. **Check test database**: Verify schema and data
2. **Review mock responses**: Ensure they match expected schemas
3. **Check API configuration**: Verify environment variables
4. **Run with debug**: `python -m pytest tests/ -v -s --tb=long`