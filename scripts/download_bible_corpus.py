#!/usr/bin/env python3
"""Download and validate the KJV and WEB Bible corpora.

Fetches the whole-Bible JSON files from the midvash/bible-data repository,
saves them under ``data/bible/``, validates their shape and verse counts,
and writes ``data/bible/manifest.json`` describing the two translations.

Schema reference: https://github.com/midvash/bible-data/blob/main/SCHEMA.md
Expected ``<slug>.json`` shape:
    {
        "version": "kjv",
        "name": "King James Version",
        "language": "en",
        "license": "public-domain",
        "books": [
            {
                "book": "Gen",          # OSIS identifier
                "bookId": 1,
                "englishName": "Genesis",
                "testament": "OT",
                "chapters": [
                    {
                        "chapter": 1,
                        "verses": [
                            {"number": 1, "text": "In the beginning..."}
                        ]
                    }
                ]
            }
        ]
    }

Exit codes:
    0 - success
    1 - command-line or I/O error
    2 - download failed
    3 - validation failed
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Corpus source URLs match the directory layout documented in SCHEMA.md.
CORPUS_BASE = "https://raw.githubusercontent.com/midvash/bible-data/main/versions/en"
TRANSLATIONS: dict[str, dict[str, Any]] = {
    "kjv": {
        "source_url": f"{CORPUS_BASE}/kjv/kjv.json",
        "license": "public-domain",
    },
    "web": {
        "source_url": f"{CORPUS_BASE}/web/web.json",
        "license": "public-domain",
    },
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "bible"
DOWNLOAD_TIMEOUT_S = 120
MIN_VERSES = 30_000
MAX_VERSES = 32_000
EXPECTED_BOOK_COUNT = 66


def _describe_top_level(data: Any) -> str:
    """Return a human-readable description of the top-level JSON value."""
    if not isinstance(data, dict):
        return f"expected top-level object, got {type(data).__name__}"
    items = []
    for key, value in sorted(data.items()):
        items.append(f"{key!r}: {type(value).__name__}")
    return "{" + ", ".join(items) + "}"


def _load_corpus(path: Path, label: str) -> dict[str, Any]:
    """Read and parse a JSON corpus file."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label}: invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"{label}: cannot read {path}: {exc}") from exc


def _download_corpus(url: str, dest: Path, label: str) -> None:
    """Download ``url`` to ``dest`` with streaming and a generous timeout."""
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT_S, stream=True)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"{label}: download failed from {url}: {exc}") from exc

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    fh.write(chunk)
    except OSError as exc:
        raise RuntimeError(f"{label}: failed writing {dest}: {exc}") from exc


def _validate_corpus(data: dict[str, Any], label: str) -> int:
    """Validate corpus shape and return the total verse count.

    Fails loudly if the JSON does not match the documented schema, printing
    the actual top-level keys so the mismatch is immediately actionable.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"{label}: expected top-level JSON object; {_describe_top_level(data)}"
        )

    # Adapt to the actual keys observed in the downloaded file.  The schema
    # documents ``books`` as the container; if that is absent we surface the
    # real top-level keys instead of crashing with a generic KeyError.
    # See https://github.com/midvash/bible-data/blob/main/SCHEMA.md
    if "books" not in data:
        raise ValueError(
            f"{label}: missing top-level 'books' key; actual keys: "
            f"{_describe_top_level(data)}"
        )

    books = data["books"]
    if not isinstance(books, list):
        raise ValueError(
            f"{label}: expected 'books' to be a list, got {type(books).__name__}"
        )

    if len(books) != EXPECTED_BOOK_COUNT:
        raise ValueError(
            f"{label}: expected {EXPECTED_BOOK_COUNT} books, got {len(books)}"
        )

    total_verses = 0
    for book_index, book in enumerate(books):
        if not isinstance(book, dict):
            raise ValueError(
                f"{label}: book {book_index} is {type(book).__name__}, expected object"
            )

        osis = book.get("book")
        if not isinstance(osis, str):
            raise ValueError(
                f"{label}: book {book_index} missing string 'book' (OSIS) key"
            )

        chapters = book.get("chapters")
        if not isinstance(chapters, list):
            raise ValueError(
                f"{label}: book {osis} 'chapters' is "
                f"{type(chapters).__name__}, expected list"
            )

        for chapter_index, chapter in enumerate(chapters):
            if not isinstance(chapter, dict):
                raise ValueError(
                    f"{label}: book {osis} chapter {chapter_index} is "
                    f"{type(chapter).__name__}, expected object"
                )

            verses = chapter.get("verses")
            if not isinstance(verses, list):
                raise ValueError(
                    f"{label}: book {osis} chapter {chapter_index} 'verses' is "
                    f"{type(verses).__name__}, expected list"
                )

            for verse_index, verse in enumerate(verses):
                if not isinstance(verse, dict):
                    raise ValueError(
                        f"{label}: book {osis} chapter {chapter_index} verse "
                        f"{verse_index} is {type(verse).__name__}, expected object"
                    )

                text = verse.get("text")
                if text is None or (isinstance(text, str) and text.strip() == ""):
                    raise ValueError(
                        f"{label}: empty verse text at book {osis} "
                        f"chapter {chapter_index} verse {verse_index}"
                    )

                total_verses += 1

    if not (MIN_VERSES <= total_verses <= MAX_VERSES):
        raise ValueError(
            f"{label}: total verses {total_verses} outside expected range "
            f"[{MIN_VERSES}, {MAX_VERSES}]"
        )

    return total_verses


def _process_translation(
    slug: str,
    override_path: Path | None,
    dest_dir: Path,
) -> dict[str, Any]:
    """Download (or copy from override) and validate one translation."""
    config = TRANSLATIONS[slug]
    source_url = config["source_url"]
    dest_file = dest_dir / f"{slug}.json"

    if override_path is not None:
        print(f"{slug}: using override file {override_path}")
        data = _load_corpus(override_path, slug)
    else:
        print(f"{slug}: downloading {source_url}")
        _download_corpus(source_url, dest_file, slug)
        data = _load_corpus(dest_file, slug)
        # Persist only when we actually downloaded; overrides are read in-place.
        print(f"{slug}: saved {dest_file}")

    verse_count = _validate_corpus(data, slug)
    print(f"{slug}: validated {len(data['books'])} books, {verse_count} verses")

    return {
        "file": dest_file.name,
        "books": len(data["books"]),
        "verses": verse_count,
        "source_url": source_url,
        "license": config["license"],
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download and validate the KJV and WEB Bible corpora."
    )
    parser.add_argument(
        "--kjv-file",
        type=Path,
        default=None,
        help="Override the downloaded KJV JSON with a local file (for testing).",
    )
    parser.add_argument(
        "--web-file",
        type=Path,
        default=None,
        help="Override the downloaded WEB JSON with a local file (for testing).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DATA_DIR,
        help=f"Directory for downloaded files (default: {DATA_DIR}).",
    )
    args = parser.parse_args(argv)

    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {}

    try:
        manifest["kjv"] = _process_translation("kjv", args.kjv_file, data_dir)
        manifest["web"] = _process_translation("web", args.web_file, data_dir)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    manifest_path = data_dir / "manifest.json"
    try:
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        print(f"ERROR: cannot write manifest: {exc}", file=sys.stderr)
        return 1

    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
