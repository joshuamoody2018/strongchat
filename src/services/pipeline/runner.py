"""Pipeline orchestrator for intent → HyDE → retrieval → context."""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.base import BaseService
from services.context import ContextRetrievalService
from services.embeddings import EmbeddingService
from services.hyde import HydeService
from services.intent import IntentService
from services.retrieval import RetrievalService
from services.vectordb import VerseStore

logger = logging.getLogger(__name__)

#: Optional progress reporter the runner invokes at each major pipeline stage.
#:
#: Called as ``await progress(stage, message, progress=None, total=None)``.
#: ``stage`` is a short snake_case identifier; ``message`` is human-readable
#: text safe to surface to an end user (e.g. inside an MCP progress
#: notification); ``progress``/``total`` are optional numeric progress
#: fractions when a stage knows them. The callback is strictly
#: informational — the runner ignores its return value and never blocks on
#: it failing. Stages emitted today: ``intent``, ``hyde``, ``retrieval``,
#: ``context``, ``serialize``.
ProgressCallback = Callable[
    [str, str, "Optional[float]", "Optional[float]"], Awaitable[None]
]


@dataclass
class IntentTrace:
    """Per-intent container holding every artifact produced during the pipeline.

    Attributes:
        intent_id: Stable identifier from ``IntentService``.
        intent_data: The full intent dict from ``IntentService``.
        hyde_document: The hypothetical passage generated for this intent,
            or ``None`` if HyDE generation failed.
        hyde_error: Human-readable error string if HyDE generation failed.
        embedding: The embedding vector used for vector search. ``None`` if
            HyDE failed or retrieval was skipped. Dropped from the serialized
            bundle the MCP server returns to agents; kept here so downstream
            reranking/debugging can still reach it.
        search_results: Mapping of translation slug to the list of verse hit
            dicts returned by the vector store. Each hit carries a
            ``context_bundle`` once the context stage runs.
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

    Attributes:
        session_uuid: Log correlation id generated per pipeline run. No
            longer backed by a database row; survives purely in the JSONL
            audit log so multi-instance logs can be sliced per run.
        query: Original user query.
        traces: Dict of ``intent_id`` -> :class:`IntentTrace`.
        query_analysis: Surfaced from ``IntentService``.
    """

    session_uuid: str
    query: str
    traces: Dict[str, IntentTrace] = field(default_factory=dict)
    query_analysis: Dict[str, Any] = field(default_factory=dict)

    @property
    def intents(self) -> List[Dict[str, Any]]:
        """Flat list view of ``intent_data`` dicts, in insertion order."""
        return [trace.intent_data for trace in self.traces.values()]

    @property
    def hyde_docs(self) -> List[Dict[str, Any]]:
        """Flat list view preserving the pre-refactor HyDE result shape."""
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
        """Flat list view of retrieval results, one entry per (intent, translation)."""
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
    """Compose intent, HyDE, embedding, retrieval, and context services.

    Stateless: each ``run()`` call generates a fresh correlation id, threads
    it through the services for log correlation only, and returns a
    ``PipelineResult`` dataclass. Nothing is persisted between calls; the
    audit trail is JSONL log records (keyed by ``correlation_id``) plus the
    returned bundle itself.
    """

    def __init__(
        self,
        registry=None,
        chroma_path: str = "data/chroma",
        macula_db_path: str = "data/macula_index.db",
    ):
        """Initialize all composed services.

        Args:
            registry: Optional overridden :class:`MessageTypeDefRegistry`.
            chroma_path: Path to the ChromaDB persistence directory.
            macula_db_path: Path to the read-only Macula index SQLite file.
        """
        super().__init__(registry=registry)
        self.embedding_service = EmbeddingService(registry=self.registry)
        self.verse_store = VerseStore(chroma_path)
        self.retrieval_service = RetrievalService(
            registry=self.registry,
            embedding_service=self.embedding_service,
            verse_store=self.verse_store,
            chroma_path=chroma_path,
        )
        self.intent_service = IntentService(registry=self.registry)
        self.hyde_service = HydeService(registry=self.registry)
        self.context_service = ContextRetrievalService(
            registry=self.registry,
            macula_db_path=macula_db_path,
        )

    async def run_intent_only(
        self,
        query: str,
        session_uuid: str,
    ) -> Dict[str, Any]:
        """Run only the intent generation part of the pipeline."""
        intent_response = await self.intent_service.generate_intents(
            query, session_uuid
        )
        return {
            'query_analysis': intent_response['query_analysis'],
            'intents': intent_response['intents'],
        }

    async def run(
        self,
        query: str,
        top_k: int = 10,
        translations: tuple[str, ...] = ("kjv", "web"),
        progress: Optional[ProgressCallback] = None,
    ) -> PipelineResult:
        """Execute the full pipeline for a user query.

        Stateless: each call generates a fresh correlation id, threads it
        through for log correlation only, and returns a ``PipelineResult``.
        Nothing server-side persists between calls — the agent's context
        window is what threads the returned bundle across the
        retrieve → synthesize → validate loop.

        Args:
            query: The raw user query.
            top_k: Number of nearest neighbors per HyDE document/translation.
            translations: Translation slugs to query.
            progress: Optional async callback invoked at each major
                pipeline stage with ``(stage, message, progress, total)``.
                Used by the MCP server to surface ``report_progress``
                notifications to the calling agent (e.g. streamed into the
                Claude.ai UI as the user waits). The runner never blocks
                on this callback; failures inside it are swallowed and
                logged. The pipeline result is unaffected.

        Returns:
            ``PipelineResult`` with the correlation id, original query,
            per-intent traces, and the original ``query_analysis``.
        """
        correlation_id = str(uuid.uuid4())
        started = time.monotonic()
        self.logger.info(
            "pipeline_start",
            extra={
                "event": "pipeline_start",
                "correlation_id": correlation_id,
                "query": query,
                "top_k": top_k,
                "translations": list(translations),
            },
        )

        async def _report(stage: str, message: str,
                          done: Optional[float] = None,
                          total: Optional[float] = None) -> None:
            """Forward a stage event to the caller's progress callback.

            Failures are swallowed: the progress callback is informational
            only and MUST NOT change pipeline behaviour. The MCP layer
            wraps this in its own try/except as well, but the runner-level
            guard means a buggy transport callback can never poison a run.
            """
            if progress is None:
                return
            try:
                await progress(stage, message, done, total)
            except Exception as exc:  # noqa: BLE001 - informational only
                self.logger.warning(
                    "progress_callback_error",
                    extra={
                        "event": "progress_callback_error",
                        "correlation_id": correlation_id,
                        "stage": stage,
                        "error": str(exc),
                    },
                )

        try:
            # Stage 1: Intent — create one empty trace per intent.
            await _report("intent", "Extracting query intent…")
            intent_response = await self.intent_service.generate_intents(
                query, correlation_id
            )
            intents = intent_response["intents"]
            query_analysis = intent_response.get("query_analysis", {})
            await _report(
                "intent",
                f"Intent extracted ({len(intents)} intent(s)).",
                done=1.0, total=1.0,
            )

            traces: Dict[str, IntentTrace] = {}
            for intent in intents:
                intent_id = intent.get("intent_id", "unknown")
                traces[intent_id] = IntentTrace(
                    intent_id=intent_id,
                    intent_data=intent,
                )

            # Stage 2: HyDE — attach hyde_document or hyde_error to each trace.
            await _report("hyde", "Generating HyDE passages…")
            hyde_docs = await self.hyde_service.generate_for_intents(
                intents, correlation_id
            )
            for hd in hyde_docs:
                intent_id = hd.get("intent_id")
                if intent_id and intent_id in traces:
                    traces[intent_id].hyde_document = hd.get("hyde_document")
                    if hd.get("error") is not None:
                        traces[intent_id].hyde_error = hd["error"]
            hyde_ok = sum(1 for t in traces.values() if t.hyde_document)
            await _report(
                "hyde",
                f"HyDE complete ({hyde_ok}/{len(traces)} docs).",
                done=1.0, total=1.0,
            )

            # Stage 3+4: Embedding + retrieval.
            await _report(
                "retrieval",
                f"Searching {len(translations)} translation(s) for nearest verses…",
            )
            retrieval_results = await self.retrieval_service.search(
                hyde_docs,
                correlation_id,
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
            total_hits = sum(
                len(hits) for trace in traces.values()
                for hits in trace.search_results.values()
            )
            await _report(
                "retrieval",
                f"Retrieval complete ({total_hits} verse hits).",
                done=1.0, total=1.0,
            )

            result = PipelineResult(
                session_uuid=correlation_id,
                query=query,
                traces=traces,
                query_analysis=query_analysis,
            )

            # Stage 5: Context retrieval — attach original-language bundles.
            await _report(
                "context",
                "Resolving original-language context bundles…",
            )
            try:
                await self.context_service.retrieve_for_pipeline(result, correlation_id)
            except Exception as e:
                self.logger.error(
                    "context_retrieval_pipeline_error",
                    extra={
                        "event": "context_retrieval_pipeline_error",
                        "correlation_id": correlation_id,
                        "error": str(e),
                    },
                )
            await _report(
                "context",
                "Original-language context resolved.",
                done=1.0, total=1.0,
            )

            await _report("serialize", "Serializing context bundle…")
            self.logger.info(
                "pipeline_end",
                extra={
                    "event": "pipeline_end",
                    "correlation_id": correlation_id,
                    "query": query,
                    "intent_count": len(traces),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "status": "ok",
                },
            )
            return result
        except Exception as exc:
            self.logger.error(
                "pipeline_end",
                extra={
                    "event": "pipeline_end",
                    "correlation_id": correlation_id,
                    "query": query,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "status": "error",
                    "error": str(exc),
                },
            )
            raise

    def close(self) -> None:
        """Close any owned services that hold resources."""
        try:
            self.context_service.close()
        except Exception:
            pass
        self.retrieval_service.close()
        # Services without their own close(): intent_service, hyde_service
        # own an LLMWrapper but it is a no-op now.

    def print_summary(self, result: PipelineResult) -> None:
        """Print a human-readable summary of a pipeline result."""
        print(f"Query: {result.query}")
        print(f"Correlation id: {result.session_uuid}")
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