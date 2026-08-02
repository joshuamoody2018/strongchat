# Deferred Error Handling & Async Implementation

## Error Handling Improvements
- [ ] Implement proper error logging with structured logging
- [ ] Create error monitoring and alerting system
- [ ] Add circuit breaker pattern for API failures
- [ ] Implement graceful degradation when LLM unavailable
- [ ] Add user-friendly error messages for validation failures
- [ ] Create error recovery strategies for different error types

## Async Implementation
- [ ] Replace sync HTTP calls with aiohttp for true async
- [ ] Implement async database operations
- [ ] Add async context managers for resource cleanup
- [ ] Implement async batch processing for multiple queries
- [ ] Add async queue for processing pipeline steps
- [ ] Implement async web server integration (Quart)

## Database Client Modernization
- [ ] Move beyond hand-rolled parameterized SQL in `ChatDatabase` to a proper database client/strategy
- [ ] Define session lifecycle and connection management (open/close/pool/reconnect semantics)
- [ ] Support true async database operations without thread-pool workarounds
- [ ] Add connection pooling or equivalent concurrency control for SQLite
- [ ] Establish typed models and deserialisation for query results and JSON columns
- [ ] Introduce a versioned migration discipline for schema changes
- [ ] Keep any future database implementation contained behind the existing `DatabasePort` abstraction

## Context Retrieval Tuning Knobs (deferred from context-retrieval plan)
- [ ] Consider moving the POS weight table from a Python `dict` constant in `src/config/context_constants.py` into a SQLite lookup table (e.g. `pos_weights(pos_code TEXT PRIMARY KEY, weight REAL, category TEXT, updated_at TIMESTAMP)`). **Reasoning for NOT doing this now**: POS codes are fixed morphological categories from the Robinson (Greek) and HAM (Hebrew) standards — they are not tunable parameters but stable linguistic facts. A ~20-entry Python dict is O(1), version-controlled, trivially testable, ships in code review, and needs no schema migration. The deterministic dict matches the existing project convention (`EMBEDDING_ENDPOINT`, `DEFAULT_DIMENSION`, `MAX_BACKOFF` in `src/services/embeddings/service.py:25-29`). An embedded table would add (a) a migration step every time a category is added, (b) drift risk between code and DB, and (c) audit difficulty (DB rows lack git history). Reopen this if: (1) a future plan introduces per-corpus or per-domain overrides, (2) we want to A/B test scoring weights without redeploying, (3) the table grows past ~50 entries, or (4) we add a lexicon-tuning workflow that needs provenance metadata beyond what a code constant can express.

## Performance Optimizations
- [ ] Add response caching with TTL
- [ ] Implement connection pooling for API calls
- [ ] Add request batching for efficiency
- [ ] Implement streaming responses for large outputs
- [ ] Add rate limiting and quota management

## Production Readiness
- [ ] Add comprehensive monitoring and metrics
- [ ] Implement health checks and readiness probes
- [ ] Add configuration management for different environments
- [ ] Implement proper logging and tracing
- [ ] Add security hardening and input validation
- [ ] Add API key rotation and management

## Documentation
- [ ] Create comprehensive API documentation
- [ ] Add usage examples for different pipeline steps
- [ ] Create migration guide from old to new system
- [ ] Add troubleshooting guide for common errors

## Testing Infrastructure
- [ ] Create test fixtures for various response formats
- [ ] Add integration tests for full pipeline
- [ ] Implement property-based testing for edge cases
- [ ] Add performance benchmarking
- [ ] Create chaos engineering tests for failure scenarios

## Deployment
- [ ] Create Docker configuration
- [ ] Add deployment scripts for different environments
- [ ] Implement canary deployments for new features
- [ ] Add database migration scripts
- [ ] Create backup and recovery procedures