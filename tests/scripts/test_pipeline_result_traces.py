#!/usr/bin/env python3
"""Regression tests for PipelineResult nested trace structure.

These tests guard against regressions in the per-intent traceability
refactor. They assert:

  * ``IntentTrace`` dataclass exists with the expected fields.
  * ``PipelineResult.traces`` is a ``Dict[str, IntentTrace]`` keyed by
    ``intent_id`` (O(1) predecessor lookup).
  * Embeddings are preserved on each trace (previously dropped after search).
  * Failed HyDE generations are captured on the trace (``hyde_error``) and
    the intent still appears in ``traces`` (no silent disappearance).
  * Backward-compatibility list views (``intents``, ``hyde_docs``,
    ``results``) still match the pre-refactor flat shape byte-for-byte.
  * ``query_analysis`` and ``recommended_search_approach`` from
    ``IntentService`` are surfaced on ``PipelineResult``.
  * ``trace.search_results[translation]`` returns hits for that translation.

All tests run offline (no OpenRouter API calls) by mocking the
service-layer entry points on ``PipelineRunner``.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Ensure a dummy API key is present so BaseService can be constructed
# without hitting the live OpenRouter endpoint.
if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from config import (
    INTENT_GENERATION_SCHEMA,
    INTENT_GENERATION_PROMPT,
    HYDE_GENERATION_SCHEMA,
    HYDE_GENERATION_PROMPT,
)
from config.cache import GlobalReferenceCache
from services.pipeline.runner import IntentTrace, PipelineResult, PipelineRunner

DIMENSION = 1536

SCHEMA_SQL = """
CREATE TABLE sessions (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT
);

CREATE TABLE ref_message_types (
    slug TEXT PRIMARY KEY,
    step_name TEXT NOT NULL,
    creator_type TEXT NOT NULL,
    request_schema TEXT NOT NULL,
    model_slug TEXT NOT NULL,
    temperature REAL DEFAULT 0.0,
    additional_model_settings TEXT,
    max_retries INTEGER DEFAULT 3,
    is_active BOOLEAN DEFAULT TRUE,
    description TEXT,
    prompt_template TEXT
);

CREATE TABLE messages (
    uuid TEXT PRIMARY KEY,
    session_uuid TEXT,
    message_type_slug TEXT,
    unique_prompt TEXT NOT NULL,
    raw_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_at TIMESTAMP,
    num_tries INTEGER DEFAULT 1,
    error_text TEXT,
    FOREIGN KEY (session_uuid) REFERENCES sessions (uuid),
    FOREIGN KEY (message_type_slug) REFERENCES ref_message_types (slug)
);
"""


def _deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


def _create_fixture_db():
    """Return (tmp, db_path) with the schema and pipeline message types seeded."""
    tmp = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp.name, "fixture.db")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        for slug, step_name, model, schema in (
            (
                "intent_generation",
                "Intent Generation",
                "meta-llama/llama-3.3-70b-instruct",
                INTENT_GENERATION_SCHEMA,
            ),
            (
                "hyde_generation",
                "HyDE Generation",
                "mistralai/mistral-small-24b-instruct-2501",
                HYDE_GENERATION_SCHEMA,
            ),
            (
                "embedding_generation",
                "Embedding Generation",
                "openai/text-embedding-3-small",
                {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "dimension": {"type": "integer"},
                        "count": {"type": "integer"},
                    },
                    "required": ["model", "dimension", "count"],
                },
            ),
        ):
            conn.execute(
                """
                INSERT INTO ref_message_types
                  (slug, step_name, creator_type, request_schema, model_slug,
                   temperature, additional_model_settings, max_retries,
                   is_active, description, prompt_template)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug,
                    step_name,
                    "programmatic" if slug == "embedding_generation" else "llm",
                    json.dumps(schema),
                    model,
                    0.0,
                    "{}",
                    3,
                    1,
                    f"{step_name} fixture",
                    INTENT_GENERATION_PROMPT if slug == "intent_generation"
                    else HYDE_GENERATION_PROMPT if slug == "hyde_generation"
                    else None,
                ),
            )
        conn.commit()
    return tmp, db_path


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

    def test_intent_trace_is_importable(self):
        """IntentTrace is exposed from runner and importable."""
        self.assertTrue(callable(IntentTrace))

    def test_intent_trace_default_construction(self):
        """IntentTrace can be constructed with the minimum required fields."""
        trace = IntentTrace(
            intent_id="comfort",
            intent_data={"intent_id": "comfort"},
        )
        self.assertEqual(trace.intent_id, "comfort")
        self.assertEqual(trace.intent_data, {"intent_id": "comfort"})
        # All optional fields default to safe empty values.
        self.assertIsNone(trace.hyde_document)
        self.assertIsNone(trace.hyde_error)
        self.assertIsNone(trace.embedding)
        self.assertEqual(trace.search_results, {})

    def test_intent_trace_full_construction(self):
        """IntentTrace stores every per-intent artifact."""
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
        """A failed HyDE generation stores the error message and no document."""
        trace = IntentTrace(
            intent_id="trust",
            intent_data={"intent_id": "trust"},
            hyde_document=None,
            hyde_error="LLM timeout",
        )
        self.assertIsNone(trace.hyde_document)
        self.assertEqual(trace.hyde_error, "LLM timeout")
        # Search should not have run for this intent.
        self.assertEqual(trace.search_results, {})


