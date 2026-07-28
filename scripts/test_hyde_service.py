#!/usr/bin/env python3
"""Offline unit tests for HydeService.

Mocks LLMWrapper.call_api so no live API calls are made. The only real
dependency exercised is the cached ref_message_types schema from the local
SQLite database.
"""

import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config.cache import GlobalReferenceCache
from services.hyde import HydeService
from services.llm.aimessage import AIMessage
from services.llm.exceptions import LLMError


INTENT_ONE = {
    "intent_id": "comfort",
    "interpretation": "Seeking comfort for anxiety",
    "keywords_explicit": ["anxiety"],
    "keywords_inferred": ["peace", "worry"],
    "themes": ["comfort", "anxiety"],
}

INTENT_TWO = {
    "intent_id": "trust",
    "interpretation": "Trusting God despite worry",
    "keywords_explicit": ["trust"],
    "keywords_inferred": ["faith", "future"],
    "themes": ["trust"],
}

LONG_DOC = (
    "A long enough hypothetical passage about comfort and anxiety " * 6
)


def _expected_prompt(intent: dict) -> str:
    """Return the JSON prompt HydeService builds from an intent."""
    return json.dumps(
        {
            "intent_id": intent["intent_id"],
            "interpretation": intent["interpretation"],
            "keywords_explicit": intent["keywords_explicit"],
            "keywords_inferred": intent["keywords_inferred"],
            "themes": intent["themes"],
        }
    )


def _make_aimessage(doc: str) -> AIMessage:
    """Build an AIMessage with the given HyDE document."""
    return AIMessage(
        uuid='test-hyde-uuid',
        session_uuid='test-session-uuid',
        message_type_slug='hyde_generation',
        unique_prompt=json.dumps(INTENT_ONE),
        raw_response=json.dumps({"hyde_document": doc}),
    )


class TestHydeService(unittest.TestCase):
    """Offline tests for HydeService.generate_for_intents."""

    def setUp(self):
        """Provide a dummy API key so LLMWrapper initializes offline."""
        os.environ['OPENROUTER_API_KEY'] = 'dummy_key_for_offline_tests'
        GlobalReferenceCache.reset('data/chat_database.db')
        self.service = HydeService()

    def test_partial_failure_returns_one_doc_and_one_error(self):
        """One successful intent and one failure yield a mixed result list."""
        async def call_api_mock(slug, prompt, session):
            if 'comfort' in prompt:
                return _make_aimessage(LONG_DOC)
            raise ValueError("simulated hyde failure")

        self.service.llm.call_api = AsyncMock(side_effect=call_api_mock)

        result = asyncio.run(
            self.service.generate_for_intents(
                [INTENT_ONE, INTENT_TWO], 'test-session-uuid'
            )
        )

        self.assertEqual(len(result), 2)
        doc_results = [r for r in result if r.get('hyde_document') is not None]
        error_results = [r for r in result if r.get('hyde_document') is None]
        self.assertEqual(len(doc_results), 1)
        self.assertEqual(len(error_results), 1)

        success = doc_results[0]
        self.assertEqual(success['intent_id'], 'comfort')
        self.assertEqual(success['message_uuid'], 'test-hyde-uuid')
        self.assertIn('hyde_document', success)

        failure = error_results[0]
        self.assertEqual(failure['intent_id'], 'trust')
        self.assertIn('error', failure)

        self.service.llm.call_api.assert_any_await(
            'hyde_generation', _expected_prompt(INTENT_ONE), 'test-session-uuid'
        )
        self.service.llm.call_api.assert_any_await(
            'hyde_generation', _expected_prompt(INTENT_TWO), 'test-session-uuid'
        )

    def test_all_fail_raises_llm_error_with_error_entries(self):
        """If every intent fails, LLMError is raised and carries error entries."""
        async def call_api_mock(slug, prompt, session):
            raise ValueError("simulated hyde failure")

        self.service.llm.call_api = AsyncMock(side_effect=call_api_mock)

        with self.assertRaises(LLMError) as ctx:
            asyncio.run(
                self.service.generate_for_intents(
                    [INTENT_ONE, INTENT_TWO], 'test-session-uuid'
                )
            )

        self.assertTrue(hasattr(ctx.exception, 'results'))
        self.assertEqual(len(ctx.exception.results), 2)
        self.assertTrue(
            all(r.get('hyde_document') is None for r in ctx.exception.results)
        )
        self.assertTrue(all('error' in r for r in ctx.exception.results))


def run_tests():
    """Run all tests."""
    print("Testing HydeService offline...")
    print("=" * 50)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestHydeService)
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
