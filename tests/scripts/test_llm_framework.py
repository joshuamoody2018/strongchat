#!/usr/bin/env python3
"""Test script for the new LLM client framework"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.llm.client import LLMClient
from services.llm.exceptions import MaxRetriesExceededError
from config.schemas import INTENT_DISAMBIGUATION_SCHEMA
from config.prompts import INTENT_DISAMBIGUATION_PROMPT


class TestLLMFramework(unittest.TestCase):
    """Test suite for the new LLM framework"""
    
    def setUp(self):
        """Set up test environment"""
        # Mock API key for testing
        os.environ['OPENROUTER_API_KEY'] = 'test_api_key'
        
    def tearDown(self):
        """Clean up test environment"""
        if 'OPENROUTER_API_KEY' in os.environ:
            del os.environ['OPENROUTER_API_KEY']
    
    def test_client_initialization(self):
        """Test LLM client initialization"""
        client = LLMClient()
        self.assertEqual(client.max_retries, 3)
        self.assertEqual(client.initial_backoff, 1.0)
        self.assertEqual(client.max_backoff, 30.0)
        self.assertIn('intent_disambiguation', client.parsers)
    
    def test_error_no_api_key(self):
        """Test error when no API key is configured"""
        if 'OPENROUTER_API_KEY' in os.environ:
            del os.environ['OPENROUTER_API_KEY']
        
        with self.assertRaises(Exception):
            LLMClient()
    
    @patch('services.llm.client.aiohttp.ClientSession')
    async def test_successful_api_call(self, mock_session_class):
        """Test successful API call"""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            'choices': [{'message': {'content': '{"test": "success"}'}}]
        }
        mock_session.__aenter__.return_value.__aenter__.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        client = LLMClient()
        result = await client.disambiguate_intent("test query")
        
        self.assertIsNotNone(result)
    
    @patch('services.llm.client.aiohttp.ClientSession')
    async def test_max_retries_exceeded(self, mock_session_class):
        """Test max retries exceeded"""
        # Mock session that always fails
        mock_session = MagicMock()
        mock_session.__aenter__.return_value.__aenter__.return_value = None
        mock_session_class.side_effect = Exception("Connection error")
        
        client = LLMClient()
        
        with self.assertRaises(MaxRetriesExceededError):
            await client.disambiguate_intent("test query")
    
    def test_json_extraction(self):
        """Test JSON extraction from various response formats"""
        from services.llm.parser import ResponseParser
        
        parser = ResponseParser(INTENT_DISAMBIGUATION_SCHEMA, type('MockResponse', (), {}))
        
        # Test plain JSON
        plain_json = '{"test": "value"}'
        result = parser._extract_json(plain_json)
        self.assertEqual(result, plain_json)
        
        # Test markdown JSON
        markdown_json = "```json\n{\"test\": \"value\"}\n```"
        result = parser._extract_json(markdown_json)
        self.assertEqual(result, "{\"test\": \"value\"}")
        
        # Test JSON in response text
        response_with_json = "Here's the response: {\"test\": \"value\"} end"
        result = parser._extract_json(response_with_json)
        self.assertEqual(result, "{\"test\": \"value\"}")


def run_tests():
    """Run all tests"""
    print("Testing LLM Framework...")
    print("=" * 50)
    
    # Create test suite
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestLLMFramework))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)