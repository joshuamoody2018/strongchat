#!/usr/bin/env python3
"""SQLite database wrapper for StrongChat"""
import sqlite3
import uuid
from datetime import datetime
from typing import Optional, List, Tuple


class ChatDatabase:
    """SQLite database wrapper for chat sessions, messages, and intents."""
    
    def __init__(self, db_path: str = 'data/chat_database.db'):
        """Initialize the database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
    
    def create_session(self, name: str, created_by: str = "user") -> str:
        """Create a new chat session.
        
        Args:
            name: Name for the session
            created_by: Creator of the session
            
        Returns:
            UUID of the created session
        """
        session_uuid = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO sessions (uuid, name, created_by) VALUES (?, ?, ?)",
            (session_uuid, name, created_by)
        )
        self.conn.commit()
        return session_uuid
    
    def create_message(self, session_uuid: str, input_text: str, output_text: str) -> str:
        """Create a new message in a session.
        
        Args:
            session_uuid: UUID of the session
            input_text: User input message
            output_text: AI response message
            
        Returns:
            UUID of the created message
        """
        message_uuid = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO messages (uuid, session_uuid, input, output) VALUES (?, ?, ?, ?)",
            (message_uuid, session_uuid, input_text, output_text)
        )
        self.conn.commit()
        return message_uuid
    
    def create_intent(self, message_uuid: str, intent: str) -> str:
        """Create an intent record for a message.
        
        Args:
            message_uuid: UUID of the message
            intent: Intent classification
            
        Returns:
            UUID of the created intent
        """
        intent_uuid = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO intents (uuid, message_uuid, intent) VALUES (?, ?, ?)",
            (intent_uuid, message_uuid, intent)
        )
        self.conn.commit()
        return intent_uuid
    
    def get_session_name(self, session_uuid: str) -> Optional[str]:
        """Get session name by UUID.
        
        Args:
            session_uuid: UUID of the session
            
        Returns:
            Session name or None if not found
        """
        self.cursor.execute("SELECT name FROM sessions WHERE uuid = ?", (session_uuid,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def get_sessions(self) -> List[Tuple[str, str, str]]:
        """Get all sessions ordered by creation time.
        
        Returns:
            List of (uuid, name, created_on) tuples
        """
        self.cursor.execute("SELECT uuid, name, created_on FROM sessions ORDER BY created_on DESC")
        return self.cursor.fetchall()
    
    def get_messages(self, session_uuid: str) -> List[Tuple[str, str, str, str]]:
        """Get all messages for a session.
        
        Args:
            session_uuid: UUID of the session
            
        Returns:
            List of (uuid, input, output, created_on) tuples
        """
        self.cursor.execute(
            "SELECT uuid, input, output, created_on FROM messages WHERE session_uuid = ? ORDER BY created_on",
            (session_uuid,)
        )
        return self.cursor.fetchall()
    
    def get_intents_for_message(self, message_uuid: str) -> List[Tuple[str, str]]:
        """Get all intents for a message.
        
        Args:
            message_uuid: UUID of the message
            
        Returns:
            List of (uuid, intent) tuples
        """
        self.cursor.execute("SELECT uuid, intent FROM intents WHERE message_uuid = ?", (message_uuid,))
        return self.cursor.fetchall()
    
    def close(self):
        """Close the database connection."""
        self.conn.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()