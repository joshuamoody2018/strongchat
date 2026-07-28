"""ChromaDB-backed verse store.

Provides a thin wrapper around ``chromadb.PersistentClient`` for storing
Bible verse embeddings with cosine HNSW collections and idempotent upserts.
"""

import os
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils.batch_utils import create_batches


class VerseStore:
    """Persistent ChromaDB store for Bible verse embeddings."""

    def __init__(self, path: str = "data/chroma") -> None:
        """Initialize the ChromaDB persistent client.

        Args:
            path: Directory where ChromaDB persists its SQLite + index files.
                Created automatically if it does not exist.
        """
        os.makedirs(path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=path)

    def get_or_create_collection(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Collection:
        """Fetch or create a collection with cosine HNSW space by default.

        Args:
            name: Collection name.
            metadata: Optional collection metadata. When omitted, the collection
                is configured with ``{"hnsw:space": "cosine"}``.

        Returns:
            The ChromaDB collection object.
        """
        if metadata is None:
            metadata = {"hnsw:space": "cosine"}
        return self.client.get_or_create_collection(name, metadata=metadata)

    def upsert_verses(
        self,
        collection_name: str,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        embeddings: List[List[float]],
    ) -> None:
        """Idempotently upsert verse batches into a collection.

        Uses ``chromadb.utils.batch_utils.create_batches`` to stay within the
        client's maximum batch size, then upserts each batch. Duplicate IDs
        are overwritten rather than raising an error.

        Args:
            collection_name: Target collection name.
            ids: Verse identifiers.
            documents: Verse text strings.
            metadatas: Per-verse metadata dictionaries.
            embeddings: Per-verse embedding vectors.

        Raises:
            ValueError: If input list lengths differ.
        """
        if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
            raise ValueError("ids, documents, metadatas, and embeddings must have the same length")

        collection = self.get_or_create_collection(collection_name)
        batches = create_batches(
            api=self.client,
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        for batch_ids, batch_embeddings, batch_metadatas, batch_documents in batches:
            collection.upsert(
                ids=batch_ids,
                embeddings=batch_embeddings,
                metadatas=batch_metadatas,
                documents=batch_documents,
            )

    def count(self, name: str) -> int:
        """Return the number of items in a collection."""
        collection = self.get_or_create_collection(name)
        return collection.count()

    def query(
        self,
        name: str,
        query_embeddings: List[List[float]],
        n_results: int,
    ) -> Dict[str, Any]:
        """Query a collection by embedding.

        Args:
            name: Collection name.
            query_embeddings: List of query embedding vectors.
            n_results: Number of nearest neighbors to return per query.

        Returns:
            ChromaDB query result dictionary.
        """
        collection = self.get_or_create_collection(name)
        return collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
        )
