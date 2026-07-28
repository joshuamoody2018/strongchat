"""JSON schemas for LLM response validation"""

INTENT_CLASSIFICATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "title": "IntentClassificationResponse",
    "description": "Structured classification of user intent for general query understanding",
    "properties": {
        "query_analysis": {
            "type": "object",
            "properties": {
                "original_query": {"type": "string"},
                "query_complexity": {
                    "type": "string",
                    "enum": ["simple", "moderate", "complex"],
                    "description": "How many distinct intents appear in the query"
                },
                "core_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Core questions the user is asking"
                },
                "context_clues": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["original_query", "query_complexity", "core_questions", "context_clues"]
        },
        "intents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intent_id": {"type": "string"},
                    "framing": {
                        "type": "object",
                        "properties": {
                            "perspective": {"type": "string"},
                            "context": {"type": "string"},
                            "approach": {"type": "string"}
                        },
                        "required": ["perspective", "context", "approach"]
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords for search and anchoring"
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_primary": {"type": "boolean"}
                },
                "required": ["intent_id", "framing", "keywords", "confidence", "is_primary"]
            },
            "minItems": 1,
            "maxItems": 5
        },
        "recommended_search_approach": {
            "type": "string",
            "description": "Recommended approach for combining multiple intents"
        }
    },
    "required": ["query_analysis", "intents", "recommended_search_approach"]
}

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

INTENT_GENERATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "title": "IntentGenerationResponse",
    "description": "Structured generation of multiple plain-language intents for a user query",
    "properties": {
        "query_analysis": {
            "type": "object",
            "properties": {
                "original_query": {"type": "string"},
                "core_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Core questions the user is asking"
                },
                "context_clues": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["original_query", "core_questions", "context_clues"]
        },
        "intents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intent_id": {"type": "string"},
                    "interpretation": {
                        "type": "string",
                        "description": "Plain-language interpretation of what the user is asking"
                    },
                    "keywords_explicit": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Terms that appear verbatim in the user query"
                    },
                    "keywords_inferred": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Related terms that do NOT appear verbatim in the query"
                    },
                    "themes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                        "description": "One to three short theme labels for this intent"
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_primary": {"type": "boolean"}
                },
                "required": [
                    "intent_id",
                    "interpretation",
                    "keywords_explicit",
                    "keywords_inferred",
                    "themes",
                    "confidence",
                    "is_primary"
                ]
            },
            "minItems": 1,
            "maxItems": 5
        },
        "recommended_search_approach": {
            "type": "string",
            "description": "Recommended approach for combining or prioritizing generated intents"
        }
    },
    "required": ["query_analysis", "intents", "recommended_search_approach"]
}

HYDE_GENERATION_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "title": "HydeGenerationResponse",
    "description": "A single hypothetical biblical passage generated from a single intent",
    "properties": {
        "hyde_document": {
            "type": "string",
            "minLength": 50,
            "description": "A 100-200 word hypothetical passage in modern English prose with biblical cadence"
        }
    },
    "required": ["hyde_document"]
}

# Future schemas can be added here
# RESPONSE_SYNTHESIS_SCHEMA = {...}
