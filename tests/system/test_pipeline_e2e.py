#!/usr/bin/env python3
"""Live end-to-end pipeline integration test.

Runs the full PipelineRunner against the real OpenRouter API and the live
ChromaDB collections, then validates the result shape and the SQLite audit
trail. Skips loudly when the API key is missing or the local verse collections
are not fully populated.

Run with the environment loaded:
    set -a; . ./.env; set +a; .venv/bin/python tests/system/test_pipeline_e2e.py
"""

import asyncio
import os
import re
import sqlite3
import sys
import tempfile

import chromadb
from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.pipeline.runner import PipelineRunner
from services.sqlite.database import ChatDatabase


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


def _get_session_messages(db: ChatDatabase, session_uuid: str) -> list[dict]:
    """Return every message recorded for a session."""
    return db.get_messages_by_session_and_type(session_uuid)


def _get_ref_slugs(db: ChatDatabase) -> set[str]:
    """Return all slugs present in ref_message_types."""
    cursor = db.cursor.execute("SELECT slug FROM ref_message_types")
    return {row[0] for row in cursor.fetchall()}


def _assert_audit_trail(db: ChatDatabase, session_uuid: str, num_intents: int) -> None:
    """Validate message counts and orphan-check the session audit trail."""
    messages = _get_session_messages(db, session_uuid)
    ref_slugs = _get_ref_slugs(db)

    orphan_slugs = {
        msg['message_type_slug']
        for msg in messages
        if msg['message_type_slug'] not in ref_slugs
    }
    assert not orphan_slugs, (
        f"orphan message_type_slug values found: {sorted(orphan_slugs)}"
    )

    counts: dict[str, int] = {}
    for msg in messages:
        counts[msg['message_type_slug']] = counts.get(msg['message_type_slug'], 0) + 1

    assert counts.get('intent_generation') == 1, (
        f"expected 1 intent_generation message, got {counts.get('intent_generation')}"
    )
    assert counts.get('hyde_generation') == num_intents, (
        f"expected {num_intents} hyde_generation messages, got {counts.get('hyde_generation')}"
    )
    assert counts.get('embedding_generation') == 1, (
        f"expected 1 embedding_generation message, got {counts.get('embedding_generation')}"
    )


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
    assert 1 <= num_intents <= 5, (
        f"expected 1-5 intents, got {num_intents}"
    )
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


async def run_tests() -> bool:
    """Run the live end-to-end pipeline test."""
    print("=== Live Pipeline End-to-End Integration Test ===\n")

    load_dotenv()
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key or api_key == 'your_openrouter_api_key_here':
        print("SKIP: OPENROUTER_API_KEY is not present in the environment.")
        return True

    ok, reason = _collection_counts_ok()
    if not ok:
        print(reason)
        return True

    runner = PipelineRunner()
    try:
        result = await runner.run(
            QUERY,
            top_k=5,
            translations=('kjv', 'web'),
        )
        print(f"Session: {result.session_uuid}")
        print(f"Intents: {len(result.intents)}")
        print(f"HyDE docs: {len(result.hyde_docs)}")

        _validate_results(result)
        _assert_audit_trail(runner.db, result.session_uuid, len(result.intents))
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
    """Deliberate negative: a fixture DB with a bogus message type slug.

    Proves that the orphan check flags a row whose message_type_slug is absent
    from ref_message_types.
    """
    schema_sql = """
        CREATE TABLE ref_message_types (
            slug TEXT PRIMARY KEY,
            step_name TEXT,
            creator_type TEXT,
            request_schema TEXT,
            model_slug TEXT,
            temperature REAL,
            additional_model_settings TEXT,
            max_retries INTEGER,
            is_active INTEGER,
            description TEXT,
            prompt_template TEXT
        );
        CREATE TABLE sessions (
            uuid TEXT PRIMARY KEY,
            name TEXT,
            created_by TEXT,
            created_on TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE messages (
            uuid TEXT PRIMARY KEY,
            session_uuid TEXT,
            message_type_slug TEXT,
            unique_prompt TEXT,
            raw_response TEXT,
            created_at TEXT,
            response_at TEXT,
            num_tries INTEGER,
            error_text TEXT
        );
        INSERT INTO ref_message_types (slug) VALUES ('valid_slug');
        INSERT INTO sessions (uuid, name, created_by) VALUES ('sess-1', 'neg', 'test');
        INSERT INTO messages (uuid, session_uuid, message_type_slug, unique_prompt, created_at)
            VALUES ('msg-1', 'sess-1', 'bogus_slug', 'prompt', '2026-07-28T00:00:00');
    """
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as handle:
        db_path = handle.name

    try:
        conn = sqlite3.connect(db_path)
        conn.executescript(schema_sql)
        conn.commit()
        conn.close()

        db = ChatDatabase(db_path)
        messages = _get_session_messages(db, 'sess-1')
        ref_slugs = _get_ref_slugs(db)
        orphan_slugs = {
            msg['message_type_slug']
            for msg in messages
            if msg['message_type_slug'] not in ref_slugs
        }
        db.close()

        assert orphan_slugs == {'bogus_slug'}, (
            f"expected orphan check to flag bogus_slug, got {orphan_slugs}"
        )
        print("Orphan negative check: PASS (bogus_slug flagged)")
    finally:
        os.unlink(db_path)


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
