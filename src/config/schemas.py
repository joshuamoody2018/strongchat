"""JSON schemas for LLM response validation"""

INTENT_DISAMBIGUATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "title": "IntentDisambiguationResponse",
    "description": "Structured disambiguation of user query for biblical search",
    "properties": {
        "query_analysis": {
            "type": "object",
            "properties": {
                "original_query": {"type": "string"},
                "ambiguous_elements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Parts of query that could mean multiple things"
                },
                "core_question": {"type": "string"},
                "context_clues": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["original_query", "ambiguous_elements", "core_question", "context_clues"]
        },
        "interpretive_framings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "framing_id": {"type": "string"},
                    "interpretation": {
                        "type": "string",
                        "description": "Plain-language interpretation of what the user is asking"
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords for embedding search"
                    },
                    "disambiguation_note": {
                        "type": "string",
                        "description": "Why this interpretation resolves the ambiguity"
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                },
                "required": ["framing_id", "interpretation", "keywords", "disambiguation_note", "confidence"]
            },
            "minItems": 2,
            "maxItems": 5
        },
        "recommended_framing": {
            "type": "string",
            "description": "Framing_id of the most likely interpretation"
        }
    },
    "required": ["query_analysis", "interpretive_framings", "recommended_framing"]
}

# Future schemas can be added here
# HYDE_GENERATION_SCHEMA = {...}
# RESPONSE_SYNTHESIS_SCHEMA = {...}