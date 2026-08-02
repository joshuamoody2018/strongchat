#!/usr/bin/env python3
"""Download and validate Macula Greek tokens.

Downloads Macula Greek tokens from the upstream Clear-Bible/macula-greek
repository (SBLGNT edition), validates the schema and shape, and writes
a manifest.json.

Source: https://raw.githubusercontent.com/Clear-Bible/macula-greek/main/SBLGNT/tsv/macula-greek-SBLGNT.tsv
License: CC BY 4.0
Canonical TSV columns: xml:id, ref, text, lemma, strongnumberx, morph, pos, gloss

Exit codes:
    0 - success
    1 - command-line or I/O error
    2 - download failed
    3 - validation failed
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# Macula Greek TSV source URL
MACULA_GREEK_TSV_URL = "https://raw.githubusercontent.com/Clear-Bible/macula-greek/main/SBLGNT/tsv/macula-greek-SBLGNT.tsv"

# Required columns in the canonical TSV
REQUIRED_COLUMNS = {"xml:id", "ref", "text", "lemma", "strongnumberx", "morph", "pos", "gloss"}

# Canonical field order for output
CANONICAL_FIELDS = ("xml:id", "ref", "text", "lemma", "strongnumberx", "morph", "pos", "gloss")

# SBLGNT-to-OSIS book code mapping
SBLGNT_TO_OSIS = {
    "MAT": "Matt",
    "MRK": "Mark", 
    "LUK": "Luke",
    "JHN": "John",
    "ACT": "Acts",
    "ROM": "Rom",
    "1CO": "1Cor",
    "2CO": "2Cor",
    "GAL": "Gal",
    "EPH": "Eph",
    "PHP": "Phil",
    "COL": "Col",
    "1TH": "1Thess",
    "2TH": "2Thess",
    "1TI": "1Tim",
    "2TI": "2Tim",
    "TIT": "Titus",
    "PHM": "Phlm",
    "HEB": "Heb",
    "JAS": "Jas",
    "1PE": "1Pet",
    "2PE": "2Pet",
    "1JN": "1John",
    "2JN": "2John",
    "3JN": "3John",
    "JUD": "Jude",
    "REV": "Rev"
}

# Validation constants
MIN_TOKENS = 100_000
MAX_TOKENS = 200_000
EXPECTED_BOOKS = 27


def _download_file(url: str, dest: Path, label: str) -> None:
    """Download a file with timeout and error handling."""
    try:
        resp = requests.get(url, timeout=180)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"{label}: download failed from {url}: {exc}") from exc

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            fh.write(resp.content)
    except OSError as exc:
        raise RuntimeError(f"{label}: failed writing {dest}: {exc}") from exc


def _transform_row(row: dict[str, str]) -> dict[str, str]:
    """Transform a row from the upstream schema to the canonical schema."""
    # Convert SBLGNT ref to OSIS format
    raw_ref = row["ref"]
    parts = raw_ref.split(None, 1)
    sblgnt_book = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    osis_book = SBLGNT_TO_OSIS.get(sblgnt_book, sblgnt_book)
    ref_canonical = f"{osis_book} {rest}".strip()
    
    return {
        "xml:id": row["xml:id"],
        "ref": ref_canonical,
        "text": row["text"],
        "lemma": row["lemma"],
        "strongnumberx": row["strong"],
        "morph": row["morph"],
        "pos": (row["morph"].split("-")[0] + "-") if row["morph"] else "",
        "gloss": row["gloss"],
    }


def _validate_tsv(tsv_path: Path) -> dict[str, int | list[str]]:
    """Validate the TSV file and return validation results."""
    print(f"Validating TSV: {tsv_path}")
    
    with tsv_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        
        # Check required columns
        actual_columns = set(reader.fieldnames or [])
        missing_columns = REQUIRED_COLUMNS - actual_columns
        if missing_columns:
            raise ValueError(
                f"Missing required columns: {missing_columns}. "
                f"Actual columns: {actual_columns}"
            )
        
        # Read all rows for validation
        rows = list(reader)
        row_count = len(rows)
        
        if not (MIN_TOKENS <= row_count <= MAX_TOKENS):
            raise ValueError(
                f"Row count {row_count} outside expected range [{MIN_TOKENS}, {MAX_TOKENS}]"
            )
        
        # Extract unique book OSIS codes from ref column
        books = set()
        empty_text_count = 0
        
        for row in rows:
            ref = row.get("ref", "")
            if ref:
                # Extract book OSIS code (first whitespace-delimited token)
                book = ref.split()[0]
                books.add(book)
            
            if not row.get("text", "").strip():
                empty_text_count += 1
        
        if empty_text_count > 0:
            raise ValueError(f"Found {empty_text_count} empty text cells")
        
        if len(books) != EXPECTED_BOOKS:
            raise ValueError(
                f"Expected {EXPECTED_BOOKS} unique books, got {len(books)}: {sorted(books)}"
            )
        
        return {
            "row_count": row_count,
            "books": sorted(books),
            "empty_text_count": empty_text_count
        }


def _write_manifest(output_dir: Path, validation_results: dict[str, int | list[str]], source_url: str) -> dict[str, str | int]:
    """Write the manifest.json file."""
    manifest = {
        "file": "macula-greek.tsv",
        "source": "Clear-Bible/macula-greek (CC BY 4.0)",
        "books": len(validation_results["books"]),
        "tokens": validation_results["row_count"],
        "source_url": source_url,
        "license": "CC-BY-4.0",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    
    manifest_path = output_dir / "manifest.json"
    try:
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        raise RuntimeError(f"Cannot write manifest: {exc}") from exc
    
    print(f"manifest: {manifest_path}")
    print(f"  books: {manifest['books']}")
    print(f"  tokens: {manifest['tokens']}")
    print(f"  license: {manifest['license']}")
    
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download and validate Macula Greek tokens."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/macula"),
        help="Directory for downloaded files (default: data/macula).",
    )
    args = parser.parse_args(argv)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Download the raw TSV
        print(f"Downloading Macula Greek TSV from {MACULA_GREEK_TSV_URL}")
        raw_tsv_path = output_dir / "macula-greek-SBLGNT-raw.tsv"
        _download_file(MACULA_GREEK_TSV_URL, raw_tsv_path, "macula_greek")
        
        # Transform to canonical format
        print("Transforming to canonical format...")
        canonical_tsv = output_dir / "macula-greek.tsv"
        
        with raw_tsv_path.open("r", encoding="utf-8") as in_fh, \
             canonical_tsv.open("w", encoding="utf-8", newline="") as out_fh:
            
            reader = csv.DictReader(in_fh, delimiter="\t")
            writer = csv.DictWriter(out_fh, fieldnames=CANONICAL_FIELDS, delimiter="\t")
            
            # Write header
            writer.writeheader()
            
            # Transform and write each row
            for row in reader:
                transformed_row = _transform_row(row)
                writer.writerow({k: transformed_row.get(k, "") for k in CANONICAL_FIELDS})
        
        # Validate the canonical TSV
        validation_results = _validate_tsv(canonical_tsv)
        
        # Write manifest
        manifest = _write_manifest(output_dir, validation_results, MACULA_GREEK_TSV_URL)

        return 0

    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"ERROR: unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())