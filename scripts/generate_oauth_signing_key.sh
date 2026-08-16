#!/usr/bin/env bash
# Generate the OAuth 2.0 JWT signing key used by src/oauth/provider.py to
# sign short-lived access tokens issued to the claude.ai web custom-
# connector (and any other OAuth 2.0 PKCE client).
#
# Idempotent: skips if a key already exists at ~/.strongchat_oauth_signing_key,
# so clients you've already onboarded keep working across re-runs. Safe to
# re-run after deploy/bootstrap.sh — neither script overwrites an existing
# key.
#
# Standalone usage:
#   ./scripts/generate_oauth_signing_key.sh
#   ./scripts/generate_oauth_signing_key.sh --print    # also print to stdout
#   ./scripts/generate_oauth_signing_key.sh --force    # overwrite existing
#
# After generation, export it so the MCP server picks it up:
#   export STRONGCHAT_OAUTH_SIGNING_KEY="$(cat ~/.strongchat_oauth_signing_key)"
# …or add the same line to .env (next to STRONGCHAT_API_KEY /
# STRONGCHAT_PUBLIC_URL). The server requires STRONGCHAT_OAUTH_SIGNING_KEY
# AND STRONGCHAT_PUBLIC_URL both set to enable the OAuth authorization-
# server provider (see src/oauth/provider.py:load_oauth_config).
#
# IMPORTANT: this key MUST be distinct from STRONGCHAT_API_KEY
# (the static-bearer secret in src/auth.py). Never reuse one for the other
# — rotating one would silently break the other auth path's clients.
#
# Prerequisites:
#   python3 (any 3.x; uses only the standard library's `secrets` module).

set -euo pipefail

log()  { echo "[oauth-key] $*"; }
warn() { echo "[oauth-key] WARNING: $*" >&2; }
err()  { echo "[oauth-key] ERROR: $*" >&2; }

KEY_PATH="${HOME}/.strongchat_oauth_signing_key"
PRINT_TO_STDOUT=0
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --print)  PRINT_TO_STDOUT=1 ;;
        --force)  FORCE=1 ;;
        --path=*) KEY_PATH="${arg#--path=}" ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *) err "unknown argument: $arg"; exit 2 ;;
    esac
done

# ---------------------------------------------------------------------------
# Guard: python3 on PATH
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found on PATH — install Python 3 first."
    exit 1
fi

# ---------------------------------------------------------------------------
# Idempotent guard: never overwrite an existing key (clients are already
# onboarded against it; rotating invalidates every issued access + refresh
# token in flight).
# ---------------------------------------------------------------------------
if [[ -e "$KEY_PATH" && $FORCE -eq 0 ]]; then
    log "key already exists at $KEY_PATH — skipping."
    log "rotate with --force (invalidates every OAuth client mid-flight)."
    if [[ $PRINT_TO_STDOUT -eq 1 ]]; then
        cat "$KEY_PATH"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# Generate a 256-bit URL-safe secret via Python stdlib `secrets`. The key is
# 43 characters (≈256 bits) by construction; base64url-without-padding of
# 32 random bytes. PyJWT (and the underlying HS256 algorithm) accept any
# length; RFC 7518 §3.2 RECOMMENDS ≥32 bytes for HS256 keys.
# ---------------------------------------------------------------------------
NEW_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

umask 077
printf '%s\n' "$NEW_KEY" > "$KEY_PATH"
chmod 600 "$KEY_PATH"

log "wrote $KEY_PATH (chmod 600, $(wc -c < "$KEY_PATH") bytes)"
log "next step: export STRONGCHAT_OAUTH_SIGNING_KEY or add it to .env"
log "  export STRONGCHAT_OAUTH_SIGNING_KEY=\"\$(cat $KEY_PATH)\""

if [[ $PRINT_TO_STDOUT -eq 1 ]]; then
    printf '%s\n' "$NEW_KEY"
fi
