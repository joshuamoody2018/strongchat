#!/usr/bin/env python3
"""Regression tests for PipelineResult nested trace structure.

These tests guard against regressions in the per-intent traceability
refactor. They assert:

  * ``IntentTrace`` dataclass exists with the expected fields.
  * ``PipelineResult.traces`` is a ``Dict[str, IntentTrace]`` keyed by
    ``intent_id`` (O(1) predecessor lookup).
  * Embeddings are preserved on each trace.
  * Failed HyDE generations are captured on the trace (``hyde_error``) and
    the intent still appears in ``traces`` (no silent disappearance).
  * Backward-compatibility list views still match the pre-refactor flat shape.
  * ``query_analysis`` from ``IntentService`` is surfaced on
    ``PipelineResult``.

All tests run offline (no OpenRouter API calls) by mocking the
service-layer entry points on ``PipelineRunner``. No application DB; the
runner is constructed against the default in-process registry.
"""

import asyncio
import hashlib
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from services.pipeline.runner import IntentTrace, PipelineResult, PipelineRunner


DIMENSION = 1536


def _deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


def _make_intent(intent_id: str, is_primary: bool = False) -> dict:
    """Build a valid intent dict with the given id."""
    return {
        "intent_id": intent_id,
        "interpretation": f"Interpretation for {intent_id}",
        "keywords_explicit": ["keyword_a"],
        "keywords_inferred": ["keyword_b"],
        "themes": ["theme_x"],
        "confidence": 0.9,
        "is_primary": is_primary,
    }


def _make_hit(reference: str, distance: float, translation: str = "kjv") -> dict:
    """Build a verse hit dict in the format RetrievalService emits."""
    return {
        "id": f"{translation}-{reference.replace(' ', '-').replace(':', '-')}",
        "text": f"Text for {reference}",
        "reference": reference,
        "distance": distance,
    }


class TestIntentTraceDataclass(unittest.TestCase):
    """Pure dataclass-shape tests for IntentTrace."""

    def test_intent_trace_default_construction(self):
        trace = IntentTrace(
            intent_id="comfort",
            intent_data={"intent_id": "comfort"},
        )
        self.assertEqual(trace.intent_id, "comfort")
        self.assertEqual(trace.intent_data, {"intent_id": "comfort"})
        self.assertIsNone(trace.hyde_document)
        self.assertIsNone(trace.hyde_error)
        self.assertIsNone(trace.embedding)
        self.assertEqual(trace.search_results, {})

    def test_intent_trace_full_construction(self):
        embedding = _deterministic_vector("text")
        hits = [_make_hit("John 3:16", 0.1)]
        trace = IntentTrace(
            intent_id="comfort",
            intent_data={"intent_id": "comfort", "is_primary": True},
            hyde_document="A hypothetical passage about comfort.",
            hyde_error=None,
            embedding=embedding,
            search_results={"kjv": hits, "web": []},
        )
        self.assertEqual(trace.hyde_document, "A hypothetical passage about comfort.")
        self.assertIsNone(trace.hyde_error)
        self.assertEqual(trace.embedding, embedding)
        self.assertEqual(len(trace.search_results["kjv"]), 1)
        self.assertEqual(trace.search_results["kjv"][0]["reference"], "John 3:16")
        self.assertEqual(trace.search_results["web"], [])

    def test_intent_trace_with_hyde_error(self):
        trace = IntentTrace(
            intent_id="trust",
            intent_data={"intent_id": "trust"},
            hyde_document=None,
            hyde_error="LLM timeout",
        )
        self.assertIsNone(trace.hyde_document)
        self.assertEqual(trace.hyde_error, "LLM timeout")
        self.assertEqual(trace.search_results, {})


class TestPipelineResultShape(unittest.TestCase):
    """Pure shape tests for PipelineResult's traces dict."""

    def test_traces_is_dict_keyed_by_intent_id(self):
        traces = {
            "comfort": IntentTrace(intent_id="comfort", intent_data={}),
            "trust": IntentTrace(intent_id="trust", intent_data={}),
        }
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces=traces,
        )
        self.assertIsInstance(result.traces, dict)
        self.assertEqual(set(result.traces.keys()), {"comfort", "trust"})

    def test_o1_predecessor_lookup_for_hit(self):
        trace = IntentTrace(
            intent_id="comfort",
            intent_data={"intent_id": "comfort", "interpretation": "x"},
            hyde_document="hyde text",
            embedding=[0.1, 0.2, 0.3],
            search_results={"kjv": [_make_hit("John 3:16", 0.0)]},
        )
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces={"comfort": trace},
        )
        t = result.traces["comfort"]
        self.assertEqual(t.intent_data["interpretation"], "x")
        self.assertEqual(t.hyde_document, "hyde text")
        self.assertEqual(t.embedding, [0.1, 0.2, 0.3])
        self.assertEqual(t.search_results["kjv"][0]["reference"], "John 3:16")

    def test_query_analysis_surfaced(self):
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces={},
            query_analysis={"original_query": "why"},
        )
        self.assertEqual(result.query_analysis["original_query"], "why")


