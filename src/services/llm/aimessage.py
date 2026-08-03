"""AIMessage dataclass with response parsing capabilities"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from jsonschema import validate, ValidationError

# Match a leading ```json or ``` fence optionally followed by a language tag
# (e.g. ```JSON), capturing the inner body up to the closing ```.
_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?[ \t]*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)


def canonicalize_json(value: Any) -> str:
    """Return a stable, fence-free JSON string for a parsed value.

    Uses ``sort_keys=True`` and compact separators so identical payloads
    produce byte-identical audit strings across runs.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _extract_strict_json(response_text: str) -> str:
    """Return the JSON substring for *response_text*, enforcing JSON-only.

    Allowed shapes:
      * pure JSON (optionally surrounded by whitespace)
      * a single ```json / ``` fence whose inner body is pure JSON

    Anything else raises ``ValueError`` — including prose like
    "Here is the response: {...}" that _used_ to be silently sliced.
    """
    if response_text is None:
        raise ValueError("Response is None")

    candidate = response_text.strip()
    if not candidate:
        raise ValueError("Response is empty")

    fence_match = _FENCE_RE.match(candidate)
    if fence_match is not None:
        before = candidate[: fence_match.start()]
        after = candidate[fence_match.end() :]
        if before.strip() or after.strip():
            raise ValueError(
                "Response contains non-whitespace characters outside the JSON fence"
            )
        body = fence_match.group(1).strip()
        try:
            json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Fenced response is not valid JSON: {exc}") from exc
        return body

    try:
        json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}") from exc
    return candidate


@dataclass
class AIMessage:
    """Represents an AI message with full tracking and parsing capabilities.

    Successful messages hold the parsed response as a native Python dict in
    memory (``parsed_response``) and a canonical, fence-free JSON string in
    ``raw_response`` for the audit log. Both fields stay in sync.
    """

    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_uuid: Optional[str] = None
    message_type_slug: str = ""
    unique_prompt: str = ""
    raw_response: Optional[str] = None
    parsed_response: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)
    response_at: Optional[datetime] = None
    num_tries: int = 1
    error_text: Optional[str] = None

    def get_parsed_response(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Return the parsed response, validating against *schema*.

        Uses the cached ``parsed_response`` when present; otherwise
        re-parses ``raw_response`` (which is itself canonical JSON).
        """
        if self.parsed_response is not None:
            data = self.parsed_response
        elif self.raw_response is not None:
            try:
                data = json.loads(self.raw_response)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Stored raw_response is not valid JSON: {exc}") from exc
        else:
            raise ValueError("No raw response available for parsing")

        try:
            validate(data, schema)
        except ValidationError as exc:
            raise ValueError(f"Schema validation error: {exc}") from exc
        return data

    def mark_success_from_text(self, response_text: str, schema: Optional[Dict[str, Any]] = None) -> None:
        """Mark the message successful using *response_text* from the provider.

        Strips markdown JSON fences if present and rejects responses that
        still contain non-whitespace residue (prose) outside the JSON body.
        When *schema* is supplied the parsed dict is validated and stored
        on ``parsed_response``; ``raw_response`` is the canonical JSON
        serialization of that dict.
        """
        json_str = _extract_strict_json(response_text)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Response is not valid JSON: {exc}") from exc

        if schema is not None:
            try:
                validate(data, schema)
            except ValidationError as exc:
                raise ValueError(f"Schema validation error: {exc}") from exc

        self.parsed_response = data if isinstance(data, dict) else None
        self.raw_response = canonicalize_json(data)
        self.response_at = datetime.now()
        self.error_text = None

    def mark_failure(self, error: str, increment_tries: bool = True) -> None:
        """Mark message as failed with error"""
        if increment_tries:
            self.num_tries += 1
        self.error_text = error
        if not self.response_at:
            self.response_at = datetime.now()
