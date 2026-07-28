#!/usr/bin/env python3
"""Offline tests for RetrievalService.

Runs without OPENROUTER_API_KEY by injecting deterministic embedding
functions and querying temp Chroma collections. Verifies that HyDE
documents are embedded once, queried in parallel across translations,
and returned as structured, sorted hits.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest

# Add src and scripts directories to path before any service imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

# BaseService -> LLMWrapper requires a non-placeholder OPENROUTER_API_KEY at
# import/instantiation time. Since these tests use an injected embed_fn, a
# dummy key is sufficient and does not weaken the "unset in parent shell" QA.
if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from config.cache import GlobalReferenceCache
from services.embeddings import EmbeddingService
from services.retrieval import RetrievalService
from services.vectordb import VerseStore

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
        """Create a fresh fixture DB and temp Chroma collections."""
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "fixture.db")
        self.chroma_path = os.path.join(self._tmp.name, "chroma")

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

        self.embedding_service = EmbeddingService(self.db_path, embed_fn=embed_fn)
        self.verse_store = VerseStore(path=self.chroma_path)
        self._seed_collections()
        self.service = RetrievalService(
            self.db_path,
            embedding_service=self.embedding_service,
            verse_store=self.verse_store,
        )

        self.session_uuid = self.service.db.create_session(name="retrieval-test")

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
                session_uuid=self.session_uuid,
                top_k=5,
                translations=("kjv", "web"),
            )
        )

        # Only the non-empty doc should be processed; one entry per translation.
        self.assertEqual(len(results), 2)
        self.assertEqual({r["translation"] for r in results}, {"kjv", "web"})

        # Locate the results for the planted doc.
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

            # Distances must be non-decreasing (ascending sort).
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
                session_uuid=self.session_uuid,
                top_k=5,
                translations=("empty",),
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["intent_id"], "empty-test")
        self.assertEqual(results[0]["doc_index"], 0)
        self.assertEqual(results[0]["translation"], "empty")
        self.assertEqual(results[0]["hits"], [])

    def test_embedding_generation_recorded_once(self):
        """A single embedding_generation message is recorded per search call."""
        hyde_docs = [
            {"intent_id": "record-test", "hyde_document": _verse_text(0)},
            {"intent_id": "record-test-2", "hyde_document": _verse_text(1)},
        ]

        asyncio.run(
            self.service.search(
                hyde_docs,
                session_uuid=self.session_uuid,
                top_k=3,
                translations=("kjv",),
            )
        )

        messages = self.service.db.get_messages_by_session_and_type(
            session_uuid=self.session_uuid,
            message_type_slug="embedding_generation",
        )
        self.assertEqual(len(messages), 1)
        parsed = json.loads(messages[0]["raw_response"])
        self.assertEqual(parsed["model"], MODEL_SLUG)
        self.assertEqual(parsed["dimension"], DIMENSION)
        self.assertEqual(parsed["count"], 2)

    def test_default_constructor_builds_services(self):
        """RetrievalService with None deps constructs its own services."""
        service = RetrievalService(self.db_path)
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