class TestBackwardCompatProperties(unittest.TestCase):
    """Compat: old call sites still read .intents/.hyde_docs/.results."""

    def test_intents_property_returns_list_of_intent_dicts(self):
        trace_a = IntentTrace(
            intent_id="a",
            intent_data={"intent_id": "a", "interpretation": "first"},
        )
        trace_b = IntentTrace(
            intent_id="b",
            intent_data={"intent_id": "b", "interpretation": "second"},
        )
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces={"a": trace_a, "b": trace_b},
        )
        intents = result.intents
        self.assertIsInstance(intents, list)
        self.assertEqual(len(intents), 2)
        self.assertEqual({i["intent_id"] for i in intents}, {"a", "b"})

    def test_hyde_docs_property_returns_flat_shape(self):
        trace_a = IntentTrace(
            intent_id="a",
            intent_data={"intent_id": "a"},
            hyde_document="hyde a",
        )
        trace_b = IntentTrace(
            intent_id="b",
            intent_data={"intent_id": "b"},
            hyde_document=None,
            hyde_error="oops",
        )
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces={"a": trace_a, "b": trace_b},
        )
        hyde_docs = result.hyde_docs
        self.assertEqual(len(hyde_docs), 2)
        for entry in hyde_docs:
            self.assertIn("intent_id", entry)
            self.assertIn("hyde_document", entry)
        docs_by_id = {d["intent_id"]: d for d in hyde_docs}
        self.assertEqual(docs_by_id["a"]["hyde_document"], "hyde a")
        self.assertNotIn("error", docs_by_id["a"])
        self.assertIsNone(docs_by_id["b"]["hyde_document"])
        self.assertEqual(docs_by_id["b"]["error"], "oops")

    def test_results_property_returns_flat_per_translation_shape(self):
        hits_kjv = [_make_hit("John 3:16", 0.1, "kjv")]
        hits_web = [_make_hit("John 3:16", 0.2, "web")]
        trace = IntentTrace(
            intent_id="comfort",
            intent_data={"intent_id": "comfort"},
            search_results={"kjv": hits_kjv, "web": hits_web},
        )
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces={"comfort": trace},
        )
        flat = result.results
        self.assertEqual(len(flat), 2)
        self.assertEqual({entry["translation"] for entry in flat}, {"kjv", "web"})


