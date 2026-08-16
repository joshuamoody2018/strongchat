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

# HAM (Hebrew Augmented Morphology) POS weight table — Macula Hebrew.
# Mirrors the Greek Robinson scheme: high-weight content words (verb, noun,
# proper noun, adjective), low-weight function words (article, conjunction,
# preposition, adverb, pronoun), and an exact-match-first semantics.
#
# The keys match the lowercase `pos` values produced by the Macula-Hebrew
# TSV `pos` column (see mappings/lowfat-macula-hebrew.xquery's local:val()
# lower-casing). Macula-Hebrew emits full English words ('noun', 'verb',
# 'preposition', 'particle', 'conjunction', 'suffix', 'adjective',
# 'pronoun', 'adverb'). HAM trigram aliases ('subs', 'nmpr', 'artc', ...)
# are also included defensively so the table is robust to a future
# upstream schema migration.
#
# ContextRetrievalService uses exact-match lookup only (no longest-prefix
# rule, since every Macula-Hebrew pos value is a single lowercase token).
# Unknown POS values default to 0.50 via get_pos_weight().
POS_WEIGHTS_HEBREW: Dict[str, float] = {
    # High-weight content words (matching Macula-Hebrew full-word POS)
    'verb': 0.95,         # Verbs (all stems/tenses)
    'noun': 0.825,        # Nouns
    'proper noun': 0.825, # Proper nouns (lowercase form; defensive)
    'adjective': 0.65,    # Adjectives

    # Low-weight function words
    'article': 0.05,      # Definite article (-הַ)
    'conjunction': 0.05,  # Conjunctions (ו, כי, אשר)
    'preposition': 0.25,  # Prepositions (ב, ל, מ, כ, עם)
    'adverb': 0.10,       # Adverbs / particles
    'particle': 0.10,     # Particles
    'pronoun': 0.40,      # Personal pronouns
    'suffix': 0.40,       # Pronominal suffixes (possessive on名词 etc.)

    # HAM trigram aliases (defensive — covers an alternate upstream shape):
    # subs=substantive (noun), nmpr=proper-noun, adjv=adjective, artc=article,
    # conj=conjunction, prep=preposition, advb=adverb, prps/prde=pronoun,
    # intr=interrogative/particle, neg=negation particle, card/ordn=numbers.
    'subs': 0.825,
    'nmpr': 0.825,
    'adjv': 0.65,
    'artc': 0.05,
    'conj': 0.05,
    'prep': 0.25,
    'advb': 0.10,
    'prps': 0.40,
    'prde': 0.40,
    'intr': 0.10,
    'neg': 0.10,
    'card': 0.10,
    'ordn': 0.10,
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

def get_pos_weight(pos_code: str, language: str = 'greek') -> float:
    """Get POS weight for a given POS code, returning default for unknown codes.

    Args:
        pos_code: Morphological code. Robinson codes for Greek (e.g. 'V-', 'N-'),
            HAM lowercase codes for Hebrew (e.g. 'verb', 'subs').
        language: 'greek' (default) or 'hebrew'. Routes to the appropriate
            POS_WEIGHTS table.

    Returns:
        Weight from the relevant POS_WEIGHTS table or 0.50 for unknown codes.
    """
    if language == 'hebrew':
        table = POS_WEIGHTS_HEBREW
    else:
        table = POS_WEIGHTS
    if pos_code in table:
        return table[pos_code]
    # Hebrew HAM codes are full lowercase words — no prefix matching needed.
    # Greek Robinson codes use prefix matching ('V-3SAI' → 'V-'); kept for
    # backward compat with the original Greek implementation.
    if language == 'greek':
        for prefix, weight in table.items():
            if pos_code.startswith(prefix):
                return weight
    return 0.50

__all__ = [
    'POS_WEIGHTS',
    'POS_WEIGHTS_HEBREW',
    'TOP_N_VECTOR_RESULTS',
    'TOP_N_PERCENT_FINAL',
    'MIN_WORDS_PER_VERSE',
    'MIN_WORDS_AFTER_TRIM',
    'composite_score',
    'get_pos_weight',
]