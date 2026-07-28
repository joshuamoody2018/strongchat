#!/usr/bin/env python3
"""Validation tests for the HyDE generation schema and prompt template."""
import json
import os
import sys
import unittest

import jsonschema

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
import config


SAMPLE_INTENT = json.dumps({
    "interpretation": "Find verses about grace and peace",
    "keywords": ["grace", "peace", "salvation"],
    "themes": ["salvation"],
})


class TestHydeGenerationSchema(unittest.TestCase):
    """Verify HYDE_GENERATION_SCHEMA and HYDE_GENERATION_PROMPT shape."""

    def test_valid_document_passes(self):
        """A hyde_document over 50 characters validates."""
        fixture = {
            "hyde_document": (
                "In the beginning was the Word, and the Word was with God, "
                "and the Word was God. He was with God in the beginning."
            ),
        }
        jsonschema.validate(fixture, config.HYDE_GENERATION_SCHEMA)

    def test_short_document_fails_min_length(self):
        """A hyde_document under 50 characters is rejected."""
        fixture = {"hyde_document": "x" * 20}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(fixture, config.HYDE_GENERATION_SCHEMA)

    def test_missing_document_fails(self):
        """A response missing hyde_document is rejected."""
        fixture = {}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(fixture, config.HYDE_GENERATION_SCHEMA)

    def test_prompt_formats_with_intent_json(self):
        """The prompt template accepts a JSON intent string containing braces."""
        formatted = config.HYDE_GENERATION_PROMPT.format(query=SAMPLE_INTENT)
        self.assertNotIn("{query}", formatted)
        self.assertIn("hyde_document", formatted)
        self.assertIn(SAMPLE_INTENT, formatted)


def run_tests():
    """Run all tests."""
    print("Testing HyDE generation schema and prompt...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestHydeGenerationSchema)
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
