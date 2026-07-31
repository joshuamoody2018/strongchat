"""Shared foundation for pipeline services."""

from typing import Dict, Any

from src.services.llm.wrapper import LLMWrapper
from src.services.llm.aimessage import AIMessage


class BaseService:
    """Minimal base for all pipeline services.

    Owns a single LLMWrapper instance and exposes its database and cache
    as aliases so downstream services can record messages and parse responses
    without re-opening connections.
    """

    def __init__(self, db_path: str = 'data/chat_database.db'):
        """Initialize the service with a single LLMWrapper.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.llm = LLMWrapper(db_path)
        self.db = self.llm.db
        self.db_port = self.llm.db_port
        self.cache = self.llm.cache

    async def record_message(
        self,
        message_type_slug: str,
        unique_prompt: str,
        session_uuid: str,
        raw_response: str = None,
        error_text: str = None,
        num_tries: int = 1,
    ) -> str:
        """Persist a message row asynchronously, returning its generated UUID.

        Args:
            message_type_slug: Message type reference slug.
            unique_prompt: The prompt or input text for the message.
            session_uuid: UUID of the parent session.
            raw_response: Optional raw LLM response text.
            error_text: Optional error text if the message failed.
            num_tries: Number of attempts made (default 1).

        Returns:
            UUID string of the created message row.
        """
        return await self.db_port.create_message_with_type(
            session_uuid=session_uuid,
            message_type_slug=message_type_slug,
            unique_prompt=unique_prompt,
            raw_response=raw_response,
            error_text=error_text,
            num_tries=num_tries,
        )

    def parse_message(self, aimessage: AIMessage, message_type_slug: str) -> Dict[str, Any]:
        """Parse an AIMessage against the cached schema for a message type.

        Args:
            aimessage: AIMessage containing a raw response.
            message_type_slug: Slug whose cached request schema drives parsing.

        Returns:
            Parsed and validated response dictionary.
        """
        message_type = self.cache.get_message_type(message_type_slug)
        schema = message_type['request_schema']
        return aimessage.get_parsed_response(schema)
