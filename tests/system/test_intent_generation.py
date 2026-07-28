#!/usr/bin/env python3
"""Live system test for intent generation via OpenRouter.

This test calls the real OpenRouter API for three representative probes and
validates that IntentService.generate_intents returns structured intents that
satisfy the INTENT_GENERATION_SCHEMA. It also verifies that each call is
recorded in the database as a single intent_generation message.

Run with the environment loaded:
    set -a; . ./.env; set +a; .venv/bin/python tests/system/test_intent_generation.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.intent import IntentService
from services.sqlite.database import ChatDatabase


PROBES = [
    "why do bad things happen to good people",
    "how do I deal with anxiety about the future",
    "what does the Bible say about forgiving someone who hurt me",
]


def validate_intents(intents: list[dict]) -> None:
    """Validate the intents list against the task's structural assertions."""
    assert 1 <= len(intents) <= 5, f"expected 1-5 intents, got {len(intents)}"

    primary_count = 0
    for intent in intents:
        assert intent.get("interpretation"), "intent missing non-empty interpretation"
        assert len(intent.get("keywords_explicit", [])) > 0, "intent missing keywords_explicit"
        assert len(intent.get("keywords_inferred", [])) > 0, "intent missing keywords_inferred"
        assert len(intent.get("themes", [])) > 0, "intent missing themes"
        if intent.get("is_primary"):
            primary_count += 1

    assert primary_count >= 1, "expected at least one primary intent"


async def test_probe(service: IntentService, db: ChatDatabase, probe: str) -> None:
    """Generate intents for one probe and validate the result plus DB record."""
    session_uuid = db.create_session(
        name=f"intent-test: {probe[:50]}",
        created_by="test",
    )
    print(f"  Session: {session_uuid}")

    result = await service.generate_intents(probe, session_uuid)

    intents = result["intents"]
    print(f"  Intents returned: {len(intents)}")
    validate_intents(intents)

    messages = db.get_messages_by_session_and_type(session_uuid, "intent_generation")
    assert len(messages) == 1, f"expected 1 intent_generation message, got {len(messages)}"
    assert messages[0]["raw_response"] is not None, "raw_response must not be null"

    print(f"  PASS: {probe[:50]}")


async def run_tests() -> bool:
    """Run the live intent generation test for all probes."""
    print("=== Live Intent Generation System Test ===\n")

    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key_here":
        print("SKIP: OPENROUTER_API_KEY is not present in the environment.")
        return True

    service = IntentService()
    db = service.db

    all_passed = True
    for probe in PROBES:
        print(f"Probe: {probe}")
        try:
            await test_probe(service, db, probe)
        except AssertionError as exc:
            print(f"  FAIL: {exc}")
            all_passed = False
        except Exception as exc:
            print(f"  ERROR: {exc}")
            all_passed = False

    db.close()
    print("\n=== Result ===")
    print("PASS" if all_passed else "FAIL")
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
