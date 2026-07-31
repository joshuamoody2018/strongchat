#!/usr/bin/env python3
"""Consolidated offline step tests for pipeline services.

Covers: parsing fenced/prose JSON and schema validation on AIMessage,
LLMWrapper retry with mocked _call_api_async, EmbeddingService retry with
an injected embed_fn, HydeService partial failure, and intent schema
boundaries. All tests use fixture DBs in temp dirs and a dummy API key
so no live OpenRouter calls are made.
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

from jsonschema import validate, ValidationError

from config import (
    INTENT_GENERATION_SCHEMA,
    INTENT_GENERATION_PROMPT,
    HYDE_GENERATION_SCHEMA,
    HYDE_GENERATION_PROMPT,
)
from config.cache import GlobalReferenceCache
from services.embeddings import EmbeddingService
from services.hyde import HydeService
from services.llm.aimessage import AIMessage
from services.llm.exceptions import APIConnectionError, MaxRetriesExceededError
from services.llm.wrapper import LLMWrapper

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

INTENT_TWO = {
    "intent_id": "trust",
    "interpretation": "Trusting God despite worry",
    "keywords_explicit": ["trust"],
    "keywords_inferred": ["faith", "future"],
    "themes": ["trust"],
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
                json.dumps(INTENT_GENERATION_SCHEMA),
                "meta-llama/llama-3.3-70b-instruct",
                0.2,
                '{"max_tokens": 1200}',
                3,
                1,
                "Generate structured intents",
                INTENT_GENERATION_PROMPT,
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
                json.dumps(HYDE_GENERATION_SCHEMA),
                "mistralai/mistral-small-24b-instruct-2501",
                0.7,
                '{"max_tokens": 800}',
                3,
                1,
                "Generate hypothetical passage",
                HYDE_GENERATION_PROMPT,
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
        conn.commit()
    return tmp, db_path


def _intent_fixture():
    """Return a valid intent-generation response fixture."""
    return {
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
        ],
        "recommended_search_approach": "Prioritize the primary intent",
    }


def _hyde_fixture():
    """Return a valid HyDE response fixture."""
    return {"hyde_document": LONG_HYDE_DOC}


def _with_intents(count: int) -> dict:
    """Return an intent fixture with ``count`` identical intents."""
    fixture = json.loads(json.dumps(_intent_fixture()))
    base_intent = fixture["intents"][0]
    fixture["intents"] = [
        {**base_intent, "intent_id": f"intent_{i}", "is_primary": i == 0}
        for i in range(count)
    ]
    return fixture


def _fence(text: str) -> str:
    """Wrap text in a markdown JSON fence."""
    return f"```json\n{text}\n```"


def _with_prose(text: str) -> str:
    """Wrap JSON in leading and trailing prose."""
    return f"Here is the response:\n\n{text}\n\nHope this helps!"


def _deterministic_vector(text: str) -> list[float]:
    """Return a stable 1536-dimensional vector seeded by ``text``."""
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


class TestAIMessageParsing(unittest.TestCase):
    """Offline parsing tests for AIMessage.get_parsed_response."""

    def test_intent_markdown_fenced_json(self):
        """Fenced JSON for the intent schema parses correctly."""
        raw = _fence(json.dumps(_intent_fixture()))
        parsed = AIMessage(raw_response=raw).get_parsed_response(
            INTENT_GENERATION_SCHEMA
        )
        self.assertEqual(
            parsed["query_analysis"]["original_query"],
            "why do bad things happen",
        )

    def test_intent_prose_wrapped_json(self):
        """JSON surrounded by prose for the intent schema parses correctly."""
        raw = _with_prose(json.dumps(_intent_fixture()))
        parsed = AIMessage(raw_response=raw).get_parsed_response(
            INTENT_GENERATION_SCHEMA
        )
        self.assertEqual(parsed["intents"][0]["intent_id"], "theological")

    def test_intent_invalid_confidence_raises(self):
        """A confidence value above 1.0 raises ValueError."""
        fixture = _intent_fixture()
        fixture["intents"][0]["confidence"] = 1.5
        raw = json.dumps(fixture)
        with self.assertRaises(ValueError):
            AIMessage(raw_response=raw).get_parsed_response(
                INTENT_GENERATION_SCHEMA
            )

    def test_hyde_markdown_fenced_json(self):
        """Fenced JSON for the HyDE schema parses correctly."""
        raw = _fence(json.dumps(_hyde_fixture()))
        parsed = AIMessage(raw_response=raw).get_parsed_response(
            HYDE_GENERATION_SCHEMA
        )
        self.assertIn("hyde_document", parsed)
        self.assertGreater(len(parsed["hyde_document"]), 50)

    def test_hyde_prose_wrapped_json(self):
        """JSON surrounded by prose for the HyDE schema parses correctly."""
        raw = _with_prose(json.dumps(_hyde_fixture()))
        parsed = AIMessage(raw_response=raw).get_parsed_response(
            HYDE_GENERATION_SCHEMA
        )
        self.assertGreater(len(parsed["hyde_document"]), 50)


class TestLLMWrapperRetry(unittest.TestCase):
    """Offline retry tests for LLMWrapper."""

    def setUp(self):
        """Create a fresh fixture DB and a wrapper instance."""
        os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"
        self._tmp, self.db_path = _create_fixture_db()
        GlobalReferenceCache.reset(self.db_path)
        self.wrapper = LLMWrapper(self.db_path)
        self.session_uuid = self.wrapper.db.create_session(name="wrapper-test")

    def tearDown(self):
        """Close the wrapper and drop the temp directory."""
        try:
            self.wrapper.close()
        finally:
            self._tmp.cleanup()

    def _make_async_side_effect(self, responses):
        """Return an async side_effect that consumes ``responses`` in order."""
        async def _side_effect(*args, **kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return _side_effect

    def test_retry_two_failures_then_success(self):
        """Two transient failures followed by success yields one success row."""
        responses = [
            APIConnectionError("failure 1"),
            APIConnectionError("failure 2"),
            json.dumps(_intent_fixture()),
        ]

        with patch.object(
            self.wrapper,
            "_call_api_async",
            new_callable=AsyncMock,
            side_effect=self._make_async_side_effect(responses),
        ):
            with patch(
                "services.llm.wrapper.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                aimessage = asyncio.run(
                    self.wrapper.call_api(
                        "intent_generation",
                        "test prompt",
                        self.session_uuid,
                    )
                )

        self.assertEqual(aimessage.num_tries, 3)
        self.assertIsNotNone(aimessage.raw_response)

        rows = self.wrapper.db.get_messages_by_session_and_type(
            self.session_uuid, "intent_generation"
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["raw_response"])
        self.assertIsNone(rows[0]["error_text"])
        self.assertEqual(rows[0]["num_tries"], 3)

    def test_retry_persistent_failure_records_error(self):
        """Persistent transient failure raises MaxRetriesExceededError."""

        async def _always_fail(*args, **kwargs):
            raise APIConnectionError("persistent failure")

        with patch.object(
            self.wrapper,
            "_call_api_async",
            new_callable=AsyncMock,
            side_effect=_always_fail,
        ):
            with patch(
                "services.llm.wrapper.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                with self.assertRaises(MaxRetriesExceededError):
                    asyncio.run(
                        self.wrapper.call_api(
                            "intent_generation",
                            "test prompt",
                            self.session_uuid,
                        )
                    )

        rows = self.wrapper.db.get_messages_by_session_and_type(
            self.session_uuid, "intent_generation"
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["raw_response"])
        self.assertIsNotNone(rows[0]["error_text"])
        # num_tries starts at 1 and is incremented once per attempt,
        # including the final failed attempt.
        self.assertEqual(rows[0]["num_tries"], 4)


class TestEmbeddingServiceRetry(unittest.TestCase):
    """Offline retry test for EmbeddingService."""

    def setUp(self):
        """Create a fresh fixture DB and point the cache at it."""
        os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"
        self._tmp, self.db_path = _create_fixture_db()
        GlobalReferenceCache.reset(self.db_path)

    def tearDown(self):
        """Drop the temp directory."""
        self._tmp.cleanup()

    def test_retry_two_failures_then_success(self):
        """Two injected failures followed by success returns correct vectors."""
        state = {"calls": 0}

        def embed_fn(texts: list[str]) -> list[list[float]]:
            state["calls"] += 1
            if state["calls"] <= 2:
                raise APIConnectionError(f"injected failure #{state['calls']}")
            return [_deterministic_vector(text) for text in texts]

        with patch(
            "services.embeddings.service.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            service = EmbeddingService(self.db_path, embed_fn=embed_fn)
            result = asyncio.run(service.embed_texts(["first", "second"]))
            service.close()

        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], _deterministic_vector("first"))
        self.assertEqual(result[1], _deterministic_vector("second"))


class TestHydePartialFailure(unittest.TestCase):
    """Offline test for HydeService mixed success/failure."""

    def setUp(self):
        """Create a fresh fixture DB and a HydeService instance."""
        os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"
        self._tmp, self.db_path = _create_fixture_db()
        GlobalReferenceCache.reset(self.db_path)
        self.service = HydeService(self.db_path)
        self.session_uuid = self.service.db.create_session(name="hyde-test")

    def tearDown(self):
        """Close the underlying wrapper and drop the temp directory."""
        try:
            self.service.llm.close()
        finally:
            self._tmp.cleanup()

    async def _hyde_call_api_async_mock(self, *args, **kwargs):
        """Fail the call that contains the comfort intent, succeed the other."""
        prompt = kwargs.get("prompt", "")
        if INTENT_ONE["intent_id"] in prompt:
            raise APIConnectionError("simulated hyde failure")
        return json.dumps({"hyde_document": LONG_HYDE_DOC})

    def test_one_success_one_failure_records_error_row(self):
        """One intent succeeds and one fails; result is mixed, DB has error row."""
        with patch.object(
            self.service.llm,
            "_call_api_async",
            new_callable=AsyncMock,
            side_effect=self._hyde_call_api_async_mock,
        ):
            with patch(
                "services.llm.wrapper.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                result = asyncio.run(
                    self.service.generate_for_intents(
                        [INTENT_ONE, INTENT_TWO], self.session_uuid
                    )
                )

        self.assertEqual(len(result), 2)
        docs = [r for r in result if r.get("hyde_document") is not None]
        errors = [r for r in result if r.get("hyde_document") is None]
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(docs[0]["intent_id"], "trust")
        self.assertEqual(errors[0]["intent_id"], "comfort")
        self.assertIn("error", errors[0])

        rows = self.service.db.get_messages_by_session_and_type(
            self.session_uuid, "hyde_generation"
        )
        self.assertEqual(len(rows), 2)
        error_rows = [r for r in rows if r["error_text"] is not None]
        self.assertEqual(len(error_rows), 1)


class TestIntentSchemaBoundary(unittest.TestCase):
    """Boundary tests for the number of intents in INTENT_GENERATION_SCHEMA."""

    def test_one_intent_passes(self):
        """A single intent satisfies minItems."""
        validate(instance=_with_intents(1), schema=INTENT_GENERATION_SCHEMA)

    def test_five_intents_passes(self):
        """Five intents satisfies maxItems."""
        validate(instance=_with_intents(5), schema=INTENT_GENERATION_SCHEMA)

    def test_zero_intents_fails(self):
        """Zero intents fails minItems."""
        with self.assertRaises(ValidationError):
            validate(instance=_with_intents(0), schema=INTENT_GENERATION_SCHEMA)

    def test_six_intents_fails(self):
        """Six intents fails maxItems."""
        with self.assertRaises(ValidationError):
            validate(instance=_with_intents(6), schema=INTENT_GENERATION_SCHEMA)


def run_tests():
    """Run all consolidated offline tests and report results."""
    print("Running consolidated offline pipeline step tests...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestAIMessageParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestLLMWrapperRetry))
    suite.addTests(loader.loadTestsFromTestCase(TestEmbeddingServiceRetry))
    suite.addTests(loader.loadTestsFromTestCase(TestHydePartialFailure))
    suite.addTests(loader.loadTestsFromTestCase(TestIntentSchemaBoundary))

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
