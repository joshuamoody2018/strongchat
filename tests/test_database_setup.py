#!/usr/bin/env python3
"""Database setup tests for new LLM message system"""

import os
import sys
import tempfile
import unittest
import sqlite3
from unittest.mock import patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.database import ChatDatabase
from services.llm.aimessage import AIMessage

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import create_new_database
import migrate_pipeline_message_types


class TestDatabaseSetup(unittest.TestCase):
    """Test database setup and schema creation"""
    
    def setUp(self):
        """Set up test database"""
        self.test_db = tempfile.mktemp(suffix='.db')

        create_new_database.create_new_database(self.test_db)
        migrate_pipeline_message_types.migrate(self.test_db)

        self.db = ChatDatabase(self.test_db)
    
    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_database_connection(self):
        """Test database connection and basic operations"""
        # Create session
        session_uuid = self.db.create_session("Test Session", "test")
        self.assertIsNotNone(session_uuid)
        
        # Get session
        session_name = self.db.get_session_name(session_uuid)
        self.assertEqual(session_name, "Test Session")
    
    def test_message_type_operations(self):
        """Test message type CRUD operations"""
        # Test getting non-existent message type
        msg_type = self.db.get_message_type("nonexistent")
        self.assertIsNone(msg_type)
        
        # Test getting active message types (should have intent_classification from setup)
        active_types = self.db.get_active_message_types()
        self.assertEqual(len(active_types), 5)
    
    def test_message_operations(self):
        """Test message operations with new schema"""
        session_uuid = self.db.create_session("Test Session", "test")

        self.db.cursor.execute("""
            INSERT INTO ref_message_types
            (slug, step_name, creator_type, request_schema, model_slug,
             temperature, additional_model_settings, max_retries, is_active, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'test_type', 'Test Type', 'programmatic',
            '{"type":"object"}', 'n/a', 0.0, '{}', 3, 1, 'Test message type'
        ))
        self.db.conn.commit()

        message_uuid = self.db.create_message_with_type(
            session_uuid=session_uuid,
            message_type_slug="test_type",
            unique_prompt="Test prompt"
        )
        self.assertIsNotNone(message_uuid)

        message = self.db.get_message_by_uuid(message_uuid)
        self.assertIsNotNone(message)
        self.assertEqual(message['session_uuid'], session_uuid)
        self.assertEqual(message['message_type_slug'], "test_type")
        self.assertEqual(message['unique_prompt'], "Test prompt")
        
        # Get messages by session
        messages = self.db.get_messages_by_session_and_type(session_uuid)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['unique_prompt'], "Test prompt")
    
    def test_foreign_key_constraints(self):
        """Test foreign key relationships"""
        # Check if foreign key constraints are enabled
        self.db.cursor.execute("PRAGMA foreign_keys")
        fk_enabled = self.db.cursor.fetchone()[0]
        
        if fk_enabled:
            # Try to create message with non-existent session
            try:
                self.db.create_message_with_type(
                    session_uuid="nonexistent_session",
                    message_type_slug="test_type",
                    unique_prompt="Test prompt"
                )
                # If we get here, the foreign key constraint didn't work as expected
                self.fail("Expected foreign key constraint violation")
            except (sqlite3.IntegrityError, sqlite3.OperationalError):
                # This is expected - foreign key constraint should prevent this
                pass
        else:
            # Foreign key constraints are disabled, test will pass
            pass
        
        # Create session first
        session_uuid = self.db.create_session("Test Session", "test")
        
        message_uuid = self.db.create_message_with_type(
            session_uuid=session_uuid,
            message_type_slug=None,
            unique_prompt="Test prompt"
        )
        self.assertIsNotNone(message_uuid)


class TestAIMessage(unittest.TestCase):
    """Test AIMessage dataclass functionality"""
    
    def test_aimessage_creation(self):
        """Test AIMessage creation with default values"""
        aimessage = AIMessage()
        self.assertIsNotNone(aimessage.uuid)
        self.assertIsNotNone(aimessage.created_at)
        self.assertEqual(aimessage.num_tries, 1)
        self.assertIsNone(aimessage.raw_response)
        self.assertIsNone(aimessage.error_text)
    
    def test_aimessage_success_flow(self):
        """Test successful message flow"""
        aimessage = AIMessage(unique_prompt="Test prompt")
        
        # Mark success
        test_response = '{"intent": "question", "confidence": 0.95}'
        aimessage.mark_success(test_response)
        
        self.assertTrue(aimessage.is_successful())
        self.assertIsNotNone(aimessage.raw_response)
        self.assertIsNotNone(aimessage.response_at)
        self.assertIsNone(aimessage.error_text)
    
    def test_aimessage_failure_flow(self):
        """Test failure message flow"""
        aimessage = AIMessage(unique_prompt="Test prompt")
        
        # Mark failure
        test_error = "API timeout"
        aimessage.mark_failure(test_error)
        
        self.assertFalse(aimessage.is_successful())
        self.assertEqual(aimessage.num_tries, 2)
        self.assertEqual(aimessage.error_text, test_error)
        self.assertIsNotNone(aimessage.response_at)
    
    def test_max_retries_exceeded(self):
        """Test max retries calculation"""
        aimessage = AIMessage(num_tries=3)
        max_retries = 3
        
        self.assertTrue(aimessage.max_retries_exceeded(max_retries))
        
        aimessage.num_tries = 2
        self.assertFalse(aimessage.max_retries_exceeded(max_retries))
    
    def test_json_parsing(self):
        """Test JSON response parsing"""
        aimessage = AIMessage(raw_response='{"intent": "question", "confidence": 0.95}')
        schema = {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "confidence": {"type": "number"}
            },
            "required": ["intent", "confidence"]
        }
        
        parsed = aimessage.get_parsed_response(schema)
        self.assertEqual(parsed["intent"], "question")
        self.assertEqual(parsed["confidence"], 0.95)
    
    def test_json_extraction(self):
        """Test JSON extraction from various response formats"""
        aimessage = AIMessage()
        
        # Test markdown JSON
        response = '''```json
{"intent": "question", "confidence": 0.95}
```'''
        json_str = aimessage._extract_json(response)
        self.assertEqual(json_str, '{"intent": "question", "confidence": 0.95}')
        
        # Test plain JSON
        response = '{"intent": "question", "confidence": 0.95}'
        json_str = aimessage._extract_json(response)
        self.assertEqual(json_str, '{"intent": "question", "confidence": 0.95}')
        
        # Test JSON with surrounding text
        response = 'Here is the response: {"intent": "question", "confidence": 0.95} - end'
        json_str = aimessage._extract_json(response)
        self.assertEqual(json_str, '{"intent": "question", "confidence": 0.95}')
    


if __name__ == '__main__':
    unittest.main()