#!/usr/bin/env bash
# Idempotent local development environment bootstrap for StrongChat.
# Installs system dependencies, creates a Python .venv, installs requirements,
# and creates/seeds the local SQLite database.

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
    log "Database created."
else
    log "Database already exists; skipping schema creation."
fi

log "Seeding message types..."
"$PYTHON" scripts/populate_message_types.py --db-path "$DB_PATH"
"$PYTHON" scripts/migrate_pipeline_message_types.py --db-path "$DB_PATH"

log "Environment setup complete."
log "Activate the virtual environment with: source $VENV_DIR/bin/activate"
