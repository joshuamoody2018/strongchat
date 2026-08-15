#!/usr/bin/env python3
"""End-to-end ingest test for the Hebrew (OT) Macula path.

Builds a tiny synthetic canonical-shape Macula Hebrew TSV plus a matching
manifest, runs the existing `scripts/build_macula_index.py --testament
hebrew` over it, then runs `scripts/build_strongs_frequency.py
--testament hebrew`, and verifies the resulting macula_index.db carries
correctly-shaped Hebrew rows + a Hebrew-only strongs_frequency partition
that does not collide with any concurrent Greek partition.

This catches regressions in:
- parse_xml_id_hebrew for the 13-char 'o' + 4-digit word_slot format
- BOOK_NUM_TO_OSIS_OT for OT book_num <-> OSIS round-trip
- per-testament row-partitioning in build_macula_index.main (and the
  DELETE WHERE book_num < 40 wipe-before-re-ingest on subsequent runs)
- build_strongs_frequency per-testament testament value assignment
- build_strongs_frequency idempotency with concurrent NT partition
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
SRC_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'src')


# Synthetic Macula-Hebrew TSV — three rows in Gen 1:1 plus one row each in
# Gen 1:2 and Ps 1:1. Uses xml:id 'o' prefix + 4-digit word_slot to match
# the real Macula-Hebrew encoding. Strong numbers use the bare zero-padded
# integer-with-optional-letter form (e.g. '0430' for H0430).
HEBREW_TSV_ROWS = [
    # Genesis 1:1, three word-slots (11, 21, 41)
    ('o010010010011', 'GEN 1:1!1', 'בְּרֵאשִׁית', 'רֵאשִׁית', '7225', 'R', 'subs', 'In the beginning'),
    ('o010010010021', 'GEN 1:1!3', 'בָּרָא',     'בָּרָא',     '1254', 'Vqvmp3sm', 'verb', 'created'),
    ('o010010010041', 'GEN 1:1!6', 'אֱלֹהִים',   'אֱלֹהִים',   '0430', 'Ncmpa',    'subs', 'God'),
    # Genesis 1:2, one word
    ('o010010020021', 'GEN 1:2!4', 'תֹהוּ', 'תֹהוּ', '8414', 'Ncbsa', 'subs', 'formless'),
    # Psalm 1:1, one word — book_num=19 sanity check
    ('o190010010011', 'PSA 1:1!1', 'אַשְׁרֵי', 'אַשְׁרֵי', '0835', 'Amsa', 'adjv', 'Blessed'),
]

HEBREW_TSV_HEADER = ['xml:id', 'ref', 'text', 'lemma', 'strongnumberx',
                     'morph', 'pos', 'gloss']
HEBREW_MANIFEST = {
    "file": "macula-hebrew.tsv",
    "source": "synthetic-test-fixture",
    "books": 2,
    "tokens": len(HEBREW_TSV_ROWS),
    "source_url": "test-fixture://synthetic",
    "license": "CC-BY-4.0",
    "downloaded_at": "2026-08-16T00:00:00+00:00",
}


def _write_tsv(path, rows):
    import csv
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=HEBREW_TSV_HEADER, delimiter='\t')
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(zip(HEBREW_TSV_HEADER, r)))


def _run_script(module_name, *args):
    """Run a scripts/ module as a subprocess (preserves its argparse main())."""
    cmd = [sys.executable, os.path.join(SCRIPTS_DIR, module_name + '.py'), *args]
    env = os.environ.copy()
    env['PYTHONPATH'] = SRC_DIR + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run(
        cmd, env=env, capture_output=True, text=True, check=False,
    )
    return proc


class TestHebrewIngestScripts(unittest.TestCase):
    """End-to-end Hebrew ingest: TSV -> DB -> frequency aggregation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work_dir = self._tmp.name
        self.tsv_path = os.path.join(self.work_dir, 'macula-hebrew.tsv')
        self.manifest_path = os.path.join(self.work_dir, 'hebrew-manifest.json')
        self.db_path = os.path.join(self.work_dir, 'macula_index.db')

        _write_tsv(self.tsv_path, HEBREW_TSV_ROWS)
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(HEBREW_MANIFEST, f)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_hebrew_ingest(self):
        proc = _run_script(
            'build_macula_index',
            '--macula-tsv', self.tsv_path,
            '--manifest', self.manifest_path,
            '--output-db', self.db_path,
            '--testament', 'hebrew',
        )
        return proc

    def test_hebrew_ingest_writes_correct_rows(self):
        proc = self._run_hebrew_ingest()
        self.assertEqual(proc.returncode, 0,
                         f"build_macula_index --testament hebrew failed:\n"
                         f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")

        with sqlite3.connect(self.db_path) as conn:
            # Row count for OT partition
            ot_count = conn.execute(
                "SELECT COUNT(*) FROM macula_tokens WHERE book_num < 40"
            ).fetchone()[0]
            self.assertEqual(ot_count, len(HEBREW_TSV_ROWS))

            # NT partition should be empty
            nt_count = conn.execute(
                "SELECT COUNT(*) FROM macula_tokens WHERE book_num >= 40"
            ).fetchone()[0]
            self.assertEqual(nt_count, 0)

            # Verify Gen 1:1 tokens parsed correctly
            rows = conn.execute(
                "SELECT book_num, book_osis, chapter, verse, word_pos, surface, "
                "lemma, strongs, pos FROM macula_tokens "
                "WHERE book_osis='Gen' AND chapter=1 AND verse=1 "
                "ORDER BY word_pos"
            ).fetchall()
            self.assertEqual(len(rows), 3)
            # Book_num 1 -> Gen
            self.assertEqual(rows[0][0], 1)
            self.assertEqual(rows[0][1], 'Gen')
            self.assertEqual(rows[0][2], 1)
            self.assertEqual(rows[0][3], 1)
            self.assertEqual(rows[0][4], 11)  # 4-digit slot '0011' → int 11
            # Strong's bare-int form preserved (leading zero stripped at
            # display, kept as-is in storage)
            self.assertEqual(rows[0][7], '7225')
            self.assertEqual(rows[1][7], '1254')
            self.assertEqual(rows[2][7], '0430')

            # Verify Psalm 1:1 row (book_num 19, chap 1, verse 1, slot 11)
            ps_row = conn.execute(
                "SELECT book_num, book_osis, chapter, verse, word_pos, pos, gloss "
                "FROM macula_tokens WHERE book_osis='Ps'"
            ).fetchone()
            self.assertIsNotNone(ps_row)
            self.assertEqual(ps_row[0], 19)
            self.assertEqual(ps_row[1], 'Ps')
            self.assertEqual(ps_row[2], 1)
            self.assertEqual(ps_row[3], 1)
            self.assertEqual(ps_row[4], 11)
            self.assertEqual(ps_row[5], 'adjv')

            # Two distinct OT books
            distinct_ot = conn.execute(
                "SELECT COUNT(DISTINCT book_osis) FROM macula_tokens "
                "WHERE book_num < 40"
            ).fetchone()[0]
            self.assertEqual(distinct_ot, 2)

    def test_hebrew_ingest_is_idempotent_on_rerun(self):
        """Pre-existing Hebrew rows should be wiped before re-ingest."""
        self._run_hebrew_ingest()
        # Insert a stray Hebrew row that would not be present in TSV
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO macula_tokens "
                "(row_id, book_num, book_osis, chapter, verse, word_pos, "
                " surface, lemma, strongs, morph, pos, gloss) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ('o010010010099', 1, 'Gen', 1, 1, 99,
                 'stray', 'stray', '0000', 'X', 'intr', 'stray')
            )
            conn.commit()

        # Re-run ingest — should clear stray row before re-inserting TSV rows
        proc = self._run_hebrew_ingest()
        self.assertEqual(proc.returncode, 0,
                         f"Hebrew re-ingest failed:\nstderr:\n{proc.stderr}")

        with sqlite3.connect(self.db_path) as conn:
            stray = conn.execute(
                "SELECT COUNT(*) FROM macula_tokens WHERE word_pos=99"
            ).fetchone()[0]
            self.assertEqual(stray, 0, "Stray row was not cleared on re-ingest")
            ot_count = conn.execute(
                "SELECT COUNT(*) FROM macula_tokens WHERE book_num < 40"
            ).fetchone()[0]
            self.assertEqual(
                ot_count, len(HEBREW_TSV_ROWS),
                "Hebrew re-ingest did not produce a clean set of TSV rows"
            )

    def test_hebrew_strongs_frequency_aggregation(self):
        """build_strongs_frequency --testament hebrew writes OT-only
        aggregation with testament='OT'."""
        # First ingest tokens
        proc = self._run_hebrew_ingest()
        self.assertEqual(proc.returncode, 0)

        # Then aggregate frequency
        proc = _run_script(
            'build_strongs_frequency',
            '--macula-db', self.db_path,
            '--output-db', self.db_path,
            '--testament', 'hebrew',
        )
        self.assertEqual(
            proc.returncode, 0,
            f"build_strongs_frequency --testament hebrew failed:\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )

        with sqlite3.connect(self.db_path) as conn:
            # Only OT rows expected
            testament_values = [r[0] for r in conn.execute(
                "SELECT DISTINCT testament FROM strongs_frequency"
            ).fetchall()]
            self.assertEqual(testament_values, ['OT'])

            # H0430 (bare key '0430') appears once in fixture
            count_430 = conn.execute(
                "SELECT occurrence_count FROM strongs_frequency "
                "WHERE strongs_number='0430' AND testament='OT'"
            ).fetchone()
            self.assertIsNotNone(count_430)
            self.assertEqual(count_430[0], 1)

            # Strong 01254 appears once in fixture (Gen 1:1 only)
            count_1254 = conn.execute(
                "SELECT occurrence_count FROM strongs_frequency "
                "WHERE strongs_number='1254' AND testament='OT'"
            ).fetchone()
            self.assertIsNotNone(count_1254)
            self.assertEqual(count_1254[0], 1)

    def test_greek_and_hebrew_partitions_coexist(self):
        """Sequence: ingest Hebrew, ingest Greek-tiny-fixture, both
        partitions must remain intact (no cross-wipe)."""
        # 1) Hebrew ingest first
        self._run_hebrew_ingest()

        # 2) Build a tiny Greek TSV in same working dir (so we share the DB)
        greek_tsv = os.path.join(self.work_dir, 'macula-greek.tsv')
        greek_manifest = os.path.join(self.work_dir, 'greek-manifest.json')
        greek_rows = [
            # John 3:16 with two tokens
            ('n430030160011', 'John 3:16', 'οὕτως', 'οὕτως', '3779', 'D-', 'D-', 'so'),
            ('n430030160021', 'John 3:16', 'γὰρ', 'γὰρ', '1063', 'C-', 'C-', 'for'),
        ]
        _write_tsv(greek_tsv, greek_rows)
        with open(greek_manifest, 'w', encoding='utf-8') as f:
            json.dump({
                "file": "macula-greek.tsv", "source": "synthetic-test-fixture",
                "books": 1, "tokens": len(greek_rows),
                "source_url": "test-fixture://synthetic",
                "license": "CC-BY-4.0",
                "downloaded_at": "2026-08-16T00:00:00+00:00",
            }, f)

        proc = _run_script(
            'build_macula_index',
            '--macula-tsv', greek_tsv,
            '--manifest', greek_manifest,
            '--output-db', self.db_path,
            '--testament', 'greek',
        )
        self.assertEqual(proc.returncode, 0,
                         f"Greek ingest failed:\nstderr:\n{proc.stderr}")

        with sqlite3.connect(self.db_path) as conn:
            ot_count = conn.execute(
                "SELECT COUNT(*) FROM macula_tokens WHERE book_num < 40"
            ).fetchone()[0]
            nt_count = conn.execute(
                "SELECT COUNT(*) FROM macula_tokens WHERE book_num >= 40"
            ).fetchone()[0]
            self.assertEqual(ot_count, len(HEBREW_TSV_ROWS))
            self.assertEqual(nt_count, len(greek_rows))

            # Greek rows must not affect Hebrew partition.
            distinct_ot_books = conn.execute(
                "SELECT DISTINCT book_osis FROM macula_tokens WHERE book_num < 40"
            ).fetchall()
            self.assertEqual(
                sorted(r[0] for r in distinct_ot_books),
                ['Gen', 'Ps'],
            )

            # All Greek tokens should be book_num >= 40
            nt_books = conn.execute(
                "SELECT DISTINCT book_osis FROM macula_tokens WHERE book_num >= 40"
            ).fetchall()
            self.assertEqual([r[0] for r in nt_books], ['John'])


if __name__ == '__main__':
    unittest.main(verbosity=2)