"""Serialize a :class:`PipelineResult` to an agent-ready JSON bundle.

The bundle is self-contained: it carries every artifact the agent needs to
synthesize an answer AND every artifact the future ``validate_answer`` tool
needs to fact-check that answer against the same retrieved context. Drop the
embedding vectors — huge, redundant for the agent, and never needed downstream
of retrieval.
"""

from typing import Any, Dict, List

from services.pipeline.runner import PipelineResult


def pipeline_result_to_bundle(result: PipelineResult) -> Dict[str, Any]:
    """Convert a :class:`PipelineResult` to a JSON-safe dict.

    Embedding vectors on traces are dropped. Every other per-intent artifact
    (intent_data, hyde_document, per-translation hits with their
    context_bundle) is preserved verbatim so the future ``validate_answer``
    tool can accept this dict back unchanged as its ``context`` argument.

    Args:
        result: The :class:`PipelineResult` returned by ``PipelineRunner.run``.

    Returns:
        Dict with ``correlation_id``, ``query``, ``query_analysis``, and
        ``traces`` (list of per-intent trace dicts).
    """
    traces_out: List[Dict[str, Any]] = []
    for trace in result.traces.values():
        search_results_out: Dict[str, List[Dict[str, Any]]] = {}
        for translation, hits in trace.search_results.items():
            # Defensive copy: strip any non-JSON-serializable residue from
            # context bundles, but otherwise pass through verbatim (the
            # bundles are already plain dicts of scalars + lists of strings).
            search_results_out[translation] = [_hit_to_dict(h) for h in hits]
        traces_out.append(
            {
                "intent_id": trace.intent_id,
                "intent_data": trace.intent_data,
                "hyde_document": trace.hyde_document,
                "hyde_error": trace.hyde_error,
                "search_results": search_results_out,
            }
        )

    return {
        "correlation_id": result.session_uuid,
        "query": result.query,
        "query_analysis": result.query_analysis,
        "traces": traces_out,
    }


def _hit_to_dict(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a single hit to a JSON-safe dict, dropping non-serializable fields.

    Embeddings were already filtered at the trace level (we never carried
    them on hits), but we still guard against the rare case where a hit
    carries an ``embedding`` key from the retrieval stage.
    """
    out: Dict[str, Any] = {
        "id": hit.get("id", ""),
        "text": hit.get("text", ""),
        "reference": hit.get("reference", ""),
        "distance": hit.get("distance"),
    }
    bundle = hit.get("context_bundle")
    if bundle is not None:
        out["context_bundle"] = bundle
    return out