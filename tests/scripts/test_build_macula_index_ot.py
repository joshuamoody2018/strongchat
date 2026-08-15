#!/usr/bin/env python3
"""Unit tests for the OT (Hebrew) ingest path of scripts/build_macula_index.py.

Covers:
- BOOK_NUM_TO_OSIS_OT mapping (1..39 -> OSIS OT short codes)
- parse_xml_id_hebrew for the Macula-Hebrew xml:id format (prefix 'o',
  2-digit book, 3-digit chapter, 3-digit verse, 4-digit word slot;
  total 13 chars including 'o').
- get_book_osis_hebrew round-trips.

No real Macula Hebrew TSV required; pure unit-level coverage.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from build_macula_index import (  # noqa: E402
    BOOK_NUM_TO_OSIS_OT,
    parse_xml_id_hebrew,
    get_book_osis_hebrew,
)


# --- Hebrew OT book-number mapping ---

def test_ot_mapping_covers_39_books():
    assert len(BOOK_NUM_TO_OSIS_OT) == 39
    assert set(BOOK_NUM_TO_OSIS_OT.keys()) == set(range(1, 40))


def test_ot_mapping_first_book():
    assert BOOK_NUM_TO_OSIS_OT[1] == 'Gen'


def test_ot_mapping_last_book():
    assert BOOK_NUM_TO_OSIS_OT[39] == 'Mal'


def test_ot_mapping_sample_books():
    assert BOOK_NUM_TO_OSIS_OT[19] == 'Ps'         # Psalm (KJV numbering)
    assert BOOK_NUM_TO_OSIS_OT[23] == 'Isa'
    assert BOOK_NUM_TO_OSIS_OT[1] == 'Gen'
    assert BOOK_NUM_TO_OSIS_OT[9] == '1Sam'
    assert BOOK_NUM_TO_OSIS_OT[11] == '1Kgs'
    assert BOOK_NUM_TO_OSIS_OT[13] == '1Chr'


def test_ot_books_do_not_overlap_with_nt():
    """Hebrew and Greek book numbers live in disjoint ranges."""
    from build_macula_index import BOOK_NUM_TO_OSIS_NT
    assert set(BOOK_NUM_TO_OSIS_OT.keys()).isdisjoint(
        set(BOOK_NUM_TO_OSIS_NT.keys())
    )


def test_ot_books_do_not_duplicate_osis():
    """Hebrew and Greek OSIS codes must not collide."""
    from build_macula_index import BOOK_NUM_TO_OSIS_NT
    ot_osis = set(BOOK_NUM_TO_OSIS_OT.values())
    nt_osis = set(BOOK_NUM_TO_OSIS_NT.values())
    assert ot_osis.isdisjoint(nt_osis), (
        f"OT and NT OSIS codes overlap: {ot_osis & nt_osis}"
    )


# --- parse_xml_id_hebrew ---

def test_parse_xml_id_hebrew_genesis_1_1_word_1():
    # xml:id 'o' + 2 book + 3 chapter + 3 verse + 4 word_slot = 13 chars
    book, ch, vs, wp = parse_xml_id_hebrew('o010010010011')
    assert book == 1
    assert ch == 1
    assert vs == 1
    assert wp == 11   # The 4-digit slot '0011' = 11 per Macula scheme


def test_parse_xml_id_hebrew_genesis_1_2():
    book, ch, vs, wp = parse_xml_id_hebrew('o010010020011')
    assert book == 1
    assert ch == 1
    assert vs == 2
    assert wp == 11


def test_parse_xml_id_hebrew_psalm_119_176():
    # Psalm 119 is the longest chapter in the Bible — confirm 3-digit chapter
    # round-trips without field overflow. xml:id format: 'o' + 2 book (19)
    # + 3 chapter (119) + 3 verse (176) + 4 word_slot (0021) = 13 chars.
    book, ch, vs, wp = parse_xml_id_hebrew('o191191760021')
    assert book == 19
    assert ch == 119
    assert vs == 176
    assert wp == 21


def test_parse_xml_id_hebrew_jonah_1_1():
    book, ch, vs, wp = parse_xml_id_hebrew('o320010010011')
    assert book == 32
    assert ch == 1
    assert vs == 1
    assert wp == 11


def test_parse_xml_id_hebrew_rejects_greek_prefix():
    with pytest.raises(ValueError):
        parse_xml_id_hebrew('n40001001001')


def test_parse_xml_id_hebrew_rejects_wrong_length():
    with pytest.raises(ValueError):
        parse_xml_id_hebrew('o01001001001')   # 12 chars — missing one digit


def test_parse_xml_id_hebrew_rejects_empty():
    with pytest.raises(ValueError):
        parse_xml_id_hebrew('')


# --- get_book_osis_hebrew ---

def test_get_book_osis_hebrew_all_numbers():
    """All keys in BOOK_NUM_TO_OSIS_OT resolve via the helper."""
    for book_num in range(1, 40):
        assert get_book_osis_hebrew(book_num) == BOOK_NUM_TO_OSIS_OT[book_num]


def test_get_book_osis_hebrew_out_of_range():
    with pytest.raises(ValueError):
        get_book_osis_hebrew(40)
    with pytest.raises(ValueError):
        get_book_osis_hebrew(0)
    with pytest.raises(ValueError):
        get_book_osis_hebrew(99)


if __name__ == '__main__':
    print("Running OT ingest unit tests...")
    sys.exit(pytest.main([__file__, '-v']))