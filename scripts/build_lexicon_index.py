#!/usr/bin/env python3
"""
Build lexicon index from STEPBible TBESG and LSJ Greek lexicon TSVs.
Ingests into data/macula_index.db with lexicon_definitions table.
"""

import argparse
import csv
import sqlite3
import sys
import requests
from pathlib import Path


def normalize_strongs(raw: str) -> str:
    """Normalize an eStrong code to the key used in macula_tokens.

    STEPBible lexicons key on the 'eStrong' / 'eStrong#' column with an
    uppercase prefix (`G0976`, `H2424`, zero-padded with a language prefix),
    while the Macula Greek TSV `strongnumberx` column is a bare integer
    string (`'976'`, `'2424'`) and the Macula Hebrew TSV uses bare
    zero-padded integers, optionally followed by a single lowercase or
    uppercase letter suffix (`'0871a'`, `'0047G'`). TBESH's `dStrong#`
    further distinguishes senses with a trailing letter. The two tables
    must share one key format for ContextRetrievalService._fetch_senses_map
    to join them per testament.

    This normalizer:
      - strips an optional leading G/H prefix (case-insensitive),
      - strips leading zeros from the numeric portion,
      - preserves an optional trailing letter suffix, lowercased,
        so that `H0047G`, `h0047g`, `047G` all map to `47g`.

    Examples:
      `G0976` -> `976`
      `h2424` -> `2424`
      `H0047G` -> `47g`
      `0871a` -> `871a`
      `0025`  -> `25`

    Returns the input untouched if it does not match the expected pattern
    (defensive; surfaces unexpected TSV drift in validation).
    """
    import re
    m = re.match(r'^([GHgh])?0*(\d+)([A-Za-z]?)$', (raw or '').strip())
    if m is None:
        return (raw or '').strip()
    suffix = m.group(3)
    return str(int(m.group(2))) + (suffix.lower() if suffix else '')


def download_tsv(url, timeout):
    """Download TSV from URL and return text content."""
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Warning: Failed to download {url}: {e}", file=sys.stderr)
        return None


def parse_tsv_content(content, expected_columns):
    """Parse TSV content and return header and rows.

    Handles the STEPBible convention of a prose header block followed by a
    column header row beginning with 'eStrong' and ending with a row of
    '===' separators before data starts.

    Accepts the header row for either Greek lexicons (TBESG/LSJ, ending in
    'Greek') or Hebrew lexicons (TBESH, ending in 'Hebrew'): the primary
    probe tries the Greek-specific prefix first, then falls back to a
    presence check on eStrong/dStrong/uStrong (testament-agnostic).
    """
    lines = content.split('\n')

    # Find the header row. Greek STEPBible lexicons start with
    # 'eStrong\tdStrong\tuStrong\tGreek'; Hebrew TBESH starts with
    # 'eStrong#\tdStrong#\tuStrong#\tHebrew'. Probe both, plus a generic
    # fallback that just checks for the eStrong/dStrong/uStrong tokens.
    header_line_idx = None
    for i, line in enumerate(lines):
        if (line.startswith('eStrong\tdStrong\tuStrong\tGreek')
                or line.startswith('eStrong#\tdStrong#\tuStrong#\tHebrew')
                or line.startswith('eStrong#\tdStrong#\tuStrong#\tHebrew ')):
            header_line_idx = i
            break

    if header_line_idx is None:
        # Try alternative header detection (e.g. truncated/different files)
        for i, line in enumerate(lines):
            if 'eStrong' in line and 'dStrong' in line and 'uStrong' in line:
                header_line_idx = i
                break

    if header_line_idx is None:
        raise ValueError(
            "Could not find a STEPBible header row starting with "
            "'eStrong\\tdStrong\\tuStrong\\t...' for either Greek or Hebrew"
        )

    header = lines[header_line_idx].strip().split('\t')

    # Some Hebrew files use 'eStrong#' as the column name; canonicalise
    # by stripping trailing '#' so the rest of the pipeline can refer to
    # a single 'eStrong' column regardless of testament.
    header = [c.rstrip('#') for c in header]

    # Find the start of data. Greek STEPBible lexicons emit a row of
    # '=====' separators between the header and the data; Hebrew TBESH
    # does not, so we fall back to "first non-empty line after the
    # header that has enough columns to be a real row".
    data_start = None
    for i in range(header_line_idx + 1, len(lines)):
        if "===============================================================================" in lines[i]:
            data_start = i + 1
            break

    if data_start is None:
        # Fallback: Hebrew TBESH layout. The data immediately follows the
        # header (optionally separated by an empty line). Accept the first
        # non-empty line whose tab-split column count matches the header.
        for i in range(header_line_idx + 1, len(lines)):
            candidate = lines[i].strip()
            if not candidate:
                continue
            if candidate.startswith('$'):
                continue
            # Skip stray prose '=====' markers (already handled above; if we
            # reached here they were filtered).
            cells = [c.strip() for c in candidate.split('\t')]
            if len(cells) >= len(header):
                data_start = i
                break

    if data_start is None:
        raise ValueError("Could not find data start marker in file")

    # Get data rows
    data_rows = []
    for line in lines[data_start:]:
        line = line.strip()
        if line and not line.startswith('$') and not line.startswith('======================================================='):
            # Split by tabs, handling potential inconsistencies
            row = [cell.strip() for cell in line.split('\t')]
            if len(row) >= len(header):  # Ensure we have enough columns
                data_rows.append(row)

    if not data_rows:
        raise ValueError("No data rows found in file")

    # Verify expected columns exist
    missing_columns = [col for col in expected_columns if col not in header]
    if missing_columns:
        print(f"Error: Missing expected columns: {missing_columns}", file=sys.stderr)
        print(f"Actual header: {header}", file=sys.stderr)
        raise ValueError(f"Missing columns: {missing_columns}")

    return header, data_rows


