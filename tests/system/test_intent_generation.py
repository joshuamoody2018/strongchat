#!/usr/bin/env python3
"""Live system test for intent generation via OpenRouter.

Calls the real OpenRouter API for three representative probes and validates
that IntentService.generate_intents returns structured intents satisfying
the INTENT_GENERATION_SCHEMA. The audit trail is now JSONL log records;
this test asserts the structured response shape rather than session rows.
There is no application DB.
"""

import asyncio
import logging
import os
import sys
import uuid

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config.logging import configure_logging
from services.intent import IntentService


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


async def test_probe(service: IntentService, probe: str) -> None:
    """Generate intents for one probe and validate the response shape."""
    correlation_id = f"intent-test-{uuid.uuid4()}"
    print(f"  Correlation id: {correlation_id}")
    result = await service.generate_intents(probe, correlation_id)
    intents = result["intents"]
    print(f"  Intents returned: {len(intents)}")
    validate_intents(intents)
    assert result["message_uuid"], "message_uuid must be non-empty"
    print(f"  PASS: {probe[:50]}")


async def run_tests() -> bool:
    """Run the live intent generation test for all probes."""
    print("=== Live Intent Generation System Test ===\n")
    load_dotenv()
    api_key = os.getenv("OPENROUTER_STRONGCHAT_DEFAULT_API_KEY")
    if not api_key or api_key == "your_OPENROUTER_STRONGCHAT_DEFAULT_API_KEY_here":
        print("SKIP: OPENROUTER_STRONGCHAT_DEFAULT_API_KEY is not present in the environment.")
        return True

    configure_logging()
    service = IntentService()

    all_passed = True
    for probe in PROBES:
        print(f"Probe: {probe}")
        try:
            await test_probe(service, probe)
        except AssertionError as exc:
            print(f"  FAIL: {exc}")
            all_passed = False
        except Exception as exc:
            print(f"  ERROR: {exc}")
            all_passed = False

    service.llm.close()
    print("\n=== Result ===")
    print("PASS" if all_passed else "FAIL")
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)