#!/usr/bin/env python3
"""Offline test for context retrieval within the full pipeline.

Tests that ContextRetrievalService properly attaches context_bundle to each
hit. Audit (the former context_retrieval DB row) now lives in the structured
log; this test asserts against returned bundle shape rather than DB rows.
No application DB; the runner uses the default in-process registry.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy_key_for_offline_tests"

from services.pipeline.runner import PipelineRunner


LONG_HYDE_DOC = (
    "A long enough hypothetical passage about comfort and anxiety. " * 6
)


def _deterministic_vector(text: str) -> list[float]:
    import hashlib
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(1536)]


class TestContextRetrievalOffline(unittest.TestCase):
    """Offline test for context retrieval within the full pipeline."""

    def setUp(self):
        """Create a runner instance using the default in-process registry."""
        self.runner = PipelineRunner()

    def tearDown(self):
        try:
            self.runner.close()
        finally:
            pass

    def test_full_pipeline_with_mocked_context_retrieval(self):
        """Mock services and verify context_bundle is attached to each hit."""
        intents = [{
            "intent_id": "comfort",
            "interpretation": "Seeking comfort for anxiety",
            "keywords_explicit": ["anxiety"],
            "keywords_inferred": ["peace", "worry"],
            "themes": ["comfort", "anxiety"],
        }]
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": LONG_HYDE_DOC, "message_uuid": "m1"}
        ]
        embedding = _deterministic_vector(LONG_HYDE_DOC)
        retrieval_results = [
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "kjv",
                "embedding": embedding,
                "hits": [
                    {
                        "id": "1",
                        "text": "For God so loved the world...",
                        "reference": "John 3:16",
                        "distance": 0.3,
                    }
                ],
            }
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "test query", "core_questions": ["test"]},
            "intents": intents,
        }

        context_service_calls = []

        async def fake_generate_intents(query, session_uuid):
            return intent_response

        async def fake_generate_for_intents(intents_in, session_uuid):
            self.assertEqual(intents_in, intents)
            return hyde_docs

        async def fake_search(hyde_docs_in, session_uuid, **kwargs):
            self.assertEqual(hyde_docs_in, hyde_docs)
            return retrieval_results

        async def fake_embed_texts(texts, **kwargs):
            self.assertEqual(texts, [LONG_HYDE_DOC])
            return [embedding]

        async def fake_retrieve_for_pipeline(pipeline_result, session_uuid):
            """Mock context retrieval that adds context_bundle to each hit."""
            context_service_calls.append((pipeline_result, session_uuid))
            for intent_id, trace in pipeline_result.traces.items():
                for translation, hits in trace.search_results.items():
                    for hit in hits:
                        hit["context_bundle"] = {
                            "hit_id": hit["id"],
                            "reference": hit["reference"],
                            "translation": translation,
                            "unique_word_count": 5,
                            "kept_word_count": 3,
                            "scored_words": [
                                {
                                    "surface": "loved",
                                    "lemma": "agapaō",
                                    "strongs": "25",
                                    "morph": "V-IAI-3S",
                                    "pos": "V-",
                                    "pos_weight": 0.95,
                                    "frequency_count": 100,
                                    "sense_count": 3,
                                    "composite_score": 0.95 * 2.39 * 1.39,
                                    "definitions": ["to love", "to be loved", "beloved"],
                                    "gloss": "loved",
                                    "lexicon_source": "tbESG+LSJ",
                                    "macula_occurrences": 143,
                                }
                            ],
                            "kept_words": [
                                {
                                    "surface": "loved",
                                    "lemma": "agapaō",
                                    "strongs": "25",
                                    "morph": "V-IAI-3S",
                                    "pos": "V-",
                                    "pos_weight": 0.95,
                                    "frequency_count": 100,
                                    "sense_count": 3,
                                    "composite_score": 0.95 * 2.39 * 1.39,
                                    "lexicon_source": "tbESG+LSJ",
                                    "definitions": ["to love", "to be loved", "beloved"],
                                    "gloss": "loved",
                                    "macula_occurrences": 143,
                                }
                            ],
                        }

        with patch.object(
            self.runner.intent_service, "generate_intents",
            new=AsyncMock(side_effect=fake_generate_intents),
        ), patch.object(
            self.runner.hyde_service, "generate_for_intents",
            new=AsyncMock(side_effect=fake_generate_for_intents),
        ), patch.object(
            self.runner.retrieval_service, "search",
            new=AsyncMock(side_effect=fake_search),
        ), patch.object(
            self.runner.embedding_service, "embed_texts",
            new=AsyncMock(side_effect=fake_embed_texts),
        ), patch.object(
            self.runner.context_service, "retrieve_for_pipeline",
            new=AsyncMock(side_effect=fake_retrieve_for_pipeline),
        ):
            result = asyncio.run(
                self.runner.run(
                    query="test query",
                    top_k=3,
                    translations=("kjv",),
                )
            )

        self.assertEqual(len(context_service_calls), 1)
        pipeline_result, called_session_uuid = context_service_calls[0]
        self.assertIsInstance(called_session_uuid, str)

        for intent_id, trace in result.traces.items():
            for translation, hits in trace.search_results.items():
                for hit in hits:
                    self.assertIn("context_bundle", hit)
                    bundle = hit["context_bundle"]
                    self.assertIn("hit_id", bundle)
                    self.assertIn("reference", bundle)
                    self.assertIn("translation", bundle)
                    self.assertIn("unique_word_count", bundle)
                    self.assertIn("kept_word_count", bundle)
                    self.assertIn("scored_words", bundle)
                    self.assertIn("kept_words", bundle)

                    self.assertGreater(len(bundle["kept_words"]), 0)
                    for w in bundle["kept_words"]:
                        self.assertIsInstance(w["strongs"], str)
                        self.assertTrue(w["strongs"])
                        self.assertIsInstance(w["surface"], str)
                        self.assertTrue(w["surface"])
                        self.assertIsInstance(w["lemma"], str)
                        self.assertTrue(w["lemma"])
                        self.assertIsInstance(w["definitions"], list)
                        self.assertTrue(w["definitions"])
                        self.assertIsInstance(w["gloss"], str)
                        self.assertTrue(w["gloss"])
                        self.assertEqual(w["lexicon_source"], "tbESG+LSJ")
                        self.assertIsInstance(w["frequency_count"], int)
                        self.assertGreater(w["frequency_count"], 0)
                        self.assertIsInstance(w["sense_count"], int)
                        self.assertEqual(w["sense_count"], len(w["definitions"]))
                        self.assertIsInstance(w["composite_score"], (int, float))
                        self.assertGreater(w["composite_score"], 0)
                        self.assertIsInstance(w["macula_occurrences"], int)
                        self.assertGreaterEqual(w["macula_occurrences"], 1)


def run_tests():
    """Run the context retrieval offline test and report results."""
    print("Running context retrieval offline test...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestContextRetrievalOffline))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
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

    print("=" * 60)
    success = result.wasSuccessful()
    print(f"Result: {'PASS' if success else 'FAIL'}")
    return success


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)