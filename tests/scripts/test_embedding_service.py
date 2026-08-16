#!/usr/bin/env python3
"""Offline tests for EmbeddingService.

Runs without OPENROUTER_STRONGCHAT_DEFAULT_API_KEY by injecting deterministic embedding
functions and asserting on chunking, retry behavior, and structured log
records. There is no application database; audit assertions use the
standard ``logging`` module via ``self.assertLogs``.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch

# Add src directory to path before any service imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

if not os.getenv("OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from services.embeddings import EmbeddingService
from services.llm.exceptions import APIConnectionError, MaxRetriesExceededError

DIMENSION = 1536
MODEL_SLUG = "openai/text-embedding-3-small"


def deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


class TestEmbeddingService(unittest.TestCase):
    """Offline functional tests for EmbeddingService."""

    def setUp(self):
        """Set up a correlation id for log assertions."""
        self.correlation_id = str(uuid.uuid4())

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
        service = EmbeddingService(embed_fn=embed_fn)

        result = asyncio.run(service.embed_texts(texts, chunk_size=256))

        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(result), 600)
        self.assertEqual(len(result[0]), DIMENSION)
        for i, text in enumerate(texts):
            self.assertEqual(result[i], deterministic_vector(text))

    def test_retry_path_recovers_from_two_connection_errors(self):
        """Two injected APIConnectionErrors followed by success should succeed.

        Audit (via caplog) emits one INFO ``embedding_generation`` record with
        ``status=ok`` and ``attempts=3``, plus a DEBUG record with the summary
        payload.
        """
        texts = ["first", "second"]
        embed_fn, state = self._make_fake_embed_fn(fail_first_n=2)
        service = EmbeddingService(embed_fn=embed_fn)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            with self.assertLogs("strongchat", level="INFO") as cm:
                result = asyncio.run(
                    service.embed_texts(
                        texts, session_uuid=self.correlation_id
                    )
                )

        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], deterministic_vector("first"))
        self.assertEqual(result[1], deterministic_vector("second"))

        info_records = [r for r in cm.records if r.levelno == logging.INFO]
        embed_records = [
            r for r in info_records
            if r.__dict__.get("event") == "embedding_generation"
            and r.__dict__.get("status") == "ok"
        ]
        self.assertEqual(len(embed_records), 1)
        self.assertEqual(embed_records[0].__dict__.get("attempts"), 3)

    def test_retry_exhaustion_raises_max_retries_exceeded(self):
        """If all retries fail, MaxRetriesExceededError is raised."""
        texts = ["only"]
        embed_fn, state = self._make_fake_embed_fn(fail_first_n=10)
        service = EmbeddingService(embed_fn=embed_fn)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            with self.assertRaises(MaxRetriesExceededError):
                asyncio.run(service.embed_texts(texts))

        self.assertEqual(state["calls"], 3)

    def test_persistent_failure_emits_error_log(self):
        """Persistent failure emits an ERROR log record carrying the error text."""
        texts = ["only"]
        embed_fn, state = self._make_fake_embed_fn(fail_first_n=10)
        service = EmbeddingService(embed_fn=embed_fn)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            with self.assertLogs("strongchat", level="ERROR") as cm:
                with self.assertRaises(MaxRetriesExceededError):
                    asyncio.run(
                        service.embed_texts(
                            texts, session_uuid=self.correlation_id
                        )
                    )

        self.assertEqual(state["calls"], 3)
        error_records = [r for r in cm.records if r.levelno == logging.ERROR]
        embed_errors = [
            r for r in error_records
            if r.__dict__.get("event") == "embedding_generation"
            and r.__dict__.get("status") == "error"
        ]
        self.assertEqual(len(embed_errors), 1)
        self.assertIn("failed after", str(embed_errors[0].__dict__.get("error")))

    def test_record_summary_payload_not_vectors(self):
        """At DEBUG level, the audit payload contains dimension/count, never vectors."""
        texts = ["alpha", "beta"]
        embed_fn, _ = self._make_fake_embed_fn()
        service = EmbeddingService(embed_fn=embed_fn)

        with self.assertLogs("strongchat", level="DEBUG") as cm:
            asyncio.run(
                service.embed_texts(
                    texts, session_uuid=self.correlation_id, record=True
                )
            )

        debug_records = [r for r in cm.records if r.levelno == logging.DEBUG]
        audit_records = [
            r for r in debug_records
            if r.__dict__.get("event") == "embedding_generation_audit"
            or r.getMessage() == "embedding_generation"
        ]
        self.assertGreaterEqual(len(audit_records), 1)
        raw_response = audit_records[0].__dict__.get("raw_response")
        self.assertIsNotNone(raw_response)
        self.assertIn("dimension", raw_response)
        self.assertNotIn('"embedding"', raw_response)
        parsed = json.loads(raw_response)
        self.assertEqual(parsed["model"], MODEL_SLUG)
        self.assertEqual(parsed["dimension"], DIMENSION)
        self.assertEqual(parsed["count"], 2)

    def test_no_record_emits_no_audit_log(self):
        """record=False must not emit an embedding_generation INFO record."""
        texts = ["gamma"]
        embed_fn, _ = self._make_fake_embed_fn()
        service = EmbeddingService(embed_fn=embed_fn)

        # assertNoLogs (3.10+) asserts that NO records of the given level
        # fire during the context. With record=False, no audit path runs,
        # so no INFO `embedding_generation` event should land.
        with self.assertNoLogs("strongchat", level="INFO"):
            asyncio.run(
                service.embed_texts(
                    texts, session_uuid=self.correlation_id, record=False
                )
            )


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