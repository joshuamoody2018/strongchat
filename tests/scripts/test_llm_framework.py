#!/usr/bin/env python3
"""Test script for the generic LLM client framework"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.llm.client import LLMClient
from services.llm.exceptions import MaxRetriesExceededError, APIConnectionError
from services.llm.parser import BaseResponseModel


class MockResponseModel(BaseResponseModel):
    def __init__(self, query: str, answer: str):
        self.query = query
        self.answer = answer


TEST_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "answer": {"type": "string"}
    },
    "required": ["query", "answer"]
}

TEST_PROMPT = "Question: {query}\nAnswer:"
TEST_MODEL = "meta-llama/llama-3.1-8b-instruct"


class TestLLMFramework(unittest.TestCase):
    """Test suite for the generic LLM client framework"""

    def setUp(self):
        os.environ['OPENROUTER_API_KEY'] = 'test_api_key'

    def tearDown(self):
        if 'OPENROUTER_API_KEY' in os.environ:
            del os.environ['OPENROUTER_API_KEY']

    def test_client_initialization(self):
        """Test LLM client initialization"""
        client = LLMClient()
        self.assertEqual(client.max_retries, 3)
        self.assertEqual(client.initial_backoff, 1.0)
        self.assertEqual(client.max_backoff, 30.0)

    def test_error_no_api_key(self):
        """Test error when no API key is configured"""
        if 'OPENROUTER_API_KEY' in os.environ:
            del os.environ['OPENROUTER_API_KEY']

        with self.assertRaises(Exception):
            LLMClient()

    @patch('services.llm.client.aiohttp.ClientSession')
    def test_successful_api_call(self, mock_session_class):
        """Test successful API call with schema"""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            'choices': [{'message': {'content': '{"query": "test", "answer": "success"}'}}]
        })

        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post.return_value = post_cm
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session

        client = LLMClient()
        result = asyncio.run(
            client.call_with_schema(
                TEST_PROMPT,
                TEST_SCHEMA,
                MockResponseModel,
                TEST_MODEL,
                query="test"
            )
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.query, "test")
        self.assertEqual(result.answer, "success")

    @patch('services.llm.client.aiohttp.ClientSession')
    def test_max_retries_exceeded(self, mock_session_class):
        """Test max retries exceeded"""
        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(side_effect=APIConnectionError("Connection error"))
        post_cm.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post.return_value = post_cm
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_class.return_value = mock_session

        client = LLMClient()

        with self.assertRaises(MaxRetriesExceededError):
            asyncio.run(
                client.call_with_schema(
                    TEST_PROMPT,
                    TEST_SCHEMA,
                    MockResponseModel,
                    TEST_MODEL,
                    query="test"
                )
            )

    def test_json_extraction(self):
        """Test JSON extraction from various response formats"""
        from services.llm.parser import ResponseParser

        parser = ResponseParser(TEST_SCHEMA, MockResponseModel)

        plain_json = '{"query": "test", "answer": "value"}'
        result = parser._extract_json(plain_json)
        self.assertEqual(result, plain_json)

        markdown_json = "```json\n{\"query\": \"test\", \"answer\": \"value\"}\n```"
        result = parser._extract_json(markdown_json)
        self.assertEqual(result, "{\"query\": \"test\", \"answer\": \"value\"}")

        response_with_json = "Here's the response: {\"query\": \"test\", \"answer\": \"value\"} end"
        result = parser._extract_json(response_with_json)
        self.assertEqual(result, "{\"query\": \"test\", \"answer\": \"value\"}")


def run_tests():
    """Run all tests"""
    print("Testing LLM Framework...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestLLMFramework))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
