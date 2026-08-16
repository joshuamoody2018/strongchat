#!/usr/bin/env python3
"""Integration test for Hebrew (OT) context retrieval using a seeded fixture DB.

Builds a temp `macula_index.db` with macula_tokens / strongs_frequency /
lexicon_definitions rows for a single OT verse (Genesis 1:1), then runs
ContextRetrievalService.retrieve_for_pipeline and asserts the full bundle
shape against the documented contract.

This test is the OT-equivalent of tests/scripts/test_context_retrieval_service.py.
It is fully offline — no real Macula Hebrew TSV, no ChromaDB, no OpenRouter
calls. The fixture is tiny (one verse × four tokens) so assertions are
deterministic.
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

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

# --- Chat-DB schema for messages FK (parallel to offline test) ---

CHAT_DB_SCHEMA = """
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
    temperature REAL DEFAULT 0.0,
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

# --- Fixture payload: Genesis 1:1 (four words from WLC) ---
# Strong's numbers are Macula-Hebrew style: bare int, zero-padded, sans H prefix.
# Gloss values are illustrative English (Macula Hebrew carries Cherith glosses).
#
# Surface forms use NFC-normalized Hebrew Unicode.
GEN_1_1_TOKENS = [
    # (row_id, book_num, book_osis, ch, vs, word_pos, surface, lemma, strongs, morph, pos, gloss)
    # pos values reflect the real Macula-Hebrew TSV `pos` column (full
    # English words: 'noun', 'verb', 'article', etc — see
    # scripts/build_macula_index.py docstring + config/context_constants.py
    # POS_WEIGHTS_HEBREW).
    ('o010010010011', 1, 'Gen', 1, 1, 11,  'בְּרֵאשִׁית', 'רֵאשִׁית',  '7225', 'R',  'noun', 'In the beginning'),
    ('o010010010021', 1, 'Gen', 1, 1, 21,  'בָּרָא',     'בָּרָא',     '1254', 'Vqvmp3sm', 'verb', 'created'),
    ('o010010010041', 1, 'Gen', 1, 1, 41,  'אֱלֹהִים',   'אֱלֹהִים',   '0430', 'Ncmpa',   'noun', 'God'),
    ('o010010010051', 1, 'Gen', 1, 1, 51,  'אֵת',         'אֵת',         '0853', 'Td',      'article', '(object marker)'),
    ('o010010010061', 1, 'Gen', 1, 1, 61,  'הַשָּׁמַיִם', 'שָׁמַיִם',   '8064', 'Ncmpa',   'noun', 'the heavens'),
    ('o010010010071', 1, 'Gen', 1, 1, 71,  'וְאֵת',       'אֵת',         '0853', 'Tdc',     'article', 'and (object marker)'),
    ('o010010010081', 1, 'Gen', 1, 1, 81,  'הָאָרֶץ',     'אֶרֶץ',       '0776', 'Ncbsa',   'noun', 'the earth'),
]

# Strong's frequency (Hebrew OT testament). Keys tie to macula_tokens strongs.
STRONGS_FREQUENCY_OT = [
    ('7225', 1,  'OT'),   # word_unique — appears once in our tiny fixture
    ('1254', 2,  'OT'),   # verb 'create' — appears twice in corpus (illustrative)
    ('430',  10, 'OT'),   # God — extremely common (illustrative; macula stores '0430')
    ('853',  4,  'OT'),
    ('8064', 2,  'OT'),
    ('776',  8,  'OT'),
]

