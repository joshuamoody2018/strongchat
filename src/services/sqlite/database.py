#!/usr/bin/env python3
"""SQLite database wrapper for StrongChat"""
import sqlite3
import uuid
import json
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

class ChatDatabase:
    """SQLite database wrapper for chat sessions, messages, and intents."""
    
    def __init__(self, db_path: str = 'data/chat_database.db'):
        """Initialize the database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys = ON")
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
        """DEPRECATED: Use create_message_with_type instead.
        Create a new message in a session.
        
        Args:
            session_uuid: UUID of the session
            input_text: User input message
            output_text: AI response message
            
        Returns:
            UUID of the created message
        """
        message_uuid = str(uuid.uuid4())
        self.cursor.execute(
            "INSERT INTO messages (uuid, session_uuid, unique_prompt, raw_response) VALUES (?, ?, ?, ?)",
            (message_uuid, session_uuid, input_text, output_text)
        )
        self.conn.commit()
        return message_uuid
    
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
        
        self.cursor.execute("""
            INSERT INTO messages (uuid, session_uuid, message_type_slug, unique_prompt, 
                                raw_response, created_at, response_at, num_tries, error_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (message_uuid, session_uuid, message_type_slug, unique_prompt, 
              raw_response, datetime.now(), response_at, num_tries, error_text))
        
        self.conn.commit()
        return message_uuid
    
    def get_message_by_uuid(self, message_uuid: str) -> Optional[Dict[str, Any]]:
        """Get message by UUID with full details.
        
        Args:
            message_uuid: UUID of the message
            
        Returns:
            Message dict or None if not found
        """
        self.cursor.execute("""
            SELECT m.uuid, m.session_uuid, m.message_type_slug, m.unique_prompt,
                   m.raw_response, m.created_at, m.response_at, m.num_tries, m.error_text,
                   mt.step_name, mt.creator_type, mt.model_slug
            FROM messages m
            LEFT JOIN ref_message_types mt ON m.message_type_slug = mt.slug
            WHERE m.uuid = ?
        """, (message_uuid,))
        
        result = self.cursor.fetchone()
        if not result:
            return None
            
        return {
            'uuid': result[0],
            'session_uuid': result[1],
            'message_type_slug': result[2],
            'unique_prompt': result[3],
            'raw_response': result[4],
            'created_at': datetime.fromisoformat(result[5]),
            'response_at': datetime.fromisoformat(result[6]) if result[6] else None,
            'num_tries': result[7],
            'error_text': result[8],
            'step_name': result[9],
            'creator_type': result[10],
            'model_slug': result[11]
        }
    
    def get_messages_by_session_and_type(self, session_uuid: str, message_type_slug: str = None) -> List[Dict[str, Any]]:
        """Get messages for a session, optionally filtered by message type.
        
        Args:
            session_uuid: UUID of the session
            message_type_slug: Optional message type slug filter
            
        Returns:
            List of message dicts
        """
        if message_type_slug:
            self.cursor.execute("""
                SELECT m.uuid, m.session_uuid, m.message_type_slug, m.unique_prompt,
                       m.raw_response, m.created_at, m.response_at, m.num_tries, m.error_text,
                       mt.step_name, mt.creator_type, mt.model_slug
                FROM messages m
                LEFT JOIN ref_message_types mt ON m.message_type_slug = mt.slug
                WHERE m.session_uuid = ? AND m.message_type_slug = ?
                ORDER BY m.created_at
            """, (session_uuid, message_type_slug))
        else:
            self.cursor.execute("""
                SELECT m.uuid, m.session_uuid, m.message_type_slug, m.unique_prompt,
                       m.raw_response, m.created_at, m.response_at, m.num_tries, m.error_text,
                       mt.step_name, mt.creator_type, mt.model_slug
                FROM messages m
                LEFT JOIN ref_message_types mt ON m.message_type_slug = mt.slug
                WHERE m.session_uuid = ?
                ORDER BY m.created_at
            """, (session_uuid,))
        
        results = self.cursor.fetchall()
        messages = []
        for result in results:
            messages.append({
                'uuid': result[0],
                'session_uuid': result[1],
                'message_type_slug': result[2],
                'unique_prompt': result[3],
                'raw_response': result[4],
                'created_at': datetime.fromisoformat(result[5]),
                'response_at': datetime.fromisoformat(result[6]) if result[6] else None,
                'num_tries': result[7],
                'error_text': result[8],
                'step_name': result[9],
                'creator_type': result[10],
                'model_slug': result[11]
            })
        
        return messages
    
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
        """DEPRECATED: Use get_messages_by_session_and_type instead.
        Get all messages for a session.
        
        Args:
            session_uuid: UUID of the session
            
        Returns:
            List of (uuid, input, output, created_on) tuples
        """
        self.cursor.execute(
            "SELECT uuid, unique_prompt, raw_response, created_at FROM messages WHERE session_uuid = ? ORDER BY created_at",
            (session_uuid,)
        )
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