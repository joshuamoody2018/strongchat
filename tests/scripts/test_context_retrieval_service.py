"""Offline test for ContextRetrievalService.

Uses the live read-only Macula index at ``data/macula_index.db``. There is
no application DB; the message-type configuration now comes from the
in-process registry, and the context_retrieval audit trail is the JSONL
log rather than a DB row.
"""

import asyncio
import json
import logging
import os
import sys
import unittest
import uuid

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

os.environ.setdefault('OPENROUTER_API_KEY', 'dummy_key_for_offline_tests')

from services.context.service import ContextRetrievalService
from services.pipeline.runner import PipelineResult, IntentTrace


class TestContextRetrievalService(unittest.TestCase):
    """Test suite for ContextRetrievalService against the live Macula index."""

    def setUp(self):
        """Set up test fixtures."""
        self.macula_db_path = 'data/macula_index.db'
        if not os.path.exists(self.macula_db_path):
            self.skipTest(f"macula_index.db not found at {self.macula_db_path}")

        self.service = ContextRetrievalService(macula_db_path=self.macula_db_path)
        self.session_uuid = f'corr-{uuid.uuid4()}'

    def tearDown(self):
        self.service.close()

    def _create_pipeline_result_with_john_3_16(self):
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
        return PipelineResult(
            session_uuid=self.session_uuid,
            query='test query',
            traces={'test-intent': trace},
        )

    def test_retrieve_for_pipeline_attaches_context_bundles(self):
        """Context bundles are attached to all hits, with the full contract."""
        result = self._create_pipeline_result_with_john_3_16()
        asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))

        for trace in result.traces.values():
            for translation, hits in trace.search_results.items():
                for hit in hits:
                    self.assertIn('context_bundle', hit)
                    bundle = hit['context_bundle']

                    self.assertIsInstance(bundle['unique_word_count'], int)
                    self.assertIsInstance(bundle['scored_word_count'], int)
                    self.assertIsInstance(bundle['kept_word_count'], int)
                    self.assertIsInstance(bundle['scored_words'], list)
                    self.assertIsInstance(bundle['kept_words'], list)
                    self.assertIsInstance(bundle['build_summary'], str)

                    self.assertGreaterEqual(bundle['kept_word_count'], 2)

                    kept_strongs = {w['strongs'] for w in bundle['kept_words'] if w['strongs']}
                    scored_strongs = {w['strongs'] for w in bundle['scored_words'] if w['strongs']}
                    self.assertTrue(kept_strongs.issubset(scored_strongs))

                    pos_tags = [w['pos'] for w in bundle['kept_words'] if w['pos']]
                    self.assertTrue(any(pos.startswith(('V-', 'N-')) for pos in pos_tags))

                    for w in bundle['kept_words']:
                        self.assertIsInstance(w['strongs'], str)
                        self.assertTrue(w['strongs'])
                        self.assertIsInstance(w['surface'], str)
                        self.assertTrue(w['surface'])
                        self.assertIsInstance(w['lemma'], str)
                        self.assertTrue(w['lemma'])
                        self.assertIsInstance(w['definitions'], list)
                        self.assertIsInstance(w['gloss'], str)
                        self.assertIsInstance(w['frequency_count'], int)
                        self.assertGreater(w['frequency_count'], 0)
                        self.assertIsInstance(w['sense_count'], int)
                        self.assertGreaterEqual(w['sense_count'], 1)
                        self.assertIsInstance(w['composite_score'], (int, float))
                        self.assertGreater(w['composite_score'], 0)
                        self.assertEqual(w['lexicon_source'], 'tbESG+LSJ')
                        self.assertIsInstance(w['macula_occurrences'], int)
                        self.assertGreaterEqual(w['macula_occurrences'], 1)
                        if w['definitions']:
                            self.assertEqual(w['sense_count'], len(w['definitions']))

                    has_defs = any(w['definitions'] for w in bundle['kept_words'])
                    self.assertTrue(
                        has_defs,
                        "no kept word has definitions — lexicon strongs key "
                        "normalization may have regressed (see "
                        "scripts/build_lexicon_index.py:normalize_strongs)")
                    has_gloss = any(w['gloss'] for w in bundle['kept_words'])
                    self.assertTrue(
                        has_gloss,
                        "no kept word has a gloss — macula_tokens.gloss ingest "
                        "may be broken (see scripts/build_macula_index.py)")

    def test_context_retrieval_log_recorded(self):
        """A context_retrieval INFO log record is emitted for the per-intent run."""
        result = self._create_pipeline_result_with_john_3_16()
        with self.assertLogs('strongchat', level='DEBUG') as cm:
            asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))

        ctx_records = [
            r for r in cm.records
            if r.levelno == logging.INFO
            and r.__dict__.get('event') == 'context_retrieval'
            and r.__dict__.get('status') == 'ok'
        ]
        self.assertEqual(len(ctx_records), 1)
        rec = ctx_records[0]
        self.assertEqual(rec.__dict__.get('intent_id'), 'test-intent')
        self.assertEqual(rec.__dict__.get('translation_count'), 2)
        self.assertEqual(rec.__dict__.get('hit_count'), 2)
        self.assertGreater(rec.__dict__.get('scored_word_count'), 0)
        self.assertGreater(rec.__dict__.get('kept_word_count'), 0)

        # DEBUG audit row carries the full bundles payload.
        debug_records = [
            r for r in cm.records if r.levelno == logging.DEBUG
        ]
        ctx_debug = [
            r for r in debug_records
            if r.__dict__.get('slug') == 'context_retrieval'
            and r.__dict__.get('raw_response') is not None
        ]
        self.assertEqual(len(ctx_debug), 1)
        raw_response = ctx_debug[0].__dict__.get('raw_response')
        parsed = json.loads(raw_response)
        self.assertEqual(parsed['intent_id'], 'test-intent')
        self.assertIsInstance(parsed['bundles'], list)
        self.assertEqual(len(parsed['bundles']), 2)
        for bundle in parsed['bundles']:
            self.assertIn('reference', bundle)
            self.assertIn('translation', bundle)
            self.assertIn('scored_words', bundle)
            self.assertIn('kept_words', bundle)
            if bundle['kept_words']:
                self.assertTrue(
                    any(w.get('definitions') for w in bundle['kept_words']),
                    "serialized bundle has no kept word with definitions")
                self.assertTrue(
                    any(w.get('gloss') for w in bundle['kept_words']),
                    "serialized bundle has no kept word with a gloss")

    def test_numbered_book_parsing(self):
        from services.context.service import _parse_reference
        self.assertEqual(_parse_reference('1 John 2:3'), ('1John', 2, 3))
        self.assertEqual(_parse_reference('2 Cor 5:17'), ('2Cor', 5, 17))
        self.assertEqual(_parse_reference('Matt 1:1'), ('Matt', 1, 1))
        self.assertEqual(_parse_reference('3 John 1:1'), ('3John', 1, 1))
        self.assertEqual(_parse_reference('1 Corinthians 13:4'), ('1Cor', 13, 4))
        self.assertIsNone(_parse_reference(''))
        self.assertIsNone(_parse_reference('John'))
        self.assertIsNone(_parse_reference('John 3'))
        self.assertIsNone(_parse_reference('Unknown 1:1'))
        self.assertIsNone(_parse_reference('1 Unknown 1:1'))

    def test_failure_path_no_macula_data(self):
        """An out-of-range chapter returns an empty bundle with reason."""
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
        asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))

        hit = trace.search_results['kjv'][0]
        self.assertIn('context_bundle', hit)
        bundle = hit['context_bundle']
        self.assertEqual(bundle['kept_word_count'], 0)
        self.assertEqual(bundle['unique_word_count'], 0)
        self.assertEqual(bundle['scored_word_count'], 0)
        self.assertIn('no macula tokens', bundle['build_summary'])

    def test_empty_search_results_no_log(self):
        """An intent with no search results emits no INFO audit record."""
        trace = IntentTrace(
            intent_id='test-intent',
            intent_data={'interpretation': 'test', 'confidence': 0.8},
            search_results={}
        )
        result = PipelineResult(
            session_uuid=self.session_uuid,
            query='test query',
            traces={'test-intent': trace}
        )

        # assertNoLogs (3.10+) asserts that NO records of the given level
        # fire during the context. With empty search_results, the context
        # stage emits no audit record.
        with self.assertNoLogs('strongchat', level='INFO'):
            asyncio.run(self.service.retrieve_for_pipeline(result, self.session_uuid))


if __name__ == '__main__':
    unittest.main(verbosity=2)