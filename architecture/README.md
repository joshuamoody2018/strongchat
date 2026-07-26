# StrongChat Architecture

## Overview

StrongChat is a biblical search system using LLMs with two-level RRF (Reciprocal Rank Fusion) and an evaluator loop for comprehensive verse retrieval and answer synthesis.

## Pipeline Architecture

### 13-Step Pipeline

1. **Input** — User's raw text
2. **Intent Generation** — LLM produces N candidate topic/theme framings (auditable inference point)
3. **HyDE Generation** — M hypothetical passages per intent (N×M total documents)
4. **Parallel Retrieval** — Embed each HyDE doc, search against English translations, top-K per doc
5. **RRF Level 1** — Merge/rerank M result sets within each intent → one ranked list per intent
6. **RRF Level 2** — Merge/rerank N per-intent lists → single candidate verse set
7. **Macula Lookup** — Pull lemma/Strong's data for candidate set (NT: Macula Greek, OT: TBD)
8. **Graph Expansion** — Lemma-based/verse-graph traversal for cross-references
9. **Re-rank/Organize** — Consolidate steps 6-8 into structured retrieval set
10. **Synthesis** — Frontier model answers using retrieval + original prompt, citations linked
11. **Evaluator** — Fresh LLM checks completeness, loops back to step 2/3 if insufficient
12. **Validator** — Programmatic + Bible-trained LLM fact-check, strips unsupported claims
13. **Response** — Final response to user

## Core Principle

**English carries semantic search (steps 3-6), original language carries support/grounding (steps 7-8)** — not the other way around.

## Current Implementation Status

### ✅ Implemented Components

#### LLM Framework (`src/services/llm/`)
- **Purpose**: Structured LLM interactions with JSON validation
- **Key Features**:
  - Exponential backoff retry logic (3 max retries)
  - Async support with aiohttp
  - JSON schema validation for responses
  - Error routing to stderr
  - Type-safe response models
- **Location**: `LLM_FRAMEWORK.md`
- **Test Status**: ✅ Parser tests passing

#### Database Layer (`src/services/sqlite/`)
- **Purpose**: SQLite database operations
- **Components**:
  - Chat session management
  - Message storage
  - Intent tracking (structured)
- **Location**: `services/sqlite/database.py`

#### Configuration (`src/config/`)
- **Purpose**: Centralized schemas and prompts
- **Components**:
  - JSON schemas for response validation
  - Pipeline-agnostic prompt templates
- **Location**: `LLM_FRAMEWORK.md`

### 🚧 In Progress Components

#### Intent Disambiguation Service
- **Purpose**: Plain-language query disambiguation (step 2)
- **Status**: Framework ready, needs service integration
- **Key Requirements**:
  - Zero biblical vocabulary in intent analysis
  - Multiple interpretive framings per query
  - Structured output for HyDE generation

### 📋 Planned Components

#### HyDE Generation Service
- **Purpose**: Hypothetical document generation (step 3)
- **Dependencies**: Intent disambiguation output
- **Requirements**:
  - Biblical prose generation
  - N×M structure (N intents × M passages each)

#### RRF Implementation
- **Purpose**: Two-level ranking fusion (steps 5-6)
- **Requirements**:
  - Intra-intent ranking
  - Cross-intent merging
  - Score normalization

#### Macula Integration
- **Purpose**: Original language data lookup (step 7)
- **Status**: NT via Macula Greek, OT TBD
- **Requirements**: Strong's concordance integration

## Directory Structure

```
src/
├── config/                    # Centralized configuration
│   ├── schemas.py           # JSON schemas
│   └── prompts.py           # Prompt templates
├── services/
│   ├── llm/                 # LLM framework
│   │   ├── client.py        # Async LLM client
│   │   ├── parser.py        # JSON response parser
│   │   └── exceptions.py   # Error handling
│   ├── sqlite/              # Database operations
│   └── intent/              # Intent disambiguation (planned)
└── main.py                  # Application entry point

data/
└── chat_database.db         # SQLite database

scripts/
├── test_*.py                # Test suites
└── create_database.py       # Database utilities

architecture/
├── high-level.md           # This document
├── llm-framework.md        # LLM framework details
└── [component-specific docs]
```

## Key Design Decisions

### 1. Separation of Concerns
- **Schemas vs Prompts**: Completely separate JSON schemas from prompt templates
- **LLM Ignorance**: LLMs only know immediate task, not pipeline context
- **Modular Services**: Each pipeline step is a separate service

### 2. Error Handling Strategy
- **Exponential Backoff**: 3 retries with 1s → 2s → 4s backoff
- **Error Routing**: Validation errors → stderr, API failures → retry → error handler
- **Graceful Degradation**: Fallback logic when API unavailable

### 3. Auditability
- **Structured Logging**: All intent decisions logged with JSON format
- **Separate Steps**: Intent disambiguation separate from HyDE generation
- **Response Models**: Type-safe objects for data consistency

## Next Steps

1. **Intent Service Integration** - Connect LLM framework to intent disambiguation
2. **Database Schema Update** - Store structured intent data
3. **HyDE Service Development** - Use intent output for hypothetical passages
4. **RRF Implementation** - Two-level ranking system
5. **Macula Integration** - Original language data lookup

## References

- [LLM Framework Documentation](LLM_FRAMEWORK.md)
- [High-Level Pipeline Overview](high-level.md)
- [Implementation Status](todo.md)