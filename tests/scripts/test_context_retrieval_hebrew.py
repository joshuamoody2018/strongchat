#!/usr/bin/env python3
"""Integration test for Hebrew (OT) context retrieval using a seeded fixture DB.

Builds a temp `macula_index.db` with macula_tokens / strongs_frequency /
lexicon_definitions rows for a single OT verse (Genesis 1:1), then runs
ContextRetrievalService.retrieve_for_pipeline and asserts the full bundle
shape against the documented contract.

The macula_index.db is a read-only data asset (NOT an application DB) seeded
locally here for the test. There is no application DB; audit assertions use
``self.assertLogs`` against the ``strongchat`` logger.
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

os.environ.setdefault('OPENROUTER_API_KEY', 'dummy_key_for_offline_hebrew_tests')

from services.context.service import ContextRetrievalService  # noqa: E402
from services.pipeline.runner import PipelineResult, IntentTrace  # noqa: E402


# --- SQLite fixture schema (subset of data/macula_index.db) ---

MACULA_DB_SCHEMA = """
CREATE TABLE macula_tokens (
    row_id TEXT PRIMARY KEY,
    book_num INTEGER NOT NULL,
    book_osis TEXT NOT NULL,
    chapter INTEGER NOT NULL,
    verse INTEGER NOT NULL,
    word_pos INTEGER NOT NULL,
    surface TEXT,
    lemma TEXT,
    strongs TEXT,
    morph TEXT,
    pos TEXT,
    gloss TEXT
);
CREATE INDEX idx_macula_ref ON macula_tokens(book_osis, chapter, verse);

CREATE TABLE strongs_frequency (
    strongs_number TEXT PRIMARY KEY,
    occurrence_count INTEGER NOT NULL,
    testament TEXT NOT NULL
);

