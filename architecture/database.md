# Database Architecture

## Databases

StrongChat uses TWO separate databases:

1. **`data/chat_database.db`** — Chat database for sessions, messages, ref_message_types, and intents
2. **`data/macula_index.db`** — Macula Greek original-language index (macula_tokens, strongs_frequency, lexicon_definitions)

## Overview

SQLite database layer for chat sessions, messages, and structured intent storage. Designed for auditability and efficient retrieval.

## Schema Design

### Core Tables

#### Sessions Table
```sql
CREATE TABLE sessions (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT
);
```

#### Messages Table
```sql
CREATE TABLE messages (
    uuid TEXT PRIMARY KEY,
    session_uuid TEXT NOT NULL,
    input TEXT,
    output TEXT,
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_uuid) REFERENCES sessions (uuid)
);
```

#### ref_message_types Table
```sql
CREATE TABLE ref_message_types (
    slug TEXT PRIMARY KEY,
    step_name TEXT NOT NULL,
    creator_type TEXT NOT NULL,  -- 'human', 'llm', or 'programmatic'
    request_schema TEXT,         -- JSON schema for validation
    model_slug TEXT,
    temperature REAL,
    additional_model_settings TEXT,  -- JSON for model-specific settings
    max_retries INTEGER DEFAULT 3,
    is_active INTEGER DEFAULT 1,
    description TEXT,
    prompt_template TEXT
);
```

#### Intents Table
```sql
CREATE TABLE intents (
    uuid TEXT PRIMARY KEY,
    message_uuid TEXT NOT NULL,
    intent TEXT,  -- JSON string for structured intent data
    FOREIGN KEY (message_uuid) REFERENCES messages (uuid)
);
```

**Note**: The `messages` table has a foreign key to `ref_message_types` (the modern pattern). The existing `intents` table may be deprecated as intent data is now stored directly in the `messages` table via the `intent_generation` message type.

## Data Layer Components

### Database Service (`src/services/sqlite/database.py`)
```python
class ChatDatabase:
    """SQLite database wrapper with context management"""
    
    Methods:
    - create_session() - Create new chat session
    - create_message() - Store user/AI messages
    - create_intent() - Store structured intent data
    - get_sessions() - List all sessions
    - get_messages() - Retrieve session messages
    - get_intents_for_message() - Get intent data for message
```

### Database Utilities (`src/services/sqlite/utils.py`)
```python
Functions:
- create_database() - Initialize database schema
- check_database() - Display database structure
- get_database_stats() - Get usage statistics
```

## Data Flow

1. **User Input** → `create_message()` → Store in messages table
2. **Intent Analysis** → `create_intent()` → Store JSON string in intents table
3. **AI Response** → `create_message()` → Store output in messages table
4. **Session Management** → `create_session()` → Track conversation context

## Macula Greek Index (data/macula_index.db)

The Macula Greek index is a separate SQLite database containing original-language data for New Testament Greek:

### macula_tokens Table
- **Schema**: `row_id INTEGER PRIMARY KEY, book_num INTEGER, book_osis TEXT, chapter INTEGER, verse INTEGER, word_pos INTEGER, surface TEXT, lemma TEXT, strongs TEXT, morph TEXT, pos TEXT`
- **Content**: 137,741 tokens across 27 NT books from Macula Greek SBLGNT
- **Source**: `scripts/build_macula_index.py`
- **License**: CC BY 4.0

### strongs_frequency Table
- **Schema**: `strongs TEXT PRIMARY KEY, frequency_count INTEGER`
- **Content**: 5,440 NT Strong's numbers with frequency counts
- **Source**: `scripts/build_strongs_frequency.py`
- **Purpose**: Used for scoring in context retrieval

### lexicon_definitions Table
- **Schema**: `strongs TEXT, sense_id INTEGER, lexicon_source TEXT, definitions TEXT, glosses TEXT`
- **Content**: ~16,000 senses across TBESG + LSJ lexicons
- **Source**: `scripts/build_lexicon_index.py`
- **License**: CC BY 4.0 (TBESG + LSJ)

### Usage
The context retrieval service queries this database to enrich retrieved verses with original-language data, including lemma, Strong's number, morphological information, and lexicon definitions.

## Structured Intent Storage

### Migration Plan
- **Current**: Simple intent strings ("greeting", "question")
- **Future**: JSON strings with structured intent data

### Example Storage Format
```json
{
  "query_analysis": {
    "original_query": "why do bad things happen",
    "core_questions": ["Why does suffering occur?"],
    "context_clues": ["suffering", "pain"]
  },
  "intents": [
    {
      "intent_id": "theodicy",
      "interpretation": "Understanding the problem of evil",
      "keywords_explicit": ["bad", "things", "happen"],
      "keywords_inferred": ["suffering", "evil", "pain"],
      "themes": ["theodicy", "suffering"],
      "confidence": 0.9,
      "is_primary": true
    }
  ]
}
```

## Integration Points

- **LLM Framework**: Stores structured intent responses
- **Chat Interface**: Provides session-based conversation history
- **Audit Trail**: All intent decisions stored in database
- **Pipeline Integration**: Structured data available for downstream processing

## File Locations

- Implementation: `src/services/sqlite/`
- Database: `data/chat_database.db`
- Macula Index: `data/macula_index.db`
- Utilities: `scripts/create_new_database.py` (schema) + `scripts/migrate_pipeline_message_types.py` (seeding)
- Macula Scripts: `scripts/download_macula_greek.py`, `scripts/build_macula_index.py`, `scripts/build_strongs_frequency.py`, `scripts/build_lexicon_index.py`

## Performance Considerations

- Indexes on foreign keys for efficient joins
- UUID-based primary keys for distributed systems
- JSON storage for flexible schema evolution
- Context managers for connection pooling

## Testing

- ✅ Database operations tests
- ✅ CRUD operations validation
- 🚧 Concurrent access tests (planned)
- 🚧 Performance benchmarks (planned)