"""Pipeline orchestrator for intent → HyDE → retrieval."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.base import BaseService
from services.embeddings import EmbeddingService
from services.hyde import HydeService
from services.intent import IntentService
from services.retrieval import RetrievalService
from services.vectordb import VerseStore


@dataclass
class PipelineResult:
    """Structured output of a full pipeline run.

    Attributes:
        session_uuid: UUID of the pipeline session.
        query: Original user query.
        intents: Structured intent list from ``IntentService``.
        hyde_docs: HyDE generation results, one per intent.
        results: Retrieval hits per doc/translation pair.
    """

    session_uuid: str
    query: str
    intents: List[Dict[str, Any]] = field(default_factory=list)
    hyde_docs: List[Dict[str, Any]] = field(default_factory=list)
    results: List[Dict[str, Any]] = field(default_factory=list)


class PipelineRunner(BaseService):
    """Compose intent, HyDE, embedding, and retrieval services.

    The runner owns one shared ``EmbeddingService`` that is reused by the
    retrieval layer to avoid duplicate API key setup and extra connections.
    """

    def __init__(
        self,
        db_path: str = "data/chat_database.db",
        chroma_path: str = "data/chroma",
    ):
        """Initialize all composed services.

        Args:
            db_path: Path to the SQLite database file.
            chroma_path: Path to the ChromaDB persistence directory.
        """
        super().__init__(db_path)
        self.embedding_service = EmbeddingService(db_path)
        self.verse_store = VerseStore(chroma_path)
        self.retrieval_service = RetrievalService(
            db_path,
            embedding_service=self.embedding_service,
            verse_store=self.verse_store,
        )
        self.intent_service = IntentService(db_path)
        self.hyde_service = HydeService(db_path)

    async def run(
        self,
        query: str,
        top_k: int = 10,
        translations: tuple[str, ...] = ("kjv", "web"),
    ) -> PipelineResult:
        """Execute the full pipeline for a user query.

        Args:
            query: The raw user query.
            top_k: Number of nearest neighbors per HyDE document/translation.
            translations: Translation slugs to query.

        Returns:
            ``PipelineResult`` containing the session UUID, intents, HyDE
            documents, and retrieval hits.
        """
        session_uuid = self.db.create_session(
            name=f"pipeline: {query[:60]}",
            created_by="pipeline",
        )

        intent_response = await self.intent_service.generate_intents(
            query, session_uuid
        )
        intents = intent_response["intents"]

        hyde_docs = await self.hyde_service.generate_for_intents(
            intents, session_uuid
        )

        results = await self.retrieval_service.search(
            hyde_docs,
            session_uuid,
            top_k=top_k,
            translations=translations,
        )

        return PipelineResult(
            session_uuid=session_uuid,
            query=query,
            intents=intents,
            hyde_docs=hyde_docs,
            results=results,
        )

    def close(self) -> None:
        """Close all owned services and the runner's own database connection."""
        self.retrieval_service.close()
        self.hyde_service.llm.close()
        self.intent_service.llm.close()
        self.llm.close()

    def print_summary(self, result: PipelineResult) -> None:
        """Print a human-readable summary of a pipeline result."""
        print(f"Query: {result.query}")
        print(f"Session: {result.session_uuid}")
        print(f"Intents generated: {len(result.intents)}")
        print(f"HyDE documents: {len(result.hyde_docs)}")
        print()

        for item in result.results:
            intent_id = item.get("intent_id", "unknown")
            translation = item.get("translation", "unknown")
            print(f"Intent: {intent_id} | Translation: {translation}")

            hits = item.get("hits", [])
            for i, hit in enumerate(hits[:3], start=1):
                reference = hit.get("reference", "unknown")
                distance = hit.get("distance", 0.0)
                print(f"  {i}. {reference} (distance: {distance:.4f})")

            if not hits:
                print("  (no hits)")

            print()
