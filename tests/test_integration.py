#!/usr/bin/env python3
"""Integration tests for complete LLM message system"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest
import asyncio
from unittest.mock import patch, AsyncMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.database import ChatDatabase
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage
from services.llm.exceptions import APITimeoutError, APIConnectionError
from config.cache import GlobalReferenceCache


class TestIntegration(unittest.TestCase):
    """Integration tests for complete LLM message system"""
    
    SCHEMA_SQL = """
    CREATE TABLE sessions (
        uuid TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT
    );

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
    );

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
    );
    """

    def setUp(self):
        """Set up test database and mock data"""
        self.test_db = tempfile.mktemp(suffix='.db')

        with sqlite3.connect(self.test_db) as setup_conn:
            setup_conn.executescript(self.SCHEMA_SQL)

        self.db = ChatDatabase(self.test_db)

        # Create test session
        self.session_uuid = self.db.create_session("Integration Test Session", "test")
        
        # Insert a mock message type for testing
        self.message_type = {
            "slug": "intent_classification",
            "step_name": "Intent Classification",
            "creator_type": "programmatic",
            "request_schema": '{"type": "object", "properties": {"intent": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["intent", "confidence"]}',
            "model_slug": "meta-llama/llama-3.1-8b-instruct",
            "temperature": 0.1,
            "additional_model_settings": '{"max_tokens": 500}',
            "max_retries": 5,
            "is_active": True,
            "description": "Classify user message intent"
        }

        self.db.cursor.execute('''
            INSERT INTO ref_message_types
            (slug, step_name, creator_type, request_schema, model_slug, temperature,
             additional_model_settings, max_retries, is_active, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            self.message_type["slug"],
            self.message_type["step_name"],
            self.message_type["creator_type"],
            self.message_type["request_schema"],
            self.message_type["model_slug"],
            self.message_type["temperature"],
            self.message_type["additional_model_settings"],
            self.message_type["max_retries"],
            self.message_type["is_active"],
            self.message_type["description"]
        ))
        self.db.conn.commit()

        GlobalReferenceCache.reset(self.test_db)
    
    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_complete_conversation_workflow(self):
        """Test complete conversation workflow with multiple messages"""
        wrapper = LLMWrapper(self.test_db)
        
        mock_response = '{"intent": "question", "confidence": 0.95}'

        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response

            result1 = asyncio.run(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )

            result2 = asyncio.run(
                wrapper.call_api("intent_classification", "How are you?", self.session_uuid)
            )

            self.assertTrue(result1.is_successful())
            self.assertTrue(result2.is_successful())

            self.assertEqual(result1.message_type_slug, "intent_classification")
            self.assertEqual(result2.message_type_slug, "intent_classification")
            self.assertEqual(
                result1.parsed_response,
                {"intent": "question", "confidence": 0.95},
            )
            self.assertEqual(
                json.loads(result1.raw_response),
                {"intent": "question", "confidence": 0.95},
            )
            self.assertEqual(
                json.loads(result2.raw_response),
                {"intent": "question", "confidence": 0.95},
            )

            messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(messages), 2)
            
            # Verify session management
            session_info = self.db.get_session_name(self.session_uuid)
            self.assertEqual(session_info, "Integration Test Session")
            
        wrapper.close()
    
    def test_error_recovery_workflow(self):
        """Test error recovery and retry logic"""
        wrapper = LLMWrapper(self.test_db)
        
        # Track API calls
        call_count = 0
        
        async def mock_api_call(prompt, model, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count <= 2:
                raise APITimeoutError(f"API timeout attempt {call_count}")
            elif call_count <= 4:
                raise APIConnectionError(f"Connection error attempt {call_count}")
            else:
                return '{"intent": "question", "confidence": 0.9}'
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call

            result = asyncio.run(
                wrapper.call_api("intent_classification", "Test message", self.session_uuid)
            )
            
            # Verify it eventually succeeded
            self.assertTrue(result.is_successful())
            self.assertEqual(result.num_tries, 5)  # 4 failures + 1 success
            self.assertEqual(
                result.parsed_response,
                {"intent": "question", "confidence": 0.9},
            )
            self.assertEqual(
                json.loads(result.raw_response),
                {"intent": "question", "confidence": 0.9},
            )
            
            # Verify success was recorded in database
            messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(messages), 1)
            saved_message = messages[0]
            self.assertIsNone(saved_message['error_text'])
            self.assertEqual(saved_message['num_tries'], 5)
            
        wrapper.close()
    
    def test_configuration_driven_behavior(self):
        """Test that database configuration drives system behavior"""
        wrapper = LLMWrapper(self.test_db)

        intent_type = wrapper.cache.get_message_type("intent_classification")

        self.assertIsNotNone(intent_type)
        self.assertEqual(intent_type['model_slug'], "meta-llama/llama-3.1-8b-instruct")
        self.assertEqual(intent_type['temperature'], 0.1)
        self.assertEqual(intent_type['max_retries'], 5)

        wrapper.close()
    
    def test_session_isolation(self):
        """Test that different sessions are properly isolated"""
        # Create second session
        session_uuid_2 = self.db.create_session("Second Session", "test")
        
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API response
        mock_response = '{"intent": "question", "confidence": 0.9}'
        
        async def mock_api_call(*args, **kwargs):
            return mock_response
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call

            result1 = asyncio.run(
                wrapper.call_api("intent_classification", "Message 1", self.session_uuid)
            )

            result2 = asyncio.run(
                wrapper.call_api("intent_classification", "Message 2", session_uuid_2)
            )
            
            # Verify both succeeded
            self.assertTrue(result1.is_successful())
            self.assertTrue(result2.is_successful())
            
            # Verify session isolation
            messages_1 = self.db.get_messages_by_session_and_type(self.session_uuid)
            messages_2 = self.db.get_messages_by_session_and_type(session_uuid_2)
            
            self.assertEqual(len(messages_1), 1)
            self.assertEqual(len(messages_2), 1)
            self.assertEqual(messages_1[0]['unique_prompt'], "Message 1")
            self.assertEqual(messages_2[0]['unique_prompt'], "Message 2")
            
        wrapper.close()
    
    def test_active_message_types_filtering(self):
        """Test that only active message types are returned"""
        self.db.cursor.execute("""
            INSERT INTO ref_message_types
            (slug, step_name, creator_type, request_schema, model_slug,
             temperature, additional_model_settings, max_retries, is_active, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            'inactive_type', 'Inactive Type', 'programmatic',
            '{"type":"object"}',
            'meta-llama/llama-3.1-8b-instruct',
            0.1, '{}', 3, 0, 'Inactive test type'
        ))
        self.db.conn.commit()

        active_types = self.db.get_active_message_types()

        self.assertEqual(len(active_types), 1)
        self.assertEqual(active_types[0]['slug'], 'intent_classification')

        deactivated_type = self.db.get_message_type('inactive_type')
        self.assertIsNone(deactivated_type)


if __name__ == '__main__':
    unittest.main()