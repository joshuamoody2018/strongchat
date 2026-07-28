"""Database port (protocol) for StrongChat services.

`DatabasePort` defines the async surface that pipeline services expect from any
backing database. A future hosted database (e.g., PostgreSQL with asyncpg) can
implement this protocol and be injected without changing service code.
"""
from typing import Any, Dict, List, Optional, Protocol, Tuple


class DatabasePort(Protocol):
    """Async database contract used by StrongChat services."""

    async def create_session(self, name: str, created_by: str = "user") -> str:
        """Create a new chat session and return its UUID."""
        ...

    async def create_message_with_type(
        self,
        session_uuid: str,
        message_type_slug: str,
        unique_prompt: str,
        raw_response: Optional[str] = None,
        num_tries: int = 1,
        error_text: Optional[str] = None,
    ) -> str:
        """Create a typed message and return its UUID."""
        ...

    async def get_message_by_uuid(
        self, message_uuid: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single message by UUID, or None if missing."""
        ...

    async def get_messages_by_session_and_type(
        self,
        session_uuid: str,
        message_type_slug: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch messages for a session, optionally filtered by type."""
        ...

    async def get_message_type(
        self, slug: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch an active message type configuration by slug."""
        ...

    async def get_active_message_types(self) -> List[Dict[str, Any]]:
        """Fetch all active message type configurations."""
        ...

    async def get_session_name(
        self, session_uuid: str
    ) -> Optional[str]:
        """Fetch a session name by UUID, or None if missing."""
        ...

    async def get_sessions(self) -> List[Tuple[str, str, str]]:
        """Fetch all sessions as (uuid, name, created_on) tuples."""
        ...

    async def close(self) -> None:
        """Release database resources."""
        ...

    async def __aenter__(self) -> "DatabasePort":
        """Async context manager entry."""
        ...

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Async context manager exit."""
        ...
