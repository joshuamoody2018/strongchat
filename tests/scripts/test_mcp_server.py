#!/usr/bin/env python3
"""Offline tests for the MCP server tool functions.

Invokes ``retrieve_context_impl`` and ``validate_answer_impl`` directly
(no stdio round-trip). Mocks PipelineRunner.run so no real OpenRouter /
ChromaDB calls are made. Asserts on the returned bundle shape.
"""

import asyncio
import os
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-mcp-tests"

import server  # noqa: E402
from services.pipeline.runner import IntentTrace, PipelineResult  # noqa: E402


def _make_pipeline_result() -> PipelineResult:
    """Build a minimal PipelineResult for mocking."""
    trace = IntentTrace(
        intent_id="comfort",
        intent_data={"intent_id": "comfort", "interpretation": "x"},
        hyde_document="hyde",
        search_results={
            "kjv": [
                {
                    "id": "k1",
                    "text": "for god so loved",
                    "reference": "John 3:16",
                    "distance": 0.0,
                    "context_bundle": {
                        "reference": "John 3:16",
                        "kept_words": [],
                        "scored_words": [],
                        "kept_word_count": 0,
                        "scored_word_count": 0,
                        "unique_word_count": 0,
                        "build_summary": "(mock)",
                    },
                }
            ],
            "web": [],
        },
    )
    return PipelineResult(
        session_uuid="corr-mcp-1",
        query="why",
        traces={"comfort": trace},
        query_analysis={"original_query": "why"},
    )


class TestRetrieveContextTool(unittest.TestCase):
    """Offline tests for the retrieve_context tool function."""

    def setUp(self):
        # Reset the module-level singleton runner so the next call rebuilds.
        server._RUNNER = None

    def test_retrieve_context_returns_bundle(self):
        """Calling retrieve_context_impl returns the serialized bundle dict."""
        fake_result = _make_pipeline_result()

        with patch.object(
            server, "_get_runner", return_value=_FakeRunner(fake_result)
        ):
            bundle = asyncio.run(
                server.retrieve_context_impl(
                    query="why do bad things happen",
                    top_k=5,
                    translations=["kjv"],
                )
            )

        self.assertEqual(bundle["correlation_id"], "corr-mcp-1")
        self.assertEqual(bundle["query"], "why")
        self.assertEqual(len(bundle["traces"]), 1)
        trace = bundle["traces"][0]
        self.assertEqual(trace["intent_id"], "comfort")
        self.assertIn("kjv", trace["search_results"])
        hit = trace["search_results"]["kjv"][0]
        self.assertIn("context_bundle", hit)
        # Embeddings must never be surfaced to the calling agent.
        self.assertNotIn("embedding", hit)

    def test_default_translations_when_none(self):
        """Passing translations=None defaults to ['kjv', 'web']."""
        fake_result = _make_pipeline_result()
        runner = _FakeRunner(fake_result)

        with patch.object(server, "_get_runner", return_value=runner):
            asyncio.run(
                server.retrieve_context_impl(query="q", translations=None)
            )

        self.assertEqual(runner.last_translations, ("kjv", "web"))

    def test_validate_answer_stub_raises_not_implemented(self):
        """The validate_answer tool raises NotImplementedError until built."""
        with self.assertRaises(NotImplementedError):
            asyncio.run(
                server.validate_answer_impl(
                    answer="synthesized answer",
                    context={"correlation_id": "x", "traces": []},
                )
            )

    def test_validate_answer_error_documents_contract(self):
        """The error message documents the planned return shape for agents."""
        try:
            asyncio.run(
                server.validate_answer_impl(
                    answer="x", context={"correlation_id": "x", "traces": []}
                )
            )
        except NotImplementedError as exc:
            msg = str(exc)
            self.assertIn("valid", msg)
            self.assertIn("unsupported_claims", msg)
            self.assertIn("missing_coverage", msg)
            self.assertIn("suggested_refinement", msg)
            return
        self.fail("validate_answer_impl did not raise NotImplementedError")


class _FakeRunner:
    """Minimal stand-in for PipelineRunner capturing the last call."""

    def __init__(self, result):
        self._result = result
        self.last_translations = None

    async def run(self, *, query, top_k, translations):
        self.last_translations = tuple(translations)
        return self._result


if __name__ == "__main__":
    unittest.main(verbosity=2)