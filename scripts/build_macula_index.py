#!/usr/bin/env python3
"""
Build Macula Greek index SQLite table from TSV data.

Ingests data/macula/macula-greek.tsv into data/macula_index.db with table
macula_tokens. Idempotent script that uses INSERT OR REPLACE to handle re-runs.
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


def parse_xml_id(xml_id):
    """Parse xml:id into components: book_num, chapter, verse, word_pos.
    
    Args:
        xml_id (str): Macula xml:id format (e.g., "n40001001001")
        
    Returns:
        tuple: (book_num, chapter, verse, word_pos)
    """
    if not xml_id.startswith('n'):
        raise ValueError(f"xml_id must start with 'n': {xml_id}")
    
    book_num = int(xml_id[1:3])
    chapter = int(xml_id[3:6])
    verse = int(xml_id[6:9])
    word_pos = int(xml_id[9:12])
    
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


def main():
    parser = argparse.ArgumentParser(description="Build Macula Greek index SQLite table")
    parser.add_argument(
        "--macula-tsv",
        default="data/macula/macula-greek.tsv",
        help="Path to Macula Greek TSV file"
    )
    parser.add_argument(
        "--output-db",
        default="data/macula_index.db",
        help="Path to output SQLite database"
    )
    parser.add_argument(
        "--manifest",
        default="data/macula/manifest.json",
        help="Path to manifest JSON file"
    )
    
    args = parser.parse_args()
    
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
    expected_book_nums = set(range(40, 67))  # 40-66 inclusive (27 books)
    mapped_book_nums = set(BOOK_NUM_TO_OSIS_NT.keys())
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
                    # Parse xml:id
                    xml_id = row['xml:id']
                    book_num, chapter, verse, word_pos = parse_xml_id(xml_id)
                    book_osis = get_book_osis(book_num)
                    
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
    
    # Count total rows
    count_result = cursor.execute("SELECT COUNT(*) FROM macula_tokens").fetchone()
    total_count = count_result[0]
    print(f"Total rows in database: {total_count}")
    
    # Verify count matches manifest
    if total_count != manifest_tokens:
        print(f"ERROR: Row count mismatch! Expected: {manifest_tokens}, Got: {total_count}")
        conn.close()
        sys.exit(1)
    
    # Check for empty lemma or strongs (should be < 5%)
    empty_fields_result = cursor.execute(
        "SELECT COUNT(*) FROM macula_tokens WHERE lemma = '' OR strongs = ''"
    ).fetchone()
    empty_fields_count = empty_fields_result[0]
    print(f"Rows with empty lemma or strongs: {empty_fields_count}")
    
    if empty_fields_count >= 0.05 * manifest_tokens:
        print(f"WARNING: Too many rows with empty fields: {empty_fields_count}/{manifest_tokens} ({empty_fields_count/manifest_tokens:.1%})")
    
    # Count distinct books
    distinct_books_result = cursor.execute("SELECT COUNT(DISTINCT book_osis) FROM macula_tokens").fetchone()
    distinct_books_count = distinct_books_result[0]
    print(f"Distinct books: {distinct_books_count}")
    
    if distinct_books_count != 27:
        print(f"ERROR: Expected 27 distinct books, got {distinct_books_count}")
        conn.close()
        sys.exit(1)
    
    # Check John 3:16 (should have >= 25 tokens)
    john_3_16_result = cursor.execute(
        "SELECT COUNT(*) FROM macula_tokens WHERE book_osis='John' AND chapter=3 AND verse=16"
    ).fetchone()
    john_3_16_count = john_3_16_result[0]
    print(f"John 3:16 token count: {john_3_16_count}")
    
    if john_3_16_count < 25:
        print(f"WARNING: John 3:16 has only {john_3_16_count} tokens (expected >= 25)")
    
    # Print summary
    print(f"\nSummary: Ingested {total_count} rows across {distinct_books_count} books into {args.output_db}")
    
    # Close connection
    conn.close()
    
    print("Script completed successfully!")


if __name__ == "__main__":
    main()