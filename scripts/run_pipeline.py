#!/usr/bin/env python3
"""CLI runner for the full StrongChat retrieval pipeline.

Orchestrates intent generation → HyDE generation → embedding retrieval
across requested translations and prints a structured summary.
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

# Add src directory to path before any service imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.pipeline import PipelineRunner


def _parse_translations(value: str) -> tuple[str, ...]:
    """Split a comma-separated translation list into a tuple."""
    return tuple(part.strip() for part in value.split(",") if part.strip())


async def _main() -> int:
    """Run the pipeline and return the shell exit code."""
    parser = argparse.ArgumentParser(
        description="Run the StrongChat intent → HyDE → retrieval pipeline."
    )
    parser.add_argument("query", help="User query to process")
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of nearest neighbors per HyDE document/translation (default: 10)",
    )
    parser.add_argument(
        "--translations",
        type=str,
        default="kjv,web",
        help="Comma-separated translation slugs (default: kjv,web)",
    )
    args = parser.parse_args()

    translations = _parse_translations(args.translations)
    if not translations:
        print("error: at least one translation is required", file=sys.stderr)
        return 1

    runner = PipelineRunner()
    try:
        result = await runner.run(
            query=args.query,
            top_k=args.top_k,
            translations=translations,
        )
        runner.print_summary(result)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1
    finally:
        runner.close()


if __name__ == "__main__":
    # Honor a deliberately unset key in the parent shell (env -u) while still
    # loading other .env values such as model slugs.
    had_api_key = "OPENROUTER_API_KEY" in os.environ
    load_dotenv()
    if not had_api_key and "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    sys.exit(asyncio.run(_main()))
