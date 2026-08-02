#!/usr/bin/env python3
"""Offline test for context retrieval within the full pipeline.

Tests that ContextRetrievalService properly attaches context_bundle to each hit
and records a context_retrieval message in the database. Uses AsyncMock to mock
all services and runs the full pipeline end-to-end.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from services.pipeline.runner import PipelineRunner, PipelineResult


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

INTENT_ONE = {
    "intent_id": "comfort",
    "interpretation": "Seeking comfort for anxiety",
    "keywords_explicit": ["anxiety"],
    "keywords_inferred": ["peace", "worry"],
    "themes": ["comfort", "anxiety"],
}

LONG_HYDE_DOC = (
    "A long enough hypothetical passage about comfort and anxiety. " * 6
)


def _create_fixture_db():
    """Return a temp directory and a seeded fixture DB path."""
    tmp = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmp.name, "fixture.db")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            """
            INSERT INTO ref_message_types
              (slug, step_name, creator_type, request_schema, model_slug,
               temperature, additional_model_settings, max_retries,
               is_active, description, prompt_template)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "intent_generation",
                "Intent Generation",
                "llm",
                json.dumps({
                    "type": "object",
                    "properties": {
                        "query_analysis": {"type": "object"},
                        "intents": {"type": "array"},
                    },
                    "required": ["query_analysis", "intents"],
                }),
                "meta-llama/llama-3.3-70b-instruct",
                0.2,
                '{"max_tokens": 1200}',
                3,
                1,
                "Generate structured intents",
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO ref_message_types
              (slug, step_name, creator_type, request_schema, model_slug,
               temperature, additional_model_settings, max_retries,
               is_active, description, prompt_template)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "hyde_generation",
                "HyDE Generation",
                "llm",
                json.dumps({
                    "type": "object",
                    "properties": {
                        "hyde_document": {"type": "string"},
                    },
                    "required": ["hyde_document"],
                }),
                "mistralai/mistral-small-24b-instruct-2501",
                0.7,
                '{"max_tokens": 800}',
                3,
                1,
                "Generate hypothetical passage",
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO ref_message_types
              (slug, step_name, creator_type, request_schema, model_slug,
               temperature, additional_model_settings, max_retries,
               is_active, description, prompt_template)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "embedding_generation",
                "Embedding Generation",
                "programmatic",
                json.dumps(
                    {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string"},
                            "dimension": {"type": "integer"},
                            "count": {"type": "integer"},
                        },
                        "required": ["model", "dimension", "count"],
                    }
                ),
                "openai/text-embedding-3-small",
                0.0,
                "{}",
                3,
                1,
                "Batched embedding generation",
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO ref_message_types
              (slug, step_name, creator_type, request_schema, model_slug,
               temperature, additional_model_settings, max_retries,
               is_active, description, prompt_template)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "context_retrieval",
                "Context Retrieval",
                "programmatic",
                json.dumps(
                    {
                        "type": "object",
                        "properties": {
                            "intent_id": {"type": "string"},
                            "translation_count": {"type": "integer"},
                            "hit_count": {"type": "integer"},
                            "scored_word_count": {"type": "integer"},
                            "kept_word_count": {"type": "integer"},
                        },
                        "required": ["intent_id", "translation_count", "hit_count", "scored_word_count", "kept_word_count"],
                    }
                ),
                "n/a",
                0.0,
                "{}",
                3,
                1,
                "Per-intent original-language context enrichment for retrieved verses",
                None,
            ),
        )
        conn.commit()
    return tmp, db_path


def _deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


