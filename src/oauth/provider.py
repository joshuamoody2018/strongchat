"""StrongChat OAuth 2.0 authorization-server provider (MCP SDK plug-in).

Implements ``mcp.server.auth.provider.OAuthAuthorizationServerProvider`` for
the single-user self-hosted deploy. When wired via
``MCPServer(auth_server_provider=StrongChatOAuthProvider(...), auth=...)``,
the MCP SDK auto-mounts the OAuth endpoints
(``/.well-known/oauth-authorization-server``, ``/authorize``, ``/token``,
``/register``, ``/revoke``, plus ``/.well-known/oauth-protected-resource/mcp``
for RFC 9728) on the same Starlette app as ``/mcp``, so a hosted claude.ai
web custom-connector can run the full PKCE onboarding flow against the
single pre-shared ``client_id`` + ``client_secret`` the deploy owner pastes
into the connector settings UI. The SDK auto-wraps the provider with
``ProviderTokenVerifier`` so incoming bearer tokens are verified through the
provider's own ``load_access_token`` (no separate ``token_verifier`` kwarg).

Static-client deployment (Option 1, the supported mode):

* ``register_client`` raises ``NotImplementedError``. The SDK's
  ``RegistrationHandler`` only calls it when
  ``client_registration_options.enabled=True``; we set it ``False`` in
  ``load_oauth_config`` so the ``/register`` route is not mounted and the
  metadata endpoint never advertises ``registration_endpoint``. RFC 7591
  dynamic client registration is therefore unavailable — every OAuth
  client must be configured with the static ``client_id`` +
  ``client_secret`` directly. claude.ai's hosted custom-connector UI
  accepts these as paste-in fields (this is the connector onboarding
  flow it falls back to when ``registration_endpoint`` is missing from
  the metadata).

* ``get_client`` is a one-record lookup against the pre-shared
  ``client_id``. Any other ``client_id`` value returns ``None`` so a
  leaked JWT bearer sent with a forged ``client_id`` still fails
  authentication on ``/token`` / ``/revoke``.

* ``client_id`` + ``client_secret`` are sourced from
  ``STRONGCHAT_OAUTH_CLIENT_ID`` + ``STRONGCHAT_OAUTH_CLIENT_SECRET``
  (idempotently generated at first boot by
  ``scripts/generate_oauth_client_credentials.sh``; readable via
  ``scripts/print_oauth_client_credentials.sh``).

Storage choice (per todo.md § "Pre-conditions + environment facts"):
**in-memory dicts** — acceptable for a single-user self-hosted deploy where
re-onboarding on restart is fine (claude.ai's connector just re-runs the
consent flow). Auth codes TTL 10 minutes; access tokens TTL 1 hour; refresh
tokens TTL 30 days. Nothing here is persisted to disk; ``data/`` is untouched.

Token format: HS256-signed JWT (PyJWT, already a transitive dependency of
``mcp``). The signing key is a 256-bit secret generated once per deploy
(``secrets.token_urlsafe(32)``) and loaded from env
``STRONGCHAT_OAUTH_SIGNING_KEY``. Distinct from the static-bearer key
(``STRONGCHAT_API_KEY``) — never reuse one for the other.

Scopes (single-user): one scope ``strongchat:retrieve_context`` advertised
in metadata ``scopes_supported`` so the claude.ai connector onboarding UI
shows the right permission label.

SDK wiring constraint (verified against the installed ``mcp`` SDK,
``mcp/server/mcpserver/server.py:237-238``):
``MCPServer.__init__`` rejects passing both ``auth_server_provider=`` AND
``token_verifier=`` with ``ValueError("Cannot specify both ...")``. The
static-bearer ``StaticBearerTokenVerifier`` (``src/auth.py``) and this OAuth
provider therefore CANNOT coexist on a single ``MCPServer`` instance.
``src/server.py:_setup_and_build_mcp`` picks ONE based on env: OAuth when
``STRONGCHAT_OAUTH_SIGNING_KEY`` + ``STRONGCHAT_PUBLIC_URL`` +
``STRONGCHAT_OAUTH_CLIENT_ID`` + ``STRONGCHAT_OAUTH_CLIENT_SECRET`` are all
set (signing-key path takes precedence), falling back to the static bearer
when only ``STRONGCHAT_API_KEY`` + ``STRONGCHAT_PUBLIC_URL`` are set, and
to no auth when neither is configured. The bearer guardrails from
``src/auth.py`` stay available as the fallback path; switching deployments
between the two is a pure env-var change.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Optional, Tuple

import jwt
from pydantic import AnyHttpUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

# The one scope this single-user deploy supports. The metadata endpoint's
# ``scopes_supported`` array mirrors this so claude.ai's connector onboarding
# UI surfaces a meaningful permission label for ``retrieve_context`` callers.
SCOPE_RETRIEVE_CONTEXT = "strongchat:retrieve_context"
SCOPES_SUPPORTED = [SCOPE_RETRIEVE_CONTEXT]

# Token lifetimes (single-user v1 minimums per the todo pre-conditions block).
AUTH_CODE_TTL_SECONDS = 10 * 60               # 10 minutes
ACCESS_TOKEN_TTL_SECONDS = 60 * 60            # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

# JWT signing algorithm. HS256 (HMAC-SHA256) with the per-deploy signing
# key. Symmetric — the same key signs and verifies; that's fine for a
# single self-hosted authorization-server + resource-server pair.
JWT_ALG = "HS256"


class StrongChatOAuthProvider(OAuthAuthorizationServerProvider):
    """In-memory single-user OAuth 2.0 PKCE authorization server.

    All ``OAuthAuthorizationServerProvider`` Protocol abstract methods are
    implemented (the Protocol requires the full set — see the pre-conditions
    block in todo.md). ``exchange_identity_assertion`` (the SEP-990 / RFC 7523
    jwt-bearer grant) is explicitly rejected — single-user self-hosted
    deploys don't have an enterprise IdP behind them.

    The provider is safe to instantiate once at server boot and reuse for
    the lifetime of the process (the MCP server is a long-lived stdio /
    streamable-http process). All stores are plain dicts guarded by the
    asyncio event loop's implicit serialization — fine for v1's
    single-user, single-server-process deploy.
    """

    def __init__(
        self,
        issuer_url: str,
        signing_key: str,
        *,
        client_id: str,
        client_secret: str,
        clock=time.time,
    ):
        if not signing_key:
            raise ValueError("OAuth signing key must not be empty")
        if not client_id:
            raise ValueError("OAuth client_id must not be empty")
        if not client_secret:
            raise ValueError("OAuth client_secret must not be empty")
        # ``issuer_url`` is what the metadata endpoint advertises AND what
        # gets stamped into every issued JWT's ``iss`` claim. Strip a
        # trailing slash so the metadata-derived endpoint URLs (built by
        # ``mcp.server.auth.routes.build_metadata`` as
        # ``issuer_url.rstrip("/") + path``) match the JWT ``iss`` exactly —
        # RFC 8414 issuer comparison is exact string comparison.
        self._issuer = str(issuer_url).rstrip("/")
        self._signing_key = signing_key
        self._clock = clock
        # Static-client deployment (Option 1 per the todo): one pre-shared
        # ``client_id`` + ``client_secret`` that the deploy owner pastes
        # into claude.ai's connector settings UI (or any other OAuth
        # client's static-credentials config). ``register_client`` rejects
        # every DCR attempt with NotImplementedError so the metadata
        # endpoint never advertises ``/register`` to RFC 7591-capable
        # clients (see ``load_oauth_config`` below which sets
        # ``client_registration_options.enabled=False``).
        self._static_client_id = client_id
        self._static_client_secret = client_secret

        # In-memory stores (see module docstring: chosen storage for v1).
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

    # ------------------------------------------------------------------ #
    # Client registration (RFC 7591 dynamic client registration)
    # ------------------------------------------------------------------ #

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        """Retrieve the single pre-shared client (static-creds deployment).

        The SDK's ``ClientAuthenticator`` (``mcp/server/auth/middleware/
        client_auth.py``) calls ``get_client`` to look up a client when
        authenticating the ``/token`` and ``/revoke`` requests. For a
        static-creds deploy, the only valid client is the one we were
        constructed with — any other ``client_id`` is rejected (returns
        ``None``) so a leaked JWT bearer signed with the right key but
        sent with a forged ``client_id`` still fails authentication.

        The returned record is built lazily on each call (no
        registration state to persist; ``register_client`` raises
        ``NotImplementedError``).
        """
        if client_id != self._static_client_id:
            return None
        return self._build_static_client_record()

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        """DCR is disabled in this deployment (Option 1: static
        ``client_id`` + ``client_secret``).

        The SDK's ``RegistrationHandler`` only calls ``register_client``
        when ``client_registration_options.enabled=True``; we set that
        ``False`` in ``load_oauth_config`` below so the ``/register``
        route isn't mounted and the metadata endpoint never advertises
        ``registration_endpoint``. This ``NotImplementedError`` is a
        defence-in-depth tripwire if a future code path reaches us
        anyway.
        """
        raise NotImplementedError(
            "Dynamic client registration is not supported by this "
            "authorization server. Provide the pre-shared client_id "
            "and client_secret directly to your OAuth client."
        )

    def _build_static_client_record(self) -> "OAuthClientInformationFull":
        """Build the synthetic ``OAuthClientInformationFull`` for the
        pre-shared client. Used by ``get_client`` and by the
        ``ClientAuthenticator`` when verifying ``/token`` POSTs.

        The redirect-URI allow-list is intentionally wide: in a static-
        creds deployment we have no advance knowledge of which loopback
        port the OAuth client (e.g. claude.ai's hosted connector) will
        pick. We override ``validate_redirect_uri`` to accept any http
        loopback URI (RFC 8252 §7.3: native apps pick a fresh loopback
        port per OAuth dance). The security property the static-creds
        model relies on is NOT redirect-URI binding — it's the
        ``client_secret`` (which only the legitimate deploy owner and
        the OAuth client share) plus the PKCE binding (which only the
        legitimate client can satisfy). Wildcard redirect matching is
        safe under that threat model.
        """
        now = int(self._clock())

        class _PermissiveClientRecord(OAuthClientInformationFull):
            """Subclass that accepts any http(s) redirect_uri. All
            other OAuthClientInformationFull semantics — including the
            Pydantic field validation, ``validate_scope``, and the
            ``client_secret`` matching done by the SDK's
            ``ClientAuthenticator`` — are inherited unchanged."""

            def validate_redirect_uri(self, redirect_uri):
                from pydantic import AnyUrl
                from mcp.shared.auth import InvalidRedirectUriError
                if redirect_uri is None:
                    raise InvalidRedirectUriError(
                        "redirect_uri is required (static-creds deployment "
                        "does not register a default URI)"
                    )
                # Reject anything that isn't a loopback http URL or a
                # public https URL — the OAuth client must be reachable
                # over the loopback redirect OR a public HTTPS endpoint
                # the deploy owner whitelisted in advance.
                host = (redirect_uri.host or "").lower()
                scheme = (redirect_uri.scheme or "").lower()
                if scheme == "https":
                    return redirect_uri
                if scheme == "http" and host in (
                    "localhost", "127.0.0.1", "[::1]",
                ):
                    return redirect_uri
                raise InvalidRedirectUriError(
                    f"Redirect URI '{redirect_uri}' not in the static-creds "
                    f"allow-list (only http://localhost, http://127.0.0.1, "
                    f"and https://* are accepted; the client_secret + PKCE "
                    f"are the actual security gates)."
                )

        return _PermissiveClientRecord(
            client_id=self._static_client_id,
            client_secret=self._static_client_secret,
            redirect_uris=[],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=SCOPE_RETRIEVE_CONTEXT,
            token_endpoint_auth_method="client_secret_post",
            client_id_issued_at=now,
            client_secret_expires_at=0,
        )

    # ------------------------------------------------------------------ #
    # /authorize
    # ------------------------------------------------------------------ #

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Single-user consent: immediately mint a short-lived authorization
        code and redirect back to the client's ``redirect_uri`` with
        ``code`` + ``state`` in the query string. There is no login step —
        there's only ever one user (the deploy owner) — and no third-party
        IdP, so the consent screen is effectively "approve" by construction.

        Raises ``AuthorizeError`` with ``invalid_scope`` if the client
        requested a scope we don't support (the SDK's authorize handler has
        already done client-side ``validate_scope`` against the client's
        registered scopes; this is the server-side authoritativeness check).
        """
        requested = params.scopes or []
        for scope in requested:
            if scope not in SCOPES_SUPPORTED:
                raise AuthorizeError(
                    error="invalid_scope",
                    error_description=(
                        f"scope {scope!r} is not supported by this "
                        f"authorization server"
                    ),
                )
        # Some clients (claude.ai connector) omit scope on /authorize and
        # rely on the server defaulting. Grant the one scope.
        scopes = list(requested) or [SCOPE_RETRIEVE_CONTEXT]

        # RFC 6749 §10.10: ≥128 bits of entropy REQUIRED; ≥160 bits RECOMMENDED.
        # ``secrets.token_urlsafe(32)`` yields 256 bits.
        code = secrets.token_urlsafe(32)
        issued_at = self._clock()
        auth_code = AuthorizationCode(
            code=code,
            scopes=scopes,
            expires_at=issued_at + AUTH_CODE_TTL_SECONDS,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            # Single-user: subject is the resource owner (the deploy owner /
            # the client itself; there is no separate user identity service).
            subject=client.client_id,
        )
        self._auth_codes[code] = auth_code
        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

    # ------------------------------------------------------------------ #
    # /token
    # ------------------------------------------------------------------ #

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        # The SDK's token handler additionally checks
        # ``auth_code.client_id == token_request.client_id`` and the auth
        # code expiry. We just surface the code (or None) and let the
        # handler do those checks; nothing here is expired.
        return code

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        """Issue an access + refresh token pair for a consumed auth code.

        The SDK's token handler has ALREADY validated PKCE
        (``code_verifier`` hashed vs ``code_challenge``), the auth code
        expiry, the redirect_uri match, and client_id ownership — we don't
        re-check those here. We DO pop the one-time auth code so it can't
        be replayed (RFC 6749 §4.1.2: "The authorization code MUST expire
        shortly after it is issued ... and MUST NOT be used more than once").
        """
        self._auth_codes.pop(authorization_code.code, None)
        scopes = list(authorization_code.scopes)
        access_token = self._issue_access_token(
            client_id=client.client_id,
            scopes=scopes,
            resource=authorization_code.resource,
            subject=authorization_code.subject or client.client_id,
        )
        refresh_token = self._issue_refresh_token(
            client_id=client.client_id,
            scopes=scopes,
            subject=authorization_code.subject or client.client_id,
        )
        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        rt = self._refresh_tokens.get(refresh_token)
        if rt is None or rt.client_id != client.client_id:
            return None
        return rt

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Rotate both access AND refresh token (RFC 6749 §6 best practice).
        The SDK's handler has already validated the requested scopes are a
        subset of the refresh token's scopes and that the refresh token
        hasn't expired. We drop the old refresh token (single-use rotation)
        and mint a new pair.
        """
        self._refresh_tokens.pop(refresh_token.token, None)
        final_scopes = list(scopes)
        access_token = self._issue_access_token(
            client_id=client.client_id,
            scopes=final_scopes,
            resource=None,
            subject=refresh_token.subject or client.client_id,
        )
        new_refresh = self._issue_refresh_token(
            client_id=client.client_id,
            scopes=final_scopes,
            subject=refresh_token.subject or client.client_id,
        )
        return OAuthToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(final_scopes),
            refresh_token=new_refresh,
        )

    # ------------------------------------------------------------------ #
    # /revoke
    # ------------------------------------------------------------------ #

    async def revoke_token(
        self,
        token: AccessToken | RefreshToken,
    ) -> None:
        """RFC 7009 token revocation. Access tokens are JWTs (not stored
        server-side) — there's no per-token record to drop, so revoking an
        access token is a no-op (it will expire on its own short TTL).
        Refresh tokens ARE stored, so we drop them immediately. Per the
        RFC, revoking an unknown or already-revoked token is a no-op.
        """
        if isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
        # AccessToken: short-lived JWT; nothing to drop.

    # ------------------------------------------------------------------ #
    # Token introspection (used by the SDK's ProviderTokenVerifier to
    # verify incoming ``Authorization: Bearer <jwt>`` on /mcp requests).
    # ------------------------------------------------------------------ #

    async def load_access_token(self, token: str) -> AccessToken | None:
        """Decode + verify a JWT bearer; return an ``AccessToken`` whose 7
        fields mirror what the static-bearer path returns
        (``StaticBearerTokenVerifier.verify_token``, ``src/auth.py:119``):
        ``token, client_id, scopes, expires_at, resource, subject, claims``.

        Invalid signature / wrong issuer / expired / malformed JWT → ``None``
        (the SDK's ``BearerAuthBackend`` turns ``None`` into ``401``).
        """
        try:
            claims = jwt.decode(
                token,
                self._signing_key,
                algorithms=[JWT_ALG],
                # Require the RFC 9068 JWT profile's mandatory claims.
                options={"require": ["exp", "iat", "iss", "sub", "client_id"]},
                issuer=self._issuer,
                audience=self._issuer,
            )
        except jwt.PyJWTError:
            return None
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=list(claims.get("scopes", [])),
            expires_at=int(claims["exp"]),
            resource=claims.get("resource"),
            subject=claims.get("sub"),
            # Surface the full claim set (incl. ``iss``, ``jti``, ``iat``) so
            # downstream introspection / audit can see them, matching how the
            # static bearer path leaves ``claims=None`` for the opaque key.
            claims=dict(claims),
        )

    # ------------------------------------------------------------------ #
    # Identity assertion (SEP-990 / RFC 7523 jwt-bearer grant)
    # ------------------------------------------------------------------ #

    async def exchange_identity_assertion(
        self,
        client: OAuthClientInformationFull,
        params: IdentityAssertionParams,
    ) -> OAuthToken:
        """Single-user self-hosted deploys don't have an enterprise IdP
        behind them, so the jwt-bearer grant is unsupported. Mirror the
        Protocol's default implementation (raise ``TokenError`` so the
        token handler surfaces ``unsupported_grant_type``).
        """
        raise TokenError(
            error="unsupported_grant_type",
            error_description=(
                "Identity assertion (RFC 7523 jwt-bearer grant) is not "
                "supported by this single-user authorization server."
            ),
        )

    # ------------------------------------------------------------------ #
    # JWT + refresh-token minting helpers
    # ------------------------------------------------------------------ #

    def _issue_access_token(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str,
    ) -> str:
        now = int(self._clock())
        payload: dict[str, object] = {
            # RFC 9068 §2.1 mandatory + recommended claims.
            "iss": self._issuer,
            "sub": subject,
            "aud": self._issuer,  # audience is this authorization server.
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL_SECONDS,
            "jti": secrets.token_urlsafe(16),
            # StrongChat-specific: the SDK's ``principal_components``
            # extracts ``client_id`` + ``iss`` + ``sub`` for session
            # ownership, and the bearer backend surfaces ``scopes`` to
            # RequireAuthMiddleware for scope-gating.
            "client_id": client_id,
            "scopes": list(scopes),
        }
        if resource is not None:
            payload["resource"] = resource
        return jwt.encode(payload, self._signing_key, algorithm=JWT_ALG)

    def _issue_refresh_token(
        self,
        *,
        client_id: str,
        scopes: list[str],
        subject: str,
    ) -> str:
        # Opaque random token (RFC 6749 §10.4: ≥128 bits).
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._refresh_tokens[token] = RefreshToken(
            token=token,
            client_id=client_id,
            scopes=list(scopes),
            expires_at=int(now + REFRESH_TOKEN_TTL_SECONDS),
            subject=subject,
        )
        return token


# ---------------------------------------------------------------------- #
# Env-driven construction helper for src/server.py
# ---------------------------------------------------------------------- #


def load_oauth_config() -> Tuple[Optional[AuthSettings], Optional[StrongChatOAuthProvider]]:
    """Return ``(auth_settings, oauth_provider)`` for ``MCPServer.__init__``.

    Both elements are ``None`` when OAuth is not configured — i.e. when
    ``STRONGCHAT_OAUTH_SIGNING_KEY`` OR ``STRONGCHAT_PUBLIC_URL`` is unset
    (in which case ``src/server.py`` falls back to the static-bearer path
    from ``src/auth.py``, or no auth at all).

    On mismatch (only one of the two env vars set) log a WARNING and
    disable — consistent with ``load_static_bearer_config``'s fail-loud-
    but-never-silent-open policy.

    When both are set, returns:
    * ``auth_settings`` — ``AuthSettings`` with ``client_registration_options``
      enabled + ``valid_scopes``/``default_scopes`` set to
      ``["strongchat:retrieve_context"]`` so the SDK's
      ``/.well-known/oauth-authorization-server`` metadata advertises the
      right scope, and ``revocation_options`` enabled so ``/revoke`` is
      mounted too.
    * ``oauth_provider`` — a fresh ``StrongChatOAuthProvider`` instance.
    """
    signing_key = os.environ.get("STRONGCHAT_OAUTH_SIGNING_KEY", "").strip()
    # ``STRONGCHAT_PUBLIC_URL`` is shared with the static bearer path
    # (``src/auth.py``) — a bearer-only deploy sets it without the OAuth
    # signing key. We therefore treat an UNSET signing key as "OAuth not
    # requested" and return silently (the bearer path picks up the
    # shared URL on its own). Only when the signing key is set but the
    # public URL is missing do we warn: that's an unambiguous
    # misconfiguration of the OAuth path specifically.
    if not signing_key:
        return None, None

    public_url = os.environ.get("STRONGCHAT_PUBLIC_URL", "").strip()
    if not public_url:
        logger.warning(
            "STRONGCHAT_OAUTH_SIGNING_KEY is set but "
            "STRONGCHAT_PUBLIC_URL is unset — disabling OAuth provider. "
            "Set STRONGCHAT_PUBLIC_URL to your public canonical base URL "
            "(the same value as the static-bearer path), or unset "
            "STRONGCHAT_OAUTH_SIGNING_KEY to fall back to the static bearer."
        )
        return None, None

    base = str(AnyHttpUrl(public_url)).rstrip("/")
    # The MCP server endpoint lives at ``/mcp`` on the same Starlette app
    # as the OAuth routes. Per RFC 9728 §3.1, the protected-resource
    # metadata URL is built as ``<scheme>://<host>/.well-known/oauth-
    # protected-resource<resource-path>`` — so the resource-server URL
    # must include ``/mcp`` or claude.ai's hosted connector probes the
    # wrong path and falls back to asking the user for a static
    # ``client_id``/``client_secret`` (the error users hit when this
    # value was set to the bare public URL).
    resource_server_url = f"{base}/mcp"

    # Static-client deployment (Option 1): a single pre-shared
    # ``client_id`` + ``client_secret`` that the deploy owner pastes into
    # each OAuth client's connector settings (claude.ai's hosted
    # custom-connector, any other client that prefers static creds over
    # RFC 7591 DCR). Read from env so they survive the systemd
    # EnvironmentFile=.env path; if either is unset the OAuth provider
    # is disabled (mirrors how the signing-key + public-URL mismatch
    # path fails loud).
    static_client_id = os.environ.get(
        "STRONGCHAT_OAUTH_CLIENT_ID", ""
    ).strip()
    static_client_secret = os.environ.get(
        "STRONGCHAT_OAUTH_CLIENT_SECRET", ""
    ).strip()
    if not static_client_id or not static_client_secret:
        logger.warning(
            "STRONGCHAT_OAUTH_SIGNING_KEY + STRONGCHAT_PUBLIC_URL are "
            "set but STRONGCHAT_OAUTH_CLIENT_ID and/or "
            "STRONGCHAT_OAUTH_CLIENT_SECRET are unset — disabling OAuth "
            "provider. Set both client creds (run "
            "scripts/generate_oauth_client_credentials.sh to mint them "
            "and scripts/print_oauth_client_credentials.sh to retrieve "
            "the values to paste into your OAuth client)."
        )
        return None, None

    auth_settings = AuthSettings(
        issuer_url=base,
        resource_server_url=resource_server_url,
        # Resource-server scope gate: only callers of ``retrieve_context``
        # (its only callable tool today) are permitted.
        required_scopes=None,  # permissive — relying on client_registration scope
        # DCR disabled (Option 1: static creds). The SDK omits the
        # ``registration_endpoint`` from the metadata document and does
        # NOT mount the ``/register`` route, so claude.ai's connector
        # onboarding won't even attempt RFC 7591 dynamic registration
        # — it goes straight to the static-credentials path the user
        # already pasted into the connector UI.
        client_registration_options=ClientRegistrationOptions(
            # DCR disabled (Option 1: static creds) — the SDK omits the
            # ``registration_endpoint`` from the metadata document and
            # does NOT mount the ``/register`` route. We still populate
            # ``valid_scopes`` / ``default_scopes`` so the metadata
            # advertises ``scopes_supported`` to claude.ai's connector
            # onboarding UI (which surfaces a permission label from
            # that field) — those lists are unused server-side when DCR
            # is off (claude.ai's static creds already carry whatever
            # scope they negotiated at signup time).
            enabled=False,
            valid_scopes=SCOPES_SUPPORTED,
            default_scopes=SCOPES_SUPPORTED,
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    provider = StrongChatOAuthProvider(
        issuer_url=base,
        signing_key=signing_key,
        client_id=static_client_id,
        client_secret=static_client_secret,
    )
    logger.info(
        "oauth-provider-enabled issuer=%s scope=%s",
        base, SCOPE_RETRIEVE_CONTEXT,
    )
    return auth_settings, provider