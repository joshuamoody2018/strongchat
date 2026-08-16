# AGENTS.md - StrongChat Agent Reference

A pointer + map for AI agents working in this repo. Not a progress log —
that's in `todo.md`. Not a deployment runbook — that's in
`deploy/README.md`. This file is for "where is X" and "what
conventions do I follow" only.

## Operational conventions

- Use `.venv/bin/python` for everything.
- Live (system) tests need `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` in
  env. Offline tests use a dummy key and run without network.
- Test queries must NOT be biblical/faith-specific — the system is
  general-purpose input → biblically-backed output.

## Code Structure

* `src/server.py` — **MCP server entry point** (stdio or
  streamable-http via `mcp v2.x`'s `MCPServer`). Two tools:
  `retrieve_context` + `validate_answer` (stub — see `todo.md`).
  Auth + OAuth provider wiring lives here too
  (`_setup_and_build_mcp`).
* `src/auth.py` — `StaticBearerTokenVerifier` (constant-time bearer
  compare against `STRONGCHAT_API_KEY`) +
  `load_static_bearer_config()`. Enabled when `STRONGCHAT_API_KEY` +
  `STRONGCHAT_PUBLIC_URL` both set.
* `src/oauth/` — `StrongChatOAuthProvider` (OAuth 2.0 PKCE
  authorization-server, Option 1 static-creds / no DCR) +
  `load_oauth_config()`. Enabled when `STRONGCHAT_OAUTH_SIGNING_KEY` +
  `STRONGCHAT_PUBLIC_URL` + `STRONGCHAT_OAUTH_CLIENT_ID` +
  `STRONGCHAT_OAUTH_CLIENT_SECRET` all set. Takes precedence over the
  static bearer.
* `src/main.py` — JSON-printing CLI smoke-test (calls
  `retrieve_context_impl`).
* `src/services/llm/` — LLM framework (wrapper, aimessage,
  exceptions).
* `src/services/base.py` — Shared `BaseService` foundation (no DB,
  just LLMWrapper + registry + logger).
* `src/services/embeddings/` — Batched embedding service.
* `src/services/vectordb/` — ChromaDB verse store.
* `src/services/intent/` — Intent generation service.
* `src/services/hyde/` — HyDE generation service.
* `src/services/retrieval/` — HyDE → verse retrieval service.
* `src/services/context/` — Original-language context retrieval
  service.
* `src/services/pipeline/` — Pipeline orchestrator (`PipelineRunner`)
  + JSON bundle serializer (`pipeline_result_to_bundle`).
* `src/config/` — JSON schemas, prompt templates, message-type
  registry (`llm_models.py`, `registry.py`), JSONL logging setup
  (`logging.py`).
* `scripts/` — Setup, ingest, corpus-build, and OAuth key/cred mint
  utilities.
* `deploy/` — `Caddyfile` (sslip.io on-demand TLS reverse proxy) +
  `bootstrap.sh` (idempotent bring-up: bearer + OAuth key/cred
  generation, public IP detection, `Caddyfile.local` render, `.env`
  write) + `strongchat.service` (optional systemd unit) +
  `README.md` (public-exposure runbook including the claude.ai
  custom-connector onboarding flow).
* `tests/system/` — Live tests (real OpenRouter API + ingested
  ChromaDB + Macula assets). Need `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY`.
* `tests/scripts/` — Offline tests (dummy key, no network).

## Read-only data assets (NOT application DB)

* `data/chroma/` — ChromaDB persistent verse vectors (`kjv_verses`,
  `web_verses`).
* `data/macula_index.db` — Macula Greek + Hebrew tokens, Strong's
  frequency, lexicon definitions (read via per-call short-lived
  `sqlite3.connect` from `ContextRetrievalService`).
* `data/logs/strongchat.log` — JSONL audit log (default ERROR level,
  configurable via `STRONGCHAT_LOG_LEVEL` env).

## Key Entry Points

* `src/server.py` — Production entry point: MCP server (stdio or
  streamable-http).
* `src/main.py` — Dev/debug: JSON-printing CLI smoke-test.
* `src/services/llm/wrapper.py` — Canonical async LLM wrapper
  (registry-driven, retry, JSONL audit).
* `src/services/pipeline/runner.py` — PipelineRunner with progress
  callback (drives the 5 streaming stage events on
  `retrieve_context`).
* `src/services/pipeline/serializer.py` — `pipeline_result_to_bundle`
  (the JSON shape the agent threads through
  `retrieve_context` → `validate_answer`).
* `src/config/llm_models.py` — Static message-type definitions
  (frozen dataclasses; replaces former `ref_message_types` SQLite
  table).
* `src/config/registry.py` — Process-wide singleton
  `MessageTypeDefRegistry` (`DEFAULT_REGISTRY`).
* `src/config/logging.py` — Cross-process-safe JSONL logging setup
  (`ConcurrentRotatingFileHandler`).

## Important Files

* `README.md` — Dev environment setup.
* `docs/` — System design + architecture documentation
  (`high-level.md`, `reference.md`, `implementation-status.md`,
  pipeline-specific docs).
* `todo.md` — All actionable items (what's left to do, in priority
  order; nothing else — no historical/done items).
* `deploy/README.md` — Public exposure runbook (bearer +
  Caddy + claude.ai custom-connector onboarding).

## Documentation Maintenance

When you change code that affects one of these, update the
corresponding file:

| Change | Update |
|---|---|
| New / moved / removed source file | This file's Code Structure + Key Entry Points sections |
| New env var or auth mode | This file's Code Structure (auth/OAuth entry) + `deploy/README.md` |
| Pipeline stage added / removed / renamed | `src/services/pipeline/runner.py` docstring + `docs/high-level.md` + `todo.md` if new work |
| New todo item or completed work | `todo.md` only (don't add narrative to this file) |
| New deploy step or onboarding path | `deploy/README.md` |
| New service directory | This file's Code Structure |
