# Public MCP deployment (sslip.io + Caddy + bearer or OAuth auth)

This directory reverse-proxies the StrongChat streamable-HTTP MCP server
to a public HTTPS URL with an automatic Let's Encrypt cert via Caddy's
**on-demand TLS**. Authentication (bearer key or OAuth 2.0 PKCE) is
enforced by the MCP backend itself — Caddy is pure TLS + reverse proxy.

> **Status today:** the server defaults to **stdio** and binds to
> **`127.0.0.1:8765`** in HTTP mode. Nothing is exposed to the internet
> until you (a) run `deploy/bootstrap.sh`, (b) start the MCP server in
> HTTP mode, AND (c) start Caddy. With no `STRONGCHAT_API_KEY` /
> `STRONGCHAT_PUBLIC_URL` / `STRONGCHAT_OAUTH_SIGNING_KEY` in your
> `.env` (the default), authentication is **disabled** — but so is any
> public surface, because Caddy isn't running and the backend is
> loopback-only.

## TL;DR — the scripted path (recommended)

`deploy/bootstrap.sh` is idempotent and safe to re-run. It:

1. Generates a 32-byte URL-safe API key at `~/.strongchat_api_key`
   (chmod 600) — **never overwrites** an existing one, so clients
   you've already configured keep working across re-runs.
2. Runs `scripts/generate_oauth_signing_key.sh` to mint
   `~/.strongchat_oauth_signing_key` (256-bit HS256 secret, distinct
   from the bearer key above). Same idempotent / never-overwrite rule.
3. Runs `scripts/generate_oauth_client_credentials.sh` to mint the
   static `~/.strongchat_oauth_client_id` +
   `~/.strongchat_oauth_client_secret` (Option 1: no DCR — see below).
4. Auto-detects this box's public IPv4 (or accepts `PUBLIC_IP=...` /
   `STRONGCHAT_HOSTNAME=...` overrides) and builds the sslip.io
   hostname `https://strongchat.<A.B.C.D>.sslip.io`.
5. Renders `deploy/Caddyfile.local` from the template (the template
   stays untouched; `Caddyfile.local` is gitignored).
6. Appends / updates `STRONGCHAT_API_KEY` + `STRONGCHAT_PUBLIC_URL` +
   `STRONGCHAT_OAUTH_SIGNING_KEY` + `STRONGCHAT_OAUTH_CLIENT_ID` +
   `STRONGCHAT_OAUTH_CLIENT_SECRET` in `.env` (loaded automatically by
   `src/server.py` at boot via `python-dotenv`; `.env` is gitignored,
   never committed).
