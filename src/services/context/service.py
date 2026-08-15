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
    get_pos_weight,
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
        # SQLite connections are not safe for concurrent use across threads;
        # check_same_thread=False only suppresses the thread-affinity check,
        # it does not serialize access. We need to call _fetch_* helpers via
        # asyncio.to_thread from parallel intent coroutines, so we use the
        # per-call short-lived connection pattern: each helper opens a fresh
        # sqlite3.connect(), runs one query, and closes it. SQLite opens in
        # <1ms on local disk and the OS-level file lock handles serialization.
        # See docs/implementation-status.md and todo.md for the rationale.
        self._macula_db_path = macula_db_path

    def close(self) -> None:
        # No long-lived macula connection to close; per-call connections are
        # closed at the end of every _fetch_* helper.
        pass

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
            bundles: List[Dict[str, Any]] = []

            for translation, hits in trace.search_results.items():
                translation_count += 1
                for hit in hits:
                    hit_count += 1
                    bundle = await self._build_bundle_for_hit(hit, translation)
                    hit['context_bundle'] = bundle
                    bundles.append(bundle)
                    scored_word_count += bundle['scored_word_count']
                    kept_word_count += bundle['kept_word_count']

            summary = {
                'intent_id': intent_id,
                'translation_count': translation_count,
                'hit_count': hit_count,
                'scored_word_count': scored_word_count,
                'kept_word_count': kept_word_count,
            }
            raw_payload = {
                'intent_id': intent_id,
                'bundles': bundles,
            }
            await self.record_message(
                message_type_slug='context_retrieval',
                unique_prompt=json.dumps(summary),
                session_uuid=session_uuid,
                raw_response=json.dumps(raw_payload),
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

        # Derive language/testament from the first token's book_num.
        # OT books are 1-39; NT are 40-66. Routed lookup is critical because
        # Greek (tbESG+lsj) and Hebrew (tbESH) share bare-int strongs keys
        # but live as separate lexicon_source rows; querying without the
        # filter would conflate definitions and frequencies across
        # testaments. Backup: consult _BOOK_OSIS_LANGUAGE if book_num is
        # somehow missing (defensive — should never happen since
        # macula_tokens.book_num is NOT NULL).
        first_book_num = tokens[0].get('book_num')
        if first_book_num is not None and first_book_num < 40:
            language = 'hebrew'
            testament = 'OT'
        else:
            language = 'greek'
            testament = 'NT'
        # Defensive: if book_num is None pick via OSIS lookup so we still
        # route correctly when the schema is missing book_num.
        if first_book_num is None:
            looked_up = _BOOK_OSIS_LANGUAGE.get(book_osis, 'greek')
            language = looked_up
            testament = _LANG_TO_TESTAMENT[looked_up]

        # Deduplicate by strongs to get unique words
        unique_words = _dedupe_tokens_by_strongs(tokens)
        if len(unique_words) < MIN_WORDS_PER_VERSE:
            return _empty_bundle(
                reference, translation,
                reason=f'fewer than {MIN_WORDS_PER_VERSE} unique words',
            )

        # Look up frequency + senses for each unique word
        strongs_numbers = [w['strongs'] for w in unique_words if w['strongs']]
        freq_map = await asyncio.to_thread(
            self._fetch_freq_map, strongs_numbers, testament,
        )
        senses_map = await asyncio.to_thread(
            self._fetch_senses_map, strongs_numbers, language,
        )
        occurrence_cache = await asyncio.to_thread(
            self._build_occurrence_cache, strongs_numbers, language,
        )

        # Pick the lexicon_source tag communicated to the synthesis stage.
        # Greek path reports 'tbESG+LSJ' (union of two Greek lexicons);
        # Hebrew path reports 'tbESH'. Tests assert against these strings.
        lexicon_source_tag = 'tbESH' if language == 'hebrew' else 'tbESG+LSJ'

        # Score each word and build scored_words list
        scored_words = []
        for w in unique_words:
            strongs = w['strongs']
            if not strongs:
                continue
            pos = w.get('pos', '')
            pos_weight = _get_pos_weight(pos, language)
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
                'gloss': w['gloss'],  # Direct access - gloss should always be present after schema fix
                'lexicon_source': lexicon_source_tag,
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
        conn = sqlite3.connect(self._macula_db_path)
        try:
            cur = conn.execute(
                "SELECT surface, lemma, strongs, morph, pos, gloss, book_num "
                "FROM macula_tokens "
                "WHERE book_osis=? AND chapter=? AND verse=? ORDER BY word_pos",
                (book_osis, chapter, verse),
            )
            return [
                {
                    'surface': r[0], 'lemma': r[1], 'strongs': r[2],
                    'morph': r[3], 'pos': r[4], 'gloss': r[5],
                    'book_num': r[6],
                }
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def _fetch_freq_map(
        self, strongs_numbers: List[str], testament: str,
    ) -> Dict[str, int]:
        """Look up corpus frequency for each strongs number, filtered
        by testament ('NT' or 'OT') to avoid Greek/Hebrew bare-int key
        collisions in the shared strongs_frequency table."""
        if not strongs_numbers:
            return {}
        placeholders = ','.join('?' * len(strongs_numbers))
        conn = sqlite3.connect(self._macula_db_path)
        try:
            cur = conn.execute(
                f"SELECT strongs_number, occurrence_count FROM strongs_frequency "
                f"WHERE testament=? AND strongs_number IN ({placeholders})",
                (testament, *strongs_numbers),
            )
            return {r[0]: r[1] for r in cur.fetchall()}
        finally:
            conn.close()

    def _fetch_senses_map(
        self, strongs_numbers: List[str], language: str,
    ) -> Dict[str, List[str]]:
        """Look up lexicon sense definitions for each strongs number,
        filtered by lexicon_source based on language so Greek keys do
        not pick up Hebrew TBESH entries and vice-versa.

        Greek path: tbESG + lsj (definitions concatenated in order).
        Hebrew path: tbESH only.
        """
        if not strongs_numbers:
            return {}
        if language == 'hebrew':
            lexicon_sources = ('tbESH',)
        else:
            lexicon_sources = ('tbESG', 'lsj')
        placeholders = ','.join('?' * len(strongs_numbers))
        src_placeholders = ','.join('?' * len(lexicon_sources))
        conn = sqlite3.connect(self._macula_db_path)
        try:
            cur = conn.execute(
                f"SELECT strongs_number, definition FROM lexicon_definitions "
                f"WHERE strongs_number IN ({placeholders}) "
                f"AND lexicon_source IN ({src_placeholders}) "
                f"ORDER BY strongs_number, lexicon_source, sense_index",
                (*strongs_numbers, *lexicon_sources),
            )
            out: Dict[str, List[str]] = {}
            for r in cur.fetchall():
                out.setdefault(r[0], []).append(r[1])
            return out
        finally:
            conn.close()

    def _build_occurrence_cache(
        self, strongs_numbers: List[str], language: str,
    ) -> Dict[str, int]:
        """Count Macula-token occurrences for each strongs number,
        filtered by testament (book_num range) so Greek and Hebrew
        keys with the same bare-int value are not conflated."""
        if not strongs_numbers:
            return {}
        if language == 'hebrew':
            book_filter = "book_num < 40"
        else:
            book_filter = "book_num >= 40"
        placeholders = ','.join('?' * len(strongs_numbers))
        conn = sqlite3.connect(self._macula_db_path)
        try:
            cur = conn.execute(
                f"SELECT strongs, COUNT(*) FROM macula_tokens "
                f"WHERE {book_filter} AND strongs IN ({placeholders}) "
                f"GROUP BY strongs",
                strongs_numbers,
            )
            return {r[0]: r[1] for r in cur.fetchall()}
        finally:
            conn.close()


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
    # NT
    'Matt': 'Matt', 'Mark': 'Mark', 'Luke': 'Luke', 'John': 'John', 'Acts': 'Acts', 'Rom': 'Rom',
    '1Cor': '1Cor', '2Cor': '2Cor', 'Gal': 'Gal', 'Eph': 'Eph', 'Phil': 'Phil', 'Col': 'Col',
    '1Thess': '1Thess', '2Thess': '2Thess', '1Tim': '1Tim', '2Tim': '2Tim', 'Titus': 'Titus', 'Phlm': 'Phlm',
    'Heb': 'Heb', 'Jas': 'Jas', '1Pet': '1Pet', '2Pet': '2Pet', '1John': '1John', '2John': '2John', '3John': '3John', 'Jude': 'Jude', 'Rev': 'Rev',
    # OT — bare OSIS short codes ('Gen', 'Isa', 'Ps', etc.) resolve to themselves
    'Gen': 'Gen', 'Exod': 'Exod', 'Lev': 'Lev', 'Num': 'Num', 'Deut': 'Deut',
    'Josh': 'Josh', 'Judg': 'Judg', 'Ruth': 'Ruth',
    '1Sam': '1Sam', '2Sam': '2Sam', '1Kgs': '1Kgs', '2Kgs': '2Kgs',
    '1Chr': '1Chr', '2Chr': '2Chr', 'Ezra': 'Ezra', 'Neh': 'Neh', 'Esth': 'Esth',
    'Job': 'Job', 'Ps': 'Ps', 'Prov': 'Prov', 'Eccl': 'Eccl', 'Song': 'Song',
    'Isa': 'Isa', 'Jer': 'Jer', 'Lam': 'Lam', 'Ezek': 'Ezek', 'Dan': 'Dan',
    'Hos': 'Hos', 'Joel': 'Joel', 'Amos': 'Amos', 'Obad': 'Obad', 'Jonah': 'Jonah',
    'Mic': 'Mic', 'Nah': 'Nah', 'Hab': 'Hab', 'Zeph': 'Zeph',
    'Hag': 'Hag', 'Zech': 'Zech', 'Mal': 'Mal',
}

# Per-testament language tag. Greek NT OSIS codes -> 'greek'; Hebrew OT
# OSIS codes -> 'hebrew'. Used by ContextRetrievalService to route pos
# weights, frequency filters, and lexicon source filters without needing
# to query the DB just to know the testament.
_BOOK_OSIS_LANGUAGE = {
    # NT
    'Matt': 'greek', 'Mark': 'greek', 'Luke': 'greek', 'John': 'greek',
    'Acts': 'greek', 'Rom': 'greek', '1Cor': 'greek', '2Cor': 'greek',
    'Gal': 'greek', 'Eph': 'greek', 'Phil': 'greek', 'Col': 'greek',
    '1Thess': 'greek', '2Thess': 'greek', '1Tim': 'greek', '2Tim': 'greek',
    'Titus': 'greek', 'Phlm': 'greek', 'Heb': 'greek', 'Jas': 'greek',
    '1Pet': 'greek', '2Pet': 'greek', '1John': 'greek', '2John': 'greek',
    '3John': 'greek', 'Jude': 'greek', 'Rev': 'greek',
    # OT
    'Gen': 'hebrew', 'Exod': 'hebrew', 'Lev': 'hebrew', 'Num': 'hebrew',
    'Deut': 'hebrew', 'Josh': 'hebrew', 'Judg': 'hebrew', 'Ruth': 'hebrew',
    '1Sam': 'hebrew', '2Sam': 'hebrew', '1Kgs': 'hebrew', '2Kgs': 'hebrew',
    '1Chr': 'hebrew', '2Chr': 'hebrew', 'Ezra': 'hebrew', 'Neh': 'hebrew',
    'Esth': 'hebrew', 'Job': 'hebrew', 'Ps': 'hebrew', 'Prov': 'hebrew',
    'Eccl': 'hebrew', 'Song': 'hebrew', 'Isa': 'hebrew', 'Jer': 'hebrew',
    'Lam': 'hebrew', 'Ezek': 'hebrew', 'Dan': 'hebrew', 'Hos': 'hebrew',
    'Joel': 'hebrew', 'Amos': 'hebrew', 'Obad': 'hebrew', 'Jonah': 'hebrew',
    'Mic': 'hebrew', 'Nah': 'hebrew', 'Hab': 'hebrew', 'Zeph': 'hebrew',
    'Hag': 'hebrew', 'Zech': 'hebrew', 'Mal': 'hebrew',
}
_TESTAMENT_TO_LANG = {'NT': 'greek', 'OT': 'hebrew'}
_LANG_TO_TESTAMENT = {'greek': 'NT', 'hebrew': 'OT'}


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


def _get_pos_weight(pos: str, language: str = 'greek') -> float:
    """Look up POS weight from the language-appropriate POS_WEIGHTS table.

    Greek: Robinson codes ('V-', 'N-', ...). Longest-prefix match applies
    so codes like 'V-3SAI' resolve to 'V-'.
    Hebrew: HAM lowercase codes ('verb', 'subs', ...). Exact match only
    (no prefix rule, since HAM codes are full lowercase trigrams).

    Returns the configured weight, defaulting to 0.50 for unknown codes.
    """
    return get_pos_weight(pos, language=language)


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