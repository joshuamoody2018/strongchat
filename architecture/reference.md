# Architecture Reference Guide

## Quick Start

For new agents, read these documents in order:

1. **[README.md](README.md)** - High-level overview and current status
2. **[implementation-status.md](implementation-status.md)** - What's done vs planned
3. **Component-specific docs** as needed:
   - `[llm-framework.md](llm-framework.md)` - LLM interactions
   - `[database.md](database.md)` - Data storage
   - `[intent-disambiguation.md](intent-disambiguation.md)` - Query analysis

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
├── README.md                    # Main overview (brief)
├── implementation-status.md     # Current progress
├── llm-framework.md            # LLM service details
├── database.md                 # Data layer details
├── intent-disambiguation.md    # Query analysis service
└── [future component docs]     # Additional components
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

### 3. Intent Disambiguation
- **Purpose**: Query analysis (Pipeline Step 2)
- **Integration**: Main application → Intent service → LLM framework
- **Status**: 🚧 Framework ready, service in progress

## Pipeline Context

### Current Implementation
- **Steps implemented**: 1 (input), partial 2 (intent framework)
- **Steps planned**: 3-13 (HyDE through response)
- **Architecture ready**: Framework supports full pipeline

### Next Integration Points
1. Intent service completion
2. HyDE service development
3. RRF algorithm implementation
4. Macula data integration

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