7. Prints the exact next-step commands (start MCP server, start Caddy,
   smoke-test with curl, opencode/Claude Desktop config snippet, the
   OAuth creds to paste into claude.ai's connector).

```sh
# from the repo root, on the box that will host the public endpoint:
./deploy/bootstrap.sh
# or, with overrides:
PUBLIC_IP=203.0.113.42 ./deploy/bootstrap.sh
STRONGCHAT_HOSTNAME=strongchat.example.com ./deploy/bootstrap.sh   # skip sslip.io
```

Then follow the printed next steps. Full reference for each step +
the claude.ai web OAuth onboarding flow + production hardening is
below.

### Where secrets live (and how to retrieve them)

| Location | What | How to read it |
|---|---|---|
| `~/.strongchat_api_key` | the bearer API key (chmod 600) | `cat ~/.strongchat_api_key` |
| `~/.strongchat_oauth_signing_key` | the OAuth JWT signing key (chmod 600). **Distinct** from the bearer key above; never reuse one for the other. | `cat ~/.strongchat_oauth_signing_key` |
| `~/.strongchat_oauth_client_id` + `~/.strongchat_oauth_client_secret` | the static OAuth client creds (Option 1: every OAuth client must use these) | `./scripts/print_oauth_client_credentials.sh` |
| `.env` (repo root, gitignored) | `STRONGCHAT_API_KEY` + `STRONGCHAT_PUBLIC_URL` + `STRONGCHAT_OAUTH_SIGNING_KEY` + `STRONGCHAT_OAUTH_CLIENT_ID` + `STRONGCHAT_OAUTH_CLIENT_SECRET` | `grep STRONGCHAT .env` |
| Caddy's cert storage (`/var/lib/caddy` by default) | Let's Encrypt cert for the sslip.io hostname | managed automatically by Caddy; no manual handling |

To paste the bearer key into opencode / Claude Desktop / any client
config: `cat ~/.strongchat_api_key`. To paste the OAuth creds into
claude.ai's connector: `./scripts/print_oauth_client_credentials.sh`.

To **rotate** any secret: delete the relevant file (e.g.
`rm ~/.strongchat_api_key`), remove the corresponding `STRONGCHAT_*`
line(s) from `.env`, rerun `./deploy/bootstrap.sh` (or the specific
`scripts/generate_oauth_*.sh` for OAuth secrets), then restart the MCP
server and update any client configs that had the old value.

## Manual path (if you can't run the script)

1. **Generate** the bearer secret + OAuth signing key + OAuth client
   creds, save each in its own file:

   ```sh
   python -c "import secrets; print(secrets.token_urlsafe(32))" \
     > ~/.strongchat_api_key
   chmod 600 ~/.strongchat_api_key

   ./scripts/generate_oauth_signing_key.sh
   ./scripts/generate_oauth_client_credentials.sh
   ./scripts/print_oauth_client_credentials.sh   # capture these for claude.ai
   ```

2. **Boot the MCP server** on `127.0.0.1` only (NOT `0.0.0.0` — Caddy
   is the only public surface):

   ```sh
   STRONGCHAT_MCP_TRANSPORT=http \
   STRONGCHAT_HOST=127.0.0.1 \
   STRONGCHAT_PORT=8765 \
   STRONGCHAT_API_KEY="$(cat ~/.strongchat_api_key)" \
   STRONGCHAT_OAUTH_SIGNING_KEY="$(cat ~/.strongchat_oauth_signing_key)" \
   STRONGCHAT_OAUTH_CLIENT_ID="$(cat ~/.strongchat_oauth_client_id)" \
   STRONGCHAT_OAUTH_CLIENT_SECRET="$(cat ~/.strongchat_oauth_client_secret)" \
   STRONGCHAT_PUBLIC_URL="https://strongchat.YOURPUBLICHOST.sslip.io" \
   .venv/bin/python src/server.py
   ```

   Leave it running in this terminal (or wrap with `systemd` /
   `pm2` / `nohup` — see the "Production hardening" section below).

3. **Point sslip.io at your box**. If your server has a public IPv4
   address (say `203.0.113.42`), the host
   `https://strongchat.203.0.113.42.sslip.io/` resolves to that IP and
   is served from your box. (See <https://sslip.io> for the full set
   of wildcard patterns; in short, anything that ends in
   `.A.B.C.D.sslip.io` resolves to `A.B.C.D`.)

   Replace `YOURPUBLICHOST` in `deploy/Caddyfile` accordingly OR
   invoke Caddy with `-adapter caddyfile --config deploy/Caddyfile`
   after substituting. For a more permanent hostname you control DNS
   for, swap in your own FQDN and skip sslip.io entirely — the
   on-demand-TLS behaviour is identical.

4. **Run Caddy** in another terminal (install once:
   `./scripts/install_caddy.sh` (Debian/Ubuntu, idempotent) /
   `brew install caddy` (macOS) / `xcaddy` /
   <https://caddyserver.com/docs/install>):

   ```sh
   caddy run --config deploy/Caddyfile
   ```

   On the first request to `https://strongchat.203.0.113.42.sslip.io/mcp`
   Caddy will hit Let's Encrypt's ACME directory, obtain a cert, and
   cache it under Caddy's storage directory. Renewals are automatic.

5. **Test** with curl — bearer path needs the `Authorization` header,
   OAuth path needs nothing (the MCP server returns 401 until it sees
   a valid bearer, either the static key OR a JWT issued by the OAuth
   provider):

   ```sh
   # Bearer path (opencode / Claude Desktop / curl with the static key):
   curl -s -X POST \
     -H "Authorization: Bearer $(cat ~/.strongchat_api_key)" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
          "params":{"protocolVersion":"2025-11-25","capabilities":{},
          "clientInfo":{"name":"smoke","version":"1.0"}}}' \
     https://strongchat.203.0.113.42.sslip.io/mcp
   # OAuth metadata path (the URL the claude.ai connector probes):
   curl -s https://strongchat.203.0.113.42.sslip.io/.well-known/oauth-authorization-server
   ```

   The first command returns `200 OK` with `text/event-stream` and
   the initialize result. Without the `Authorization` header (or with
   a wrong key) you get `401`. The second command returns the OAuth
   authorization-server metadata document the MCP SDK auto-serves.

## Pointing clients at the public endpoint

### opencode

[opencode](https://opencode.ai) speaks MCP over HTTP natively and lets
you paste a bearer into the server definition. Add to your opencode
config:

```json
{
  "mcpServers": {
    "strongchat-remote": {
      "url": "https://strongchat.203.0.113.42.sslip.io/mcp",
      "headers": { "Authorization": "Bearer <paste `cat ~/.strongchat_api_key`>" }
    }
  }
}
```

### Claude Desktop (static bearer)

Claude Desktop's `claude_desktop_config.json` supports remote
streamable-HTTP MCP servers with a static bearer. (Static bearer
support landed in MCP client JSON config — see the Anthropic MCP docs
for the exact schema; the shape is the same as opencode's.)

```json
{
  "mcpServers": {
    "strongchat-remote": {
      "url": "https://strongchat.203.0.113.42.sslip.io/mcp",
      "headers": { "Authorization": "Bearer <paste `cat ~/.strongchat_api_key`>" }
    }
  }
}
```

Stdio mode (local `python src/server.py` launched as a subprocess by
Claude Desktop) also still works and is unchanged from the previous
Phase A setup.

### curl (manual smoke)

See the TL;DR above. The two-step `initialize` -> `tools/call`
handshake is fiddly to do by hand with curl; the included
`tests/system/test_mcp_server_http.py` exercises the same handshake
via the official `mcp.client.streamable_http` Python SDK if you want
a script-based sanity check.

### claude.ai (web custom-connector) — OAuth 2.0 PKCE

The hosted **claude.ai web custom-connector** flow does NOT use a
static bearer — it runs the full OAuth 2.0 PKCE authorization-code
flow against the MCP server's built-in authorization-server endpoints.
The MCP SDK auto-mounts these on the same Starlette app as `/mcp` when
`STRONGCHAT_OAUTH_SIGNING_KEY` + `STRONGCHAT_PUBLIC_URL` +
`STRONGCHAT_OAUTH_CLIENT_ID` + `STRONGCHAT_OAUTH_CLIENT_SECRET` are
all set.

**Onboarding flow:**

1. **Run `deploy/bootstrap.sh`** (or the manual path above) so all
   four OAuth env vars land in `.env` alongside the bearer key, and
   the three OAuth secret files exist at
   `~/.strongchat_oauth_{signing_key,client_id,client_secret}`.

2. **Start the MCP server bound to `127.0.0.1` in HTTP mode** with
   those env vars loaded (the systemd unit does this automatically
   via `EnvironmentFile=.env`). The OAuth path takes precedence over
   the static bearer in `_setup_and_build_mcp`, so the server now
   expects OAuth-issued JWTs, not the static bearer key.

3. **Start Caddy** pointing at `deploy/Caddyfile.local`. Caddy is
   pure TLS + reverse proxy — it doesn't care which auth mode the
   backend uses.

4. **Open claude.ai → Settings → Connectors → Add custom connector**
   and fill in:
   - **Connector URL**: `https://strongchat.YOURIP.sslip.io/mcp`
     (the same URL you'd paste into opencode, but with the OAuth
     flow).
   - **OAuth Client ID**: paste `client_id` from
     `./scripts/print_oauth_client_credentials.sh`
   - **OAuth Client Secret**: paste `client_secret` from the same
     command
   - Leave the other connector fields at their defaults (no DCR,
     single-user deploy).
   claude.ai probes
   `https://<host>/.well-known/oauth-authorization-server`, runs the
   `/authorize` → consent screen → `/token` PKCE dance, stores the
   short-lived JWT, and starts calling `retrieve_context` over
   `streamable-http` authenticated as that bearer.

5. **Done.** The MCP server logs the OAuth handshake events at INFO
   level under the `oauth` logger. Subsequent token refreshes are
   transparent (refresh tokens rotate, access tokens are 1h).

**Missing-env error.** If you skip any of the four OAuth env vars
(`STRONGCHAT_OAUTH_SIGNING_KEY` /
`STRONGCHAT_OAUTH_CLIENT_ID` /
`STRONGCHAT_OAUTH_CLIENT_SECRET` / `STRONGCHAT_PUBLIC_URL`),
`load_oauth_config` logs a `WARNING` and disables the OAuth provider.
The server falls back to the static-bearer path (if
`STRONGCHAT_API_KEY` is also set) or no auth (local-only). In either
case, claude.ai's connector probe of
`/.well-known/oauth-authorization-server` returns `404` and the
onboarding UI shows a generic "couldn't reach server" error. The
fix is to set the missing var, restart the MCP server, and retry
the onboarding.

To verify the OAuth metadata is being served before onboarding:
```sh
curl -s https://strongchat.YOURIP.sslip.io/.well-known/oauth-authorization-server | jq .
```
Expect a JSON document with `issuer`, `authorization_endpoint`,
`token_endpoint`, `revocation_endpoint`, and
`scopes_supported: ["strongchat:retrieve_context"]`. If you get `404`
instead, the OAuth provider isn't enabled — check the server boot
logs for the `oauth-provider-disabled` warning.

To **rotate** the OAuth signing key:
`./scripts/generate_oauth_signing_key.sh --force`. Any OAuth client
mid-flight loses its access + refresh tokens and must re-run the
PKCE flow.

To **rotate** the OAuth client creds:
`./scripts/generate_oauth_client_credentials.sh --force`. Every OAuth
client (claude.ai connector, MCP Inspector, etc.) must be
re-configured with the new pair.

## Production hardening (optional — beyond personal testing)

| Concern | Cheap option | Robust option |
|---|---|---|
| Process supervision | `deploy/strongchat.service` systemd unit (see below) | container orchestration (systemd-nspawn, k8s, Nomad) |
| Key rotation | Restart the MCP server with new `STRONGCHAT_*` env vars | Hashicorp Vault sidecar fetching short-lived keys |
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
| `bootstrap.sh` | **The scripted path.** Idempotent — generates bearer key, OAuth signing key, OAuth client creds; detects public IP; renders `Caddyfile.local`; writes all five `STRONGCHAT_*` env vars into `.env`; prints next-step commands and the OAuth creds to paste into claude.ai's connector. Run this first on a fresh box. |
| `Caddyfile` | Caddy reverse-proxy + on-demand TLS + sane TLS-response headers. Adjustable host substring `YOURPUBLICHOST`. Template — bootstrap.sh renders a local copy. |
| `Caddyfile.local` | Rendered artifact (gitignored). The actual file you point Caddy at. |
| `strongchat.service` | Optional systemd unit so the MCP server survives reboot (see "Production hardening"). |
| `README.md` | This file. |

The scripts `scripts/setup_environment.sh` and `scripts/ingest_corpus.py`
still build the read-only `data/chroma/` + `data/macula_index.db` assets
that `src/server.py` reads; the deploy here assumes those are already
built locally (they don't change between boot/restart unless you
re-ingest).
