"""Process-wide registry of :class:`MessageTypeDef` configurations.

Replaces the former ``GlobalReferenceCache`` + SQLite ``ref_message_types``
lookup. The registry is built once at import time from
:data:`config.llm_models.DEFAULT_MESSAGE_TYPES` and never mutated afterwards;
read-only after import, GIL-safe across asyncio tasks and worker threads.

Tests that need to point at a different registry can call
:meth:`MessageTypeDefRegistry.reset` (replaces the singleton contents) or
construct a fresh ``MessageTypeDefRegistry`` and inject it into the services.
"""

from typing import Dict, Iterable, Optional

from config.llm_models import MessageTypeDef, DEFAULT_MESSAGE_TYPES


class MessageTypeDefRegistry:
    """Slug → ``MessageTypeDef`` lookup, populated once at import time."""

    def __init__(self, defs: Optional[Iterable[MessageTypeDef]] = None) -> None:
        source = list(defs) if defs is not None else list(DEFAULT_MESSAGE_TYPES.values())
        self._defs: Dict[str, MessageTypeDef] = {d.slug: d for d in source}

    def get(self, slug: str) -> MessageTypeDef:
        """Return the def for *slug*; raise ``KeyError`` if unknown.

        Mirrors the previous ``GlobalReferenceCache.get_message_type`` call
        surface used by :class:`services.llm.wrapper.LLMWrapper` and the
        service base, but raises instead of returning ``None`` so callers don't
        silently fall through on a misconfigured slug.
        """
        try:
            return self._defs[slug]
        except KeyError as exc:
            raise KeyError(
                f"Message type '{slug}' not found or inactive in registry"
            ) from exc

    def has(self, slug: str) -> bool:
        """True if *slug* is registered."""
        return slug in self._defs

    def all(self):
        """Iterate over every registered def."""
        return iter(self._defs.values())

    def reset(self, defs: Iterable[MessageTypeDef]) -> None:
        """Replace the contents of this registry instance.

        Test-only helper: lets a fixture swap the singleton contents in place
        without re-instantiating every service. Production code never calls
        this; the singleton built at import time is the source of truth for
        the lifetime of the process.
        """
        self._defs = {d.slug: d for d in defs}


DEFAULT_REGISTRY = MessageTypeDefRegistry()