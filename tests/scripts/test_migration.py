#!/usr/bin/env python3
"""Tests for scripts/migrate_pipeline_message_types.py.

Runs the migration TWICE against a temp COPY of the live database (the live
DB is never migrated by these tests) and verifies row flags, idempotency,
and foreign-key enforcement via ChatDatabase (PRAGMA foreign_keys = ON).
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

# Add src and scripts directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from services.sqlite.database import ChatDatabase
import migrate_pipeline_message_types as migration

LIVE_DB = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'chat_database.db')

EXPECTED_ACTIVE = {
    'human_input',
    'intent_generation',
    'hyde_generation',
    'embedding_generation',
    'llm_response',
}


class TestPipelineMessageTypeMigration(unittest.TestCase):
    """Verify migration contents, idempotency, and FK enforcement on a copy."""

    def setUp(self):
        """Copy the live DB to a temp dir and run the migration once."""
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, 'copy.db')
        shutil.copyfile(LIVE_DB, self.db_path)
        migration.migrate(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            self.rows_after_first = conn.execute(
                "SELECT * FROM ref_message_types ORDER BY slug"
            ).fetchall()
            self.message_count = conn.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]

    def tearDown(self):
        """Drop the temp dir (copy DB and its .pre-pipeline.bak)."""
        self._tmp.cleanup()

    def _flags(self):
        with sqlite3.connect(self.db_path) as conn:
            return dict(
                conn.execute(
                    "SELECT slug, is_active FROM ref_message_types"
                ).fetchall()
            )

    def test_backup_written(self):
        """The pre-pipeline backup must exist next to the migrated copy."""
        self.assertTrue(
            os.path.exists(self.db_path + migration.BACKUP_SUFFIX),
            "backup file was not written",
        )

    def test_ref_rows_present_with_expected_flags(self):
        """All expected rows are active; intent_disambiguation is gone."""
        flags = self._flags()
        for slug in EXPECTED_ACTIVE:
            self.assertEqual(flags.get(slug), 1, f"{slug} should be active")
        self.assertNotIn('intent_disambiguation', flags)
        self.assertNotIn('intent_classification', flags)
        self.assertNotIn('error', flags)
        self.assertNotIn('corpus_ingest', flags)
        self.assertEqual(len(flags), 5)

    def test_new_row_field_values(self):
        """Spot-check the seeded rows carry the specified field values."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = {
                row['slug']: dict(row)
                for row in conn.execute(
                    "SELECT * FROM ref_message_types WHERE slug IN (?, ?, ?, ?, ?)",
                    (
                        'human_input',
                        'intent_generation',
                        'hyde_generation',
                        'embedding_generation',
                        'llm_response',
                    ),
                )
            }
        self.assertEqual(rows['human_input']['creator_type'], 'human')
        self.assertEqual(rows['human_input']['step_name'], 'Human Input')
        self.assertEqual(rows['intent_generation']['creator_type'], 'programmatic')
        self.assertEqual(rows['intent_generation']['step_name'], 'Intent Generation')
        self.assertEqual(rows['hyde_generation']['creator_type'], 'programmatic')
        self.assertEqual(rows['hyde_generation']['step_name'], 'HyDE Generation')
        self.assertEqual(
            rows['embedding_generation']['model_slug'],
            'openai/text-embedding-3-small',
        )
        self.assertEqual(rows['llm_response']['creator_type'], 'llm')
        self.assertEqual(rows['llm_response']['step_name'], 'LLM Response')
        
        for slug, row in rows.items():
            self.assertEqual(row['max_retries'], 3, slug)
            self.assertEqual(row['is_active'], 1, slug)
            
            # Check additional_model_settings - some have actual settings
            if slug in ['intent_generation', 'hyde_generation']:
                self.assertIn('max_tokens', json.loads(row['additional_model_settings']), slug)
                self.assertIsNotNone(row['prompt_template'], slug)
                # Check specific temperatures
                if slug == 'intent_generation':
                    self.assertEqual(row['temperature'], 0.2, slug)
                else:  # hyde_generation
                    self.assertEqual(row['temperature'], 0.7, slug)
            else:
                self.assertEqual(row['additional_model_settings'], '{}', slug)
                self.assertIsNone(row['prompt_template'], slug)
                self.assertEqual(row['temperature'], 0.0, slug)

    def test_intent_generation_row_values(self):
        """The intent_generation row carries the refined schema/prompt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = dict(
                conn.execute(
                    "SELECT * FROM ref_message_types WHERE slug = ?",
                    ('intent_generation',),
                ).fetchone()
            )
        self.assertEqual(row['step_name'], 'Intent Generation')
        self.assertEqual(row['creator_type'], 'programmatic')
        self.assertEqual(row['model_slug'], migration.MODEL_INTENT_GENERATION)
        self.assertEqual(row['temperature'], 0.2)
        self.assertEqual(row['max_retries'], 3)
        self.assertEqual(row['is_active'], 1)
        self.assertEqual(row['additional_model_settings'], '{"max_tokens": 1200}')
        self.assertIsNotNone(row['prompt_template'])
        self.assertIn('{query}', row['prompt_template'])
        self.assertIsNotNone(row['request_schema'])
        self.assertIn('IntentGenerationResponse', row['request_schema'])

    def test_hyde_generation_row_values(self):
        """The hyde_generation row carries the HyDE schema/prompt."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = dict(
                conn.execute(
                    "SELECT * FROM ref_message_types WHERE slug = ?",
                    ('hyde_generation',),
                ).fetchone()
            )
        self.assertEqual(row['step_name'], 'HyDE Generation')
        self.assertEqual(row['creator_type'], 'programmatic')
        self.assertEqual(row['model_slug'], migration.MODEL_HYDE_GENERATION)
        self.assertEqual(row['temperature'], 0.7)
        self.assertEqual(row['max_retries'], 3)
        self.assertEqual(row['is_active'], 1)
        self.assertEqual(row['additional_model_settings'], '{"max_tokens": 800}')
        self.assertIsNotNone(row['prompt_template'])
        self.assertIn('{query}', row['prompt_template'])
        self.assertIsNotNone(row['request_schema'])
        self.assertIn('HydeGenerationResponse', row['request_schema'])

    def test_second_run_idempotent(self):
        """A second migration run must leave rows and counts unchanged."""
        migration.migrate(self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            rows_after_second = conn.execute(
                "SELECT * FROM ref_message_types ORDER BY slug"
            ).fetchall()
            message_count_after = conn.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0]
        self.assertEqual(rows_after_second, self.rows_after_first)
        self.assertEqual(message_count_after, self.message_count)

    def test_fk_insert_bogus_slug_raises(self):
        """ChatDatabase (PRAGMA foreign_keys = ON) must reject unknown slugs."""
        db = ChatDatabase(self.db_path)
        try:
            session_uuid = db.create_session(name='fk-fixture')
            with self.assertRaises(sqlite3.IntegrityError):
                db.create_message_with_type(
                    session_uuid=session_uuid,
                    message_type_slug='bogus_slug',
                    unique_prompt='should never land',
                )
        finally:
            db.close()

    def test_insert_human_input_succeeds(self):
        """A message with the newly seeded human_input slug must insert."""
        db = ChatDatabase(self.db_path)
        try:
            session_uuid = db.create_session(name='fk-fixture')
            message_uuid = db.create_message_with_type(
                session_uuid=session_uuid,
                message_type_slug='human_input',
                unique_prompt='why do bad things happen',
            )
            row = db.get_message_by_uuid(message_uuid)
            self.assertIsNotNone(row)
            self.assertEqual(row['message_type_slug'], 'human_input')
        finally:
            db.close()


def run_tests():
    """Run all tests."""
    print("Testing pipeline message-type migration (on a temp COPY)...")
    print("=" * 50)

    suite = unittest.TestSuite()
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(
            TestPipelineMessageTypeMigration
        )
    )

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
