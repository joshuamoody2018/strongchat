"""Enums for message types and creator types"""

from enum import Enum
from typing import Dict, Any

class MessageType(str, Enum):
    """Message types for different pipeline steps"""
    INTENT_CLASSIFICATION = "intent_classification"
    # Future message types can be added here
    # INITIAL_PROMPT = "initial_prompt"
    # HYDE = "hyde"
    # RESPONSE_SYNTHESIS = "response_synthesis"

class CreatorType(str, Enum):
    """Creator types for messages"""
    HUMAN = "human"
    PROGRAMMATIC = "programmatic"
    LLM = "llm"

# Legacy mapping for backward compatibility
LEGACY_MESSAGE_MAPPING = {
    "initial_prompt": MessageType.INITENT_CLASSIFICATION,
    "intent_classification": MessageType.INTENT_CLASSIFICATION,
    "hyde": MessageType.INITENT_CLASSIFICATION,  # Placeholder
}