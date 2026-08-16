# Public MCP deployment (sslip.io + Caddy + bearer auth)

This directory reverse-proxies the StrongChat streamable-HTTP MCP server
to a public HTTPS URL with an automatic Let's Encrypt cert via Caddy's
**on-demand TLS**. Bearer auth is enforced by the MCP backend itself (see
`src/auth.py`), so Caddy is pure TLS + reverse proxy — single source of
truth for the shared key.

> **Status today:** the server defaults to **stdio** and binds to
> **`127.0.0.1:8765`** in HTTP mode. Nothing is exposed to the internet
> until you (a) run `deploy/bootstrap.sh`, (b) start the MCP server in
> HTTP mode, AND (c) start Caddy. With no `STRONGCHAT_API_KEY` /
> `STRONGCHAT_PUBLIC_URL` in your `.env` (the default), the bearer
> middleware is **disabled** — but so is any public surface, because
> Caddy isn't running and the backend is loopback-only.

## TL;DR — the scripted path (recommended)

`deploy/bootstrap.sh` is idempotent and safe to re-run. It:

1. Generates a 32-byte URL-safe API key at `~/.strongchat_api_key`
   (chmod 600) — **never overwrites** an existing one, so clients
   you've already configured keep working across re-runs.
2. Auto-detects this box's public IPv4 (or accepts `PUBLIC_IP=...` /
   `STRONGCHAT_HOSTNAME=...` overrides) and builds the sslip.io
   hostname `https://strongchat.<A.B.C.D>.sslip.io`.
3. Renders `deploy/Caddyfile.local` from the template (the template
   stays untouched; `Caddyfile.local` is gitignored).
4. Appends / updates `STRONGCHAT_API_KEY` + `STRONGCHAT_PUBLIC_URL` in
   `.env` (loaded automatically by `src/server.py` at boot via
   `python-dotenv`; `.env` is gitignored, never committed).
5. Prints the exact next-step commands (start MCP server, start Caddy,
   smoke-test with curl, opencode/Claude Desktop config snippet).

```sh
# from the repo root, on the box that will host the public endpoint:
./deploy/bootstrap.sh
# or, with overrides:
PUBLIC_IP=203.0.113.42 ./deploy/bootstrap.sh
STRONGCHAT_HOSTNAME=strongchat.example.com ./deploy/bootstrap.sh   # skip sslip.io
```

Then follow the printed next steps. Full reference for each step +
the claude.ai web OAuth caveat + production hardening is below.

### Where secrets live (and how to retrieve them)

| Location | What | How to read it |
|---|---|---|
| `~/.strongchat_api_key` | the bearer API key (chmod 600) | `cat ~/.strongchat_api_key` |
| `.env` (repo root, gitignored) | `STRONGCHAT_API_KEY` + `STRONGCHAT_PUBLIC_URL` next to your `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` | `grep STRONGCHAT .env` |
| Caddy's cert storage (`/var/lib/caddy` by default) | Let's Encrypt cert for the sslip.io hostname | managed automatically by Caddy; no manual handling |

To paste the key into opencode / Claude Desktop / any client config:
```sh
cat ~/.strongchat_api_key
```

To **rotate** the key: `rm ~/.strongchat_api_key`, remove the two
`STRONGCHAT_*` lines from `.env`, rerun `./deploy/bootstrap.sh`, then
update any client configs that had the old key.

## Manual path (if you can't run the script)

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

   `./scripts/install_caddy.sh` (Debian/Ubuntu, idempotent) /
   `brew install caddy` (macOS) / `xcaddy` / https://caddyserver.com/docs/install):

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
| Process supervision | `deploy/strongchat.service` systemd unit (see below) | container orchestration (systemd-nspawn, k8s, Nomad) |
| Key rotation | Restart the MCP server with a new `STRONGCHAT_API_KEY` | Hashicorp Vault sidecar fetching short-lived keys |
| Abuse / cert issuance rate limit | Add Caddy's `on_demand_tls { ask <url> }` gate (see Caddyfile) | Use a fixed DNS name + standard cert issuance |
| Audit log shipping | JSONL goes to `data/logs/strongchat.log`; any filebeat/vector | systemd journal → Loki / Datadog |
| Bandwidth abuse | Caddy rate-limit module, or front with Cloudflare | DDoS-protected origin |

### systemd unit for the MCP backend

`deploy/strongchat.service` runs the MCP server in HTTP mode under
systemd so it survives reboot. The unit reads env from `.env` via an
`EnvironmentFile=` directive. Install + enable:

```sh
sudo cp deploy/strongchat.service /etc/systemd/system/
# Make sure the ExecStart path matches your repo location; edit the file
# (or override with `systemctl edit strongchat`) if it differs.
sudo systemctl daemon-reload
sudo systemctl enable --now strongchat
journalctl -u strongchat -f   # tail logs
```

Caddy itself ships with its own systemd unit on most distros (`apt
install caddy`); point it at `deploy/Caddyfile.local` by editing
`/etc/caddy/Caddyfile` to `import /abs/path/to/deploy/Caddyfile.local`.

## Files in this directory

| File | Purpose |
|---|---|
| `bootstrap.sh` | **The scripted path.** Idempotent — generates API key, detects public IP, renders `Caddyfile.local`, writes env vars into `.env`, prints next-step commands. Run this first on a fresh box. |
| `Caddyfile` | Caddy reverse-proxy + on-demand TLS + sane TLS-response headers. Adjustable host substring `YOURPUBLICHOST`. Template — bootstrap.sh renders a local copy. |
| `Caddyfile.local` | Rendered artifact (gitignored). The actual file you point Caddy at. |
| `strongchat.service` | Optional systemd unit so the MCP server survives reboot (see "Production hardening"). |
| `README.md` | This file. |

The scripts `scripts/setup_environment.sh` and `scripts/ingest_corpus.py`
still build the read-only `data/chroma/` + `data/macula_index.db` assets
that `src/server.py` reads; the deploy here assumes those are already built
locally (they don't change between boot/restart unless you re-ingest).