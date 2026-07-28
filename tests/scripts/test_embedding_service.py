#!/usr/bin/env python3
"""Offline tests for EmbeddingService.

Runs without OPENROUTER_API_KEY by injecting deterministic embedding
functions and asserting on chunking, retry behavior, and recording.
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

# Add src directory to path before any service imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# BaseService -> LLMWrapper requires a non-placeholder OPENROUTER_API_KEY at
# import/instantiation time. Since these tests use an injected embed_fn, a
# dummy key is sufficient and does not weaken the "unset in parent shell" QA.
if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from services.embeddings import EmbeddingService
from services.llm.exceptions import APIConnectionError, MaxRetriesExceededError
from config.cache import GlobalReferenceCache

DIMENSION = 1536
MODEL_SLUG = "openai/text-embedding-3-small"

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


def deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


class TestEmbeddingService(unittest.TestCase):
    """Offline functional tests for EmbeddingService."""

    def setUp(self):
        """Create a fresh fixture DB with the embedding_generation ref row."""
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "fixture.db")

        with sqlite3.connect(self.db_path) as conn:
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
                    MODEL_SLUG,
                    0.0,
                    "{}",
                    3,
                    1,
                    "Batched embedding generation call record",
                    None,
                ),
            )
            conn.commit()

        GlobalReferenceCache.reset(self.db_path)
        self.service = EmbeddingService(self.db_path)
        self.session_uuid = self.service.db.create_session(name="embedding-test")

    def tearDown(self):
        """Close the service and drop the temp directory."""
        try:
            self.service.close()
        finally:
            self._tmp.cleanup()

    def _make_fake_embed_fn(self, fail_first_n: int = 0):
        """Return an injected embed_fn that counts calls and optionally fails."""
        state = {"calls": 0}

        def embed_fn(texts: list[str]) -> list[list[float]]:
            state["calls"] += 1
            if state["calls"] <= fail_first_n:
                raise APIConnectionError(f"injected failure #{state['calls']}")
            return [deterministic_vector(text) for text in texts]

        return embed_fn, state

    def test_600_texts_chunks_into_three_calls_and_preserves_order(self):
        """Given 600 texts and chunk_size=256, expect 3 calls in input order."""
        texts = [f"verse-{i}" for i in range(600)]
        embed_fn, state = self._make_fake_embed_fn()
        service = EmbeddingService(self.db_path, embed_fn=embed_fn)

        result = asyncio.run(service.embed_texts(texts, chunk_size=256))

        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(result), 600)
        self.assertEqual(len(result[0]), DIMENSION)
        # Order preservation: the i-th output must correspond to the i-th input.
        for i, text in enumerate(texts):
            self.assertEqual(result[i], deterministic_vector(text))

    def test_retry_path_recovers_from_two_connection_errors(self):
        """Two injected APIConnectionErrors followed by success should succeed and record num_tries."""
        texts = ["first", "second"]
        embed_fn, state = self._make_fake_embed_fn(fail_first_n=2)
        service = EmbeddingService(self.db_path, embed_fn=embed_fn)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            result = asyncio.run(
                service.embed_texts(texts, session_uuid=self.session_uuid)
            )

        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], deterministic_vector("first"))
        self.assertEqual(result[1], deterministic_vector("second"))

        messages = service.db.get_messages_by_session_and_type(
            session_uuid=self.session_uuid,
            message_type_slug="embedding_generation",
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["num_tries"], 3)
        self.assertIsNotNone(messages[0]["raw_response"])
        self.assertIsNone(messages[0]["error_text"])

    def test_retry_exhaustion_raises_max_retries_exceeded(self):
        """If all retries fail, MaxRetriesExceededError is raised."""
        texts = ["only"]
        embed_fn, state = self._make_fake_embed_fn(fail_first_n=10)
        service = EmbeddingService(self.db_path, embed_fn=embed_fn)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            with self.assertRaises(MaxRetriesExceededError):
                asyncio.run(service.embed_texts(texts))

        self.assertEqual(state["calls"], 3)

    def test_persistent_failure_records_num_tries_and_error_text(self):
        """Persistent failure writes an error_text row with num_tries == max_retries."""
        texts = ["only"]
        embed_fn, state = self._make_fake_embed_fn(fail_first_n=10)
        service = EmbeddingService(self.db_path, embed_fn=embed_fn)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            with self.assertRaises(MaxRetriesExceededError):
                asyncio.run(
                    service.embed_texts(texts, session_uuid=self.session_uuid)
                )

        self.assertEqual(state["calls"], 3)

        messages = service.db.get_messages_by_session_and_type(
            session_uuid=self.session_uuid,
            message_type_slug="embedding_generation",
        )
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["num_tries"], 3)
        self.assertIsNone(messages[0]["raw_response"])
        self.assertIsNotNone(messages[0]["error_text"])
        self.assertIn("failed after", messages[0]["error_text"])

    def test_recording_stores_summary_not_vectors(self):
        """A recorded message must contain dimension/count, never embeddings."""
        texts = ["alpha", "beta"]
        embed_fn, _ = self._make_fake_embed_fn()
        service = EmbeddingService(self.db_path, embed_fn=embed_fn)

        asyncio.run(
            service.embed_texts(texts, session_uuid=self.session_uuid, record=True)
        )

        messages = service.db.get_messages_by_session_and_type(
            session_uuid=self.session_uuid,
            message_type_slug="embedding_generation",
        )
        self.assertEqual(len(messages), 1)
        raw_response = messages[0]["raw_response"]
        self.assertIsNotNone(raw_response)
        self.assertIn("dimension", raw_response)
        # The model slug itself contains "embedding", so assert the summary
        # object has no top-level "embedding" key with raw vectors.
        self.assertNotIn('"embedding"', raw_response)
        parsed = json.loads(raw_response)
        self.assertEqual(parsed["model"], MODEL_SLUG)
        self.assertEqual(parsed["dimension"], DIMENSION)
        self.assertEqual(parsed["count"], 2)

    def test_no_record_skips_message_insert(self):
        """record=False must not insert an embedding_generation row."""
        texts = ["gamma"]
        embed_fn, _ = self._make_fake_embed_fn()
        service = EmbeddingService(self.db_path, embed_fn=embed_fn)

        asyncio.run(
            service.embed_texts(texts, session_uuid=self.session_uuid, record=False)
        )

        messages = service.db.get_messages_by_session_and_type(
            session_uuid=self.session_uuid,
            message_type_slug="embedding_generation",
        )
        self.assertEqual(len(messages), 0)


def run_tests():
    """Run all tests and report results."""
    print("Testing EmbeddingService (offline)...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestEmbeddingService)
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
