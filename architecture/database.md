# Database Architecture

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

#### Intents Table
```sql
CREATE TABLE intents (
    uuid TEXT PRIMARY KEY,
    message_uuid TEXT NOT NULL,
    intent TEXT,  -- JSON string for structured intent data
    FOREIGN KEY (message_uuid) REFERENCES messages (uuid)
);
```

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
  ],
  "recommended_search_approach": "Prioritize the primary intent"
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
- Utilities: `scripts/create_database.py`, `scripts/check_database.py`

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