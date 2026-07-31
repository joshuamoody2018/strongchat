"""HyDE generation service."""

import asyncio  # noqa: ANYIO_OK
import json
import logging
from typing import Dict, Any, List

from src.services.base import BaseService
from src.services.llm.exceptions import LLMError

logger = logging.getLogger(__name__)

_HYDE_INTENT_FIELDS = (
    "intent_id",
    "interpretation",
    "keywords_explicit",
    "keywords_inferred",
    "themes",
)


class HydeService(BaseService):
    """Generate one hypothetical Bible passage per intent in parallel."""

    async def generate_for_intents(
        self, intents: List[Dict[str, Any]], session_uuid: str
    ) -> List[Dict[str, Any]]:
        """Generate a HyDE document for every intent.

        Each intent is serialized to a bias-isolated JSON prompt containing only
        the fields needed for HyDE generation. Calls are launched in parallel
        via ``asyncio.gather``; failures are captured per intent. If every
        intent fails, an ``LLMError`` is raised.

        Args:
            intents: List of intent dictionaries from ``IntentService``.
            session_uuid: UUID of the parent session.

        Returns:
            List of result dictionaries, each containing either a successful
            ``hyde_document`` or an ``error`` key with ``hyde_document`` set to
            ``None``.

        Raises:
            LLMError: If zero intents produced a successful HyDE document.
        """
        # The shared LLMWrapper and its SQLite connection are safe under
        # asyncio.gather: a single-threaded event loop serializes all DB
        # writes, so concurrent _generate_one coroutines do not contend for the
        # connection even though they share one wrapper instance.
        results = await asyncio.gather(
            *[self._generate_one(intent, session_uuid) for intent in intents],
            return_exceptions=True,
        )

        processed: List[Dict[str, Any]] = []
        for result in results:
            if isinstance(result, BaseException):
                if isinstance(result, Exception):
                    processed.append(
                        {
                            "hyde_document": None,
                            "error": str(result),
                        }
                    )
                    continue
                raise result
            processed.append(result)

        successes = [
            result for result in processed if result.get("hyde_document") is not None
        ]
        if not successes:
            error = LLMError(
                f"All {len(intents)} intent HyDE generations failed"
            )
            error.results = processed
            raise error

        return processed

    async def _generate_one(
        self, intent: Dict[str, Any], session_uuid: str
    ) -> Dict[str, Any]:
        """Generate a single HyDE document for one intent.

        Args:
            intent: A single intent dictionary.
            session_uuid: UUID of the parent session.

        Returns:
            Result dictionary with ``intent_id`` and either a successful
            ``hyde_document``/``message_uuid`` pair or an ``error`` key.
        """
        intent_id = intent.get("intent_id", "unknown")

        try:
            intent_subset = {
                field: intent[field] for field in _HYDE_INTENT_FIELDS
            }
            intent_json = json.dumps(intent_subset)
        except KeyError as exc:
            logger.exception(
                "HyDE intent %s missing required field %s", intent_id, exc
            )
            return {
                "intent_id": intent_id,
                "hyde_document": None,
                "error": f"Missing required field: {exc}",
            }

        try:
            aimessage = await self.llm.call_api(
                "hyde_generation", intent_json, session_uuid
            )
            parsed = self.parse_message(aimessage, "hyde_generation")
            return {
                "intent_id": intent_id,
                "hyde_document": parsed["hyde_document"],
                "message_uuid": aimessage.uuid,
            }
        except Exception as exc:  # noqa: BROAD_EXCEPT_OK
            logger.exception("HyDE generation failed for intent %s", intent_id)
            return {
                "intent_id": intent_id,
                "hyde_document": None,
                "error": str(exc),
            }
