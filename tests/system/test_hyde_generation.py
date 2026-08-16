#!/usr/bin/env python3
"""Live system test for HyDE generation via OpenRouter.

Calls the real OpenRouter API for one representative probe, generates
intents, feeds them to HydeService in parallel, and validates that one
HyDE document (or error entry) is produced per intent. The audit trail is
now JSONL log records; no application DB.
"""

import asyncio
import os
import sys
import uuid

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config.logging import configure_logging
from services.hyde import HydeService
from services.intent import IntentService


QUERY = "what does the Bible say about anxiety"


async def run_tests() -> bool:
    """Run the live HyDE generation system test."""
    print("=== Live HyDE Generation System Test ===\n")
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key_here":
        print("SKIP: OPENROUTER_API_KEY is not present in the environment.")
        return True

    configure_logging()
    correlation_id = f"hyde-test-{uuid.uuid4()}"
    print(f"Correlation id: {correlation_id}")

    intent_service = IntentService()
    hyde_service = HydeService()

    try:
        intent_result = await intent_service.generate_intents(QUERY, correlation_id)
        intents = intent_result["intents"]
        print(f"Intents returned: {len(intents)}")

        results = await hyde_service.generate_for_intents(intents, correlation_id)
        assert len(results) == len(intents), (
            f"expected {len(intents)} results, got {len(results)}"
        )

        success_count = 0
        for result in results:
            doc = result.get("hyde_document")
            if doc is not None:
                assert len(doc) >= 50, (
                    f"doc for {result['intent_id']} too short ({len(doc)} chars)"
                )
                success_count += 1

        print(f"Successful HyDE docs: {success_count}/{len(intents)}")

        print("\n=== Result ===")
        print("PASS")
        return True
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        return False
    except Exception as exc:
        print(f"ERROR: {exc}")
        return False
    finally:
        intent_service.llm.close()
        hyde_service.llm.close()


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)