#!/usr/bin/env python3
"""Seed pipeline message types into ref_message_types (hyde-retrieval-pipeline task 6).

Steps:
  0. Back up the database to <db_path>.pre-pipeline.bak via sqlite3's backup API
     (an existing backup is overwritten).
  1. DELETE the superseded intent_disambiguation and intent_classification rows
  2. INSERT OR REPLACE the 6 pipeline message-type rows
     (human_input, llm_response, embedding_generation, corpus_ingest, intent_generation, hyde_generation).
   3. Upsert context_retrieval using summary schema (not LLM schema).
   4. Upsert intent_generation and hyde_generation using cheap open-weight models.

Idempotent: safe to run multiple times against the same database.
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import config

BACKUP_SUFFIX = '.pre-pipeline.bak'

MODEL_INTENT_GENERATION = 'meta-llama/llama-3.3-70b-instruct'
MODEL_HYDE_GENERATION = 'mistralai/mistral-small-24b-instruct-2501'

# (slug, step_name, creator_type, request_schema, model_slug, temperature, description)
PIPELINE_MESSAGE_TYPES = [
    (
        'human_input',
        'Human Input',
        'human',
        '{"type":"object"}',
        'n/a',
        0.0,
        'User-originated input message',
    ),
    (
        'intent_generation',
        'Intent Generation',
        'programmatic',
        json.dumps(config.INTENT_GENERATION_SCHEMA),
        MODEL_INTENT_GENERATION,
        0.2,
        'Refined multi-intent generation for a user query',
    ),
    (
        'hyde_generation',
        'HyDE Generation',
        'programmatic',
        json.dumps(config.HYDE_GENERATION_SCHEMA),
        MODEL_HYDE_GENERATION,
        0.7,
        'Hypothetical biblical passage generated from a single intent',
    ),
    (
        'embedding_generation',
        'Embedding Generation',
        'programmatic',
        '{"type":"object","properties":{"model":{"type":"string"},"dimension":{"type":"integer"},"count":{"type":"integer"}},"required":["model","dimension","count"]}',
        'openai/text-embedding-3-small',
        0.0,
        'Batched embedding generation call record (summary only, never raw vectors)',
    ),
    (
        'llm_response',
        'LLM Response',
        'llm',
        '{"type":"object"}',
        'n/a',
        0.0,
        'Assistant response message',
    ),
]

INSERT_SQL = """
INSERT OR REPLACE INTO ref_message_types
  (slug, step_name, creator_type, request_schema, model_slug, temperature,
   additional_model_settings, max_retries, is_active, description, prompt_template)
VALUES (?, ?, ?, ?, ?, ?, '{}', 3, 1, ?, NULL)
"""

DELETE_SQL = (
    "DELETE FROM ref_message_types WHERE slug IN ('intent_disambiguation', 'intent_classification', 'error', 'corpus_ingest')"
)

INTENT_GENERATION_SQL = """
INSERT OR REPLACE INTO ref_message_types
  (slug, step_name, creator_type, request_schema, model_slug, temperature,
   additional_model_settings, max_retries, is_active, description, prompt_template)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

INTENT_GENERATION_ROW = (
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
)

HYDE_GENERATION_ROW = (
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
)


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

CONTEXT_RETRIEVAL_ROW = (
    'context_retrieval',                                          # slug
    'Context Retrieval',                                          # step_name
    'programmatic',                                               # creator_type (NOT 'llm')
    json.dumps(CONTEXT_RETRIEVAL_REQUEST_SCHEMA),                 # request_schema (SUMMARY shape)
    'n/a',                                                        # model_slug
    0.0,                                                          # temperature
    '{}',                                                         # additional_model_settings
    3,                                                            # max_retries
    1,                                                            # is_active
    'Per-intent original-language context enrichment for retrieved verses',  # description
    None,                                                         # prompt_template (NULL — not an LLM message)
)


def backup_database(db_path: str) -> str:
    """Copy db_path to <db_path>.pre-pipeline.bak, overwriting any prior backup."""
    backup_path = db_path + BACKUP_SUFFIX
    source = sqlite3.connect(db_path)
    try:
        dest = sqlite3.connect(backup_path)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return backup_path


def _seed_rows(conn: sqlite3.Connection) -> None:
    """Seed all 6 pipeline message types into the database connection."""
    conn.execute(DELETE_SQL)
    conn.executemany(INSERT_SQL, PIPELINE_MESSAGE_TYPES)
    conn.execute(INTENT_GENERATION_SQL, INTENT_GENERATION_ROW)
    conn.execute(INTENT_GENERATION_SQL, HYDE_GENERATION_ROW)
    conn.execute(INTENT_GENERATION_SQL, CONTEXT_RETRIEVAL_ROW)


def migrate(db_path: str) -> str:
    """Back up db_path, seed pipeline message types, drop intent_disambiguation."""
    backup_path = backup_database(db_path)
    print(f"Backup written: {backup_path}")

    conn = sqlite3.connect(db_path)
    try:
        _seed_rows(conn)
        conn.commit()

        rows = conn.execute(
            "SELECT slug, is_active FROM ref_message_types ORDER BY slug"
        ).fetchall()
        print("ref_message_types after migration:")
        for slug, is_active in rows:
            print(f"  {slug}: is_active={is_active}")
        print(f"Total rows: {len(rows)}")
    finally:
        conn.close()

    return backup_path


def main():
    parser = argparse.ArgumentParser(
        description="Seed pipeline message types into ref_message_types"
    )
    parser.add_argument(
        '--db-path',
        default='data/chat_database.db',
        help="Path to the SQLite database (default: data/chat_database.db)",
    )
    args = parser.parse_args()
    migrate(args.db_path)


if __name__ == '__main__':
    main()
