#!/usr/bin/env bash
# Idempotent local development environment bootstrap for StrongChat.
# Installs system dependencies, creates a Python .venv, installs requirements,
# creates the chat DB, downloads and ingests the Macula Greek corpus + STEPBible TBESG/LSJ lexicons,
# and runs pipeline message-type migrations.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DB_PATH="data/chat_database.db"
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

log "Ensuring SQLite database exists at $DB_PATH..."
if [ ! -f "$DB_PATH" ]; then
    "$PYTHON" scripts/create_new_database.py --db-path "$DB_PATH"
    log "Database created and seeded."
else
    log "Database already exists; skipping schema creation and seeding."
fi

log "Downloading Macula Greek corpus (Clear-Bible/macula-greek, CC BY 4.0)..."
if [ ! -f data/macula/macula-greek.tsv ]; then
    log "Downloading Macula Greek corpus (Clear-Bible/macula-greek, CC BY 4.0)..."
    .venv/bin/python scripts/download_macula_greek.py
else
    log "Macula Greek corpus already present at data/macula/macula-greek.tsv; skipping download."
fi

log "Building Macula Greek SQLite index..."
if ! .venv/bin/python -c "import sqlite3; c = sqlite3.connect('data/macula_index.db'); n = c.execute('SELECT COUNT(*) FROM macula_tokens').fetchone()[0]; import sys; sys.exit(0 if n > 0 else 1)" 2>/dev/null; then
    log "Building Macula Greek SQLite index..."
    .venv/bin/python scripts/build_macula_index.py
    .venv/bin/python scripts/build_strongs_frequency.py
    .venv/bin/python scripts/build_lexicon_index.py
else
    log "Macula index already populated; skipping build."
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

log "Environment setup complete."
log "Macula + Bible data ingested, ChromaDB populated. To re-run: delete data/macula_index.db, data/macula/macula-greek.tsv, data/bible/*.json, or data/chroma/ and re-run this script."
log "Activate the virtual environment with: source $VENV_DIR/bin/activate"