class TestPipelineResultShape(unittest.TestCase):
    """Pure shape tests for PipelineResult's traces dict."""

    def test_traces_is_dict_keyed_by_intent_id(self):
        """PipelineResult.traces is Dict[str, IntentTrace] for O(1) lookup."""
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
        """Given a known intent_id, trace data is one dict lookup."""
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

        # One lookup to go from intent_id to full trace, including embedding.
        t = result.traces["comfort"]
        self.assertEqual(t.intent_data["interpretation"], "x")
        self.assertEqual(t.hyde_document, "hyde text")
        self.assertEqual(t.embedding, [0.1, 0.2, 0.3])
        self.assertEqual(t.search_results["kjv"][0]["reference"], "John 3:16")

    def test_query_analysis_and_approach_surfaced(self):
        """PipelineResult surfaces query_analysis and recommended_search_approach."""
        result = PipelineResult(
            session_uuid="sess-1",
            query="why",
            traces={},
            query_analysis={"original_query": "why"},
            recommended_search_approach="hyde_then_search",
        )
        self.assertEqual(result.query_analysis["original_query"], "why")
        self.assertEqual(result.recommended_search_approach, "hyde_then_search")


class TestBackwardCompatProperties(unittest.TestCase):
    """Backward-compat: old call sites still read .intents/.hyde_docs/.results."""

    def test_intents_property_returns_list_of_intent_dicts(self):
        """result.intents is a list of intent dicts in insertion order."""
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
        # Order should be stable (dict insertion order in Python 3.7+).
        ids = {i["intent_id"] for i in intents}
        self.assertEqual(ids, {"a", "b"})

    def test_hyde_docs_property_returns_flat_shape(self):
        """result.hyde_docs returns [{intent_id, hyde_document, ...}, ...]."""
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
        """result.results returns [{intent_id, translation, hits}, ...]."""
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
        # One entry per (intent, translation) pair.
        self.assertEqual(len(flat), 2)
        translations = {entry["translation"] for entry in flat}
        self.assertEqual(translations, {"kjv", "web"})
        for entry in flat:
            self.assertEqual(entry["intent_id"], "comfort")
            self.assertIn("hits", entry)
            self.assertGreater(len(entry["hits"]), 0)


