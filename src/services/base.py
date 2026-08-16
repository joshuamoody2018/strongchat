"""Shared foundation for pipeline services."""

import logging
from typing import Any, Dict, Optional

from config.logging import get_logger
from config.registry import MessageTypeDefRegistry, DEFAULT_REGISTRY
from services.llm.aimessage import AIMessage
from services.llm.wrapper import LLMWrapper


class BaseService:
    """Minimal base for all pipeline services.

    Owns one :class:`LLMWrapper` instance and exposes its registry and a
    child logger as aliases so downstream services can issue structured log
    records and look up message types without re-opening connections.

    There is no application database. The audit trail is the JSONL log and
    the returned ``PipelineResult`` bundle. ``record_message`` is kept as a
    thin logger shim so existing service call sites only change one line.
    """

    def __init__(
        self,
        registry: Optional[MessageTypeDefRegistry] = None,
        chroma_path: Optional[str] = None,
    ) -> None:
        """Initialize the service.

        Args:
            registry: Optional overridden :class:`MessageTypeDefRegistry`.
                Defaults to the process-wide singleton built at import time.
            chroma_path: Reserved for services that compose a ``VerseStore``;
                ignored by leaf services. Held on the signature so the
                ``PipelineRunner`` can pass it through uniformly.
        """
        self.registry = registry or DEFAULT_REGISTRY
        self.llm = LLMWrapper(registry=self.registry)
        self.logger = get_logger(self.__class__.__module__)

    async def record_message(
        self,
        message_type_slug: str,
        unique_prompt: str,
        session_uuid: str,
        raw_response: Optional[str] = None,
        error_text: Optional[str] = None,
        num_tries: int = 1,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit a structured log record in place of a former DB insert.

        The signature matches the previous async DB write so existing service
        call sites change minimally. ``session_uuid`` is now a pure log
        correlation id, never persisted. ``extra`` is a new optional kwarg for
        additional JSON fields (e.g. ``{"intent_id": "primary"}``).
        """
        payload: Dict[str, Any] = {
            "correlation_id": session_uuid,
            "slug": message_type_slug,
            "attempts": num_tries,
        }
        if extra:
            payload.update(extra)
        level = logging.ERROR if error_text is not None else logging.INFO
        if level == logging.ERROR:
            payload["error"] = error_text
            self.logger.log(level, message_type_slug, extra=payload)
            return
        self.logger.log(level, message_type_slug, extra=payload)
        # DEBUG-level audit: prompt + raw response (matches the old messages row)
        debug_payload = {
            "correlation_id": session_uuid,
            "slug": message_type_slug,
            "prompt": unique_prompt,
            "raw_response": raw_response,
            "attempts": num_tries,
        }
        if extra:
            debug_payload.update(extra)
        self.logger.debug(message_type_slug, extra=debug_payload)

    def parse_message(self, aimessage: AIMessage, message_type_slug: str) -> Dict[str, Any]:
        """Parse an AIMessage against the registered schema for a slug.

        Args:
            aimessage: AIMessage containing a raw response.
            message_type_slug: Slug whose registered request schema drives parsing.

        Returns:
            Parsed and validated response dictionary.
        """
        message_type = self.registry.get(message_type_slug)
        schema = message_type.request_schema
        return aimessage.get_parsed_response(schema)