#!/usr/bin/env python3
"""Live end-to-end context retrieval integration test.

Runs the full PipelineRunner against the real OpenRouter API and the live
ChromaDB collections, then validates that every hit carries a context_bundle
with the expected structure. Skips loudly when the API key is missing or the
local data is not fully populated.

Run with the environment loaded:
    set -a; . ./.env; set +a; .venv/bin/python tests/system/test_context_retrieval_e2e.py
"""

import asyncio
import json
import os
import re
import sqlite3
import sys

import chromadb
from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.pipeline.runner import PipelineRunner
from config.context_constants import MIN_WORDS_AFTER_TRIM
from services.sqlite.database import ChatDatabase


QUERY = "what does the Bible say about fear"
MIN_VERSES = 30_000
REFERENCE_RE = re.compile(r'^(?:\w+\s)+\d+:\d+$')


def _check_skip_conditions() -> tuple[bool, str]:
    """Check if we should skip the test and return (should_skip, reason)."""
    # Check API key
    load_dotenv()
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key or api_key == 'your_openrouter_api_key_here':
        return True, "SKIP: OPENROUTER_API_KEY is not present in the environment."
    
    # Check macula_index.db
    macula_db_path = os.path.join('data', 'macula_index.db')
    if not os.path.exists(macula_db_path):
        return True, f"SKIP: macula_index.db not found at {macula_db_path}"
    
    # Check macula-greek.tsv
    macula_tsv_path = os.path.join('data', 'macula', 'macula-greek.tsv')
    if not os.path.exists(macula_tsv_path):
        return True, f"SKIP: macula-greek.tsv not found at {macula_tsv_path}"
    
    # Check ChromaDB collections
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


