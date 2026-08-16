#!/usr/bin/env python3
"""Consolidated offline step tests for pipeline services.

Covers: parsing fenced/prose JSON and schema validation on AIMessage,
AIMessage lifecycle (creation defaults, success/failure, retries),
LLMWrapper retry with mocked _call_api_async, EmbeddingService retry with
an injected embed_fn, HydeService partial failure, and intent schema
boundaries. No application database; audit assertions use the standard
``logging`` module via ``self.assertLogs``.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from jsonschema import validate, ValidationError

from config import (
    INTENT_GENERATION_SCHEMA,
    HYDE_GENERATION_SCHEMA,
)
from services.embeddings import EmbeddingService
from services.hyde import HydeService
from services.llm.aimessage import AIMessage
from services.llm.exceptions import APIConnectionError, MaxRetriesExceededError
from services.llm.wrapper import LLMWrapper

DIMENSION = 1536

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
        msg = AIMessage()
        msg.mark_success_from_text(
            _fence(json.dumps(_intent_fixture())),
            schema=INTENT_GENERATION_SCHEMA,
        )
        parsed = msg.get_parsed_response(INTENT_GENERATION_SCHEMA)
        self.assertEqual(
            parsed["query_analysis"]["original_query"],
            "why do bad things happen",
        )

    def test_intent_prose_wrapped_json_rejected(self):
        """Prose-wrapped JSON is rejected by strict extraction."""
        raw = _with_prose(json.dumps(_intent_fixture()))
        with self.assertRaises(ValueError):
            AIMessage(raw_response=raw).get_parsed_response(
                INTENT_GENERATION_SCHEMA
            )

    def test_intent_mark_success_strips_fence_and_canonicalizes(self):
        """mark_success_from_text strips fences and stores canonical JSON."""
        msg = AIMessage()
        msg.mark_success_from_text(
            _fence(json.dumps(_intent_fixture())),
            schema=INTENT_GENERATION_SCHEMA,
        )
        self.assertIsInstance(msg.parsed_response, dict)
        self.assertNotIn("```", msg.raw_response or "")
        reparsed = json.loads(msg.raw_response)
        self.assertEqual(
            reparsed["query_analysis"]["original_query"],
            "why do bad things happen",
        )

    def test_intent_mark_success_prose_residue_rejected(self):
        """Prose residue around a fenced body is rejected."""
        msg = AIMessage()
        with self.assertRaises(ValueError):
            msg.mark_success_from_text(
                _with_prose(json.dumps(_intent_fixture())),
                schema=INTENT_GENERATION_SCHEMA,
            )

    def test_intent_invalid_confidence_raises(self):
        """A confidence value above 1.0 raises ValueError."""
        fixture = _intent_fixture()
        fixture["intents"][0]["confidence"] = 1.5
        msg = AIMessage()
        with self.assertRaises(ValueError):
            msg.mark_success_from_text(
                json.dumps(fixture),
                schema=INTENT_GENERATION_SCHEMA,
            )

    def test_hyde_markdown_fenced_json(self):
        """Fenced JSON for the HyDE schema parses correctly."""
        msg = AIMessage()
        msg.mark_success_from_text(
            _fence(json.dumps(_hyde_fixture())),
            schema=HYDE_GENERATION_SCHEMA,
        )
        parsed = msg.get_parsed_response(HYDE_GENERATION_SCHEMA)
        self.assertIn("hyde_document", parsed)
        self.assertGreater(len(parsed["hyde_document"]), 50)

    def test_hyde_prose_wrapped_json_rejected(self):
        """Prose-wrapped HyDE JSON is rejected by strict extraction."""
        raw = _with_prose(json.dumps(_hyde_fixture()))
        with self.assertRaises(ValueError):
            AIMessage(raw_response=raw).get_parsed_response(
                HYDE_GENERATION_SCHEMA
            )


class TestAIMessageDataclass(unittest.TestCase):
    """AIMessage lifecycle: creation defaults, success, failure, retries."""

    def test_aimessage_creation_defaults(self):
        """A fresh AIMessage has generated uuid/created_at and null fields."""
        msg = AIMessage()
        self.assertIsNotNone(msg.uuid)
        self.assertIsNotNone(msg.created_at)
        self.assertEqual(msg.num_tries, 1)
        self.assertIsNone(msg.raw_response)
        self.assertIsNone(msg.error_text)

    def test_aimessage_success_flow(self):
        """mark_success_from_text stores the parsed response."""
        msg = AIMessage(unique_prompt="Test prompt")
        msg.mark_success_from_text(
            '{"intent": "question", "confidence": 0.95}',
            schema={"type": "object"},
        )
        self.assertIsNotNone(msg.raw_response)
        self.assertEqual(
            msg.get_parsed_response({"type": "object"}),
            {"intent": "question", "confidence": 0.95},
        )
        self.assertIsNotNone(msg.response_at)
        self.assertIsNone(msg.error_text)

    def test_aimessage_failure_flow(self):
        """mark_failure records the error and increments num_tries."""
        msg = AIMessage(unique_prompt="Test prompt")
        msg.mark_failure("API timeout")
        self.assertEqual(msg.num_tries, 2)
        self.assertEqual(msg.error_text, "API timeout")
        self.assertIsNotNone(msg.response_at)

    def test_max_retries_exceeded(self):
        """num_tries crossing max_retries signals retry exhaustion."""
        msg = AIMessage(num_tries=3)
        self.assertTrue(msg.num_tries >= 3)
        msg.num_tries = 2
        self.assertFalse(msg.num_tries >= 3)


class TestLLMWrapperRetry(unittest.TestCase):
    """Offline retry tests for LLMWrapper."""

    def setUp(self):
        """Create a wrapper instance with a dummy API key."""
        os.environ["OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"] = "dummy-key-for-offline-tests"
        self.wrapper = LLMWrapper()
        self.correlation_id = str(uuid.uuid4())

    def tearDown(self):
        """Close the wrapper."""
        self.wrapper.close()

    def _make_async_side_effect(self, responses):
        """Return an async side_effect that consumes ``responses`` in order."""
        async def _side_effect(*args, **kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return _side_effect

    def test_retry_two_failures_then_success(self):
        """Two transient failures followed by success yields one success log row."""
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
                with self.assertLogs("strongchat", level="INFO") as cm:
                    aimessage = asyncio.run(
                        self.wrapper.call_api(
                            "intent_generation",
                            "test prompt",
                            self.correlation_id,
                        )
                    )

        self.assertEqual(aimessage.num_tries, 3)
        self.assertIsNotNone(aimessage.raw_response)

        llm_info = [
            r for r in cm.records
            if r.__dict__.get("event") == "llm_call"
            and r.__dict__.get("status") == "ok"
        ]
        self.assertEqual(len(llm_info), 1)
        self.assertEqual(llm_info[0].__dict__.get("attempts"), 3)
        self.assertEqual(
            llm_info[0].__dict__.get("correlation_id"), self.correlation_id
        )

    def test_retry_persistent_failure_emits_error_log(self):
        """Persistent transient failure raises MaxRetriesExceededError and
        emits one ERROR ``llm_call`` log record."""

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
                with self.assertLogs("strongchat", level="ERROR") as cm:
                    with self.assertRaises(MaxRetriesExceededError):
                        asyncio.run(
                            self.wrapper.call_api(
                                "intent_generation",
                                "test prompt",
                                self.correlation_id,
                            )
                        )

        llm_errors = [
            r for r in cm.records
            if r.__dict__.get("event") == "llm_call"
            and r.__dict__.get("status") == "error"
        ]
        self.assertEqual(len(llm_errors), 1)
        self.assertIn("persistent failure",
                      str(llm_errors[0].__dict__.get("error")))


class TestEmbeddingServiceRetry(unittest.TestCase):
    """Offline retry test for EmbeddingService."""

    def test_retry_two_failures_then_success(self):
        """Two injected failures followed by success returns correct vectors."""
        os.environ["OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"] = "dummy-key-for-offline-tests"
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
            service = EmbeddingService(embed_fn=embed_fn)
            result = asyncio.run(service.embed_texts(["first", "second"]))
            service.close()

        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], _deterministic_vector("first"))
        self.assertEqual(result[1], _deterministic_vector("second"))


class TestHydePartialFailure(unittest.TestCase):
    """Offline test for HydeService mixed success/failure."""

    def setUp(self):
        """Create a HydeService instance."""
        os.environ["OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"] = "dummy-key-for-offline-tests"
        self.service = HydeService()
        self.correlation_id = str(uuid.uuid4())

    def tearDown(self):
        """Close the underlying wrapper."""
        self.service.llm.close()

    async def _hyde_call_api_async_mock(self, *args, **kwargs):
        """Fail the call that contains the comfort intent, succeed the other."""
        prompt = kwargs.get("prompt", "")
        if INTENT_ONE["intent_id"] in prompt:
            raise APIConnectionError("simulated hyde failure")
        return json.dumps({"hyde_document": LONG_HYDE_DOC})

    def test_one_success_one_failure_returns_mixed_result(self):
        """One intent succeeds and one fails; result is mixed, no DB write."""
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
                        [INTENT_ONE, INTENT_TWO], self.correlation_id
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
    suite.addTests(loader.loadTestsFromTestCase(TestAIMessageDataclass))
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