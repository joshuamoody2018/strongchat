# Context Retrieval Pipeline

## Overview

The context retrieval stage of the StrongChat pipeline takes the ranked verse candidates from the HyDE-retrieval step and enriches them with original-language data from Macula Greek (NT) and Macula Hebrew WLC (OT). It covers pipeline steps 7 and 9:

1. **Macula Lookup** — Pull lemma, Strong's number, and morphological data for each verse candidate. The service routes per hit by `book_num < 40` (Hebrew OT) vs `book_num >= 40` (Greek NT) because Greek and Hebrew Strong's bare-int ranges overlap.
2. **Re-rank/Organize** — Filter by part-of-speech (Robinson codes for Greek, HAM codes for Hebrew), score by frequency and ambiguity, and trim to the most significant words.

The implemented service is located under `src/services/context/` and is composed by `PipelineRunner` (`src/services/pipeline/runner.py`). This document describes the message types, service contracts, data flow, and scoring methodology.

## Message Types and Schemas

The audit trail is JSONL log records (no application DB). The context
retrieval pipeline uses one message type:

| Message type | Model slug | Purpose |
|--------------|------------|---------|
| `context_retrieval` | (none) | Per-intent programmatic summary of context enrichment results. |

### Schema

- `context_retrieval` has no JSON response schema; it is emitted as a
  summary record carrying the following extras on the INFO log record:
  ```json
  {
    "event": "context_retrieval",
    "intent_id": "string",
    "translation_count": 2,
    "hit_count": 4,
    "scored_word_count": 25,
    "kept_word_count": 8,
    "elapsed_ms": 120,
    "status": "ok"
  }
  ```

The companion DEBUG audit record carries the full per-hit bundles payload
serialized as the `raw_response` field (mirrors the former `messages`
row's `raw_response` column shape).

## Service Contracts

All services inherit from `BaseService` (`src/services/base.py`), which
provides a shared `LLMWrapper` and the process-wide
`MessageTypeDefRegistry` (`DEFAULT_REGISTRY`). There is no application DB;
audit records land in the JSONL log file (`data/logs/strongchat.log`).

### ContextRetrievalService (`src/services/context/service.py`)

```python
async def retrieve_for_pipeline(self, pipeline_result: PipelineResult, correlation_id: str) -> PipelineResult:
    """Return PipelineResult with context_bundle attached to each hit."""
```

- Launches one `_process_intent` task per intent in parallel via `asyncio.gather`.
- For each intent × translation × hit: parses reference, looks up Macula tokens, filters by POS, scores words, and attaches bundle.
- Per-intent failures are captured and logged; the pipeline continues with other intents.
- Emits one INFO `context_retrieval` + DEBUG `raw_response`-carrying audit
  record per intent that has search results.

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

1. `PipelineRunner.run()` calls `context_service.retrieve_for_pipeline(result, correlation_id)`.
2. For each intent with search results, `_process_intent` is launched in parallel.
3. For each hit in the intent's search results: `_build_bundle_for_hit` parses the reference, queries Macula tokens, filters by POS, scores words, and trims to the top 20%.
4. Each hit gets a `context_bundle` with two lists: `scored_words` (all filtered words with scores) and `kept_words` (trimmed subset with full word data).
5. One INFO `context_retrieval` + one DEBUG `raw_response`-carrying audit log record is emitted per intent.

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
- **Ingest**: `scripts/download_macula_greek.py` → `data/macula/macula-greek.tsv`; `scripts/build_macula_index.py --testament greek`

### Macula Hebrew Tokens (WLC)
- **Source**: `Clear-Bible/macula-hebrew` WLC (Westminster Leningrad Codex)
- **URL**: https://github.com/Clear-Bible/macula-hebrew/blob/main/WLC/tsv/macula-hebrew.tsv (served via Git LFS; the download script resolves the LFS pointer itself via the GitHub LFS batch API)
- **License**: CC BY 4.0 (WLC text public domain from the Groves Center; morphology from Open Scriptures Hebrew Bible; syntax trees from Groves Center under CC BY 4.0; Cherith Glosses CC BY 4.0; MARBLE/SDBH sense data)
- **Content**: OT Hebrew tokens with lemma, Strong's number (bare zero-padded int, optionally suffixed with a sense letter like `0430a`), morphological tags (HAM lowercase codes), and gloss. xml:id format: `o` + 2-digit book (1..39) + 3-digit chapter + 3-digit verse + 4-digit word_slot (13 chars total).
- **Ingest**: `scripts/download_macula_hebrew.py` → `data/macula/macula-hebrew.tsv`; `scripts/build_macula_index.py --testament hebrew`

### TBESG (Tyndale Brief Extended Greek)
- **Source**: `STEPBible/STEPBible-Data` Lexicons/TBESG
- **URL**: https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TBESG%20-%20Tyndale%20Brief%20Greek%20Lexicon%20of%20Extended%20Strong%E2%80%99s%20for%20Greek.tsv
- **License**: CC BY 4.0
- **Content**: NT Greek lexicon with Strong's-keyed definitions. Stored in `lexicon_definitions` under `lexicon_source='tbESG'`.

### TBESH (Tyndale Brief Extended Hebrew)
- **Source**: `STEPBible/STEPBible-Data` Lexicons/TBESH
- **URL**: https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt
- **License**: CC BY 4.0
- **Content**: OT Hebrew lexicon with Strong's-keyed definitions, one row per `dStrong#` sense (the Greek TBESG has one row per lemma with multi-sense splits inside the definition; this difference is handled by `build_lexicon_index.process_lexicon_data`, which assigns sequential `sense_index` per strongs number across both single-row-multi-sense and multi-row single-sense patterns). Stored in `lexicon_definitions` under `lexicon_source='tbESH'`.

### LSJ (Liddell-Scott Jones Greek Lexicon)
- **Source**: `STEPBible/STEPBible-Data` Lexicons/TFLSJ
- **URL**: https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TFLSJ%20%200-5624%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt
- **License**: CC BY 4.0
- **Note**: Used as fallback when TBESG doesn't have coverage (Thayer's is public domain but LSJ has better coverage). Stored under `lexicon_source='lsj'`.

