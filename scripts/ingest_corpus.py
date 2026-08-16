#!/usr/bin/env python3
"""Ingest Bible corpora into ChromaDB.

Loads each translation from ``data/bible/<slug>.json``, embeds all verse texts
via the batched embedding service, and upserts them into a ChromaDB collection.
Runs are idempotent: repeated executions overwrite the same verse IDs and
complete the collection count.

Audit: a single ``corpus_ingest`` INFO log record per translation summarising
``translation, verses, batch_count, elapsed_ms, status``. There is no
application database.

Exit codes:
    0 - success
    1 - configuration or I/O error
    2 - vector store error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config.logging import configure_logging, get_logger
from services.base import BaseService
from services.embeddings.service import EmbeddingService
from services.vectordb.store import VerseStore


CHUNK_SIZE = 256
DEFAULT_CHROMA_PATH = "data/chroma"
BIBLE_DIR = Path(__file__).resolve().parent.parent / "data" / "bible"
MANIFEST_PATH = BIBLE_DIR / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    """Load the Bible corpus manifest."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"manifest not found at {MANIFEST_PATH}; run download_bible_corpus.py first"
        )
    with MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _flatten_translation(data: dict[str, Any], slug: str) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Flatten a whole-translation JSON into ChromaDB-ready lists."""
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    for book in data["books"]:
        osis = book["book"]
        book_name = book.get("englishName", osis)
        for chapter in book["chapters"]:
            chapter_num = chapter["chapter"]
            for verse in chapter["verses"]:
                verse_num = verse["number"]
                text = verse["text"]
                verse_id = f"{slug.upper()}-{osis}-{chapter_num}-{verse_num}"
                ids.append(verse_id)
                documents.append(text)
                metadatas.append(
                    {
                        "book": book_name,
                        "osis": osis,
                        "chapter": int(chapter_num),
                        "verse": int(verse_num),
                        "translation": slug.lower(),
                    }
                )

    return ids, documents, metadatas


async def _ingest_translation(
    slug: str,
    store: VerseStore,
    embedder: EmbeddingService,
    base: BaseService,
    max_batches: int | None,
    manifest: dict[str, Any],
) -> None:
    """Embed and upsert a single translation, then emit a summary log record."""
    collection_name = f"{slug.lower()}_verses"
    expected_verses = manifest[slug]["verses"]

    corpus_path = BIBLE_DIR / f"{slug}.json"
    with corpus_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    ids, documents, metadatas = _flatten_translation(data, slug)
    if len(documents) != expected_verses:
        raise ValueError(
            f"{slug}: manifest expects {expected_verses} verses, file has {len(documents)}"
        )

    store.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})

    total_batches = (len(documents) + CHUNK_SIZE - 1) // CHUNK_SIZE
    batches_to_run = total_batches if max_batches is None else min(max_batches, total_batches)

    print(f"{slug}: ingesting {len(documents)} verses in {batches_to_run}/{total_batches} batches")

    started = time.monotonic()
    for batch_index in range(batches_to_run):
        start = batch_index * CHUNK_SIZE
        end = start + CHUNK_SIZE
        chunk_ids = ids[start:end]
        chunk_documents = documents[start:end]
        chunk_metadatas = metadatas[start:end]

        embeddings = await embedder.embed_texts(
            chunk_documents,
            record=False,
            chunk_size=CHUNK_SIZE,
        )

        store.upsert_verses(
            collection_name,
            ids=chunk_ids,
            documents=chunk_documents,
            metadatas=chunk_metadatas,
            embeddings=embeddings,
        )

        batch_num = batch_index + 1
        if batch_num % 10 == 0 or batch_num == batches_to_run:
            print(f"{slug}: batch {batch_num}/{total_batches}")

    actual_count = store.count(collection_name)
    if actual_count != expected_verses:
        raise RuntimeError(
            f"{slug}: collection count {actual_count} != expected {expected_verses}"
        )

    # Emit one corpus_ingest summary record (no DB write; JSONL log only).
    correlation_id = str(uuid.uuid4())
    summary = {
        "translation": slug,
        "verses": expected_verses,
        "collection": collection_name,
        "batches": batches_to_run,
    }
    await base.record_message(
        message_type_slug="corpus_ingest",
        unique_prompt=json.dumps(summary),
        session_uuid=correlation_id,
        raw_response=json.dumps(
            {"status": "ok", "dimension": 1536, "translation": slug, "verses": expected_verses}
        ),
        num_tries=1,
        extra={
            "event": "corpus_ingest",
            "translation": slug,
            "verse_count": expected_verses,
            "batch_count": batches_to_run,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "status": "ok",
        },
    )
    print(f"{slug}: verified {actual_count} verses in {collection_name}")


async def _semantic_check(embedder: EmbeddingService, store: VerseStore) -> None:
    """Query ``kjv_verses`` for ``love your enemies`` and assert the expected hits."""
    query_text = "love your enemies"
    query_embeddings = await embedder.embed_texts(
        [query_text],
        record=False,
        chunk_size=1,
    )
    results = store.query(
        "kjv_verses",
        query_embeddings=query_embeddings,
        n_results=5,
    )

    print(f"\nsemantic check: '{query_text}' top-5 hits")
    hits: set[tuple[str, int, int]] = set()
    for metas in results["metadatas"]:
        for meta in metas:
            print(
                f"  {meta['osis']} {meta['chapter']}:{meta['verse']} "
                f"({meta['translation']})"
            )
            hits.add((meta["osis"], meta["chapter"], meta["verse"]))

    expected_hits = {
        ("Matt", 5, 44),
        ("Luke", 6, 27),
        ("Luke", 6, 35),
    }
    if not (hits & expected_hits):
        raise AssertionError(
            f"semantic check failed: expected one of {expected_hits}, got {hits}"
        )
    print("semantic check: passed")


async def main(argv: list[str] | None = None) -> int:
    """Run the corpus ingest pipeline."""
    parser = argparse.ArgumentParser(
        description="Ingest Bible corpora into ChromaDB."
    )
    parser.add_argument(
        "--chroma-path",
        type=str,
        default=DEFAULT_CHROMA_PATH,
        help=f"Path to the ChromaDB directory (default: {DEFAULT_CHROMA_PATH}).",
    )
    parser.add_argument(
        "--translation",
        type=str,
        default=None,
        choices=["kjv", "web"],
        help="Ingest only a single translation (default: both kjv and web).",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Stop after N embedding batches (for failure/resume testing).",
    )
    parser.add_argument(
        "--skip-semantic-check",
        action="store_true",
        help="Skip the post-ingest semantic query check.",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    configure_logging()
    if not os.getenv("OPENROUTER_STRONGCHAT_DEFAULT_API_KEY"):
        print("ERROR: OPENROUTER_STRONGCHAT_DEFAULT_API_KEY not configured", file=sys.stderr)
        return 1

    try:
        manifest = _load_manifest()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    translations = [args.translation] if args.translation else ["kjv", "web"]

    store = VerseStore(path=args.chroma_path)
    embedder = EmbeddingService()
    # Base is used purely for its structured logger shim (record_message).
    base = BaseService()

    try:
        for slug in translations:
            await _ingest_translation(
                slug,
                store,
                embedder,
                base,
                max_batches=args.max_batches,
                manifest=manifest,
            )

        if not args.skip_semantic_check:
            await _semantic_check(embedder, store)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        embedder.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))