def split_definition_senses(definition):
    """Split definition into individual senses using numbered markers and semicolons."""
    if not definition:
        return []
    
    # First try to split on numbered markers (1), 2), 3), etc.)
    import re
    numbered_parts = re.split(r'\s*\d+\)\s*', definition)
    
    # If we got more than one part from numbered markers, use those
    if len(numbered_parts) > 1:
        senses = [part.strip() for part in numbered_parts if part.strip()]
    else:
        # No numbered markers found, try semicolon separation
        senses = [part.strip() for part in definition.split('; ') if part.strip()]
        
        # If only one part after semicolon split, treat as single sense
        if len(senses) == 1:
            senses = [definition.strip()]
    
    # Filter out empty senses
    senses = [sense for sense in senses if sense]
    
    return senses if senses else [definition.strip()]


def process_lexicon_data(header, data_rows, lexicon_source, conn, definition_col='Gloss'):
    """Process lexicon data and insert into database.

    For each row, split the definition into individual senses and insert
    each as a row keyed by (strongs_number, lexicon_source, sense_index).

    sense_index is the per-(strongs, lexicon) ordinal assigned across both
    senses within a single definition text (e.g. '1) ... 2) ...' splitting)
    AND across multiple rows sharing the same strongs number. The latter
    matters for TBESH, which emits one row per dStrong# sense (e.g.
    H0047G, H0047H, ...). Greek TBESG has one row per lemma with multi-
    sense splits inside the definition; Hebrew TBESH has one row per
    sense per lemma. This function unifies both into a single sequential
    sense_index per strongs number so the downstream sense_count lookup
    returns the correct value for either testament.
    """
    strongs_idx = header.index('strongs')
    definition_idx = header.index('definition')  # Always 'definition' in temp_header

    # Prepare batch insert
    batch = []
    batch_size = 1000

    # Per-(strongs_number, lexicon_source) sense counter so multi-row
    # Hebrew lemmas increment sense_index across rows instead of clobbering
    # at sense_index=1.
    per_strongs_counter = {}

    for row in data_rows:
        if not row or len(row) < max(strongs_idx, definition_idx) + 1:
            continue

        strongs_number = normalize_strongs(row[strongs_idx])
        definition = row[definition_idx]

        if not strongs_number or not definition:
            continue

        # Split definition into senses
        senses = split_definition_senses(definition)

        # Add one row per sense, sense_index increments per strongs.
        for sense in senses:
            next_idx = per_strongs_counter.get(strongs_number, 0) + 1
            per_strongs_counter[strongs_number] = next_idx
            batch.append((strongs_number, lexicon_source, next_idx, sense))

            # Execute batch when full
            if len(batch) >= batch_size:
                conn.executemany(
                    "INSERT OR REPLACE INTO lexicon_definitions "
                    "(strongs_number, lexicon_source, sense_index, definition) "
                    "VALUES (?, ?, ?, ?)",
                    batch
                )
                conn.commit()
                batch = []

    # Insert remaining rows
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO lexicon_definitions "
            "(strongs_number, lexicon_source, sense_index, definition) "
            "VALUES (?, ?, ?, ?)",
            batch
        )
        conn.commit()


