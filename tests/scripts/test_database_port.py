#!/usr/bin/env python3
"""Offline tests for the async DatabasePort and SQLite adapter.

Creates a temporary fixture database with the live schema, seeds an
``embedding_generation`` message type, and exercises every required async
method of ``AsyncSQLiteDatabase``.
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
import uuid

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.database.adapters.sqlite import AsyncSQLiteDatabase


SCHEMA_SQL = """
CREATE TABLE sessions (
    uuid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT
);

CREATE TABLE ref_message_types (
    slug TEXT PRIMARY KEY,
    step_name TEXT NOT NULL,
    creator_type TEXT NOT NULL,
    request_schema TEXT NOT NULL,
    model_slug TEXT NOT NULL,
    temperature REAL DEFAULT 0.1,
    additional_model_settings TEXT,
    max_retries INTEGER DEFAULT 3,
    is_active BOOLEAN DEFAULT TRUE,
    description TEXT,
    prompt_template TEXT
);

CREATE TABLE messages (
    uuid TEXT PRIMARY KEY,
    session_uuid TEXT,
    message_type_slug TEXT,
    unique_prompt TEXT NOT NULL,
    raw_response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_at TIMESTAMP,
    num_tries INTEGER DEFAULT 1,
    error_text TEXT,
    FOREIGN KEY (session_uuid) REFERENCES sessions (uuid),
    FOREIGN KEY (message_type_slug) REFERENCES ref_message_types (slug)
);
"""

EMBEDDING_TYPE_ROW = (
    'embedding_generation',
    'Embedding Generation',
    'programmatic',
    json.dumps({
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "dimension": {"type": "integer"},
            "count": {"type": "integer"},
        },
        "required": ["model", "dimension", "count"],
    }),
    'openai/text-embedding-3-small',
    0.0,
    '{}',
    3,
    1,
    'Batched embedding generation call record',
    None,
)


def _is_uuid(value: str) -> bool:
    """Return True if value is a valid UUID4 string."""
    try:
        uuid.UUID(value, version=4)
        return True
    except (ValueError, TypeError):
        return False


class TestDatabasePort(unittest.IsolatedAsyncioTestCase):
    """Verify AsyncSQLiteDatabase against the DatabasePort contract."""

    async def asyncSetUp(self):
        """Create a fresh fixture database for each test."""
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, 'fixture.db')

        with sqlite3.connect(self.db_path) as setup_conn:
            setup_conn.executescript(SCHEMA_SQL)
            setup_conn.execute(
                """
                INSERT INTO ref_message_types
                  (slug, step_name, creator_type, request_schema, model_slug,
                   temperature, additional_model_settings, max_retries,
                   is_active, description, prompt_template)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                EMBEDDING_TYPE_ROW,
            )
            setup_conn.commit()

        self.db = AsyncSQLiteDatabase(self.db_path)

    async def asyncTearDown(self):
        """Close the adapter and remove the temporary database."""
        try:
            await self.db.close()
        finally:
            self._tmp.cleanup()

    async def test_create_session_returns_uuid(self):
        """create_session must return a valid UUID string."""
        session_uuid = await self.db.create_session('test-session')
        self.assertTrue(_is_uuid(session_uuid))

    async def test_create_message_with_type_returns_uuid(self):
        """create_message_with_type must return a valid UUID string."""
        session_uuid = await self.db.create_session('test-session')
        message_uuid = await self.db.create_message_with_type(
            session_uuid=session_uuid,
            message_type_slug='embedding_generation',
            unique_prompt='test prompt',
        )
        self.assertTrue(_is_uuid(message_uuid))

    async def test_get_message_type_returns_seeded_row(self):
        """get_message_type must return the seeded embedding_generation row."""
        cfg = await self.db.get_message_type('embedding_generation')
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg['slug'], 'embedding_generation')
        self.assertEqual(cfg['model_slug'], 'openai/text-embedding-3-small')
        self.assertTrue(cfg['is_active'])

    async def test_context_manager_closes_on_exit(self):
        """The async context manager must open and close cleanly."""
        async with AsyncSQLiteDatabase(self.db_path) as db:
            session_uuid = await db.create_session('context-session')
            self.assertTrue(_is_uuid(session_uuid))


def run_tests():
    """Run the DatabasePort adapter tests."""
    print("Testing DatabasePort / AsyncSQLiteDatabase adapter...")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestDatabasePort)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
