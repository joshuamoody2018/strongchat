#!/usr/bin/env python3
"""
Build Macula index SQLite table from TSV data.

Ingests Macula tokens (Greek or Hebrew) into data/macula_index.db with table
macula_tokens. Idempotent script that uses INSERT OR REPLACE to handle re-runs.

The two testaments share the macula_tokens table; book_num disambiguates
(1-39 OT, 40-66 NT) and OSIS book codes are disjoint across testaments.
Use --testament to select the source TSV and the parsing/encoding scheme:
  greek  : Macula Greek SBLGNT (xml:id prefix 'n', 12 chars, 3-digit word_pos)
  hebrew : Macula Hebrew WLC   (xml:id prefix 'o', 13 chars, 4-digit word_pos)
"""

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path


BOOK_NUM_TO_OSIS_NT = {
    40: "Matt", 41: "Mark", 42: "Luke", 43: "John",
    44: "Acts", 45: "Rom",
    46: "1Cor", 47: "2Cor", 48: "Gal", 49: "Eph",
    50: "Phil", 51: "Col",
    52: "1Thess", 53: "2Thess",
    54: "1Tim", 55: "2Tim", 56: "Titus", 57: "Phlm",
    58: "Heb", 59: "Jas",
    60: "1Pet", 61: "2Pet",
    62: "1John", 63: "2John", 64: "3John", 65: "Jude", 66: "Rev",
}

# Hebrew OT book numbering follows the standard KJV Protestant ordering
# (Genesis=1 ... Malachi=39). Mirrors mappings/lowfat-macula-hebrew.xquery.
BOOK_NUM_TO_OSIS_OT = {
    1: "Gen", 2: "Exod", 3: "Lev", 4: "Num", 5: "Deut",
    6: "Josh", 7: "Judg", 8: "Ruth",
    9: "1Sam", 10: "2Sam", 11: "1Kgs", 12: "2Kgs",
    13: "1Chr", 14: "2Chr", 15: "Ezra", 16: "Neh", 17: "Esth",
    18: "Job", 19: "Ps", 20: "Prov", 21: "Eccl", 22: "Song",
    23: "Isa", 24: "Jer", 25: "Lam", 26: "Ezek", 27: "Dan",
    28: "Hos", 29: "Joel", 30: "Amos", 31: "Obad", 32: "Jonah",
    33: "Mic", 34: "Nah", 35: "Hab", 36: "Zeph",
    37: "Hag", 38: "Zech", 39: "Mal",
}

# Per-testament encoding parameters.
# Greek Macula xml:id: 'n' + 2 book + 3 chapter + 3 verse + 3 word_pos = 12 chars
# Hebrew Macula xml:id: 'o' + 2 book + 3 chapter + 3 verse + 4 word_pos = 13 chars
TESTAMENT_CONFIG = {
    'greek': {
        'prefix': 'n',
        'word_pos_slice': (9, 12),
        'xml_id_len': 12,
        'book_map': BOOK_NUM_TO_OSIS_NT,
        'expected_books': 27,
        'book_num_range': range(40, 67),
        'anchor_book': 'John',
        'anchor_chapter': 3,
        'anchor_verse': 16,
        'anchor_min_tokens': 25,
    },
    'hebrew': {
        'prefix': 'o',
        'word_pos_slice': (9, 13),
        'xml_id_len': 13,
        'book_map': BOOK_NUM_TO_OSIS_OT,
        'expected_books': 39,
        'book_num_range': range(1, 40),
        'anchor_book': 'Gen',
        'anchor_chapter': 1,
        'anchor_verse': 1,
        'anchor_min_tokens': 5,
    },
}


def parse_xml_id(xml_id):
    """Parse Greek (SBLGNT) xml:id into components: book_num, chapter, verse, word_pos.

    Args:
        xml_id (str): Macula Greek xml:id format (e.g., "n40001001001")

    Returns:
        tuple: (book_num, chapter, verse, word_pos)
    """
    if not xml_id.startswith('n'):
        raise ValueError(f"Greek xml_id must start with 'n': {xml_id}")

    book_num = int(xml_id[1:3])
    chapter = int(xml_id[3:6])
    verse = int(xml_id[6:9])
    word_pos = int(xml_id[9:12])

    return book_num, chapter, verse, word_pos