def validate_ingestion(conn):
    """Validate ingestion results and return counts.

    Returns a dict keyed by lexicon_source so callers can pretty-print
    per-source counts. The malformed_strongs check permits an optional
    single lowercase trailing letter for Hebrew H047G-style sense-coded
    keys (Macula-Hebrew scheme). Greek keys remain pure integers.
    """
    # tbESG validation
    tb_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE lexicon_source='tbESG'"
    ).fetchone()[0]

    # LSJ validation
    lsj_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE lexicon_source='lsj'"
    ).fetchone()[0]

    # tbESH (Hebrew OT) validation
    tbeh_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE lexicon_source='tbESH'"
    ).fetchone()[0]

    # Union validation
    union_count = conn.execute(
        "SELECT COUNT(DISTINCT strongs_number) FROM lexicon_definitions"
    ).fetchone()[0]

    # Empty definitions validation
    empty_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE definition = '' OR definition IS NULL"
    ).fetchone()[0]

    # Format drift validation: keys must be pure integers (Greek) or
    # integer-with-optional-trailing-lowercase-letter (Hebrew, e.g. '47g').
    # Catches regressions in normalize_strongs early.
    import re
    malformed_count = 0
    samples_malformed = []
    for (s,) in conn.execute("SELECT DISTINCT strongs_number FROM lexicon_definitions"):
        if not re.match(r'^\d+[a-z]?$', s or ''):
            malformed_count += 1
            if len(samples_malformed) < 10:
                samples_malformed.append(s)

    return {
        'tbESG': tb_count,
        'lsj': lsj_count,
        'tbESH': tbeh_count,
        'union': union_count,
        'empty': empty_count,
        'malformed': malformed_count,
        'malformed_samples': samples_malformed,
    }


