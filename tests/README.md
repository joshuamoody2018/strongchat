# Integration Tests for LLM Message System

This directory contains integration tests for the new database-driven LLM message system. Tests are designed to verify the complete workflow from database setup to API calls and message tracking.

## Test Organization

This test suite is organized into three main categories:

### Integration Tests (`tests/`)
Focus on the complete database-driven LLM message system workflow, testing how components work together in the full pipeline.

### Script Tests (`tests/scripts/`)
Standalone script-style tests that exercise services and components directly. These are not pytest tests and should be run as individual scripts.

### System Tests (`tests/system/`)
Focus on individual components and specific scenarios, providing more granular testing of system parts and edge cases. Many require a live `OPENROUTER_API_KEY`.

## Test Philosophy

- **Message-level testing**: Tests focus on complete message workflows rather than individual components
- **Integration-first**: Tests verify that components work together correctly
- **Schema-driven**: Tests validate that the database schema drives the system behavior
- **Error handling**: Tests cover both successful and failure scenarios

## Test Structure

### 1. Integration Tests (`/tests/`)
Integration tests for the database-driven LLM message system:

#### Integration Test Files:
- **Database Setup Tests** (`test_database_setup.py`)
  - Verify new database schema creation
  - Test message types table population
  - Validate foreign key relationships
  
- **Message Workflow Tests** (`test_message_workflow.py`)
  - Complete message lifecycle: creation → API call → parsing → storage
  - Test retry logic and error handling
  - Validate response parsing with schemas
  
- **Integration Tests** (`test_integration.py`)
  - End-to-end workflow tests
  - Session management with multiple messages
  - Message type routing and validation

### 2. Script Tests (`/tests/scripts/`)
Standalone script-style tests for services and components. Run each file directly with Python:

#### Script Test Files:
- **Database Tests** (`test_database_queries.py`, `test_database_port.py`)
  - Verify database queries, schema, and port handling
- **Embedding Tests** (`test_embedding_service.py`)
  - Validate embedding service behavior
- **HyDE Tests** (`test_hyde_schema.py`, `test_hyde_service.py`)
  - Validate HyDE schema and service behavior
- **Intent Tests** (`test_intent_schema.py`, `test_intent_service.py`)
  - Validate intent schema and service behavior
- **Migration Tests** (`test_migration.py`)
  - Verify database migration logic
- **Pipeline Tests** (`test_pipeline_offline.py`, `test_pipeline_result_traces.py`)
  - Run offline pipeline validation
- **Retrieval Tests** (`test_retrieval_service.py`)
  - Validate retrieval service behavior

### 3. System Tests (`/tests/system/`)
End-to-end system tests for individual components and scenarios:

#### System Test Files:
- **Final System Tests** (`test_final_system.py`)
  - Test final system with concise prompts
  - Verify complete intent classification workflow
  
- **Intent Classification Tests** (`test_intent.py`)
  - Test the intent classification API directly
  - Validate intent classification functionality
  
- **API Tests** (`test_json_api.py`, `test_real_api.py`)
  - Test real API calls with intent classification
  - Validate JSON response parsing and validation
  - Test different API scenarios and configurations
  
- **Generation Tests** (`test_intent_generation.py`, `test_hyde_generation.py`)
  - Test live LLM generation for intent and HyDE
  
- **End-to-End Tests** (`test_pipeline_e2e.py`)
  - Run the complete pipeline against live APIs
  
- **Cache Tests** (`test_refreshed_cache.py`)
  - Test real API call with refreshed cache
  - Verify cache refresh functionality

## Running Tests

This project does not use pytest. Run tests directly with Python or via `unittest` for the top-level test modules.

```bash
# Run script-style tests directly
.venv/bin/python tests/scripts/test_database_queries.py
.venv/bin/python tests/scripts/test_intent_service.py
.venv/bin/python tests/scripts/test_pipeline_offline.py

# Run live system tests with OPENROUTER_API_KEY in the environment
set -a; . ./.env; set +a
.venv/bin/python tests/system/test_intent_generation.py
.venv/bin/python tests/system/test_hyde_generation.py
.venv/bin/python tests/system/test_pipeline_e2e.py

# Run top-level unittest tests
.venv/bin/python -m unittest tests.test_database_setup
.venv/bin/python -m unittest tests.test_message_workflow
.venv/bin/python -m unittest tests.test_integration
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
    "intent_generation": {
        "query_analysis": {...},
        "intents": [...]
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

1. **Add to ref_message_types table**: Update `migrate_pipeline_message_types.py`
2. **Create test scenario**: Add to appropriate test file
3. **Verify integration**: Test complete workflow
4. **Document**: Update this README with new test patterns

## Test Requirements

No pytest installation is required. The script-style tests run with the project virtual environment and standard library modules.

```txt
aiohttp>=3.8.0
```

## Test Environment Setup

```bash
# Create test database
.venv/bin/python scripts/create_new_database.py --db-path data/test_chat_database.db

# Populate test data
.venv/bin/python scripts/populate_message_types.py --db-path data/test_chat_database.db

# Run a quick script-style test
.venv/bin/python tests/scripts/test_database_queries.py
```

## Debugging Tests

If tests fail:

1. **Check test database**: Verify schema and data
2. **Review mock responses**: Ensure they match expected schemas
3. **Check API configuration**: Verify environment variables
4. **Run with verbose output**: Add logging or print statements to the script, then run it directly
