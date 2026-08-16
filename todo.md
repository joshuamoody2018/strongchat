# TODO - StrongChat Development Tasks

## Active MCP pivot (`mcp` branch)

### Phase A — Stateless MCP server (✅ DONE 2026-08-16)
- [x] Strip the application DB (`sessions`, `messages`,
  `ref_message_types` SQLite tables + `ChatDatabase` + `AsyncSQLiteDatabase`
  + `DatabasePort` Protocol + adapter) and `scripts/create_new_database.py`.
- [x] Replace `GlobalReferenceCache` + SQLite `ref_message_types` lookup with
  an in-process registry of frozen dataclasses
  (`src/config/llm_models.py` `MessageTypeDef` instances +
  `src/config/registry.py` `MessageTypeDefRegistry`/`DEFAULT_REGISTRY`).
- [x] Migrate audit trail from SQLite `messages` rows to JSONL log records
  (`src/config/logging.py` + `concurrent-log-handler`; levels:
  `ERROR`default / `INFO` / `DEBUG`.
- [x] Update `LLMWrapper` / `BaseService` / `EmbeddingService` /
  `ContextRetrievalService` / `PipelineRunner` to emit INFO + DEBUG
  structured log records instead of writing SQLite rows. The `session_uuid`
  parameter survives semantically as `correlation_id` (pure log-slicing
  key, never persisted).
- [x] Serialise `PipelineResult` to a JSON-safe bundle
  (`src/services/pipeline/serializer.py:pipeline_result_to_bundle`)
  dropping embedding vectors so the future `validate_answer` tool can
  accept it back unchanged.
- [x] MCP server entry point `src/server.py` (`MCPServer` from mcp v2.x,
  falling back to v1.x `FastMCP`). Tool:
  `retrieve_context(query, top_k=10, translations=["kjv","web"]) -> dict`.
  Plus a `validate_answer(answer, context=<bundle>)` stub that raises
  `NotImplementedError` with the documented planned return shape
  (`{valid, unsupported_claims, missing_coverage, suggested_refinement}`)
  to lock the contract in for the future agent harness.
- [x] Live stdio round-trip test
  (`tests/system/test_mcp_server_stdio.py`): spawns the server as a
  subprocess and drives the actual JSON-RPC handshake
  (initialize -> notifications/initialized -> tools/list -> tools/call
  validate_answer). ERROR-level audit records also directly exercised to
  disk now (`tests/scripts/test_logging.py`).
- [x] Repurpose `src/main.py` as a JSON-printing CLI smoke-test calling
  the same `retrieve_context_impl` function the MCP server tool wraps.
- [x] Update `scripts/setup_environment.sh` + `scripts/ingest_corpus.py`
  to drop the `create_new_database.py` step and the `--db-path` flag.
- [x] Update existing offline tests (`tests/scripts/test_*`):
  - Drop every `CREATE TABLE sessions/ref_message_types/messages` fixture
    DB and `GlobalReferenceCache.reset` setup
  - Use `DEFAULT_REGISTRY` (or construct a fresh `MessageTypeDefRegistry`)
    instead
  - Replace `self.service.db.create_session(...)` with
    `str(uuid.uuid4())` for the per-call correlation id
  - Replace audit assertions on `self.service.db.cursor.execute(...)` with
    `self.assertLogs("strongchat", level="INFO"/"DEBUG")` against the
    structured log records.
- [x] Update system tests (`tests/system/test_*`) to drop the audit_trail
  on `messages` rows; replace with assertions against the returned bundle
  (`pipeline_result_to_bundle(result)` carries the same intent + HyDE +
  hit shape, minus embedded vectors and minus SQLite rows).
- [x] Delete stale system tests `test_real_api.py`, `test_final_system.py`,
  `test_json_api.py`, `test_refreshed_cache.py`, `test_intent.py`
  (referenced removed `intent_classification` slug long pre-MCP).
- [x] Rewrite `tests/test_integration.py` against the new registry +
  bundle shape + caplog (was a top-level fixture-DB CRUD integration).
- [x] New tests:
  - `tests/scripts/test_mcp_server.py` —�单 invokes
    `retrieve_context_impl` with a mocked runner; asserts the bundle
    shape; asserts `validate_answer_impl` raises `NotImplementedError`
    documenting the contract.
  - `tests/scripts/test_logging.py` — `JsonFormatter` record shape,
    level resolution, idempotent `configure_logging`, non-serializable
    extra repr fallback.
- [x] Update docs: `AGENTS.md`, `README.md`, `docs/high-level.md`,
  `docs/database.md`, `docs/reference.md`, `docs/implementation-status.md`,
  `docs/pipeline-hyde-retrieval.md`, `docs/pipeline-context-retrieval.md`,
  `docs/llm-framework.md`, `docs/architecture-diagram.md` for the MCP
  entry, statelessness, no-app-DB, JSONL audit, and the `validate_answer`
  stub.

### Phase B — `validate_answer` tool implementation (NEXT)
- [ ] Implement the `validate_answer` body in `src/server.py`. The
  contract is locked in:
  - Input: `(answer: str, context: <bundle>)`
  - Output: `{valid: bool, unsupported_claims: [...], missing_coverage: [...], suggested_refinement: str | null}`
- [ ] Build the fact-check library: parse claim + citation references out
  of the agent's `answer`, verify each against the per-intent traces'
  `context_bundle` data in the provided `context` bundle.
- [ ] Emit structured agent-actionable feedback so the calling agent can
  decide whether to re-call `retrieve_context` with a refined query (or
  re-synthesize using a stronger model, then re-validate).
- [ ] Add tests (`tests/scripts/test_mcp_server.py` extension): one
  passing + one failing case, mocked LLM underneath, `assertLogs` on
  JSONL audit records.

### Phase C — HTTP transport + streaming progress (✅ DONE 2026-08-16)
- [x] Add a `progress` callback param to `PipelineRunner.run()` so the
  runner emits a stage event at every major pipeline step
  (`intent`, `hyde`, `retrieval`, `context`, `serialize`) without
  depending on the MCP SDK. The runner treats the callback as strictly
  informational — failures inside it are swallowed and logged, never
  poisoning the run. (`src/services/pipeline/runner.py`)
- [x] Wire the MCP `Context.report_progress` / `Context.info` helpers
  to that callback inside the `retrieve_context` tool wrapper in
  `src/server.py`. Imported `Context` at module scope from
  `mcp.server.mcpserver.context` (the pydantic-BaseModel one that the
  SDK's `find_context_parameter` matches against — NOT the lower-level
  `mcp.server.context.Context`, which is a different class and would
  crash tool registration with `PydanticInvalidForJsonSchema`).
- [x] Add streamable-HTTP transport selection: `STRONGCHAT_MCP_TRANSPORT`
  env or `--transport {stdio,http}` argv; `--host` / `--port` /
  `STRONGCHAT_HOST` / `STRONGCHAT_PORT` for the bind address. Defaults
  to `stdio` / `127.0.0.1:8765`. HTTP mode uses
  `mcp.run(transport="streamable-http", host=, port=)` (falls back to
  `streamable_http_app()` + manual `uvicorn.run` on older SDKs).
- [x] Tests:
  - `tests/scripts/test_mcp_server.py` extension: progress callback
    forwarded to runner; transport selection from env/argv; unknown
    transport falls back to stdio.
  - `tests/system/test_mcp_server_http.py`: live streamable-HTTP
    round-trip (initialize → tools/list → tools/call validate_answer)
    via the official `mcp.client.streamable_http` SDK driving an
    in-process uvicorn server on an ephemeral port. Plus an offline
    test asserting the progress callback receives all five stage
    events in order.

### Phase D — Public exposure via sslip.io + Caddy + bearer auth (✅ DONE 2026-08-16)
- [x] Add `src/auth.py` exposing `StaticBearerTokenVerifier` (an
  `mcp.server.auth.provider.TokenVerifier` implementation that constant-time
  compares the `Authorization: Bearer <key>` value against
  `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY`) plus `load_static_bearer_config()` which returns
  `(AuthSettings, token_verifier)` for `MCPServer.__init__` from env.
- [x] Wire `auth_settings` + `token_verifier` into `MCPServer(...)` inside
  `_setup_and_build_mcp` in `src/server.py`. Both env controls
  (`OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` + `STRONGCHAT_PUBLIC_URL`) set → SDK auto-wires
  `BearerAuthBackend` + `AuthContextMiddleware` + serves
  `/.well-known/oauth-protected-resource`. Only one set — log WARNING +
  disable auth so misconfiguration is LOUD but never silently leaves a
  public endpoint open.
- [x] Add `deploy/Caddyfile` using sslip.io + on-demand TLS. Caddy
  terminates TLS, forwards to `127.0.0.1:8765` plaintext, passes the
  `Authorization` header through unchanged (the bearer check happens
  in the MCP backend; Caddy is pure TLS + reverse proxy). Long
  SSE-friendly timeouts for in-flight retrieve_context calls.
- [x] Add `deploy/README.md` documenting bring-up (generate key → boot
  MCP server bound to 127.0.0.1 → run Caddy pointing at the sslip.io
  hostname → smoke with curl carrying the bearer) + claude.ai web
  custom-connector caveat (below) + production-hardening options.
- [x] Tests `tests/system/test_mcp_server_http.py` extension: 401 on
  missing/malformed/wrong bearer; 200 on correct bearer; 200 on
  unauthenticated path when `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` unset (backwards
  compatible — stdio / local HTTP / ACL'd exposure stays open).
- [x] `deploy/bootstrap.sh` — idempotent scripted bring-up: generates +
  stores API key at `~/.OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` (chmod 600, never overwrites
  existing), auto-detects public IPv4 (or accepts `PUBLIC_IP=` /
  `STRONGCHAT_HOSTNAME=` overrides), renders `deploy/Caddyfile.local`
  from the template, writes `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` + `STRONGCHAT_PUBLIC_URL`
  into `.env` (no duplicates on re-run), prints the exact next-step
  commands. Safe to re-run; key is preserved across re-runs.
- [x] `deploy/strongchat.service` — optional systemd unit so the MCP
  backend survives reboot. Forces loopback bind + HTTP transport in-unit
  (defence in depth) and reads env from `.env` via `EnvironmentFile=`.

### What YOU need to do to finish setting this up (manual, on the host box)
The code + scripts are done; these are the steps only a human with shell
access + (for some) DNS / firewall control can perform. None of them
are coded yet on a fresh box.

- [ ] Install Caddy on the box that will host the public endpoint:
  `./scripts/install_caddy.sh` (Debian/Ubuntu, idempotent) /
  `brew install caddy` (macOS) / https://caddyserver.com/docs/install
  (other). Also installed automatically by `scripts/setup_environment.sh`
  via an interactive prompt at the end of dev setup. `deploy/bootstrap.sh`
  checks for it and warns if missing.
- [ ] Open inbound TCP 443 on the host firewall (Caddy serves HTTPS on
  443; the MCP backend stays on 127.0.0.1:8765 — no inbound rule needed
  for 8765). Examples:
  - ufw: `sudo ufw allow 443/tcp`
  - firewalld: `sudo firewall-cmd --permanent --add-service=https && sudo firewall-cmd --reload`
  - cloud VM security group: add an inbound rule for TCP 443 from 0.0.0.0/0
- [ ] If the box is behind home / office NAT, forward external TCP 443 →
  this box's LAN IP in the router's port-forwarding config. (Cloud VMs
  usually have a routable public IP already; skip this.)
- [ ] Run `./deploy/bootstrap.sh` from the repo root. It writes:
  - `~/.OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` (chmod 600) — the bearer secret.
  - `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` + `STRONGCHAT_PUBLIC_URL` lines in `.env`.
  - `deploy/Caddyfile.local` (rendered; gitignored).
  Re-read its printed output — it tells you the exact public URL.
- [ ] (Optional but recommended) Install the systemd unit so the MCP
  backend survives reboot:
  ```sh
  sudo cp deploy/strongchat.service /etc/systemd/system/
  # Edit WorkingDirectory + ExecStart + EnvironmentFile paths in the
  # unit to match your actual repo location if it isn't /opt/strongchat.
  sudo systemctl daemon-reload
  sudo systemctl enable --now strongchat
  journalctl -u strongchat -f   # tail logs
  ```
  Otherwise just run
  `STRONGCHAT_MCP_TRANSPORT=http .venv/bin/python src/server.py`
  in its own terminal.
- [ ] Start Caddy pointing at the rendered config. With the distro
  `caddy.service`, edit `/etc/caddy/Caddyfile` to a single line:
  `import /abs/path/to/strongchat/deploy/Caddyfile.local`
  then `sudo systemctl reload caddy`. Or run it manually in another
  terminal: `caddy run --config deploy/Caddyfile.local`.
- [ ] Smoke-test from a DIFFERENT machine (your laptop) to confirm the
  public path works end-to-end:
  ```sh
  curl -s -X POST \
    -H "Authorization: Bearer $(ssh host-box cat ~/.OPENROUTER_STRONGCHAT_DEFAULT_API_KEY)" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
         "params":{"protocolVersion":"2025-11-25","capabilities":{},
         "clientInfo":{"name":"smoke","version":"1.0"}}}' \
    https://strongchat.YOURIP.sslip.io/mcp
  ```
  Expect `200 OK` + `text/event-stream` body containing `protocolVersion`.
  Without the `Authorization` header expect `401`.
- [ ] Point an MCP client at the public URL. Example for opencode.json
  (or Claude Desktop's `claude_desktop_config.json`):
  ```json
  {
    "mcpServers": {
      "strongchat-remote": {
        "url": "https://strongchat.YOURIP.sslip.io/mcp",
        "headers": { "Authorization": "Bearer <paste `cat ~/.OPENROUTER_STRONGCHAT_DEFAULT_API_KEY`>" }
      }
    }
  }
  ```
- [ ] (Rotation) To rotate the API key later: `rm ~/.OPENROUTER_STRONGCHAT_DEFAULT_API_KEY`,
  remove the two `STRONGCHAT_*` lines from `.env`, rerun
  `./deploy/bootstrap.sh`, restart the MCP server, and update any
  client configs that had the old key.

### What's next if we want to set up OAuth (claude.ai web custom-connector)
The static bearer is sufficient for any client where the user can paste
the key into config (opencode / Claude Desktop / curl / opencode-hosted
agent harnesses). It is **NOT** sufficient on its own for the hosted
**claude.ai web** custom-connector flow, which expects OAuth 2.0 PKCE
authorization-server metadata at `/.well-known/oauth-authorization-server`
plus `/authorize`, `/token`, `/register` endpoints that issue
short-lived scoped tokens claude.ai stores via `mcp-session-id`.

The MCP SDK already supports the authorization-server side as a
construction-time plugin (`OAuthAuthorizationServerProvider`); the work
is implementing that provider. Strictly additive — swap
`token_verifier` for `auth_server_provider` on `MCPServer(...)` and the
SDK auto-exposes the OAuth metadata endpoints on the same base URL. The
bearer guardrails from `src/auth.py` stay unchanged.

- [ ] Implement `src/oauth/provider.py` with an
  `OAuthAuthorizationServerProvider` subclass that wires:
  - [ ] `get_authorization_server_metadata()` → serves
    `/.well-known/oauth-authorization-server` with the issuer URL,
    `authorization_endpoint`, `token_endpoint`,
    `registration_endpoint`, `revocation_endpoint`,
    `code_challenge_methods_supported=["S256"]`, scopes.
  - [ ] `get_client(client_id)` + `register_client(metadata)` →
    RFC 7591 dynamic client registration. For a single-user deploy the
    minimum is to accept claude.ai's registration request and return a
    stable client id + secret.
  - [ ] `authorize(client, authorization_request)` → the `/authorize`
    endpoint. For a single-user deploy, the simplest flow is a
    consent screen that just says "Allow claude.ai to call StrongChat?"
    with an approve button that issues a short-lived authorization
    code. No login step needed since there's only one user.
  - [ ] `load_authorization_code(client, code)` +
    `exchange_authorization_code(client, code)` → the `/token`
    endpoint. Validates the PKCE code_verifier against the stored
    code_challenge, issues a short-lived JWT access token (e.g. 1h)
    signed with a per-deploy signing key (NOT the bearer key — the
    bearer key stays as a fallback / admin path).
  - [ ] `load_access_token(token)` + `refresh_token(client,
    refresh_token)` → token introspection + refresh flow. Optional
    for v1; required if we want token rotation without re-onboarding.
  - [ ] `revoke_token(...)` → the `/revoke` endpoint (RFC 7009).
- [ ] Wire `auth_server_provider=` (instead of `token_verifier=`) into
  `MCPServer(...)` in `src/server.py:_setup_and_build_mcp`. The SDK
  auto-mounts the OAuth endpoints + serves
  `/.well-known/oauth-authorization-server`. The static-bearer
  `StaticBearerTokenVerifier` can stay as a secondary token verifier
  if we want both paths (admin/static + OAuth-issued) — confirm with
  the SDK's `auth=` + `token_verifier=` + `auth_server_provider=`
  interaction; may need to compose.
- [ ] Add a per-deploy JWT signing key (random 256-bit secret) stored
  alongside `~/.OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` (e.g.
  `~/.strongchat_oauth_signing_key`, chmod 600). `deploy/bootstrap.sh`
  generates it if missing.
- [ ] Tests:
  - [ ] `tests/scripts/test_oauth_provider.py` — offline: register a
    client, run authorize → get code, exchange → get token, validate
    token via the verifier. Mock the client store.
  - [ ] `tests/system/test_mcp_server_http.py` extension — drive the
    full PKCE flow over the in-process uvicorn: register, authorize,
    exchange, then call `retrieve_context` with the issued token.
- [ ] Update `deploy/README.md` to document the claude.ai web
  custom-connector onboarding flow (URL to paste, scopes, consent
  screen).
- [ ] Add `STRONGCHAT_OAUTH_ISSUER_URL` env (or reuse
  `STRONGCHAT_PUBLIC_URL`) so the JWT `iss` claim matches what
  claude.ai expects from the metadata endpoint.

## Earlier parity work (pre-MCP, still relevant)

### Phase 1: Structured Response Framework ✅
- [x] Create src/config/schemas.py with INTENT_GENERATION_SCHEMA
- [x] Create src/config/prompts.py with INTENT_GENERATION_PROMPT
- [x] Create src/services/llm/aimessage.py with strict JSON parsing
- [x] Create src/services/llm/wrapper.py with retry/backoff logic
- [x] Create src/services/llm/exceptions.py for error handling
- [x] Create src/services/llm/__init__.py and src/config/__init__.py

### Phase 2: Intent Service Refactor ✅
- [x] Update src/services/intent/service.py to use the wrapper framework
- [x] Define intent response models in src/services/llm/aimessage.py
- [x] Update database schema to store structured intent data

### Phase 3: Testing
- [ ] Create comprehensive tests for response parsing
- [ ] Test schema validation with malformed responses
- [ ] Test retry/backoff logic with mock failures
- [ ] Test error routing to stderr
- [ ] Test async functionality with real API calls

### Phase 4: Migration
- [ ] Replace current get_message_intent() with new structured approach
- [ ] Add audit logging for intent disambiguation decisions
- [ ] Implement fallback logic for parsing failures
- [ ] Update main.py to use new LLM client

### Phase 6: Context Retrieval ✅
- [x] 1. Add context_constants module with POS weight table and scoring formula
- [x] 2. Download Macula Greek tokens and validate shape
- [x] 3. Build Macula Greek index SQLite table
- [x] 4. Compute Strong's frequency table from Macula
- [x] 5. Ingest STEPBible TBESG + Thayer's sense counts and definitions
- [x] 6. Extend migration script with context_retrieval ref-message-type row
- [x] 7. Add ContextRetrievalService with offline test
- [x] 8. Wire ContextRetrievalService into PipelineRunner and extend trace regression test
- [x] 9. Add live end-to-end integration test for context retrieval
- [x] 10. Add offline test for context retrieval within the full pipeline
- [x] 11. Update architecture documentation for the context retrieval pipeline

### Macula schema follow-up ✅ (2026-08-16)
- [x] Add `gloss` column to `macula_tokens` and re-ingest from TSV
- [x] Fix strongs-key format mismatch between `lexicon_definitions` (was `G0976`)
      and `macula_tokens`/`strongs_frequency` (bare int `976`): normalize at
      ingest in `scripts/build_lexicon_index.py` (`normalize_strongs` helper)
- [x] Add ingest-time format-drift validation that fails loudly on regression
- [x] Add regression canaries to all 3 context-retrieval test files
      (`definitions` non-empty, `gloss` non-empty, per-word schema validation)

### Hebrew OT Macula integration ✅ (2026-08-16)
- [x] Add `BOOK_NUM_TO_OSIS_OT` (1..39) + OT-aware `parse_xml_id_hebrew`
      (13-char `o` + 4-digit word_slot) to `scripts/build_macula_index.py`,
      routed via `--testament {greek,hebrew}`
- [x] Add `scripts/download_macula_hebrew.py` (LFS-pointer resolver + canonical
      TSV projector + manifest writer)
- [x] Extend `scripts/build_strongs_frequency.py` with `--testament` path
      partitioning `strongs_frequency.testament` ('NT' vs 'OT')
- [x] Extend `scripts/build_lexicon_index.py` to ingest TBESH (Hebrew CC BY 4.0)
      under `lexicon_source='tbESH'`; generalise `parse_tsv_content` to support
      Hebrew headers; permit letter-suffixed strongs keys in validation
- [x] Add `POS_WEIGHTS_HEBREW` (HAM codes: verb 0.95, subs/nmpr 0.825, ...)
      + language-routed `get_pos_weight(pos, language)` in `config/context_constants.py`
- [x] Route `ContextRetrievalService` per hit by `book_num < 40`: filter
      `strongs_frequency.testament`, `lexicon_definitions.lexicon_source`,
      occurrence cache by `book_num` range, and pick HAM vs Robinson POS weights
- [x] Add `_BOOK_OSIS_LANGUAGE` map + extend `BOOK_OSIS_IDENTITY` to include
      OT OSIS codes for already-OSIS inputs
- [x] Add 4 boilerplate/test files:
      `test_normalize_strongs.py`, `test_build_macula_index_ot.py`,
      `test_context_constants_hebrew.py`, `test_context_retrieval_hebrew.py`,
      `test_hebrew_ingest_integration.py` (50 new tests, all passing)
- [x] Update `scripts/setup_environment.sh` to bootstrap Hebrew corpus +
      lexicon + frequency partitions alongside Greek path
- [x] Update docs (`pipeline-context-retrieval.md`, `architecture-diagram.md`,
      `README.md`, `high-level.md`)

## Next steps (post-MCP strip)

### Short Term
- Implement `validate_answer` MCP tool (see Phase B above).
- Implement the OAuth metadata path (`/.well-known/oauth-authorization-server`
  + a minimal PKCE flow) so claude.ai's hosted custom-connector can use the
  public streamable-HTTP endpoint directly, instead of web users having to
  rely on a static `OPENROUTER_STRONGCHAT_DEFAULT_API_KEY` bearer (Phase D doc).
- Add an end-to-end OT live test (`tests/system/test_context_retrieval_e2e_ot.py`)
  once an OT ingest is operational on a CI host (the live `test_context_retrieval_e2e.py`
  is currently NT-flavored).

### Medium Term
- Implement RRF ranking (steps 5-6) as `src/services/rrf/`; wire between
  RetrievalService.search and ContextRetrievalService.
- Implement graph expansion (step 8) as `src/services/graph/`.

### Long Term
- Implement synthesis (step 10) and evaluator loop (step 11) if the agent
  harness / wrapper itself (your separate project) needs server-side hooks
  rather than running the loop entirely in the agent's context window.
- Evaluate production monitoring options (JSONL is the audit surface; add
  aggregators if a hosted variant is built later).
- Tag `dev` (`v0.1-classic-sqlite-audit`) once `mcp` stabilizes; let
  `mcp` become the new default.