def _get_context_retrieval_messages(db: ChatDatabase, session_uuid: str) -> list[dict]:
    """Return all context_retrieval messages for a session.

    Queries the chat DB directly rather than going through ChatDatabase,
    which does not expose a sync get_messages_by_session_and_type accessor
    (the async port does, but the e2e test runs synchronously after the
    pipeline completes). Mirrors the pattern in
    tests/scripts/test_context_retrieval_service.py.
    """
    db_path = db.db_path if hasattr(db, 'db_path') else 'data/chat_database.db'
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            'SELECT uuid, session_uuid, message_type_slug, unique_prompt, '
            'raw_response, created_at, response_at, num_tries, error_text '
            'FROM messages WHERE session_uuid = ? AND message_type_slug = ?',
            (session_uuid, 'context_retrieval'),
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _validate_context_bundles(result) -> None:
    """Validate that every hit has a properly structured context_bundle."""
    saw_definitions = False  # regression canary for strongs-key normalization
    saw_gloss = False         # regression canary for macula gloss schema
    saw_nonempty_bundle = False  # gating flag: only fire canaries if >= 1 bundle had kept words
    for item in result.results:
        hits = item.get('hits', [])
        for hit in hits:
            # (a) every hit has a context_bundle key
            assert 'context_bundle' in hit, "hit missing context_bundle key"

            bundle = hit['context_bundle']

            # Only validate kept_word_count for successful retrievals
            build_summary = bundle.get('build_summary', '')
            if build_summary not in ['unparseable reference'] and not build_summary.startswith('no macula tokens for'):
                # (b) every successful context_bundle has kept_word_count >= MIN_WORDS_AFTER_TRIM
                kept_word_count = bundle.get('kept_word_count', 0)
                assert kept_word_count >= MIN_WORDS_AFTER_TRIM, (
                    f"kept_word_count {kept_word_count} < {MIN_WORDS_AFTER_TRIM} for successful retrieval"
                )

                # (c) kept_words is a strict subset of the unique-word count from scored_words
                kept_words = bundle.get('kept_words', [])
                scored_words = bundle.get('scored_words', [])
                unique_word_count = bundle.get('unique_word_count', 0)

                assert len(kept_words) <= len(scored_words), (
                    f"kept_words count {len(kept_words)} > scored_words count {len(scored_words)}"
                )
                assert len(kept_words) <= unique_word_count, (
                    f"kept_words count {len(kept_words)} > unique_word_count {unique_word_count}"
                )

                # (d) at least one scored_words entry has pos in ('V-', 'N-')
                has_content_word = any(
                    word.get('pos', '') in ('V-', 'N-')
                    for word in scored_words
                )
                assert has_content_word, (
                    "no scored_words entry with pos in ('V-', 'N-')"
                )

                saw_nonempty_bundle = True

                # (e) every kept_word has the full contract: non-empty
                # strongs/surface/lemma, correct types for numeric and list
                # fields, lexicon_source tag, composite_score > 0. Catches
                # drift between live output and the synthesis-ready schema.
                for w in kept_words:
                    assert isinstance(w.get('strongs'), str) and w['strongs'], (
                        f"kept word strongs must be a non-empty str: {w.get('strongs')!r}")
                    assert isinstance(w.get('surface'), str) and w['surface'], (
                        f"kept word surface must be a non-empty str: {w.get('surface')!r}")
                    assert isinstance(w.get('lemma'), str) and w['lemma'], (
                        f"kept word lemma must be a non-empty str: {w.get('lemma')!r}")
                    assert isinstance(w.get('definitions'), list), (
                        f"definitions must be a list: {w.get('definitions')!r}")
                    assert isinstance(w.get('gloss'), str), (
                        f"gloss must be a str: {w.get('gloss')!r}")
                    assert isinstance(w.get('frequency_count'), int) and w['frequency_count'] > 0, (
                        f"frequency_count must be a positive int: {w.get('frequency_count')!r}")
                    assert isinstance(w.get('sense_count'), int) and w['sense_count'] >= 1, (
                        f"sense_count must be int >= 1: {w.get('sense_count')!r}")
                    assert isinstance(w.get('composite_score'), (int, float)) and w['composite_score'] > 0, (
                        f"composite_score must be positive number: {w.get('composite_score')!r}")
                    assert w.get('lexicon_source') == 'tbESG+LSJ', (
                        f"lexicon_source must be 'tbESG+LSJ': {w.get('lexicon_source')!r}")
                    assert isinstance(w.get('macula_occurrences'), int) and w['macula_occurrences'] >= 1, (
                        f"macula_occurrences must be int >= 1: {w.get('macula_occurrences')!r}")
                    # sense_count must match len(definitions) when defs exist
                    if w['definitions']:
                        assert w['sense_count'] == len(w['definitions']), (
                            f"sense_count {w['sense_count']} != len(definitions) "
                            f"{len(w['definitions'])} for strongs {w['strongs']}")

                    if w['definitions']:
                        saw_definitions = True
                    if w['gloss']:
                        saw_gloss = True

    # (f) regression canaries: gated on saw_nonempty_bundle so a result set
    # of purely-OT verses (which legitimately have no Macula tokens and thus
    # no definitions) does not false-fire. If at least one non-empty bundle
    # was produced, at least one of its kept words must carry non-empty
    # definitions and a non-empty gloss. If either fires, a downstream ingest
    # script (build_lexicon_index.py or build_macula_index.py) has regressed
    # and the context bundle is no longer synthesis-ready.
    assert saw_nonempty_bundle, (
        "no non-empty context_bundle was produced for any hit — either every "
        "retrieved verse was OT (no Macula tokens), or context retrieval is "
        "silently producing all-empty bundles"
    )
    assert saw_definitions, (
        "no kept word across any non-empty bundle has definitions — lexicon "
        "strongs key normalization may have regressed (see "
        "scripts/build_lexicon_index.py:normalize_strongs)"
    )
    assert saw_gloss, (
        "no kept word across any non-empty bundle has a gloss — macula_tokens."
        "gloss ingest may be broken (see scripts/build_macula_index.py)"
    )


def _validate_context_retrieval_messages(db: ChatDatabase, session_uuid: str, num_intents: int, result) -> None:
    """Validate context_retrieval message counts and error status."""
    messages = _get_context_retrieval_messages(db, session_uuid)
    
    # (e) one context_retrieval row per intent that had search results
    expected_count = sum(1 for trace in result.traces.values() if trace.search_results)
    assert len(messages) == expected_count, (
        f"expected {expected_count} context_retrieval messages, got {len(messages)}"
    )
    
    # (f) every context_retrieval row has error_text IS NULL
    for msg in messages:
        assert msg.get('error_text') is None, (
            f"context_retrieval message has error_text: {msg.get('error_text')}"
        )


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
    
    runner = PipelineRunner()
    try:
        result = await runner.run(QUERY, top_k=5)
        print(f"Session: {result.session_uuid}")
        print(f"Intents: {len(result.intents)}")
        print(f"HyDE docs: {len(result.hyde_docs)}")
        
        _validate_context_bundles(result)
        _validate_context_retrieval_messages(runner.db, result.session_uuid, len(result.intents), result)
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