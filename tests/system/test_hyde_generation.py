#!/usr/bin/env python3
"""Live system test for HyDE generation via OpenRouter.

This test calls the real OpenRouter API for one representative probe,
generates intents, feeds them to HydeService in parallel, and validates that
one HyDE document (or error entry) is produced per intent and that every
successful document meets the minimum length requirement. It also verifies that
each attempted intent is recorded as a ``hyde_generation`` message row.

Run with the environment loaded:
    set -a; . ./.env; set +a; .venv/bin/python tests/system/test_hyde_generation.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.hyde import HydeService
from services.intent import IntentService
from services.sqlite.database import ChatDatabase


QUERY = "what does the Bible say about anxiety"


async def run_tests() -> bool:
    """Run the live HyDE generation system test."""
    print("=== Live HyDE Generation System Test ===\n")

    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key_here":
        print("SKIP: OPENROUTER_API_KEY is not present in the environment.")
        return True

    db = ChatDatabase()
    session_uuid = db.create_session(
        name=f"hyde-test: {QUERY[:50]}",
        created_by="test",
    )
    print(f"Session: {session_uuid}")

    intent_service = IntentService()
    hyde_service = HydeService()

    try:
        intent_result = await intent_service.generate_intents(QUERY, session_uuid)
        intents = intent_result["intents"]
        print(f"Intents returned: {len(intents)}")

        results = await hyde_service.generate_for_intents(intents, session_uuid)
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

        messages = db.get_messages_by_session_and_type(
            session_uuid, "hyde_generation"
        )
        assert len(messages) == len(intents), (
            f"expected {len(intents)} hyde_generation messages, got {len(messages)}"
        )

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
        db.close()


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
