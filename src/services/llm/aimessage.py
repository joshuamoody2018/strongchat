"""AIMessage dataclass with response parsing capabilities"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional
from jsonschema import validate, ValidationError

@dataclass
class AIMessage:
    """Represents an AI message with full tracking and parsing capabilities"""
    
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_uuid: Optional[str] = None
    message_type_slug: str = ""
    unique_prompt: str = ""
    raw_response: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    response_at: Optional[datetime] = None
    num_tries: int = 1
    error_text: Optional[str] = None
    
    def get_parsed_response(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Parse raw response using provided schema"""
        if not self.raw_response:
            raise ValueError("No raw response available for parsing")
        
        try:
            # Extract JSON from response
            json_str = self._extract_json(self.raw_response)
            data = json.loads(json_str)
            
            # Validate against schema
            validate(data, schema)
            
            return data
            
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON decode error: {e}")
        except ValidationError as e:
            raise ValueError(f"Schema validation error: {e}")
    
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
    
    def mark_success(self, response: str):
        """Mark message as successful with response"""
        self.raw_response = response
        self.response_at = datetime.now()
        self.error_text = None
    
    def mark_failure(self, error: str, increment_tries: bool = True):
        """Mark message as failed with error"""
        if increment_tries:
            self.num_tries += 1
        self.error_text = error
        if not self.response_at:
            self.response_at = datetime.now()
    
    def is_successful(self) -> bool:
        """Check if message was successful"""
        return self.raw_response is not None and self.error_text is None
    
    def max_retries_exceeded(self, max_retries: int) -> bool:
        """Check if max retries have been exceeded"""
        return self.num_tries >= max_retries