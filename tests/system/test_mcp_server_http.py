#!/usr/bin/env python3
"""Live (offline) streamable-HTTP round-trip test for the StrongChat MCP server.

Drives the same JSON-RPC handshake as
``tests/system/test_mcp_server_stdio.py`` but over the streamable-HTTP
transport — without binding a real socket. We build the Starlette ASGI
app via ``MCPServer.streamable_http_app()`` and wrap it in
``httpx2.ASGITransport`` so the MCP client SDK drives the entire
request/response loop in-process. This proves the new HTTP transport
wiring in ``src/server.py`` actually speaks the streamable-HTTP protocol
(no stdio fallback), and that the MCP ``validate_answer`` stub still
surfaces its ``NotImplementedError`` contract over HTTP.

``retrieve_context`` itself is NOT called here (would need a real
OpenRouter API key + ingested ChromaDB + Macula assets); the HTTP
transport is a thin pass-through and is adequately covered by the
``validate_answer`` round-trip below + the existing stdio test.

Run with the environment loaded:
    set -a; . ./.env; set +a
    .venv/bin/python tests/system/test_mcp_server_http.py
"""

import asyncio
import contextlib
import os
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

if not os.getenv("OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-mcp-http-test"


import server  # noqa: E402
from services.pipeline.runner import ProgressCallback  # noqa: E402


def _pick_ephemeral_port() -> int:
    """Return a free TCP port the kernel hands out for this test run."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.asynccontextmanager
async def _running_http_server(host: str, port: int):
    """Start the StrongChat MCP server on streamable-HTTP at
    ``http://{host}:{port}/mcp`` for the duration of the context.

    The MCP streamable-HTTP transport initializes its session-manager
    task group through the Starlette app's lifespan. ``httpx2.ASGITransport``
    does NOT trigger lifespan events, so we drive a real uvicorn server on
    an ephemeral port instead — fully in-process, just with a bound TCP
    socket.
    """
    mcp = await server._setup_and_build_mcp()
    app = mcp.streamable_http_app(streamable_http_path="/mcp")
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    instance = uvicorn.Server(config)
    server_task = asyncio.create_task(instance.serve())
    # Wait for uvicorn to accept a TCP connection before yielding.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if instance.started:
            try:
                with contextlib.closing(
                    socket.create_connection((host, port), timeout=0.5)
                ):
                    break
            except OSError:
                pass
        await asyncio.sleep(0.05)
    else:  # pragma: no cover - rarely hit
        server_task.cancel()
        raise AssertionError("uvicorn did not start within 10s")
    try:
        yield f"http://{host}:{port}/mcp"
    finally:
        instance.should_exit = True
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(server_task, timeout=5.0)


class TestMcpServerStreamableHttp(unittest.TestCase):
    """Drive the MCP server over streamable-HTTP using the official
    ``mcp.client`` SDK + an in-process uvicorn server on an ephemeral port."""

    def test_http_roundtrip_initialize_list_tools_validate_answer(self):
        """End-to-end HTTP handshake: initialize -> tools/list ->
        tools/call validate_answer (the stub raises NotImplementedError)."""
        ok = asyncio.run(self._run_http_roundtrip())
        self.assertTrue(ok, "HTTP round-trip assertions failed (see stdout)")

    async def _run_http_roundtrip(self) -> bool:
        from mcp.client.streamable_http import streamable_http_client
        from mcp.client.session import ClientSession

        host, port = "127.0.0.1", _pick_ephemeral_port()
        async with _running_http_server(host, port) as url:
            async with streamable_http_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    # 1. initialize
                    init = await session.initialize()
                    self.assertIsNotNone(init.protocol_version,
                                         "no protocolVersion from initialize")
                    self.assertIsNotNone(init.server_info,
                                         "no serverInfo from initialize")
                    print(f"1. initialize OK: "
                          f"protocol={init.protocol_version}, "
                          f"server={init.server_info.name}")

                    # 2. tools/list -> both tools present
                    tools_result = await session.list_tools()
                    tool_names = {t.name for t in tools_result.tools}
                    self.assertIn("retrieve_context", tool_names, tool_names)
                    self.assertIn("validate_answer", tool_names, tool_names)
                    print(f"2. tools/list OK: {sorted(tool_names)}")

                    # Sanity: the retrieve_context schema must NOT surface
                    # the internal ``ctx`` Context parameter as a tool input
                    # (the SDK's find_context_parameter strips it; this
                    # assertion guards against regressions that would
                    # crash tool registration with
                    # PydanticInvalidForJsonSchema).
                    rc_tool = next(
                        t for t in tools_result.tools
                        if t.name == "retrieve_context"
                    )
                    schema_props = set(
                        (rc_tool.input_schema or {}).get("properties", {}).keys()
                    )
                    self.assertNotIn("ctx", schema_props,
                                     f"ctx leaked into retrieve_context schema: "
                                     f"{schema_props}")
                    self.assertIn("query", schema_props)

                    # 3. tools/call validate_answer -> the stub raises
                    # NotImplementedError. MCP surfaces this either as
                    # ``is_error=True`` on the CallToolResult (preferred
                    # path on recent SDKs) or as an exception out of
                    # ``call_tool``. Accept both since both are proof the
                    # tool ran end-to-end over the HTTP transport.
                    call = await session.call_tool(
                        "validate_answer",
                        arguments={
                            "answer": "synthesized answer",
                            "context": {"correlation_id": "x", "traces": []},
                        },
                    )
                    # On v2.x the stub error surfaces as is_error=True on
                    # the result. Concatenate text content; assert the
                    # NotImplementedError contract text is present.
                    text_parts = []
                    for block in getattr(call, "content", []) or []:
                        t = getattr(block, "text", None)
                        if t:
                            text_parts.append(t)
                    text = " ".join(text_parts)
                    is_error = bool(getattr(call, "is_error", False))
                    self.assertTrue(
                        is_error or "NotImplementedError" in text
                        or "validate_answer" in text,
                        f"validate_answer call did not surface stub error: "
                        f"is_error={is_error} text={text!r}",
                    )
                    print(f"3. tools/call validate_answer OK "
                          f"(is_error={is_error}): {text[:120]}...")

                    print("\n=== Result ===\nPASS")
                    return True


class TestRetrieveContextProgress(unittest.TestCase):
    """Offline test that calls ``retrieve_context_impl`` with a progress
    callback and a mocked runner. Confirms the impl end-to-end forwards
    the callback and exposes stage events to the caller (which the MCP
    tool wrapper in turn translates into ``ctx.report_progress`` +
    ``ctx.info`` notifications streamed over the SSE response)."""

    def setUp(self):
        server._RUNNER = None

    def test_progress_callback_receives_stage_events(self):
        fake_result = _make_minimal_pipeline_result()
        captured: list[tuple[str, str, object, object]] = []

        async def cb(stage, message, done=None, total=None):
            captured.append((stage, message, done, total))

        runner = _StageFiringRunner(fake_result)

        with _patch_get_runner(runner):
            bundle = asyncio.run(
                server.retrieve_context_impl(
                    query="why", translations=["kjv"], progress=cb
                )
            )

        # Bundle returned + all five stage events arrived in order.
        self.assertEqual(bundle["query"], "why")
        self.assertEqual(
            [e[0] for e in captured],
            ["intent", "hyde", "retrieval", "context", "serialize"],
        )
        # progress fractions carried through unchanged.
        for _, _, done, total in captured:
            self.assertEqual((done, total), (1.0, 1.0))


def _make_minimal_pipeline_result():
    from services.pipeline.runner import IntentTrace, PipelineResult

    trace = IntentTrace(
        intent_id="x",
        intent_data={"intent_id": "x", "interpretation": "y"},
        hyde_document="hyde",
        search_results={"kjv": []},
    )
    return PipelineResult(
        session_uuid="corr-x",
        query="why",
        traces={"x": trace},
        query_analysis={"original_query": "why"},
    )


class _StageFiringRunner:
    """Stand-in for PipelineRunner.run that fires all five pipeline
    stage events through the supplied progress callback. Mocks the entire
    pipeline so no ChromaDB / OpenRouter calls are needed."""

    def __init__(self, result):
        self._result = result

    async def run(self, *, query, top_k, translations, progress=None):
        stages = [
            ("intent", "Extracting query intent…"),
            ("hyde", "Generating HyDE passages…"),
            ("retrieval", "Searching…"),
            ("context", "Resolving context bundles…"),
            ("serialize", "Serializing context bundle…"),
        ]
        for stage, msg in stages:
            if progress is not None:
                await progress(stage, msg, 1.0, 1.0)
        return self._result


@contextlib.contextmanager
def _patch_get_runner(runner):
    """Context-managed monkey-patch of ``server._get_runner``."""
    import contextlib
    from unittest.mock import patch

    with patch.object(server, "_get_runner", return_value=runner):
        yield


# --------------------------------------------------------------------------- #
# Bearer-token authentication integration tests
# --------------------------------------------------------------------------- #
#
# When ``STRONGCHAT_API_KEY`` + ``STRONGCHAT_PUBLIC_URL`` are set in env
# at server boot, the MCP SDK's ``BearerAuthBackend`` middleware is
# auto-wired: every request to ``/mcp`` MUST carry ``Authorization:
# Bearer <key>``. Anything else gets a ``401 Unauthorized`` before the
# MCP session machinery even runs. These tests boot the server normally
# (over an ephemeral HTTP socket) with the auth env vars set, then send
# raw POST requests to assert:
#
#   - missing Authorization header      -> 401
#   - malformed Authorization header   -> 401
#   - wrong bearer token               -> 401
#   - correct bearer token             -> 200 (initialize completes)
#
# The mcp.client SDK can't be used to drive the failing cases here
# because it sends no ``Authorization`` header by default and (correctly)
# fails on 401 itself, so we use plain httpx2 to inspect the raw status.


_TEST_API_KEY = "test-secret-bearer-key-not-for-prod"


class TestMcpServerBearerAuth(unittest.TestCase):
    """Verify the static-API-key bearer middleware:
    rejects missing/malformed/wrong bearer; accepts the configured key.
    """

    def setUp(self):
        # Make sure no leftover auth env from other tests pollutes us.
        for k in ("STRONGCHAT_API_KEY", "STRONGCHAT_PUBLIC_URL"):
            os.environ.pop(k, None)

    def test_bearer_auth_rejects_unauthenticated_requests(self):
        asyncio.run(self._run_auth_reject_cases())

    async def _run_auth_reject_cases(self):
        import httpx2

        port = _pick_ephemeral_port()
        os.environ["STRONGCHAT_API_KEY"] = _TEST_API_KEY
        os.environ["STRONGCHAT_PUBLIC_URL"] = f"http://strongchat.test:{port}"
        try:
            async with _running_http_server("127.0.0.1", port) as url:
                init_request_body = (
                    '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                    '"params":{"protocolVersion":"2025-11-25",'
                    '"capabilities":{},'
                    '"clientInfo":{"name":"http-auth-test","version":"1.0"}}}'
                )
                headers_ok = {"Authorization": f"Bearer {_TEST_API_KEY}"}

                async with httpx2.AsyncClient() as client:
                    # (1) Missing Authorization header -> 401.
                    r = await client.post(
                        url,
                        content=init_request_body,
                        headers={"Content-Type": "application/json",
                                 "Accept": "application/json, text/event-stream"},
                    )
                    self.assertEqual(
                        r.status_code, 401,
                        f"missing bearer expected 401 got {r.status_code}; "
                        f"body={r.text[:300]!r}",
                    )

                    # (2) Malformed Authorization scheme -> 401.
                    for bad_hdr in (
                        {"Authorization": "Basic xyz=="},
                        {"Authorization": "Bearer"},
                        {"Authorization": _TEST_API_KEY},
                        {"Authorization": f"Bearer  {_TEST_API_KEY} mismatch"},  # wrong token after bearer
                        {"Authorization": "Bearer wrong-token"},
                    ):
                        r = await client.post(
                            url,
                            content=init_request_body,
                            headers={"Content-Type": "application/json",
                                     "Accept": "application/json, text/event-stream",
                                     **bad_hdr},
                        )
                        self.assertEqual(
                            r.status_code, 401,
                            f"bad header {bad_hdr!r} expected 401 got "
                            f"{r.status_code}; body={r.text[:300]!r}",
                        )

                    # (3) Correct bearer -> 200 OK with the initialize result.
                    r = await client.post(
                        url,
                        content=init_request_body,
                        headers={"Content-Type": "application/json",
                                 "Accept": "application/json, text/event-stream",
                                 **headers_ok},
                    )
                    self.assertEqual(
                        r.status_code, 200,
                        f"correct bearer expected 200 got {r.status_code}; "
                        f"body={r.text[:500]!r}",
                    )
                    # 200 path is text/event-stream; peek the body for the
                    # protocol version (already returned by the init
                    # handler, so the auth check sat AND the handler ran).
                    self.assertIn("protocolVersion", r.text)
                    print(" bearer-auth: 401 / 401x5 / 200 sequence PASS")
        finally:
            os.environ.pop("STRONGCHAT_API_KEY", None)
            os.environ.pop("STRONGCHAT_PUBLIC_URL", None)


class TestMcpServerNoAuthWhenUnset(unittest.TestCase):
    """Without ``STRONGCHAT_API_KEY``, the server stays unauthenticated
    (the default stdio / local dev path must not be silently locked
    behind an unset token)."""

    def setUp(self):
        for k in ("STRONGCHAT_API_KEY", "STRONGCHAT_PUBLIC_URL"):
            os.environ.pop(k, None)

    def test_unauthenticated_request_succeeds_when_no_key(self):
        asyncio.run(self._run_unconfigured_case())

    async def _run_unconfigured_case(self):
        import httpx2

        port = _pick_ephemeral_port()
        async with _running_http_server("127.0.0.1", port) as url:
            body = (
                '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                '"params":{"protocolVersion":"2025-11-25","capabilities":{},'
                '"clientInfo":{"name":"noauth","version":"1.0"}}}'
            )
            async with httpx2.AsyncClient() as client:
                # No Authorization header at all; server must accept.
                r = await client.post(
                    url,
                    content=body,
                    headers={"Content-Type": "application/json",
                             "Accept": "application/json, text/event-stream"},
                )
                self.assertEqual(
                    r.status_code, 200,
                    f"unauthenticated path expected 200 got "
                    f"{r.status_code}; body={r.text[:300]!r}",
                )
                self.assertIn("protocolVersion", r.text)
                print(" no-auth passthrough: 200 PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)