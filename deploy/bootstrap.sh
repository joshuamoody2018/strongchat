#!/usr/bin/env bash
# Public MCP exposure bootstrap for StrongChat.
#
# This script is the "I just cloned the repo on a fresh box and want to
# expose my MCP server to the internet via sslip.io + Caddy + bearer
# auth" path. It is the operational companion to deploy/README.md.
#
# What it does (idempotent — safe to re-run):
#
#   1. Generates a 32-byte URL-safe API key and stores it at
#      ~/.strongchat_api_key (chmod 600). If the file already exists it
#      is left alone so existing clients keep working.
#   2. Detects this box's public IPv4 (via a public echo service) so we
#      can build the sslip.io hostname
#      https://strongchat.<A.B.C.D>.sslip.io that resolves back to us.
#   3. Substitutes that hostname into a rendered deploy/Caddyfile.local
#      (leaving the versioned template deploy/Caddyfile untouched).
#   4. Appends two lines to .env (only if they're not already there):
#        STRONGCHAT_API_KEY=<the key>
#        STRONGCHAT_PUBLIC_URL=https://strongchat.<A.B.C.D>.sslip.io
#      The MCP server auto-picks them up on next boot via load_dotenv().
#   5. Checks whether Caddy and uvicorn are installed and prints clear
#      next-step commands.
#
# What it does NOT do:
#   - Start the MCP server (you do that explicitly so you see the log)
#   - Start Caddy (same reason)
#   - Open firewall ports (host-specific; script just prints what to open)
#   - Anything that requires root
#
# Re-run any time — the only destructive thing it can do is overwrite
# deploy/Caddyfile.local, which is a rendered artifact (gitignored).
#
# Where the secrets live after a successful run:
#
#   ~/.strongchat_api_key           the API key (chmod 600). Cat this to
#                                   paste into opencode / Claude Desktop
#                                   config: `cat ~/.strongchat_api_key`
#   .env                           Loaded by src/server.py at boot via
#                                   python-dotenv. Contains
#                                   STRONGCHAT_API_KEY +
#                                   STRONGCHAT_PUBLIC_URL next to your
#                                   existing OPENROUTER_API_KEY etc.
#                                   (.env is gitignored, never committed.)
#
# Usage:
#   ./deploy/bootstrap.sh                  # public IP auto-detect
#   PUBLIC_IP=203.0.113.42 ./deploy/bootstrap.sh   # override detection
#   STRONGCHAT_HOSTNAME=strongchat.example.com ./deploy/bootstrap.sh
#                                          # skip sslip.io entirely,
#                                          # use your own DNS

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { echo "[bootstrap] $*"; }
warn() { echo "[bootstrap] WARNING: $*" >&2; }
err()  { echo "[bootstrap] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# 1. API key — never overwrite an existing one; clients may be using it.
# ---------------------------------------------------------------------------
KEY_FILE="${STRONGCHAT_KEY_FILE:-$HOME/.strongchat_api_key}"

if [[ -f "$KEY_FILE" ]]; then
  log "API key already present at $KEY_FILE (mode $(stat -c '%a' "$KEY_FILE" 2>/dev/null || stat -f '%A' "$KEY_FILE"))"
  API_KEY="$(cat "$KEY_FILE")"
else
  log "generating a new 32-byte URL-safe API key"
  API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))' \
             || openssl rand -base64 32 | tr -d '\n' \
             || head -c 32 /dev/urandom | base64 | tr -d '\n' | tr '+/' '-_')"
  if [[ -z "${API_KEY:-}" ]]; then
    err "could not generate a key (need python3 OR openssl OR /dev/urandom)"
    exit 1
  fi
  ( umask 077; printf '%s' "$API_KEY" > "$KEY_FILE" )
  chmod 600 "$KEY_FILE"
  log "wrote new API key to $KEY_FILE (chmod 600)"
fi

# Sanity: refuse an empty key file.
if [[ -z "$API_KEY" ]]; then
  err "$KEY_FILE is empty. Delete it and rerun to regenerate."
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Public IP / hostname resolution.
# ---------------------------------------------------------------------------
PUBLIC_URL="${STRONGCHAT_PUBLIC_URL:-}"
HOSTNAME="${STRONGCHAT_HOSTNAME:-}"

