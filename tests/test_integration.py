#!/usr/bin/env python3
"""Integration tests for complete LLM message system"""

import os
import sys
import tempfile
import unittest
import asyncio
from unittest.mock import patch, AsyncMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.database import ChatDatabase
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage


class TestIntegration(unittest.TestCase):
    """Integration tests for complete LLM message system"""
    
    def setUp(self):
        """Set up test database and mock data"""
        self.test_db = tempfile.mktemp(suffix='.db')
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
            "max_retries": 3,
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

            loop = asyncio.get_event_loop()

            result1 = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )

            result2 = loop.run_until_complete(
                wrapper.call_api("intent_classification", "How are you?", self.session_uuid)
            )

            self.assertTrue(result1.is_successful())
            self.assertTrue(result2.is_successful())

            self.assertEqual(result1.message_type_slug, "intent_classification")
            self.assertEqual(result2.message_type_slug, "intent_classification")
            self.assertEqual(result1.raw_response, mock_response)
            self.assertEqual(result2.raw_response, mock_response)

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
            
            # Simulate different error scenarios
            if call_count <= 2:
                raise Exception(f"API timeout attempt {call_count}")
            elif call_count <= 4:
                raise Exception(f"Connection error attempt {call_count}")
            else:
                return '{"intent": "question", "confidence": 0.9}'
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call
            
            loop = asyncio.get_event_loop()
            
            # This should succeed after retries
            result = loop.run_until_complete(
                wrapper.call_api("intent_classification", "Test message", self.session_uuid)
            )
            
            # Verify it eventually succeeded
            self.assertTrue(result.is_successful())
            self.assertEqual(result.num_tries, 5)  # 4 failures + 1 success
            self.assertEqual(result.raw_response, '{"intent": "question", "confidence": 0.9}')
            
            # Verify error was recorded in database
            messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(messages), 1)
            saved_message = messages[0]
            self.assertIsNotNone(saved_message['error_text'])
            self.assertEqual(saved_message['num_tries'], 5)
            
        wrapper.close()
    
    def test_configuration_driven_behavior(self):
        """Test that database configuration drives system behavior"""
        wrapper = LLMWrapper(self.test_db)

        intent_type = wrapper.cache.get_message_type("intent_classification")

        self.assertIsNotNone(intent_type)
        self.assertEqual(intent_type['model_slug'], "meta-llama/llama-3.1-8b-instruct")
        self.assertEqual(intent_type['temperature'], 0.1)
        self.assertEqual(intent_type['max_retries'], 3)

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
            
            loop = asyncio.get_event_loop()
            
            # Add message to first session
            result1 = loop.run_until_complete(
                wrapper.call_api("intent_classification", "Message 1", self.session_uuid)
            )
            
            # Add message to second session
            result2 = loop.run_until_complete(
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
    
    def test_schema_validation_error_handling(self):
        """Test handling of schema validation errors"""
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API response that doesn't match schema
        mock_response = '{"invalid": "response", "missing_required": "fields"}'
        
        async def mock_api_call(*args, **kwargs):
            return mock_response
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call
            
            loop = asyncio.get_event_loop()
            
            # This should fail due to schema validation
            result = loop.run_until_complete(
                wrapper.call_api("intent_classification", "Test message", self.session_uuid)
            )
            
            # Verify it failed
            self.assertFalse(result.is_successful())
            self.assertIsNotNone(result.error_text)
            self.assertIn("Schema validation error", result.error_text)
            
            # Verify error was saved
            messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(messages), 1)
            self.assertIsNotNone(messages[0]['error_text'])
            
        wrapper.close()


if __name__ == '__main__':
    unittest.main()