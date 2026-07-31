# Next Steps Implementation

## Phase 1: Structured Response Framework ✅
- [x] Create src/config/schemas.py with INTENT_GENERATION_SCHEMA
- [x] Create src/config/prompts.py with INTENT_GENERATION_PROMPT
- [x] Create src/services/llm/parser.py with automated JSON parsing
- [x] Create src/services/llm/client.py with retry/backoff logic
- [x] Create src/services/llm/exceptions.py for error handling
- [x] Create src/services/llm/__init__.py and src/config/__init__.py

## Phase 2: Intent Service Refactor
- [ ] Update src/services/intent/service.py to use the wrapper framework
- [ ] Define intent response models in src/services/llm/parser.py
- [ ] Update database schema to store structured intent data

## Phase 3: Testing
- [ ] Create comprehensive tests for response parsing
- [ ] Test schema validation with malformed responses
- [ ] Test retry/backoff logic with mock failures
- [ ] Test error routing to stderr
- [ ] Test async functionality with real API calls

## Phase 4: Migration
- [ ] Replace current get_message_intent() with new structured approach
- [ ] Add audit logging for intent disambiguation decisions
- [ ] Implement fallback logic for parsing failures
- [ ] Update main.py to use new LLM client

## Phase 5: Expand Framework
- [ ] Add HYDE_GENERATION_SCHEMA and prompt
- [ ] Add RESPONSE_SYNTHESIS_SCHEMA and prompt
- [ ] Create additional response models for different pipeline steps
- [ ] Implement model routing (cheap intent model vs expensive HyDE model)