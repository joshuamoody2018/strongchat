"""Pipeline orchestrator for intent → HyDE → retrieval."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.base import BaseService
from services.embeddings import EmbeddingService
from services.hyde import HydeService
from services.intent import IntentService
from services.retrieval import RetrievalService
from services.vectordb import VerseStore


@dataclass
class IntentTrace:
    """Per-intent container holding every artifact produced during the pipeline.

    One ``IntentTrace`` is created per intent returned by ``IntentService`` and
    accumulates data from each downstream stage (HyDE, embedding, retrieval)
    in-place. Keying ``PipelineResult.traces`` by ``intent_id`` gives O(1)
    predecessor lookup for any downstream artifact (verse hit, embedding,
    HyDE document).

    Attributes:
        intent_id: Stable identifier from ``IntentService``; the dict key
            used in ``PipelineResult.traces``.
        intent_data: The full intent dict from ``IntentService`` (includes
            ``interpretation``, ``keywords_explicit/inferred``, ``themes``,
            ``confidence``, ``is_primary``).
        hyde_document: The hypothetical passage generated for this intent,
            or ``None`` if HyDE generation failed.
        hyde_error: Human-readable error string if HyDE generation failed,
            otherwise ``None``. A non-``None`` value indicates the trace
            will have no embedding or search results.
        embedding: The embedding vector used for vector search. ``None`` if
            HyDE failed (no document to embed) or retrieval was skipped.
            Previously this was dropped after search; preserving it enables
            downstream reranking and debugging.
        search_results: Mapping of translation slug (e.g. ``"kjv"``) to the
            list of verse hit dicts returned by the vector store. Empty
            for translations that were not requested, for intents whose
            HyDE failed, or for translations that returned no hits.
    """

    intent_id: str
    intent_data: Dict[str, Any]
    hyde_document: Optional[str] = None
    hyde_error: Optional[str] = None
    embedding: Optional[List[float]] = None
    search_results: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Structured output of a full pipeline run.

    The primary shape is ``traces``: a dict keyed by ``intent_id`` whose
    values are :class:`IntentTrace` instances holding every per-intent
    artifact produced during the run. This gives O(1) traversal from any
    downstream artifact (verse hit, embedding) back to its intent.

    Backward-compatible list views (``intents``, ``hyde_docs``, ``results``)
    are exposed as @properties so existing call sites that iterate over the
    pre-refactor flat shape continue to work without changes.

    Attributes:
        session_uuid: UUID of the pipeline session.
        query: Original user query.
        traces: Dict of ``intent_id`` -> :class:`IntentTrace`.
        query_analysis: Surfaced from ``IntentService`` (was previously
            computed but dropped before reaching the result).
        recommended_search_approach: Surfaced from ``IntentService`` (was
            previously computed but dropped before reaching the result).
    """

    session_uuid: str
    query: str
    traces: Dict[str, IntentTrace] = field(default_factory=dict)
    query_analysis: Dict[str, Any] = field(default_factory=dict)
    recommended_search_approach: str = ""

    @property
    def intents(self) -> List[Dict[str, Any]]:
        """Flat list view of ``intent_data`` dicts, in insertion order."""
        return [trace.intent_data for trace in self.traces.values()]

    @property
    def hyde_docs(self) -> List[Dict[str, Any]]:
        """Flat list view preserving the pre-refactor HyDE result shape.

        Each entry mirrors what ``HydeService.generate_for_intents`` returned:
        ``intent_id``, ``hyde_document`` (``None`` on failure), and either
        ``message_uuid`` on success or ``error`` on failure.
        """
        out: List[Dict[str, Any]] = []
        for trace in self.traces.values():
            entry: Dict[str, Any] = {
                "intent_id": trace.intent_id,
                "hyde_document": trace.hyde_document,
            }
            if trace.hyde_error is not None:
                entry["error"] = trace.hyde_error
            out.append(entry)
        return out

    @property
    def results(self) -> List[Dict[str, Any]]:
        """Flat list view of retrieval results, one entry per (intent, translation).

        Each entry preserves the pre-refactor ``RetrievalService`` result shape:
        ``intent_id``, ``translation``, ``hits``. ``doc_index`` is included
        for compatibility with downstream callers.
        """
        out: List[Dict[str, Any]] = []
        doc_index = 0
        for trace in self.traces.values():
            for translation, hits in trace.search_results.items():
                out.append(
                    {
                        "intent_id": trace.intent_id,
                        "doc_index": doc_index,
                        "translation": translation,
                        "hits": hits,
                    }
                )
            doc_index += 1
        return out


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

    async def run_intent_only(
        self,
        query: str,
        session_uuid: str,
    ) -> Dict[str, Any]:
        """Run only the intent generation part of the pipeline.

        Args:
            query: The raw user query.
            session_uuid: UUID of the parent session.

        Returns:
            Dictionary with intent analysis results.
        """
        intent_response = await self.intent_service.generate_intents(
            query, session_uuid
        )
        return {
            'query_analysis': intent_response['query_analysis'],
            'intents': intent_response['intents'],
            'recommended_search_approach': intent_response['recommended_search_approach'],
        }

    async def run(
        self,
        query: str,
        top_k: int = 10,
        translations: tuple[str, ...] = ("kjv", "web"),
    ) -> PipelineResult:
        """Execute the full pipeline for a user query.

        Each stage attaches its output to the per-intent trace in-place,
        so the returned ``PipelineResult`` preserves every artifact from
        intent through retrieval. Traceability is O(1): given any intent_id
        or any verse hit's intent_id, the full chain (intent → hyde →
        embedding → hits) is a single dict lookup.

        Args:
            query: The raw user query.
            top_k: Number of nearest neighbors per HyDE document/translation.
            translations: Translation slugs to query.

        Returns:
            ``PipelineResult`` containing the session UUID, a per-intent
            ``traces`` dict, the original ``query_analysis`` and
            ``recommended_search_approach`` from ``IntentService``, plus
            backward-compatible flat list views.
        """
        session_uuid = self.db.create_session(
            name=f"pipeline: {query[:60]}",
            created_by="pipeline",
        )

        # Stage 1: Intent — create one empty trace per intent.
        intent_response = await self.intent_service.generate_intents(
            query, session_uuid
        )
        intents = intent_response["intents"]
        query_analysis = intent_response.get("query_analysis", {})
        recommended_search_approach = intent_response.get(
            "recommended_search_approach", ""
        )

        traces: Dict[str, IntentTrace] = {}
        for intent in intents:
            intent_id = intent.get("intent_id", "unknown")
            traces[intent_id] = IntentTrace(
                intent_id=intent_id,
                intent_data=intent,
            )

        # Stage 2: HyDE — attach hyde_document or hyde_error to each trace.
        hyde_docs = await self.hyde_service.generate_for_intents(
            intents, session_uuid
        )
        for hd in hyde_docs:
            intent_id = hd.get("intent_id")
            if intent_id and intent_id in traces:
                traces[intent_id].hyde_document = hd.get("hyde_document")
                if hd.get("error") is not None:
                    traces[intent_id].hyde_error = hd["error"]

        # Stage 3+4: Embedding + retrieval.
        # RetrievalService.search returns one entry per (hyde_doc, translation),
        # each carrying the embedding it used. We attach both to the
        # corresponding trace by intent_id. Intents whose HyDE failed
        # (hyde_document is None) are skipped by search() and thus have
        # no embedding or search_results — matching the pre-refactor behavior
        # of silently dropping them, but now visible on the trace.
        retrieval_results = await self.retrieval_service.search(
            hyde_docs,
            session_uuid,
            top_k=top_k,
            translations=translations,
        )
        for r in retrieval_results:
            intent_id = r.get("intent_id")
            if intent_id and intent_id in traces:
                if "embedding" in r:
                    traces[intent_id].embedding = r["embedding"]
                translation = r.get("translation")
                if translation is not None:
                    traces[intent_id].search_results[translation] = r.get("hits", [])

        return PipelineResult(
            session_uuid=session_uuid,
            query=query,
            traces=traces,
            query_analysis=query_analysis,
            recommended_search_approach=recommended_search_approach,
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
