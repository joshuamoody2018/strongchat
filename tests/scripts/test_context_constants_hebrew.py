#!/usr/bin/env python3
"""Unit tests for Hebrew POS weight table in config/context_constants.py.

Mirrors tests/scripts/test_context_constants.py but for the OT path.
Validates the HAM (Hebrew Augmented Morphology) weight table, that
all weights fall in [0, 1.0], that get_pos_weight routes by language,
and that composite_score (invariant across languages) still holds.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config.context_constants import (  # noqa: E402
    POS_WEIGHTS_HEBREW,
    POS_WEIGHTS,  # greek
    composite_score,
    get_pos_weight,
)


# --- Hebrew POS categories ---

def test_hebrew_pos_weights_categories():
    """Test that high- and low-weight HAM categories are present.

    Asserts BOTH the actual Macula-Hebrew TSV `pos` full-word forms
    ('noun', 'verb', ...) AND defensive HAM trigram aliases ('subs',
    'nmpr', ...) so the table is robust to upstream schema variations.
    """
    # High-weight content words (Macula-Hebrew full-English-word forms)
    assert 'verb' in POS_WEIGHTS_HEBREW, "Hebrew verb category missing"
    assert 'noun' in POS_WEIGHTS_HEBREW, "Hebrew noun category missing"
    assert 'proper noun' in POS_WEIGHTS_HEBREW, "Hebrew proper-noun category missing"
    assert 'adjective' in POS_WEIGHTS_HEBREW, "Hebrew adjective category missing"

    # Low-weight function words (Macula-Hebrew full-English-word forms)
    assert 'article' in POS_WEIGHTS_HEBREW, "Hebrew article category missing"
    assert 'conjunction' in POS_WEIGHTS_HEBREW, "Hebrew conjunction category missing"
    assert 'preposition' in POS_WEIGHTS_HEBREW, "Hebrew preposition category missing"
    assert 'adverb' in POS_WEIGHTS_HEBREW, "Hebrew adverb category missing"
    assert 'pronoun' in POS_WEIGHTS_HEBREW, "Hebrew pronoun category missing"
    assert 'suffix' in POS_WEIGHTS_HEBREW, "Hebrew suffix category missing"

    # HAM trigram aliases (defensive — covers alternate upstream shape)
    assert 'subs' in POS_WEIGHTS_HEBREW, "HAM subs alias missing"
    assert 'nmpr' in POS_WEIGHTS_HEBREW, "HAM nmpr alias missing"
    assert 'artc' in POS_WEIGHTS_HEBREW, "HAM artc alias missing"
    assert 'conj' in POS_WEIGHTS_HEBREW, "HAM conj alias missing"
    assert 'prep' in POS_WEIGHTS_HEBREW, "HAM prep alias missing"


def test_hebrew_weights_bounded():
    """All Hebrew weights in [0.0, 1.0]."""
    for pos_code, weight in POS_WEIGHTS_HEBREW.items():
        assert 0.0 <= weight <= 1.0, (
            f"Hebrew weight for {pos_code} is {weight}, not in [0.0, 1.0]"
        )


def test_hebrew_weights_distinct_from_greek_keys():
    """Hebrew HAM codes are lowercase word-trigrams; Greek Robinson codes are
    two-letter-with-dash. The two keyspaces must not collide."""
    overlap = set(POS_WEIGHTS_HEBREW.keys()) & set(POS_WEIGHTS.keys())
    assert not overlap, (
        f"Hebrew and Greek POS weight keys must not overlap; collision: {overlap}"
    )


# --- get_pos_weight language routing ---

def test_get_pos_weight_greek_default():
    """Default language='greek' preserves existing Robinson lookup behaviour."""
    assert get_pos_weight('V-') == POS_WEIGHTS['V-']
    assert get_pos_weight('N-') == POS_WEIGHTS['N-']


def test_get_pos_weight_hebrew():
    """Explicit language='hebrew' routes to the HAM table."""
    assert get_pos_weight('verb', language='hebrew') == POS_WEIGHTS_HEBREW['verb']
    assert get_pos_weight('subs', language='hebrew') == POS_WEIGHTS_HEBREW['subs']


def test_get_pos_weight_unknown_hebrew():
    assert get_pos_weight('ZZZ', language='hebrew') == 0.50


def test_get_pos_weight_unknown_default_returns_default():
    assert get_pos_weight('ZZZ') == 0.50


def test_get_pos_weight_Greek_unknown_after_Greek_match_falls_through():
    """Sanity: a Hebrew code passed without language falls to Greek default 0.50
    (preserves the existing contract that an unknown POS yields 0.50)."""
    assert get_pos_weight('verb') == 0.50   # 'verb' is not a Greek Robinson code


# --- composite_score is language-agnostic (composite_score unchanged) ---

def test_hebrew_path_smoke_composite_score():
    pos_w = POS_WEIGHTS_HEBREW['verb']  # 0.95 per parity with Greek verbs
    score = composite_score(pos_w, 100, 3)
    assert score > 0.0


def test_hebrew_verb_dominates_particle():
    """Verb (0.95) dominates particle (low weight), paralleling Greek test_pos_dominance."""
    high = composite_score(POS_WEIGHTS_HEBREW['verb'], 100, 5)
    low = composite_score(POS_WEIGHTS_HEBREW['particle'], 100, 5)
    assert high > low


if __name__ == '__main__':
    print("Running Hebrew POS weight tests...")
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f"✓ {t.__name__}")
    print("\nAll Hebrew POS weight tests passed!")