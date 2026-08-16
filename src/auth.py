"""Static-API-key bearer authentication for the StrongChat MCP server.

When exposed via streamable-HTTP (e.g. behind the included
``deploy/Caddyfile`` + sslip.io), the public MCP endpoint can be firewalled
behind a single static bearer token. This module wires the MCP SDK's own
``TokenVerifier`` + ``AuthSettings`` machinery onto that static key, so the
auth check uses the spec-correct OAuth 2.0 ``Bearer`` scheme that every
remote MCP client (opencode / Claude Desktop / a hosted custom-connector)
already speaks — without стояing up a full OAuth authorization-server
implementation.

Enabled by setting two env vars at server start:

* ``STRONGCHAT_API_KEY`` — the shared secret. When unset, the MCP server
  runs unauthenticated (correct for local stdio, local-only HTTP, or a
  network ACL'd HTTP exposure).
* ``STRONGCHAT_PUBLIC_URL`` — the public canonical base URL the server is
  reachable at (e.g. ``https://strongchat.foo.sslip.io``). Used as the
  OAuth ``issuer_url`` and ``resource_server_url`` so cross-checking
  clients don't reject us.

When both are set, ``static_key_auth_settings()`` returns a
``(auth_settings, token_verifier)`` pair that ``src/server.py`` passes
into ``MCPServer.__init__``. The SDK wires:

* ``BearerAuthBackend`` — Starlette middleware that OBLIGATELY returns
  ``401 Unauthorized`` on missing/malformed ``Authorization`` headers
  and on any token our verifier rejects.
* ``AuthContextMiddleware`` — pulls the verified ``AccessToken`` into
  the request context so the ``ServerRequestContext`` carries it.

## Important: claude.ai hosted custom-connector OAuth caveat

This static-key auth works for **any client that already has the bearer
token** (curl, opencode, Claude Desktop wired with the key in its config,
or any HTTP agent harness). It is **NOT** sufficient on its own for the
claude.ai web custom-connector to onboard and obtain a token, because
that flow expects OAuth 2.0 PKCE authorization-server metadata at
``GET /.well-known/oauth-authorization-server`` and a working token
endpoint. That requires an ``OAuthAuthorizationServerProvider`` (the
second SDK hook), which is out of scope for the static-key guard.

You have two deployment options if you must use the hosted claude.ai web
custom-connector specifically:

1. Stand up a separate OAuth authorization-server implementation that
   issues short-lived tokens keyed off claude.ai's developer portal
   client. The MCP `auth_server_provider` plug-in point lets the
   streamable-HTTP app expose the metadata + token endpoints from the
   same base URL. This is the spec-true path.

2. Use a different consumer (the Claude Desktop app, opencode, or any
   MCP client that lets you paste the bearer key into config) against
   the same public URL. The pipeline itself is unchanged.

We chose option 2 as the documented local-test path; the
``token_verifier`` hook remains so adding an ``auth_server_provider``
later is a strict additive change (one more constructor kwarg).
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# These names mirror what the rest of the project reaches for. We import
# them lazily inside the helpers so a pre-v2 SDK without the auth module
# degrades cleanly to "no auth configured" rather than crashing import.
_AUTH_AVAILABLE: Optional[bool] = None


def _check_auth_module() -> bool:
    """Detect whether the installed mcp SDK exposes the auth hooks we use."""
    global _AUTH_AVAILABLE
    if _AUTH_AVAILABLE is None:
        try:
            from mcp.server.auth.provider import TokenVerifier  # noqa: F401
            from mcp.server.auth.settings import AuthSettings  # noqa: F401
            from mcp.server.auth.types import AccessToken  # noqa: F401 (not strict)
            _AUTH_AVAILABLE = True
        except ImportError:
            try:
                from mcp.server.auth.provider import (
                    AccessToken as _AT,
                    TokenVerifier as _TV,
                )
                _AUTH_AVAILABLE = True
            except ImportError:
                _AUTH_AVAILABLE = False
    return _AUTH_AVAILABLE


class StaticBearerTokenVerifier:  # implements mcp.server.auth.provider.TokenVerifier
    """Verify ``Authorization: Bearer <key>`` against the
    ``STRONGCHAT_API_KEY`` env value.

    Constant-time comparison (``hmac.compare_digest``) so brute-force
    timing-leak attacks don't harvest the key. Returns an
    ``AccessToken`` carrying an opaque ``client_id`` on success, or
    ``None`` otherwise — the SDK's ``BearerAuthBackend`` turns ``None``
    into ``401 Unauthorized``.
    """

    #: Stable OAuth ``client_id`` we present to the SDK for any static-key
    #: caller. There is only ever one caller identity with a static key.
    STATIC_CLIENT_ID = "strongchat-static-bearer"

    def __init__(self, expected_key: str):
        if not expected_key:
            raise ValueError("STRONGCHAT_API_KEY must not be empty")
        # ``hmac.compare_digest`` requires equal-length bytes for some
        # implementations; pre-encode our expected key once.
        self._expected = expected_key.encode("utf-8")

    async def verify_token(self, token: str):
        """Verify a bearer token; return an ``AccessToken`` or ``None``.

        Satisfies the mcp SDK ``TokenVerifier`` Protocol (structural).
        """
        if token is None:
            return None
        candidate = token.encode("utf-8", "replace")
        if not hmac.compare_digest(candidate, self._expected):
            return None
        try:
            from mcp.server.auth.provider import AccessToken
        except ImportError:  # pragma: no cover - defensive
            return None
        return AccessToken(
            token=token,
            client_id=self.STATIC_CLIENT_ID,
            scopes=[],
            expires_at=None,
            resource=None,
            subject=None,
            claims=None,
        )


def load_static_bearer_config() -> Tuple[Optional[object], Optional[object]]:
    """Return ``(auth_settings, token_verifier)`` for ``MCPServer.__init__``.

    Both elements are ``None`` when either ``STRONGCHAT_API_KEY`` or
    ``STRONGCHAT_PUBLIC_URL`` is unset (auth is disabled — correct for
    stdio / local-only HTTP / ACL'd network exposure).

    On mismatch (only one of the two env vars set) we log a WARNING and
    disable auth — failing closed on misconfiguration rather than
    silently serving unauthenticated traffic on a public endpoint.
    """
    if not _check_auth_module():
        return None, None

    api_key = os.environ.get("STRONGCHAT_API_KEY", "").strip()
    public_url = os.environ.get("STRONGCHAT_PUBLIC_URL", "").strip()

    if not api_key and not public_url:
        # Default case: nothing configured -> no auth (stdio, local-only).
        return None, None

    if not api_key or not public_url:
        logger.warning(
            "STRONGCHAT_API_KEY (set=%s) / STRONGCHAT_PUBLIC_URL (set=%s) "
            "mismatch — disabling bearer auth. Fix the missing var (or "
            "unset both) to silence this warning.",
            bool(api_key), bool(public_url),
        )
        return None, None

    from mcp.server.auth.settings import AuthSettings
    from pydantic import AnyHttpUrl

    # ``AnyHttpUrl`` is a strict validator; the env string must include
    # a scheme. The Caddy deploy uses https://strongchat.X.sslip.io so
    # this is satisfied naturally.
    base = str(AnyHttpUrl(public_url))

    auth_settings = AuthSettings(
        issuer_url=base,  # any base that satisfies the OAuth issuer check
        resource_server_url=base,
        required_scopes=None,  # the static key has no scopes concept
    )
    token_verifier = StaticBearerTokenVerifier(api_key)
    logger.info(
        "bearer-auth-enabled public_url=%s client_id=%s",
        base, StaticBearerTokenVerifier.STATIC_CLIENT_ID,
    )
    return auth_settings, token_verifier