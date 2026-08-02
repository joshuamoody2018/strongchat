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
    """Parse TSV content and return header and rows."""
    lines = content.split('\n')
    
    # Find the header row (starts with "eStrong	dStrong	uStrong	Greek...")
    header_line_idx = None
    for i, line in enumerate(lines):
        if line.startswith('eStrong	dStrong	uStrong	Greek'):
            header_line_idx = i
            break
    
    if header_line_idx is None:
        # Try alternative header detection
        for i, line in enumerate(lines):
            if 'eStrong' in line and 'dStrong' in line and 'uStrong' in line:
                header_line_idx = i
                break
    
    if header_line_idx is None:
        raise ValueError("Could not find header row starting with 'eStrong	dStrong	uStrong	Greek'")
    
    # Get header line
    header = lines[header_line_idx].strip().split('\t')
    print(f"Parsed header: {header}")
    
    # Find the start of data (after "===============================================================================")
    data_start = None
    for i in range(header_line_idx + 1, len(lines)):
        if "===============================================================================" in lines[i]:
            data_start = i + 1
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
    """Process lexicon data and insert into database."""
    strongs_idx = header.index('strongs')
    definition_idx = header.index('definition')  # Always use 'definition' as the column name in temp_header
    
    # Prepare batch insert
    batch = []
    batch_size = 1000
    
    for row in data_rows:
        if not row or len(row) < max(strongs_idx, definition_idx) + 1:
            continue
        
        strongs_number = row[strongs_idx]
        definition = row[definition_idx]
        
        if not strongs_number or not definition:
            continue
        
        # Split definition into senses
        senses = split_definition_senses(definition)
        
        # Add one row per sense
        for sense_idx, sense in enumerate(senses, 1):
            batch.append((strongs_number, lexicon_source, sense_idx, sense))
            
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
    """Validate ingestion results and return counts."""
    # tbESG validation
    tb_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE lexicon_source='tbESG'"
    ).fetchone()[0]
    
    # LSJ validation
    lsj_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE lexicon_source='lsj'"
    ).fetchone()[0]
    
    # Union validation
    union_count = conn.execute(
        "SELECT COUNT(DISTINCT strongs_number) FROM lexicon_definitions"
    ).fetchone()[0]
    
    # Empty definitions validation
    empty_count = conn.execute(
        "SELECT COUNT(*) FROM lexicon_definitions WHERE definition = '' OR definition IS NULL"
    ).fetchone()[0]
    
    return tb_count, lsj_count, union_count, empty_count


def main():
    parser = argparse.ArgumentParser(description='Build lexicon index from TSV files')
    parser.add_argument('--tbESG-url', default='https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt')
    parser.add_argument('--lsj-url', default='https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/TFLSJ%20%200-5624%20-%20Translators%20Formatted%20full%20LSJ%20Bible%20lexicon%20-%20STEPBible.org%20CC%20BY.txt')
    parser.add_argument('--tbESG-path', help='Local path for TBESG file (for testing)')
    parser.add_argument('--output-db', default='data/macula_index.db')
    args = parser.parse_args()
    
    # Note: BDAG (Bauer-Danker-Arndt-Gingrich Greek Lexicon) is intentionally excluded — copyrighted by UChicago Press 2000; using public-domain STEPBible TBESG + LSJ (Liddell-Scott-Jones) instead per plan D2.
    
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
    
    # Process TBESG
    print("Processing TBESG...")
    if args.tbESG_path:
        # Use local file for testing
        with open(args.tbESG_path, 'r', encoding='utf-8') as f:
            tb_content = f.read()
    else:
        # Download from URL
        tb_content = download_tsv(args.tbESG_url, 60)
    
    if tb_content:
        try:
            header, data_rows = parse_tsv_content(tb_content, ['eStrong', 'Gloss'])
            print(f"TBESG header: {header}")
            print(f"TBESG data rows count: {len(data_rows)}")
            if data_rows:
                print(f"First data row: {data_rows[0]}")
            # Map column names to expected names
            processed_rows = []
            for row in data_rows:
                if len(row) >= 2:
                    processed_rows.append([
                        row[header.index('eStrong')],  # strongs_number
                        row[header.index('Gloss')]     # definition
                    ])
            print(f"Processed rows count: {len(processed_rows)}")
            # Create a temporary header for processing
            temp_header = ['strongs', 'definition']
            process_lexicon_data(temp_header, processed_rows, 'tbESG', conn, definition_col='Gloss')
            print("TBESG processing completed")
        except Exception as e:
            print(f"Error processing TBESG: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Error: TBESG download failed", file=sys.stderr)
        sys.exit(1)
    
    # Process LSJ
    print("Processing LSJ...")
    lsj_content = download_tsv(args.lsj_url, 120)
    if lsj_content:
        try:
            header, data_rows = parse_tsv_content(lsj_content, ['eStrong', 'Gloss'])
            # Map column names to expected names
            processed_rows = []
            for row in data_rows:
                if len(row) >= 2:
                    processed_rows.append([
                        row[header.index('eStrong')],  # strongs_number
                        row[header.index('Gloss')]     # definition
                    ])
            # Create a temporary header for processing
            temp_header = ['strongs', 'definition']
            process_lexicon_data(temp_header, processed_rows, 'lsj', conn, definition_col='LSJ Meaning')
            print("LSJ processing completed")
        except Exception as e:
            print(f"Warning: Error processing LSJ: {e}", file=sys.stderr)
    else:
        print("Warning: LSJ download failed, continuing with TBESG only", file=sys.stderr)
    
    # Validate and print summary
    tb_count, lsj_count, union_count, empty_count = validate_ingestion(conn)
    
    print(f"\nTBESG: {tb_count} senses across {conn.execute('SELECT COUNT(DISTINCT strongs_number) FROM lexicon_definitions WHERE lexicon_source=\'tbESG\'').fetchone()[0]} Strong's numbers")
    print(f"LSJ: {lsj_count} senses across {conn.execute('SELECT COUNT(DISTINCT strongs_number) FROM lexicon_definitions WHERE lexicon_source=\'lsj\'').fetchone()[0]} Strong's numbers")
    print(f"Union: {union_count} Strong's numbers")
    
    # Check for empty definitions
    if empty_count > 0:
        print(f"Warning: Found {empty_count} empty definitions", file=sys.stderr)
    
    conn.close()


if __name__ == '__main__':
    main()