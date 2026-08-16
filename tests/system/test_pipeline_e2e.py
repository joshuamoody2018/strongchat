#!/usr/bin/env python3
"""Live end-to-end pipeline integration test.

Runs the full PipelineRunner against the real OpenRouter API and the live
ChromaDB collections, then validates the returned bundle shape. Audit trail
is JSONL log records; no application DB. Skips loudly when the API key is
missing or the local verse collections are not fully populated.

Run with the environment loaded:
    set -a; . ./.env; set +a; .venv/bin/python tests/system/test_pipeline_e2e.py
"""

import asyncio
import os
import re
import sys

import chromadb
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config.logging import configure_logging
from services.pipeline import PipelineRunner, pipeline_result_to_bundle


QUERY = "why do bad things happen to good people"
MIN_VERSES = 30_000
REFERENCE_RE = re.compile(r'^(?:\w+\s)+\d+:\d+$')


def _collection_counts_ok() -> tuple[bool, str]:
    """Return (ok, reason) for the local ChromaDB collections."""
    chroma_path = os.path.join('data', 'chroma')
    if not os.path.isdir(chroma_path):
        return False, f"SKIP: ChromaDB path not found: {chroma_path}"

    client = chromadb.PersistentClient(path=chroma_path)
    for name in ('kjv_verses', 'web_verses'):
        try:
            collection = client.get_collection(name)
        except Exception as exc:
            return False, f"SKIP: cannot open collection {name}: {exc}"

        count = collection.count()
        if count < MIN_VERSES:
            return False, (
                f"SKIP: collection {name} has {count} verses "
                f"(need >= {MIN_VERSES})"
            )

    return True, ""


def _print_top_hits(result) -> None:
    """Print the closest hit reference and snippet for each translation."""
    hits_by_translation: dict[str, list[dict]] = {}
    for item in result.results:
        translation = item['translation']
        hits_by_translation.setdefault(translation, []).extend(item.get('hits', []))

    for translation in sorted(hits_by_translation):
        hits = hits_by_translation[translation]
        hits.sort(key=lambda hit: hit['distance'])
        top = hits[0]
        snippet = top.get('text', '')[:200].replace('\n', ' ')
        print(f"  Top {translation.upper()} hit: {top['reference']} | {snippet}...")


def _validate_references(result) -> None:
    """Ensure every hit reference matches the expected verse reference shape."""
    for item in result.results:
        for hit in item.get('hits', []):
            reference = hit.get('reference', '')
            assert REFERENCE_RE.match(reference), (
                f"reference {reference!r} does not match ^\\w+ \\d+:\\d+$"
            )


def _validate_results(result) -> None:
    """Validate result counts, shape, and non-empty retrieval for both translations."""
    num_intents = len(result.intents)
    assert 1 <= num_intents <= 5, f"expected 1-5 intents, got {num_intents}"
    assert len(result.hyde_docs) == num_intents, (
        f"expected {num_intents} hyde_docs, got {len(result.hyde_docs)}"
    )

    translations_found = {item['translation'] for item in result.results}
    assert 'kjv' in translations_found, "no retrieval results for kjv"
    assert 'web' in translations_found, "no retrieval results for web"

    for item in result.results:
        assert len(item.get('hits', [])) > 0, (
            f"no hits for intent {item.get('intent_id')} / {item.get('translation')}"
        )

    _validate_references(result)


def _validate_bundle_shape(result) -> None:
    """The serialized JSON bundle carries the correlation id + per-intent traces."""
    bundle = pipeline_result_to_bundle(result)
    assert bundle["correlation_id"] == result.session_uuid
    assert bundle["query"] == result.query
    assert isinstance(bundle["traces"], list)
    assert len(bundle["traces"]) == len(result.intents)
    for trace in bundle["traces"]:
        assert "intent_id" in trace
        assert "intent_data" in trace
        assert "hyde_document" in trace
        assert "search_results" in trace
        # Embeddings must be dropped (never serialized to the agent).
        for hits in trace["search_results"].values():
            for hit in hits:
                assert "embedding" not in hit


async def run_tests() -> bool:
    """Run the live end-to-end pipeline test."""
    print("=== Live Pipeline End-to-End Integration Test ===\n")

    load_dotenv()
    api_key = os.getenv('OPENROUTER_STRONGCHAT_DEFAULT_API_KEY')
    if not api_key or api_key == 'your_openrouter_api_key_here':
        print("SKIP: OPENROUTER_STRONGCHAT_DEFAULT_API_KEY is not present in the environment.")
        return True

    ok, reason = _collection_counts_ok()
    if not ok:
        print(reason)
        return True

    configure_logging()
    runner = PipelineRunner()
    try:
        result = await runner.run(
            QUERY,
            top_k=5,
            translations=('kjv', 'web'),
        )
        print(f"Correlation id: {result.session_uuid}")
        print(f"Intents: {len(result.intents)}")
        print(f"HyDE docs: {len(result.hyde_docs)}")

        _validate_results(result)
        _validate_bundle_shape(result)
        _print_top_hits(result)

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
        runner.close()


def run_orphan_negative_check() -> None:
    """Deliberate negative: validate that the bundle never carries embeddings.

    The original SQLite-era orphan check verified FK integrity. Now that
    there is no application DB, the equivalent regression guard asserts that
    the serialized bundle drops embedding vectors.
    """
    from dataclasses import dataclass, field
    from typing import Any, Dict, List, Optional
    from services.pipeline.runner import IntentTrace, PipelineResult
    from services.pipeline.serializer import pipeline_result_to_bundle

    trace = IntentTrace(
        intent_id="neg-test",
        intent_data={"intent_id": "neg-test"},
        hyde_document="hyde",
        embedding=[0.1, 0.2, 0.3],
        search_results={
            "kjv": [
                {
                    "id": "k1",
                    "text": "loved",
                    "reference": "John 3:16",
                    "distance": 0.0,
                    # Pretend the retrieval stage leaked an embedding onto the hit.
                    "embedding": [0.4, 0.5],
                }
            ]
        },
    )
    result = PipelineResult(
        session_uuid="neg-correlation",
        query="neg",
        traces={"neg-test": trace},
    )
    bundle = pipeline_result_to_bundle(result)
    assert "embedding" not in bundle["traces"][0], (
        "bundle trace leaked the per-intent embedding"
    )
    assert "embedding" not in bundle["traces"][0]["search_results"]["kjv"][0], (
        "bundle hit leaked the embedding vector — serializer regressed"
    )
    print("Orphan negative check: PASS (_embeddings dropped from bundle)")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--orphan-negative':
        try:
            run_orphan_negative_check()
            sys.exit(0)
        except AssertionError as exc:
            print(f"Orphan negative check: FAIL ({exc})")
            sys.exit(1)
        except Exception as exc:
            print(f"Orphan negative check: ERROR ({exc})")
            sys.exit(1)

    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)