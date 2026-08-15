#!/usr/bin/env python3
"""Unit tests for scripts/build_lexicon_index.py:normalize_strongs.

Covers Greek (no letter suffix), Hebrew with letter suffix (Macula Hebrew scheme),
and defensive pass-through for malformed inputs. Validates the cross-testament
integer-key normalization that joins macula_tokens to lexicon_definitions.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from build_lexicon_index import normalize_strongs  # noqa: E402


# --- Greek (bare-int, no letter suffix; legacy behaviour) ---

def test_greek_no_prefix():
    assert normalize_strongs('976') == '976'


def test_greek_uppercase_prefix():
    assert normalize_strongs('G0976') == '976'


def test_greek_lowercase_prefix():
    assert normalize_strongs('g0976') == '976'


def test_greek_no_leading_zeros():
    assert normalize_strongs('G976') == '976'


# --- Hebrew (may carry letter suffix; new OT behaviour) ---

def test_hebrew_uppercase_prefix_no_suffix():
    assert normalize_strongs('H2424') == '2424'


def test_hebrew_lowercase_prefix_no_suffix():
    assert normalize_strongs('h2424') == '2424'


def test_hebrew_uppercase_letter_suffix():
    """Macle Hebrew scheme: H871a / H047G-style codes."""
    assert normalize_strongs('H0047G') == '47g'


def test_hebrew_lowercase_letter_suffix():
    assert normalize_strongs('h0047g') == '47g'


def test_hebrew_bare_letter_suffix():
    """Macula Hebrew TSV strongnumberx may be a bare '0871a' with leading zeros."""
    assert normalize_strongs('0871a') == '871a'


def test_hebrew_bare_no_letter_suffix():
    assert normalize_strongs('7225') == '7225'


def test_hebrew_bare_no_leading_zero_with_suffix():
    assert normalize_strongs('1886a') == '1886a'


# --- Defensive / no-match ---

def test_empty_string_passes_through():
    assert normalize_strongs('') == ''


def test_none_passes_through():
    assert normalize_strongs(None) == ''


def test_malformed_passes_through():
    """Surfaces unexpected TSV drift in validation rather than silently
    corrupting the join key space."""
    assert normalize_strongs('abc') == 'abc'


def test_garbage_with_letters_only_passes_through():
    assert normalize_strongs('GHGH') == 'GHGH'


def test_suffix_letter_is_lowercased():
    """Both Macula-H (lowercase 'a') and TBESH (uppercase 'G') collapse to
    a single canonical form so join keys match."""
    assert normalize_strongs('H047G') == normalize_strongs('h047g') == '47g'


# --- Cross-testament collision safety ---

def test_greek_and_hebrew_one_normalizes_same():
    """Important constraint for the data model: a Greek G1 and Hebrew H1
    both normalize to the bare '1' string. The service layer is responsible
    for routing by testament/lexicon_source, NOT the normalize function."""
    assert normalize_strongs('G1') == '1'
    assert normalize_strongs('H1') == '1'
    assert normalize_strongs('G1') == normalize_strongs('H1')


if __name__ == '__main__':
    print("Running normalize_strongs tests...")
    tests = [
        ('test_greek_no_prefix', test_greek_no_prefix),
        ('test_greek_uppercase_prefix', test_greek_uppercase_prefix),
        ('test_greek_lowercase_prefix', test_greek_lowercase_prefix),
        ('test_greek_no_leading_zeros', test_greek_no_leading_zeros),
        ('test_hebrew_uppercase_prefix_no_suffix', test_hebrew_uppercase_prefix_no_suffix),
        ('test_hebrew_lowercase_prefix_no_suffix', test_hebrew_lowercase_prefix_no_suffix),
        ('test_hebrew_uppercase_letter_suffix', test_hebrew_uppercase_letter_suffix),
        ('test_hebrew_lowercase_letter_suffix', test_hebrew_lowercase_letter_suffix),
        ('test_hebrew_bare_letter_suffix', test_hebrew_bare_letter_suffix),
        ('test_hebrew_bare_no_letter_suffix', test_hebrew_bare_no_letter_suffix),
        ('test_hebrew_bare_no_leading_zero_with_suffix', test_hebrew_bare_no_leading_zero_with_suffix),
        ('test_empty_string_passes_through', test_empty_string_passes_through),
        ('test_none_passes_through', test_none_passes_through),
        ('test_malformed_passes_through', test_malformed_passes_through),
        ('test_garbage_with_letters_only_passes_through', test_garbage_with_letters_only_passes_through),
        ('test_suffix_letter_is_lowercased', test_suffix_letter_is_lowercased),
        ('test_greek_and_hebrew_one_normalizes_same', test_greek_and_hebrew_one_normalizes_same),
    ]
    for name, fn in tests:
        fn()
        print(f"✓ {name}")
    print("\nAll tests passed!")