class TestPipelineRunnerPopulatesTraces(unittest.TestCase):
    """End-to-end runner test with mocked services to verify trace population."""

    def setUp(self):
        """Create a fresh fixture DB and reset the cache."""
        self._tmp, self.db_path = _create_fixture_db()
        GlobalReferenceCache.reset(self.db_path)

    def tearDown(self):
        """Drop the temp directory."""
        self._tmp.cleanup()

    def _make_runner(self) -> PipelineRunner:
        """Construct a PipelineRunner with all services pointing at the fixture."""
        return PipelineRunner(db_path=self.db_path)

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
            "recommended_search_approach": "hyde_then_search",
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

        # Top-level shape.
        self.assertEqual(result.query, "why do bad things happen")
        self.assertIsInstance(result.session_uuid, str)
        self.assertEqual(
            result.query_analysis["original_query"], "why"
        )
        self.assertEqual(
            result.recommended_search_approach, "hyde_then_search"
        )

        # Traces dict has the one intent keyed by intent_id.
        self.assertIsInstance(result.traces, dict)
        self.assertEqual(set(result.traces.keys()), {"comfort"})

        trace = result.traces["comfort"]
        self.assertEqual(trace.intent_id, "comfort")
        self.assertEqual(trace.intent_data["is_primary"], True)
        self.assertEqual(trace.hyde_document, "hyde text")
        self.assertIsNone(trace.hyde_error)
        # The embedding used for search is preserved (was previously dropped).
        self.assertEqual(trace.embedding, embedding)
        # Search results are addressable by translation.
        self.assertEqual(len(trace.search_results["kjv"]), 1)
        self.assertEqual(trace.search_results["kjv"][0]["reference"], "John 3:16")
        self.assertEqual(len(trace.search_results["web"]), 1)

        # Backward-compat properties still expose the pre-refactor flat shape.
        self.assertEqual(len(result.intents), 1)
        self.assertEqual(len(result.hyde_docs), 1)
        self.assertEqual(len(result.results), 2)  # 1 intent × 2 translations
        self.assertEqual(
            {r["translation"] for r in result.results}, {"kjv", "web"}
        )

    def test_failed_hyde_intent_still_appears_in_traces(self):
        """A HyDE failure must not silently drop the intent from traces."""
        intents = [
            _make_intent("comfort", is_primary=True),
            _make_intent("trust", is_primary=False),
        ]
        # comfort succeeded, trust failed.
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": "hyde text", "message_uuid": "m1"},
            {"intent_id": "trust", "hyde_document": None, "error": "LLM timeout"},
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "why"},
            "intents": intents,
            "recommended_search_approach": "hyde_then_search",
        }
        embedding = _deterministic_vector("hyde text")
        # RetrievalService skips docs with hyde_document=None, so only comfort
        # returns hits.
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
                    runner.run(
                        query="why",
                        top_k=5,
                        translations=("kjv", "web"),
                    )
                )
            finally:
                runner.close()

        # Both intents must be present — no silent disappearance.
        self.assertEqual(set(result.traces.keys()), {"comfort", "trust"})

        # comfort: full success path.
        comfort = result.traces["comfort"]
        self.assertEqual(comfort.hyde_document, "hyde text")
        self.assertIsNone(comfort.hyde_error)
        self.assertEqual(comfort.embedding, embedding)
        self.assertEqual(len(comfort.search_results["kjv"]), 1)

        # trust: HyDE failed, no embedding, no search.
        trust = result.traces["trust"]
        self.assertIsNone(trust.hyde_document)
        self.assertEqual(trust.hyde_error, "LLM timeout")
        self.assertIsNone(trust.embedding)
        self.assertEqual(trust.search_results, {})

        # Backward-compat .hyde_docs still shows both entries (incl. failure).
        hyde_docs_flat = result.hyde_docs
        self.assertEqual(len(hyde_docs_flat), 2)
        by_id = {d["intent_id"]: d for d in hyde_docs_flat}
        self.assertIsNone(by_id["trust"]["hyde_document"])
        self.assertEqual(by_id["trust"]["error"], "LLM timeout")


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
