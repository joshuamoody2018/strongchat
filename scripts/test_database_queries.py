#!/usr/bin/env python3
"""Smoke tests for ChatDatabase query helpers.

Covers the ref_message_types JOINs and the prompt_template column added in
task 4 of the hyde-retrieval-pipeline plan.
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.database import ChatDatabase


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


class TestDatabaseQueries(unittest.TestCase):
    """Verify JOINs to ref_message_types and the prompt_template column."""

    def setUp(self):
        """Build a fresh fixture DB in a temp dir on every test."""
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, 'fixture.db')

        # Apply the live schema before ChatDatabase opens the file
        with sqlite3.connect(self.db_path) as setup_conn:
            setup_conn.executescript(SCHEMA_SQL)
            setup_conn.execute(
                """
                INSERT INTO ref_message_types
                  (slug, step_name, creator_type, request_schema, model_slug,
                   description, prompt_template)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'hyde_gen',
                    'HyDE Generation',
                    'llm',
                    json.dumps({'type': 'object'}),
                    'openai/gpt-3.5-turbo',
                    'Generate a hypothetical answer passage',
                    'Imagine a passage that answers: {query}',
                ),
            )
            setup_conn.commit()

        self.db = ChatDatabase(self.db_path)
        self.session_uuid = self.db.create_session(name='fixture-session')
        self.message_uuid = self.db.create_message_with_type(
            session_uuid=self.session_uuid,
            message_type_slug='hyde_gen',
            unique_prompt='why do bad things happen',
            raw_response='{"hypothetical": "because the world is broken"}',
        )

    def tearDown(self):
        """Close the connection and drop the temp dir."""
        try:
            self.db.close()
        finally:
            self._tmp.cleanup()

    def test_get_message_by_uuid_returns_step_name(self):
        """The LEFT JOIN to ref_message_types must populate step_name."""
        row = self.db.get_message_by_uuid(self.message_uuid)
        self.assertIsNotNone(row)
        self.assertIsNotNone(row['step_name'])
        self.assertEqual(row['step_name'], 'HyDE Generation')
        self.assertEqual(row['message_type_slug'], 'hyde_gen')

    def test_get_message_type_includes_prompt_template(self):
        """get_message_type must surface the new prompt_template column."""
        cfg = self.db.get_message_type('hyde_gen')
        self.assertIsNotNone(cfg)
        self.assertIn('prompt_template', cfg)
        self.assertEqual(
            cfg['prompt_template'],
            'Imagine a passage that answers: {query}',
        )
        # Sanity: existing keys still present
        self.assertEqual(cfg['step_name'], 'HyDE Generation')
        self.assertEqual(cfg['model_slug'], 'openai/gpt-3.5-turbo')

    def test_get_messages_by_session_and_type_joins_step_name(self):
        """The session+type query must also return step_name via the JOIN."""
        rows = self.db.get_messages_by_session_and_type(
            session_uuid=self.session_uuid,
            message_type_slug='hyde_gen',
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]['step_name'])
        self.assertEqual(rows[0]['step_name'], 'HyDE Generation')

    def test_get_message_type_missing_slug_returns_none(self):
        """A missing slug must return None without raising."""
        self.assertIsNone(self.db.get_message_type('does_not_exist'))


def run_tests():
    """Run all tests."""
    print("Testing ChatDatabase query helpers...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestDatabaseQueries))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")

    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")

    print("=" * 50)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
