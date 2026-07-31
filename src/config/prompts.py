"""Prompt templates for LLM interactions"""

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

INTENT_GENERATION_PROMPT = """Analyze the following user query.

Query: {query}

Return ONLY complete, valid JSON matching the schema.

Rules:
- The "query_analysis" section must describe the user's request in plain language.
- "core_questions" must contain at least one question the user is asking.
- "context_clues" must always be present. Include any explicit context (e.g., names, places, time references) from the query; if there are none, use an empty array [].
- "keywords_explicit" must contain only words that appear verbatim in the query.
- "keywords_inferred" must contain related words or concepts that do NOT appear verbatim in the query.
- Each intent must have 1 to 3 short "themes" labels.
- Provide 1 to 5 distinct intents that represent different plausible readings of the query.
- Every intent must include the "is_primary" field (true or false). Exactly one intent across the entire list must have "is_primary": true.

Response format:
{{
  "query_analysis": {{
    "original_query": "<user query>",
    "core_questions": ["what the user is asking"],
    "context_clues": ["any contextual hints"]
  }},
  "intents": [
    {{
      "intent_id": "primary",
      "interpretation": "plain-language interpretation",
      "keywords_explicit": ["verbatim", "from", "query"],
      "keywords_inferred": ["related", "not", "in", "query"],
      "themes": ["theme one"],
      "confidence": 0.9,
      "is_primary": true
    }},
    {{
      "intent_id": "secondary",
      "interpretation": "another plausible reading of the query",
      "keywords_explicit": ["other", "query", "words"],
      "keywords_inferred": ["inferred", "terms", "not", "verbatim"],
      "themes": ["theme two"],
      "confidence": 0.6,
      "is_primary": false
    }}
  ],
  "recommended_search_approach": "brief description"
}}"""

HYDE_GENERATION_PROMPT = """You are given exactly one intent, serialized as JSON, that captures an interpretation of a user's question, along with keywords and themes.

Intent:
{query}

Using only the information in this intent, write a 100-200 word hypothetical passage in the style of an English Bible: modern English prose with biblical cadence, as if it were a verse or short chapter that contains the answer. Do not include the original user query, and do not add commentary outside the passage.

Respond with ONLY complete, valid JSON matching this schema:
{{
  "hyde_document": "<the hypothetical passage>"
}}"""

# RESPONSE_SYNTHESIS_PROMPT = """
# """

# RESPONSE_SYNTHESIS_PROMPT = """
# """