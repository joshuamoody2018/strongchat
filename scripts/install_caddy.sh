#!/usr/bin/env bash
# Install Caddy via the official Cloudsmith stable apt repo (Debian/Ubuntu).
#
# Idempotent: skips if `caddy` is already on PATH. Safe to re-run.
# Non-fatal: returns 0 on "already installed" / "wrong platform" so
# callers (setup_environment.sh) can chain it without breaking on
# boxes where the install isn't applicable.
#
# Standalone usage:
#   ./scripts/install_caddy.sh
#
# Called from scripts/setup_environment.sh after the dev environment
# is ready, behind an interactive prompt. Also reachable directly
# if you decide later you want public exposure on a box that was
# initially set up local-only.
#
# Prerequisites (assumed present from setup_environment.sh):
#   curl, apt-get, sudo (when not root).

set -euo pipefail

log()  { echo "[caddy] $*"; }
warn() { echo "[caddy] WARNING: $*" >&2; }
err()  { echo "[caddy] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
if command -v caddy >/dev/null 2>&1; then
    log "already installed at $(command -v caddy) — skipping."
    exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
    warn "no apt-get — this isn't Debian/Ubuntu."
    warn "Install Caddy manually for your platform:"
    warn "  https://caddyserver.com/docs/install"
    exit 0
fi

# ---------------------------------------------------------------------------
# Privilege helper
# ---------------------------------------------------------------------------
if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
log "Installing Caddy via the official Cloudsmith stable repo (Debian/Ubuntu)..."

# The Cloudsmith repo setup needs the keyring + apt-transport-https
# prerequisites. curl is installed earlier by setup_environment.sh, but
# be defensive in case this script is run standalone on a minimal box.
$SUDO apt-get install -y \
    debian-keyring debian-archive-keyring apt-transport-https curl \
    2>/dev/null || true

curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | $SUDO gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg

curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | $SUDO tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null

$SUDO apt-get update -qq
$SUDO apt-get install -y caddy

log "installed: $(command -v caddy 2>/dev/null || echo 'path unknown')"
log "next: ./deploy/bootstrap.sh  (generates API key, renders Caddyfile, prints next steps)"