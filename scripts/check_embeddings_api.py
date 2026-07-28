#!/usr/bin/env python3
"""Smoke check for the OpenRouter /v1/embeddings endpoint.

Mirrors the request shape and headers used by ``src/services/llm/wrapper.py``
but hits the embeddings endpoint with a small two-string payload so the
HyDE retrieval pipeline can rely on the live contract without a database
write or LLM round-trip.

Exit codes:
    0 - success (HTTP 200, response shape matches assertions)
    1 - OPENROUTER_API_KEY missing or placeholder
    2 - HTTP non-200 from OpenRouter
    3 - response shape assertion failed
    4 - unexpected transport / parse failure
"""

import json
import os
import sys
import time

import requests

# Path-bootstrap pattern: make the src/ tree importable when running from
# the repo root. Mirrors scripts/test_parser.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from dotenv import load_dotenv
except ImportError:
    print("ERROR: python-dotenv is required (install into .venv).", file=sys.stderr)
    sys.exit(4)

# Load .env from the repo root (one level up from scripts/).
#
# Snapshot the pre-load environment so we can distinguish "key came from the
# caller" (good) from "key only appeared after load_dotenv read .env" (not
# acceptable for a secret). This keeps the `env -u OPENROUTER_API_KEY`
# failure-QA path meaningful: the .env file is consulted so other settings
# (MODEL_SLUG_INTENTS, etc.) are honored, but the API key must be supplied
# by the calling environment, not by the on-disk .env file.
had_key_in_env = "OPENROUTER_API_KEY" in os.environ
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Constants match the wrapper's base URL and the model we plan to use for
# HyDE query expansion. Two short Bible verses keep the test cheap and
# semantically meaningful.
ENDPOINT = "https://openrouter.ai/api/v1/embeddings"
MODEL = "openai/text-embedding-3-small"
INPUTS = [
    "In the beginning God created the heaven and the earth.",
    "For God so loved the world, that he gave his only begotten Son",
]
EXPECTED_DIM = 1536
TIMEOUT_S = 60

# Header style mirrors src/services/llm/wrapper.py:45-50.
HTTP_REFERER = "http://localhost:8000"
APP_TITLE = "StrongChat"


def fail(code: int, msg: str) -> None:
    """Print to stderr and exit with a non-zero code."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def main() -> int:
    api_key = os.getenv("OPENROUTER_API_KEY")
    # Treat the documented placeholder the same as "not configured", and
    # also reject the case where load_dotenv pulled the key from .env but
    # the caller never supplied one in the real environment.
    if not api_key or api_key == "your_openrouter_api_key_here" or not had_key_in_env:
        print("ERROR: OPENROUTER_API_KEY not configured", file=sys.stderr)
        return 1

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": HTTP_REFERER,
        "X-Title": APP_TITLE,
    }
    payload = {"model": MODEL, "input": INPUTS}

    try:
        t0 = time.perf_counter()
        resp = requests.post(ENDPOINT, headers=headers, json=payload, timeout=TIMEOUT_S)
        latency_ms = (time.perf_counter() - t0) * 1000.0
    except requests.RequestException as exc:
        print(f"ERROR: transport failure: {exc}", file=sys.stderr)
        return 4

    if resp.status_code != 200:
        # Truncate the body to keep evidence files readable.
        body = resp.text.strip().replace("\n", " ")
        if len(body) > 400:
            body = body[:400] + "..."
        print(
            f"ERROR: HTTP {resp.status_code} from {ENDPOINT}: {body}",
            file=sys.stderr,
        )
        return 2

    try:
        body = resp.json()
    except ValueError as exc:
        print(f"ERROR: response was not valid JSON: {exc}", file=sys.stderr)
        return 4

    data = body.get("data")
    if not isinstance(data, list) or len(data) != 2:
        print(
            f"ERROR: expected 2 embeddings, got "
            f"{len(data) if isinstance(data, list) else type(data).__name__}",
            file=sys.stderr,
        )
        return 3

    first_embedding = data[0].get("embedding")
    if not isinstance(first_embedding, list) or len(first_embedding) != EXPECTED_DIM:
        actual = (
            len(first_embedding)
            if isinstance(first_embedding, list)
            else type(first_embedding).__name__
        )
        print(
            f"ERROR: dim assertion failed: expected {EXPECTED_DIM}, got {actual}",
            file=sys.stderr,
        )
        return 3

    # Success output: keep keys stable so the evidence file is greppable.
    usage = body.get("usage", {})
    print(f"endpoint={ENDPOINT}")
    print(f"model={body.get('model', MODEL)}")
    print(f"latency_ms={latency_ms:.1f}")
    print(f"count={len(data)}")
    print(f"dim={len(first_embedding)}")
    if usage:
        # Print usage on one line for easy diffing across runs.
        print(f"usage={json.dumps(usage, sort_keys=True)}")
    else:
        print("usage=<absent>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
