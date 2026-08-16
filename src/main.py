#!/usr/bin/env python3
"""CLI smoke-test for the StrongChat retrieval pipeline.

Calls the same ``retrieve_context_impl`` function the MCP server exposes,
prints the returned bundle as JSON to stdout. Useful for ad-hoc dev/debug
without spinning up an MCP client. NOT a production entry point; the MCP
server (``src/server.py``) is the real entry point now.
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

from config.logging import configure_logging
from services.pipeline import pipeline_result_to_bundle
from services.pipeline.runner import PipelineRunner


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the StrongChat pipeline and print the JSON bundle."
    )
    parser.add_argument("query", help="User query to process")
    parser.add_argument(
        "--top-k", type=int, default=10, help="Hits per HyDE doc / translation"
    )
    parser.add_argument(
        "--translations",
        nargs="+",
        default=["kjv", "web"],
        help="Translation slugs to query (default: kjv web)",
    )
    args = parser.parse_args()

    runner = PipelineRunner()
    try:
        result = await runner.run(
            query=args.query,
            top_k=args.top_k,
            translations=tuple(args.translations),
        )
        print(json.dumps(pipeline_result_to_bundle(result), indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.close()


if __name__ == "__main__":
    had_api_key = "OPENROUTER_API_KEY" in os.environ
    load_dotenv()
    if not had_api_key and "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    configure_logging()
    sys.exit(asyncio.run(main()))