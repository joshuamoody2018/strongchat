"""LLM client with async support, retry logic, and response validation"""

import asyncio
import logging
from typing import Dict, Any, Optional, Type
from jsonschema import validate, ValidationError
import aiohttp
import time
from .exceptions import (
    APITimeoutError, APIConnectionError, APIResponseError,
    ResponseValidationError, ResponseParsingError, MaxRetriesExceededError,
    ConfigurationError, ModelNotFoundError
)
from .parser import ResponseParser, BaseResponseModel, IntentDisambiguationResponse
from config.schemas import INTENT_DISAMBIGUATION_SCHEMA
from config.prompts import INTENT_DISAMBIGUATION_PROMPT

logger = logging.getLogger(__name__)

class LLMClient:
    """LLM client with async support, retry logic, and response validation"""
    
    def __init__(self, model_config: Optional[Dict[str, Any]] = None):
        self.model_config = model_config or {}
        self.max_retries = 3  # Constant for max retries
        self.initial_backoff = 1.0
        self.max_backoff = 30.0
        self.timeout = 30.0
        
        # Initialize parsers for different response types
        self.parsers = {
            "intent_disambiguation": ResponseParser(
                INTENT_DISAMBIGUATION_SCHEMA,
                self._get_response_model("IntentDisambiguationResponse")
            )
        }
        
        # Set up API configuration
        self._setup_api_config()
    
    def _setup_api_config(self):
        """Set up API configuration from environment"""
        import os
        
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.api_key or self.api_key == 'your_openrouter_api_key_here':
            raise ConfigurationError("OpenRouter API key not configured")
        
        self.base_url = "https://openrouter.ai/api/v1"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "StrongChat"
        }
    
    def _get_response_model(self, model_name: str) -> Type[BaseResponseModel]:
        """Get response model class by name"""
        if model_name == "IntentDisambiguationResponse":
            from .parser import IntentDisambiguationResponse
            return IntentDisambiguationResponse
        else:
            raise ValueError(f"Unknown response model: {model_name}")
    
    async def call_with_schema(
        self,
        prompt_template: str,
        response_schema: Dict[str, Any],
        response_model_name: str,
        **prompt_vars
    ) -> BaseResponseModel:
        """Call LLM with exponential backoff and response validation"""
        
        prompt = prompt_template.format(**prompt_vars)
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                # Call API with async
                raw_response = await self._call_api_async(prompt)
                
                # Parse and validate response
                parser = self.parsers.get(response_model_name)
                if not parser:
                    raise ValueError(f"Unknown response model: {response_model_name}")
                
                response = parser.parse(raw_response)
                return response
                
            except (APITimeoutError, APIConnectionError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    backoff_time = min(self.initial_backoff * (2 ** attempt), self.max_backoff)
                    logger.warning(f"API call failed, retrying in {backoff_time}s: {e}")
                    await asyncio.sleep(backoff_time)
                else:
                    # After final retry, go to error route
                    logger.error(f"API call failed after {self.max_retries} attempts: {e}")
                    self._error_handler(e, prompt)
                    raise MaxRetriesExceededError(f"API call failed after {self.max_retries} attempts: {e}")
                continue
                
            except ResponseValidationError as e:
                logger.error(f"Response validation failed: {e}")
                self._validation_error_handler(e)
                raise
                
            except ResponseParsingError as e:
                logger.error(f"Response parsing failed: {e}")
                self._validation_error_handler(e)
                raise
        
        raise MaxRetriesExceededError(f"Max retries exceeded for prompt: {prompt[:100]}...")
    
    def _validation_error_handler(self, error: ResponseValidationError):
        """Handle validation errors (emit to stderr for now)"""
        import sys
        print(f"VALIDATION_ERROR: {error}", file=sys.stderr)
    
    def _error_handler(self, error: Exception, prompt: str):
        """Handle errors after max retries reached (emit to stderr for now)"""
        import sys
        print(f"ERROR_HANDLER: {error} - Prompt: {prompt[:100]}...", file=sys.stderr)
    
    async def _call_api_async(self, prompt: str, model: str = "openai/gpt-3.5-turbo") -> str:
        """Async API call using aiohttp"""
        
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1
        }
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(url, json=payload, headers=self.headers) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        return result['choices'][0]['message']['content']
                    elif response.status == 401:
                        raise APIResponseError("Invalid API key")
                    elif response.status == 404:
                        raise ModelNotFoundError(f"Model {model} not found")
                    else:
                        error_text = await response.text()
                        raise APIResponseError(f"API returned {response.status}: {error_text}")
                        
        except asyncio.TimeoutError:
            raise APITimeoutError(f"API call timed out after {self.timeout}s")
        except aiohttp.ClientError as e:
            raise APIConnectionError(f"API connection error: {e}")
    
    async def disambiguate_intent(self, query: str) -> IntentDisambiguationResponse:
        """Convenience method for intent disambiguation"""
        return await self.call_with_schema(
            INTENT_DISAMBIGUATION_PROMPT,
            INTENT_DISAMBIGUATION_SCHEMA,
            "intent_disambiguation",
            query=query
        )
    
    def sync_disambiguate_intent(self, query: str) -> IntentDisambiguationResponse:
        """Synchronous wrapper for intent disambiguation"""
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.disambiguate_intent(query))