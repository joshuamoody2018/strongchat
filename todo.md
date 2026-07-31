# TODO - StrongChat Development Tasks

## Next Steps Implementation

### Phase 1: Structured Response Framework ✅
- [x] Create src/config/schemas.py with INTENT_GENERATION_SCHEMA
- [x] Create src/config/prompts.py with INTENT_GENERATION_PROMPT
- [x] Create src/services/llm/parser.py with automated JSON parsing
- [x] Create src/services/llm/client.py with retry/backoff logic
- [x] Create src/services/llm/exceptions.py for error handling
- [x] Create src/services/llm/__init__.py and src/config/__init__.py

### Phase 2: Intent Service Refactor ✅
- [x] Update src/services/intent/service.py to use the wrapper framework
- [x] Define intent response models in src/services/llm/parser.py
- [x] Update database schema to store structured intent data

### Phase 3: Testing
- [ ] Create comprehensive tests for response parsing
- [ ] Test schema validation with malformed responses
- [ ] Test retry/backoff logic with mock failures
- [ ] Test error routing to stderr
- [ ] Test async functionality with real API calls

### Phase 4: Migration
- [ ] Replace current get_message_intent() with new structured approach
- [ ] Add audit logging for intent disambiguation decisions
- [ ] Implement fallback logic for parsing failures
- [ ] Update main.py to use new LLM client

### Phase 5: Expand Framework
- [x] Add HYDE_GENERATION_SCHEMA and prompt
- [ ] Add RESPONSE_SYNTHESIS_SCHEMA and prompt
- [ ] Create additional response models for different pipeline steps
- [x] Implement model routing (cheap intent model vs expensive HyDE model)
- [x] Add EmbeddingService for batched OpenRouter embeddings
- [x] Add RetrievalService for HyDE → Chroma verse search
- [x] Add PipelineRunner orchestrator and CLI runner

## Deferred Error Handling & Async Implementation

### Error Handling Improvements
- [ ] Implement proper error logging with structured logging
- [ ] Create error monitoring and alerting system
- [ ] Add circuit breaker pattern for API failures
- [ ] Implement graceful degradation when LLM unavailable
- [ ] Add user-friendly error messages for validation failures
- [ ] Create error recovery strategies for different error types

### Async Implementation
- [ ] Replace sync HTTP calls with aiohttp for true async
- [x] Create DatabasePort protocol and AsyncSQLiteDatabase adapter
- [ ] Migrate LLMWrapper and BaseService to write messages through DatabasePort
- [ ] Add async production database adapter (e.g., asyncpg) behind DatabasePort when hosted DB is chosen
- [ ] Add async context managers for resource cleanup
- [ ] Implement async batch processing for multiple queries
- [ ] Add async queue for processing pipeline steps
- [ ] Implement async web server integration (Quart)

### Performance Optimizations
- [ ] Add response caching with TTL
- [ ] Implement connection pooling for API calls
- [ ] Add request batching for efficiency
- [ ] Implement streaming responses for large outputs
- [ ] Add rate limiting and quota management

### Production Readiness
- [ ] Add comprehensive monitoring and metrics
- [ ] Implement health checks and readiness probes
- [ ] Add configuration management for different environments
- [ ] Implement proper logging and tracing
- [ ] Add security hardening and input validation
- [ ] Add API key rotation and management

### Documentation
- [ ] Create comprehensive API documentation
- [ ] Add usage examples for different pipeline steps
- [ ] Create migration guide from old to new system
- [ ] Add troubleshooting guide for common errors

### Testing Infrastructure
- [ ] Create test fixtures for various response formats
- [ ] Add integration tests for full pipeline
- [ ] Implement property-based testing for edge cases
- [ ] Add performance benchmarking
- [ ] Create chaos engineering tests for failure scenarios

### Deployment
- [ ] Create Docker configuration
- [ ] Add deployment scripts for different environments
- [ ] Implement canary deployments for new features
- [ ] Add database migration scripts
- [ ] Create backup and recovery procedures