#!/usr/bin/env python3
"""Live end-to-end context retrieval integration test.

Runs the full PipelineRunner against the real OpenRouter API and the live
ChromaDB collections, then validates that every hit carries a context_bundle
with the expected structure. The audit trail is now JSONL log records;
this test asserts against the returned bundle shape rather than DB rows.
Skips loudly when the API key is missing or the local data is not fully
populated.

Run with the environment loaded:
    set -a; . ./.env; set +a; .venv/bin/python tests/system/test_context_retrieval_e2e.py
"""

import asyncio
import os
import re
import sys

import chromadb
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config.context_constants import MIN_WORDS_AFTER_TRIM
from config.logging import configure_logging
from services.pipeline.runner import PipelineRunner


QUERY = "what does the Bible say about fear"
MIN_VERSES = 30_000
REFERENCE_RE = re.compile(r'^(?:\w+\s)+\d+:\d+$')


def _check_skip_conditions() -> tuple[bool, str]:
    """Check if we should skip the test and return (should_skip, reason)."""
    load_dotenv()
    api_key = os.getenv('OPENROUTER_STRONGCHAT_DEFAULT_API_KEY')
    if not api_key or api_key == 'your_openrouter_api_key_here':
        return True, "SKIP: OPENROUTER_API_KEY is not present in the environment."

    macula_db_path = os.path.join('data', 'macula_index.db')
    if not os.path.exists(macula_db_path):
        return True, f"SKIP: macula_index.db not found at {macula_db_path}"

    macula_tsv_path = os.path.join('data', 'macula', 'macula-greek.tsv')
    if not os.path.exists(macula_tsv_path):
        return True, f"SKIP: macula-greek.tsv not found at {macula_tsv_path}"

    chroma_path = os.path.join('data', 'chroma')
    if not os.path.isdir(chroma_path):
        return True, f"SKIP: ChromaDB path not found: {chroma_path}"

    client = chromadb.PersistentClient(path=chroma_path)
    for name in ('kjv_verses', 'web_verses'):
        try:
            collection = client.get_collection(name)
        except Exception as exc:
            return True, f"SKIP: cannot open collection {name}: {exc}"

        count = collection.count()
        if count < MIN_VERSES:
            return True, (
                f"SKIP: collection {name} has {count} verses "
                f"(need >= {MIN_VERSES})"
            )

    return False, ""


def _validate_context_bundles(result) -> None:
    """Validate that every hit has a properly structured context_bundle."""
    saw_definitions = False
    saw_gloss = False
    saw_nonempty_bundle = False

    greek_content_pos = ('V-', 'N-', 'A-')
    hebrew_content_pos = ('verb', 'noun', 'proper noun', 'adjective')

    for item in result.results:
        hits = item.get('hits', [])
        for hit in hits:
            assert 'context_bundle' in hit, "hit missing context_bundle key"
            bundle = hit['context_bundle']
            build_summary = bundle.get('build_summary', '')
            if build_summary not in ['unparseable reference'] and not build_summary.startswith('no macula tokens for'):
                kept_word_count = bundle.get('kept_word_count', 0)
                assert kept_word_count >= MIN_WORDS_AFTER_TRIM, (
                    f"kept_word_count {kept_word_count} < {MIN_WORDS_AFTER_TRIM}"
                )

                kept_words = bundle.get('kept_words', [])
                scored_words = bundle.get('scored_words', [])
                unique_word_count = bundle.get('unique_word_count', 0)

                assert len(kept_words) <= len(scored_words)
                assert len(kept_words) <= unique_word_count

                has_content_word = any(
                    word.get('pos', '') in greek_content_pos + hebrew_content_pos
                    for word in scored_words
                )
                assert has_content_word, "no content-word pos detected"

                saw_nonempty_bundle = True

                for w in kept_words:
                    assert isinstance(w.get('strongs'), str) and w['strongs']
                    assert isinstance(w.get('surface'), str) and w['surface']
                    assert isinstance(w.get('lemma'), str) and w['lemma']
                    assert isinstance(w.get('definitions'), list)
                    assert isinstance(w.get('gloss'), str)
                    assert isinstance(w.get('frequency_count'), int) and w['frequency_count'] > 0
                    assert isinstance(w.get('sense_count'), int) and w['sense_count'] >= 1
                    assert isinstance(w.get('composite_score'), (int, float)) and w['composite_score'] > 0
                    assert w.get('lexicon_source') in ('tbESG+LSJ', 'tbESH')
                    assert isinstance(w.get('macula_occurrences'), int) and w['macula_occurrences'] >= 1
                    if w['definitions']:
                        assert w['sense_count'] == len(w['definitions'])
                        saw_definitions = True
                    if w['gloss']:
                        saw_gloss = True

    assert saw_nonempty_bundle, "no non-empty context_bundle was produced for any hit"
    assert saw_definitions, "no kept word has definitions — lexicon ingest may have regressed"
    assert saw_gloss, "no kept word has a gloss — macula_tokens.gloss ingest may be broken"


def _print_top_kept_words(result) -> None:
    """Print the first 3 kept words of the top-scoring hit per translation."""
    hits_by_translation: dict[str, list[dict]] = {}
    for item in result.results:
        translation = item['translation']
        hits = item.get('hits', [])
        hits_by_translation.setdefault(translation, []).extend(hits)

    for translation in sorted(hits_by_translation):
        hits = hits_by_translation[translation]
        hits.sort(key=lambda hit: hit.get('distance', float('inf')))
        top_hit = hits[0]
        bundle = top_hit.get('context_bundle', {})
        kept_words = bundle.get('kept_words', [])

        print(f"  Top {translation.upper()} hit: {top_hit.get('reference', 'unknown')}")
        if kept_words:
            print("    First 3 kept words:")
            for word in kept_words[:3]:
                print(
                    f"      {word.get('strongs', 'no-strongs')}: "
                    f"{word.get('surface', 'no-surface')} "
                    f"({word.get('pos', 'no-pos')}, "
                    f"score: {word.get('composite_score', 0):.3f}, "
                    f"defs: {word.get('definitions', [])}, "
                    f"gloss: {word.get('gloss', '')!r})"
                )
        else:
            print("    No kept words found")


async def run_tests() -> bool:
    """Run the live context retrieval end-to-end test."""
    print("=== Live Context Retrieval End-to-End Integration Test ===\n")

    should_skip, reason = _check_skip_conditions()
    if should_skip:
        print(reason)
        return True

    configure_logging()
    runner = PipelineRunner()
    try:
        result = await runner.run(QUERY, top_k=5)
        print(f"Correlation id: {result.session_uuid}")
        print(f"Intents: {len(result.intents)}")
        print(f"HyDE docs: {len(result.hyde_docs)}")

        _validate_context_bundles(result)
        _print_top_kept_words(result)

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


if __name__ == '__main__':
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)