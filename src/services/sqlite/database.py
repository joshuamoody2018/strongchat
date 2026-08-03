#!/usr/bin/env python3
"""SQLite database wrapper for StrongChat"""
import sqlite3
import uuid
import json
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

class ChatDatabase:
    """SQLite database wrapper for chat sessions, messages, and intents."""
    
    def __init__(self, db_path: str = 'data/chat_database.db', check_same_thread: bool = True):
        """Initialize the database connection.
        
        Args:
            db_path: Path to the SQLite database file
            check_same_thread: Passed through to sqlite3.connect
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.cursor = self.conn.cursor()
        self._closed = False
    
    def _execute_write(self, sql: str, parameters: Tuple = ()) -> None:
        """Execute a write statement inside a transaction that auto-commits or rolls back.
        
        Uses the connection context manager so a failed write does not leave the
        connection in an aborted transaction state.
        """
        with self.conn:
            self.cursor.execute(sql, parameters)
    
    def create_session(self, name: str, created_by: str = "user") -> str:
        """Create a new chat session.
        
        Args:
            name: Name for the session
            created_by: Creator of the session
            
        Returns:
            UUID of the created session
        """
        session_uuid = str(uuid.uuid4())
        self._execute_write(
            "INSERT INTO sessions (uuid, name, created_by) VALUES (?, ?, ?)",
            (session_uuid, name, created_by)
        )
        return session_uuid

    def get_message_type(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get message type configuration by slug.
        
        Args:
            slug: Message type slug
            
        Returns:
            Message type configuration dict or None if not found
        """
        self.cursor.execute("""
            SELECT slug, step_name, creator_type, request_schema, model_slug, 
                   temperature, additional_model_settings, max_retries, is_active, description, prompt_template
            FROM ref_message_types 
            WHERE slug = ? AND is_active = 1
        """, (slug,))
        result = self.cursor.fetchone()
        
        if not result:
            return None
            
        return {
            'slug': result[0],
            'step_name': result[1],
            'creator_type': result[2],
            'request_schema': json.loads(result[3]),
            'model_slug': result[4],
            'temperature': result[5],
            'additional_model_settings': json.loads(result[6]) if result[6] else {},
            'max_retries': result[7],
            'is_active': bool(result[8]),
            'description': result[9],
            'prompt_template': result[10] if result[10] else None
        }
    
    def create_message_with_type(self, session_uuid: str, message_type_slug: str, 
                                unique_prompt: str, raw_response: Optional[str] = None,
                                num_tries: int = 1, error_text: Optional[str] = None) -> str:
        """Create a new message with message type.
        
        Args:
            session_uuid: UUID of the session
            message_type_slug: Slug of the message type
            unique_prompt: The core message content
            raw_response: Raw AI response (optional)
            num_tries: Number of tries (default 1)
            error_text: Error text if failed (optional)
            
        Returns:
            UUID of the created message
        """
        message_uuid = str(uuid.uuid4())
        response_at = datetime.now() if raw_response or error_text else None
        
        self._execute_write("""
            INSERT INTO messages (uuid, session_uuid, message_type_slug, unique_prompt, 
                                raw_response, created_at, response_at, num_tries, error_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (message_uuid, session_uuid, message_type_slug, unique_prompt, 
              raw_response, datetime.now(), response_at, num_tries, error_text))
        
        return message_uuid
    

    

    
    def get_active_message_types(self) -> List[Dict[str, Any]]:
        """Get all active message types.
        
        Returns:
            List of active message type configs
        """
        self.cursor.execute("""
            SELECT slug, step_name, creator_type, request_schema, model_slug,
                   temperature, additional_model_settings, max_retries, is_active, description, prompt_template
            FROM ref_message_types 
            WHERE is_active = 1
            ORDER BY step_name
        """)
        
        results = self.cursor.fetchall()
        message_types = []
        for result in results:
            message_types.append({
                'slug': result[0],
                'step_name': result[1],
                'creator_type': result[2],
                'request_schema': json.loads(result[3]),
                'model_slug': result[4],
                'temperature': result[5],
                'additional_model_settings': json.loads(result[6]) if result[6] else {},
                'max_retries': result[7],
                'is_active': bool(result[8]),
                'description': result[9],
                'prompt_template': result[10] if result[10] else None
            })
        
        return message_types
    

    

    

    
    def close(self):
        """Close the database connection."""
        if self._closed:
            return
        try:
            self.conn.close()
        finally:
            self._closed = True
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()