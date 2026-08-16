#!/usr/bin/env python3
"""Download and validate Macula Hebrew tokens.

Downloads Macula Hebrew tokens from the upstream Clear-Bible/macula-hebrew
repository, validates the TSV shape, and writes a manifest for use by
build_macula_index.py --testament hebrew.

Source: https://raw.githubusercontent.com/Clear-Bible/macula-hebrew/main/WLC/tsv/macula-hebrew.tsv
License: CC BY 4.0 (WLC text public domain via Groves Center; syntax
trees/glosses CC BY 4.0; sense data via UBS MARBLE / SDBH).

Macula Hebrew is served via Git LFS, so this script resolves the LFS
pointer itself rather than relying on raw.githubusercontent.com (which
serves only the pointer text, not the underlying file). Falls back to a
plain HTTPS GET to the LFS S3 endpoint declared in the pointer, then
writes the canonical TSV to data/macula/macula-hebrew.tsv.

Exit codes:
  0   success
  1   CLI / IO error (bad paths, manifest write failure)
  3   download or validation failure (malformed TSV, wrong shape)
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


# Upstream URL (will serve the LFS pointer text, not the actual TSV).
MACULA_HEBREW_TSV_URL = (
    "https://raw.githubusercontent.com/Clear-Bible/macula-hebrew/main/WLC/tsv/"  # noqa: E501
    "macula-hebrew.tsv"
)

# Canonical schema. The upstream Macula Hebrew TSV defines 32 columns per
# WLC/tsv/hebrew-nodes-to-tsv.xq's local:headers(); we ingest the subset
# needed by ContextRetrievalService (matching the Greek canonical schema).
REQUIRED_COLUMNS = {
    "xml:id", "ref", "text", "lemma", "strongnumberx", "morph", "pos", "gloss",
}
# Canonical output field order, identical to the Greek canonical TSV so
# build_macula_index.py can ingest both with one path.
CANONICAL_FIELDS = (
    "xml:id", "ref", "text", "lemma", "strongnumberx", "morph", "pos", "gloss",
)

# Macula Hebrew has ~39 books and ~424k WLC tokens. Use a generous but
# sane validation range.
MIN_TOKENS = 300_000
MAX_TOKENS = 700_000
EXPECTED_BOOKS = 39

# Hebrew book code (REF's first whitespace token in the upstream TSV is
# the OSIS-style book code; per mappings/lowfat-macula-hebrew.xquery the
# upstream uses uppercase codes like 'GEN', 'EXO' ... 'MAL').
HEBREW_REF_CODE_TO_OSIS = {
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth",
    "1SA": "1Sam", "2SA": "2Sam", "1KI": "1Kgs", "2KI": "2Kgs",
    "1CH": "1Chr", "2CH": "2Chr", "EZR": "Ezra", "NEH": "Neh",
    "EST": "Esth", "JOB": "Job", "PSA": "Ps", "PRO": "Prov",
    "ECC": "Eccl", "SNG": "Song", "ISA": "Isa", "JER": "Jer",
    "LAM": "Lam", "EZK": "Ezek", "DAN": "Dan",
    "HOS": "Hos", "JOL": "Joel", "AMO": "Amos", "OBA": "Obad",
    "JON": "Jonah", "MIC": "Mic", "NAM": "Nah", "HAB": "Hab",
    "ZEP": "Zeph", "HAG": "Hag", "ZEC": "Zech", "MAL": "Mal",
}


def _download_text(url: str, label: str) -> str:
    """Download text content from URL, raising on HTTP error."""
    print(f"Downloading {label} from {url}")
    req = Request(url, headers={"User-Agent": "strongchat/1.0 (+lfs-resolver)"})
    try:
        with urlopen(req, timeout=120) as resp:
            payload = resp.read()
    except Exception as e:
        print(f"Error: download failed for {url}: {e}", file=sys.stderr)
        sys.exit(3)
    # Resolve Git LFS pointer if present.
    text = payload.decode("utf-8", errors="replace")
    if text.startswith("version https://git-lfs.github.com/spec/v1"):
        text = _resolve_lfs_pointer(text, label)
    return text


def _resolve_lfs_pointer(pointer_text: str, label: str) -> str:
    """Resolve a Git LFS pointer by POSTing to the GitHub LFS batch API.

    The pointer format is:
        version https://git-lfs.github.com/spec/v1
        oid sha256:<hex>
        size <bytes>
    """
    print(f"  Detected Git LFS pointer; resolving via GitHub LFS batch API...")
    lines = [l.strip() for l in pointer_text.splitlines() if l.strip()]
    meta = {}
    for line in lines:
        if line.startswith("version ") or line.startswith("oid ") or line.startswith("size "):
            key, _, value = line.partition(" ")
            meta[key] = value
    oid = meta.get("oid", "")
    if "sha256:" not in oid:
        print(f"Error: LFS pointer oid malformed: {oid!r}", file=sys.stderr)
        sys.exit(3)
    sha = oid.split(":", 1)[1]

    # GitHub LFS batch API endpoint for the macula-hebrew repo. GitHub
    # requires the '.git' segment in the URL path (the
    # '/info/lfs/objects/batch' route is hosted under the bare-repo
    # namespace, not the human-facing repo URL). Without '.git' the API
    # returns HTTP 422 Unprocessable Entity.
    repo = "Clear-Bible/macula-hebrew"
    api_url = f"https://github.com/{repo}.git/info/lfs/objects/batch"
    batch_body = json.dumps({
        "operation": "download",
        "transfers": ["basic"],
        "objects": [{"oid": sha, "size": int(meta.get("size", "0") or "0")}],
    }).encode("utf-8")
    req = Request(
        api_url,
        data=batch_body,
        headers={
            "Accept": "application/vnd.git-lfs+json",
            "Content-Type": "application/vnd.git-lfs+json",
            "User-Agent": "strongchat/1.0 (+lfs-resolver)",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as resp:
            response_json = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error: LFS batch API call failed: {e}", file=sys.stderr)
        sys.exit(3)

    objects = response_json.get("objects", [])
    if not objects:
        print("Error: LFS batch API returned no objects", file=sys.stderr)
        sys.exit(3)
    obj = objects[0]
    if "error" in obj:
        print(f"Error: LFS batch API returned error for object: {obj['error']}",
              file=sys.stderr)
        sys.exit(3)
    actions = obj.get("actions", {})
    download_action = actions.get("download")
    if not download_action:
        print("Error: LFS batch API response missing download action", file=sys.stderr)
        sys.exit(3)
    href = download_action.get("href")
    if not href:
        print("Error: LFS download action missing href", file=sys.stderr)
        sys.exit(3)

    print(f"  Downloading actual TSV payload from LFS storage...")
    req = Request(href, headers={"User-Agent": "strongchat/1.0 (+lfs-resolver)"})
    try:
        with urlopen(req, timeout=300) as resp:
            payload = resp.read()
    except Exception as e:
        print(f"Error: LFS payload download failed: {e}", file=sys.stderr)
        sys.exit(3)
    text = payload.decode("utf-8", errors="replace")
    print(f"  Resolved {len(text)} bytes via LFS storage")
    return text


def _validate_canonical_tsv(tsv_path: Path) -> dict:
    """Validate the canonical TSV's shape.

    Returns a dict with row_count, books (set), and empty_text_count.
    Raises ValueError on shape violations.

    Note: upstream WLC legitimately records rows with empty `text` for
    maqaf-attached morphemes (e.g. prefixed article ה attached to the
    following word — `xml:id` ends in a Hebrew letter suffix and morph
    is 'Td'). These rows carry morphological data + gloss despite the
    empty surface, so we count them as a soft warning rather than reject.
    """
    with open(tsv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        actual_columns = reader.fieldnames
        missing = [c for c in CANONICAL_FIELDS if c not in (actual_columns or [])]
        if missing:
            raise ValueError(
                f"Canonical TSV missing required columns: {missing}. "
                f"Got: {actual_columns}"
            )

        rows = list(reader)
        row_count = len(rows)
        if not (MIN_TOKENS <= row_count <= MAX_TOKENS):
            raise ValueError(
                f"Row count {row_count} outside expected range "
                f"[{MIN_TOKENS}, {MAX_TOKENS}]"
            )

        # 'ref' is the OSIS-formatted ref like 'GEN 1:1'. First whitespace-
        # delimited token identifies the book.
        books = set()
        empty_text_count = 0
        for r in rows:
            ref = r.get("ref", "") or ""
            if ref:
                first_token = ref.split()[0] if ref.split() else ""
                books.add(HEBREW_REF_CODE_TO_OSIS.get(first_token, first_token))
            if not (r.get("text") or "").strip():
                empty_text_count += 1

        # Empty-text is expected for WLC maqaf-attached morphemes (Hel article,
        # ב/כ/ל prepositions attached via maqaf). Allow up to ~5% of rows to
        # carry empty surface; warn but don't fail. Hard-fail only on a
        # catastrophic level of emptiness (>20%) that signals a corrupt TSV.
        if empty_text_count > 0.20 * row_count:
            raise ValueError(
                f"{empty_text_count} of {row_count} rows have empty text "
                f"({empty_text_count/row_count:.1%}) — exceeds 20% threshold; "
                f"upstream TSV may be corrupt"
            )
        if empty_text_count > 0:
            print(f"  note: {empty_text_count} rows carry empty `text` "
                  f"(expected for WLC maqaf-attached morphemes like ה article)")

        if len(books) != EXPECTED_BOOKS:
            raise ValueError(
                f"Expected {EXPECTED_BOOKS} distinct Hebrew books, got "
                f"{len(books)}: {sorted(books)}"
            )

    return {"row_count": row_count, "books": sorted(books), "empty_text_count": empty_text_count}


def _write_manifest(output_dir: Path, validation_results: dict, source_url: str):
    """Write a manifest parallel to data/macula/manifest.json for Greek."""
    manifest = {
        "file": "macula-hebrew.tsv",
        "source": "Clear-Bible/macula-hebrew (CC BY 4.0)",
        "books": len(validation_results["books"]),
        "tokens": validation_results["row_count"],
        "source_url": source_url,
        "license": "CC-BY-4.0",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = output_dir / "hebrew-manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"Manifest written: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Download and validate Macula Hebrew tokens."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/macula"),
        help="Directory for downloaded files (default: data/macula).",
    )
    parser.add_argument(
        "--source-url",
        default=MACULA_HEBREW_TSV_URL,
        help="Override for the upstream Macula Hebrew TSV URL.",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_tsv_path = output_dir / "macula-hebrew-raw.tsv"
    canonical_tsv = output_dir / "macula-hebrew.tsv"

    text = _download_text(args.source_url, "macula_hebrew")
    with open(raw_tsv_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Saved raw TSV: {raw_tsv_path}")

    # Macula Hebrew's upstream TSV is already in the canonical shape
    # (column-wise subset is what we need). Re-write a canonical TSV with
    # just the required columns to keep ingest fast and the on-disk file
    # small, parallel to the Greek pipeline's _transform_row step.
    _build_canonical_tsv(raw_tsv_path, canonical_tsv)
    print(f"Canonical TSV written: {canonical_tsv}")

    try:
        validation_results = _validate_canonical_tsv(canonical_tsv)
    except ValueError as e:
        print(f"Error: validation failed: {e}", file=sys.stderr)
        sys.exit(3)

    print(f"Validation OK: {validation_results['row_count']} tokens, "
          f"{len(validation_results['books'])} books")

    _write_manifest(output_dir, validation_results, args.source_url)


def _build_canonical_tsv(raw_path: Path, canonical_path: Path):
    """Project the upstream Macula Hebrew TSV down to the canonical
    8-column schema. Filters out the ~24 supplemental columns."""
    with open(raw_path, "r", encoding="utf-8", newline="") as fin:
        reader = csv.DictReader(fin, delimiter="\t")
        upstream_fields = reader.fieldnames or []
        missing = [c for c in CANONICAL_FIELDS if c not in upstream_fields]
        if missing:
            print(f"Error: upstream TSV missing required columns: {missing}",
                  file=sys.stderr)
            print(f"  Available columns: {upstream_fields}", file=sys.stderr)
            sys.exit(3)
        with open(canonical_path, "w", encoding="utf-8", newline="") as fout:
            writer = csv.DictWriter(
                fout, fieldnames=list(CANONICAL_FIELDS), delimiter="\t",
            )
            writer.writeheader()
            count = 0
            for row in reader:
                writer.writerow({k: row.get(k, "") for k in CANONICAL_FIELDS})
                count += 1
                if count % 50000 == 0:
                    print(f"  Projected {count} rows...")


if __name__ == "__main__":
    main()