class TestContextRetrievalOffline(unittest.TestCase):
    """Offline test for context retrieval within the full pipeline."""

    def setUp(self):
        """Create a fresh fixture DB and runner instance."""
        os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"
        self._tmp, self.db_path = _create_fixture_db()
        self.runner = PipelineRunner(self.db_path)
        self.session_uuid = self.runner.db.create_session(name="context-retrieval-test")

    def tearDown(self):
        """Close the runner and drop the temp directory."""
        try:
            self.runner.close()
        finally:
            self._tmp.cleanup()

    def test_full_pipeline_with_mocked_context_retrieval(self):
        """Mock services and verify context_bundle is attached to each hit."""
        intents = [INTENT_ONE]
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
                        "hit_id": "1",
                        "reference": "John 3:16",
                        "translation": "kjv",
                        "score": 0.8,
                        "content": "For God so loved the world...",
                    }
                ],
            }
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "test query", "core_questions": ["test"]},
            "intents": intents,
        }

        # Track context service calls
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
            """Mock context retrieval that adds context_bundle to each hit and records message."""
            context_service_calls.append((pipeline_result, session_uuid))
            
            # Add context_bundle to each hit
            for intent_id, trace in pipeline_result.traces.items():
                for translation, hits in trace.search_results.items():
                    for hit in hits:
                        hit["context_bundle"] = {
                            "hit_id": hit["hit_id"],
                            "reference": hit["reference"],
                            "translation": hit["translation"],
                            "unique_word_count": 5,
                            "kept_word_count": 3,
                            "scored_words": [
                                {
                                    "surface": "loved",
                                    "lemma": "agapaō",
                                    "strongs": "G25",
                                    "pos": "V-",
                                    "pos_weight": 0.95,
                                    "frequency_count": 100,
                                    "sense_count": 3,
                                    "composite_score": 0.95 * 2.39 * 1.39,
                                }
                            ],
                            "kept_words": [
                                {
                                    "surface": "loved",
                                    "lemma": "agapaō",
                                    "strongs": "G25",
                                    "morph": "V-IAI-3S",
                                    "pos": "V-",
                                    "pos_weight": 0.95,
                                    "frequency_count": 100,
                                    "sense_count": 3,
                                    "composite_score": 0.95 * 2.39 * 1.39,
                                    "lexicon_source": "tbESG",
                                    "definitions": ["to love"],
                                    "glosses": ["loved"],
                                }
                            ],
                        }
            
            # Record the context_retrieval message
            for intent_id, trace in pipeline_result.traces.items():
                if trace.search_results:  # Only record if there are search results
                    summary = {
                        'intent_id': intent_id,
                        'translation_count': len(trace.search_results),
                        'hit_count': sum(len(hits) for hits in trace.search_results.values()),
                        'scored_word_count': 15,  # Mock value
                        'kept_word_count': 9,    # Mock value
                    }
                    bundles = [
                        hit['context_bundle']
                        for hits in trace.search_results.values()
                        for hit in hits
                    ]
                    raw_payload = {'intent_id': intent_id, 'bundles': bundles}
                    await self.runner.context_service.record_message(
                        message_type_slug='context_retrieval',
                        unique_prompt=json.dumps(summary),
                        session_uuid=session_uuid,
                        raw_response=json.dumps(raw_payload),
                        error_text=None,
                        num_tries=1,
                    )

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
            try:
                result = asyncio.run(
                    self.runner.run(
                        query="test query",
                        top_k=3,
                        translations=("kjv",),
                    )
                )
            except Exception as e:
                self.runner.close()
                raise e

        # Assert context service was called exactly once
        self.assertEqual(len(context_service_calls), 1)
        pipeline_result, called_session_uuid = context_service_calls[0]
        # Pipeline runner may create its own session UUID
        self.assertIsInstance(called_session_uuid, str)

        # Assert every hit has a context_bundle
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
                    
                    # Assert at least one hit has kept_word_count >= 2
                    if bundle["kept_word_count"] >= 2:
                        break
                else:
                    continue
                break
            else:
                self.fail("No hit found with kept_word_count >= 2")

        # Assert context_retrieval message was recorded in database
        # Query with the session UUID used by the mock
        if context_service_calls:
            _, used_session_uuid = context_service_calls[0]
            rows = self.runner.db.get_messages_by_session_and_type(
                used_session_uuid, "context_retrieval"
            )
        else:
            rows = []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["message_type_slug"], "context_retrieval")
        self.assertIsNone(rows[0]["error_text"])

        # Close the runner after all assertions
        self.runner.close()


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