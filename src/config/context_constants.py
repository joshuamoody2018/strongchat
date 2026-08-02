"""Context retrieval constants for POS weighting and scoring."""

import math
from typing import Dict

# Robinson (Greek NT) morphological codes POS weight table
# High-weight content words: verbs, nouns, adjectives
# Low-weight function words: articles, conjunctions, particles, prepositions, pronouns, determinatives
# Unknown POS defaults to 0.50 to avoid zeroing out words
# Source: Robinson morphological codes for Greek New Testament
POS_WEIGHTS: Dict[str, float] = {
    # High-weight content words
    'V-': 0.95,    # Verbs (all tenses/moods)
    'N-': 0.825,  # Nouns (predicate and substantive nouns collapsed per round-3 review caveat)
    'A-': 0.65,   # Adjectives
    
    # Low-weight function words  
    'D-': 0.05,   # Articles (definite/indefinite)
    'C-': 0.05,   # Conjunctions
    'X-': 0.10,   # Particles
    'R-': 0.25,   # Prepositions
    'P-': 0.40,   # Pronouns
    'T-': 0.40,   # Determinatives
}

# Tuning knobs for context retrieval
TOP_N_VECTOR_RESULTS = 25
TOP_N_PERCENT_FINAL = 0.20
MIN_WORDS_PER_VERSE = 3
MIN_WORDS_AFTER_TRIM = 2

def composite_score(pos_weight: float, frequency_count: int, sense_count: int) -> float:
    """Compute composite score for context word selection.
    
    Formula: pos_weight * log(1 + 1/frequency_count) * log(1 + sense_count)
    
    Args:
        pos_weight: Weight from POS_WEIGHTS (0.0-1.0)
        frequency_count: Corpus frequency of the word (>= 1)
        sense_count: Number of senses/meanings (>= 1)
    
    Returns:
        Composite score for word ranking
    """
    return pos_weight * math.log1p(1.0 / max(frequency_count, 1)) * math.log1p(sense_count)

def get_pos_weight(pos_code: str) -> float:
    """Get POS weight for a given POS code, returning default for unknown codes.
    
    Args:
        pos_code: Robinson morphological code (e.g., 'V-', 'N-')
    
    Returns:
        Weight from POS_WEIGHTS or 0.50 for unknown codes
    """
    return POS_WEIGHTS.get(pos_code, 0.50)

__all__ = [
    'POS_WEIGHTS',
    'TOP_N_VECTOR_RESULTS', 
    'TOP_N_PERCENT_FINAL',
    'MIN_WORDS_PER_VERSE',
    'MIN_WORDS_AFTER_TRIM',
    'composite_score',
    'get_pos_weight',
]