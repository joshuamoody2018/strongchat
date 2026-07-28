## README.md repository-focused rewrite

- Replaced the server-specific "Development Environment Setup" and "Quick Start" sections with a project overview, installation via `scripts/setup_environment.sh`, usage examples, and test commands.
- Removed references to SSH, Contabo, VPS, Windows Terminal, tmux, and neovim.
- Removed the stale "Open Items" checklist.
- Kept "Contributing & Licensing" at the top per project requirement.
- Referenced `tests/scripts/` and `tests/system/` as requested, though `tests/scripts/` does not currently exist in the working tree.
- Verified with `grep -iE 'ssh|contabo|server-setup|vps|windows terminal|tmux|neovim'` returns no matches.

## 2026-07-29 — Added `scripts/setup_environment.sh`

- Created an idempotent environment bootstrap script.
- Installs apt packages (`python3-venv`, `python3-pip`, `build-essential`, `curl`) only if missing.
- Creates `.venv`, upgrades pip, installs `requirements.txt`.
- Creates `data/chat_database.db` if missing and seeds it via `scripts/populate_message_types.py` and `scripts/migrate_pipeline_message_types.py`.
- Uses `set -euo pipefail`, prints progress messages, and avoids server connection details, API keys, and `pip --break-system-packages`.
- Verified: `bash -n scripts/setup_environment.sh` passes; running the script produces a working `.venv` and a populated `data/chat_database.db` (9 message types, 111 messages).
- `shellcheck` was not available in this environment (no passwordless sudo), so it could not be run; the script is written with quoted variables and safe patterns.

## 2026-07-29: Move script-style tests from scripts/ to tests/scripts/

- Relocated all 12 `scripts/test_*.py` files to `tests/scripts/` using `git mv` so Git tracks the rename.
- Updated the `sys.path` bootstrap in every moved test from `os.path.join(os.path.dirname(__file__), '..', 'src')` to `os.path.join(os.path.dirname(__file__), '..', '..', 'src')` (and the double-quoted equivalent) so the scripts still resolve `src/` from the new deeper directory.
- `tests/scripts/test_migration.py` required two extra path adjustments because it imports `migrate_pipeline_message_types` (which stays in `scripts/`) and copies the live DB:
  - `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))`
  - `LIVE_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'chat_database.db')`
- Verified `OPENROUTER_API_KEY` is unset for all runs; each test supplies its own dummy key or mocks the LLM client.
- Ran every moved test and confirmed exit code 0:
  - `test_database_queries.py`
  - `test_database_port.py`
  - `test_embedding_service.py`
  - `test_hyde_schema.py`
  - `test_hyde_service.py`
  - `test_intent_schema.py`
  - `test_intent_service.py`
  - `test_llm_framework.py`
  - `test_migration.py`
  - `test_parser.py`
  - `test_pipeline_offline.py`
  - `test_retrieval_service.py`
- Confirmed no `test_*.py` files remain in `scripts/`.
- Committed as `1fdd39c` with message: "Move script-style tests from scripts/ to tests/scripts/".

