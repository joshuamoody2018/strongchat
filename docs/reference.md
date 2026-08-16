# Architecture Reference Guide

## Quick Start

For new agents, read these documents in order:

1. **[README.md](../README.md)** - High-level overview and current status
2. **[implementation-status.md](implementation-status.md)** - What's done vs planned
3. **Component-specific docs** as needed:
   - `[llm-framework.md](llm-framework.md)` - LLM wrapper + registry + JSONL audit
   - `[database.md](database.md)` - Read-only data assets + JSONL audit (no app DB)
   - `[pipeline-hyde-retrieval.md](pipeline-hyde-retrieval.md)` - HyDE + retrieval (steps 2-4)
   - `[pipeline-context-retrieval.md](pipeline-context-retrieval.md)` - Context (steps 7, 9)

## Architecture Philosophy

### Stateless MCP server
- The server is a pure function of its inputs. Nothing persists between
  calls. The agent's context window threads state across the
  retrieve → synthesize → validate loop.
- No application database. The audit trail is JSONL log records (keyed by
  per-call `correlation_id`); the returned `PipelineResult` bundle IS the
  auditable artifact for the agent.

### Modular Design
- Each component has dedicated documentation
- High-level overview references detailed docs
- Clear separation of concerns
- Independent component evolution

### Minimalist Documentation
- Main docs are brief and reference detailed specs
- Technical details in separate files
- Avoid duplication across documents
- Focus on integration points

## Document Structure

```
docs/
├── high-level.md                   13-step pipeline overview (MCP entry, stateless)
├── implementation-status.md       Current progress tracking
├── reference.md                   This document
├── llm-framework.md               LLM wrapper + registry + JSONL audit
├── database.md                    Read-only data assets + JSONL audit (no app DB)
├── pipeline-hyde-retrieval.md     HyDE + retrieval pipeline (steps 2-4)
├── pipeline-context-retrieval.md  Context retrieval pipeline (steps 7, 9)
└── architecture-diagram.md        Mermaid top-level + retrieval-detail diagrams
```

## Key Integration Points

### 1. MCP Server
- **Purpose**: Stdio server exposing the pipeline as `retrieve_context` (+ a
  `validate_answer` stub) for any MCP-compatible agent.
- **Integration**: Agent (Claude Desktop / opencode) — entry point — pipeline
- **Status**: ✅ `retrieve_context` live; `validate_answer` is a stub

### 2. LLM Framework
- **Purpose**: Structured, retry-aware, schema-validated LLM interactions
- **Integration**: All services using LLM calls
- **Status**: ✅ Complete and tested
- **Audit**: JSONL log records per call (INFO timing + DEBUG prompt/response)

### 3. Message-type Registry
- **Purpose**: Static message-type config (slug → model_slug, temperature,
  max_retries, request_schema, prompt_template)
- **Integration**: LLMWrapper + BaseService + every service that records audit
- **Status**: ✅ Complete; replaces former `ref_message_types` SQLite table
- **Location**: `src/config/llm_models.py`, `src/config/registry.py`

### 4. Structured Logging
- **Purpose**: Cross-process-safe JSONL audit (replaces former `messages`
  SQLite inserts)
- **Integration**: Called from LLMWrapper + EmbeddingService +
  ContextRetrievalService + PipelineRunner + ingest scripts
- **Status**: ✅ Complete
- **Location**: `src/config/logging.py` → `data/logs/strongchat.log`

### 5. Intent Generation Service (steps 2-3)
- **Status**: ✅ Complete and tested

### 6. HyDE Generation Service (step 3)
- **Status**: ✅ Complete and tested

### 7. Embeddings Service (step 4)
- **Status**: ✅ Complete and tested

### 8. Verse Store / Retrieval Service (steps 4 + ingest)
- **Status**: ✅ Complete and tested

### 9. Context Retrieval Service (steps 7, 9)
- **Status**: ✅ Complete and tested (Greek + Hebrew paths)

### 10. Pipeline Orchestrator + Serializer
- **Purpose**: Compose all services into a runnable pipeline; serialize the
  result to a JSON bundle the agent can carry across calls.
