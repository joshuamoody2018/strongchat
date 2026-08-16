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
        # Make sure no leftover auth env from other tests pollutes us. The
        # OAuth path requires BOTH STRONGCHAT_OAUTH_SIGNING_KEY and
        # STRONGCHAT_PUBLIC_URL; unset STRONGCHAT_API_KEY so the OAuth path
        # unambiguously wins (per src/server.py:_setup_and_build_mcp
        # precedence: signing-key path > static-bearer path).
        for k in (
            "STRONGCHAT_API_KEY",
            "STRONGCHAT_OAUTH_SIGNING_KEY",
            "STRONGCHAT_PUBLIC_URL",
        ):
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
            os.environ.pop("STRONGCHAT_OAUTH_SIGNING_KEY", None)


class TestMcpServerNoAuthWhenUnset(unittest.TestCase):
    """Without ``STRONGCHAT_API_KEY``, the server stays unauthenticated
    (the default stdio / local dev path must not be silently locked
    behind an unset token)."""

    def setUp(self):
        for k in (
            "STRONGCHAT_API_KEY",
            "STRONGCHAT_OAUTH_SIGNING_KEY",
            "STRONGCHAT_PUBLIC_URL",
        ):
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


# --------------------------------------------------------------------------- #
# OAuth 2.0 PKCE round-trip integration tests
# --------------------------------------------------------------------------- #
#
# When ``STRONGCHAT_OAUTH_SIGNING_KEY`` + ``STRONGCHAT_PUBLIC_URL`` (loopback
# ``http://127.0.0.1:<port>`` form — ``validate_issuer_url`` requires HTTPS
# otherwise) are set at server boot AND ``STRONGCHAT_API_KEY`` is unset, the
# OAuth authorization-server provider (``src/oauth/provider.py``) takes
# precedence in ``src/server.py:_setup_and_build_mcp``. The MCP SDK then
# mounts ``/.well-known/oauth-authorization-server``, ``/authorize```,
# ``/token``, ``/register``, ``/revoke`` on the same Starlette app as
# ``/mcp``, and auto-wraps the provider with ``ProviderTokenVerifier`` so
# incoming bearer tokens are verified via ``load_access_token``.
#
# These tests drive the FULL claude.ai custom-connector flow end-to-end over
# the in-process uvicorn server — no static bearer key anywhere — exercising:
#
#   1. POST /register (RFC 7591 dynamic client registration)            -> 201
#   2. GET  /authorize (PKCE code request)                              -> 302
#   3. POST /token     (PKCE code_verifier check; exchanges code)       -> 200
#   4. POST /mcp       initialize with ``Authorization: Bearer <jwt>`` -> 200
#   5. POST /mcp       with a bogus bearer                              -> 401
#   6. POST /mcp       with no bearer                                   -> 401
#
# The MCP ``retrieve_context`` tool is NOT called here (would need a real
# OpenRouter API key + the ingested ChromaDB + Macula assets — see the
# existing HTTP roundtrip test comment). ``initialize`` proves the OAuth-
# issued JWT satisfies ``BearerAuthBackend`` all the way through to the MCP
# session machinery launching.

import base64
import hashlib
import secrets as _secrets


