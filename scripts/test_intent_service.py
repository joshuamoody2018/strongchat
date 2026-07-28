#!/usr/bin/env python3
"""Offline unit tests for IntentService.

Mocks LLMWrapper.call_api so no live API calls are made. The only
real dependency exercised is the cached ref_message_types schema from the
local SQLite database.
"""

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import INTENT_GENERATION_SCHEMA
from config.cache import GlobalReferenceCache
from services.intent import IntentService
from services.llm.aimessage import AIMessage


VALID_FIXTURE = {
    "query_analysis": {
        "original_query": "why do bad things happen",
        "core_questions": ["Why does suffering occur"],
        "context_clues": ["suffering", "pain"],
    },
    "intents": [
        {
            "intent_id": "theological",
            "interpretation": "Understanding the problem of evil",
            "keywords_explicit": ["bad", "things", "happen"],
            "keywords_inferred": ["suffering", "evil", "pain"],
            "themes": ["theodicy", "suffering"],
            "confidence": 0.9,
            "is_primary": True,
        },
        {
            "intent_id": "comfort",
            "interpretation": "Seeking comfort during difficult times",
            "keywords_explicit": ["bad", "things"],
            "keywords_inferred": ["comfort", "hope", "support"],
            "themes": ["comfort"],
            "confidence": 0.6,
            "is_primary": False,
        },
    ],
    "recommended_search_approach": "Prioritize the primary intent, then include supporting verses",
}


INVALID_FIXTURE = {
    "query_analysis": {
        "original_query": "why do bad things happen",
        "core_questions": ["Why does suffering occur"],
        "context_clues": ["suffering", "pain"],
    },
    "intents": [
        {
            "intent_id": "theological",
            "interpretation": "Understanding the problem of evil",
            "keywords_explicit": ["bad", "things", "happen"],
            "keywords_inferred": ["suffering", "evil", "pain"],
            # Missing required "themes" field
            "confidence": 0.9,
            "is_primary": True,
        },
    ],
    "recommended_search_approach": "Prioritize the primary intent, then include supporting verses",
}


class TestIntentService(unittest.TestCase):
    """Offline tests for IntentService.generate_intents."""

    def setUp(self):
        """Provide a dummy API key so LLMWrapper initializes offline."""
        os.environ['OPENROUTER_API_KEY'] = 'dummy_key_for_offline_tests'
        GlobalReferenceCache.reset('data/chat_database.db')
        self.service = IntentService()

    def _make_aimessage(self, raw_response: str) -> AIMessage:
        """Build an AIMessage with the given raw response."""
        return AIMessage(
            uuid='test-message-uuid',
            session_uuid='test-session-uuid',
            message_type_slug='intent_generation',
            unique_prompt='why do bad things happen',
            raw_response=raw_response,
        )

    def test_generate_intents_returns_structured_result(self):
        """A valid response is parsed and returned with the expected keys."""
        expected_call = ('intent_generation', 'why do bad things happen', 'test-session-uuid')
        aimessage = self._make_aimessage(json.dumps(VALID_FIXTURE))

        with patch.object(self.service.llm, 'call_api', new_callable=AsyncMock) as mock_call_api:
            mock_call_api.return_value = aimessage

            result = asyncio.run(self.service.generate_intents(expected_call[1], expected_call[2]))

        self.assertEqual(result['message_uuid'], 'test-message-uuid')
        self.assertEqual(result['query_analysis'], VALID_FIXTURE['query_analysis'])
        self.assertEqual(result['intents'], VALID_FIXTURE['intents'])
        self.assertEqual(
            result['recommended_search_approach'],
            VALID_FIXTURE['recommended_search_approach'],
        )
        mock_call_api.assert_awaited_once_with(*expected_call)

    def test_generate_intents_invalid_response_raises_value_error(self):
        """A response missing the required themes field raises ValueError."""
        expected_call = ('intent_generation', 'why do bad things happen', 'test-session-uuid')
        aimessage = self._make_aimessage(json.dumps(INVALID_FIXTURE))

        with patch.object(self.service.llm, 'call_api', new_callable=AsyncMock) as mock_call_api:
            mock_call_api.return_value = aimessage

            with self.assertRaises(ValueError):
                asyncio.run(self.service.generate_intents(expected_call[1], expected_call[2]))

        mock_call_api.assert_awaited_once_with(*expected_call)


def run_tests():
    """Run all tests."""
    print("Testing IntentService offline...")
    print("=" * 50)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestIntentService)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    print("=" * 50)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
