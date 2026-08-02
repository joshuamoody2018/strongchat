#!/usr/bin/env python3
"""Tests for the refined intent generation schema and prompt template.

Validates INTENT_GENERATION_SCHEMA with jsonschema and checks that
INTENT_GENERATION_PROMPT formats safely via .format(query=...).
"""
import json
import os
import sys
import unittest

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from jsonschema import validate, ValidationError
from config import INTENT_GENERATION_SCHEMA, INTENT_GENERATION_PROMPT


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
}


def _with_intents(count: int) -> dict:
    """Return a valid fixture with ``count`` identical intents."""
    fixture = json.loads(json.dumps(VALID_FIXTURE))
    base_intent = fixture["intents"][0]
    fixture["intents"] = [
        {**base_intent, "intent_id": f"intent_{i}", "is_primary": i == 0}
        for i in range(count)
    ]
    return fixture


class TestIntentGenerationSchema(unittest.TestCase):
    """Validate the refined intent generation schema."""

    def test_valid_fixture_passes(self):
        """The valid fixture must validate against the schema."""
        validate(instance=VALID_FIXTURE, schema=INTENT_GENERATION_SCHEMA)

    def test_missing_themes_fails(self):
        """An intent missing the required themes array must fail."""
        fixture = json.loads(json.dumps(VALID_FIXTURE))
        del fixture["intents"][0]["themes"]
        with self.assertRaises(ValidationError):
            validate(instance=fixture, schema=INTENT_GENERATION_SCHEMA)

    def test_missing_keywords_inferred_fails(self):
        """An intent missing the required keywords_inferred array must fail."""
        fixture = json.loads(json.dumps(VALID_FIXTURE))
        del fixture["intents"][0]["keywords_inferred"]
        with self.assertRaises(ValidationError):
            validate(instance=fixture, schema=INTENT_GENERATION_SCHEMA)

    def test_zero_intents_fails(self):
        """An empty intents array must fail the minItems constraint."""
        fixture = json.loads(json.dumps(VALID_FIXTURE))
        fixture["intents"] = []
        with self.assertRaises(ValidationError):
            validate(instance=fixture, schema=INTENT_GENERATION_SCHEMA)

    def test_six_intents_fails(self):
        """Six intents must fail the maxItems constraint."""
        fixture = _with_intents(6)
        with self.assertRaises(ValidationError):
            validate(instance=fixture, schema=INTENT_GENERATION_SCHEMA)

    def test_confidence_out_of_range_fails(self):
        """A confidence value above 1.0 must fail."""
        fixture = json.loads(json.dumps(VALID_FIXTURE))
        fixture["intents"][0]["confidence"] = 1.5
        with self.assertRaises(ValidationError):
            validate(instance=fixture, schema=INTENT_GENERATION_SCHEMA)


class TestIntentGenerationPrompt(unittest.TestCase):
    """Validate the prompt template formatting."""

    def test_prompt_formats_without_exception(self):
        """The prompt must format with .format(query=...) and include the query."""
        formatted = INTENT_GENERATION_PROMPT.format(query='test query')
        self.assertIn('test query', formatted)
        self.assertIn('query_analysis', formatted)
        self.assertIn('keywords_explicit', formatted)
        self.assertIn('keywords_inferred', formatted)


def run_tests():
    """Run all tests."""
    print("Testing refined intent generation schema and prompt...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestIntentGenerationSchema)
    )
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestIntentGenerationPrompt)
    )

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
