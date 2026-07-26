#!/usr/bin/env python3
"""Create new database schema with message_types and messages tables"""

import sqlite3
import json
from datetime import datetime

def create_new_database(db_path: str = 'data/chat_database.db') -> None:
    """Create database with new schema and populate initial message types."""
    
    # Drop existing tables if they exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Dropping existing tables...")
    cursor.execute("DROP TABLE IF EXISTS messages")
    cursor.execute("DROP TABLE IF EXISTS message_types")
    cursor.execute("DROP TABLE IF EXISTS sessions")
    cursor.execute("DROP TABLE IF EXISTS intents")
    
    # Create sessions table (keep existing)
    cursor.execute('''
        CREATE TABLE sessions (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT
        )
    ''')
    
    # Create message_types table (new)
    cursor.execute('''
        CREATE TABLE message_types (
            slug TEXT PRIMARY KEY,
            step_name TEXT NOT NULL,
            creator_type TEXT NOT NULL,
            request_schema TEXT NOT NULL,
            model_slug TEXT NOT NULL,
            temperature REAL DEFAULT 0.1,
            additional_model_settings TEXT,
            max_retries INTEGER DEFAULT 3,
            is_active BOOLEAN DEFAULT TRUE,
            description TEXT
        )
    ''')
    
    # Create messages table (new - replaces old messages)
    cursor.execute('''
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
            FOREIGN KEY (message_type_slug) REFERENCES message_types (slug)
        )
    ''')
    
    conn.commit()
    
    # Populate initial message types
    initial_message_types = [
        {
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
            "description": "Classify user message intent"
        }
    ]
    
    print("Populating initial message types...")
    for msg_type in initial_message_types:
        cursor.execute('''
            INSERT INTO message_types 
            (slug, step_name, creator_type, request_schema, model_slug, temperature, 
             additional_model_settings, max_retries, is_active, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            msg_type["description"]
        ))
    
    conn.commit()
    conn.close()
    print("New database schema created and populated successfully!")

if __name__ == "__main__":
    create_new_database()