def main():
    parser = argparse.ArgumentParser(description='Build lexicon index from TSV files')
    parser.add_argument('--tbESG-url', default='https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt')
    parser.add_argument('--lsj-url', default='https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TFLSJ%20%200-5624%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt')
    parser.add_argument(
        '--tbESH-url',
        default='https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt',
    )
    parser.add_argument('--tbESG-path', help='Local path for TBESG file (for testing)')
    parser.add_argument('--lsj-path', help='Local path for LSJ file (for testing)')
    parser.add_argument('--tbESH-path', help='Local path for TBESH file (for testing)')
    parser.add_argument(
        '--testament',
        choices=['greek', 'hebrew', 'both'],
        default='both',
        help='Which lexicons to ingest. "greek" loads TBESG+LSJ only, '
             '"hebrew" loads TBESH only, "both" (default) loads all three. '
             'Use to keep rebuilds lean when iterating on one testament.'
    )
    parser.add_argument('--output-db', default='data/macula_index.db')
    args = parser.parse_args()

    # Notes on copyright:
    # - BDAG (Bauer-Danker-Arndt-Gingrich Greek Lexicon) is intentionally
    #   excluded — copyrighted by University of Chicago Press 2000; using
    #   public-domain STEPBible TBESG + LSJ (Liddell-Scott-Jones) instead
    #   per plan D2.
    # - TBESH is the Hebrew parallel to TBESG, also CC BY 4.0 from STEPBible.
    # - BDB / TWOT / HALOT are intentionally excluded due to copyright (BDB
    #   is public-domain but no STEPBible TSV exists for it; HALOT and TWOT
    #   are copyrighted by Brill / Hendrickson respectively).

    ingest_greek = args.testament in ('greek', 'both')
    ingest_hebrew = args.testament in ('hebrew', 'both')

    # Create database connection
    conn = sqlite3.connect(args.output_db)

    # Create table and index
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lexicon_definitions (
            strongs_number TEXT NOT NULL,
            lexicon_source TEXT NOT NULL,
            sense_index INTEGER NOT NULL,
            definition TEXT NOT NULL,
            PRIMARY KEY (strongs_number, lexicon_source, sense_index)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lex_strongs_source
        ON lexicon_definitions(strongs_number, lexicon_source)
    """)

    # Wipe before re-ingest: INSERT OR REPLACE only dedupes by PK, so without
    # this a re-run after a normalization change would leave stale rows behind
    # (e.g. old 'G0976' rows alongside new '976' rows). The lexicon TSVs are
    # the canonical source of truth and are fully re-ingested every run.
    if ingest_greek and ingest_hebrew:
        conn.execute("DELETE FROM lexicon_definitions")
    elif ingest_greek:
        conn.execute(
            "DELETE FROM lexicon_definitions WHERE lexicon_source IN ('tbESG', 'lsj')"
        )
    elif ingest_hebrew:
        conn.execute(
            "DELETE FROM lexicon_definitions WHERE lexicon_source = 'tbESH'"
        )

    def _load_local_or_url(local_path, url, timeout, label):
        if local_path:
            with open(local_path, 'r', encoding='utf-8') as f:
                return f.read()
        return download_tsv(url, timeout)

    def _process_stepbible_lexicon(content, source_tag, label):
        """Common path: parse, extract (eStrong, Gloss), insert under source_tag."""
        if not content:
            print(f"Warning: {label} download failed", file=sys.stderr)
            return
        try:
            header, data_rows = parse_tsv_content(content, ['eStrong', 'Gloss'])
            processed_rows = []
            for row in data_rows:
                if len(row) >= 2:
                    processed_rows.append([
                        row[header.index('eStrong')],
                        row[header.index('Gloss')],
                    ])
            temp_header = ['strongs', 'definition']
            process_lexicon_data(temp_header, processed_rows, source_tag, conn,
                                 definition_col='Gloss')
            print(f"{label} processing completed")
        except Exception as e:
            print(f"Error processing {label}: {e}", file=sys.stderr)
            sys.exit(1)

    # Process Greek lexicons (TBESG + LSJ)
    if ingest_greek:
        print("Processing TBESG...")
        tb_content = _load_local_or_url(args.tbESG_path, args.tbESG_url, 60, 'TBESG')
        _process_stepbible_lexicon(tb_content, 'tbESG', 'TBESG')

        print("Processing LSJ...")
        lsj_content = _load_local_or_url(args.lsj_path, args.lsj_url, 120, 'LSJ')
        if lsj_content:
            try:
                header, data_rows = parse_tsv_content(lsj_content, ['eStrong', 'Gloss'])
                processed_rows = []
                for row in data_rows:
                    if len(row) >= 2:
                        processed_rows.append([
                            row[header.index('eStrong')],
                            row[header.index('Gloss')],
                        ])
                temp_header = ['strongs', 'definition']
                process_lexicon_data(temp_header, processed_rows, 'lsj', conn,
                                     definition_col='LSJ Meaning')
                print("LSJ processing completed")
            except Exception as e:
                print(f"Warning: Error processing LSJ: {e}", file=sys.stderr)
        else:
            print("Warning: LSJ download failed, continuing with TBESG only",
                  file=sys.stderr)

    # Process Hebrew lexicon (TBESH)
    if ingest_hebrew:
        print("Processing TBESH (Hebrew)...")
        tbeh_content = _load_local_or_url(args.tbESH_path, args.tbESH_url, 120, 'TBESH')
        _process_stepbible_lexicon(tbeh_content, 'tbESH', 'TBESH')

    # Validate and print summary
    counts = validate_ingestion(conn)

    tb_count = counts['tbESG']
    lsj_count = counts['lsj']
    tbeh_count = counts['tbESH']
    union_count = counts['union']
    empty_count = counts['empty']
    malformed_count = counts['malformed']

    def _src_count(tag):
        return conn.execute(
            "SELECT COUNT(DISTINCT strongs_number) FROM lexicon_definitions "
            f"WHERE lexicon_source='{tag}'"
        ).fetchone()[0]

    print(f"\nTBESG: {tb_count} senses across {_src_count('tbESG')} Strong's numbers")
    print(f"LSJ:   {lsj_count} senses across {_src_count('lsj')} Strong's numbers")
    print(f"TBESH: {tbeh_count} senses across {_src_count('tbESH')} Strong's numbers")
    print(f"Union: {union_count} Strong's numbers")

    # Check for empty definitions
    if empty_count > 0:
        print(f"Warning: Found {empty_count} empty definitions", file=sys.stderr)

    # Fail loudly if normalization regressed. Per-testament key shape:
    #   Greek  -> pure integer          '[0-9]+'
    #   Hebrew -> integer + letter      '[0-9]+[a-z]?'
    # The regex in validate_ingestion permits both, so anything malformed
    # here is a normalize_strongs regression (the helper still strips G/H
    # prefix but must always return a numeric-with-optional-lowercase-letter).
    if malformed_count > 0:
        print(
            f"ERROR: {malformed_count} distinct strongs_number rows are not "
            f"in canonical ('<digits>' or '<digits><lowercase letter>') "
            f"format after normalization. Examples: "
            f"{counts['malformed_samples']}",
            file=sys.stderr,
        )
        sys.exit(1)

    conn.close()


if __name__ == '__main__':
    main()