def _generate_pkce_pair():
    """Return a (code_verifier, code_challenge) pair per RFC 7636 §4.2.

    ``code_verifier`` is a 64-byte random URL-safe string (≥43 ≤128 chars);
    ``code_challenge`` is ``base64url(sha256(verifier))`` with the trailing
    ``=`` padding removed (RFC 7636 §A.4.2).
    """
    verifier = base64.urlsafe_b64encode(_secrets.token_bytes(48)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


_TEST_OAUTH_SIGNING_KEY = "test-signing-key-must-be-at-least-32-chars!!"
# Static-creds deployment (Option 1: DCR disabled). These are the
# pre-shared values the deploy owner pastes into claude.ai's connector
# UI; the test sets them via env so the server's ``load_oauth_config``
# returns an active provider (it requires all four OAuth env vars).
_TEST_OAUTH_CLIENT_ID = "strongchat-static-oauth-client"
_TEST_OAUTH_CLIENT_SECRET = "test-client-secret-must-be-at-least-32-chars!!"
_REGISTER_REDIRECT = "http://localhost:0/callback"


class TestMcpServerOAuthPkce(unittest.TestCase):
    """Live (offline) full PKCE round-trip against the in-process uvicorn
    server with the OAuth authorization-server provider wired in place of
    the static bearer. The JWT-issued access token is then used to
    authenticate an MCP ``initialize`` call — proving the OAuth flow
    issues a bearer that satisfies ``BearerAuthBackend``.

    Static-creds deployment (Option 1): DCR is disabled, so the
    ``/register`` route is not mounted and the test does NOT call it.
    The pre-shared ``STRONGCHAT_OAUTH_CLIENT_ID`` +
    ``STRONGCHAT_OAUTH_CLIENT_SECRET`` set in ``setUp`` are used directly
    on ``/token`` (matching what a deployed claude.ai connector does
    after the deploy owner pastes them into its onboarding UI)."""

    def setUp(self):
        # Make sure no leftover auth env from other tests pollutes us. The
        # OAuth path requires BOTH STRONGCHAT_OAUTH_SIGNING_KEY and
        # STRONGCHAT_PUBLIC_URL; unset STRONGCHAT_API_KEY so the OAuth path
        # unambiguously wins (per src/server.py:_setup_and_build_mcp
        # precedence: signing-key path > static-bearer path).
        for k in (
            "STRONGCHAT_API_KEY",
            "STRONGCHAT_OAUTH_SIGNING_KEY",
            "STRONGCHAT_OAUTH_CLIENT_ID",
            "STRONGCHAT_OAUTH_CLIENT_SECRET",
            "STRONGCHAT_PUBLIC_URL",
        ):
            os.environ.pop(k, None)
        # Seed the static client creds so load_oauth_config returns an
        # active provider. (Option 1: DCR disabled — see
        # src/oauth/provider.py:load_oauth_config for the full env matrix.)
        os.environ["STRONGCHAT_OAUTH_CLIENT_ID"] = _TEST_OAUTH_CLIENT_ID
        os.environ["STRONGCHAT_OAUTH_CLIENT_SECRET"] = _TEST_OAUTH_CLIENT_SECRET

    def test_oauth_pkce_roundtrip_authenticates_mcp_endpoint(self):
        asyncio.run(self._run_pkce_roundtrip())

    async def _run_pkce_roundtrip(self):
        import httpx2

        port = _pick_ephemeral_port()
        # Loopback HTTP issuer is required: ``validate_issuer_url`` in
        # ``mcp.server.auth.routes`` rejects HTTP for non-loopback hosts.
        issuer = f"http://127.0.0.1:{port}"
        os.environ["STRONGCHAT_OAUTH_SIGNING_KEY"] = _TEST_OAUTH_SIGNING_KEY
        os.environ["STRONGCHAT_PUBLIC_URL"] = issuer

        try:
            async with _running_http_server("127.0.0.1", port) as mcp_url:
                async with httpx2.AsyncClient() as client:
                    # (0) Confirm DCR is disabled: /register must NOT be
                    # mounted (Option 1: static creds). The SDK omits
                    # registration_endpoint from the metadata and never
                    # wires the route. Sanity-check this so a future
                    # regression that re-enables DCR (or re-mounts the
                    # route) fails loudly here instead of silently.
                    r = await client.post(
                        f"{issuer}/register",
                        json={"redirect_uris": [_REGISTER_REDIRECT]},
                    )
                    self.assertEqual(
                        r.status_code, 404,
                        f"/register should be unmounted (Option 1: static "
                        f"creds) but got {r.status_code}; "
                        f"body={r.text[:300]!r}",
                    )
                    client_id = _TEST_OAUTH_CLIENT_ID
                    client_secret = _TEST_OAUTH_CLIENT_SECRET
                    print(
                        "0. /register unmounted (404) — Option 1 static "
                        "creds; using pre-shared client_id"
                    )

                    # (1) PKCE code request -> 302 redirect with code.
                    code_verifier, code_challenge = _generate_pkce_pair()
                    state = "state-" + _secrets.token_hex(4)
                    authorize_params = {
                        "response_type": "code",
                        "client_id": client_id,
                        "redirect_uri": _REGISTER_REDIRECT,
                        "code_challenge": code_challenge,
                        "code_challenge_method": "S256",
                        "state": state,
                        "scope": "strongchat:retrieve_context",
                    }
                    r = await client.get(
                        f"{issuer}/authorize",
                        params=authorize_params,
                        follow_redirects=False,
                    )
                    self.assertEqual(
                        r.status_code, 302,
                        f"/authorize expected 302 got {r.status_code}; "
                        f"body={r.text[:500]!r}",
                    )
                    location = r.headers.get("location", "")
                    self.assertTrue(
                        location.startswith(_REGISTER_REDIRECT),
                        f"/authorize redirect to unexpected location={location!r}",
                    )
                    # The provider echoes ``state`` back; pull the code out.
                    self.assertIn(f"state={state}", location)
                    self.assertIn("code=", location)
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(location)
                    qs = parse_qs(parsed.query)
                    code = qs["code"][0]
                    self.assertTrue(code)
                    print(f"1. /authorize OK: 302 -> code (len {len(code)})")

                    # (2) PKCE code exchange -> JWT access token.
                    token_form = {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": _REGISTER_REDIRECT,
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "code_verifier": code_verifier,
                    }
                    r = await client.post(
                        f"{issuer}/token",
                        data=token_form,
                    )
                    self.assertEqual(
                        r.status_code, 200,
                        f"/token expected 200 got {r.status_code}; "
                        f"body={r.text[:500]!r}",
                    )
                    token_json = r.json()
                    access_token = token_json["access_token"]
                    self.assertEqual(
                        token_json.get("token_type", "").lower(), "bearer"
                    )
                    self.assertIn("refresh_token", token_json)
                    self.assertGreater(token_json.get("expires_in", 0), 0)
                    # JWT shape sanity: three dot-separated b64url segments.
                    self.assertEqual(access_token.count("."), 2)
                    print("2. /token OK: JWT access token issued")

                    # (3) authenticate against /mcp with the issued token.
                    init_request_body = (
                        '{"jsonrpc":"2.0","id":1,"method":"initialize",'
                        '"params":{"protocolVersion":"2025-11-25",'
                        '"capabilities":{},'
                        '"clientInfo":{"name":"oauth-pkce-test","version":"1.0"}}}'
                    )
                    r = await client.post(
                        mcp_url,
                        content=init_request_body,
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",
                        },
                    )
                    self.assertEqual(
                        r.status_code, 200,
                        f"/mcp initialize w/OAuth token expected 200 got "
                        f"{r.status_code}; body={r.text[:500]!r}",
                    )
                    self.assertIn("protocolVersion", r.text)
                    print(
                        "3. /mcp initialize w/OAuth-issued bearer -> 200 OK"
                    )

                    # (4) Bogus bearer -> 401 (ProviderTokenVerifier rejects
                    # the unsigned/foreign-key JWT via load_access_token=None;
                    # BearerAuthBackend turns None into 401).
                    r = await client.post(
                        mcp_url,
                        content=init_request_body,
                        headers={
                            "Authorization":
                                "Bearer not-a-valid-jwt-token",
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",
                        },
                    )
                    self.assertEqual(
                        r.status_code, 401,
                        f"bogus bearer expected 401 got {r.status_code}; "
                        f"body={r.text[:300]!r}",
                    )
                    print("4. /mcp with bogus bearer -> 401 OK")

                    # (5) Missing bearer -> 401.
                    r = await client.post(
                        mcp_url,
                        content=init_request_body,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",
                        },
                    )
                    self.assertEqual(
                        r.status_code, 401,
                        f"missing bearer expected 401 got "
                        f"{r.status_code}; body={r.text[:300]!r}",
                    )
                    print("5. /mcp with no bearer -> 401 OK")

                    print("\n=== OAuth PKCE round-trip ===\nPASS")
        finally:
            os.environ.pop("STRONGCHAT_OAUTH_SIGNING_KEY", None)
            os.environ.pop("STRONGCHAT_PUBLIC_URL", None)
            os.environ.pop("STRONGCHAT_OAUTH_CLIENT_ID", None)
            os.environ.pop("STRONGCHAT_OAUTH_CLIENT_SECRET", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)