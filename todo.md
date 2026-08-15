# TODO - StrongChat Development Tasks

## Next Steps Implementation

### Phase 1: Structured Response Framework ✅
- [x] Create src/config/schemas.py with INTENT_GENERATION_SCHEMA
- [x] Create src/config/prompts.py with INTENT_GENERATION_PROMPT
- [x] Create src/services/llm/aimessage.py with strict JSON parsing
- [x] Create src/services/llm/client.py with retry/backoff logic
- [x] Create src/services/llm/exceptions.py for error handling
- [x] Create src/services/llm/__init__.py and src/config/__init__.py

### Phase 2: Intent Service Refactor ✅
- [x] Update src/services/intent/service.py to use the wrapper framework
- [x] Define intent response models in src/services/llm/aimessage.py
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

### Phase 6: Context Retrieval ✅
- [x] 1. Add context_constants module with POS weight table and scoring formula
- [x] 2. Download Macula Greek tokens and validate shape
- [x] 3. Build Macula Greek index SQLite table
- [x] 4. Compute Strong's frequency table from Macula
- [x] 5. Ingest STEPBible TBESG + Thayer's sense counts and definitions
- [x] 6. Extend migration script with context_retrieval ref-message-type row
- [x] 7. Add ContextRetrievalService with offline test
- [x] 8. Wire ContextRetrievalService into PipelineRunner and extend trace regression test
- [x] 9. Add live end-to-end integration test for context retrieval
- [x] 10. Add offline test for context retrieval within the full pipeline
- [x] 11. Update architecture documentation for the context retrieval pipeline

### Macula schema follow-up ✅ (2026-08-16)
- [x] Add `gloss` column to `macula_tokens` and re-ingest from TSV
- [x] Fix strongs-key format mismatch between `lexicon_definitions` (was `G0976`)
      and `macula_tokens`/`strongs_frequency` (bare int `976`): normalize at
      ingest in `scripts/build_lexicon_index.py` (`normalize_strongs` helper)
- [x] Add ingest-time format-drift validation that fails loudly on regression
- [x] Add regression canaries to all 3 context-retrieval test files
      (`definitions` non-empty, `gloss` non-empty, per-word schema validation)

## Next steps

### Short Term
- Fix stale online tests: 5 files in `tests/system/` (`test_intent.py`,
  `test_json_api.py`, `test_real_api.py`, `test_refreshed_cache.py`,
  `test_final_system.py`) reference the removed `intent_classification`
  message-type slug (only `intent_generation` is seeded now). Either delete
  them or rewrite them against the current `intent_generation` schema.
- Fix `ContextRetrievalService` concurrency bug: a single shared
  `sqlite3.connect(..., check_same_thread=False)` connection is touched by
  parallel `asyncio.to_thread` calls without the declared `self._macula_lock`
  being acquired anywhere. Causes intermittent `InterfaceError: bad parameter
  or other API misuse` under live parallel intent processing.
- Hebrew OT Macula integration (architecture/high-level.md notes 'OT: TBD')

### Medium Term
- Implement RRF ranking (steps 5-6)
- Implement response synthesis (step 10)
- Add evaluator loop (step 11)
- Add validator (step 12)

### Long Term
- Complete full pipeline integration (steps 5-13)
- Add production monitoring
- Optimize performance and scalability
- Evaluate DB layer: keep SQLite with per-task short-lived connections, or
  migrate to a server-style DB (Postgres) once concurrent load demands it
  (see notes below)