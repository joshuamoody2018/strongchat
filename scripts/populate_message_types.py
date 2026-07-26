#!/usr/bin/env python3
"""Populate message_types table with existing schemas"""

import sqlite3
import json

def populate_message_types(db_path: str = 'data/chat_database.db'):
    """Populate message_types table with existing schemas."""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Intent Classification (already exists, but let's update it)
    intent_schema = {
        "slug": "intent_classification",
        "step_name": "Intent Classification",
        "creator_type": "programmatic",
        "request_schema": json.dumps({
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "IntentClassificationResponse",
            "description": "Classification of user intent",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "Primary intent classification",
                    "enum": ["greeting", "question", "statement", "command", "goodbye", "help"]
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Confidence score for the classification"
                }
            },
            "required": ["intent", "confidence"]
        }),
        "model_slug": "openai/gpt-3.5-turbo",
        "temperature": 0.1,
        "additional_model_settings": json.dumps({"max_tokens": 100}),
        "max_retries": 3,
        "is_active": True,
        "description": "Classify user message intent for biblical search"
    }
    
    # Intent Disambiguation (from existing parser)
    intent_disambiguation_schema = {
        "slug": "intent_disambiguation",
        "step_name": "Intent Disambiguation",
        "creator_type": "programmatic",
        "request_schema": json.dumps({
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
        }),
        "model_slug": "openai/gpt-3.5-turbo",
        "temperature": 0.2,
        "additional_model_settings": json.dumps({"max_tokens": 500}),
        "max_retries": 3,
        "is_active": True,
        "description": "Disambiguate user queries to identify multiple possible interpretations"
    }
    
    message_types = [intent_schema, intent_disambiguation_schema]
    
    # Insert or update message types
    for msg_type in message_types:
        cursor.execute('''
            INSERT OR REPLACE INTO message_types 
            (slug, step_name, creator_type, request_schema, model_slug, temperature, 
             additional_model_settings, max_retries, is_active, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            msg_type["slug"],
            msg_type["step_name"],
            msg_type["creator_type"],
            msg_type["request_schema"],
            msg_type["model_slug"],
            msg_type["temperature"],
            msg_type["additional_model_settings"],
            msg_type["max_retries"],
            msg_type["is_active"],
            msg_type["description"]
        ))
    
    conn.commit()
    conn.close()
    print(f"Populated {len(message_types)} message types successfully!")

if __name__ == "__main__":
    populate_message_types()