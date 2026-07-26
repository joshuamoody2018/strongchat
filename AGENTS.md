# AGENTS.md - StrongChat Agent Reference

## Project Overview
- **Purpose**: Bible verse retrieval and answer synthesis using LLMs
- **Architecture**: 13-step pipeline with two-level RRF and cross-language search
- **Key Design**: English for semantic search, original language for grounding

## Important Files
* `README.md` - Dev environment setup (VPS-focused)
* `LLM_FRAMEWORK.md` - LLM framework documentation and usage
* `architecture/` - System design and architecture documentation
  * `high-level.md` - 13-step pipeline overview
  * `reference.md` - Agent workflow and integration
  * `implementation-status.md` - Current progress tracking
* `todo-next.md` - Next actionable items (Phase 1-5)
* `todo-deferred.md` - Deferred items (error handling, async improvements)

## Code Structure
* `src/services/llm/` - LLM framework (client, parser, exceptions)
* `src/services/sqlite/` - Database operations and session management
* `src/config/` - JSON schemas and prompt templates
* `src/services/intent/` - Intent disambiguation (planned)
* `scripts/` - Testing and utility scripts

## Key Entry Points
* `src/main.py` - Application entry point (basic chat interface)
* `src/services/llm/client.py` - LLM client with structured responses
* `src/services/sqlite/database.py` - Database operations
* `src/config/schemas.py` - Response validation schemas

## Documentation Maintenance
* **Manual Updates**: Review and update when:
  - Major architecture changes
  - New pipeline steps implemented
  - Development conventions change
  - New services added to `src/services/`
* **Refer to**: `todo-deferred.md` for planned update mechanism