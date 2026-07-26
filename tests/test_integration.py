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
        
        # Insert mock message types
        self.message_types = [
            {
                "slug": "intent_classification",
                "step_name": "Intent Classification",
                "creator_type": "programmatic",
                "request_schema": '{"type": "object", "properties": {"intent": {"type": "string"}, "confidence": {"type": "number"}}, "required": ["intent", "confidence"]}',
                "model_slug": "openai/gpt-3.5-turbo",
                "temperature": 0.1,
                "additional_model_settings": '{"max_tokens": 100}',
                "max_retries": 3,
                "is_active": True,
                "description": "Classify user message intent"
            },
            {
                "slug": "intent_disambiguation",
                "step_name": "Intent Disambiguation",
                "creator_type": "programmatic",
                "request_schema": '{"type": "object", "properties": {"recommended_framing": {"type": "string"}}, "required": ["recommended_framing"]}',
                "model_slug": "openai/gpt-4",
                "temperature": 0.2,
                "additional_model_settings": '{"max_tokens": 500}',
                "max_retries": 2,
                "is_active": True,
                "description": "Disambiguate user queries"
            }
        ]
        
        # Insert message types
        for msg_type in self.message_types:
            self.db.cursor.execute('''
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
        self.db.conn.commit()
    
    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_complete_conversation_workflow(self):
        """Test complete conversation workflow with multiple messages"""
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API responses for different message types
        mock_responses = {
            "intent_classification": '{"intent": "question", "confidence": 0.95}',
            "intent_disambiguation": '{"recommended_framing": "biblical_context"}'
        }
        
        async def mock_api_call(prompt, model, **kwargs):
            # Determine message type from prompt (simplified)
            if "What is love" in prompt:
                return mock_responses["intent_classification"]
            elif "ambiguous" in prompt:
                return mock_responses["intent_disambiguation"]
            else:
                return '{"intent": "question", "confidence": 0.9}'
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call
            
            loop = asyncio.get_event_loop()
            
            # First message: What is love?
            result1 = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )
            
            # Second message: Ambiguous query
            result2 = loop.run_until_complete(
                wrapper.call_api("intent_disambiguation", "What is love ambiguous biblical?", self.session_uuid)
            )
            
            # Third message: Simple question
            result3 = loop.run_until_complete(
                wrapper.call_api("intent_classification", "How are you?", self.session_uuid)
            )
            
            # Verify all results
            self.assertTrue(all([r.is_successful() for r in [result1, result2, result3]]))
            
            # Verify different message types
            self.assertEqual(result1.message_type_slug, "intent_classification")
            self.assertEqual(result2.message_type_slug, "intent_disambiguation")
            self.assertEqual(result3.message_type_slug, "intent_classification")
            
            # Verify different models were used (based on configuration)
            self.assertEqual(result1.raw_response, '{"intent": "question", "confidence": 0.95}')
            self.assertEqual(result2.raw_response, '{"recommended_framing": "biblical_context"}')
            
            # Verify all messages were saved
            messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(messages), 3)
            
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
        
        # Verify different message types have different configurations
        intent_type = wrapper.get_message_type_config("intent_classification")
        disambiguation_type = wrapper.get_message_type_config("intent_disambiguation")
        
        self.assertIsNotNone(intent_type)
        self.assertIsNotNone(disambiguation_type)
        
        # Verify different configurations
        self.assertEqual(intent_type['model_slug'], "openai/gpt-3.5-turbo")
        self.assertEqual(disambiguation_type['model_slug'], "openai/gpt-4")
        
        self.assertEqual(intent_type['temperature'], 0.1)
        self.assertEqual(disambiguation_type['temperature'], 0.2)
        
        self.assertEqual(intent_type['max_retries'], 3)
        self.assertEqual(disambiguation_type['max_retries'], 2)
        
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
        # Deactivate one message type
        self.db.cursor.execute("UPDATE message_types SET is_active = 0 WHERE slug = 'intent_disambiguation'")
        self.db.conn.commit()
        
        # Test that only active types are returned
        active_types = self.db.get_active_message_types()
        
        # Should only have intent_classification active
        self.assertEqual(len(active_types), 1)
        self.assertEqual(active_types[0]['slug'], 'intent_classification')
        
        # Test that deactivated type is not returned
        deactivated_type = self.db.get_message_type('intent_disambiguation')
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