- **Status**: ✅ Complete and tested
- **Location**: `src/services/pipeline/`, `src/server.py`, `src/main.py`

## Pipeline Context

### Current Implementation
- **Steps implemented**: 7/13 (input, intent generation, HyDE generation,
  retrieval, Macula lookup, context retrieval, re-rank/organize)
- **Steps planned**: 5-6 (RRF), 8 (graph expansion), 10-13 (synthesis →
  response); `validate_answer` MCP tool is a stub today (contract locked)

### Next Integration Points
1. `validate_answer` implementation (step 12) — drives the agent's
   re-call/loop decision with structured `unsupported_claims` /
   `missing_coverage` / `suggested_refinement` feedback
2. RRF algorithm implementation (steps 5-6)
3. Graph expansion (step 8)
4. Response synthesis (step 10) and evaluator loop (step 11)

## Agent Workflow

### For New Agents
1. Read `README.md` for system overview
2. Check `implementation-status.md` for current state
3. Read `high-level.md` for the MCP entry + retrieve → validate loop shape
4. Study relevant component docs
5. Review integration points
6. Check task lists for next steps

### For Development
1. Identify component to work on
2. Read specific component documentation
3. Review integration requirements
4. Check test status and dependencies
5. Update implementation status

### For Testing
1. Run `bash scripts/setup_environment.sh` (or skip ingest — most offline
   tests do not require either ChromaDB or macula_index.db)
2. Run offline tests with a dummy key:
   `.venv/bin/python tests/scripts/test_*` (no network)
3. Live system tests need `OPENROUTER_API_KEY` + ingested corpus:
   `.venv/bin/python tests/system/test_*`
4. Top-level cross-service integration test:
   `.venv/bin/python -m unittest tests.test_integration`

## Configuration and Dependencies

### Environment Setup
```bash
# Required
export OPENROUTER_API_KEY=your_api_key_here

# Optional logging
export STRONGCHAT_LOG_LEVEL=ERROR        # default if unset; INFO or DEBUG
export STRONGCHAT_LOG_FILE=data/logs/strongchat.log  # default
```

### Key Files
- `src/config/` - Static config + registry + JSONL logging setup
- `src/services/` - Service implementations
- `src/server.py` - MCP server entry point
- `data/` - Read-only data assets + JSONL log
- `scripts/` - Setup, ingest, and corpus-build utilities

## Error Handling

### Common Patterns
- **LLM failures**: Retry logic with exponential backoff; ERROR log record
  on final failure
- **Validation errors**: Schema enforcement via `jsonschema`; raises
  `ValueError` to the caller
- **Context retrieval errors**: Per-intent capture; do not abort the
  pipeline; ERROR log record
- **Pipeline errors**: Failed run emits an ERROR `pipeline_end` record and
  re-raises

### Debugging
- Check `implementation-status.md` for known issues
- Tail the JSONL audit log: `tail -f data/logs/strongchat.log`
- Slice per run: `grep <correlation_id> data/logs/strongchat.log | jq .`
- Set `STRONGCHAT_LOG_LEVEL=DEBUG` to capture full prompts + raw responses
  (equivalent to the former SQLite `messages.unique_prompt` / `.raw_response`
  columns)

## Future Scaling

### Planned Components
- `validate_answer` MCP tool implementation (step 12)
- RRF ranking system (steps 5-6)
- Graph expansion (step 8)
- Synthesis + evaluator (steps 10-11)

### Documentation Updates
- New components add their own docs
- Implementation status updated regularly
- Integration points documented as added
- Testing status tracked per component

## Best Practices

### For Documentation
- Keep main docs brief and reference detailed specs
- Update status regularly
- Maintain clear separation between components
- Document integration points clearly

### For Development
- Follow existing patterns in components
- Maintain test coverage
- Update implementation status
- Document new dependencies

### For Integration
- Respect component boundaries
- Use the defined interfaces (`BaseService`, `LLMWrapper`,
  `MessageTypeDefRegistry`)
- Update integration documentation
- Test cross-component functionality