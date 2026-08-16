#!/usr/bin/env python3
"""Offline tests for the StrongChat OAuth 2.0 authorization-server provider.

Exercises every abstract method of the MCP SDK's
``OAuthAuthorizationServerProvider`` Protocol against
``StrongChatOAuthProvider`` (``src/oauth/provider.py``) in isolation — no
HTTP server, no Starlette, no uvicorn. Storage is the provider's own
in-memory dicts; no fixtures need patching.

Covers:

* register_client / get_client (RFC 7591 client lifecycle)
* authorize + load_authorization_code (auth-code mint + redirect URL,
  invalid-scope rejection)
* exchange_authorization_code (issues access + refresh; one-time-code
  consumed after exchange)
* load_access_token (JWT verify happy path; expired / malformed /
  wrong-signing-key tokens rejected as ``None``)
* exchange_refresh_token (rotation: old refresh dropped, new pair minted)
* revoke_token (AccessToken is a no-op JWT; RefreshToken dropped from
  the store)
* exchange_identity_assertion (raises ``TokenError`` ``unsupported_grant_type``)

Each test builds a fresh ``StrongChatOAuthProvider`` so stores don't
leak across cases. The provider's PKCE code_challenge/code_verifier math
is performed by the SDK's TokenHandler — we don't re-test it here; we
assert the provider cooperates with the values it's handed.
"""

import asyncio
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

if not os.getenv("OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"):
    os.environ["OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"] = "dummy-key-for-offline-oauth-tests"

from mcp.server.auth.provider import (  # noqa: E402
    AuthorizationParams,
    AuthorizeError,
    IdentityAssertionParams,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull  # noqa: E402
from pydantic import AnyUrl  # noqa: E402

from oauth import (  # noqa: E402
    SCOPE_RETRIEVE_CONTEXT,
    StrongChatOAuthProvider,
)
from oauth.provider import ACCESS_TOKEN_TTL_SECONDS  # noqa: E402


_ISSUER = "http://127.0.0.1:8765"
# Quiet PyJWT's InsecureKeyLengthWarning: ≥32 bytes for HS256.
_SIGNING_KEY = "test-signing-key-must-be-at-least-32-chars!!"
# Static-creds deployment — every test uses the same pre-shared values
# (Option 1: DCR disabled, paste the same client_id + secret into every
# OAuth client that connects, just like STRONGCHAT_API_KEY for the
# static-bearer path).
_STATIC_CLIENT_ID = "strongchat-static-oauth-client"
_STATIC_CLIENT_SECRET = "test-client-secret-must-be-at-least-32-chars!!"
_REDIRECT = "http://localhost:0/cb"
_CODE_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"  # demo value from RFC 7636


def _make_provider(
    issuer=_ISSUER,
    signing_key=_SIGNING_KEY,
    client_id=_STATIC_CLIENT_ID,
    client_secret=_STATIC_CLIENT_SECRET,
):
    """Build a StrongChatOAuthProvider with the standard test fixtures."""
    return StrongChatOAuthProvider(
        issuer_url=issuer,
        signing_key=signing_key,
        client_id=client_id,
        client_secret=client_secret,
    )


def _make_client(
    client_id=_STATIC_CLIENT_ID,
    client_secret=_STATIC_CLIENT_SECRET,
) -> OAuthClientInformationFull:
    """Build an OAuthClientInformationFull that mirrors the synthetic
    record ``StrongChatOAuthProvider.get_client`` returns. Used to drive
    the SDK's ``ClientAuthenticator``-style flows in tests; the provider
    itself never persists client records in the static-creds deployment.
    """
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=client_secret,
        # Empty list so claude.ai's dynamic loopback redirect ports all
        # pass — the provider accepts any loopback redirect in
        # ``validate_redirect_uri`` because the synthetic record's
        # ``redirect_uris`` is None.
        redirect_uris=None,
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=SCOPE_RETRIEVE_CONTEXT,
        token_endpoint_auth_method="client_secret_post",
        client_id_issued_at=int(time.time()),
        client_secret_expires_at=0,
    )


