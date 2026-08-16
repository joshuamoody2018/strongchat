# Deferred Error Handling & Async Implementation

## `validate_answer` MCP tool implementation (deferred from MCP plan)
- [ ] Implement the `validate_answer` tool body in `src/server.py`
  (replace the `NotImplementedError` stub with the planned return shape).
- [ ] Build the fact-check library: take `(answer, context=<bundle>)`,
  parse claims + citation references out of the answer, and verify each
  against the per-intent traces' `context_bundle` data in the bundle.
- [ ] Emit structured agent-actionable feedback:
  `{valid, unsupported_claims, missing_coverage, suggested_refinement}`.
  That output is what makes the agent loop useful rather than a black box.
- [ ] Add tests for `validate_answer` shape and at least one passing +
  one failing case (mocked LLM underneath; the same `assertLogs` /
  bundle-shape pattern used in `tests/scripts/test_mcp_server.py`).

## RRF (steps 5-6) + graph expansion (step 8)
- [ ] Implement RRF Level 1 (intra-intent merge) and Level 2
  (cross-intent merge) as a new `src/services/rrf/` module.
- [ ] Wire RRF Stage output into `PipelineRunner.run()` between retrieval
  and context lookup.
- [ ] Implement lemma/verse-graph traversal (step 8) as a new
  `src/services/graph/` module (or extend the existing context service).
- [ ] Update `docs/architecture-diagram.md` once both land.

## Async Implementation
- [ ] Add async context managers for resource cleanup where helpful
- [ ] Implement async batch processing for multiple queries (e.g. when an
  agent drives parallel `retrieve_context` calls)
- [ ] Add async queue for processing pipeline steps if a hosted variant
  of the server ever materialises

## Database Client Modernization — N/A after the MCP strip
The MCP pivot removed the application database entirely. The remaining
SQLite surface is the read-only Macula index (`data/macula_index.db`),
which intentionally uses per-call short-lived `sqlite3.connect` (no
shared connection, no concurrency hazard). Do not re-introduce a
long-lived DB client without revisiting the MCP-era design first.

## Context Retrieval Tuning Knobs (deferred from context-retrieval plan)
- [ ] Consider moving the POS weight table from a Python `dict` in
  `src/config/context_constants.py` into a SQLite lookup table. **Reasoning
  for NOT doing this now** (carried forward unchanged from the prior era):
  POS codes are fixed morphological categories from the Robinson (Greek)
  and HAM (Hebrew) standards — they are not tunable parameters but stable
  linguistic facts. An ~20-entry Python dict is O(1), version-controlled,
  trivially testable, ships in code review, and needs no schema migration.
  Reopen this if a per-corpus or per-domain override becomes desirable.

## Performance Optimizations
- [ ] Add response caching with TTL (keyed by slug + prompt hash)
- [ ] Implement connection pooling at the aiohttp ClientSession level
  (one shared session across the singleton `PipelineRunner` lifetime)
- [ ] Add request batching for efficiency
- [ ] Implement streaming responses for large outputs (mainly an MCP
  transport concern — only revisit if the agent landscape demands it)
- [ ] Add rate limiting and quota management (OpenRouter-side already
  throttles; revisit only if 429s become frequent in practice)

## Production Readiness
- [ ] Add comprehensive monitoring and metrics on the JSONL audit log
  (e.g. per-step latency percentiles, error rate)
- [ ] Implement health checks and readiness probes (only if/when an
  HTTP/SSE transport variant is added; the stdio server has no health
  surface today)
- [ ] Add configuration management for different environments (each env
  sets its own `STRONGCHAT_LOG_LEVEL` / `STRONGCHAT_LOG_FILE`)
- [ ] Implement proper tracing (each `correlation_id` is one trace; the
  JSONL log already carries the field; consider emitting OpenTelemetry
  spans if a tracing aggregator is added)
- [ ] Add security hardening and input validation (query length cap,
  translation whitelist, top_k bounds)
- [ ] Add API key rotation and management

## Documentation
- [ ] Create comprehensive API documentation for the MCP tool surface
- [ ] Add usage examples for different agent clients (Claude Desktop,
  opencode, ChatGPT)
- [ ] Create migration guide from old `dev` / SQLite-era code to the new
  MCP `mcp` branch
- [ ] Add troubleshooting guide for common errors (key issues, missing
  chroma path, missing macula_index.db, log level mismatches)

## Testing Infrastructure
- [ ] Create test fixtures for various LLM response formats (covered by
  `test_pipeline_offline.py` today; could be a shared `fixtures/` dir)
- [ ] Add integration tests for the full pipeline (currently
  `tests/system/test_pipeline_e2e.py` covers the live path)
- [ ] Implement property-based testing for edge cases (hypothesis on
  `AIMessage` parsing, `pipeline_result_to_bundle` round-trip)
- [ ] Add performance benchmarking
- [ ] Create chaos engineering tests for failure scenarios (rate-limit
  injection, partial Macula outages, malformed LLM responses)

## Deployment
- [ ] Create Docker configuration (only if/when a hosted transport
  variant is added; stdio MCP servers do not containerize usefully)
- [ ] Add deployment scripts for different environments
- [ ] Implement canary deployments for new features
- [ ] Create backup and recovery procedures for read-only assets (the
  ChromaDB directory and Macula index can be re-ingested from
  `scripts/setup_environment.sh`; no separate backup script is needed
  unless the rebuild time becomes operationally painful)