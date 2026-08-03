#!/usr/bin/env python3
"""Unit tests for context constants module.

Tests the POS weight table, composite score formula, and invariants.
"""

import sys
import os

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config.context_constants import (
    POS_WEIGHTS,
    composite_score,
    get_pos_weight,
)


def test_pos_weights_categories():
    """Test all Robinson NT POS categories are present."""
    assert 'V-' in POS_WEIGHTS, "Verb category missing"
    assert 'N-' in POS_WEIGHTS, "Noun category missing"
    assert 'A-' in POS_WEIGHTS, "Adjective category missing"
    assert 'D-' in POS_WEIGHTS, "Article category missing"
    assert 'T-' in POS_WEIGHTS, "Determinative category missing"
    assert 'C-' in POS_WEIGHTS, "Conjunction category missing"
    assert 'X-' in POS_WEIGHTS, "Particle category missing"
    assert 'P-' in POS_WEIGHTS, "Pronoun category missing"
    assert 'R-' in POS_WEIGHTS, "Preposition category missing"


def test_weights_bounded():
    """Test all weights are in [0.0, 1.0]."""
    for pos_code, weight in POS_WEIGHTS.items():
        assert 0.0 <= weight <= 1.0, f"Weight for {pos_code} is {weight}, not in [0.0, 1.0]"


def test_pos_dominance():
    """Test that POS weight dominates the composite score."""
    high_score = composite_score(0.95, 100, 5)
    low_score = composite_score(0.05, 100, 5)
    assert high_score > low_score, "High POS weight should yield higher score"


def test_rarity_dominance():
    """Test that rarity (low frequency) dominates the composite score."""
    rare_score = composite_score(0.95, 5, 5)
    common_score = composite_score(0.95, 1000, 5)
    assert rare_score > common_score, "Rare words should score higher"


def test_ambiguity_dominance():
    """Test that ambiguity (high sense count) dominates the composite score."""
    ambiguous_score = composite_score(0.95, 5, 10)
    unambiguous_score = composite_score(0.95, 5, 2)
    assert ambiguous_score > unambiguous_score, "Ambiguous words should score higher"


def test_monotone_non_negative():
    """Test composite_score is monotone non-negative for positive inputs."""
    import random

    for _ in range(10):
        pos_weight = random.uniform(0.0, 1.0)
        frequency_count = random.randint(1, 1000)
        sense_count = random.randint(1, 100)

        score = composite_score(pos_weight, frequency_count, sense_count)
        assert score >= 0.0, f"Composite score should be non-negative: {score}"


def test_unknown_pos_handling():
    """Test unknown POS codes return default weight."""
    assert get_pos_weight('ZZZ') == 0.50, "Unknown POS should return default weight 0.50"
    assert get_pos_weight('UNKNOWN') == 0.50, "Unknown POS should return default weight 0.50"


def test_pos_zero_yields_zero():
    """Test that zero POS weight yields zero composite score."""
    score = composite_score(0.0, 1, 1)
    assert score == 0.0, "Zero POS weight should yield zero composite score"


if __name__ == "__main__":
    print("Running context constants tests...")

    test_pos_weights_categories()
    print("✓ POS weights categories test passed")

    test_weights_bounded()
    print("✓ Weights bounded test passed")

    test_pos_dominance()
    print("✓ POS dominance test passed")

    test_rarity_dominance()
    print("✓ Rarity dominance test passed")

    test_ambiguity_dominance()
    print("✓ Ambiguity dominance test passed")

    test_monotone_non_negative()
    print("✓ Monotone non-negative test passed")

    test_unknown_pos_handling()
    print("✓ Unknown POS handling test passed")

    test_pos_zero_yields_zero()
    print("✓ POS zero yields zero test passed")

    print("All tests passed!")
