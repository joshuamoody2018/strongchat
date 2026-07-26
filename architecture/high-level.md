# StrongChat Pipeline Architecture

## 13-Step Pipeline Overview

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

## Implementation Status

- ✅ **LLM Framework**: Structured LLM interactions with JSON validation
- ✅ **Database Layer**: SQLite operations with session management
- 🚧 **Intent Disambiguation**: Framework ready, service in progress
- 📋 **HyDE Generation**: Planned for next phase
- 📋 **RRF Implementation**: Planned for later phase

## Detailed Documentation

See [architecture reference](reference.md) for component details and integration points.

- [LLM Framework](llm-framework.md) - Structured LLM interactions
- [Database](database.md) - Data storage and operations
- [Intent Disambiguation](intent-disambiguation.md) - Query analysis service
- [Implementation Status](implementation-status.md) - Current progress tracking
- [Reference Guide](reference.md) - Agent workflow and integration
