#!/usr/bin/env python3
"""Offline tests for RetrievalService.

Runs without OPENROUTER_API_KEY by injecting deterministic embedding
functions and querying temp Chroma collections. Verifies that HyDE
documents are embedded once, queried in parallel across translations,
and returned as structured, sorted hits. Audit assertions use the standard
``logging`` module via ``self.assertLogs``; there is no application DB.
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

# Add src and scripts directories to path before any service imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from services.embeddings import EmbeddingService
from services.retrieval import RetrievalService
from services.vectordb import VerseStore

DIMENSION = 1536
MODEL_SLUG = "openai/text-embedding-3-small"


def deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


def embed_fn(texts: list[str]) -> list[list[float]]:
    """Deterministic embedding function used for all tests."""
    return [deterministic_vector(text) for text in texts]


def _verse_id(index: int, translation: str) -> str:
    """Build a verse ID for the fixture."""
    return f"{translation}-GEN-1-{index + 1}"


def _verse_text(index: int) -> str:
    """Build a unique verse text for the fixture."""
    return f"Genesis 1:{index + 1} fixture verse text number {index + 1}"


def _verse_metadata(index: int, translation: str) -> dict[str, int | str]:
    """Build verse metadata for the fixture."""
    return {
        "book": "Genesis",
        "osis": "Gen",
        "chapter": 1,
        "verse": index + 1,
        "translation": translation,
    }


class TestRetrievalService(unittest.TestCase):
    """Offline functional tests for RetrievalService."""

    def setUp(self):
        """Create a temp Chroma store and seed collections."""
        self._tmp = tempfile.TemporaryDirectory()
        self.chroma_path = os.path.join(self._tmp.name, "chroma")

        self.embedding_service = EmbeddingService(embed_fn=embed_fn)
        self.verse_store = VerseStore(path=self.chroma_path)
        self._seed_collections()
        self.service = RetrievalService(
            embedding_service=self.embedding_service,
            verse_store=self.verse_store,
        )
        self.correlation_id = str(uuid.uuid4())

    def tearDown(self):
        """Close the service and drop the temp directory."""
        try:
            self.service.close()
        finally:
            self._tmp.cleanup()

    def _seed_collections(self):
        """Seed kjv_verses and web_verses with 30 deterministic verses each."""
        for translation in ("kjv", "web"):
            ids = [_verse_id(i, translation) for i in range(30)]
            documents = [_verse_text(i) for i in range(30)]
            metadatas = [_verse_metadata(i, translation) for i in range(30)]
            embeddings = [deterministic_vector(text) for text in documents]
            self.verse_store.upsert_verses(
                f"{translation}_verses",
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )

        # Empty collection for failure QA.
        self.verse_store.get_or_create_collection("empty_verses")

    def test_search_structure_and_planted_top1(self):
        """A planted doc matches its designated verse as top-1 across translations."""
        planted_index = 7
        planted_text = _verse_text(planted_index)

        hyde_docs = [
            {"intent_id": "anxiety-comfort", "hyde_document": planted_text},
            {"intent_id": "trust-future", "hyde_document": None},
            {"intent_id": "ignored-empty", "hyde_document": ""},
        ]

        results = asyncio.run(
            self.service.search(
                hyde_docs,
                session_uuid=self.correlation_id,
                top_k=5,
                translations=("kjv", "web"),
            )
        )

        self.assertEqual(len(results), 2)
        self.assertEqual({r["translation"] for r in results}, {"kjv", "web"})

        planted_results = {
            r["translation"]: r
            for r in results
            if r["doc_index"] == 0 and r["intent_id"] == "anxiety-comfort"
        }
        self.assertEqual(set(planted_results.keys()), {"kjv", "web"})

        for translation in ("kjv", "web"):
            hits = planted_results[translation]["hits"]
            self.assertEqual(len(hits), 5)

            top_hit = hits[0]
            self.assertEqual(top_hit["id"], _verse_id(planted_index, translation))
            self.assertEqual(
                top_hit["reference"],
                f"Genesis 1:{planted_index + 1}",
            )
            self.assertAlmostEqual(top_hit["distance"], 0.0, places=5)

            distances = [h["distance"] for h in hits]
            self.assertEqual(distances, sorted(distances))

            for hit in hits:
                self.assertIn("id", hit)
                self.assertIn("text", hit)
                self.assertIn("reference", hit)
                self.assertIn("distance", hit)

    def test_empty_collection_returns_empty_hits(self):
        """Querying an empty collection returns an empty hits list."""
        hyde_docs = [
            {"intent_id": "empty-test", "hyde_document": _verse_text(0)},
        ]

        results = asyncio.run(
            self.service.search(
                hyde_docs,
                session_uuid=self.correlation_id,
                top_k=5,
                translations=("empty",),
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["intent_id"], "empty-test")
        self.assertEqual(results[0]["doc_index"], 0)
        self.assertEqual(results[0]["translation"], "empty")
        self.assertEqual(results[0]["hits"], [])

    def test_embedding_generation_logged_once(self):
        """A single embedding_generation INFO record is emitted per search call."""
        hyde_docs = [
            {"intent_id": "record-test", "hyde_document": _verse_text(0)},
            {"intent_id": "record-test-2", "hyde_document": _verse_text(1)},
        ]

        with self.assertLogs("strongchat", level="INFO") as cm:
            asyncio.run(
                self.service.search(
                    hyde_docs,
                    session_uuid=self.correlation_id,
                    top_k=3,
                    translations=("kjv",),
                )
            )

        embed_records = [
            r for r in cm.records
            if r.__dict__.get("event") == "embedding_generation"
            and r.__dict__.get("status") == "ok"
        ]
        self.assertEqual(len(embed_records), 1)
        # The DEBUG audit row carries the model slug + dimension + count summary.
        # Confirm the summary count through the INFO record's count extra.
        self.assertEqual(embed_records[0].__dict__.get("count"), 2)

    def test_default_constructor_builds_services(self):
        """RetrievalService with None deps constructs its own services."""
        service = RetrievalService()
        self.assertIsNotNone(service.embedding_service)
        self.assertIsNotNone(service.store)
        service.close()


def run_tests():
    """Run all tests and report results."""
    print("Testing RetrievalService (offline)...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestRetrievalService)
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