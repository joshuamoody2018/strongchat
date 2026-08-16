#!/usr/bin/env bash
# Idempotent local development environment bootstrap for StrongChat.
# Installs system dependencies, creates a Python .venv, installs requirements,
# downloads and ingests the Macula Greek + Hebrew
# corpora + STEPBible TBESG/LSJ/TBESH lexicons. There is NO application
# database; the audit trail is the JSONL log under data/logs/.
#
# At the end, prompts to install Caddy (for the public-exposure path in
# deploy/) via scripts/install_caddy.sh. Skip with --no-caddy,
# SKIP_CADDY=1, or by piping input (non-interactive runs always skip
# the prompt and just print the manual-run hint).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR=".venv"
PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

log() {
    echo "[setup] $*"
}

APT_PACKAGES=(
    python3-venv
    python3-pip
    build-essential
    curl
)

check_dependency() {
    case "$1" in
        python3-venv)
            python3 -m venv --help >/dev/null 2>&1
            ;;
        python3-pip)
            python3 -m pip --version >/dev/null 2>&1
            ;;
        build-essential)
            command -v gcc >/dev/null 2>&1
            ;;
        curl)
            command -v curl >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}

missing_packages=()
for pkg in "${APT_PACKAGES[@]}"; do
    if ! check_dependency "$pkg"; then
        missing_packages+=("$pkg")
    fi
done

if [ "${#missing_packages[@]}" -eq 0 ]; then
    log "All apt dependencies already satisfied; skipping apt install."
else
    log "Installing missing apt dependencies: ${missing_packages[*]}"
    if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
        sudo apt-get update -qq
        sudo apt-get install -y "${missing_packages[@]}"
    else
        apt-get update -qq
        apt-get install -y "${missing_packages[@]}"
    fi
fi

log "Creating Python virtual environment at $VENV_DIR if missing..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    log "Virtual environment created."
else
    log "Virtual environment already exists; skipping creation."
fi

log "Upgrading pip..."
"$PIP" install --upgrade pip

log "Installing Python requirements..."
"$PIP" install -r requirements.txt

log "Ensuring data directory exists..."
mkdir -p data

log "Downloading Macula Greek corpus (Clear-Bible/macula-greek, CC BY 4.0)..."
if [ ! -f data/macula/macula-greek.tsv ]; then
    log "Downloading Macula Greek corpus (Clear-Bible/macula-greek, CC BY 4.0)..."
    .venv/bin/python scripts/download_macula_greek.py
else
    log "Macula Greek corpus already present at data/macula/macula-greek.tsv; skipping download."
fi

log "Downloading Macula Hebrew corpus (Clear-Bible/macula-hebrew, CC BY 4.0)..."
if [ ! -f data/macula/macula-hebrew.tsv ]; then
    .venv/bin/python scripts/download_macula_hebrew.py
else
    log "Macula Hebrew corpus already present at data/macula/macula-hebrew.tsv; skipping download."
fi

log "Building Macula SQLite index (Greek + Hebrew)..."
if ! .venv/bin/python -c "import sqlite3, sys; c = sqlite3.connect('data/macula_index.db'); sys.exit(0 if c.execute('SELECT COUNT(*) FROM macula_tokens WHERE book_num < 40').fetchone()[0] > 0 and c.execute('SELECT COUNT(*) FROM macula_tokens WHERE book_num >= 40').fetchone()[0] > 0 else 1)" 2>/dev/null; then
    .venv/bin/python scripts/build_macula_index.py --testament greek
    .venv/bin/python scripts/build_macula_index.py --testament hebrew
    .venv/bin/python scripts/build_strongs_frequency.py --testament greek
    .venv/bin/python scripts/build_strongs_frequency.py --testament hebrew
    .venv/bin/python scripts/build_lexicon_index.py --testament both
else
    log "Macula index already populated with both testaments; skipping build."
fi

log "Downloading Bible corpus (KJV + WEB)..."
if [ ! -f data/bible/kjv.json ]; then
  .venv/bin/python scripts/download_bible_corpus.py
else
  log "Bible corpus already present at data/bible/kjv.json; skipping download."
fi

log "Ingesting Bible corpus into ChromaDB..."
if [ ! -f data/chroma/chroma.sqlite3 ]; then
  .venv/bin/python scripts/ingest_corpus.py
else
  log "ChromaDB already populated at data/chroma/chroma.sqlite3; skipping ingest."
fi

# ---------------------------------------------------------------------------
# Optional: install Caddy for the public-exposure path (deploy/).
# Prompts interactively after dev setup completes. Non-interactive runs
# (piped stdin, CI=1, SKIP_CADDY=1, or --no-caddy) skip the prompt and
# just print the manual-run hint so setup stays non-blocking in CI.
# The actual install lives in scripts/install_caddy.sh (idempotent,
# reusable standalone) so this script stays focused on the dev env.
# ---------------------------------------------------------------------------
if [ "${SKIP_CADDY:-0}" = "1" ] || [ "${1:-}" = "--no-caddy" ]; then
    log "Caddy install skipped (--no-caddy / SKIP_CADDY=1)."
    log "  Run ./scripts/install_caddy.sh later if you want public exposure."
elif [ "${CI:-0}" = "1" ] || ! [ -t 0 ]; then
    # No interactive TTY (piped stdin, CI, etc.) — don't block.
    log "Non-interactive shell detected; skipping Caddy install prompt."
    log "  Run ./scripts/install_caddy.sh later for public-exposure setup."
else
    echo
    read -r -p "[setup] Dev environment ready. Install Caddy for public internet access to this MCP server? [y/N] " _ans
    case "${_ans:-}" in
        y|Y|yes|YES)
            log "Running scripts/install_caddy.sh ..."
            bash "$REPO_ROOT/scripts/install_caddy.sh" \
                || log "Caddy install failed (non-fatal); see scripts/install_caddy.sh output above."
            ;;
        *)
            log "Skipping Caddy install. Run ./scripts/install_caddy.sh later if you change your mind."
            ;;
    esac
fi

log "Environment setup complete."
log "Macula Hebrew + Greek data ingested, ChromaDB populated."
log "No application database is required — audit trail is JSONL at data/logs/strongchat.log"
log "Run the MCP server with: $VENV_DIR/bin/python src/server.py"
log "Run the CLI smoke-test with: $VENV_DIR/bin/python src/main.py \"<query>\""
log "Activate the virtual environment with: source $VENV_DIR/bin/activate"
log "For public exposure (sslip.io + Caddy + bearer auth), run: ./deploy/bootstrap.sh"