## Cross-Testament Routing

The service derives `language` ('greek' or 'hebrew') from the first token's `book_num` (OT < 40 ≤ NT), then routes all downstream lookups:

| Lookup | Greek branch | Hebrew branch |
|--------|--------------|----------------|
| POS weight table | `POS_WEIGHTS` (Robinson 'V-', 'N-', ...) | `POS_WEIGHTS_HEBREW` (HAM 'verb', 'subs', ...) |
| Frequency filter | `strongs_frequency.testament='NT'` | `strongs_frequency.testament='OT'` |
| Lexicon source filter | `tbESG` + `lsj` | `tbESH` |
| Occurrence cache (Macula count) | `WHERE book_num >= 40` | `WHERE book_num < 40` |
| `lexicon_source` tag in bundle | `'tbESG+LSJ'` | `'tbESH'` |

The routing is critical because Greek and Hebrew Strong's bare-int ranges overlap (e.g. G1 and H1 both normalize to bare int `'1'` via `normalize_strongs` in `build_lexicon_index.py`). The shared `macula_tokens` and `strongs_frequency` tables use `book_num` and `testament` as per-testament partition keys respectively.

## OT-Deferred Note

~~This implementation is NT-only. Hebrew OT integration is deferred to a future plan per the architecture's "OT: TBD" note in the Macula Lookup step.~~

**Resolved (2026-08-16):** The pipeline now supports both testaments end-to-end. Macula Hebrew WLC tokens and TBESH Lexicon senses are ingested by `scripts/download_macula_hebrew.py`, `scripts/build_macula_index.py --testament hebrew`, `scripts/build_strongs_frequency.py --testament hebrew`, and `scripts/build_lexicon_index.py --testament hebrew`. Per-hit routing by testament happens automatically in `ContextRetrievalService._build_bundle_for_hit`. See `tests/scripts/test_context_retrieval_hebrew.py` for the live contract and `tests/scripts/test_hebrew_ingest_integration.py` for ingest-path coverage.

## Known Limitations

1. **Missing Gloss Column**: ~~The `gloss` field on each kept_word is empty because todo 3's `macula_tokens` SQLite schema does not include the `gloss` column from the canonical TSV. Flagged for a follow-up "fix macula schema" plan.~~ RESOLVED (Macula schema follow-up, 2026-08-16): the `gloss` column was added to `macula_tokens` and re-ingested from the canonical TSV for both Greek and Hebrew; regression canaries in `test_context_retrieval_service.py` and `test_context_retrieval_e2e.py` validate non-empty glosses.

2. **Lexicon Source Substitution**: BDAG (Greek) and HALOT / TWOT (Hebrew) are explicitly excluded (copyrighted). For Greek, TBESG + LSJ are used instead. For Hebrew, TBESH is used. All three are public CC BY 4.0 from STEPBible.

3. **Aramaic Verses**: The WLC includes Aramaic passages (Ezra 4:8–6:18, 7:12-26; Daniel 2:4–7:28; Jeremiah 10:11). TBESH designates Aramaic senses via the `Morph` column `A:` prefix. The current ingest treats all Hebrew-canon words uniformly; Aramaic-specific sense filtering is deferred until a use case materialises.

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