# Public MCP deployment (sslip.io + Caddy + bearer auth)

This directory reverse-proxies the StrongChat streamable-HTTP MCP server
to a public HTTPS URL with an automatic Let's Encrypt cert via Caddy's
**on-demand TLS**. Bearer auth is enforced by the MCP backend itself (see
`src/auth.py`), so Caddy is pure TLS + reverse proxy — single source of
truth for the shared key.

## TL;DR — bring up a public test endpoint in ~2 minutes

1. **Generate** a strong shared API key once, save it somewhere:

   ```sh
   python -c "import secrets; print(secrets.token_urlsafe(32))" \
     > ~/.strongchat_api_key
   chmod 600 ~/.strongchat_api_key
   ```

2. **Boot the MCP server** on `127.0.0.1` only (NOT `0.0.0.0` — Caddy is
   the only public surface):

   ```sh
   STRONGCHAT_MCP_TRANSPORT=http \
   STRONGCHAT_HOST=127.0.0.1 \
   STRONGCHAT_PORT=8765 \
   STRONGCHAT_API_KEY="$(cat ~/.strongchat_api_key)" \
   STRONGCHAT_PUBLIC_URL="https://strongchat.YOURPUBLICHOST.sslip.io" \
   .venv/bin/python src/server.py
   ```

   Leave it running in this terminal (or wrap with `systemd` /
   `pm2` / `nohup` — see the "Production hardening" section below).

3. **Point sslip.io at your box**. If your server has a public IPv4
   address (say `203.0.113.42`), the host
   `https://strongchat.203.0.113.42.sslip.io/` resolves to that IP and
   is served from your box. (See <https://sslip.io> for the full set of
   wildcard patterns; in short, anything that ends in `.A.B.C.D.sslip.io`
   resolves to `A.B.C.D`.)

   Replace `YOURPUBLICHOST` in `deploy/Caddyfile` accordingly OR invoke
   Caddy with `-adapter caddyfile --config deploy/Caddyfile` after
   substituting. For a more permanent hostname you control DNS for, swap
   in your own FQDN and skip sslip.io entirely — the on-demand-TLS
   behaviour is identical.

4. **Run Caddy** in another terminal (install once:

   `apt install caddy` / `brew install caddy` / `xcaddy`):

   ```sh
   caddy run --config deploy/Caddyfile
   ```

   On the first request to `https://strongchat.203.0.113.42.sslip.io/mcp`
   Caddy will hit Let's Encrypt's ACME directory, obtain a cert, and
   cache it under Caddy's storage directory. Renewals are automatic.

5. **Test** with curl — you'll need both the cert (which curl gets via
   the system trust store automatically) AND the bearer header, OR you
   get a `401`:

   ```sh
   curl -s -X POST \
     -H "Authorization: Bearer $(cat ~/.strongchat_api_key)" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
          "params":{"protocolVersion":"2025-11-25","capabilities":{},
          "clientInfo":{"name":"smoke","version":"1.0"}}}' \
     https://strongchat.203.0.113.42.sslip.io/mcp
   ```

   Expect a `200 OK` with `text/event-stream` and the initialize result
   in the SSE body. Without the `Authorization` header (or with a wrong
   key), expect a `401`.

## Pointing clients at the public endpoint

### opencode

