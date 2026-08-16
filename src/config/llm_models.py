"""Static message-type definitions (replaces the former ref_message_types table).

Each :class:`MessageTypeDef` records the same fields the SQLite
``ref_message_types`` row used to hold. The instances below are frozen and
constructed at import time; once the module-level ``DEFAULT_REGISTRY`` is built
they are never mutated, which makes them safe to share across asyncio tasks and
worker threads without locking.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from config.schemas import (
    INTENT_GENERATION_SCHEMA,
    HYDE_GENERATION_SCHEMA,
)
from config.prompts import (
    INTENT_GENERATION_PROMPT,
    HYDE_GENERATION_PROMPT,
)


@dataclass(frozen=True)
class MessageTypeDef:
    """Immutable configuration for one pipeline message type.

    Attributes:
        slug: Stable identifier used by services and the LLM wrapper.
        step_name: Human-readable pipeline step name.
        creator_type: ``'human'`` | ``'llm'`` | ``'programmatic'``.
        request_schema: JSON schema dict for validating the LLM response,
            or ``{"type":"object"}`` for non-LLM summary rows.
        model_slug: OpenRouter model slug, or ``'n/a'`` for programmatic rows.
        temperature: Sampling temperature.
        additional_model_settings: Extra payload keys merged into the chat
            completion request (e.g. ``{"max_tokens": 1200}``).
        max_retries: Maximum attempts before giving up.
        description: Short human-readable description.
        prompt_template: ``.format(query=...)`` template string, or ``None``
            when the prompt is built by the caller.
    """

    slug: str
    step_name: str
    creator_type: str
    request_schema: Dict[str, Any]
    model_slug: str
    temperature: float
    additional_model_settings: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 3
    description: str = ""
    prompt_template: Optional[str] = None


EMBEDDING_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "dimension": {"type": "integer"},
        "count": {"type": "integer"},
    },
    "required": ["model", "dimension", "count"],
}

CONTEXT_RETRIEVAL_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "intent_id": {"type": "string"},
        "translation_count": {"type": "integer"},
        "hit_count": {"type": "integer"},
        "scored_word_count": {"type": "integer"},
        "kept_word_count": {"type": "integer"},
    },
    "required": [
        "intent_id",
        "translation_count",
        "hit_count",
        "scored_word_count",
        "kept_word_count",
    ],
}

MODEL_INTENT_GENERATION = "meta-llama/llama-3.3-70b-instruct"
MODEL_HYDE_GENERATION = "mistralai/mistral-small-24b-instruct-2501"
MODEL_EMBEDDING = "openai/text-embedding-3-small"


DEFAULT_MESSAGE_TYPES: Dict[str, MessageTypeDef] = {
    "human_input": MessageTypeDef(
        slug="human_input",
        step_name="Human Input",
        creator_type="human",
        request_schema={"type": "object"},
        model_slug="n/a",
        temperature=0.0,
        max_retries=3,
        description="User-originated input message",
    ),
    "intent_generation": MessageTypeDef(
        slug="intent_generation",
        step_name="Intent Generation",
        creator_type="programmatic",
        request_schema=INTENT_GENERATION_SCHEMA,
        model_slug=MODEL_INTENT_GENERATION,
        temperature=0.2,
        additional_model_settings={"max_tokens": 1200},
        max_retries=3,
        description="Refined multi-intent generation for a user query",
        prompt_template=INTENT_GENERATION_PROMPT,
    ),
    "hyde_generation": MessageTypeDef(
        slug="hyde_generation",
        step_name="HyDE Generation",
        creator_type="programmatic",
        request_schema=HYDE_GENERATION_SCHEMA,
        model_slug=MODEL_HYDE_GENERATION,
        temperature=0.7,
        additional_model_settings={"max_tokens": 800},
        max_retries=3,
        description="Hypothetical biblical passage generated from a single intent",
        prompt_template=HYDE_GENERATION_PROMPT,
    ),
    "embedding_generation": MessageTypeDef(
        slug="embedding_generation",
        step_name="Embedding Generation",
        creator_type="programmatic",
        request_schema=EMBEDDING_REQUEST_SCHEMA,
        model_slug=MODEL_EMBEDDING,
        temperature=0.0,
        max_retries=3,
        description="Batched embedding generation call record (summary only, never raw vectors)",
    ),
    "context_retrieval": MessageTypeDef(
        slug="context_retrieval",
        step_name="Context Retrieval",
        creator_type="programmatic",
        request_schema=CONTEXT_RETRIEVAL_REQUEST_SCHEMA,
        model_slug="n/a",
        temperature=0.0,
        max_retries=3,
        description="Per-intent original-language context enrichment for retrieved verses",
    ),
    "corpus_ingest": MessageTypeDef(
        slug="corpus_ingest",
        step_name="Corpus Ingest",
        creator_type="programmatic",
        request_schema=EMBEDDING_REQUEST_SCHEMA,
        model_slug=MODEL_EMBEDDING,
        temperature=0.0,
        max_retries=3,
        description="Summary row emitted at the end of a translation ingest run",
    ),
}