# Context Retrieval Pipeline

## Overview

The context retrieval stage of the StrongChat pipeline takes the ranked verse candidates from the HyDE-retrieval step and enriches them with original-language data from Macula Greek. It covers pipeline steps 7 and 9:

1. **Macula Lookup** — Pull lemma, Strong's number, and morphological data for each verse candidate.
2. **Re-rank/Organize** — Filter by part-of-speech, score by frequency and ambiguity, and trim to the most significant words.

The implemented service is located under `src/services/context/` and is composed by `PipelineRunner` (`src/services/pipeline/runner.py`). This document describes the message types, service contracts, data flow, and scoring methodology.

## Message Types and Schemas

All LLM and embedding calls are recorded as rows in the `messages` table, linked to `ref_message_types`. The message type used by the context retrieval pipeline is:

| Message type | Model slug | Purpose |
|--------------|------------|---------|
| `context_retrieval` | (none) | Programmatic summary of per-intent context enrichment results. |

### Schema

- `context_retrieval` has no JSON response schema; it is recorded as a summary row with the following structure:
  ```json
  {
    "intent_id": "string",
    "translation_count": "integer",
    "hit_count": "integer", 
    "scored_word_count": "integer",
    "kept_word_count": "integer"
  }
  ```

## Service Contracts

All services inherit from `BaseService` (`src/services/base.py`), which provides a shared `LLMWrapper`, `ChatDatabase`, and `GlobalReferenceCache`.

### ContextRetrievalService (`src/services/context/service.py`)

```python
async def retrieve_for_pipeline(self, pipeline_result: PipelineResult, session_uuid: str) -> PipelineResult:
    """Return PipelineResult with context_bundle attached to each hit."""
```

- Launches one `_process_intent` task per intent in parallel via `asyncio.gather`.
- For each intent × translation × hit: parses reference, looks up Macula tokens, filters by POS, scores words, and attaches bundle.
- Per-intent failures are captured and logged; the pipeline continues with other intents.
- Records one `context_retrieval` summary message per intent that had search results.

## Data Flow

```
PipelineResult (after retrieval)
    │
    ▼
┌─────────────────────────────┐
│ ContextRetrievalService    │
│  - _process_intent (parallel) │
│  - _build_bundle_for_hit   │
│  - macula_tokens lookup    │
│  - pos_weight filtering    │
│  - frequency + sense lookup │
│  - composite scoring      │
│  - trim to top 20%         │
└─────────────────────────────┘
    │
    ▼
PipelineResult with hit["context_bundle"]
```

1. `PipelineRunner.run()` calls `context_service.retrieve_for_pipeline(result, session_uuid)`.
2. For each intent with search results, `_process_intent` is launched in parallel.
3. For each hit in the intent's search results: `_build_bundle_for_hit` parses the reference, queries Macula tokens, filters by POS, scores words, and trims to the top 20%.
4. Each hit gets a `context_bundle` with two lists: `scored_words` (all filtered words with scores) and `kept_words` (trimmed subset with full word data).
5. One `context_retrieval` summary message is recorded per intent.

## Scoring Formula

The composite score for each word is calculated as:

```
composite_score(pos_weight, frequency_count, sense_count) = pos_weight * log1p(1/frequency_count) * log1p(sense_count)
```

Where:
- `pos_weight`: Weight from POS_WEIGHTS table (verbs: 0.95, nouns: 0.825, adjectives: 0.65, etc.)
- `frequency_count`: Number of times the Strong's number appears in the NT corpus (from `strongs_frequency` table)
- `sense_count`: Number of definitions for this Strong's number in TBESG + Thayer's (from `lexicon_definitions` table)

### Worked Example: John 3:16 (μονογενής)

For the word "μονογενής" (G3439) in John 3:16:
- POS: N- (noun) → pos_weight = 0.825
- Frequency: 9 occurrences → frequency_count = 9
- Sense count: 1 definition → sense_count = 1

```
composite_score = 0.825 * log1p(1/9) * log1p(1)
                = 0.825 * log1p(0.111) * log1p(1)
                = 0.825 * 0.10536 * 0.69315
                ≈ 0.825 * 0.0730
                ≈ 0.0602
```

## Data Sources and Licenses

### Macula Greek Tokens
- **Source**: `Clear-Bible/macula-greek` SBLGNT
- **URL**: https://raw.githubusercontent.com/Clear-Bible/macula-greek/main/tsv/macula-greek.tsv
- **License**: CC BY 4.0
- **Content**: NT Greek tokens with lemma, Strong's number, morphological tags, and gloss

### TBESG (Tyndale Brief Extended Greek)
- **Source**: `STEPBible/STEPBible-Data` Lexicons/TBESG
- **URL**: https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TBESG%20-%20Tyndale%20Brief%20Greek%20Lexicon%20of%20Extended%20Strong%E2%80%99s%20for%20Greek.tsv
- **License**: CC BY 4.0
- **Content**: NT Greek lexicon with Strong's-keyed definitions

### LSJ (Liddell-Scott Jones Greek Lexicon)
- **Source**: `STEPBible/STEPBible-Data` Lexicons/TFLSJ
- **URL**: https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/Thayers%20Greek%20Lexicon.tsv
- **License**: CC BY 4.0
- **Note**: Used as fallback when TBESG doesn't have coverage (Thayer's is public domain but LSJ has better coverage)

## OT-Deferred Note

This implementation is NT-only. Hebrew OT integration is deferred to a future plan per the architecture's "OT: TBD" note in the Macula Lookup step.

## Known Limitations

1. **Missing Gloss Column**: The `gloss` field on each kept_word is empty because todo 3's `macula_tokens` SQLite schema does not include the `gloss` column from the canonical TSV. Flagged for a follow-up "fix macula schema" plan.

2. **Lexicon Source Substitution**: BDAG is explicitly excluded (copyrighted University of Chicago Press 2000). TBESG + LSJ are used instead with user approval.

## Bundle Shape Example

Each hit in the search results gets a `context_bundle` with the following structure:

```json
{
  "context_bundle": {
    "scored_words": [
      {
        "surface": "λογος",
        "lemma": "λογος",
        "strongs": "G3056",
        "morph": "N---NSM-",
        "pos": "N-",
        "pos_weight": 0.825,
        "frequency_count": 531,
        "sense_count": 7,
        "composite_score": 0.0475
      }
    ],
    "kept_words": [
      {
        "surface": "λογος",
        "lemma": "λογος", 
        "strongs": "G3056",
        "morph": "N---NSM-",
        "pos": "N-",
        "pos_weight": 0.825,
        "frequency_count": 531,
        "sense_count": 7,
        "composite_score": 0.0475,
        "lexicon_source": "tbESG",
        "definitions": ["word, speech, discourse", "reason, thought", "account, message"],
        "glosses": ["word"]
      }
    ]
  }
}
```

The `kept_words` list contains only the top 20% of scored words (minimum 2 words per verse) and includes all data needed for the synthesis stage to understand the original-language context of each verse.