# AGENTS.md - StrongChat Agent Reference

## ACTIVE WORK STATUS (updated 2026-08-16)
context-retrieval OT (Hebrew) integration complete 2026-08-16. NT path
unchanged; macula_tokens is now partitioned by book_num (< 40 Hebrew, >= 40
Greek), strongs_frequency by testament, lexicon_definitions by lexicon_source
(tbESG+lsj vs tbESH). Setup script + docs updated. NT-only live e2e test still
un-addressed for OT (would require real ~80 MB Hebrew TSV download — synthetic
fixture coverage in tests/scripts/test_hebrew_ingest_integration.py covers the
ingest contract).

## Project operational conventions
- Use `.venv/bin/python` for everything.
- Every OpenRouter call recorded in `messages` linked to `ref_message_types`.
- Test queries must NOT be biblical/christian/faith-specific. The system is general-purpose input → biblically-backed output, so tests should use non-biblical questions (themes may incidentally overlap scripture, but never ask "what does the Bible say about X" as a test).

## Project Overview
- **Purpose**: Bible verse retrieval and answer synthesis using LLMs
- **Architecture**: 13-step pipeline with two-level RRF and cross-language search
- **Key Design**: English for semantic search, original language for grounding

## Important Files
* `README.md` - Dev environment setup (VPS-focused)
* `docs/llm-framework.md` - LLM framework documentation and usage
* `docs/` - System design and architecture documentation
  * `high-level.md` - 13-step pipeline overview
  * `reference.md` - Agent workflow and integration
  * `implementation-status.md` - Current progress tracking
* `todo.md` - All actionable items (next steps and deferred tasks)

## Code Structure
* `src/services/llm/` - LLM framework (wrapper, aimessage, parser, exceptions)
* `src/services/base.py` - Shared `BaseService` foundation
* `src/services/sqlite/` - Database operations and session management
* `src/services/intent/` - Intent generation service
* `src/services/hyde/` - HyDE generation service
* `src/services/embeddings/` - Batched embedding service
* `src/services/vectordb/` - ChromaDB verse store
* `src/services/retrieval/` - HyDE → verse retrieval service
* `src/services/context/` - Original-language context retrieval service
* `src/services/pipeline/` - Pipeline orchestrator
* `src/config/` - JSON schemas and prompt templates
* `scripts/` - Testing and utility scripts

## Key Entry Points
* `src/main.py` - Application entry point (basic chat interface)
* `src/services/llm/wrapper.py` - Canonical async LLM wrapper (database-driven config, retry, recording)
* `src/services/sqlite/database.py` - Database operations
* `src/config/schemas.py` - Response validation schemas

## Documentation Maintenance
* **Manual Updates**: Review and update when:
  - Major architecture changes
  - New pipeline steps implemented
  - Development conventions change
  - New services added to `src/services/`
  - The "ACTIVE WORK STATUS" section is stale (plan started, completed, or paused)
* **Refer to**: `todo.md` for planned update mechanism
