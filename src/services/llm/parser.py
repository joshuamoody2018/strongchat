"""Automated JSON response parser with validation"""

import json
from typing import Any, Dict, Type, TypeVar
from jsonschema import validate, ValidationError
from .exceptions import ResponseValidationError, ResponseParsingError

T = TypeVar('T', bound='BaseResponseModel')

class BaseResponseModel:
    """Base class for parsed LLM responses"""
    
    @classmethod
    def from_json(cls: Type[T], json_data: Dict[str, Any]) -> T:
        """Parse JSON data into response model"""
        return cls(**json_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert response model to dictionary"""
        return self.__dict__
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_dict()})"

class IntentDisambiguationResponse(BaseResponseModel):
    """Parsed intent disambiguation response"""
    
    def __init__(
        self,
        query_analysis: Dict[str, Any],
        interpretive_framings: list,
        recommended_framing: str
    ):
        self.query_analysis = query_analysis
        self.interpretive_framings = interpretive_framings
        self.recommended_framing = recommended_framing

class ResponseParser:
    """Automated parser for LLM responses with schema validation"""
    
    def __init__(self, schema: Dict[str, Any], response_model: Type[BaseResponseModel]):
        self.schema = schema
        self.response_model = response_model
    
    def parse(self, response_text: str) -> BaseResponseModel:
        """Parse raw LLM response into structured object"""
        try:
            # Extract JSON from response
            json_str = self._extract_json(response_text)
            
            # Parse JSON
            data = json.loads(json_str)
            
            # Validate against schema
            validate(data, self.schema)
            
            # Create response model
            return self.response_model.from_json(data)
            
        except json.JSONDecodeError as e:
            raise ResponseParsingError(f"JSON decode error: {e}")
        except ValidationError as e:
            raise ResponseValidationError(f"Schema validation error: {e}")
    
    def _extract_json(self, response_text: str) -> str:
        """Extract JSON content from formatted response"""
        response_text = response_text.strip()
        
        # Handle markdown JSON blocks
        if response_text.startswith('```json'):
            return response_text.split('```json')[1].split('```')[0].strip()
        elif response_text.startswith('```'):
            # Check if it's JSON block
            content = response_text.split('```')[1].strip()
            try:
                json.loads(content)
                return content
            except json.JSONDecodeError:
                # Not JSON, continue with other extraction methods
                pass
        
        # Handle JSON at the beginning/end of response
        first_brace = response_text.find('{')
        last_brace = response_text.rfind('}')
        
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            return response_text[first_brace:last_brace + 1]
        
        # If no JSON found, assume the entire response is JSON
        return response_text