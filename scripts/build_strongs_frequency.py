#!/usr/bin/env python3
"""
Strong's frequency aggregation script.

Aggregates Strong's number frequencies from the macula_tokens table and writes
the strongs_frequency table in the same SQLite database. Idempotent.

Supports both testaments. Use --testament to select the source partition:
  greek  : aggregates rows with book_num >= 40, writes testament='NT'
  hebrew : aggregates rows with book_num < 40, writes testament='OT'
"""

import argparse
import collections
import sqlite3
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate Strong's number frequencies from Macula tokens"
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
    parser.add_argument(
        "--testament",
        choices=['greek', 'hebrew'],
        default='greek',
        help="Testament to aggregate: greek (book_num>=40, writes 'NT') "
             "or hebrew (book_num<40, writes 'OT'). Default: greek."
    )

    args = parser.parse_args()

    # Resolve per-testament parameters
    if args.testament == 'hebrew':
        book_filter = "book_num < 40"
        testament_value = 'OT'
    else:
        book_filter = "book_num >= 40"
        testament_value = 'NT'

    # Convert to absolute paths
    macula_db = Path(args.macula_db).resolve()
    output_db = Path(args.output_db).resolve()

    print(f"Reading from: {macula_db}")
    print(f"Writing to: {output_db}")
    print(f"Testament: {args.testament} (entries written as {testament_value!r})")

    # Connect to the output database
    conn = sqlite3.connect(output_db)
    conn.execute("PRAGMA foreign_keys = ON")

    # Create the strongs_frequency table with composite PK so cross-testament
    # bare-int keys (e.g. Greek G1 vs Hebrew H1, both normalised to '1') do
    # not overwrite each other on INSERT OR REPLACE. The original NT-only
    # schema used strongs_number as the sole PK, which was fine when there
    # was only one testament but becomes a correctness bug with two.
    # We auto-migrate any pre-existing single-PK table by dropping and
    # recreating; lossless since the canonical source is macula_tokens,
    # which we re-aggregate below.
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS strongs_frequency (
        strongs_number TEXT NOT NULL,
        occurrence_count INTEGER NOT NULL,
        testament TEXT NOT NULL,
        PRIMARY KEY (strongs_number, testament)
    );
    """
    # Detect the legacy single-PK schema and migrate transparently.
    existing_pk = conn.execute(
        "SELECT name FROM pragma_table_info('strongs_frequency') "
        "WHERE pk > 0 ORDER BY pk"
    ).fetchall() if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strongs_frequency'"
    ).fetchone() else []
    if existing_pk and len(existing_pk) == 1:
        print("Existing strongs_frequency table uses legacy single-PK schema; "
              "dropping and recreating with composite PK (strongs_number, testament)")
        conn.execute("DROP TABLE strongs_frequency")
    conn.execute(create_table_sql)

    # Wipe any existing rows for this testament (idempotent re-runs).
    # The PRIMARY KEY is strongs_number alone; Greek and Hebrew bare-int
    # keys overlap (G1 vs H1 both normalize to '1'), so DELETE-by-testament
    # is mandatory to avoid one testament overwriting the other on re-run.
    conn.execute(
        "DELETE FROM strongs_frequency WHERE testament = ?",
        (testament_value,),
    )
    conn.commit()
    print(f"Cleared existing {testament_value} rows before re-aggregation")

    # Aggregate Strong's frequencies for this testament only
    print("Aggregating Strong's numbers...")
    start_time = time.time()

    query = (
        f"SELECT strongs, COUNT(*) FROM macula_tokens "
        f"WHERE strongs != '' AND {book_filter} GROUP BY strongs"
    )
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
                "INSERT OR REPLACE INTO strongs_frequency "
                "(strongs_number, occurrence_count, testament) "
                "VALUES (?, ?, ?)",
                (strongs_number, occurrence_count, testament_value)
            )

        # Print progress if it took more than 5 seconds
        elapsed = time.time() - start_time
        if elapsed > 5:
            print(f"Aggregated {len(frequency_counter)} Strong's "
                  f"numbers in {elapsed:.1f} seconds...")

    # Validation queries
    print("\nRunning validation checks...")

    # Check unique count and total tokens for THIS testament
    unique_count = conn.execute(
        "SELECT COUNT(*) FROM strongs_frequency WHERE testament = ?",
        (testament_value,),
    ).fetchone()[0]
    total_tokens_row = conn.execute(
        "SELECT SUM(occurrence_count) FROM strongs_frequency WHERE testament = ?",
        (testament_value,),
    ).fetchone()
    total_tokens = total_tokens_row[0] if total_tokens_row[0] is not None else 0

    print(f"Unique Strong's numbers ({testament_value}): {unique_count}")
    print(f"Total tokens aggregated ({testament_value}): {total_tokens}")

    # Check frequency statistics for this testament
    stats = conn.execute(
        "SELECT MAX(occurrence_count), MIN(occurrence_count), AVG(occurrence_count) "
        "FROM strongs_frequency WHERE testament = ?",
        (testament_value,),
    ).fetchone()

    max_count, min_count, avg_count = stats
    avg_display = f"{avg_count:.1f}" if avg_count else "0"
    print(f"Frequency statistics ({testament_value}): "
          f"MAX={max_count}, MIN={min_count}, AVG={avg_display}")

    # Note cross-testament key overlap (informational, not an error).
    # Greek G1 and Hebrew H1 both normalize to bare int '1', so this is
    # expected and acceptable — ContextRetrievalService._fetch_freq_map
    # filters by testament, so the two rows are never confused at query
    # time. We surface the count so a silent normalization regression is
    # visible from the script output.
    other = 'NT' if testament_value == 'OT' else 'OT'
    overlap_count = conn.execute(
        "SELECT COUNT(*) FROM strongs_frequency "
        "WHERE testament = ? AND strongs_number IN "
        "(SELECT strongs_number FROM strongs_frequency WHERE testament = ?)",
        (testament_value, other),
    ).fetchone()[0]
    print(f"Cross-testament strongs-key overlap (informational): {overlap_count}")

    # Final summary
    print(f"\nStrong's frequency ({testament_value}): "
          f"{unique_count} unique numbers, {total_tokens} tokens")

    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()