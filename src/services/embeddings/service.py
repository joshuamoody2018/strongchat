"""Batched OpenRouter embedding service.

Provides chunked, retry-aware embedding generation with a single summary
message recorded per ``embed_texts`` call. Raw vectors are never persisted.
"""

import asyncio
import inspect
import json
import logging
from typing import Callable, List, Optional, Tuple

import aiohttp

from services.base import BaseService
from services.llm.exceptions import (
    APIConnectionError,
    APIResponseError,
    APITimeoutError,
    MaxRetriesExceededError,
)

logger = logging.getLogger(__name__)

EMBEDDING_ENDPOINT = "https://openrouter.ai/api/v1/embeddings"
DEFAULT_DIMENSION = 1536
DEFAULT_CHUNK_SIZE = 256
DEFAULT_TIMEOUT = 30.0
MAX_BACKOFF = 30.0

EmbedFn = Callable[[List[str]], List[List[float]]]


class EmbeddingService(BaseService):
    """Generate batched embeddings via OpenRouter or an injected function."""

    def __init__(
        self,
        db_path: str = "data/chat_database.db",
        embed_fn: Optional[EmbedFn] = None,
    ):
        """Initialize the embedding service.

        Args:
            db_path: Path to the SQLite database file.
            embed_fn: Optional injectable embedding function for tests.
                Signature: ``(texts: List[str]) -> List[List[float]]``.
                If None, the live OpenRouter embeddings endpoint is used.
        """
        super().__init__(db_path)
        self._embed_fn = embed_fn
        self._message_type = self.cache.get_message_type("embedding_generation")
        if not self._message_type:
            raise ValueError("Message type 'embedding_generation' not found or inactive")
        self._model_slug = self._message_type["model_slug"]
        self._max_retries = self._message_type["max_retries"]
        self._headers = self.llm.headers

    async def embed_texts(
        self,
        texts: List[str],
        session_uuid: Optional[str] = None,
        record: bool = True,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        Inputs are split into chunks of ``chunk_size`` and submitted
        sequentially. Results are concatenated in input order.

        Args:
            texts: List of input strings.
            session_uuid: Optional session UUID for recording.
            record: Whether to record an ``embedding_generation`` message.
            chunk_size: Maximum number of texts per chunk.

        Returns:
            List of embedding vectors in the same order as ``texts``.

        Raises:
            MaxRetriesExceededError: If transient errors persist after retries.
            APIResponseError: If the API returns a non-retryable error.
        """
        chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]
        results: List[List[float]] = []
        num_tries = 0

        try:
            for chunk in chunks:
                chunk_embeddings, chunk_tries = await self._embed_chunk(chunk)
                results.extend(chunk_embeddings)
                num_tries += chunk_tries

            if record and session_uuid is not None:
                raw_response = json.dumps(
                    {
                        "model": self._model_slug,
                        "dimension": DEFAULT_DIMENSION,
                        "count": len(texts),
                    }
                )
                unique_prompt = json.dumps({"texts": texts})[:4000]
                await self.record_message(
                    message_type_slug="embedding_generation",
                    unique_prompt=unique_prompt,
                    session_uuid=session_uuid,
                    raw_response=raw_response,
                    num_tries=num_tries,
                )

            return results

        except Exception as exc:
            num_tries += getattr(exc, "_embedding_attempts", 1)
            if record and session_uuid is not None:
                await self.record_message(
                    message_type_slug="embedding_generation",
                    unique_prompt=json.dumps({"texts": texts})[:4000],
                    session_uuid=session_uuid,
                    error_text=str(exc),
                    num_tries=num_tries,
                )
            raise

    def close(self) -> None:
        """Close the underlying database connection."""
        self.llm.close()

    async def _embed_chunk(self, texts: List[str]) -> Tuple[List[List[float]], int]:
        """Embed a single chunk, retrying transient failures.

        Returns:
            A tuple of (embeddings, attempts_made).
        """
        attempts = 0
        last_error: Optional[Exception] = None

        while attempts < self._max_retries:
            attempts += 1
            try:
                return await self._call_embedder_once(texts), attempts
            except (APITimeoutError, APIConnectionError) as exc:
                last_error = exc
                if attempts < self._max_retries:
                    backoff_time = min(1.0 * (2 ** (attempts - 1)), MAX_BACKOFF)
                    logger.warning(
                        "Embedding API call failed, retrying in %.1fs: %s",
                        backoff_time,
                        exc,
                    )
                    await asyncio.sleep(backoff_time)
            except Exception as exc:
                setattr(exc, "_embedding_attempts", attempts)
                raise

        err = MaxRetriesExceededError(
            f"API call failed after {self._max_retries} attempts: {last_error}"
        )
        setattr(err, "_embedding_attempts", attempts)
        raise err from last_error

    async def _call_embedder_once(self, texts: List[str]) -> List[List[float]]:
        """Call the injected function or the live OpenRouter endpoint once."""
        if self._embed_fn is not None:
            result = self._embed_fn(texts)
            if inspect.isawaitable(result):
                return await result
            return result

        return await self._post_embeddings(texts)

    async def _post_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Perform a single POST to the embeddings endpoint.

        Raises:
            APITimeoutError: On request timeout.
            APIConnectionError: On transport failure.
            APIResponseError: On non-2xx HTTP status or malformed payload count.
        """
        payload = {"model": self._model_slug, "input": texts}
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
            ) as session:
                async with session.post(
                    EMBEDDING_ENDPOINT, json=payload, headers=self._headers
                ) as response:
                    if response.status == 200:
                        body = await response.json()
                        data = body.get("data", [])
                        if not isinstance(data, list) or len(data) != len(texts):
                            raise APIResponseError(
                                f"Expected {len(texts)} embeddings, got {len(data)}"
                            )
                        sorted_data = sorted(
                            data, key=lambda item: item.get("index", 0)
                        )
                        return [item["embedding"] for item in sorted_data]
                    if response.status == 401:
                        raise APIResponseError("Invalid API key")
                    if response.status == 404:
                        raise APIResponseError(
                            f"Model {self._model_slug} not found"
                        )
                    error_text = await response.text()
                    raise APIResponseError(
                        f"API returned {response.status}: {error_text}"
                    )
        except asyncio.TimeoutError as exc:
            raise APITimeoutError(
                f"API call timed out after {DEFAULT_TIMEOUT}s"
            ) from exc
        except aiohttp.ClientError as exc:
            raise APIConnectionError(f"API connection error: {exc}") from exc
