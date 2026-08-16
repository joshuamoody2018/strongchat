#!/usr/bin/env bash
# Generate the static OAuth 2.0 client_id + client_secret used by the
# single-user StrongChat authorization server (src/oauth/provider.py).
#
# In Option 1 (static-credentials) deployment, every OAuth client (claude.ai
# web custom-connector, MCP Inspector, curl-based smoke tests) must be
# configured with THIS client_id + client_secret — not generated per-client
# like in RFC 7591 dynamic client registration. The deploy owner pastes
# these into each client's static-creds config.
#
# Idempotent: skips if either ~/.strongchat_oauth_client_id or
# ~/.strongchat_oauth_client_secret already exists, so clients you've
# already onboarded keep working across re-runs. Safe to re-run after
# deploy/bootstrap.sh — neither script overwrites existing creds.
#
# Standalone usage:
#   ./scripts/generate_oauth_client_credentials.sh
#   ./scripts/generate_oauth_client_credentials.sh --print    # also echo
#   ./scripts/generate_oauth_client_credentials.sh --force    # rotate both
#
# After generation, export the values into your shell so the MCP server
# picks them up:
#   export STRONGCHAT_OAUTH_CLIENT_ID="$(cat ~/.strongchat_oauth_client_id)"
#   export STRONGCHAT_OAUTH_CLIENT_SECRET="$(cat ~/.strongchat_oauth_client_secret)"
# …or add the same lines to .env (next to STRONGCHAT_OAUTH_SIGNING_KEY and
# STRONGCHAT_PUBLIC_URL). See scripts/print_oauth_client_credentials.sh for
# retrieval after rotation.
#
# Rotation: rotate BOTH at once. Any client (claude.ai, MCP Inspector, etc.)
# configured with the old pair will need re-pasting.

set -euo pipefail

log()  { echo "[oauth-cred] $*"; }
warn() { echo "[oauth-cred] WARNING: $*" >&2; }
err()  { echo "[oauth-cred] ERROR: $*" >&2; }

ID_PATH="${HOME}/.strongchat_oauth_client_id"
SECRET_PATH="${HOME}/.strongchat_oauth_client_secret"
PRINT_TO_STDOUT=0
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --print)  PRINT_TO_STDOUT=1 ;;
        --force)  FORCE=1 ;;
        --id-path=*)    ID_PATH="${arg#--id-path=}" ;;
        --secret-path=*) SECRET_PATH="${arg#--secret-path=}" ;;
        -h|--help)
            sed -n '2,28p' "$0"
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
# Idempotent guard: never overwrite existing creds (every OAuth client
# configured against them — claude.ai's connector, MCP Inspector, curl
# smoke tests — would silently break). Use --force to rotate.
# ---------------------------------------------------------------------------
if [[ ( -e "$ID_PATH" || -e "$SECRET_PATH" ) && $FORCE -eq 0 ]]; then
    if [[ -e "$ID_PATH" || -e "$SECRET_PATH" ]]; then
        log "credentials already exist — skipping."
        log "  id_path=$ID_PATH (exists=$([ -e "$ID_PATH" ] && echo yes || echo no))"
        log "  secret_path=$SECRET_PATH (exists=$([ -e "$SECRET_PATH" ] && echo yes || echo no))"
        log "rotate with --force (invalidates every OAuth client mid-flight)."
        if [[ $PRINT_TO_STDOUT -eq 1 ]]; then
            [[ -e "$ID_PATH"    ]] && cat "$ID_PATH"
            [[ -e "$SECRET_PATH" ]] && cat "$SECRET_PATH"
        fi
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Generate. client_id is 16 random bytes → 22-char URL-safe string. Long
# enough to be globally unique per deploy without being awkward to paste
# into claude.ai's connector UI; not so long that copy-paste breaks.
# client_secret is 32 random bytes → 43-char URL-safe string. RFC 6749
# §A.10 RECOMMENDS ≥128 bits of entropy for client secrets; we exceed.
# ---------------------------------------------------------------------------
NEW_ID="$(python3 -c 'import secrets; print(secrets.token_urlsafe(16))')"
NEW_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

umask 077
printf '%s\n' "$NEW_ID"     > "$ID_PATH"
printf '%s\n' "$NEW_SECRET" > "$SECRET_PATH"
chmod 600 "$ID_PATH" "$SECRET_PATH"

log "wrote $ID_PATH     (chmod 600, $(wc -c < "$ID_PATH") bytes)"
log "wrote $SECRET_PATH (chmod 600, $(wc -c < "$SECRET_PATH") bytes)"
log "next step: export STRONGCHAT_OAUTH_CLIENT_ID + STRONGCHAT_OAUTH_CLIENT_SECRET, or add them to .env"
log "  export STRONGCHAT_OAUTH_CLIENT_ID=\"\$(cat $ID_PATH)\""
log "  export STRONGCHAT_OAUTH_CLIENT_SECRET=\"\$(cat $SECRET_PATH)\""
log "paste them into claude.ai's custom-connector OAuth settings:"

if [[ $PRINT_TO_STDOUT -eq 1 ]]; then
    printf '\n%s\n%s\n' "$NEW_ID" "$NEW_SECRET"
else
    printf '\n  client_id     = %s\n  client_secret = %s\n' "$NEW_ID" "$NEW_SECRET"
fi
