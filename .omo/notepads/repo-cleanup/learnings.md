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

## 2026-07-29: Update README test instructions for direct invocation

- Updated `README.md` testing section to show direct script invocation using `.venv/bin/python tests/scripts/<file>.py` and `.venv/bin/python tests/system/<file>.py`, plus top-level `unittest` commands.
- Updated `tests/README.md` to describe the three test categories (integration, script, system), list the 12 script-style tests under `tests/scripts/`, and replace all pytest-based commands with direct invocation examples.
- Verified `grep -iE 'pytest' README.md` returns no matches and `tests/README.md` no longer claims pytest is required for script-style tests.
- Staged only `README.md` and `tests/README.md`; committed with message: "Fix README test commands and document tests/scripts/ layout".

## 2026-07-29: Final Verification Wave F2 — Test execution audit

- Verdict: **APPROVE**.
- Ran all 12 `tests/scripts/test_*.py` files with `OPENROUTER_API_KEY=` unset; each exited 0:
  - `tests/scripts/test_database_port.py` exit 0
  - `tests/scripts/test_database_queries.py` exit 0
  - `tests/scripts/test_embedding_service.py` exit 0
  - `tests/scripts/test_hyde_schema.py` exit 0
  - `tests/scripts/test_hyde_service.py` exit 0
  - `tests/scripts/test_intent_schema.py` exit 0
  - `tests/scripts/test_intent_service.py` exit 0
  - `tests/scripts/test_llm_framework.py` exit 0
  - `tests/scripts/test_migration.py` exit 0
  - `tests/scripts/test_parser.py` exit 0
  - `tests/scripts/test_pipeline_offline.py` exit 0
  - `tests/scripts/test_retrieval_service.py` exit 0
- Ran `tests/system/test_intent_generation.py` with the environment's OpenRouter key; exit 0, result: PASS (3 probes passed).
- No failing tests; no files modified.

## 2026-07-29 — Final Verification Wave F3: README/setup script audit

- **Criterion (a)**: `grep -iE 'ssh|contabo|server-setup|vps|windows terminal|tmux|neovim' README.md` returned no matches.
- **Criterion (b)**: README.md contains a project description ("StrongChat is a Bible verse retrieval and answer synthesis system..."), installation via `bash scripts/setup_environment.sh`, a usage example (`.venv/bin/python scripts/run_pipeline.py "your question"`), and testing instructions (`tests/scripts/`, `tests/system/`, and `unittest` sections).
- **Criterion (c)**: `bash -n scripts/setup_environment.sh` returned no errors.
- **Criterion (d)**: A naive substring grep for `ssh|ip|hostname|root@|contabo|vps` matched only benign occurrences inside `pip`/`pipefail`; a word-boundary grep for these terms returned no matches, confirming no server connection details are present.
- **Verdict**: APPROVE.

## 2026-07-29: Final Verification Wave F1 — File layout audit

Verdict: **APPROVE**

Evidence:
- `scripts/test_*.py` glob returns no matches; no test files remain in `scripts/`.
- `tests/scripts/` contains all 12 expected files:
  - test_database_port.py, test_database_queries.py, test_embedding_service.py,
  - test_hyde_schema.py, test_hyde_service.py, test_intent_schema.py,
  - test_intent_service.py, test_llm_framework.py, test_migration.py,
  - test_parser.py, test_pipeline_offline.py, test_retrieval_service.py
- `scripts/` still contains the required non-test scripts:
  - check_database.py, check_embeddings_api.py,
  - create_database.py, create_new_database.py,
  - populate_message_types.py, ingest_corpus.py,
  - run_pipeline.py, download_bible_corpus.py, migrate_pipeline_message_types.py
- Bootstrap paths in moved tests reach `src/` from `tests/scripts/`:
  - Sample `tests/scripts/test_intent_service.py`: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))`
  - Sample `tests/scripts/test_migration.py`: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))` and `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))`
- `notes/server-setup.md` exists.
- `.gitignore` line 1-2 contains `# Private notes and configuration` and `notes/`, and `git check-ignore notes/server-setup.md` returns `notes/server-setup.md`.