if [[ -n "$HOSTNAME" ]]; then
  # User supplied their own DNS name (skip sslip.io).
  PUBLIC_URL="${PUBLIC_URL:-https://$HOSTNAME}"
  log "using user-supplied hostname: $HOSTNAME"
elif [[ -n "$PUBLIC_URL" ]]; then
  log "using user-supplied PUBLIC_URL: $PUBLIC_URL"
else
  # Auto-detect public IPv4 and build an sslip.io hostname off it.
  PUBLIC_IP="${PUBLIC_IP:-}"
  if [[ -z "$PUBLIC_IP" ]]; then
    log "auto-detecting public IPv4 (curl https://api.ipify.org)"
    if command -v curl >/dev/null 2>&1; then
      PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || true)"
    fi
  fi
  if [[ -z "$PUBLIC_IP" ]]; then
    # Fallback to the box's primary outbound IP (LAN address; only useful
    # if your Caddy box is on a routable IP — otherwise sslip.io won't
    # resolve back to you; the script continues and you fix it by hand).
    warn "could not auto-detect public IPv4 (no network?). Falling back"
    warn "to the box's primary outbound IP — only useful if that IP is"
    warn "routable from the open internet. Override with PUBLIC_IP=..."
    warn "or STRONGCHAT_HOSTNAME=..."
    PUBLIC_IP="$(python3 -c 'import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2); 
try:
    s.connect(("8.8.8.8",80)); print(s.getsockname()[0])
except Exception: print("")
finally: s.close()' 2>/dev/null || true)"
    if [[ -z "$PUBLIC_IP" ]]; then
      err "no usable IP detected. Re-run with PUBLIC_IP=x.x.x.x or STRONGCHAT_HOSTNAME=foo.example.com"
      exit 1
    fi
  fi
  HOSTNAME="strongchat.${PUBLIC_IP}.sslip.io"
  PUBLIC_URL="https://${HOSTNAME}"
  log "detected public IP: $PUBLIC_IP"
fi

