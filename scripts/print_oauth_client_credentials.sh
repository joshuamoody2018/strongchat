#!/usr/bin/env bash
# Print the static OAuth 2.0 client_id + client_secret that the StrongChat
# authorization server expects every OAuth client to use (Option 1:
# static-credentials deployment — see src/oauth/provider.py).
#
# Use this after running scripts/generate_oauth_client_credentials.sh to
# retrieve the values to paste into your OAuth clients (claude.ai web
# custom-connector, MCP Inspector, curl smoke tests, …).
#
# Standalone usage:
#   ./scripts/print_oauth_client_credentials.sh
#   ./scripts/print_oauth_client_credentials.sh --json   # one-line JSON for scripting
#
# Returns non-zero if either file is missing — run
# scripts/generate_oauth_client_credentials.sh first.

set -euo pipefail

log()  { echo "[oauth-cred] $*"; }
err()  { echo "[oauth-cred] ERROR: $*" >&2; }

ID_PATH="${HOME}/.strongchat_oauth_client_id"
SECRET_PATH="${HOME}/.strongchat_oauth_client_secret"
MODE="text"

for arg in "$@"; do
    case "$arg" in
        --json)   MODE="json" ;;
        --id-path=*)    ID_PATH="${arg#--id-path=}" ;;
        --secret-path=*) SECRET_PATH="${arg#--secret-path=}" ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) err "unknown argument: $arg"; exit 2 ;;
    esac
done

if [[ ! -e "$ID_PATH" ]]; then
    err "client_id file not found at $ID_PATH — run scripts/generate_oauth_client_credentials.sh first."
    exit 1
fi
if [[ ! -e "$SECRET_PATH" ]]; then
    err "client_secret file not found at $SECRET_PATH — run scripts/generate_oauth_client_credentials.sh first."
    exit 1
fi

CLIENT_ID="$(cat "$ID_PATH")"
CLIENT_SECRET="$(cat "$SECRET_PATH")"

case "$MODE" in
    json)
        printf '{"client_id":"%s","client_secret":"%s"}\n' "$CLIENT_ID" "$CLIENT_SECRET"
        ;;
    *)
        cat <<EOF
OAuth 2.0 client credentials for this StrongChat deploy:

  client_id     = ${CLIENT_ID}
  client_secret = ${CLIENT_SECRET}

Paste these into claude.ai's custom-connector OAuth settings
(Settings -> Connectors -> Add custom connector -> OAuth Client ID +
OAuth Client Secret fields), or into MCP Inspector, or any other OAuth
client that connects to this deployment.

Files:
  ${ID_PATH}
  ${SECRET_PATH}
EOF
        ;;
esac
