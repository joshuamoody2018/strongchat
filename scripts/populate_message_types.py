#!/usr/bin/env python3
"""Populate ref_message_types table with existing schemas"""

import argparse
import json
import os
import sqlite3
import sys

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config.prompts import INTENT_CLASSIFICATION_PROMPT, INTENT_DISAMBIGUATION_PROMPT
from config.schemas import INTENT_DISAMBIGUATION_SCHEMA


def populate_message_types(db_path: str = 'data/chat_database.db'):
    """Populate ref_message_types table with existing schemas."""

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Intent Classification (already exists, but let's update it)
    # request_schema stays the simple inline shape: main.py depends on it exactly.
    intent_schema = {
        "slug": "intent_classification",
        "step_name": "Intent Classification",
        "creator_type": "programmatic",
        "request_schema": json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "IntentClassificationResponse",
            "description": "Classification of user intent",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "Primary intent classification",
                    "enum": ["greeting", "question", "statement", "command", "goodbye", "help"]
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Confidence score for the classification"
                }
            },
            "required": ["intent", "confidence"]
        }),
        "model_slug": "openai/gpt-3.5-turbo",
        "temperature": 0.1,
        "additional_model_settings": json.dumps({"max_tokens": 100}),
        "max_retries": 3,
        "is_active": True,
        "description": "Classify user message intent for biblical search",
        "prompt_template": INTENT_CLASSIFICATION_PROMPT
    }

    # Intent Disambiguation (schema and prompt sourced from config)
    intent_disambiguation_schema = {
        "slug": "intent_disambiguation",
        "step_name": "Intent Disambiguation",
        "creator_type": "programmatic",
        "request_schema": json.dumps(INTENT_DISAMBIGUATION_SCHEMA),
        "model_slug": "openai/gpt-3.5-turbo",
        "temperature": 0.2,
        "additional_model_settings": json.dumps({"max_tokens": 500}),
        "max_retries": 3,
        "is_active": True,
        "description": "Disambiguate user queries to identify multiple possible interpretations",
        "prompt_template": INTENT_DISAMBIGUATION_PROMPT
    }

    message_types = [intent_schema, intent_disambiguation_schema]

    # Insert or update message types
    for msg_type in message_types:
        cursor.execute('''
            INSERT OR REPLACE INTO ref_message_types
            (slug, step_name, creator_type, request_schema, model_slug, temperature,
             additional_model_settings, max_retries, is_active, description, prompt_template)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            msg_type["slug"],
            msg_type["step_name"],
            msg_type["creator_type"],
            msg_type["request_schema"],
            msg_type["model_slug"],
            msg_type["temperature"],
            msg_type["additional_model_settings"],
            msg_type["max_retries"],
            msg_type["is_active"],
            msg_type["description"],
            msg_type["prompt_template"]
        ))

    conn.commit()
    conn.close()
    print(f"Populated {len(message_types)} message types successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Populate ref_message_types table (idempotent)")
    parser.add_argument(
        '--db-path',
        default='data/chat_database.db',
        help='Path to SQLite database file (default: data/chat_database.db)')
    args = parser.parse_args()
    populate_message_types(args.db_path)
