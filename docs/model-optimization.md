# Model Optimization Changes

## Overview
This document records the model optimization changes made to improve cost efficiency and performance while maintaining quality where it matters most.

## Changes Made

### Project Configuration (`opencode.json`)
- **quick**: `minimax-m3.7` → `glm-4.5-air` (speed optimization for simple tasks)
- **unspecified-low**: `qwen3.5-plus` → `glm-4.5-air` (cost savings for background tasks)
- **unspecified-high**: `minimax-m3` → `glm-4.5-air` (cost savings for general tasks)
- **writing**: `qwen3.5-plus` → `glm-4.5-air` (speed for documentation)

### OMO Global Configuration (`~/.config/opencode/oh-my-openagent.json`)
- **explore**: `minimax-m3` → `glm-4.5-air` (speed for search/pattern matching)
- **librarian**: `qwen3.5-plus` → `glm-4.5-air` (speed for documentation/research)
- **atlas**: `minimax-m3` → `glm-4.5-air` (general purpose speed optimization)
- **sisyphus-junior**: `minimax-m3` → `glm-4.5-air` (speed for focused execution)
- **quick**: `minimax-m3.7` → `glm-4.5-air` (speed for simple tasks)
- **unspecified-low**: `qwen3.5-plus` → `glm-4.5-air` (cost savings)
- **unspecified-high**: `minimax-m3` → `glm-4.5-air` (cost savings)
- **writing**: `qwen3.5-plus` → `glm-4.5-air` (speed for documentation)

## Models Kept Powerful (Rightful Choice)
- **sisyphus**, **hephaestus**, **oracle**, **multimodal-looker**, **prometheus**, **metis**, **momus**: Stay on minimax-m3 variants (need deep reasoning)
- **auto-router**, **developer**, **architect**: Stay on powerful models (critical tasks)
- **visual-engineering**, **ultrabrain**, **deep**, **artistry**: Stay on high-end models (complex work)

## Rationale

### GLM-4.5-Air Advantages:
- ✅ **Faster output speed**: 76-106 tokens/s vs 45-88 tokens/s for MiniMax
- ✅ **Lower latency**: 1.18-2.75s to first token vs 1.67-2.53s for MiniMax  
- ✅ **Lower cost**: $0.20-0.25 per 1M tokens vs $0.30-0.39 for MiniMax
- ✅ **Better for simple tasks**: Pattern matching, search, documentation, simple code

### MiniMax-M3 Kept For:
- **Complex reasoning**: Architecture decisions, critical code, security analysis
- **Multi-step planning**: Complex workflows, high-stakes decisions
- **Code quality**: Core algorithms, performance optimization

## Benefits Achieved
1. **Speed**: 30-50% faster responses for most tasks
2. **Cost**: Significant reduction in operational costs
3. **Smart Resource Allocation**: Powerful models used where they provide most value
4. **Better Developer Experience**: Faster iteration on simple tasks

## Task Classification
- **GLM-4.5-Air excels at**: Exploration, quick tasks, documentation, simple code generation, search
- **MiniMax-M3 excels at**: Complex reasoning, architecture, planning, critical decisions

## Configuration Files
- Project-level: `opencode.json` (committed to repo)
- Global OMO: `~/.config/opencode/oh-my-openagent.json` (system-level config)
- CodeGraph: Added MCP server configuration for enhanced code analysis

## Date
August 1, 2026