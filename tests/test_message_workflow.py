#!/usr/bin/env python3
"""Message workflow tests for LLM message system"""

import os
import sys
import tempfile
import unittest
import asyncio
import json
from unittest.mock import patch, AsyncMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.database import ChatDatabase
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage

# Import the database creation script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import create_new_database


class TestMessageWorkflow(unittest.TestCase):
    """Test complete message workflow"""
    
    def setUp(self):
        """Set up test database and mock data"""
        self.test_db = tempfile.mktemp(suffix='.db')
        
        # Create the database schema
        create_new_database.create_new_database(self.test_db)
        
        self.db = ChatDatabase(self.test_db)
        
        # Create test session
        self.session_uuid = self.db.create_session("Test Session", "test")
        
        # Get the message type that was created
        self.mock_message_type = self.db.get_message_type("intent_classification")
        
        # The message_type is already created by create_new_database
    
    def tearDown(self):
        """Clean up test database"""
        self.db.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
    
    def test_successful_message_workflow(self):
        """Test complete successful message workflow"""
        # Create LLM wrapper
        wrapper = LLMWrapper(self.test_db)
        
        # Mock successful API response
        mock_response = '{"intent": "question", "confidence": 0.95}'
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response
            
            # Call API
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )
            
            # Verify result
            self.assertIsInstance(result, AIMessage)
            self.assertTrue(result.is_successful())
            self.assertEqual(result.raw_response, mock_response)
            self.assertEqual(result.num_tries, 1)
            
            # Verify message was saved to database
            saved_message = self.db.get_message_by_uuid(result.uuid)
            self.assertIsNotNone(saved_message)
            self.assertEqual(saved_message['unique_prompt'], "What is love?")
            self.assertEqual(saved_message['raw_response'], mock_response)
            self.assertEqual(saved_message['num_tries'], 1)
            self.assertIsNone(saved_message['error_text'])
            
        wrapper.close()
    
    def test_retry_logic_workflow(self):
        """Test message workflow with retry logic"""
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API that fails twice then succeeds
        mock_responses = [
            Exception("API timeout"),  # First attempt fails
            Exception("Connection error"),  # Second attempt fails
            '{"intent": "question", "confidence": 0.95}'  # Third attempt succeeds
        ]
        
        call_count = 0
        
        async def mock_api_call(*args, **kwargs):
            nonlocal call_count
            if call_count < len(mock_responses):
                response = mock_responses[call_count]
                call_count += 1
                if isinstance(response, Exception):
                    raise response
                return response
            raise Exception("Unexpected API call")
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call
            
            # Call API
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )
            
            # Verify result
            self.assertIsInstance(result, AIMessage)
            self.assertTrue(result.is_successful())
            self.assertEqual(result.raw_response, '{"intent": "question", "confidence": 0.95}')
            self.assertEqual(result.num_tries, 3)  # Should have retried twice
            
            # Verify message was saved with correct retry count
            saved_message = self.db.get_message_by_uuid(result.uuid)
            self.assertEqual(saved_message['num_tries'], 3)
            
        wrapper.close()
    
    def test_max_retries_exceeded_workflow(self):
        """Test message workflow when max retries are exceeded"""
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API that always fails
        async def mock_api_call(*args, **kwargs):
            raise Exception("Persistent API error")
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = mock_api_call
            
            # Call API - should raise MaxRetriesExceededError
            loop = asyncio.get_event_loop()
            with self.assertRaises(Exception):  # MaxRetriesExceededError
                loop.run_until_complete(
                    wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
                )
            
            # Verify error message was saved
            saved_messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(saved_messages), 1)
            saved_message = saved_messages[0]
            self.assertIsNotNone(saved_message['error_text'])
            self.assertEqual(saved_message['num_tries'], 3)  # Max retries (1 initial + 2 retries)
            self.assertIsNone(saved_message['raw_response'])
            
        wrapper.close()
    
    def test_response_parsing_workflow(self):
        """Test response parsing with schema validation"""
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API response
        mock_response = '{"intent": "question", "confidence": 0.95}'
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response
            
            # Call API
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )
            
            # Parse response using schema
            schema = json.loads(self.mock_message_type["request_schema"])
            parsed_data = result.get_parsed_response(schema)
            
            # Verify parsing
            self.assertEqual(parsed_data["intent"], "question")
            self.assertEqual(parsed_data["confidence"], 0.95)
            
        wrapper.close()
    
    def test_invalid_response_handling(self):
        """Test handling of invalid API responses"""
        wrapper = LLMWrapper(self.test_db)
        
        # Mock invalid API response
        mock_response = "This is not valid JSON at all"
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response
            
            # Call API - should handle gracefully
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )
            
            # Verify error handling
            self.assertFalse(result.is_successful())
            self.assertIsNotNone(result.error_text)
            self.assertIn("JSON decode error", result.error_text)
            
        wrapper.close()
    
    def test_message_type_not_found(self):
        """Test handling of missing message type"""
        wrapper = LLMWrapper(self.test_db)
        
        # Try to call with non-existent message type
        loop = asyncio.get_event_loop()
        with self.assertRaises(ValueError):
            loop.run_until_complete(
                wrapper.call_api("nonexistent_type", "What is love?", self.session_uuid)
            )
        
        wrapper.close()
    
    def test_multiple_message_types_workflow(self):
        """Test workflow with multiple message types"""
        # Insert another message type
        second_message_type = {
            "slug": "intent_disambiguation",
            "step_name": "Intent Disambiguation",
            "creator_type": "programmatic",
            "request_schema": '{"type": "object", "properties": {"recommended_framing": {"type": "string"}}, "required": ["recommended_framing"]}',
            "model_slug": "openai/gpt-3.5-turbo",
            "temperature": 0.2,
            "additional_model_settings": '{"max_tokens": 500}',
            "max_retries": 3,
            "is_active": True,
            "description": "Test intent disambiguation"
        }
        
        self.db.cursor.execute('''
            INSERT INTO message_types 
            (slug, step_name, creator_type, request_schema, model_slug, temperature, 
             additional_model_settings, max_retries, is_active, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            second_message_type["slug"],
            second_message_type["step_name"],
            second_message_type["creator_type"],
            second_message_type["request_schema"],
            second_message_type["model_slug"],
            second_message_type["temperature"],
            second_message_type["additional_model_settings"],
            second_message_type["max_retries"],
            second_message_type["is_active"],
            second_message_type["description"]
        ))
        self.db.conn.commit()
        
        wrapper = LLMWrapper(self.test_db)
        
        # Mock API response for disambiguation
        mock_response = '{"recommended_framing": "framing_1"}'
        
        with patch.object(wrapper, '_call_api_async', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = mock_response
            
            # Call API with different message types
            loop = asyncio.get_event_loop()
            
            # First call with intent_classification
            result1 = loop.run_until_complete(
                wrapper.call_api("intent_classification", "What is love?", self.session_uuid)
            )
            
            # Second call with intent_disambiguation
            result2 = loop.run_until_complete(
                wrapper.call_api("intent_disambiguation", "What is love?", self.session_uuid)
            )
            
            # Verify both calls succeeded
            self.assertTrue(result1.is_successful())
            self.assertTrue(result2.is_successful())
            
            # Verify different message types were used
            self.assertEqual(result1.message_type_slug, "intent_classification")
            self.assertEqual(result2.message_type_slug, "intent_disambiguation")
            
            # Verify both messages were saved
            messages = self.db.get_messages_by_session_and_type(self.session_uuid)
            self.assertEqual(len(messages), 2)
            
        wrapper.close()


if __name__ == '__main__':
    unittest.main()