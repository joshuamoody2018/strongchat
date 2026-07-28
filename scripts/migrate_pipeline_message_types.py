#!/usr/bin/env python3
"""Seed pipeline message types into ref_message_types (hyde-retrieval-pipeline task 6).

Steps:
  0. Back up the database to <db_path>.pre-pipeline.bak via sqlite3's backup API
     (an existing backup is overwritten).
  1. INSERT OR REPLACE the 5 pipeline message-type rows
     (human_input, llm_response, error, embedding_generation, corpus_ingest).
  2. Deactivate intent_disambiguation (superseded; zero callers).
     intent_classification is NOT touched (main.py depends on it).

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
        'llm_response',
        'LLM Response',
        'llm',
        '{"type":"object"}',
        'n/a',
        0.0,
        'Assistant response message',
    ),
    (
        'error',
        'Error',
        'programmatic',
        '{"type":"object"}',
        'n/a',
        0.0,
        'Error record for failed operations',
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
        'corpus_ingest',
        'Corpus Ingest',
        'programmatic',
        '{"type":"object","properties":{"translation":{"type":"string"},"verses":{"type":"integer"},"status":{"type":"string"}},"required":["translation","verses","status"]}',
        'n/a',
        0.0,
        'One summary row per translation corpus ingest',
    ),
]

INSERT_SQL = """
INSERT OR REPLACE INTO ref_message_types
  (slug, step_name, creator_type, request_schema, model_slug, temperature,
   additional_model_settings, max_retries, is_active, description, prompt_template)
VALUES (?, ?, ?, ?, ?, ?, '{}', 3, 1, ?, NULL)
"""

DEACTIVATE_SQL = (
    "UPDATE ref_message_types SET is_active=0 WHERE slug='intent_disambiguation'"
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
    'openai/gpt-4.1-mini',
    0.2,
    '{"max_tokens": 800}',
    3,
    1,
    'Refined multi-intent generation for a user query',
    config.INTENT_GENERATION_PROMPT,
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


def migrate(db_path: str) -> str:
    """Back up db_path, seed pipeline message types, deactivate intent_disambiguation."""
    backup_path = backup_database(db_path)
    print(f"Backup written: {backup_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(INSERT_SQL, PIPELINE_MESSAGE_TYPES)
        conn.execute(INTENT_GENERATION_SQL, INTENT_GENERATION_ROW)
        conn.execute(DEACTIVATE_SQL)
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
