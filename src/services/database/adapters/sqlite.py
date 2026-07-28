"""Async SQLite adapter implementing ``DatabasePort``.

The adapter wraps the synchronous :class:`services.sqlite.database.ChatDatabase`
and runs every operation in ``asyncio.to_thread``, giving services an async
interface without changing the underlying SQLite code.
"""
import asyncio
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from services.database.port import DatabasePort
from services.sqlite.database import ChatDatabase


class _ThreadSafeChatDatabase(ChatDatabase):
    """ChatDatabase whose connection can be used from worker threads.

    Python's default ``sqlite3`` module refuses to use a connection created in
    one thread from another thread. ``asyncio.to_thread`` dispatches work to a
    thread pool, so we open the underlying connection with
    ``check_same_thread=False``. Calls are still serialized by awaiting each
    async method, so the connection is never used concurrently.
    """

    def __init__(self, db_path: str) -> None:
        super().__init__(db_path, check_same_thread=False)


class AsyncSQLiteDatabase:
    """Threaded async wrapper around ``ChatDatabase``.

    All operations are serialized with an ``asyncio.Lock`` so that the
    underlying cursor is never used recursively by concurrent tasks.
    """

    def __init__(self, db_path: str) -> None:
        self._db = _ThreadSafeChatDatabase(db_path)
        self._lock = asyncio.Lock()

    async def _run(self, fn, *args, **kwargs):
        """Run a synchronous database function under the instance lock."""
        async with self._lock:
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def create_session(
        self, name: str, created_by: str = "user"
    ) -> str:
        return await self._run(self._db.create_session, name, created_by)

    async def create_message_with_type(
        self,
        session_uuid: str,
        message_type_slug: str,
        unique_prompt: str,
        raw_response: Optional[str] = None,
        num_tries: int = 1,
        error_text: Optional[str] = None,
    ) -> str:
        return await self._run(
            self._db.create_message_with_type,
            session_uuid,
            message_type_slug,
            unique_prompt,
            raw_response,
            num_tries,
            error_text,
        )

    async def get_message_by_uuid(
        self, message_uuid: str
    ) -> Optional[Dict[str, Any]]:
        return await self._run(self._db.get_message_by_uuid, message_uuid)

    async def get_messages_by_session_and_type(
        self,
        session_uuid: str,
        message_type_slug: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await self._run(
            self._db.get_messages_by_session_and_type,
            session_uuid,
            message_type_slug,
        )

    async def get_message_type(
        self, slug: str
    ) -> Optional[Dict[str, Any]]:
        return await self._run(self._db.get_message_type, slug)

    async def get_active_message_types(self) -> List[Dict[str, Any]]:
        return await self._run(self._db.get_active_message_types)

    async def get_session_name(
        self, session_uuid: str
    ) -> Optional[str]:
        return await self._run(self._db.get_session_name, session_uuid)

    async def get_sessions(self) -> List[Tuple[str, str, str]]:
        return await self._run(self._db.get_sessions)

    async def close(self) -> None:
        await self._run(self._db.close)

    async def __aenter__(self) -> DatabasePort:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        await self.close()