# TBESH-style lexicon definitions. Multiple senses for two lemmas to
# exercise sense_count being > 1.
LEXICON_TBESH = [
    # (strongs_number, lexicon_source, sense_index, definition)
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

# Defensive: include a Greek tbESG row sharing the bare-int key '430' to
# validate that the Hebrew-only filter (lexicon_source='tbESH') does not
# conflate Greek and Hebrew lexicon entries.
LEXICON_GREEK_CONTAMINANT = [
    ('430', 'tbESG', 1, 'ἄλφα — Greek letter alpha (sentinel: must NOT appear in Hebrew bundle)'),
]


class TestContextRetrievalHebrew(unittest.TestCase):
    """Test ContextRetrievalService against a seeded Hebrew-OT fixture DB."""

    def setUp(self):
        self._tmp_macula = tempfile.TemporaryDirectory()
        self._tmp_chat = tempfile.TemporaryDirectory()
        self.macula_db_path = os.path.join(self._tmp_macula.name, 'macula_hebrew_test.db')
        self.chat_db_path = os.path.join(self._tmp_chat.name, 'chat_test.db')

        self._seed_macula_db()
        self._seed_chat_db()

        os.environ['OPENROUTER_API_KEY'] = 'dummy_key_for_offline_hebrew_tests'
        self.service = ContextRetrievalService(
            db_path=self.chat_db_path,
            macula_db_path=self.macula_db_path,
        )
        self.session_uuid = f'hebrew-test-session-{uuid.uuid4()}'
        self._create_session()

    def tearDown(self):
        self.service.close()
        self._tmp_macula.cleanup()
        self._tmp_chat.cleanup()

    # --- fixture seeding ---

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

    def _seed_chat_db(self):
        with sqlite3.connect(self.chat_db_path) as conn:
            conn.executescript(CHAT_DB_SCHEMA)
            conn.execute(
                """INSERT INTO ref_message_types
                   (slug, step_name, creator_type, request_schema, model_slug,
                    temperature, additional_model_settings, max_retries,
                    is_active, description, prompt_template)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ('context_retrieval', 'Context Retrieval', 'programmatic',
                 '{}', 'n/a', 0.0, None, 1, 1, 'Hebrew OT integration test',
                 None),
            )

    def _create_session(self):
        with sqlite3.connect(self.chat_db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (uuid, name, created_by) VALUES (?, ?, ?)",
                (self.session_uuid, 'hebrew-test', 'test'),
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

    # --- helpers ---

    def _get_context_retrieval_messages(self):
        with sqlite3.connect(self.chat_db_path) as conn:
            return conn.execute(
                "SELECT unique_prompt, raw_response, error_text FROM messages "
                "WHERE message_type_slug='context_retrieval'"
            ).fetchall()

    # --- the test ---

    def test_hebrew_bundle_attaches_to_genesis_1_1_hit(self):
        """A Genesis 1:1 hit returns a NON-empty context bundle, proving the
        Hebrew path resolves Macula tokens, frequency, and TBESH senses."""
        result = asyncio.run(self._run())
        trace = result.traces['hebrew-test-intent']
        self.assertEqual(len(trace.search_results), 2)

        for translation, hits in trace.search_results.items():
            self.assertEqual(translation in {'kjv', 'web'}, True)
            for hit in hits:
                self.assertIn('context_bundle', hit,
                              "Hebrew hit must carry a context_bundle")
                bundle = hit['context_bundle']
                self.assertGreater(bundle['unique_word_count'], 0,
                                    "Genesis 1:1 should have unique words")
                self.assertGreater(bundle['kept_word_count'], 0,
                                    "Hebrew bundle must keep at least one word")
                self.assertGreater(bundle['scored_word_count'], 0)
                self.assertEqual(bundle['reference'], 'Genesis 1:1')
                self.assertEqual(bundle['translation'], translation)

                self.assertEqual(len(bundle['kept_words']),
                                 bundle['kept_word_count'])
                self.assertEqual(len(bundle['scored_words']),
                                 bundle['scored_word_count'])

                for w in bundle['kept_words']:
                    # Schema-shape checks parallel to Greek path
                    self.assertIsInstance(w['strongs'], str)
                    self.assertTrue(w['strongs'], "Hebrew kept word strongs is empty")
                    self.assertIsInstance(w['surface'], str)
                    self.assertTrue(w['surface'], "Hebrew surface must be non-empty")
                    self.assertIsInstance(w['lemma'], str)
                    self.assertTrue(w['lemma'], "Hebrew lemma must be non-empty")
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

                    # Hebrew-specific contract
                    self.assertEqual(
                        w['lexicon_source'], 'tbESH',
                        f"Hebrew kept word lexicon_source must be 'tbESH'; "
                        f"got {w['lexicon_source']!r} for strongs={w['strongs']!r}"
                    )

    def test_hebrew_bundle_does_not_contaminate_with_greek_lexicon(self):
        """The sentinel Greek tbESG row for bare int '430' must NOT bleed into
        the Hebrew bundle's definitions list (validates lexicon_source filter)."""
        result = asyncio.run(self._run())
        trace = result.traces['hebrew-test-intent']
        all_kept = []
        for hits in trace.search_results.values():
            for hit in hits:
                all_kept.extend(hit['context_bundle']['kept_words'])
        for w in all_kept:
            for defn in w['definitions']:
                self.assertNotIn('Greek letter alpha', defn,
                                 f"Greek-contaminant definition leaked into "
                                 f"Hebrew bundle for strongs={w['strongs']!r}")

    def test_hebrew_pos_weight_routes_through_table(self):
        """A Hebrew verb's pos_weight must come from POS_WEIGHTS_HEBREW
        (0.95), not the Greek default (0.50)."""
        from config.context_constants import POS_WEIGHTS_HEBREW
        result = asyncio.run(self._run())
        trace = result.traces['hebrew-test-intent']
        for hits in trace.search_results.values():
            for hit in hits:
                verbs = [w for w in hit['context_bundle']['kept_words']
                         if w['pos'] == 'verb']
                if verbs:
                    for v in verbs:
                        self.assertEqual(v['pos_weight'],
                                         POS_WEIGHTS_HEBREW['verb'])
                    return
        self.fail("Expected at least one verb in Genesis 1:1 kept_words, "
                   "got none")

    def test_hebrew_message_recorded(self):
        """Exactly one context_retrieval row is recorded per intent with hits,
        with the OT-flavored summary payload and no error_text."""
        asyncio.run(self._run())
        rows = self._get_context_retrieval_messages()
        self.assertEqual(len(rows), 1)
        unique_prompt, raw_response, error_text = rows[0]
        self.assertIsNone(error_text)
        summary = json.loads(unique_prompt)
        self.assertEqual(summary['intent_id'], 'hebrew-test-intent')
        self.assertEqual(summary['translation_count'], 2)
        self.assertEqual(summary['hit_count'], 2)
        self.assertGreater(summary['scored_word_count'], 0)
        self.assertGreater(summary['kept_word_count'], 0)
        payload = json.loads(raw_response)
        self.assertEqual(payload['intent_id'], 'hebrew-test-intent')
        self.assertEqual(len(payload['bundles']), 2)

    async def _run(self):
        result = self._make_pipeline_result()
        return await self.service.retrieve_for_pipeline(
            result, self.session_uuid,
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)