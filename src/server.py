#!/usr/bin/env python3
"""StrongChat MCP server: retrieve_context tool (stateless, no app DB).

Exposes the StrongChat retrieval pipeline (steps 2-4 + 7 + 9 of the 13-step
architecture) as a single MCP tool. The agent (Claude Desktop, opencode, any
MCP-compatible client) drives the loop itself:

    1. Agent calls ``retrieve_context(query)`` → gets back a structured JSON
       bundle: query_analysis, per-intent traces (intent_data, hyde_document,
       per-translation hits each carrying reference/text/distance/context_bundle).
    2. Agent synthesizes an answer using that bundle + its own model.
    3. Agent calls ``validate_answer(answer, context=<the bundle from step 1>)``
       to fact-check the answer against that exact retrieved context.
    4. If validation fails, the agent decides whether to re-call
       ``retrieve_context`` with a refined query, re-synthesize, re-validate.

Nothing server-side remembers anything between calls — each call is a pure
function of its inputs. The agent's context window threads state across the
loop; the server doesn't need session storage or correlation by id.

## Transports

The server supports two transports, selected by the ``STRONGCHAT_MCP_TRANSPORT``
environment variable (or ``--transport <stdio|http>`` argv override):

* **stdio** (default): JSON-RPC over the process's stdin/stdout. Used by
  Claude Desktop / opencode / local agents that spawn this server. Inline
  ``notifications/progress`` and ``notifications/message`` (log) records
  flow back over the same stdio pipe so any watching client can surface
  pipeline stage events while a tool call is in flight.

    .venv/bin/python src/server.py

* **streamable-http** (``STRONGCHAT_MCP_TRANSPORT=http`` or ``--transport http``):
  Anthropic's streamable MCP-over-HTTP+SSE transport. The server runs a
  uvicorn ASGI loop on ``127.0.0.1:8765`` by default
  (``STRONGCHAT_HOST`` / ``STRONGCHAT_PORT`` override). Use this for remote
  hosting behind a reverse proxy (Caddy / nginx). The same progress + log
  notifications are streamed over the SSE response stream so a remote agent
  (e.g. claude.ai's hosted MCP custom-connector, or any HTTP client
  speaking MCP streamable-http) can show the user pipeline progress as it
  happens.

    STRONGCHAT_MCP_TRANSPORT=http .venv/bin/python src/server.py
    # then connect a client to http://127.0.0.1:8765/mcp

For public exposure wrap this with the included ``deploy/Caddyfile`` (which
terminates TLS via sslip.io on-demand certs and forwards a bearer API key
configured via ``STRONGCHAT_API_KEY``).
"""

import argparse
import asyncio
import json
import os
import sys

# Make ``src/`` importable when the file is launched directly (e.g. by an
# MCP client that runs `python src/server.py` rather than going through a
# package entrypoint). This matches the pattern used in src/main.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

from config.logging import configure_logging
from services.pipeline import PipelineRunner, pipeline_result_to_bundle
from services.pipeline.runner import ProgressCallback

# Import the high-level MCP request Context at module scope so tools nested
# inside ``_setup_and_build_mcp`` can annotate ``ctx: Context`` and the
# SDK's ``find_context_parameter`` is able to resolve the name from the
# function's ``__globals__`` (= this module).
#
# IMPORTANT: on mcp v2.x, the Context that the tool framework actually
# matches against is ``mcp.server.mcpserver.context.Context`` (a pydantic
# BaseModel wrapper), NOT the lower-level ``mcp.server.context.Context``
# (which is the BaseContext protocol-style class). Passing the wrong one
# here means the SDK's ``find_context_parameter`` would not detect the
# kwarg, pydantic would try to emit a JSON schema for it, and tool
# registration would crash with ``PydanticInvalidForJsonSchema``.
# Pre-v2 SDKs may not expose this path; in that case we degrade gracefully
# to a no-progress variant.
try:
    from mcp.server.mcpserver.context import Context  # noqa: F401  (annotation)
