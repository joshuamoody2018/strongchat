# AGENTS.md - StrongChat Agent Reference

## ACTIVE WORK IN PROGRESS — READ THIS FIRST (updated 2026-07-28)
An orchestrated work plan is mid-execution. **Resume it before starting any new work.**
- **Plan**: `hyde-retrieval-pipeline` — intent generation → parallel HyDE generation → OpenRouter embeddings → Chroma retrieval over KJV+WEB. **Progress: 5/24 tasks complete** (todos 1-5 done, verified, committed).
- **Next task**: todo 6 (cache db_path injection + FK pragma + message-type migration). A first dispatch was aborted BEFORE any file changes (stalled session `ses_0592d876cffelbhH3TTwhp06ML` — safe to resume or discard; no migration script exists, live DB untouched).
- **How to resume**: run `/start-work hyde-retrieval-pipeline` — the boulder hook auto-continues from the first unchecked todo.
- **State files (all under `.omo/`, now committed)**: `boulder.json` (active work), `plans/hyde-retrieval-pipeline.md` (plan + checkboxes — ground truth), `drafts/hyde-retrieval-pipeline.md` (decisions D1-D6), `notepads/hyde-retrieval-pipeline/` (learnings/issues), `start-work/ledger.jsonl` (evidence ledger), `for-user-review.md` (significant deviations for the user), `evidence/` (per-task QA transcripts).
- **Operational rules for the resumer**: use `.venv/bin/python` for everything; one commit per todo with explicit-path staging (NEVER `git add -A`); never stage `.env`, `data/`, `README.md`, `.gitignore` (user's pending edits), `*.pyc`; freeform sentence-case commit messages; every OpenRouter call recorded in `messages` linked to `ref_message_types`.

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
* `todo.md` - All actionable items (next steps and deferred tasks)

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
* **Refer to**: `todo.md` for planned update mechanism