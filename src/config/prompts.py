"""Prompt templates for LLM interactions"""

INTENT_DISAMBIGUATION_PROMPT = """
Analyze the following query to identify possible interpretations and ambiguities.

Query: "{query}"

Please provide a structured analysis identifying different ways this query could be interpreted, including:
- What parts of the query might be ambiguous
- Multiple possible interpretations
- Keywords that would be relevant for each interpretation

Format your response as valid JSON matching the expected schema.
"""

# Future prompts can be added here
# HYDE_GENERATION_PROMPT = """
# Based on the following interpretation, generate a hypothetical biblical passage:
# """

# RESPONSE_SYNTHESIS_PROMPT = """
# """