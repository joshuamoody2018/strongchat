# Architecture Reference Guide

## Quick Start

For new agents, read these documents in order:

1. **[README.md](README.md)** - High-level overview and current status
2. **[implementation-status.md](implementation-status.md)** - What's done vs planned
3. **Component-specific docs** as needed:
   - `[llm-framework.md](llm-framework.md)` - LLM interactions
   - `[database.md](database.md)` - Data storage
   - `[pipeline-hyde-retrieval.md](pipeline-hyde-retrieval.md)` - HyDE + retrieval pipeline
   - `[pipeline-context-retrieval.md](pipeline-context-retrieval.md)` - Context retrieval pipeline

## Architecture Philosophy

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

### Future-Proof
- Documentation structure supports scaling
- New components add their own docs
- Clear versioning and status tracking
- Agent-friendly format

## Document Structure

```
architecture/
├── README.md                       # Main overview (brief)
├── high-level.md                   # 13-step pipeline overview
├── implementation-status.md       # Current progress tracking
├── reference.md                    # This document
├── llm-framework.md               # LLM service details
├── database.md                    # Data layer + Macula index
├── pipeline-hyde-retrieval.md      # HyDE + retrieval pipeline
└── pipeline-context-retrieval.md   # Context retrieval pipeline (NT original-language)
```

## Key Integration Points

### 1. LLM Framework
- **Purpose**: Structured LLM interactions
- **Integration**: All services using LLM calls
- **Status**: ✅ Complete and tested

### 2. Database Layer
- **Purpose**: Persistent data storage
- **Integration**: All stateful operations
- **Status**: ✅ Complete and tested

### 3. Intent Generation Service
- **Purpose**: Query analysis (Pipeline Step 2)
- **Integration**: Main application → Intent service → LLM framework
- **Status**: ✅ Complete and tested

### 4. HyDE Generation Service
- **Purpose**: Hypothetical document generation (Pipeline Step 3)
- **Integration**: Intent service → HyDE service → LLM framework
- **Status**: ✅ Complete and tested

### 5. Embeddings Service
- **Purpose**: Batched embedding generation
- **Integration**: HyDE documents → Embeddings → Retrieval
- **Status**: ✅ Complete and tested

### 6. Verse Store / Retrieval Service
- **Purpose**: Bible verse storage and retrieval
- **Integration**: HyDE embeddings → ChromaDB → Retrieved verses
- **Status**: ✅ Complete and tested

### 7. Context Retrieval Service
- **Purpose**: Original-language data enrichment (Pipeline Steps 7, 9)
- **Integration**: Retrieved verses → Macula lookup → Scoring → Bundling
- **Status**: ✅ Complete and tested

### 8. Pipeline Orchestrator
- **Purpose**: Compose all services into runnable pipeline
- **Integration**: All services → Pipeline runner → CLI
- **Status**: ✅ Complete and tested

## Pipeline Context

### Current Implementation
- **Steps implemented**: 7/13 (input, intent generation, HyDE generation, retrieval, Macula lookup, context retrieval, re-rank/organize)
- **Steps planned**: 5-6 (RRF), 8 (graph expansion), 10-13 (synthesis through response)
- **Architecture ready**: Framework supports full pipeline

### Next Integration Points
1. RRF algorithm implementation (steps 5-6)
2. Graph expansion (step 8)
3. Response synthesis (step 10)
4. Evaluator loop (step 11)
5. Fact validation (step 12)
6. Final response (step 13)

## Agent Workflow

### For New Agents
1. Read `README.md` for system overview
2. Check `implementation-status.md` for current state
3. Study relevant component docs
4. Review integration points
5. Check task lists for next steps

### For Development
1. Identify component to work on
2. Read specific component documentation
3. Review integration requirements
4. Check test status and dependencies
5. Update implementation status

### For Testing
1. Review test files in `scripts/`
2. Check component-specific test status
3. Run existing tests before changes
4. Add new tests for new functionality

## Configuration and Dependencies

### Environment Setup
```bash
# Required dependencies
sudo apt install python3-aiohttp python3-jsonschema

# Environment variables
export OPENROUTER_API_KEY=your_api_key_here
export MODEL_SLUG_INTENTS=mistralai/mistral-small-24b-instruct-2501
```

### Key Files
- `src/config/` - Centralized configuration
- `src/services/` - Implementation components
- `data/` - Database storage
- `scripts/` - Testing and utilities

## Error Handling

### Common Patterns
- **LLM failures**: Retry logic with exponential backoff
- **Validation errors**: Schema enforcement with stderr routing
- **Database errors**: Connection management with context managers
- **Integration errors**: Graceful degradation with fallbacks

### Debugging
- Check `implementation-status.md` for known issues
- Review test failures in `scripts/test_*.py`
- Monitor stderr output for validation errors
- Check database schema consistency

## Future Scaling

### Planned Components
- HyDE generation service
- RRF ranking system
- Macula integration
- Production monitoring

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
- Use defined interfaces
- Update integration documentation
- Test cross-component functionality