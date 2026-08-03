"""Offline test for ContextRetrievalService."""

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from services.context.service import ContextRetrievalService
from services.pipeline.runner import PipelineResult, IntentTrace


class TestContextRetrievalService(unittest.TestCase):
    """Test suite for ContextRetrievalService."""

    def setUp(self):
        """Set up test fixtures."""
        self.chat_db_path = 'data/test_chat_database.db'
        self.macula_db_path = 'data/macula_index.db'
        
        # Create a fresh test database
        self._create_fresh_test_db()
        
        os.environ['OPENROUTER_API_KEY'] = 'dummy_key_for_offline_tests'
        
        # Create service with test database
        self.service = ContextRetrievalService(
            db_path=self.chat_db_path,
            macula_db_path=self.macula_db_path
        )
        
        # Create test session
        self.session_uuid = self._create_test_session()

    def tearDown(self):
        """Clean up test fixtures."""
        self.service.close()

    def _create_fresh_test_db(self):
        """Create a fresh test database with required schema."""
        if os.path.exists(self.chat_db_path):
            os.remove(self.chat_db_path)
        
        conn = sqlite3.connect(self.chat_db_path)
        cursor = conn.cursor()
        
        # Create sessions table
        cursor.execute('''
            CREATE TABLE sessions (
                uuid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create messages table
        cursor.execute('''
            CREATE TABLE messages (
                uuid TEXT PRIMARY KEY,
                session_uuid TEXT NOT NULL,
                message_type_slug TEXT NOT NULL,
                unique_prompt TEXT NOT NULL,
                raw_response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                response_at TIMESTAMP,
                num_tries INTEGER DEFAULT 1,
                error_text TEXT,
                FOREIGN KEY (session_uuid) REFERENCES sessions (uuid),
                FOREIGN KEY (message_type_slug) REFERENCES ref_message_types (slug)
            )
        ''')
        
        # Create ref_message_types table
        cursor.execute('''
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
            )
        ''')
        
        # Insert context_retrieval message type
        context_retrieval_schema = {
            "type": "object", 
            "properties": {
                "intent_id": {"type": "string"},
                "translation_count": {"type": "integer"},
                "hit_count": {"type": "integer"},
                "scored_word_count": {"type": "integer"},
                "kept_word_count": {"type": "integer"}
            }, 
            "required": ["intent_id", "translation_count", "hit_count", "scored_word_count", "kept_word_count"]
        }
        
        cursor.execute('''
            INSERT INTO ref_message_types 
            (slug, step_name, creator_type, request_schema, model_slug, description)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            'context_retrieval',
            'Context Retrieval',
            'programmatic',
            json.dumps(context_retrieval_schema),
            'n/a',
            'Per-intent original-language context enrichment for retrieved verses'
        ))
        
        conn.commit()
        conn.close()

    def _create_test_session(self):
        """Create a test session and return its UUID."""
        conn = sqlite3.connect(self.chat_db_path)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO sessions (uuid, name, created_by) VALUES (?, ?, ?)',
            ('test-session-123', 'test session', 'test')
        )
        conn.commit()
        conn.close()
        return 'test-session-123'

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
            'SELECT * FROM messages WHERE message_type_slug = "context_retrieval"'
        )
        messages = cursor.fetchall()
        conn.close()

        # Should have exactly one context_retrieval message
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
        """Test handling of verses with no Macula data."""
        # Create a hit with a reference that has no Macula data (OT book)
        trace = IntentTrace(
            intent_id='test-intent',
            intent_data={'interpretation': 'test', 'confidence': 0.8},
            search_results={
                'kjv': [
                    {
                        'id': 'gen-1-1-kjv-1',
                        'text': 'In the beginning...',
                        'reference': 'Genesis 1:1',
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
            'SELECT * FROM messages WHERE message_type_slug = "context_retrieval"'
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