class TestPipelineRunnerPopulatesTraces(unittest.TestCase):
    """End-to-end runner test with mocked services to verify trace population."""

    def _make_runner(self) -> PipelineRunner:
        """Construct a PipelineRunner using the default in-process registry."""
        return PipelineRunner()

    def test_full_run_populates_traces_with_all_artifacts(self):
        """Mock services and verify traces dict contains intent+hyde+embedding+hits."""
        intents = [_make_intent("comfort", is_primary=True)]
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": "hyde text", "message_uuid": "m1"}
        ]
        embedding = _deterministic_vector("hyde text")
        retrieval_results = [
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "kjv",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "kjv")],
            },
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "web",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "web")],
            },
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "why", "core_questions": ["why"]},
            "intents": intents,
        }

        runner = self._make_runner()

        async def fake_generate_intents(query, session_uuid):
            return intent_response

        async def fake_generate_for_intents(intents_in, session_uuid):
            self.assertEqual(intents_in, intents)
            return hyde_docs

        async def fake_search(hyde_docs_in, session_uuid, **kwargs):
            self.assertEqual(hyde_docs_in, hyde_docs)
            return retrieval_results

        async def fake_embed_texts(texts, **kwargs):
            self.assertEqual(texts, ["hyde text"])
            return [embedding]

        with patch.object(
            runner.intent_service, "generate_intents",
            new=AsyncMock(side_effect=fake_generate_intents),
        ), patch.object(
            runner.hyde_service, "generate_for_intents",
            new=AsyncMock(side_effect=fake_generate_for_intents),
        ), patch.object(
            runner.retrieval_service, "search",
            new=AsyncMock(side_effect=fake_search),
        ), patch.object(
            runner.embedding_service, "embed_texts",
            new=AsyncMock(side_effect=fake_embed_texts),
        ):
            try:
                result = asyncio.run(
                    runner.run(
                        query="why do bad things happen",
                        top_k=5,
                        translations=("kjv", "web"),
                    )
                )
            finally:
                runner.close()

        self.assertEqual(result.query, "why do bad things happen")
        self.assertIsInstance(result.session_uuid, str)
        self.assertEqual(result.query_analysis["original_query"], "why")
        self.assertIsInstance(result.traces, dict)
        self.assertEqual(set(result.traces.keys()), {"comfort"})

        trace = result.traces["comfort"]
        self.assertEqual(trace.intent_id, "comfort")
        self.assertEqual(trace.intent_data["is_primary"], True)
        self.assertEqual(trace.hyde_document, "hyde text")
        self.assertIsNone(trace.hyde_error)
        self.assertEqual(trace.embedding, embedding)
        self.assertEqual(len(trace.search_results["kjv"]), 1)
        self.assertEqual(trace.search_results["kjv"][0]["reference"], "John 3:16")
        self.assertEqual(len(trace.search_results["web"]), 1)

        self.assertEqual(len(result.intents), 1)
        self.assertEqual(len(result.hyde_docs), 1)
        self.assertEqual(len(result.results), 2)
        self.assertEqual({r["translation"] for r in result.results}, {"kjv", "web"})

    def test_failed_hyde_intent_still_appears_in_traces(self):
        """A HyDE failure must not silently drop the intent from traces."""
        intents = [
            _make_intent("comfort", is_primary=True),
            _make_intent("trust", is_primary=False),
        ]
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": "hyde text", "message_uuid": "m1"},
            {"intent_id": "trust", "hyde_document": None, "error": "LLM timeout"},
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "why"},
            "intents": intents,
        }
        embedding = _deterministic_vector("hyde text")
        retrieval_results = [
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "kjv",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "kjv")],
            },
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "web",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "web")],
            },
        ]

        runner = self._make_runner()

        async def fake_generate_intents(query, session_uuid):
            return intent_response

        async def fake_generate_for_intents(intents_in, session_uuid):
            return hyde_docs

        async def fake_search(hyde_docs_in, session_uuid, **kwargs):
            return retrieval_results

        async def fake_embed_texts(texts, **kwargs):
            return [embedding]

        with patch.object(
            runner.intent_service, "generate_intents",
            new=AsyncMock(side_effect=fake_generate_intents),
        ), patch.object(
            runner.hyde_service, "generate_for_intents",
            new=AsyncMock(side_effect=fake_generate_for_intents),
        ), patch.object(
            runner.retrieval_service, "search",
            new=AsyncMock(side_effect=fake_search),
        ), patch.object(
            runner.embedding_service, "embed_texts",
            new=AsyncMock(side_effect=fake_embed_texts),
        ):
            try:
                result = asyncio.run(
                    runner.run(query="why", top_k=5, translations=("kjv", "web"))
                )
            finally:
                runner.close()

        self.assertEqual(set(result.traces.keys()), {"comfort", "trust"})
        comfort = result.traces["comfort"]
        self.assertEqual(comfort.hyde_document, "hyde text")
        self.assertIsNone(comfort.hyde_error)
        self.assertEqual(comfort.embedding, embedding)
        trust = result.traces["trust"]
        self.assertIsNone(trust.hyde_document)
        self.assertEqual(trust.hyde_error, "LLM timeout")
        self.assertIsNone(trust.embedding)
        self.assertEqual(trust.search_results, {})

    def test_context_bundle_attached_to_each_hit_after_runner(self):
        """Mock ContextRetrievalService and verify context bundles land on each hit."""
        intents = [_make_intent("comfort", is_primary=True)]
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": "hyde text", "message_uuid": "m1"}
        ]
        embedding = _deterministic_vector("hyde text")
        retrieval_results = [
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "kjv",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "kjv")],
            },
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "web",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "web")],
            },
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "why", "core_questions": ["why"]},
            "intents": intents,
        }

        runner = self._make_runner()

        async def fake_generate_intents(query, session_uuid):
            return intent_response

        async def fake_generate_for_intents(intents_in, session_uuid):
            return hyde_docs

        async def fake_search(hyde_docs_in, session_uuid, **kwargs):
            return retrieval_results

        async def fake_embed_texts(texts, **kwargs):
            return [embedding]

        async def fake_retrieve_for_pipeline(result, session_uuid):
            for trace in result.traces.values():
                for translation, hits in trace.search_results.items():
                    for hit in hits:
                        hit["context_bundle"] = {
                            "hit_id": hit["id"],
                            "reference": hit["reference"],
                            "translation": translation,
                            "unique_word_count": 5,
                            "kept_word_count": 3,
                            "scored_words": ["love", "god", "comfort"],
                        }

        with patch.object(
            runner.intent_service, "generate_intents",
            new=AsyncMock(side_effect=fake_generate_intents),
        ), patch.object(
            runner.hyde_service, "generate_for_intents",
            new=AsyncMock(side_effect=fake_generate_for_intents),
        ), patch.object(
            runner.retrieval_service, "search",
            new=AsyncMock(side_effect=fake_search),
        ), patch.object(
            runner.embedding_service, "embed_texts",
            new=AsyncMock(side_effect=fake_embed_texts),
        ), patch.object(
            runner.context_service, "retrieve_for_pipeline",
            new=AsyncMock(side_effect=fake_retrieve_for_pipeline),
        ):
            try:
                result = asyncio.run(
                    runner.run(
                        query="why do bad things happen",
                        top_k=5,
                        translations=("kjv", "web"),
                    )
                )
            finally:
                runner.close()

        for trace in result.traces.values():
            for translation, hits in trace.search_results.items():
                for hit in hits:
                    self.assertIn("context_bundle", hit)
                    bundle = hit["context_bundle"]
                    self.assertEqual(bundle["hit_id"], hit["id"])
                    self.assertEqual(bundle["reference"], hit["reference"])
                    self.assertEqual(bundle["translation"], translation)

    def test_context_error_path(self):
        """Context retrieval errors don't break the pipeline."""
        intents = [_make_intent("comfort", is_primary=True)]
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": "hyde text", "message_uuid": "m1"}
        ]
        embedding = _deterministic_vector("hyde text")
        retrieval_results = [
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "kjv",
                "embedding": embedding,
                "hits": [_make_hit("John 3:16", 0.0, "kjv")],
            },
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "why", "core_questions": ["why"]},
            "intents": intents,
        }

        runner = self._make_runner()

        async def fake_generate_intents(query, session_uuid):
            return intent_response

        async def fake_generate_for_intents(intents_in, session_uuid):
            return hyde_docs

        async def fake_search(hyde_docs_in, session_uuid, **kwargs):
            return retrieval_results

        async def fake_embed_texts(texts, **kwargs):
            return [embedding]

        context_service_mock = AsyncMock()
        context_service_mock.retrieve_for_pipeline.side_effect = Exception("simulated DB connection failed")

        with patch.object(
            runner.intent_service, "generate_intents",
            new=AsyncMock(side_effect=fake_generate_intents),
        ), patch.object(
            runner.hyde_service, "generate_for_intents",
            new=AsyncMock(side_effect=fake_generate_for_intents),
        ), patch.object(
            runner.retrieval_service, "search",
            new=AsyncMock(side_effect=fake_search),
        ), patch.object(
            runner.embedding_service, "embed_texts",
            new=AsyncMock(side_effect=fake_embed_texts),
        ), patch.object(
            runner, 'context_service', context_service_mock
        ):
            try:
                result = asyncio.run(
                    runner.run(
                        query="why do bad things happen",
                        top_k=5,
                        translations=("kjv",),
                    )
                )
            finally:
                runner.close()

        self.assertEqual(len(result.traces), 1)
        trace = result.traces["comfort"]
        self.assertEqual(len(trace.search_results["kjv"]), 1)
        hit = trace.search_results["kjv"][0]
        self.assertIn("reference", hit)
        self.assertIn("id", hit)


def run_tests():
    """Run the regression tests and report results."""
    print("Testing PipelineResult nested trace structure...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestIntentTraceDataclass))
    suite.addTests(loader.loadTestsFromTestCase(TestPipelineResultShape))
    suite.addTests(loader.loadTestsFromTestCase(TestBackwardCompatProperties))
    suite.addTests(loader.loadTestsFromTestCase(TestPipelineRunnerPopulatesTraces))

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
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)