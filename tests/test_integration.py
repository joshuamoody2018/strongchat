#!/usr/bin/env python3
"""Top-level integration tests for the stateless MCP retrieval pipeline.

Cross-service integration: registry construction, intent → HyDE → retrieval
shape, and JSONL audit assertions via ``self.assertLogs``. No application
DB; the registry is built in-process from
:data:`config.llm_models.DEFAULT_MESSAGE_TYPES`.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

if not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = "dummy-key-for-offline-tests"

from config import DEFAULT_REGISTRY, MessageTypeDef, MessageTypeDefRegistry
from services.pipeline import PipelineRunner, pipeline_result_to_bundle


DIMENSION = 1536


def _deterministic_vector(text: str) -> list[float]:
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
    return [float((seed + i) % 1000) / 1000.0 for i in range(DIMENSION)]


def _make_intent(intent_id: str, is_primary: bool = False) -> dict:
    return {
        "intent_id": intent_id,
        "interpretation": f"Interpretation for {intent_id}",
        "keywords_explicit": ["kw_a"],
        "keywords_inferred": ["kw_b"],
        "themes": ["theme_x"],
        "confidence": 0.9,
        "is_primary": is_primary,
    }


class TestRegistry(unittest.TestCase):
    """The default in-process registry covers every pipeline message type."""

    def test_registry_has_all_pipeline_slugs(self):
        for slug in (
            "intent_generation",
            "hyde_generation",
            "embedding_generation",
            "context_retrieval",
            "corpus_ingest",
        ):
            self.assertTrue(DEFAULT_REGISTRY.has(slug), f"missing slug: {slug}")

    def test_registry_get_returns_immutable_typedef(self):
        mt = DEFAULT_REGISTRY.get("intent_generation")
        self.assertEqual(mt.slug, "intent_generation")
        self.assertEqual(
            mt.model_slug, "meta-llama/llama-3.3-70b-instruct"
        )
        # Frozen dataclass: assignment must fail.
        with self.assertRaises(Exception):
            mt.slug = "tampered"  # type: ignore[misc]

    def test_registry_reset_swaps_contents_in_place(self):
        original = MessageTypeDefRegistry(DEFAULT_REGISTRY.all())
        dummy = MessageTypeDef(
            slug="dummy", step_name="d", creator_type="programmatic",
            request_schema={"type": "object"}, model_slug="dummy/model",
            temperature=0.0, description="",
        )
        try:
            DEFAULT_REGISTRY.reset([dummy])
            self.assertTrue(DEFAULT_REGISTRY.has("dummy"))
            self.assertFalse(DEFAULT_REGISTRY.has("intent_generation"))
            self.assertEqual(DEFAULT_REGISTRY.get("dummy").slug, "dummy")
        finally:
            # Restore the canonical defaults so other tests aren't affected.
            DEFAULT_REGISTRY.reset(list(original.all()))


class TestPipelineBundleShape(unittest.TestCase):
    """End-to-end bundle shape with mocked services."""

    def test_bundle_shape_and_logging(self):
        intents = [_make_intent("comfort", is_primary=True)]
        hyde_docs = [
            {"intent_id": "comfort", "hyde_document": "hyde text", "message_uuid": "m1"}
        ]
        embedding = _deterministic_vector("hyde text")
        retrieval_results = [
            {
                "intent_id": "comfort",
                "doc_index": 0,
                "translation": "kjv",
                "embedding": embedding,
                "hits": [
                    {
                        "id": "h1",
                        "text": "text1",
                        "reference": "John 3:16",
                        "distance": 0.0,
                    }
                ],
            },
        ]
        intent_response = {
            "message_uuid": "intent-msg-1",
            "query_analysis": {"original_query": "why", "core_questions": ["why"]},
            "intents": intents,
        }

        runner = PipelineRunner()
        try:
            async def fake_generate_intents(query, session_uuid):
                return intent_response

            async def fake_generate_for_intents(intents_in, session_uuid):
                return hyde_docs

            async def fake_search(hyde_docs_in, session_uuid, **kwargs):
                return retrieval_results

            async def fake_embed_texts(texts, **kwargs):
                return [embedding]

            async def fake_retrieve_for_pipeline(result, session_uuid):
                for trace in result.traces.values():
                    for hits in trace.search_results.values():
                        for hit in hits:
                            hit["context_bundle"] = {
                                "reference": hit["reference"],
                                "kept_words": [],
                                "scored_words": [],
                                "kept_word_count": 0,
                                "scored_word_count": 0,
                                "unique_word_count": 0,
                                "build_summary": "(mocked)",
                            }

            with self.assertLogs("strongchat", level="INFO") as cm:
                with patch.object(
                    runner.intent_service, "generate_intents",
                    new=AsyncMock(side_effect=fake_generate_intents),
                ), patch.object(
                    runner.hyde_service, "generate_for_intents",
                    new=AsyncMock(side_effect=fake_generate_for_intents),
                ), patch.object(
                    runner.retrieval_service, "search",
                    new=AsyncMock(side_effect=fake_search),
                ), patch.object(
                    runner.embedding_service, "embed_texts",
                    new=AsyncMock(side_effect=fake_embed_texts),
                ), patch.object(
                    runner.context_service, "retrieve_for_pipeline",
                    new=AsyncMock(side_effect=fake_retrieve_for_pipeline),
                ):
                    result = asyncio.run(
                        runner.run(query="why", top_k=3, translations=("kjv",))
                    )

            # Audit: pipeline_start + pipeline_end emitted at INFO.
            info_events = {
                r.__dict__.get("event") for r in cm.records
                if r.levelno == logging.INFO
            }
            self.assertIn("pipeline_start", info_events)
            self.assertIn("pipeline_end", info_events)

            bundle = pipeline_result_to_bundle(result)
            self.assertEqual(bundle["query"], "why")
            self.assertEqual(bundle["correlation_id"], result.session_uuid)
            self.assertEqual(len(bundle["traces"]), 1)
            trace = bundle["traces"][0]
            self.assertEqual(trace["intent_id"], "comfort")
            self.assertIn("kjv", trace["search_results"])
            hit = trace["search_results"]["kjv"][0]
            self.assertIn("context_bundle", hit)
            # Embeddings must NEVER make it into the agent bundle.
            self.assertNotIn("embedding", hit)
        finally:
            runner.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)