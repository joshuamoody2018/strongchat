#!/usr/bin/env python3
"""Create the SQLite database schema and seed ref_message_types (create + seed).

Single entry point for standing up data/chat_database.db: builds the
sessions / ref_message_types / messages tables and seeds the canonical
pipeline message-type rows. Seeding is idempotent (INSERT OR REPLACE), so the
script is safe to run multiple times; note it DROPS existing tables first.
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config

MODEL_INTENT_GENERATION = 'meta-llama/llama-3.3-70b-instruct'
MODEL_HYDE_GENERATION = 'mistralai/mistral-small-24b-instruct-2501'

EMBEDDING_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "dimension": {"type": "integer"},
        "count": {"type": "integer"},
    },
    "required": ["model", "dimension", "count"],
}

CONTEXT_RETRIEVAL_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "intent_id": {"type": "string"},
        "translation_count": {"type": "integer"},
        "hit_count": {"type": "integer"},
        "scored_word_count": {"type": "integer"},
        "kept_word_count": {"type": "integer"},
    },
    "required": ["intent_id", "translation_count", "hit_count", "scored_word_count", "kept_word_count"],
}

# (slug, step_name, creator_type, request_schema, model_slug, temperature,
#  additional_model_settings, max_retries, is_active, description, prompt_template)
SEED_MESSAGE_TYPES = [
    (
        'human_input',
        'Human Input',
        'human',
        '{"type":"object"}',
        'n/a',
        0.0,
        '{}',
        3,
        1,
        'User-originated input message',
        None,
    ),
    (
        'intent_generation',
        'Intent Generation',
        'programmatic',
        json.dumps(config.INTENT_GENERATION_SCHEMA),
        MODEL_INTENT_GENERATION,
        0.2,
        '{"max_tokens": 1200}',
        3,
        1,
        'Refined multi-intent generation for a user query',
        config.INTENT_GENERATION_PROMPT,
    ),
    (
        'hyde_generation',
        'HyDE Generation',
        'programmatic',
        json.dumps(config.HYDE_GENERATION_SCHEMA),
        MODEL_HYDE_GENERATION,
        0.7,
        '{"max_tokens": 800}',
        3,
        1,
        'Hypothetical biblical passage generated from a single intent',
        config.HYDE_GENERATION_PROMPT,
    ),
    (
        'embedding_generation',
        'Embedding Generation',
        'programmatic',
        json.dumps(EMBEDDING_REQUEST_SCHEMA),
        'openai/text-embedding-3-small',
        0.0,
        '{}',
        3,
        1,
        'Batched embedding generation call record (summary only, never raw vectors)',
        None,
    ),
    (
        'context_retrieval',
        'Context Retrieval',
        'programmatic',
        json.dumps(CONTEXT_RETRIEVAL_REQUEST_SCHEMA),
        'n/a',
        0.0,
        '{}',
        3,
        1,
        'Per-intent original-language context enrichment for retrieved verses',
        None,
    ),
]

SEED_SQL = """
INSERT OR REPLACE INTO ref_message_types
  (slug, step_name, creator_type, request_schema, model_slug, temperature,
   additional_model_settings, max_retries, is_active, description, prompt_template)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _create_schema(conn: sqlite3.Connection) -> None:
    """Drop and rebuild the sessions / ref_message_types / messages tables."""
    conn.execute("DROP TABLE IF EXISTS messages")
    conn.execute("DROP TABLE IF EXISTS ref_message_types")
    conn.execute("DROP TABLE IF EXISTS sessions")

    conn.execute('''
        CREATE TABLE sessions (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE ref_message_types (
            slug TEXT PRIMARY KEY,
            step_name TEXT NOT NULL,
            creator_type TEXT NOT NULL,
            request_schema TEXT NOT NULL,
            model_slug TEXT NOT NULL,
            temperature REAL DEFAULT 0.1,
            additional_model_settings TEXT,
            max_retries INTEGER DEFAULT 3,
            is_active BOOLEAN DEFAULT TRUE,
            description TEXT,
            prompt_template TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE messages (
            uuid TEXT PRIMARY KEY,
            session_uuid TEXT,
            message_type_slug TEXT,
            unique_prompt TEXT NOT NULL,
            raw_response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_at TIMESTAMP,
            num_tries INTEGER DEFAULT 1,
            error_text TEXT,
            FOREIGN KEY (session_uuid) REFERENCES sessions (uuid),
            FOREIGN KEY (message_type_slug) REFERENCES ref_message_types (slug)
        )
    ''')


def seed_ref_message_types(conn: sqlite3.Connection) -> None:
    """Seed the canonical pipeline message-type rows (idempotent)."""
    conn.executemany(SEED_SQL, SEED_MESSAGE_TYPES)


def create_new_database(db_path: str = 'data/chat_database.db') -> None:
    """Create the database schema and seed ref_message_types."""
    conn = sqlite3.connect(db_path)
    try:
        print("Dropping existing tables...")
        _create_schema(conn)

        print("Seeding ref_message_types...")
        seed_ref_message_types(conn)

        conn.commit()

        rows = conn.execute(
            "SELECT slug, is_active FROM ref_message_types ORDER BY slug"
        ).fetchall()
        print("ref_message_types:")
        for slug, is_active in rows:
            print(f"  {slug}: is_active={is_active}")
        print(f"Total rows: {len(rows)}")
    finally:
        conn.close()
    print("Database schema created and seeded successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create the database schema and seed ref_message_types")
    parser.add_argument(
        '--db-path',
        default='data/chat_database.db',
        help='Path to SQLite database file (default: data/chat_database.db)')
    args = parser.parse_args()
    create_new_database(args.db_path)
