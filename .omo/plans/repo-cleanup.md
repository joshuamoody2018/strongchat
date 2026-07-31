# repo-cleanup - Work Plan

## TL;DR
Clean up repository organization: move test files out of `scripts/` into `tests/scripts/`, remove server-specific setup content from `README.md` (it lives in the already-git-ignored `notes/` folder), improve the README to describe the project, and add a committed environment setup script that installs system/Python dependencies without any server-connection instructions.

## Scope

### Must have
- Move all `scripts/test_*.py` files into `tests/scripts/`.
- Update any relative `sys.path` bootstrap in moved tests so they still find `src/`.
- Verify every moved test still exits 0 (offline tests with key unset; live tests only if key is present and data exists).
- Remove the "Development Environment Setup" and "Quick Start" sections from `README.md` that reference SSH/server setup.
- Improve `README.md`: concise project description, what the pipeline does, directory layout, how to run the setup script, how to run tests, and how to run the pipeline CLI.
- Keep all server-specific/Contabo/SSH/dev-tool instructions in `notes/server-setup.md` (already git-ignored).
- Create `scripts/setup_environment.sh`: installs apt dependencies, creates `.venv`, installs `requirements.txt`, and creates seed DBs. Must NOT contain SSH keys, IP addresses, server hostnames, or connection commands.

### Must NOT have
- NO edits to `.gitignore` (it already ignores `notes/`; leave user's pending changes untouched).
- NO moving non-test scripts out of `scripts/`.
- NO server-specific connection details in the committed setup script.
- NO loss of test coverage when moving files.

## Verification strategy
- After move: each offline test exits 0 with `OPENROUTER_API_KEY` unset.
- `lsp_diagnostics` on `tests/scripts/` and `scripts/setup_environment.sh` returns zero errors.
- `README.md` no longer contains "SSH", "Contabo", "server-setup", or "VPS".
- `scripts/setup_environment.sh` runs with `bash -n` and `shellcheck` (if available).

## Todos
- [x] 1. Move `scripts/test_*.py` into `tests/scripts/` and update bootstrap paths
- [x] 2. Remove server-specific setup sections from `README.md`
- [x] 3. Improve `README.md` with repo-focused content
- [x] 4. Create committed `scripts/setup_environment.sh` for system/Python dependencies
- [x] 5. Update `tests/README.md` to mention the new `tests/scripts/` location

## Final verification wave
- [x] F1. File layout audit
- [x] F2. Test execution audit
- [x] F3. README/setup script audit
