#!/usr/bin/env python3
"""Database utilities for StrongChat"""
import sqlite3
from typing import List, Tuple


def check_database(db_path: str = 'data/chat_database.db') -> None:
    """Check and display database structure.
    
    Args:
        db_path: Path to the SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Tables in database:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    for table in tables:
        print(f"  {table[0]}")
    
    print("\nTable schemas:")
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table[0]})")
        columns = cursor.fetchall()
        print(f"\n{table[0]}:")
        for col in columns:
            constraints = []
            if col[5]:
                constraints.append("PRIMARY KEY")
            if col[3]:
                constraints.append("NOT NULL")
            if col[4] is not None:
                constraints.append(f"DEFAULT {col[4]}")
            
            constraint_str = " ".join(constraints) if constraints else ""
            print(f"  {col[1]} {col[2]} {constraint_str}")
    
    conn.close()


def create_database(db_path: str = 'data/chat_database.db') -> None:
    """Create database and tables.
    
    Args:
        db_path: Path to the SQLite database file
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT
        )
    ''')
    
    # Create messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            uuid TEXT PRIMARY KEY,
            session_uuid TEXT NOT NULL,
            input TEXT,
            output TEXT,
            created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_uuid) REFERENCES sessions (uuid)
        )
    ''')
    
    # Create intents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS intents (
            uuid TEXT PRIMARY KEY,
            message_uuid TEXT NOT NULL,
            intent TEXT,
            FOREIGN KEY (message_uuid) REFERENCES messages (uuid)
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database and tables created successfully at: {db_path}")


def get_database_stats(db_path: str = 'data/chat_database.db') -> dict:
    """Get database statistics.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        Dictionary with database statistics
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    stats = {}
    
    # Get session count
    cursor.execute("SELECT COUNT(*) FROM sessions")
    stats['session_count'] = cursor.fetchone()[0]
    
    # Get message count
    cursor.execute("SELECT COUNT(*) FROM messages")
    stats['message_count'] = cursor.fetchone()[0]
    
    # Get intent count
    cursor.execute("SELECT COUNT(*) FROM intents")
    stats['intent_count'] = cursor.fetchone()[0]
    
    # Get oldest and newest sessions
    cursor.execute("SELECT MIN(created_on), MAX(created_on) FROM sessions")
    result = cursor.fetchone()
    stats['oldest_session'] = result[0]
    stats['newest_session'] = result[1]
    
    conn.close()
    return stats