def parse_xml_id_hebrew(xml_id):
    """Parse Hebrew (WLC) xml:id into components: book_num, chapter, verse, word_pos.

    Macula Hebrew xml:id format:
        'o' + 2-digit book (1..39) + 3-digit chapter + 3-digit verse +
        4-digit word_slot = 13 chars total.

    Word_slot is a morphological slot encoding (values like 0011, 0012, 0021)
    not a strict 1-based position; treated opaque here as an int.

    Args:
        xml_id (str): e.g. "o010010010011" for Gen 1:1 word 11

    Returns:
        tuple: (book_num, chapter, verse, word_pos)
    """
    if not xml_id.startswith('o'):
        raise ValueError(f"Hebrew xml_id must start with 'o': {xml_id}")
    if len(xml_id) != 13:
        raise ValueError(
            f"Hebrew xml_id must be 13 chars (o+2+3+3+4): {xml_id!r} "
            f"(len={len(xml_id)})"
        )
    book_num = int(xml_id[1:3])
    chapter = int(xml_id[3:6])
    verse = int(xml_id[6:9])
    word_pos = int(xml_id[9:13])
    return book_num, chapter, verse, word_pos


def get_book_osis(book_num):
    """Get OSIS code from book number using BOOK_NUM_TO_OSIS_NT mapping.

    Args:
        book_num (int): Book number (40-66 for NT)

    Returns:
        str: OSIS code (e.g., "Matt", "1John")

    Raises:
        ValueError: If book_num is not in the mapping
    """
    if book_num not in BOOK_NUM_TO_OSIS_NT:
        raise ValueError(f"Book number {book_num} not found in BOOK_NUM_TO_OSIS_NT mapping")

    return BOOK_NUM_TO_OSIS_NT[book_num]


def get_book_osis_hebrew(book_num):
    """Get OSIS code from Hebrew book number (1-39).

    Args:
        book_num (int): Book number 1-39 (OT)

    Returns:
        str: OSIS code (e.g., "Gen", "Ps", "Isa")

    Raises:
        ValueError: If book_num is not in the OT mapping.
    """
    if book_num not in BOOK_NUM_TO_OSIS_OT:
        raise ValueError(f"Book number {book_num} not found in BOOK_NUM_TO_OSIS_OT mapping")
    return BOOK_NUM_TO_OSIS_OT[book_num]


def _parse_xml_id_for_testament(xml_id, testament):
    """Dispatch xml:id parsing by testament."""
    if testament == 'hebrew':
        return parse_xml_id_hebrew(xml_id)
    return parse_xml_id(xml_id)


def _get_book_osis_for_testament(book_num, testament):
    """Dispatch book-num→OSIS lookup by testament."""
    if testament == 'hebrew':
        return get_book_osis_hebrew(book_num)
    return get_book_osis(book_num)


