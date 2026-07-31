"""Intent generation service."""

from typing import Dict, Any

from src.services.base import BaseService
from src.services.llm.aimessage import AIMessage


class IntentService(BaseService):
    """Generate structured intents from a user query."""

    async def generate_intents(self, query: str, session_uuid: str) -> Dict[str, Any]:
        """Call the LLM for intent generation and return parsed fields.

        Args:
            query: The raw user query.
            session_uuid: UUID of the parent session.

        Returns:
            Dictionary with message_uuid, query_analysis, intents, and
            recommended_search_approach.
        """
        aimessage = await self.llm.call_api('intent_generation', query, session_uuid)
        parsed = self.parse_message(aimessage, 'intent_generation')
        return {
            'message_uuid': aimessage.uuid,
            'query_analysis': parsed['query_analysis'],
            'intents': parsed['intents'],
            'recommended_search_approach': parsed['recommended_search_approach'],
        }
