"""Prompt templates for LLM interactions"""

INTENT_DISAMBIGUATION_PROMPT = """
Analyze the following query to identify possible interpretations and ambiguities:

Query: "{query}"

Please provide a structured analysis identifying different ways this query could be interpreted, including:
- What parts of the query might be ambiguous
- Multiple possible interpretations
- Keywords that would be relevant for each interpretation

Format your response as valid JSON matching the expected schema.
"""

INTENT_CLASSIFICATION_PROMPT = """Classify the following query into structured intents. Return ONLY complete JSON.

Query: {query}

Response format:
{{
  "query_analysis": {{
    "original_query": "{query}",
    "query_complexity": "simple|moderate|complex",
    "core_questions": ["q1", "q2"],
    "context_clues": ["c1", "c2"]
  }},
  "intents": [
    {{
      "intent_id": "id1",
      "framing": {{
        "perspective": "personal|theological|historical|doctrinal",
        "context": "general|specific|academic|personal", 
        "approach": "expository|analytical|practical|comparative"
      }},
      "keywords": ["kw1", "kw2", "kw3"],
      "confidence": 0.9,
      "is_primary": true
    }}
  ],
  "recommended_search_approach": "approach description"
}}"""

# Future prompts can be added here
# HYDE_GENERATION_PROMPT = """
# Based on the following interpretation, generate a hypothetical biblical passage:
# """

# RESPONSE_SYNTHESIS_PROMPT = """
# """

# RESPONSE_SYNTHESIS_PROMPT = """
# """