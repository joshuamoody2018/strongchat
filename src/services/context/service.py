"""Original-language context enrichment for retrieved verses."""
import asyncio
import json
import logging
import re
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from services.base import BaseService
from config.context_constants import (
    POS_WEIGHTS, TOP_N_VECTOR_RESULTS, TOP_N_PERCENT_FINAL,
    MIN_WORDS_PER_VERSE, MIN_WORDS_AFTER_TRIM, composite_score,
)

logger = logging.getLogger(__name__)


class ContextRetrievalService(BaseService):
    """Attach synthesis-ready original-language context to every retrieved hit."""

    def __init__(
        self,
        db_path: str = 'data/chat_database.db',
        macula_db_path: str = 'data/macula_index.db',
    ) -> None:
        super().__init__(db_path)
        # macula DB is a SEPARATE connection with check_same_thread=False
        # so asyncio.to_thread calls don't raise sqlite3.ProgrammingError.
        # Pattern mirrors _ThreadSafeChatDatabase at src/services/database/adapters/sqlite.py:25-26.
        self._macula_conn = sqlite3.connect(macula_db_path, check_same_thread=False)
        # Single lock to serialize writes; reads can be concurrent under WAL
        # but the lock keeps things simple for v1.
        self._macula_lock = asyncio.Lock()

    def close(self) -> None:
        self._macula_conn.close()

    # ----- public API -----

    async def retrieve_for_pipeline(
        self, pipeline_result, session_uuid: str,
    ) -> Any:
        """Run context enrichment for every intent in the pipeline result.

        Iterates trace.search_results.items() per intent, attaches context_bundle
        to each hit in place, and records one context_retrieval message per
        intent (per-intent exception capture: failures do not abort other intents).

        Returns the same pipeline_result (mutated in place).
        """
        tasks = [
            self._process_intent(intent_id, trace, session_uuid)
            for intent_id, trace in pipeline_result.traces.items()
            if trace.search_results  # skip intents with no retrieval hits
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        return pipeline_result

    # ----- internal -----

    async def _process_intent(
        self, intent_id: str, trace, session_uuid: str,
    ) -> None:
        """Process every hit under this intent's search_results dict.

        On any exception, logs to stderr, records a context_retrieval row
        with error_text, and does NOT propagate.
        """
        try:
            translation_count = 0
            hit_count = 0
            scored_word_count = 0
            kept_word_count = 0

            for translation, hits in trace.search_results.items():
                translation_count += 1
                for hit in hits:
                    hit_count += 1
                    bundle = await self._build_bundle_for_hit(hit, translation)
                    hit['context_bundle'] = bundle
                    scored_word_count += bundle['scored_word_count']
                    kept_word_count += bundle['kept_word_count']

            summary = {
                'intent_id': intent_id,
                'translation_count': translation_count,
                'hit_count': hit_count,
                'scored_word_count': scored_word_count,
                'kept_word_count': kept_word_count,
            }
            await self.record_message(
                message_type_slug='context_retrieval',
                unique_prompt=json.dumps(summary),
                session_uuid=session_uuid,
                raw_response=None,
                error_text=None,
                num_tries=1,
            )
        except Exception as exc:
            logger.exception("Context retrieval failed for intent %s", intent_id)
            try:
                await self.record_message(
                    message_type_slug='context_retrieval',
                    unique_prompt=json.dumps({'intent_id': intent_id}),
                    session_uuid=session_uuid,
                    error_text=str(exc),
                    num_tries=1,
                )
            except Exception:
                logger.exception("Could not record context_retrieval error row")

    async def _build_bundle_for_hit(
        self, hit: Dict[str, Any], translation: str,
    ) -> Dict[str, Any]:
        """Build a synthesis-ready context_bundle for one hit."""
        reference = hit.get('reference', '')
        parsed = _parse_reference(reference)
        if parsed is None:
            return _empty_bundle(reference, translation, reason='unparseable reference')
        book_osis, chapter, verse = parsed

        # Look up tokens for this verse
        tokens = await asyncio.to_thread(
            self._fetch_tokens, book_osis, chapter, verse,
        )
        if not tokens:
            return _empty_bundle(
                reference, translation,
                reason=f'no macula tokens for {book_osis} {chapter}:{verse}',
            )

        # Deduplicate by strongs to get unique words
        unique_words = _dedupe_tokens_by_strongs(tokens)
        if len(unique_words) < MIN_WORDS_PER_VERSE:
            return _empty_bundle(
                reference, translation,
                reason=f'fewer than {MIN_WORDS_PER_VERSE} unique words',
            )

        # Look up frequency + senses for each unique word
        strongs_numbers = [w['strongs'] for w in unique_words if w['strongs']]
        freq_map = await asyncio.to_thread(self._fetch_freq_map, strongs_numbers)
        senses_map = await asyncio.to_thread(self._fetch_senses_map, strongs_numbers)
        occurrence_cache = await asyncio.to_thread(self._build_occurrence_cache, strongs_numbers)

        # Score each word and build scored_words list
        scored_words = []
        for w in unique_words:
            strongs = w['strongs']
            if not strongs:
                continue
            pos = w.get('pos', '')
            pos_weight = _get_pos_weight(pos)
            freq_count = freq_map.get(strongs, 1)
            senses = senses_map.get(strongs, [])
            sense_count = len(senses) if senses else 1
            score = composite_score(pos_weight, freq_count, sense_count)
            scored_words.append({
                'strongs': strongs,
                'surface': w['surface'],
                'lemma': w['lemma'],
                'pos': pos,
                'morph': w['morph'],
                'pos_weight': pos_weight,
                'frequency_count': freq_count,
                'sense_count': sense_count,
                'composite_score': score,
                'definitions': [s for s in senses],
                'gloss': w.get('gloss', ''),  # Use .get() with fallback for missing gloss
                'lexicon_source': 'tbESG+LSJ',
                'macula_occurrences': occurrence_cache.get(strongs, 0),
            })

        # Sort by composite_score DESC, take top N, filter to score > 0
        scored_words.sort(key=lambda x: x['composite_score'], reverse=True)
        # Keep top N% (rounded up to int) with score > 0
        top_n_count = max(MIN_WORDS_AFTER_TRIM,
                           int(len(scored_words) * TOP_N_PERCENT_FINAL))
        kept_words = [w for w in scored_words[:top_n_count] if w['composite_score'] > 0]
        if len(kept_words) < MIN_WORDS_AFTER_TRIM:
            # Fall back to top MIN_WORDS_AFTER_TRIM regardless of score
            kept_words = scored_words[:MIN_WORDS_AFTER_TRIM]

        return {
            'hit_id': hit.get('id', ''),
            'reference': reference,
            'translation': translation,
            'unique_word_count': len(unique_words),
            'scored_word_count': len(scored_words),
            'kept_word_count': len(kept_words),
            'scored_words': scored_words,
            'kept_words': kept_words,
            'build_summary': (
                f'{len(unique_words)} unique → {len(scored_words)} scored '
                f'→ {len(kept_words)} kept'
            ),
        }

    # ----- SQLite helpers (synchronous; called via asyncio.to_thread) -----

    def _fetch_tokens(
        self, book_osis: str, chapter: int, verse: int,
    ) -> List[Dict[str, Any]]:
        cur = self._macula_conn.execute(
            "SELECT surface, lemma, strongs, morph, pos FROM macula_tokens "
            "WHERE book_osis=? AND chapter=? AND verse=? ORDER BY word_pos",
            (book_osis, chapter, verse),
        )
        return [
            {'surface': r[0], 'lemma': r[1], 'strongs': r[2], 'morph': r[3], 'pos': r[4]}
            for r in cur.fetchall()
        ]

    def _fetch_freq_map(self, strongs_numbers: List[str]) -> Dict[str, int]:
        if not strongs_numbers:
            return {}
        placeholders = ','.join('?' * len(strongs_numbers))
        cur = self._macula_conn.execute(
            f"SELECT strongs_number, occurrence_count FROM strongs_frequency "
            f"WHERE strongs_number IN ({placeholders})",
            strongs_numbers,
        )
        return {r[0]: r[1] for r in cur.fetchall()}

    def _fetch_senses_map(
        self, strongs_numbers: List[str],
    ) -> Dict[str, List[str]]:
        if not strongs_numbers:
            return {}
        placeholders = ','.join('?' * len(strongs_numbers))
        cur = self._macula_conn.execute(
            f"SELECT strongs_number, definition FROM lexicon_definitions "
            f"WHERE strongs_number IN ({placeholders}) ORDER BY strongs_number, sense_index",
            strongs_numbers,
        )
        out: Dict[str, List[str]] = {}
        for r in cur.fetchall():
            out.setdefault(r[0], []).append(r[1])
        return out

    def _build_occurrence_cache(self, strongs_numbers: List[str]) -> Dict[str, int]:
        if not strongs_numbers:
            return {}
        placeholders = ','.join('?' * len(strongs_numbers))
        cur = self._macula_conn.execute(
            f"SELECT strongs, COUNT(*) FROM macula_tokens "
            f"WHERE strongs IN ({placeholders}) GROUP BY strongs",
            strongs_numbers,
        )
        return {r[0]: r[1] for r in cur.fetchall()}


# ----- module-level helpers -----

NUMBERED_BOOK_PREFIXES = ('1', '2', '3')

# Short-form (numbered-book short names) -> OSIS
BOOK_OSIS_SHORT = {
    '1 John': '1John', '2 John': '2John', '3 John': '3John',
    '1 Cor': '1Cor', '2 Cor': '2Cor',
    '1 Thess': '1Thess', '2 Thess': '2Thess',
    '1 Tim': '1Tim', '2 Tim': '2Tim',
    '1 Pet': '1Pet', '2 Pet': '2Pet',
}

# Full-form (numbered-book full English names) -> OSIS
BOOK_OSIS_FULL = {
    '1 Corinthians': '1Cor', '2 Corinthians': '2Cor',
    '1 Thessalonians': '1Thess', '2 Thessalonians': '2Thess',
    '1 Timothy': '1Tim', '2 Timothy': '2Tim',
    '1 Peter': '1Pet', '2 Peter': '2Pet',
}

# Non-numbered-book identity mapping (English names as returned by ChromaDB ingest)
BOOK_OSIS_NAME = {
    'Genesis': 'Gen', 'Exodus': 'Exod', 'Leviticus': 'Lev',
    'Numbers': 'Num', 'Deuteronomy': 'Deut', 'Joshua': 'Josh',
    'Judges': 'Judg', 'Ruth': 'Ruth',
    '1 Samuel': '1Sam', '2 Samuel': '2Sam',
    '1 Kings': '1Kgs', '2 Kings': '2Kgs',
    '1 Chronicles': '1Chr', '2 Chronicles': '2Chr',
    'Ezra': 'Ezra', 'Nehemiah': 'Neh', 'Esther': 'Esth',
    'Job': 'Job', 'Psalm': 'Ps', 'Proverbs': 'Prov',
    'Ecclesiastes': 'Eccl', 'Song of Solomon': 'Song',
    'Isaiah': 'Isa', 'Jeremiah': 'Jer', 'Lamentations': 'Lam',
    'Ezekiel': 'Ezek', 'Daniel': 'Dan',
    'Hosea': 'Hos', 'Joel': 'Joel', 'Amos': 'Amos',
    'Obadiah': 'Obad', 'Jonah': 'Jonah', 'Micah': 'Mic',
    'Nahum': 'Nah', 'Habakkuk': 'Hab', 'Zephaniah': 'Zeph',
    'Haggai': 'Hag', 'Zechariah': 'Zech', 'Malachi': 'Mal',
    'Matthew': 'Matt', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John',
    'Acts': 'Acts', 'Romans': 'Rom',
    'Galatians': 'Gal', 'Ephesians': 'Eph', 'Philippians': 'Phil',
    'Colossians': 'Col',
    'Titus': 'Titus', 'Philemon': 'Phlm',
    'Hebrews': 'Heb', 'James': 'Jas',
    'Jude': 'Jude', 'Revelation': 'Rev',
}

# OSIS short codes as they appear in the Macula DB (identity map for already-OSIS inputs)
BOOK_OSIS_IDENTITY = {
    'Matt': 'Matt', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John', 'Acts': 'Acts', 'Rom': 'Rom',
    '1Cor': '1Cor', '2Cor': '2Cor', 'Gal': 'Gal', 'Eph': 'Eph', 'Phil': 'Phil', 'Col': 'Col',
    '1Thess': '1Thess', '2Thess': '2Thess', '1Tim': '1Tim', '2Tim': '2Tim', 'Titus': 'Titus', 'Phlm': 'Phlm',
    'Heb': 'Heb', 'Jas': 'Jas', '1Pet': '1Pet', '2Pet': '2Pet', '1John': '1John', '2John': '2John', '3John': '3John', 'Jude': 'Jude', 'Rev': 'Rev',
}


def _book_to_osis(book: str) -> Optional[str]:
    """Map a book name (English full, short, or OSIS) to OSIS short code.

    Try short-form first (for numbered-book short names like '1 John'),
    then full-form (for numbered-book full names like '1 Corinthians'),
    then identity (already-OSIS like '1John' or non-numbered like 'John'),
    then BOOK_OSIS_NAME (English names like 'Matthew').
    Returns None if not recognized.
    """
    if not book:
        return None
    if book in BOOK_OSIS_SHORT:
        return BOOK_OSIS_SHORT[book]
    if book in BOOK_OSIS_FULL:
        return BOOK_OSIS_FULL[book]
    if book in BOOK_OSIS_IDENTITY:
        return book
    if book in BOOK_OSIS_NAME:
        return BOOK_OSIS_NAME[book]
    # Last resort: try lowercase match against the full set
    for d in (BOOK_OSIS_SHORT, BOOK_OSIS_FULL, BOOK_OSIS_IDENTITY, BOOK_OSIS_NAME):
        for k, v in d.items():
            if k.lower() == book.lower():
                return v
    return None


def _parse_reference(reference: str) -> Optional[Tuple[str, int, int]]:
    """Parse '1 John 2:3' / 'John 3:16' / 'Matt 1:1' into (book_osis, chapter, verse).

    Uses NUMBERED_BOOK_PREFIXES to decide whether the first TWO whitespace-
    delimited tokens form the book name.
    """
    if not reference:
        return None
    parts = reference.split()
    if len(parts) < 2:
        return None
    if parts[0][0:1] in NUMBERED_BOOK_PREFIXES:
        book = ' '.join(parts[:2])
        rest = ' '.join(parts[2:])
    else:
        book = parts[0]
        rest = ' '.join(parts[1:])
    # rest looks like "3:16" or "2:3"
    m = re.match(r'^(\d+):(\d+)', rest)
    if not m:
        return None
    chapter = int(m.group(1))
    verse = int(m.group(2))
    book_osis = _book_to_osis(book)
    if book_osis is None:
        return None
    return (book_osis, chapter, verse)


def _get_pos_weight(pos: str) -> float:
    """Look up POS weight from the POS_WEIGHTS dict.

    POS_WEIGHTS keys are prefixes (e.g. 'V-', 'N-'). Match by longest prefix.
    Unknown POS returns the default weight of 0.50.
    """
    if pos in POS_WEIGHTS:
        return POS_WEIGHTS[pos]
    # Try prefix matching: 'V-3SAI' → 'V-'
    for prefix, weight in POS_WEIGHTS.items():
        if pos.startswith(prefix):
            return weight
    return 0.50


def _dedupe_tokens_by_strongs(tokens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate tokens by strongs number, keeping first occurrence per strongs."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for t in tokens:
        strongs = t.get('strongs', '')
        if not strongs:
            continue
        if strongs in seen:
            continue
        seen.add(strongs)
        out.append(t)
    return out


def _empty_bundle(
    reference: str, translation: str, reason: str,
) -> Dict[str, Any]:
    """Build an empty context_bundle when no enrichment is possible."""
    return {
        'hit_id': '',
        'reference': reference,
        'translation': translation,
        'unique_word_count': 0,
        'scored_word_count': 0,
        'kept_word_count': 0,
        'scored_words': [],
        'kept_words': [],
        'build_summary': reason,
    }