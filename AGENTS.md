# AGENTS.md - StrongChat Agent Reference

## ACTIVE WORK STATUS (updated 2026-08-16)

### MCP pivot (in progress, `mcp` branch)

StrongChat is being repackaged as a stateless **MCP server**. The agent
(Claude Desktop / opencode / any MCP-compatible client) drives the
retrieve → synthesize → validate loop itself; the server is a pure
function of its inputs. Nothing server-side persists between calls.

- **Repo strategy:** `mcp` is a sibling long-lived branch to `dev`. The
  `dev` branch is the **pre-MCP SQLite-audit era** — reference only, no
  further development. Periodic rebases onto `dev` until `mcp` stabilizes,
  at which point `dev` will be tagged and `mcp` becomes the default.
- **No application database.** The three former tables (`sessions`,
  `messages`, `ref_message_types`) are gone. Static message-type config
  lives in `src/config/llm_models.py` (frozen dataclasses) and is loaded
  once at import time into `src/config/registry.py:DEFAULT_REGISTRY`.
- **Audit trail is JSONL logging.** `src/config/logging.py` writes
  cross-process-safe records (via `concurrent-log-handler`) to
  `data/logs/strongchat.log`. Levels: `ERROR` (default), `INFO` (per-step
  timing), `DEBUG` (full audit — prompt, raw_response, context bundle).
- **Entry point:** `src/server.py` exposes a `FastMCP` (Anthropic `mcp`
  SDK) stdio server with two tools:
  - `retrieve_context(query, top_k=10, translations=["kjv","web"]) -> dict`
    — runs the existing pipeline (intent → HyDE → retrieval → context),
    returns a self-contained JSON bundle.
  - `validate_answer(answer, context=<bundle>) -> dict` — **stub** raises
    `NotImplementedError`; contract locked in for the future agent harness
    / wrapper that drives state management.
- **Assets (read-only data, NOT stripped):** `data/chroma/`
  (verse vectors) and `data/macula_index.db` (Greek/Hebrew tokens +
  lexicon). These survive because they are read-only data assets — not
  application state.
- **State lifecycle:** the agent's context window threads state across
  the loop. The returned `PipelineResult` bundle IS the auditable
  artifact; the server doesn't need session storage or correlation by id
  (a per-call correlation_id is generated for log slicing only).

### Earlier OT (Hebrew) integration (complete 2026-08-16)
context-retrieval OT (Hebrew) integration complete. NT path unchanged;
macula_tokens is partitioned by book_num (< 40 Hebrew, >= 40 Greek),
strongs_frequency by testament, lexicon_definitions by lexicon_source
(tbESG+lsj vs tbESH). Setup script + docs updated. NT-only live e2e
test still un-addressed for OT (would require real ~80 MB Hebrew TSV
download — synthetic fixture coverage in
tests/scripts/test_hebrew_ingest_integration.py covers the ingest
contract).

## Project operational conventions

- Use `.venv/bin/python` for everything.
- Live (system) tests need `OPENROUTER_API_KEY` in env. Offline tests
  use a dummy key and run without network. Test queries must NOT be
  biblical/faith-specific (the system is general-purpose input →
  biblically-backed output).

## Project Overview

- **Purpose:** Bible verse retrieval with original-language grounding,
  exposed as an MCP server for agent-driven retrieve → synthesize →
  validate loops.
- **Architecture:** 13-step pipeline (steps 2–4, 7, 9 implemented) with
  English semantic search and original-language support/grounding.
- **Key Design:** English carries semantic search (HyDE → ChromaDB);
  original language carries support/grounding (Macula + lexicons).
- **MCP entry point:** `src/server.py` (stdio server with `FastMCP`);
  `validate_answer` is a stub today.

## Important Files

* `README.md` - Dev environment setup
* `docs/llm-framework.md` - LLM framework documentation
* `docs/` - System design and architecture documentation
  * `high-level.md` - 13-step pipeline overview (MCP entry, stateless)
  * `reference.md` - Agent workflow and integration
  * `implementation-status.md` - Current progress tracking
* `todo.md` - All actionable items (next steps and deferred tasks)

## Code Structure
* `src/server.py` - **MCP server entry point** (FastMCP stdio)
* `src/main.py` - JSON-printing CLI smoke-test (calls `retrieve_context_impl`)
* `src/services/llm/` - LLM framework (wrapper, aimessage, exceptions)
* `src/services/base.py` - Shared `BaseService` foundation (no DB, just
  LLMWrapper + registry + logger)
* `src/services/embeddings/` - Batched embedding service
* `src/services/vectordb/` - ChromaDB verse store
* `src/services/intent/` - Intent generation service
* `src/services/hyde/` - HyDE generation service
* `src/services/retrieval/` - HyDE → verse retrieval service
* `src/services/context/` - Original-language context retrieval service
* `src/services/pipeline/` - Pipeline orchestrator + JSON bundle serializer
* `src/config/` - JSON schemas, prompt templates, **message-type
  registry** (`llm_models.py`, `registry.py`), **JSONL logging setup**
  (`logging.py`)
* `scripts/` - Setup, ingest, and corpus-build utilities

## Read-only data assets (NOT application DB)
* `data/chroma/` - ChromaDB persistent verse vectors (kjv_verses, web_verses)
* `data/macula_index.db` - Macula Greek + Hebrew tokens, Strong's
  frequency, lexicon definitions (read via per-call short-lived
  `sqlite3.connect` from `ContextRetrievalService`)
* `data/logs/strongchat.log` - JSONL audit log (default ERROR level,
  configurable via `STRONGCHAT_LOG_LEVEL` env)

## Key Entry Points
* `src/server.py` - **Production entry point**: MCP stdio server
* `src/main.py` - Dev/debug: JSON-printing CLI smoke-test
* `src/services/llm/wrapper.py` - Canonical async LLM wrapper (registry-driven,
  retry, JSONL audit)
* `src/config/llm_models.py` - Static message-type definitions (frozen
  dataclasses; replaces former `ref_message_types` SQLite table)
* `src/config/registry.py` - Process-wide singleton `MessageTypeDefRegistry`
* `src/config/logging.py` - Cross-process-safe JSONL logging setup
  (`ConcurrentRotatingFileHandler`)

## Documentation Maintenance
* **Manual Updates:** Review and update when:
  - Major architecture changes
  - New pipeline steps implemented
  - Development conventions change
  - New services added to `src/services/`
  - The "ACTIVE WORK STATUS" section is stale (plan started, completed,
    or paused)
* **Refer to:** `todo.md` for planned update mechanism