if [[ "$PUBLIC_URL" != https://* ]]; then
  err "STRONGCHAT_PUBLIC_URL must start with https:// (got: $PUBLIC_URL)"
  exit 1
fi

log "public URL: $PUBLIC_URL"

# ---------------------------------------------------------------------------
# 3. Render deploy/Caddyfile.local from the template.
# ---------------------------------------------------------------------------
CADDY_TEMPLATE="deploy/Caddyfile"
CADDY_LOCAL="deploy/Caddyfile.local"

if [[ ! -f "$CADDY_TEMPLATE" ]]; then
  err "$CADDY_TEMPLATE missing — are you running from the repo root?"
  exit 1
fi

# Substitute YOURHOST (the sslip.io placeholder) and the local backend
# host/port. The template uses strongchat.YOURHOST.sslip.io as the
# canonical "fill me in" form, so replacing that whole string handles
# both sslip.io paths and any user-supplied hostname.
sed -e "s|strongchat\.YOURHOST\.sslip\.io|${HOSTNAME}|g" \
    "$CADDY_TEMPLATE" > "$CADDY_LOCAL"
log "rendered $CADDY_LOCAL (host: ${HOSTNAME})"

# ---------------------------------------------------------------------------
# 4. Append env keys to .env if not already there.
# ---------------------------------------------------------------------------
ENV_FILE=".env"
touch "$ENV_FILE"

ensure_env_line() {
  local key="$1" val="$2"
  # Strip any existing lines for this key (so re-running with a new
  # detected IP / regenerated handle updates cleanly; the API KEY line
  # is preserved by the KEY_FILE guard above and only re-written if the
  # value legitimately changed, which on a fresh key is fine).
  if grep -qE "^${key}=" "$ENV_FILE"; then
    # Update in place.
    python3 - "$ENV_FILE" "$key" "$val" <<'PY'
import sys, os, re
path, key, val = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as f: lines = f.readlines()
out = []
seen = False
for ln in lines:
    if re.match(rf"^{re.escape(key)}=", ln):
        out.append(f"{key}={val}\n"); seen = True
    else:
        out.append(ln)
if not seen: out.append(f"{key}={val}\n")
with open(path, "w") as f: f.writelines(out)
PY
  else
    printf '\n# added by deploy/bootstrap.sh (%s)\n%s=%s\n' "$(date -I)" "$key" "$val" >> "$ENV_FILE"
  fi
}

ensure_env_line "STRONGCHAT_API_KEY"    "$API_KEY"
ensure_env_line "STRONGCHAT_PUBLIC_URL" "$PUBLIC_URL"
log "env vars present in $ENV_FILE (loaded by src/server.py at boot)"

# ---------------------------------------------------------------------------
# 5. Sanity checks + next-steps.
# ---------------------------------------------------------------------------
echo
log "=== sanity ==="
command -v caddy >/dev/null 2>&1 \
  && log "caddy: installed at $(command -v caddy)" \
  || warn "caddy not on PATH. Install:  apt install caddy  |  brew install caddy  |  https://caddyserver.com/docs/install"
command -v .venv/bin/python >/dev/null 2>&1 \
  && log "python venv: .venv/bin/python exists" \
  || warn ".venv/bin/python missing. Run scripts/setup_environment.sh first."

# ---------------------------------------------------------------------------
# 6. Print the canonical "you do this now" instructions.
# ---------------------------------------------------------------------------
cat <<EOF

=== bootstrap complete ===

Where the secret lives:
  ~/.strongchat_api_key            (chmod 600; cat it to paste into clients)
  .env                             STRONGCHAT_API_KEY + STRONGCHAT_PUBLIC_URL
                                   loaded automatically by src/server.py

To paste the API key into opencode / Claude Desktop config:
  cat ~/.strongchat_api_key

NEXT STEPS — do these by hand so you can watch the logs:

  1) Allow inbound 443 through your host firewall (sslip.io + Caddy use
     443; there is no port mapping needed for 8765 because Caddy proxies
     to 127.0.0.1). Example on ufw:
        sudo ufw allow 443/tcp

     If your box is behind a home router / NAT, also forward external
     TCP 443 to this box's LAN IP. (Cloud VMs usually allow 443 by
     default in their security group.)

  2) Start the MCP server (in its own terminal so you can see logs):
        .venv/bin/python src/server.py
     (STRONGCHAT_MCP_TRANSPORT defaults to stdio. Set
     STRONGCHAT_MCP_TRANSPORT=http to expose /mcp on 127.0.0.1:8765
     that Caddy will proxy to.)

        STRONGCHAT_MCP_TRANSPORT=http .venv/bin/python src/server.py

  3) Start Caddy in another terminal:
        caddy run --config deploy/Caddyfile.local

     The first request to ${PUBLIC_URL}/mcp triggers on-demand TLS
     issuance from Let's Encrypt. (Subsequent requests are normal.)

  4) Smoke-test from your laptop (replace the bearer with your key):
        curl -s -X POST \\
          -H "Authorization: Bearer \$(cat ~/.strongchat_api_key)" \\
          -H "Content-Type: application/json" \\
          -H "Accept: application/json, text/event-stream" \\
          -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
                "params":{"protocolVersion":"2025-11-25","capabilities":{},
                "clientInfo":{"name":"smoke","version":"1.0"}}}' \\
          ${PUBLIC_URL}/mcp
     Expect 200 OK with a text/event-stream body containing
     protocolVersion. Without the Authorization header expect 401.

  5) Point an MCP client at it. Example for opencode.json:
        {
          "mcpServers": {
            "strongchat-remote": {
              "url": "${PUBLIC_URL}/mcp",
              "headers": { "Authorization": "Bearer <paste key>" }
            }
          }
        }

rotate the API key later by deleting ~/.strongchat_api_key, removing
the two STRONGCHAT_* lines from .env, and rerunning ./deploy/bootstrap.sh.
EOF