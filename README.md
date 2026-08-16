## Contributing & Licensing

This project is licensed under the **CC BY-NC 4.0** license. Commercial use requires explicit approval.

By contributing to this repository, you agree to the terms of our [Contributor License Agreement (CLA)](CLA.md).

---

# StrongChat

StrongChat is a **stateless MCP server** that exposes a Bible verse retrieval
pipeline with original-language grounding. It is designed to be called by an
agent (Claude Desktop, opencode, any MCP-compatible client) that drives the
retrieve → synthesize → validate loop itself; the server is a pure function
of its inputs and nothing persists between calls.

## Features

- **MCP server entry point**: stdio server built on the official Anthropic
  `mcp` SDK with `FastMCP`. One tool today (`retrieve_context`); a second
  (`validate_answer`) has its contract locked in but is a stub.
- **Intent disambiguation**: clarifies ambiguous or shorthand questions before
  retrieval.
- **HyDE generation**: produces hypothetical answer passages to improve
  semantic retrieval.
- **Cross-language retrieval**: English semantic search (ChromaDB), original-
  language grounding (Macula Greek + Hebrew + Strong's lexicons).
- **Stateless**: no application database. Audit trail is JSONL log records
  (cross-process safe via `concurrent-log-handler`).
- **Structured output**: the returned `PipelineResult` bundle is JSON-serializable
  and self-contained — the agent's context window threads state across the
  loop.

## Directory Layout

```
src/              Source code and service implementations
  server.py       MCP stdio server (FastMCP) — production entry point
  main.py          Dev/debug JSON CLI smoke-test
  services/       LLM framework, pipeline services
    config/         JSON schemas, prompt templates, message-type registry,
                    JSONL logging setup
scripts/          Setup, utility, and pipeline scripts
  setup_environment.sh    Bootstrap Python environment and ingest read-only assets
  ingest_corpus.py        Ingest Bible corpus into ChromaDB
tests/            Test suites
  system/         System/integration tests (need OPENROUTER_STRONGCHAT_DEFAULT_API_KEY)
  scripts/        Script-style offline tests (dummy key)
data/             Read-only data assets
  chroma/         ChromaDB persistent verse vectors (kjv_verses, web_verses)
  macula_index.db Macula Greek + Hebrew tokens + Strong's + lexicons
  logs/           JSONL audit log (data/logs/strongchat.log)
docs/             System design and architecture documentation
```

## Prerequisites

- Python 3.12 or newer
- Ubuntu/Debian-based environment
- Git

## Installation

Run the committed setup script to create a virtual environment, install
dependencies, and ingest the read-only data assets (Macula Greek + Hebrew
corpora, lexicons, KJV + WEB verses into ChromaDB):

```bash
bash scripts/setup_environment.sh
```

There is **no application database** to create or migrate. The audit trail
is the JSONL log file under `data/logs/strongchat.log`, created lazily on
the first log record.

Then create a `.env` file in the project root with at least your OpenRouter
API key:

```bash
OPENROUTER_STRONGCHAT_DEFAULT_API_KEY="sk-or-..."
```

Optional logging configuration:

```bash
STRONGCHAT_LOG_LEVEL="ERROR"          # default if unset; also INFO or DEBUG
STRONGCHAT_LOG_FILE="data/logs/strongchat.log"  # default if unset
```

## Usage

### Run the MCP server (production)

```bash
.venv/bin/python src/server.py
```

Wire it into Claude Desktop via `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "strongchat": {
      "command": "/abs/path/to/strongchat/.venv/bin/python",
      "args": ["/abs/path/to/strongchat/src/server.py"]
    }
  }
}
```

### Dev/debug CLI smoke-test

```bash
set -a; . ./.env; set +a
.venv/bin/python src/main.py "your question"
```

Prints the full JSON bundle the MCP `retrieve_context` tool would return.

## Tools exposed

### `retrieve_context(query, top_k=10, translations=["kjv","web"]) -> dict`

Runs intent → HyDE → parallel retrieval → Macula context enrichment, then
returns a self-contained JSON bundle keyed by `correlation_id` with one
trace per intent. Each trace carries `intent_data`, `hyde_document`, and per-
translation `hits` (each hit has `reference`, `text`, `distance`, and a
synthesis-ready `context_bundle`).

Embedding vectors are NOT included in the bundle (too large, redundant
downstream of retrieval).

### `validate_answer(answer, context) -> dict`

**Stub** — raises `NotImplementedError`. Contract locked in for the future
agent harness / wrapper tool that drives state management across the
retrieve → synthesize → validate loop. Planned return shape:

```json
{
  "valid": false,
  "unsupported_claims": [{"claim": "...", "reason": "...", "missing_reference": null}],
  "missing_coverage": ["Romans 8:28 cross-reference"],
  "suggested_refinement": "re-call retrieve_context with expanded intents about suffering+perseverance"
}
```

## Testing

Offline script-style tests (no network, dummy API key):

```bash
.venv/bin/python tests/scripts/test_intent_service.py
.venv/bin/python tests/scripts/test_pipeline_offline.py
.venv/bin/python tests/scripts/test_mcp_server.py
.venv/bin/python tests/scripts/test_logging.py
```

Live system tests (need `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` and a fully ingested corpus):

```bash
set -a; . ./.env; set +a
.venv/bin/python tests/system/test_intent_generation.py
.venv/bin/python tests/system/test_pipeline_e2e.py
.venv/bin/python tests/system/test_context_retrieval_e2e.py
```

Top-level cross-service integration test:

```bash
.venv/bin/python -m unittest tests.test_integration
```

## Documentation

- `docs/high-level.md` — 13-step pipeline overview (MCP entry, stateless)
- `docs/reference.md` — agent workflow and integration
- `docs/implementation-status.md` — current progress tracking
- `docs/database.md` — read-only data assets + JSONL audit (no app DB)
- `docs/pipeline-hyde-retrieval.md` — HyDE + retrieval pipeline (steps 2–4)
- `docs/pipeline-context-retrieval.md` — context retrieval pipeline (steps 7, 9)
- `docs/llm-framework.md` — LLM wrapper + registry + JSONL audit
- `docs/architecture-diagram.md` — Mermaid top-level + retrieval-detail diagrams
- `todo.md` — implementation backlog and next steps