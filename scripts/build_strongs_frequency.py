#!/usr/bin/env python3
"""
Strong's frequency aggregation script.

Aggregates Strong's number frequencies from the macula_tokens table and writes
the strongs_frequency table in the same SQLite database. NT-only, idempotent.
"""

import argparse
import collections
import sqlite3
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate Strong's number frequencies from Macula Greek tokens"
    )
    parser.add_argument(
        "--macula-db",
        default="data/macula_index.db",
        help="Path to Macula SQLite database (default: data/macula_index.db)"
    )
    parser.add_argument(
        "--output-db", 
        default="data/macula_index.db",
        help="Path to output SQLite database (default: data/macula_index.db)"
    )
    
    args = parser.parse_args()
    
    # Convert to absolute paths
    macula_db = Path(args.macula_db).resolve()
    output_db = Path(args.output_db).resolve()
    
    print(f"Reading from: {macula_db}")
    print(f"Writing to: {output_db}")
    
    # Connect to the output database
    conn = sqlite3.connect(output_db)
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Create the strongs_frequency table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS strongs_frequency (
        strongs_number TEXT PRIMARY KEY,
        occurrence_count INTEGER NOT NULL,
        testament TEXT NOT NULL
    );
    """
    conn.execute(create_table_sql)
    
    # Aggregate Strong's frequencies
    print("Aggregating Strong's numbers...")
    start_time = time.time()
    
    query = "SELECT strongs, COUNT(*) FROM macula_tokens WHERE strongs != '' GROUP BY strongs"
    cursor = conn.execute(query)
    
    # Use Counter for deduplication (defensive - SQL GROUP BY already dedupes)
    frequency_counter = collections.Counter()
    for strongs, count in cursor:
        frequency_counter[strongs] = count
    
    # Insert or replace in a single transaction
    with conn:
        print(f"Inserting {len(frequency_counter)} unique Strong's numbers...")
        
        for strongs_number, occurrence_count in frequency_counter.items():
            conn.execute(
                "INSERT OR REPLACE INTO strongs_frequency (strongs_number, occurrence_count, testament) VALUES (?, ?, 'NT')",
                (strongs_number, occurrence_count)
            )
        
        # Print progress if it took more than 5 seconds
        elapsed = time.time() - start_time
        if elapsed > 5:
            print(f"Aggregated {len(frequency_counter)} Strong's numbers in {elapsed:.1f} seconds...")
    
    # Validation queries
    print("\nRunning validation checks...")
    
    # Check unique count and total tokens
    unique_count = conn.execute("SELECT COUNT(*) FROM strongs_frequency").fetchone()[0]
    total_tokens = conn.execute("SELECT SUM(occurrence_count) FROM strongs_frequency").fetchone()[0]
    
    print(f"Unique Strong's numbers: {unique_count}")
    print(f"Total tokens aggregated: {total_tokens}")
    
    # Check frequency statistics
    stats = conn.execute("""
        SELECT MAX(occurrence_count), MIN(occurrence_count), AVG(occurrence_count) 
        FROM strongs_frequency
    """).fetchone()
    
    max_count, min_count, avg_count = stats
    print(f"Frequency statistics: MAX={max_count}, MIN={min_count}, AVG={avg_count:.1f}")
    
    # Verify all testament values are 'NT'
    testament_check = conn.execute("SELECT DISTINCT testament FROM strongs_frequency").fetchall()
    if all(t[0] == 'NT' for t in testament_check):
        print("✓ All testament values are 'NT'")
    else:
        print("✗ Found non-NT testament values!")
        for t in testament_check:
            if t[0] != 'NT':
                print(f"  Found: {t[0]}")
        sys.exit(1)
    
    # Final summary
    print(f"\nStrong's frequency: {unique_count} unique numbers, {total_tokens} tokens")
    
    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()