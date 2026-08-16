"""Async retrieval service for HyDE documents."""

import asyncio
import logging
from typing import Any, Dict, List

from services.base import BaseService
from services.embeddings import EmbeddingService
from services.vectordb import VerseStore

logger = logging.getLogger(__name__)


class RetrievalService(BaseService):
    """Retrieve Bible verse hits for HyDE documents across translations."""

    def __init__(
        self,
        registry=None,
        embedding_service: EmbeddingService = None,
        verse_store: VerseStore = None,
        chroma_path: str = "data/chroma",
    ):
        """Initialize the retrieval service.

        Args:
            registry: Optional overridden :class:`MessageTypeDefRegistry`.
            embedding_service: Optional injected :class:`EmbeddingService`. If
                None, one is constructed using the same registry.
            verse_store: Optional injected :class:`VerseStore`. If None, one is
                constructed at ``chroma_path``.
            chroma_path: Path to the ChromaDB persistence directory; ignored
                when ``verse_store`` is injected.
        """
        super().__init__(registry=registry)
        self._owns_embedding_service = embedding_service is None
        self.embedding_service = embedding_service or EmbeddingService(
            registry=self.registry,
        )
        self.store = verse_store or VerseStore(chroma_path)

    def close(self) -> None:
        """No resources to release; kept for backwards compatibility."""
        if self._owns_embedding_service:
            self.embedding_service.close()

    async def search(
        self,
        hyde_docs: List[Dict[str, Any]],
        session_uuid: str,
        top_k: int = 10,
        translations: tuple[str, ...] = ("kjv", "web"),
    ) -> List[Dict[str, Any]]:
        """Embed HyDE documents and retrieve verse hits per translation.

        Args:
            hyde_docs: List of dicts with ``intent_id`` and ``hyde_document``.
            session_uuid: Log correlation id (no longer persisted).
            top_k: Number of nearest neighbors per query.
            translations: Translation slugs to query.

        Returns:
            List of result items, each with ``intent_id``, ``doc_index``,
            ``translation``, ``embedding``, and ``hits``.
        """
        valid_docs: List[tuple[int, Dict[str, Any]]] = []
        for i, doc in enumerate(hyde_docs):
            if doc and doc.get("hyde_document"):
                valid_docs.append((i, doc))

        if not valid_docs:
            return []

        texts = [doc["hyde_document"] for _, doc in valid_docs]
        embeddings = await self.embedding_service.embed_texts(
            texts,
            session_uuid=session_uuid,
            record=True,
        )

        tasks = []
        task_keys: List[tuple[int, Dict[str, Any], str]] = []
        for (doc_index, doc), embedding in zip(valid_docs, embeddings):
            for translation in translations:
                collection_name = f"{translation}_verses"
                tasks.append(
                    asyncio.to_thread(
                        self.store.query,
                        collection_name,
                        [embedding],
                        top_k,
                    )
                )
                task_keys.append((doc_index, doc, translation))

        raw_results = await asyncio.gather(*tasks)

        embedding_by_doc_index: Dict[int, List[float]] = {
            doc_index: embedding
            for (doc_index, _), embedding in zip(valid_docs, embeddings)
        }

        results: List[Dict[str, Any]] = []
        for (doc_index, doc, translation), raw in zip(task_keys, raw_results):
            results.append(
                {
                    "intent_id": doc.get("intent_id"),
                    "doc_index": doc_index,
                    "translation": translation,
                    "embedding": embedding_by_doc_index.get(doc_index),
                    "hits": self._format_hits(raw),
                }
            )

        return results

    def _format_hits(self, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert Chroma query result into a structured, sorted hit list."""
        ids = raw.get("ids", [[]])[0]
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        hits: List[Dict[str, Any]] = []
        for hit_id, text, metadata, distance in zip(
            ids, documents, metadatas, distances
        ):
            metadata = metadata or {}
            book = metadata.get("book", "Unknown")
            chapter = metadata.get("chapter", 0)
            verse = metadata.get("verse", 0)
            hits.append(
                {
                    "id": hit_id,
                    "text": text,
                    "reference": f"{book} {chapter}:{verse}",
                    "distance": distance,
                }
            )

        hits.sort(key=lambda hit: hit["distance"])
        return hits