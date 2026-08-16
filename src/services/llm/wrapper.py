"""LLMWrapper with schema-driven approach, retry logic, and structured logging.

No application database. Audit trail is JSONL log records keyed by
``correlation_id`` (the parameter previously named ``session_uuid``); the field
is threaded through service signatures unchanged so existing call sites stay
stable, but it is no longer persisted anywhere — it is purely a log correlation
id so multi-instance interleaved logs can be sliced per pipeline run.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import aiohttp

from config.logging import get_logger
from config.registry import MessageTypeDefRegistry, DEFAULT_REGISTRY
from services.llm.aimessage import AIMessage
from services.llm.exceptions import (
    APIConnectionError,
    APIResponseError,
    APITimeoutError,
    ConfigurationError,
    MaxRetriesExceededError,
    ModelNotFoundError,
)


class LLMWrapper:
    """LLM wrapper with registry-driven configuration and retry logic."""

    def __init__(
        self,
        registry: Optional[MessageTypeDefRegistry] = None,
    ) -> None:
        """Initialize the wrapper.

        Args:
            registry: Optional overridden :class:`MessageTypeDefRegistry`.
                Defaults to the process-wide singleton built at import time.
        """
        self.registry = registry or DEFAULT_REGISTRY
        self.logger = get_logger("strongchat.llm")
        self.base_url = "https://openrouter.ai/api/v1"
        self.timeout = 30.0
        self._setup_api_config()

    def _setup_api_config(self) -> None:
        """Set up API configuration from environment."""
        self.api_key = os.getenv("OPENROUTER_STRONGCHAT_DEFAULT_API_KEY")
        if not self.api_key or self.api_key == "your_OPENROUTER_STRONGCHAT_DEFAULT_API_KEY_here":
            raise ConfigurationError("OpenRouter API key not configured")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "StrongChat",
        }

    async def call_api(
        self,
        message_type_slug: str,
        unique_prompt: str,
        session_uuid: str,
    ) -> AIMessage:
        """Call the LLM API with registry-driven configuration and retry logic.

        Args:
            message_type_slug: Slug of the message type from the registry.
            unique_prompt: The core message content.
            session_uuid: Log-only correlation id (no longer persisted).

        Returns:
            AIMessage object with the result.

        Raises:
            MaxRetriesExceededError: If max retries are exceeded.
        """
        message_type = self.registry.get(message_type_slug)
        max_retries = message_type.max_retries

        prompt_template = message_type.prompt_template
        if prompt_template:
            formatted_prompt = prompt_template.format(query=unique_prompt)
        else:
            formatted_prompt = unique_prompt

        aimessage = AIMessage(
            session_uuid=session_uuid,
            message_type_slug=message_type_slug,
            unique_prompt=unique_prompt,
        )

        started = time.monotonic()
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                raw_response = await self._call_api_async(
                    prompt=formatted_prompt,
                    model=message_type.model_slug,
                    temperature=message_type.temperature,
                    additional_settings=message_type.additional_model_settings,
                )

                try:
                    aimessage.mark_success_from_text(
                        raw_response,
                        schema=message_type.request_schema,
                    )
                except ValueError as parse_error:
                    raise APIResponseError(str(parse_error)) from parse_error

                elapsed_ms = int((time.monotonic() - started) * 1000)
                self.logger.info(
                    message_type_slug,
                    extra={
                        "event": "llm_call",
                        "correlation_id": session_uuid,
                        "slug": message_type_slug,
                        "attempts": attempt + 1,
                        "elapsed_ms": elapsed_ms,
                        "status": "ok",
                    },
                )
                self.logger.debug(
                    message_type_slug,
                    extra={
                        "event": "llm_call_audit",
                        "correlation_id": session_uuid,
                        "slug": message_type_slug,
                        "prompt": unique_prompt,
                        "raw_response": aimessage.raw_response,
                        "attempts": attempt + 1,
                    },
                )
                return aimessage

            except (APITimeoutError, APIConnectionError, APIResponseError) as e:
                last_error = e
                aimessage.mark_failure(str(e), increment_tries=True)
                if attempt < max_retries - 1:
                    backoff_time = min(1.0 * (2 ** attempt), 30.0)
                    self.logger.warning(
                        message_type_slug,
                        extra={
                            "event": "llm_call_retry",
                            "correlation_id": session_uuid,
                            "slug": message_type_slug,
                            "attempt": attempt + 1,
                            "backoff_ms": int(backoff_time * 1000),
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(backoff_time)
                else:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    self.logger.error(
                        message_type_slug,
                        extra={
                            "event": "llm_call",
                            "correlation_id": session_uuid,
                            "slug": message_type_slug,
                            "attempts": aimessage.num_tries,
                            "elapsed_ms": elapsed_ms,
                            "status": "error",
                            "error": str(e),
                        },
                    )
                    self.logger.debug(
                        message_type_slug,
                        extra={
                            "event": "llm_call_audit",
                            "correlation_id": session_uuid,
                            "slug": message_type_slug,
                            "prompt": unique_prompt,
                            "raw_response": None,
                            "attempts": aimessage.num_tries,
                            "error": str(e),
                        },
                    )
                    raise MaxRetriesExceededError(
                        f"API call failed after {max_retries} attempts: {e}"
                    ) from e

            except Exception as e:
                aimessage.mark_failure(str(e), increment_tries=True)
                self.logger.error(
                    message_type_slug,
                    extra={
                        "event": "llm_call",
                        "correlation_id": session_uuid,
                        "slug": message_type_slug,
                        "attempts": aimessage.num_tries,
                        "status": "error",
                        "error": str(e),
                    },
                )
                raise

        raise MaxRetriesExceededError(
            f"Max retries exceeded for message type '{message_type_slug}'"
        )

    async def _call_api_async(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.1,
        additional_settings: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Async API call using aiohttp."""
        url = f"{self.base_url}/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if additional_settings:
            payload.update(additional_settings)

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(url, json=payload, headers=self.headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result["choices"][0]["message"]["content"]
                    if response.status == 401:
                        raise APIResponseError("Invalid API key")
                    if response.status == 404:
                        raise ModelNotFoundError(f"Model {model} not found")
                    error_text = await response.text()
                    raise APIResponseError(
                        f"API returned {response.status}: {error_text}"
                    )
        except asyncio.TimeoutError as exc:
            raise APITimeoutError(
                f"API call timed out after {self.timeout}s"
            ) from exc
        except aiohttp.ClientError as exc:
            raise APIConnectionError(f"API connection error: {exc}") from exc

    def close(self) -> None:
        """No resources to release; kept for backwards compatibility."""
        pass