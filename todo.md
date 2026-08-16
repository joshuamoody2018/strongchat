# TODO

## Code

- [ ] `validate_answer` body (Phase B) — contract locked; stub raises
      `NotImplementedError` in `src/server.py:validate_answer_impl`. Build the
      fact-check library + tests (`tests/scripts/test_mcp_server.py`).
- [ ] `deploy/bootstrap.sh` — mint OAuth signing key + client creds alongside
      the bearer API key so a fresh box is OAuth-ready without manual scripts.
- [ ] `deploy/README.md` — document the claude.ai custom-connector onboarding
      flow (URL, paste client_id/secret, Caddy TLS, missing-env error).

## Pipeline (13-step architecture)

- [ ] RRF ranking (steps 5–6) — new `src/services/rrf/`, wired between
      `RetrievalService.search` and `ContextRetrievalService`.
- [ ] Graph expansion (step 8) — new `src/services/graph/`.
- [ ] Synthesis (step 10) + evaluator loop (step 11) — only if the agent
      harness needs server-side hooks rather than running the loop in its own
      context window.

## Tests

- [ ] OT live e2e test (`tests/system/test_context_retrieval_e2e_ot.py`) — once
      an OT ingest is operational on a CI host (current live e2e is NT-only).

## Ops

- [ ] Tag `dev` as `v0.1-classic-sqlite-audit` once `mcp` stabilizes; switch
      default branch to `mcp`.
