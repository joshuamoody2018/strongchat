# For User Review — hyde-retrieval-pipeline

Significant decisions, deviations, and observations raised during execution. Newest at the bottom. Nothing here blocks the pipeline; each entry notes why it matters.

---

## [2026-07-28 Wave 1] Execution directives recorded
- Proceed without asking permission; bias-for-action; significant items logged in this file.
- Cheap models at low temperature are acceptable for tests as long as outputs adhere to the JSON schemas. Ref rows use `openai/gpt-4.1-mini` (already cheap tier); no change needed.

## [2026-07-28 Task 1] venv bootstrap deviation (no sudo available)
- `python3 -m venv .venv` failed (ensurepip missing; `python3.12-venv` apt package absent) and `sudo` needs a password this session cannot supply.
- Deviation: venv created `--without-pip`, pip bootstrapped via `get-pip.py`. System Python untouched, no `--break-system-packages`.
- If you rebuild the venv elsewhere, prefer `sudo apt install -y python3.12-venv` first. Details in notepad `learnings.md` Task 1.

## [2026-07-28 Task 3] check_embeddings_api.py env-snapshot design (deliberate)
- The smoke script intentionally FAILS (exit 1) when `OPENROUTER_API_KEY` comes only from `.env` and not the calling environment — keeps the `env -u` failure-QA meaningful.
- Consequence: run it with `set -a; . ./.env; set +a` first. Deliberate, not a bug.

## [2026-07-28 Tasks 3-5] LSP unavailable; py_compile substituted
- basedpyright not installed (install previously declined); `lsp_diagnostics` unavailable for Python. Workers used `py_compile` + behavioral tests. Install basedpyright if you want static checks in QA.

## [2026-07-28 Wave 1] Tracked .pyc files in the repo
- `src/services/sqlite/__pycache__/database.cpython-312.pyc` (and likely other `__pycache__` bytecode) is TRACKED in git and flaps on every Python run. Workers never stage it. Recommend `git rm -r --cached **/__pycache__` sometime — not done here (outside plan scope).

## [2026-07-28 Tasks 3-5] Session interruptions recovered cleanly
- Three worker dispatches were interrupted (tool aborts). Recovery: verified on-disk state independently, resumed two stalled sessions, completed todo 4's remainder with a fresh worker. No duplicate commits or conflicts; all on-disk work verified before commit.

## [2026-07-28 Wave 1 checkpoint] Commits so far (all verified: exact paths only, no scope creep)
- `7a96d38` Add project venv and pinned requirements.txt (todo 1)
- `a434510` Fix ref_message_types JOINs and remove dead code (todo 4)
- `54cab26` Add OpenRouter embeddings API smoke check script (todo 3) — carries a Sisyphus co-author trailer; flag if you'd rather not have those
- `a0b6be3` Align database setup scripts with ref_message_types schema (todo 5)
- Todo 2 had no commit by design (.git/info/exclude is unversioned). Live DB untouched (still 2 ref rows) — migrations begin in todo 6 with a backup first.

## [2026-07-28 ~03:50] SLEEP CHECKPOINT — state saved to repo
- User went to bed; execution paused at 5/24 tasks (todos 1-5 complete + verified).
- Checkpoint commit `615e56a` contains: `.omo/` (plan, draft, notepads, ledger, boulder, evidence, this file) + `AGENTS.md` with a resume banner at the top. Secrets scan of .omo was CLEAN before staging.
- **Todo 6 partial work preserved**: stalled session `ses_0592d876cffelbhH3TTwhp06ML` had edited `src/config/cache.py` (db_path injection + `reset()` classmethod — todo 6(a)). Orchestrator reviewed the edit: sane, matches spec, left UNCOMMITTED in the working tree for the resumer to verify and build on. Still missing: FK pragma, migration script + test, live run.
- To resume: `/start-work hyde-retrieval-pipeline` — the boulder hook continues from todo 6.

## [2026-07-28 Wave 2/3] EmbeddingService architecture divergence from single LLM-client pattern
- The original `LLMWrapper` (and the older `LLMClient`) centralizes retry/backoff, error handling, and raw-response recording for chat-completions calls. `EmbeddingService` does not reuse `LLMWrapper` because the OpenRouter `/embeddings` endpoint has a different URL, payload shape, and response shape.
- `EmbeddingService` reimplements the same retry/backoff policy and records a single summary `embedding_generation` message per `embed_texts` call (per plan: "summary only, never raw vectors"). Per-chunk embedding calls are therefore not individually recorded in `messages`.
- This is a moderate, intentional divergence driven by the endpoint difference and the plan's summary-only rule. It does not break the audit trail, but it duplicates retry boilerplate. Suggested correction (post-pipeline): extract a shared async HTTP retry helper used by both `LLMWrapper` and `EmbeddingService`, or extend `LLMWrapper` with a pluggable endpoint path.

## [2026-07-28 Tasks 8 & 11] Extra commits to keep migration regression test in sync
- The plan specifies "one commit per todo". When the migration script was extended to add `intent_generation` (todo 8) and `hyde_generation` (todo 11), the existing `scripts/test_migration.py` regression guard had to be updated to expect the new row counts and assert the new row values.
- Workers committed the migration/schema/prompt changes first, then committed the test update as a separate commit (`cda1719` after `7d7b770`, and `2b52c67` after `7da04cf`). The extra commits were necessary to keep the test suite green; future similar changes should squash the test update into the same todo commit.
