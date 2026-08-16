"""Offline test for ContextRetrievalService.

Uses the main database (data/chat_database.db), seeding it via
scripts/create_new_database.py only if it is missing or lacks the
context_retrieval message type. Test sessions and messages are left in the
database (not a production instance).
"""

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
import sys
import uuid

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from services.context.service import ContextRetrievalService
from services.pipeline.runner import PipelineResult, IntentTrace
import create_new_database


class TestContextRetrievalService(unittest.TestCase):
    """Test suite for ContextRetrievalService."""

    def setUp(self):
        """Set up test fixtures."""
        self.chat_db_path = 'data/chat_database.db'
        self.macula_db_path = 'data/macula_index.db'

        # Ensure the main database exists and carries the context_retrieval type
        if not self._message_type_exists('context_retrieval'):
            create_new_database.create_new_database(self.chat_db_path)

        os.environ['OPENROUTER_API_KEY'] = 'dummy_key_for_offline_tests'

        # Create service with the main database
        self.service = ContextRetrievalService(
            db_path=self.chat_db_path,
            macula_db_path=self.macula_db_path
        )

        # Create test session
        self.session_uuid = self._create_test_session()

    def tearDown(self):
        """Close the service. Test rows are intentionally left in the database."""
        self.service.close()

    def _message_type_exists(self, slug):
        """Return True if the database is present and has the message type."""
        if not os.path.exists(self.chat_db_path):
            return False
        with sqlite3.connect(self.chat_db_path) as conn:
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ref_message_types'"
            ).fetchone()
            if not table:
                return False
            row = conn.execute(
                "SELECT 1 FROM ref_message_types WHERE slug = ?", (slug,)
            ).fetchone()
            return row is not None

    def _create_test_session(self):
        """Create a test session and return its UUID."""
        self.session_uuid = f'test-session-{uuid.uuid4()}'
        with sqlite3.connect(self.chat_db_path) as conn:
            conn.execute(
                'INSERT INTO sessions (uuid, name, created_by) VALUES (?, ?, ?)',
                (self.session_uuid, 'test session', 'test')
            )
            conn.commit()
        return self.session_uuid

    def _create_pipeline_result_with_john_3_16(self):
        """Create a PipelineResult with John 3:16 hits for testing."""
        # Create intent trace with search results
        trace = IntentTrace(
            intent_id='test-intent',
            intent_data={'interpretation': 'test', 'confidence': 0.8},
            search_results={
                'kjv': [
                    {
                        'id': 'john-3-16-kjv-1',
                        'text': 'For God so loved the world...',
                        'reference': 'John 3:16',
                        'distance': 0.1
                    }
                ],
                'web': [
                    {
                        'id': 'john-3-16-web-1',
                        'text': 'For God loved the world so much...',
                        'reference': 'John 3:16',
                        'distance': 0.2
                    }
                ]
            }
        )
        
        # Create pipeline result
        result = PipelineResult(
            session_uuid=self.session_uuid,
            query='test query',
            traces={'test-intent': trace}
        )
        
        return result

    def test_retrieve_for_pipeline_attaches_context_bundles(self):
        """Test that context bundles are attached to all hits."""
        # Create test pipeline result
        result = self._create_pipeline_result_with_john_3_16()
        
        # Run the service
        asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))
        
        # Verify every hit has a context_bundle
        for trace in result.traces.values():
            for translation, hits in trace.search_results.items():
                for hit in hits:
                    self.assertIn('context_bundle', hit)
                    bundle = hit['context_bundle']
                    
                    # Assert bundle structure
                    self.assertIsInstance(bundle['unique_word_count'], int)
                    self.assertIsInstance(bundle['scored_word_count'], int)
                    self.assertIsInstance(bundle['kept_word_count'], int)
                    self.assertIsInstance(bundle['scored_words'], list)
                    self.assertIsInstance(bundle['kept_words'], list)
                    self.assertIsInstance(bundle['build_summary'], str)
                    
                    # Assert minimum kept words
                    self.assertGreaterEqual(bundle['kept_word_count'], 2)  # MIN_WORDS_AFTER_TRIM
                    
                    # Assert kept_words is subset of scored_words by strongs
                    kept_strongs = {w['strongs'] for w in bundle['kept_words'] if w['strongs']}
                    scored_strongs = {w['strongs'] for w in bundle['scored_words'] if w['strongs']}
                    self.assertTrue(kept_strongs.issubset(scored_strongs))
                    
                    # Assert at least one kept word has V- or N- POS
                    pos_tags = [w['pos'] for w in bundle['kept_words'] if w['pos']]
                    self.assertTrue(any(pos.startswith(('V-', 'N-')) for pos in pos_tags))

                    # Assert every kept word has expected fields with correct
                    # types and non-empty values where the contract demands it.
                    for w in bundle['kept_words']:
                        self.assertIsInstance(w['strongs'], str)
                        self.assertTrue(w['strongs'],
                                        "kept word strongs must be non-empty")
                        self.assertIsInstance(w['surface'], str)
                        self.assertTrue(w['surface'],
                                        "kept word surface must be non-empty")
                        self.assertIsInstance(w['lemma'], str)
                        self.assertTrue(w['lemma'],
                                        "kept word lemma must be non-empty")
                        self.assertIsInstance(w['definitions'], list)
                        self.assertIsInstance(w['gloss'], str)
                        self.assertIsInstance(w['frequency_count'], int)
                        self.assertGreater(w['frequency_count'], 0)
                        self.assertIsInstance(w['sense_count'], int)
                        self.assertGreaterEqual(w['sense_count'], 1)
                        self.assertIsInstance(
                            w['composite_score'], (int, float))
                        self.assertGreater(w['composite_score'], 0)
                        self.assertEqual(w['lexicon_source'], 'tbESG+LSJ')
                        self.assertIsInstance(w['macula_occurrences'], int)
                        self.assertGreaterEqual(w['macula_occurrences'], 1)
                        # sense_count must match len(definitions) when defs exist
                        if w['definitions']:
                            self.assertEqual(
                                w['sense_count'], len(w['definitions']))

                    # Regression canary for the strongs-key normalization bug
                    # (lexicon_definitions vs macula_tokens key format). If this
                    # fails, scripts/build_lexicon_index.py normalization has
                    # regressed and definitions silently come back empty.
                    has_defs = any(w['definitions'] for w in bundle['kept_words'])
                    self.assertTrue(
                        has_defs,
                        "no kept word has definitions — lexicon strongs key "
                        "normalization may have regressed (see "
                        "scripts/build_lexicon_index.py:normalize_strongs)")

                    # Regression canary for the macula gloss schema (todo 3 gap
                    # that was previously fixed). If this fails, the macula
                    # TSV ingest has stopped populating the gloss column.
                    has_gloss = any(w['gloss'] for w in bundle['kept_words'])
                    self.assertTrue(
                        has_gloss,
                        "no kept word has a gloss — macula_tokens.gloss ingest "
                        "may be broken (see scripts/build_macula_index.py)")

    def test_context_retrieval_message_recorded(self):
        """Test that context_retrieval message is recorded in database."""
        # Create test pipeline result
        result = self._create_pipeline_result_with_john_3_16()

        # Run the service
        asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))

        # Check that context_retrieval message was recorded
        conn = sqlite3.connect(self.chat_db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM messages WHERE session_uuid = ? AND message_type_slug = "context_retrieval"',
            (self.session_uuid,)
        )
        messages = cursor.fetchall()
        conn.close()

        # Should have exactly one context_retrieval message for this run
        self.assertEqual(len(messages), 1)

        # Column order: uuid=0, session_uuid=1, message_type_slug=2,
        # unique_prompt=3, raw_response=4, created_at=5, response_at=6,
        # num_tries=7, error_text=8.
        message = messages[0]
        unique_prompt = message[3]
        raw_response = message[4]
        error_text = message[8]

        # unique_prompt keeps the cheap summary shape
        parsed_prompt = json.loads(unique_prompt) if unique_prompt else {}
        self.assertEqual(parsed_prompt['intent_id'], 'test-intent')
        self.assertEqual(parsed_prompt['translation_count'], 2)
        self.assertEqual(parsed_prompt['hit_count'], 2)
        self.assertGreater(parsed_prompt['scored_word_count'], 0)
        self.assertGreater(parsed_prompt['kept_word_count'], 0)
        self.assertIsNone(error_text)

        # raw_response now carries the full per-hit bundles for replay
        self.assertIsNotNone(raw_response)
        parsed_response = json.loads(raw_response)
        self.assertEqual(parsed_response['intent_id'], 'test-intent')
        self.assertIsInstance(parsed_response['bundles'], list)
        self.assertEqual(len(parsed_response['bundles']), parsed_prompt['hit_count'])
        for bundle in parsed_response['bundles']:
            self.assertIn('reference', bundle)
            self.assertIn('translation', bundle)
            self.assertIn('scored_words', bundle)
            self.assertIn('kept_words', bundle)

            # Round-trip regression canary: serialized kept_words must carry
            # non-empty definitions and glosses after the strongs-key
            # normalization fix.
            if bundle['kept_words']:
                self.assertTrue(
                    any(w.get('definitions') for w in bundle['kept_words']),
                    "serialized bundle has no kept word with definitions")
                self.assertTrue(
                    any(w.get('gloss') for w in bundle['kept_words']),
                    "serialized bundle has no kept word with a gloss")

    def test_numbered_book_parsing(self):
        """Test numbered book reference parsing."""
        from services.context.service import _parse_reference
        
        # Test various numbered book formats
        self.assertEqual(_parse_reference('1 John 2:3'), ('1John', 2, 3))
        self.assertEqual(_parse_reference('2 Cor 5:17'), ('2Cor', 5, 17))
        self.assertEqual(_parse_reference('Matt 1:1'), ('Matt', 1, 1))
        self.assertEqual(_parse_reference('3 John 1:1'), ('3John', 1, 1))
        self.assertEqual(_parse_reference('1 Corinthians 13:4'), ('1Cor', 13, 4))
        
        # Test edge cases
        self.assertIsNone(_parse_reference(''))
        self.assertIsNone(_parse_reference('John'))
        self.assertIsNone(_parse_reference('John 3'))
        self.assertIsNone(_parse_reference('Unknown 1:1'))
        self.assertIsNone(_parse_reference('1 Unknown 1:1'))

    def test_failure_path_no_macula_data(self):
        """Test handling of references that parse but have no Macula tokens.

        Originally this case used Genesis 1:1, assuming the OT corpus was
        not ingested. As of 2026-08-16 the OT (Hebrew WLC) is ingested
        alongside the NT, so a well-known Genesis reference now resolves
        to real tokens. To preserve the behaviour the test was written to
        assert (empty bundle + 'no macula tokens for …'), we point at an
        uncanonical verse (a chapter/verse outside any book's range).
        """
        # Use Gen 1:99999:1 — chapter is out of range; macula_tokens has no
        # rows with chapter=99999 so the service returns an empty bundle.
        uncanonical_ref = 'Genesis 99999:1'
        trace = IntentTrace(
            intent_id='test-intent',
            intent_data={'interpretation': 'test', 'confidence': 0.8},
            search_results={
                'kjv': [
                    {
                        'id': 'gen-99999-1-kjv-1',
                        'text': '(non-canonical reference)',
                        'reference': uncanonical_ref,
                        'distance': 0.1
                    }
                ]
            }
        )

        result = PipelineResult(
            session_uuid=self.session_uuid,
            query='test query',
            traces={'test-intent': trace}
        )

        # Run the service
        asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))

        # Verify bundle exists but is empty
        hit = trace.search_results['kjv'][0]
        self.assertIn('context_bundle', hit)
        bundle = hit['context_bundle']

        self.assertEqual(bundle['kept_word_count'], 0)
        self.assertEqual(bundle['unique_word_count'], 0)
        self.assertEqual(bundle['scored_word_count'], 0)
        self.assertIn('no macula tokens', bundle['build_summary'])


    def test_empty_search_results(self):
        """Test handling of intents with empty search_results."""
        # Create intent trace with no search results
        trace = IntentTrace(
            intent_id='test-intent',
            intent_data={'interpretation': 'test', 'confidence': 0.8},
            search_results={}  # Empty
        )
        
        result = PipelineResult(
            session_uuid=self.session_uuid,
            query='test query',
            traces={'test-intent': trace}
        )
        
        # Run the service - should not crash
        asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))
        
        # Verify no context_retrieval message was recorded (no work done)
        conn = sqlite3.connect(self.chat_db_path)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM messages WHERE session_uuid = ? AND message_type_slug = "context_retrieval"',
            (self.session_uuid,)
        )
        messages = cursor.fetchall()
        conn.close()
        self.assertEqual(len(messages), 0)


def main():
    """Run the test suite."""
    # Create evidence directory if it doesn't exist
    os.makedirs('.omo/evidence', exist_ok=True)
    
    # Run tests
    unittest.main(verbosity=2)


if __name__ == '__main__':
    main()