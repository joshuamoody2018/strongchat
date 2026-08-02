#!/usr/bin/env python3
"""Create new database schema with ref_message_types and messages tables (schema only)"""

import argparse
import sqlite3


def create_new_database(db_path: str = 'data/chat_database.db') -> None:
    """Create database with new schema. Seeding is migrate_pipeline_message_types.py's job."""

    # Drop existing tables if they exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("Dropping existing tables...")
    cursor.execute("DROP TABLE IF EXISTS messages")
    cursor.execute("DROP TABLE IF EXISTS ref_message_types")
    cursor.execute("DROP TABLE IF EXISTS sessions")

    # Create sessions table (keep existing)
    cursor.execute('''
        CREATE TABLE sessions (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT
        )
    ''')

    # Create ref_message_types table (matches live schema)
    cursor.execute('''
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
            FOREIGN KEY (message_type_slug) REFERENCES ref_message_types (slug)
        )
    ''')

    conn.commit()
    conn.close()
    print("New database schema created successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create new database schema (schema only, no seeding)")
    parser.add_argument(
        '--db-path',
        default='data/chat_database.db',
        help='Path to SQLite database file (default: data/chat_database.db)')
    args = parser.parse_args()
    create_new_database(args.db_path)