CREATE TABLE lexicon_definitions (
    strongs_number TEXT NOT NULL,
    lexicon_source TEXT NOT NULL,
    sense_index INTEGER NOT NULL,
    definition TEXT NOT NULL,
    PRIMARY KEY (strongs_number, lexicon_source, sense_index)
);
CREATE INDEX idx_lex_strongs_source ON lexicon_definitions(strongs_number, lexicon_source);
"""

GEN_1_1_TOKENS = [
    ('o010010010011', 1, 'Gen', 1, 1, 11,  'בְּרֵאשִׁית', 'רֵאשִׁית',  '7225', 'R',  'noun', 'In the beginning'),
    ('o010010010021', 1, 'Gen', 1, 1, 21,  'בָּרָא',     'בָּרָא',     '1254', 'Vqvmp3sm', 'verb', 'created'),
    ('o010010010041', 1, 'Gen', 1, 1, 41,  'אֱלֹהִים',   'אֱלֹהִים',   '0430', 'Ncmpa',   'noun', 'God'),
    ('o010010010051', 1, 'Gen', 1, 1, 51,  'אֵת',         'אֵת',         '0853', 'Td',      'article', '(object marker)'),
    ('o010010010061', 1, 'Gen', 1, 1, 61,  'הַשָּׁמַיִם', 'שָׁמַיִם',   '8064', 'Ncmpa',   'noun', 'the heavens'),
    ('o010010010071', 1, 'Gen', 1, 1, 71,  'וְאֵת',       'אֵת',         '0853', 'Tdc',     'article', 'and (object marker)'),
    ('o010010010081', 1, 'Gen', 1, 1, 81,  'הָאָרֶץ',     'אֶרֶץ',       '0776', 'Ncbsa',   'noun', 'the earth'),
]

STRONGS_FREQUENCY_OT = [
    ('7225', 1,  'OT'),
    ('1254', 2,  'OT'),
    ('430',  10, 'OT'),
    ('853',  4,  'OT'),
    ('8064', 2,  'OT'),
    ('776',  8,  'OT'),
]

LEXICON_TBESH = [
    ('7225',  'tbESH', 1, 'first, beginning, choicest'),
    ('7225',  'tbESH', 2, 'first of its kind'),
    ('1254',  'tbESH', 1, 'create, shape, form'),
    ('1254',  'tbESH', 2, 'cut down'),
    ('1254',  'tbESH', 3, 'make fat'),
    ('430',   'tbESH', 1, 'god, God'),
    ('853',   'tbESH', 1, 'object marker'),
    ('8064',  'tbESH', 1, 'heaven, sky'),
    ('776',   'tbESH', 1, 'land, earth'),
    ('776',   'tbESH', 2, 'country, region'),
]

LEXICON_GREEK_CONTAMINANT = [
    ('430', 'tbESG', 1, 'ἄλφα — Greek letter alpha (sentinel: must NOT appear in Hebrew bundle)'),
]


class TestContextRetrievalHebrew(unittest.TestCase):
    """Test ContextRetrievalService against a seeded Hebrew-OT fixture DB."""

    def setUp(self):
        self._tmp_macula = tempfile.TemporaryDirectory()
        self.macula_db_path = os.path.join(self._tmp_macula.name, 'macula_hebrew_test.db')

        self._seed_macula_db()

        self.service = ContextRetrievalService(
            macula_db_path=self.macula_db_path,
        )
        self.session_uuid = f'hebrew-test-session-{uuid.uuid4()}'

    def tearDown(self):
        self.service.close()
        self._tmp_macula.cleanup()

    def _seed_macula_db(self):
        with sqlite3.connect(self.macula_db_path) as conn:
            conn.executescript(MACULA_DB_SCHEMA)
            conn.executemany(
                "INSERT INTO macula_tokens "
                "(row_id, book_num, book_osis, chapter, verse, word_pos, "
                " surface, lemma, strongs, morph, pos, gloss) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                GEN_1_1_TOKENS,
            )
            conn.executemany(
                "INSERT OR REPLACE INTO strongs_frequency "
                "(strongs_number, occurrence_count, testament) "
                "VALUES (?, ?, ?)",
                STRONGS_FREQUENCY_OT,
            )
            conn.executemany(
                "INSERT OR REPLACE INTO lexicon_definitions "
                "(strongs_number, lexicon_source, sense_index, definition) "
                "VALUES (?, ?, ?, ?)",
                LEXICON_TBESH + LEXICON_GREEK_CONTAMINANT,
            )

    def _make_pipeline_result(self, reference='Genesis 1:1'):
        trace = IntentTrace(
            intent_id='hebrew-test-intent',
            intent_data={'interpretation': 'OT support test', 'confidence': 0.8},
            search_results={
                'kjv': [{
                    'id': 'gen-1-1-kjv-1',
                    'text': 'In the beginning God created the heaven and the earth.',
                    'reference': reference,
                    'distance': 0.1,
                }],
                'web': [{
                    'id': 'gen-1-1-web-1',
                    'text': 'In the beginning God created the heavens and the earth.',
                    'reference': reference,
                    'distance': 0.2,
                }],
            },
        )
        return PipelineResult(
            session_uuid=self.session_uuid,
            query='genesis 1:1 creation',
            traces={'hebrew-test-intent': trace},
        )

    def test_hebrew_bundle_attaches_to_genesis_1_1_hit(self):
        """A Genesis 1:1 hit returns a NON-empty Hebrew context bundle."""
        result = asyncio.run(self._run())
        trace = result.traces['hebrew-test-intent']
        self.assertEqual(len(trace.search_results), 2)

        for translation, hits in trace.search_results.items():
            self.assertEqual(translation in {'kjv', 'web'}, True)
            for hit in hits:
                self.assertIn('context_bundle', hit)
                bundle = hit['context_bundle']
                self.assertGreater(bundle['unique_word_count'], 0)
                self.assertGreater(bundle['kept_word_count'], 0)
                self.assertGreater(bundle['scored_word_count'], 0)
                self.assertEqual(bundle['reference'], 'Genesis 1:1')
                self.assertEqual(bundle['translation'], translation)

                self.assertEqual(len(bundle['kept_words']), bundle['kept_word_count'])
                self.assertEqual(len(bundle['scored_words']), bundle['scored_word_count'])

                for w in bundle['kept_words']:
                    self.assertIsInstance(w['strongs'], str)
                    self.assertTrue(w['strongs'])
                    self.assertIsInstance(w['surface'], str)
                    self.assertTrue(w['surface'])
                    self.assertIsInstance(w['lemma'], str)
                    self.assertTrue(w['lemma'])
                    self.assertIsInstance(w['pos'], str)
                    self.assertIsInstance(w['morph'], str)
                    self.assertIsInstance(w['gloss'], str)
                    self.assertIsInstance(w['definitions'], list)
                    self.assertIsInstance(w['frequency_count'], int)
                    self.assertGreater(w['frequency_count'], 0)
                    self.assertIsInstance(w['sense_count'], int)
                    self.assertGreaterEqual(w['sense_count'], 1)
                    self.assertIsInstance(w['composite_score'], float)
                    self.assertGreater(w['composite_score'], 0.0)
                    self.assertIsInstance(w['pos_weight'], float)
                    self.assertIsInstance(w['macula_occurrences'], int)
                    self.assertGreaterEqual(w['macula_occurrences'], 1)
                    self.assertEqual(w['lexicon_source'], 'tbESH')

    def test_hebrew_bundle_does_not_contaminate_with_greek_lexicon(self):
        """The sentinel Greek tbESG row for bare int '430' must NOT bleed in."""
        result = asyncio.run(self._run())
        trace = result.traces['hebrew-test-intent']
        all_kept = []
        for hits in trace.search_results.values():
            for hit in hits:
                all_kept.extend(hit['context_bundle']['kept_words'])
        for w in all_kept:
            for defn in w['definitions']:
                self.assertNotIn('Greek letter alpha', defn)

    def test_hebrew_pos_weight_routes_through_table(self):
        """A Hebrew verb's pos_weight comes from POS_WEIGHTS_HEBREW (0.95)."""
        from config.context_constants import POS_WEIGHTS_HEBREW
        result = asyncio.run(self._run())
        trace = result.traces['hebrew-test-intent']
        for hits in trace.search_results.values():
            for hit in hits:
                verbs = [w for w in hit['context_bundle']['kept_words']
                         if w['pos'] == 'verb']
                if verbs:
                    for v in verbs:
                        self.assertEqual(v['pos_weight'], POS_WEIGHTS_HEBREW['verb'])
                    return
        self.fail("Expected at least one verb in Genesis 1:1 kept_words")

    def test_hebrew_log_recorded(self):
        """Exactly one INFO context_retrieval record is emitted per run."""
        with self.assertLogs('strongchat', level='DEBUG') as cm:
            asyncio.run(self._run())

        ctx_records = [
            r for r in cm.records
            if r.levelno == logging.INFO
            and r.__dict__.get('event') == 'context_retrieval'
            and r.__dict__.get('status') == 'ok'
        ]
        self.assertEqual(len(ctx_records), 1)
        rec = ctx_records[0]
        self.assertEqual(rec.__dict__.get('intent_id'), 'hebrew-test-intent')
        self.assertEqual(rec.__dict__.get('translation_count'), 2)
        self.assertEqual(rec.__dict__.get('hit_count'), 2)
        self.assertGreater(rec.__dict__.get('scored_word_count'), 0)
        self.assertGreater(rec.__dict__.get('kept_word_count'), 0)

        # DEBUG raw_response carries the full per-hit bundles payload.
        debug_records = [
            r for r in cm.records if r.levelno == logging.DEBUG
        ]
        ctx_debug = [
            r for r in debug_records
            if r.__dict__.get('slug') == 'context_retrieval'
            and r.__dict__.get('raw_response') is not None
        ]
        self.assertEqual(len(ctx_debug), 1)
        parsed = json.loads(ctx_debug[0].__dict__.get('raw_response'))
        self.assertEqual(parsed['intent_id'], 'hebrew-test-intent')
        self.assertEqual(len(parsed['bundles']), 2)

    async def _run(self):
        result = self._make_pipeline_result()
        return await self.service.retrieve_for_pipeline(
            result, self.session_uuid,
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)