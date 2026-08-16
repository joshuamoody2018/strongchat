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
        # No progress callback wired -> the fake runner must NOT have
        # recorded any progress events.
        self.assertIsNone(runner.last_progress)
        self.assertEqual(runner.progress_events, [])

    def test_progress_callback_is_forwarded_to_runner(self):
        """A ``progress`` arg passed to retrieve_context_impl is forwarded
        to PipelineRunner.run and the runner calls it. This proves the MCP
        tool wrapper's ``ctx.report_progress`` plumbing reaches the
        pipeline without needing a live JSON-RPC round-trip."""
        fake_result = _make_pipeline_result()
        runner = _FakeRunner(fake_result)
        captured: list[tuple[str, str, object, object]] = []

        async def cb(stage, message, done=None, total=None):
            captured.append((stage, message, done, total))

        with patch.object(server, "_get_runner", return_value=runner):
            asyncio.run(
                server.retrieve_context_impl(
                    query="q", translations=["kjv"], progress=cb
                )
            )

        # The fake runner fires one synthetic ``intent`` event when a
        # callback is wired; prove the impl actually forwarded ``cb``.
        self.assertIs(runner.last_progress, cb)
        self.assertEqual(runner.progress_events, [("intent", "fake intent", 1.0, 1.0)])
        self.assertEqual(captured, [("intent", "fake intent", 1.0, 1.0)])

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
        self.last_progress = None
        # Record every (stage, message, progress, total) tuple the runner
        # forwards so tests can assert the progress callback is wired.
        self.progress_events: list[tuple[str, str, object, object]] = []

    async def run(self, *, query, top_k, translations, progress=None):
        self.last_translations = tuple(translations)
        self.last_progress = progress

        # If the impl wired a progress callback, fire one synthetic event
        # so tests can assert the callback is forwarded end-to-end. The
        # real PipelineRunner fires these at each stage; the fake one
        # only needs to prove the impl plumbed the callback through.
        if progress is not None:
            try:
                await progress("intent", "fake intent", 1.0, 1.0)
                self.progress_events.append(("intent", "fake intent", 1.0, 1.0))
            except Exception:
                pass

        return self._result


class TestTransportSelection(unittest.TestCase):
    """Offline tests for the stdio/http transport selection in src/server.py.

    Runs entirely offline (never starts uvicorn or stdio); only checks that
    argv/env precedence resolves to the expected ``(transport, host, port)``
    tuple and that unknown values fall back to safe defaults.
    """

    def setUp(self):
        # Snapshot env so we can mutate + restore cleanly.
        self._env = os.environ.copy()
        # Clear STRONGCHAT_* controls so tests don't inherit host state.
        for k in ("STRONGCHAT_MCP_TRANSPORT", "STRONGCHAT_HOST", "STRONGCHAT_PORT"):
            os.environ.pop(k, None)
        # argv reset: patch out sys.argv into each test's value.
        self._argv = sys.argv

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        sys.argv = self._argv

    def _set_argv(self, *args):
        sys.argv = ["src/server.py", *args]

    def test_defaults_to_stdio(self):
        self._set_argv()
        self.assertEqual(server._select_transport(), ("stdio", "127.0.0.1", 8765))

    def test_env_selects_http_with_host_port(self):
        os.environ["STRONGCHAT_MCP_TRANSPORT"] = "http"
        os.environ["STRONGCHAT_HOST"] = "0.0.0.0"
        os.environ["STRONGCHAT_PORT"] = "9000"
        self._set_argv()
        self.assertEqual(server._select_transport(),
                         ("http", "0.0.0.0", 9000))

    def test_argv_overrides_env(self):
        os.environ["STRONGCHAT_MCP_TRANSPORT"] = "http"
        os.environ["STRONGCHAT_PORT"] = "9000"
        self._set_argv("--transport", "stdio")
        self.assertEqual(server._select_transport(),
                         ("stdio", "127.0.0.1", 9000))

    def test_unknown_transport_falls_back_to_stdio(self):
        os.environ["STRONGCHAT_MCP_TRANSPORT"] = "weird-thing"
        self._set_argv()
        self.assertEqual(server._select_transport()[0], "stdio")

    def test_http_explicit_argv(self):
        self._set_argv("--transport", "http", "--host", "127.0.0.1",
                       "--port", "8888")
        self.assertEqual(server._select_transport(),
                         ("http", "127.0.0.1", 8888))


if __name__ == "__main__":
    unittest.main(verbosity=2)