def _authorize_params(scopes=None, state="abc-state", code_challenge=_CODE_CHALLENGE):
    return AuthorizationParams(
        state=state,
        scopes=list(scopes) if scopes is not None else [SCOPE_RETRIEVE_CONTEXT],
        code_challenge=code_challenge,
        redirect_uri=AnyUrl(_REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


class TestOAuthProviderRegistration(unittest.TestCase):
    """Static-creds deployment (Option 1): no DCR; get_client returns
    the pre-shared record; register_client raises NotImplementedError."""

    def test_register_client_raises_not_implemented(self):
        """DCR is disabled — every register_client call is rejected."""
        p = _make_provider()

        async def go():
            with self.assertRaises(NotImplementedError):
                await p.register_client(_make_client())

        asyncio.run(go())

    def test_get_client_returns_static_record_for_known_client(self):
        """get_client returns the synthetic pre-shared client record."""
        p = _make_provider()

        async def go():
            fetched = await p.get_client(_STATIC_CLIENT_ID)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.client_id, _STATIC_CLIENT_ID)
            self.assertEqual(fetched.client_secret, _STATIC_CLIENT_SECRET)
            # The synthetic record advertises the right grant_types +
            # scope so the SDK's ClientAuthenticator accepts the static
            # creds on /token and /revoke POSTs.
            self.assertIn("authorization_code", fetched.grant_types)
            self.assertEqual(fetched.scope, SCOPE_RETRIEVE_CONTEXT)

        asyncio.run(go())

    def test_get_client_returns_none_for_unknown_client(self):
        """Any other client_id is rejected — a leaked JWT bearer sent
        with a forged client_id still fails authentication."""
        p = _make_provider()

        async def go():
            self.assertIsNone(await p.get_client("does-not-exist"))
            self.assertIsNone(await p.get_client(""))

        asyncio.run(go())

    def test_empty_signing_key_or_creds_rejected_at_construction(self):
        """Provider construction validates every required secret."""
        with self.assertRaises(ValueError):
            StrongChatOAuthProvider(
                _ISSUER, "", client_id="x", client_secret="y",
            )
        with self.assertRaises(ValueError):
            StrongChatOAuthProvider(
                _ISSUER, "k"*32, client_id="", client_secret="y",
            )
        with self.assertRaises(ValueError):
            StrongChatOAuthProvider(
                _ISSUER, "k"*32, client_id="x", client_secret="",
            )


class TestOAuthProviderAuthorize(unittest.TestCase):
    """/authorize — auth code mint + redirect URL + scope validation."""

    def test_authorize_emits_redirect_with_code_and_state(self):
        p = _make_provider()

        async def go():
            client = _make_client()
            url = await p.authorize(client, _authorize_params(state="st-123"))
            self.assertTrue(url.startswith(_REDIRECT), url)
            self.assertIn("code=", url)
            self.assertIn("state=st-123", url)

        asyncio.run(go())

    def test_authorize_stores_authorization_code(self):
        p = _make_provider()

        async def go():
            client = _make_client()
            url = await p.authorize(client, _authorize_params())
            code = url.split("code=")[1].split("&")[0]
            ac = await p.load_authorization_code(client, code)
            self.assertIsNotNone(ac)
            self.assertEqual(ac.client_id, client.client_id)
            self.assertEqual(ac.code_challenge, _CODE_CHALLENGE)
            # Expiry is ~10 min after issuance.
            self.assertGreater(ac.expires_at, time.time())
            self.assertLess(ac.expires_at, time.time() + 11 * 60)

        asyncio.run(go())

    def test_authorize_rejects_unsupported_scope(self):
        p = _make_provider()

        async def go():
            client = _make_client()
            with self.assertRaises(AuthorizeError) as ctx:
                await p.authorize(
                    client, _authorize_params(scopes=["bogus-scope"])
                )
            self.assertEqual(ctx.exception.error, "invalid_scope")

        asyncio.run(go())

    def test_authorize_defaults_scope_when_none_requested(self):
        p = _make_provider()

        async def go():
            client = _make_client()
            url = await p.authorize(
                client, _authorize_params(scopes=[])
            )
            code = url.split("code=")[1].split("&")[0]
            ac = await p.load_authorization_code(client, code)
            self.assertEqual(ac.scopes, [SCOPE_RETRIEVE_CONTEXT])

        asyncio.run(go())

    def test_load_authorization_code_unknown_returns_none(self):
        p = _make_provider()

        async def go():
            client = _make_client()
            self.assertIsNone(await p.load_authorization_code(client, "nope"))

        asyncio.run(go())


class TestOAuthProviderExchange(unittest.TestCase):
    """/token — auth-code exchange + refresh-token rotation."""

    def _make_auth_code(self, provider, client):
        async def go():
            url = await provider.authorize(client, _authorize_params())
            code = url.split("code=")[1].split("&")[0]
            return await provider.load_authorization_code(client, code)

        return asyncio.run(go())

    def test_exchange_issues_access_and_refresh_tokens(self):
        p = _make_provider()
        client = _make_client()
        ac = self._make_auth_code(p, client)

        async def go():
            tokens = await p.exchange_authorization_code(client, ac)
            self.assertEqual(tokens.token_type.lower(), "bearer")
            self.assertEqual(tokens.expires_in, ACCESS_TOKEN_TTL_SECONDS)
            self.assertEqual(tokens.scope, SCOPE_RETRIEVE_CONTEXT)
            self.assertTrue(tokens.access_token)
            self.assertTrue(tokens.refresh_token)
            # Auth code is single-use: a second load returns None (popped).
            self.assertIsNone(await p.load_authorization_code(client, ac.code))

        asyncio.run(go())

    def test_exchange_refresh_rotates_both_tokens(self):
        p = _make_provider()
        client = _make_client()
        ac = self._make_auth_code(p, client)

        async def go():
            tokens = await p.exchange_authorization_code(client, ac)
            rt = await p.load_refresh_token(client, tokens.refresh_token)
            self.assertIsNotNone(rt)
            self.assertEqual(rt.client_id, client.client_id)
            new_tokens = await p.exchange_refresh_token(
                client, rt, [SCOPE_RETRIEVE_CONTEXT]
            )
            self.assertNotEqual(
                new_tokens.refresh_token, tokens.refresh_token
            )
            # Old refresh is revoked (single-use rotation).
            self.assertIsNone(
                await p.load_refresh_token(client, tokens.refresh_token)
            )
            # New refresh loads.
            self.assertIsNotNone(
                await p.load_refresh_token(client, new_tokens.refresh_token)
            )

        asyncio.run(go())

    def test_load_refresh_token_wrong_client_returns_none(self):
        p = _make_provider()
        client = _make_client()
        ac = self._make_auth_code(p, client)

        async def go():
            tokens = await p.exchange_authorization_code(client, ac)
            other = _make_client(client_id="other-client")
            self.assertIsNone(
                await p.load_refresh_token(client=other,
                                           refresh_token=tokens.refresh_token)
            )

        asyncio.run(go())


class TestOAuthProviderAccessToken(unittest.TestCase):
    """load_access_token — JWT verify happy path + rejection cases."""

    def _issue_token(self, provider, client_id=SCOPE_RETRIEVE_CONTEXT):
        # subject, client_id, etc. — produce a real access token through the
        # public flow so it carries the full claim set we expect.
        async def go():
            client = _make_client(client_id="c")
            url = await provider.authorize(client, _authorize_params())
            code = url.split("code=")[1].split("&")[0]
            ac = await provider.load_authorization_code(client, code)
            tokens = await provider.exchange_authorization_code(client, ac)
            return client, tokens.access_token

        return asyncio.run(go())

    def test_load_access_token_returns_seven_field_AccessToken(self):
        p = _make_provider()
        client, token = self._issue_token(p)

        async def go():
            at = await p.load_access_token(token)
            self.assertIsNotNone(at)
            # Mirrors the 7-field shape StaticBearerTokenVerifier returns
            # at src/auth.py:119+ (token, client_id, scopes, expires_at,
            # resource, subject, claims).
            self.assertEqual(at.token, token)
            self.assertEqual(at.client_id, client.client_id)
            self.assertEqual(at.scopes, [SCOPE_RETRIEVE_CONTEXT])
            self.assertIsNotNone(at.expires_at)
            self.assertIsNone(at.resource)  # none requested
            self.assertEqual(at.subject, client.client_id)
            self.assertIsNotNone(at.claims)
            self.assertEqual(at.claims.get("iss"), _ISSUER)
            self.assertIn("jti", at.claims)

        asyncio.run(go())

    def test_load_access_token_rejects_malformed(self):
        p = _make_provider()

        async def go():
            self.assertIsNone(await p.load_access_token("not-a-jwt"))
            self.assertIsNone(await p.load_access_token(""))

        asyncio.run(go())

    def test_load_access_token_rejects_wrong_signing_key(self):
        p = _make_provider()
        _, token = self._issue_token(p)
        p_other = _make_provider(signing_key="a-totally-different-secret-key!!")

        async def go():
            # Same `iss`/`aud`/`sub` claims — only the signing key differs,
            # so HS256 verification fails with InvalidSignatureError.
            self.assertIsNone(await p_other.load_access_token(token))

        asyncio.run(go())

    def test_load_access_token_rejects_expired(self):
        # Provider clocked into the past so the issued token is already
        # past its ``exp`` (1h TTL by default).
        back_then = time.time() - 2 * 3600
        p = StrongChatOAuthProvider(
            _ISSUER, _SIGNING_KEY,
            client_id=_STATIC_CLIENT_ID,
            client_secret=_STATIC_CLIENT_SECRET,
            clock=lambda: back_then,
        )
        _, token = self._issue_token(p)

        async def go():
            self.assertIsNone(await p.load_access_token(token))

        asyncio.run(go())

    def test_load_access_token_rejects_wrong_issuer(self):
        p = _make_provider()
        _, token = self._issue_token(p)
        p_other_issuer = _make_provider(issuer="http://127.0.0.1:9999")

        async def go():
            # Same signing key, JWT decodes — but ``iss`` doesn't match
            # the new provider's configured issuer → rejected.
            self.assertIsNone(await p_other_issuer.load_access_token(token))

        asyncio.run(go())


class TestOAuthProviderRevoke(unittest.TestCase):
    """revoke_token — RFC 7009."""

    def test_revoke_refresh_token_drops_store(self):
        p = _make_provider()
        client = _make_client()

        async def go():
            url = await p.authorize(client, _authorize_params())
            code = url.split("code=")[1].split("&")[0]
            ac = await p.load_authorization_code(client, code)
            tokens = await p.exchange_authorization_code(client, ac)
            rt = await p.load_refresh_token(client, tokens.refresh_token)
            self.assertIsNotNone(rt)
            await p.revoke_token(rt)
            self.assertIsNone(
                await p.load_refresh_token(client, tokens.refresh_token)
            )

        asyncio.run(go())

    def test_revoke_unknown_token_is_noop(self):
        p = _make_provider()

        async def go():
            # An access token we never issued — revoke_token must not
            # raise (RFC 7009 §2.2: invalid_token is a no-op).
            from mcp.server.auth.provider import AccessToken
            phantom = AccessToken(
                token="never-issued",
                client_id="x",
                scopes=[],
                expires_at=None,
            )
            await p.revoke_token(phantom)

        asyncio.run(go())


class TestOAuthProviderIdentityAssertion(unittest.TestCase):
    """exchange_identity_assertion — always unsupported on this single-user AS."""

    def test_identity_assertion_rejected(self):
        p = _make_provider()

        async def go():
            client = _make_client()
            with self.assertRaises(TokenError) as ctx:
                await p.exchange_identity_assertion(
                    client, IdentityAssertionParams(assertion="x.y.z")
                )
            self.assertEqual(ctx.exception.error, "unsupported_grant_type")

        asyncio.run(go())


class TestLoadOAuthConfigEnv(unittest.TestCase):
    """``load_oauth_config`` env parsing — precedence + mismatch handling."""

    def setUp(self):
        self._env = os.environ.copy()
        for k in (
            "STRONGCHAT_OAUTH_SIGNING_KEY",
            "STRONGCHAT_PUBLIC_URL",
            "STRONGCHAT_OAUTH_CLIENT_ID",
            "STRONGCHAT_OAUTH_CLIENT_SECRET",
            "STRONGCHAT_API_KEY",
        ):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_unset_returns_none_pair(self):
        from oauth import load_oauth_config
        self.assertEqual(load_oauth_config(), (None, None))

    def test_mismatch_signing_key_only_warns_and_disables(self):
        from oauth import load_oauth_config
        os.environ["STRONGCHAT_OAUTH_SIGNING_KEY"] = _SIGNING_KEY
        with self.assertLogs("oauth", level="WARNING"):
            auth_settings, provider = load_oauth_config()
        self.assertIsNone(auth_settings)
        self.assertIsNone(provider)

    def test_public_url_only_is_silent_non_oauth(self):
        # ``STRONGCHAT_PUBLIC_URL`` is shared with the static bearer path
        # (src/auth.py); setting it alone must NOT raise an OAuth mismatch
        # warning (the bearer path picks up that URL on its own). OAuth
        # simply reports "not configured".
        from oauth import load_oauth_config
        os.environ["STRONGCHAT_PUBLIC_URL"] = _ISSUER
        # assertNoWarns would silence — but we want to confirm the helper
        # returns (None, None) and did NOT log a WARNING. Capture logs.
        import logging
        records: list[logging.LogRecord] = []

        class _H(logging.Handler):
            def emit(self, rec):
                records.append(rec)

        h = _H()
        h.setLevel(logging.WARNING)
        root = logging.getLogger("oauth")
        root.addHandler(h)
        try:
            auth_settings, provider = load_oauth_config()
        finally:
            root.removeHandler(h)
        self.assertIsNone(auth_settings)
        self.assertIsNone(provider)
        self.assertFalse(
            any(r.levelno >= logging.WARNING for r in records),
            f"unexpected OAuth warning when signing key unset: {records!r}",
        )

    def test_both_set_returns_active_config(self):
        from oauth import load_oauth_config
        os.environ["STRONGCHAT_OAUTH_SIGNING_KEY"] = _SIGNING_KEY
        os.environ["STRONGCHAT_PUBLIC_URL"] = _ISSUER
        os.environ["STRONGCHAT_OAUTH_CLIENT_ID"] = _STATIC_CLIENT_ID
        os.environ["STRONGCHAT_OAUTH_CLIENT_SECRET"] = _STATIC_CLIENT_SECRET
        auth_settings, provider = load_oauth_config()
        self.assertIsNotNone(auth_settings)
        self.assertIsNotNone(provider)
        self.assertEqual(str(auth_settings.issuer_url).rstrip("/"), _ISSUER)
        # resource_server_url must include /mcp so RFC 9728 metadata is
        # discoverable at /.well-known/oauth-protected-resource/mcp.
        self.assertEqual(
            str(auth_settings.resource_server_url).rstrip("/"),
            f"{_ISSUER}/mcp",
        )
        # DCR is disabled (Option 1: static creds). Revocation still on
        # so /revoke is mounted.
        self.assertFalse(auth_settings.client_registration_options.enabled)
        self.assertTrue(auth_settings.revocation_options.enabled)

if __name__ == "__main__":
    unittest.main(verbosity=2)