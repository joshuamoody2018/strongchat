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

Run as a stdio server (default for Claude Desktop / opencode / local agents):

    .venv/bin/python src/server.py

Or wire into Claude Desktop's ``claude_desktop_config.json``:

    {
      "mcpServers": {
        "strongchat": {
          "command": "/abs/path/to/strongchat/.venv/bin/python",
          "args": ["/abs/path/to/strongchat/src/server.py"]
        }
      }
    }
"""

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
) -> dict:
    """Pure-function implementation of the retrieve_context tool.

    Exposed separately from the MCP decorator so it can be unit-tested
    directly (no stdio round-trip needed). The MCP tool wrapper below calls
    this.
    """
    if translations is None:
        translations = ["kjv", "web"]
    runner = _get_runner()
    try:
        result = await runner.run(
            query=query,
            top_k=top_k,
            translations=tuple(translations),
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

    mcp = MCPServer(name="strongchat", description=(
        "StrongChat retrieve_context + validate_answer MCP server. "
        "retrieve_context runs the intent -> HyDE -> retrieval -> "
        "original-language context pipeline and returns a self-contained "
        "JSON bundle. validate_answer is a stub today (raises "
        "NotImplementedError); its contract is locked in for the future "
        "agent harness / wrapper that drives state management."
    ))

    @mcp.tool(
        name="retrieve_context",
        description=(
            "Retrieve Bible verses with original-language context bundles "
            "for a plain-language query. Returns a structured JSON bundle "
            "(query_analysis, per-intent traces with hits and context_bundle). "
            "Pass the entire returned bundle back as the `context` argument "
            "to validate_answer to fact-check a synthesized answer."
        ),
    )
    async def retrieve_context(
        query: str,
        top_k: int = 10,
        translations: list[str] | None = None,
    ) -> dict:
        return await retrieve_context_impl(
            query, top_k=top_k, translations=translations
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


def main() -> int:
    """Run the MCP stdio server. Never returns under normal operation."""
    try:
        mcp = asyncio.run(_setup_and_build_mcp())
    except ImportError:
        return 1

    # MCPServer.run() is the synchronous entry on v2.x: it wraps anyio.run
    # internally and owns the event loop for the lifetime of the server.
    # On v1.x FastMCP, run() also works (defaults to stdio). Either way
    # this call owns the loop and we must NOT be inside asyncio.run when
    # we call it.
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