except ImportError:  # pragma: no cover - pre-v2 SDK fallback
    try:
        from mcp.server.fastmcp import Context  # type: ignore # noqa: F401
    except ImportError:
        Context = None  # type: ignore[assignment]


# Tool input/output schemas surface to the agent as JSON Schema. Defined here
# so the future ``validate_answer`` tool can reuse the same ``context`` shape
# verbatim — this is what locks the two-tool contract together.

RETRIEVE_CONTEXT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Plain-language user query to retrieve context for.",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of nearest neighbor verses to return per HyDE document per translation.",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
        },
        "translations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Translation slugs to query. Default: ['kjv','web'].",
            "default": ["kjv", "web"],
        },
    },
    "required": ["query"],
}

VALIDATE_ANSWER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The synthesized answer to validate.",
        },
        "context": {
            "type": "object",
            "description": (
                "The exact bundle returned by a prior retrieve_context call. "
                "The validator re-checks claims in ``answer`` against this "
                "bundle's traces[].search_results[].hits[].context_bundle."
            ),
        },
    },
    "required": ["answer", "context"],
}

# Build the lazy singleton runner once. The MCP server holds a long-lived
# process (stdio); constructing the runner once amortizes ChromaDB client /
# registry setup across many tool calls. PipelineRunner.run() itself remains
# stateless — each call generates a fresh correlation_id and returns a
# self-contained bundle. No state survives between calls.
_RUNNER: PipelineRunner | None = None


def _get_runner() -> PipelineRunner:
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = PipelineRunner()
    return _RUNNER