def main():
    parser = argparse.ArgumentParser(description="Build Macula index SQLite table")
    parser.add_argument(
        "--macula-tsv",
        default=None,
        help="Path to Macula TSV file. If omitted, defaults to "
             "data/macula/macula-greek.tsv (greek) or "
             "data/macula/macula-hebrew.tsv (hebrew)."
    )
    parser.add_argument(
        "--output-db",
        default="data/macula_index.db",
        help="Path to output SQLite database"
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to manifest JSON file. If omitted, defaults to "
             "data/macula/manifest.json (greek) or "
             "data/macula/hebrew-manifest.json (hebrew)."
    )
    parser.add_argument(
        "--testament",
        choices=['greek', 'hebrew'],
        default='greek',
        help="Testament of the source TSV (default: greek)."
    )
    args = parser.parse_args()

    cfg = TESTAMENT_CONFIG[args.testament]

    if args.macula_tsv is None:
        args.macula_tsv = (
            'data/macula/macula-hebrew.tsv'
            if args.testament == 'hebrew'
            else 'data/macula/macula-greek.tsv'
        )
    if args.manifest is None:
        args.manifest = (
            'data/macula/hebrew-manifest.json'
            if args.testament == 'hebrew'
            else 'data/macula/manifest.json'
        )
    
    # Load manifest
    try:
        with open(args.manifest, 'r') as f:
            manifest = json.load(f)
        manifest_tokens = manifest['tokens']
        print(f"Manifest: {manifest_tokens} tokens, {manifest['books']} books")
    except FileNotFoundError:
        print(f"Error: Manifest file not found: {args.manifest}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in manifest file: {args.manifest}")
        sys.exit(1)
    except KeyError:
        print(f"Error: Manifest missing 'tokens' field: {args.manifest}")
        sys.exit(1)
    
    # Check if all book numbers in the mapping are covered
    expected_book_nums = set(cfg['book_num_range'])
    mapped_book_nums = set(cfg['book_map'].keys())
    unmapped = expected_book_nums - mapped_book_nums
    if unmapped:
        print(f"Error: Missing mappings for book numbers: {sorted(unmapped)}")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    Path(args.output_db).parent.mkdir(parents=True, exist_ok=True)
    
    # Connect to database
    conn = sqlite3.connect(args.output_db)
    cursor = conn.cursor()
    
    # Check if table exists and get its columns
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='macula_tokens'")
    table_exists = cursor.fetchone()
    
    if table_exists:
        # Table exists - check if it has the gloss column
        existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(macula_tokens)").fetchall()]
        if 'gloss' not in existing_cols:
            print("Existing schema missing gloss column - adding it and rebuilding from TSV...")
            cursor.execute("ALTER TABLE macula_tokens ADD COLUMN gloss TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_macula_ref ON macula_tokens(book_osis, chapter, verse)")
            conn.commit()
            # Re-populate the gloss column by reading the canonical TSV.
            # The TSV is the source of truth; rebuild from it.
            cursor.execute("DELETE FROM macula_tokens")
            conn.commit()
        else:
            print("Table exists with gloss column - proceeding with normal ingestion")
    else:
        print("No existing table - creating fresh schema")
    
    # Create table (will be no-op if table already exists)
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS macula_tokens (
        row_id TEXT PRIMARY KEY,
        book_num INTEGER NOT NULL,
        book_osis TEXT NOT NULL,
        chapter INTEGER NOT NULL,
        verse INTEGER NOT NULL,
        word_pos INTEGER NOT NULL,
        surface TEXT,
        lemma TEXT,
        strongs TEXT,
        morph TEXT,
        pos TEXT,
        gloss TEXT
    );
    """
    cursor.execute(create_table_sql)
    
    create_index_sql = """
    CREATE INDEX IF NOT EXISTS idx_macula_ref ON macula_tokens(book_osis, chapter, verse);
    """
    cursor.execute(create_index_sql)

    # If re-ingesting the same testament, wipe existing rows for that
    # testament first to keep the table idempotent across re-runs. We use
    # book_num range as the per-testament partition key (1-39 OT, 40-66 NT).
    if args.testament == 'hebrew':
        cursor.execute("DELETE FROM macula_tokens WHERE book_num < 40")
    else:
        cursor.execute("DELETE FROM macula_tokens WHERE book_num >= 40")
    conn.commit()
    print(f"Cleared existing {args.testament} rows before re-ingest")
    
    # Read TSV file
    try:
        with open(args.macula_tsv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            
            # Validate header
            expected_columns = ['xml:id', 'ref', 'text', 'lemma', 'strongnumberx', 'morph', 'pos', 'gloss']
            actual_columns = reader.fieldnames
            if actual_columns != expected_columns:
                print(f"Error: Header mismatch. Expected: {expected_columns}, Got: {actual_columns}")
                sys.exit(1)
            
            # Process rows
            rows = []
            total_rows = 0
            for row_num, row in enumerate(reader, 1):
                try:
                    # Parse xml:id using the testament-specific parser
                    xml_id = row['xml:id']
                    book_num, chapter, verse, word_pos = _parse_xml_id_for_testament(
                        xml_id, args.testament
                    )
                    book_osis = _get_book_osis_for_testament(book_num, args.testament)
                    
                    # Build tuple for INSERT
                    row_tuple = (
                        xml_id,  # row_id
                        book_num,
                        book_osis,
                        chapter,
                        verse,
                        word_pos,
                        row['text'],  # surface
                        row['lemma'],
                        row['strongnumberx'],  # strongs
                        row['morph'],
                        row['pos'],
                        row['gloss']  # gloss
                    )
                    rows.append(row_tuple)
                    total_rows += 1
                    
                    # Progress reporting
                    if total_rows % 25000 == 0:
                        print(f"Ingested {total_rows}/{manifest_tokens} rows...")
                
                except ValueError as e:
                    print(f"Error parsing row {row_num} (xml_id={row['xml:id']}): {e}")
                    sys.exit(1)
                except Exception as e:
                    print(f"Error processing row {row_num}: {e}")
                    sys.exit(1)
            
            print(f"Total rows to ingest: {total_rows}")
            
            # Insert in chunks with executemany
            chunk_size = 5000
            for i in range(0, len(rows), chunk_size):
                chunk = rows[i:i + chunk_size]
                insert_sql = """
                INSERT OR REPLACE INTO macula_tokens 
                (row_id, book_num, book_osis, chapter, verse, word_pos, surface, lemma, strongs, morph, pos, gloss)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                cursor.executemany(insert_sql, chunk)
                print(f"Inserted chunk {i//chunk_size + 1}: {len(chunk)} rows")
            
            # Commit transaction
            conn.commit()
            print("Transaction committed")
            
    except FileNotFoundError:
        print(f"Error: TSV file not found: {args.macula_tsv}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading TSV file: {e}")
        conn.rollback()
        sys.exit(1)
    
    # Validation queries
    print("\nRunning validation queries...")
    
    # Count total rows for THIS testament only
    if args.testament == 'hebrew':
        count_sql = "SELECT COUNT(*) FROM macula_tokens WHERE book_num < 40"
        distinct_books_sql = "SELECT COUNT(DISTINCT book_osis) FROM macula_tokens WHERE book_num < 40"
        anchor_sql = (
            "SELECT COUNT(*) FROM macula_tokens WHERE book_osis=? AND chapter=? AND verse=?"
        )
    else:
        count_sql = "SELECT COUNT(*) FROM macula_tokens WHERE book_num >= 40"
        distinct_books_sql = "SELECT COUNT(DISTINCT book_osis) FROM macula_tokens WHERE book_num >= 40"
        anchor_sql = (
            "SELECT COUNT(*) FROM macula_tokens WHERE book_osis=? AND chapter=? AND verse=?"
        )
    count_result = cursor.execute(count_sql).fetchone()
    total_count = count_result[0]
    print(f"Total {args.testament} rows in database: {total_count}")
    
    # Verify count matches manifest (for this testament)
    if total_count != manifest_tokens:
        print(f"ERROR: Row count mismatch! Expected: {manifest_tokens}, Got: {total_count}")
        conn.close()
        sys.exit(1)
    
    # Check for empty lemma or strongs (should be < 5%)
    empty_fields_result = cursor.execute(
        "SELECT COUNT(*) FROM macula_tokens WHERE lemma = '' OR strongs = ''"
        + (" AND book_num < 40" if args.testament == 'hebrew' else " AND book_num >= 40")
    ).fetchone()
    empty_fields_count = empty_fields_result[0]
    print(f"Rows with empty lemma or strongs: {empty_fields_count}")
    
    if empty_fields_count >= 0.05 * manifest_tokens:
        print(f"WARNING: Too many rows with empty fields: {empty_fields_count}/{manifest_tokens} ({empty_fields_count/manifest_tokens:.1%})")
    
    # Count distinct books for this testament
    distinct_books_result = cursor.execute(distinct_books_sql).fetchone()
    distinct_books_count = distinct_books_result[0]
    print(f"Distinct {args.testament} books: {distinct_books_count}")

    # Pass when the actual count matches the manifest's promise; this keeps
    # the check meaningful for production full-corpus ingests (manifest books
    # == 27 for Greek, 39 for Hebrew) while letting small synthetic fixtures
    # (manifest books < expected) succeed in tests.
    manifest_books = manifest.get('books', cfg['expected_books'])
    if distinct_books_count != manifest_books:
        print(
            f"ERROR: Manifest promised {manifest_books} distinct "
            f"{args.testament} books, got {distinct_books_count}"
        )
        conn.close()
        sys.exit(1)
    # Additional sanity check: when the manifest matches full corpus size,
    # also verify against the canonically expected book count.
    if manifest_books == cfg['expected_books'] and distinct_books_count != cfg['expected_books']:
        print(
            f"WARNING: distinct {args.testament} books ({distinct_books_count}) "
            f"!= canonical expected ({cfg['expected_books']})"
        )
    
    # Anchor verse spot check
    anchor_count = cursor.execute(
        anchor_sql,
        (cfg['anchor_book'], cfg['anchor_chapter'], cfg['anchor_verse']),
    ).fetchone()[0]
    print(f"{cfg['anchor_book']} {cfg['anchor_chapter']}:{cfg['anchor_verse']} token count: {anchor_count}")
    if anchor_count < cfg['anchor_min_tokens']:
        print(f"WARNING: {cfg['anchor_book']} {cfg['anchor_chapter']}:{cfg['anchor_verse']} has only {anchor_count} tokens (expected >= {cfg['anchor_min_tokens']})")
    
    # Print summary
    print(f"\nSummary: Ingested {total_count} {args.testament} rows across {distinct_books_count} books into {args.output_db}")
    
    # Close connection
    conn.close()
    
    print("Script completed successfully!")


if __name__ == "__main__":
    main()