[opencode](https://opencode.ai) speaks MCP over HTTP natively and lets
you paste a bearer into the server definition. Add to your opencode config:

```json
{
  "mcpServers": {
    "strongchat-remote": {
      "url": "https://strongchat.203.0.113.42.sslip.io/mcp",
      "headers": { "Authorization": "Bearer <paste key here>" }
    }
  }
}
```

### Claude Desktop

Claude Desktop's `claude_desktop_config.json` supports remote streamable-HTTP
MCP servers with a static bearer. (Static bearer support landed in MCP
client JSON config — see the Anthropic MCP docs for the exact schema; the
shape is the same as opencode's.)

```json
{
  "mcpServers": {
    "strongchat-remote": {
      "url": "https://strongchat.203.0.113.42.sslip.io/mcp",
      "headers": { "Authorization": "Bearer <paste key here>" }
    }
  }
}
```

Stdio mode (local `python src/server.py` launched as a subprocess by Claude
Desktop) also still works and is unchanged from the previous Phase A setup.

### curl (manual smoke)

See the TL;DR above. The two-step `initialize` -> `tools/call` handshake is
fiddly to do by hand with curl; the included
`tests/system/test_mcp_server_http.py` exercises the same handshake via
the official `mcp.client.streamable_http` Python SDK if you want a
script-based sanity check.

## ⚠️ Important caveat: claude.ai (the web-hosted chat)* does NOT work
## with a static bearer key alone

The hosted **claude.ai custom connectors** menu (web app) expects an
OAuth 2.0 PKCE authorization-server flow — it discovers the issuer via
`GET /.well-known/oauth-authorization-server` and needs the server to
expose `/authorize`, `/token`, and `/register` endpoints that issue
scoped, short-lived tokens claude.ai stores via `mcp-session-id`.

This deploy configures the **resource-server** side only
(`/.well-known/oauth-protected-resource` is auto-served by the MCP SDK
when `STRONGCHAT_API_KEY` + `STRONGCHAT_PUBLIC_URL` are set; it tells
clients "I expect a bearer from issuer X"). What's MISSING is the
**authorization-server** side — the actual `/authorize` + `/token` flow
that issues those tokens.

Until the OAuth-issuer side is wired (see the "What's left for full
claude.ai web OAuth support" section below), the public endpoint
legitimately rejects any client that doesn't already possess the static
bearer **on every request**. That covers opencode / Claude Desktop / curl,
which let you paste the key into config. The hosted claude.ai web
custom-connector flow is the only major consumer that needs the full
OAuth flow instead, because the web app does its own onboarding dance.

**To test against claude.ai (web) right now:** use one of the working
clients (opencode / Claude Desktop). The StrongChat pipeline is identical
across transports — the static bearer simply means claude.ai web can't
self-onboard; it doesn't restrict the actual retrieval work.

### What's left for full claude.ai web OAuth support (follow-up work)

The MCP SDK already supports the authorization-server side as a
construction-time plugin:

```python
from mcp.server.auth.provider import OAuthAuthorizationServerProvider

mcp = MCPServer(
    auth=AuthSettings(issuer_url=..., resource_server_url=...),
    auth_server_provider=YourProvider(),
    # NOTE: token_verifier becomes optional — the SDK uses the provider
    #       for both issuing AND verifying tokens.
)
```

`YourProvider` would implement:

- token issuance via PKCE flow (returns short-lived JWTs)
- `/register` (RFC 7591 dynamic client registration)
- client lifecycle / token revocation surface

The user-management backing for this (what counts as a "user", how
they log in, what scopes they get) is project-specific and was
deliberately not built for the static-key phase. If/when you need full
claude.ai web custom-connector support, this is the work — the bearer
guardrails from `src/auth.py` are designed so adding it is a strict
**additive** change (you set `auth_server_provider` instead of
`token_verifier`, and the SDK auto-exposes the OAuth metadata endpoints
on the same base URL).

## Production hardening (optional — beyond personal testing)

| Concern | Cheap option | Robust option |
|---|---|---|
| Process supervision | `systemd` service file in `deploy/strongchat.service` (TODO) | container orchestration (systemd-nspawn, k8s, Nomad) |
| Key rotation | Restart the MCP server with a new `STRONGCHAT_API_KEY` | Hashicorp Vault sidecar fetching short-lived keys |
| Abuse / cert issuance rate limit | Add Caddy's `on_demand_tls { ask <url> }` gate (see Caddyfile) | Use a fixed DNS name + standard cert issuance |
| Audit log shipping | JSONL goes to `data/logs/strongchat.log`; any filebeat/vector | systemd journal → Loki / Datadog |
| Bandwidth abuse | Caddy rate-limit module, or front with Cloudflare | DDoS-protected origin |

## Files in this directory

| File | Purpose |
|---|---|
| `Caddyfile` | Caddy reverse-proxy + on-demand TLS + sane TLS-response headers. Adjustable host substring `YOURPUBLICHOST`. |
| `README.md` | This file. |

The scripts `scripts/setup_environment.sh` and `scripts/ingest_corpus.py`
still build the read-only `data/chroma/` + `data/macula_index.db` assets
that `src/server.py` reads; the deploy here assumes those are already built
locally (they don't change between boot/restart unless you re-ingest).