async def retrieve_context_impl(
    query: str,
    top_k: int = 10,
    translations: list[str] | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    """Pure-function implementation of the retrieve_context tool.

    Exposed separately from the MCP decorator so it can be unit-tested
    directly (no stdio or HTTP round-trip needed). The MCP tool wrapper
    below calls this, forwarding a ``progress`` callback that bridges the
    pipeline's stage events onto the MCP client's progress / log
    notification stream.
    """
    if translations is None:
        translations = ["kjv", "web"]
    runner = _get_runner()
    try:
        result = await runner.run(
            query=query,
            top_k=top_k,
            translations=tuple(translations),
            progress=progress,
        )
        return pipeline_result_to_bundle(result)
    finally:
        # Don't close the singleton runner between calls; close() is for
        # process shutdown. Each call gets a fresh correlation_id; the runner
        # holds no per-call state.
        pass


async def validate_answer_impl(answer: str, context: dict) -> dict:
    """Validate an agent-synthesized answer against a retrieved context bundle.

    NOT IMPLEMENTED YET. The stub raises ``NotImplementedError`` with a
    documented return schema so the calling agent gets actionable feedback
    rather than silence, and so the contract is locked in for your future
    agent harness / wrapper.

    Planned return shape (when implemented):

        {
          "valid": bool,
          "unsupported_claims": [
            {"claim": str, "reason": str, "missing_reference": str | null}
          ],
          "missing_coverage": [str, ...],
          "suggested_refinement": str | null
        }
    """
    raise NotImplementedError(
        "validate_answer is not implemented yet. "
        "Planned return shape: "
        "{valid: bool, unsupported_claims: [...], missing_coverage: [...], "
        "suggested_refinement: str | null}. "
        "Input contract: (answer: str, context: <bundle from retrieve_context>)."
    )


async def _setup_and_build_mcp():
    """Load env, configure logging, register tools; return the MCPServer.

    Returns the configured MCPServer (or FastMCP on v1.x) instance with both
    tools already registered. The caller then runs the stdio loop on it.
    Pulled out of _main so it doesn't need to be async-then-sync-then-async
    again.
    """
    # Load .env so OPENROUTER_API_KEY etc. are available; preserve an
    # explicitly-unset key in the parent shell (matches src/main.py behaviour).
    had_api_key = "OPENROUTER_API_KEY" in os.environ
    load_dotenv()
    if not had_api_key and "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]

    configure_logging()

    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as MCPServer
        except ImportError as exc:
            print(
                f"ERROR: mcp package not installed or unsupported version. "
                f"Run `pip install -r requirements.txt`. ({exc})",
                file=sys.stderr,
            )
            raise

    # ``Context`` is imported at module scope (see top of file) so that
    # ``find_context_parameter`` can resolve the ``ctx: Context``
    # annotation on the tool wrapper below from the function's globals.
    # Pre-v2 SDK paths degrade to ``Context = None``, in which case the
    # tool falls back to a no-op progress callback (pipelines still run;
    # the agent just loses streaming notifications).
    mcp = MCPServer(name="strongchat", description=(
        "StrongChat retrieve_context + validate_answer MCP server. "
        "retrieve_context runs the intent -> HyDE -> retrieval -> "
        "original-language context pipeline and returns a self-contained "
        "JSON bundle. validate_answer is a stub today (raises "
        "NotImplementedError); its contract is locked in for the future "
        "agent harness / wrapper that drives state management."
    ))

    def _make_progress_callback(ctx):
        """Build a ProgressCallback that bridges pipeline stage events onto
        the MCP client's ``notifications/progress`` and
        ``notifications/message`` (log) streams.

        Returns ``None`` when ``ctx`` is missing (offline unit tests / a
        pre-v2 SDK) — the pipeline treats ``None`` as "no streaming".
        """
        if ctx is None:
            return None

        async def _cb(stage: str, message: str,
                      done: float | None = None,
                      total: float | None = None) -> None:
            try:
                # structured progress notification for clients that surface
                # progress bars / waiting indicators.
                if hasattr(ctx, "report_progress"):
                    if done is not None and total is not None:
                        await ctx.report_progress(done, total, message)
                    else:
                        await ctx.report_progress(0, 0, message)
                # human-readable notice (level=info) carrying the stage
                # name + message — Claude.ai shows these inline.
                if hasattr(ctx, "info"):
                    await ctx.info(f"[{stage}] {message}")
                elif hasattr(ctx, "log"):
                    await ctx.log("info", f"[{stage}] {message}")
            except Exception:
                # The pipeline already wraps callbacks in try/except, but
                # defensive: a closed transport mid-flight must not break
                # the actual retrieval. Hand the failure back to the
                # caller's logger (the MCPServer prints context log errors
                # itself); otherwise swallow.
                return

        return _cb

    # The tool signature changes based on whether ``Context`` is importable
    # on this SDK. We register a thin wrapper that takes ``ctx`` when
    # available so the framework injects the live request context; the
    # underlying impl stays context-free for offline tests.

    if Context is not None:
        @mcp.tool(
            name="retrieve_context",
            description=(
                "Retrieve Bible verses with original-language context bundles "
                "for a plain-language query. Returns a structured JSON bundle "
                "(query_analysis, per-intent traces with hits and "
                "context_bundle). Pass the entire returned bundle back as "
                "the `context` argument to validate_answer to fact-check a "
                "synthesized answer. Emits streaming progress notifications "
                "at each major pipeline stage (intent, hyde, retrieval, "
                "context, serialize) while the call is in flight."
            ),
        )
        async def retrieve_context(
            query: str,
            top_k: int = 10,
            translations: list[str] | None = None,
            ctx: Context = None,  # type: ignore[valid-type]
        ) -> dict:
            return await retrieve_context_impl(
                query, top_k=top_k, translations=translations,
                progress=_make_progress_callback(ctx),
            )
    else:  # pragma: no cover - SDK without Context support
        @mcp.tool(
            name="retrieve_context",
            description=(
                "Retrieve Bible verses with original-language context bundles "
                "for a plain-language query. Returns a structured JSON "
                "bundle (query_analysis, per-intent traces with hits and "
                "context_bundle). Pass the entire returned bundle back as "
                "the `context` argument to validate_answer to fact-check a "
                "synthesized answer."
            ),
        )
        async def retrieve_context(
            query: str,
            top_k: int = 10,
            translations: list[str] | None = None,
        ) -> dict:
            return await retrieve_context_impl(
                query, top_k=top_k, translations=translations,
            )

    @mcp.tool(
        name="validate_answer",
        description=(
            "Re-check a synthesized answer against the exact context bundle "
            "returned by a prior retrieve_context call. Currently NOT "
            "IMPLEMENTED (raises NotImplementedError); contract is locked in "
            "for agent harness compatibility."
        ),
    )
    async def validate_answer(answer: str, context: dict) -> dict:
        return await validate_answer_impl(answer=answer, context=context)

    return mcp


def _select_transport() -> tuple[str, str, int]:
    """Pick the transport from argv / env.

    Returns ``(transport, host, port)``. Precedence:

    1. ``--transport <stdio|http>`` argv (long form); ``--host`` / ``--port``.
    2. ``STRONGCHAT_MCP_TRANSPORT``, ``STRONGCHAT_HOST``, ``STRONGCHAT_PORT``
       env vars.
    3. Defaults: ``stdio`` / ``127.0.0.1`` / ``8765``.

    Unknown argv values fall back to env / defaults rather than crashing —
    a misconfigured launcher should still boot, just on the safe default.
    """
    parser = argparse.ArgumentParser(
        prog="strongchat-mcp",
        description="StrongChat MCP server (stdio or streamable-http).",
        add_help=True,
    )
    parser.add_argument("--transport", choices=["stdio", "http"],
                        default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    # Parse only the flags we recognize; ignore everything else so MCP
    # clients that pass their own argv through (e.g. a wrapper script)
    # don't crash us.
    args, _unknown = parser.parse_known_args()

    transport = (
        args.transport
        or os.environ.get("STRONGCHAT_MCP_TRANSPORT", "stdio")
    ).lower()
    if transport not in ("stdio", "http"):
        transport = "stdio"

    host = args.host or os.environ.get("STRONGCHAT_HOST", "127.0.0.1")
    port = args.port or int(os.environ.get("STRONGCHAT_PORT", "8765"))
    return transport, host, port


def main() -> int:
    """Run the MCP server (stdio by default; streamable-http on request).

    Never returns under normal operation.
    """
    transport, host, port = _select_transport()

    try:
        mcp = asyncio.run(_setup_and_build_mcp())
    except ImportError:
        return 1

    if transport == "http":
        # mcp v2.x: run(transport="streamable-http", host=, port=) wraps anyio
        # + uvicorn internally. Older v1.x signatures raised TypeError on the
        # extra kwargs; we fall back to streamable_http_app + a direct
        # uvicorn serve for those.
        if hasattr(mcp, "run"):
            try:
                mcp.run(transport="streamable-http", host=host, port=port)
                return 0
            except TypeError:
                pass  # fall through to manual uvicorn wiring
        # Manual wiring: build a Starlette ASGI app and run it ourselves.
        try:
            import uvicorn
        except ImportError:
            print(
                "ERROR: streamable-http transport needs uvicorn. "
                "Run `pip install uvicorn starlette sse-starlette`.",
                file=sys.stderr,
            )
            return 1
        if not hasattr(mcp, "streamable_http_app"):
            print(
                "ERROR: installed mcp SDK does not expose "
                "streamable_http_app(). Upgrade with `pip install -U mcp`.",
                file=sys.stderr,
            )
            return 1
        app = mcp.streamable_http_app()
        uvicorn.run(app, host=host, port=port)
        return 0

    # stdio (default)
    if hasattr(mcp, "run"):
        try:
            mcp.run(transport="stdio")
        except TypeError:
            # Older v1.x signature: run() takes no transport arg.
            mcp.run()
        return 0
    # Last-resort fallback: an SDK with only the async entry exposed.
    if hasattr(mcp, "run_stdio_async"):
        asyncio.run(mcp.run_stdio_async())
        return 0
    print("ERROR: MCPServer exposes neither run() nor run_stdio_async()",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())