"""LLMWrapper with schema-driven approach and retry logic"""

import asyncio
import aiohttp
import logging
import json
from typing import Dict, Any, Optional
from datetime import datetime

from .aimessage import AIMessage
from ..sqlite.database import ChatDatabase
from services.database.adapters.sqlite import AsyncSQLiteDatabase
from config.cache import GlobalReferenceCache
from .exceptions import (
    APITimeoutError, APIConnectionError, APIResponseError,
    MaxRetriesExceededError, ConfigurationError, ModelNotFoundError
)

logger = logging.getLogger(__name__)

class LLMWrapper:
    """LLM wrapper with database-driven configuration and retry logic"""
    
    def __init__(self, db_path: str = 'data/chat_database.db'):
        """Initialize LLM wrapper with database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db = ChatDatabase(db_path)
        self.db_port = AsyncSQLiteDatabase(db_path)
        self.cache = GlobalReferenceCache()
        self.base_url = "https://openrouter.ai/api/v1"
        self.timeout = 30.0
        
        # Set up API configuration
        self._setup_api_config()
    
    def _setup_api_config(self):
        """Set up API configuration from environment"""
        import os
        
        self.api_key = os.getenv('OPENROUTER_API_KEY')
        if not self.api_key or self.api_key == 'your_openrouter_api_key_here':
            raise ConfigurationError("OpenRouter API key not configured")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "StrongChat"
        }
    
    async def call_api(self, message_type_slug: str, unique_prompt: str, 
                        session_uuid: str) -> AIMessage:
        """Call LLM API with database-driven configuration and retry logic.
        
        Args:
            message_type_slug: Slug of the message type from database
            unique_prompt: The core message content
            session_uuid: UUID of the session
            
        Returns:
            AIMessage object with the result
            
        Raises:
            MaxRetriesExceededError: If max retries are exceeded
        """
        # Get message type configuration from cache
        message_type = self.cache.get_message_type(message_type_slug)
        if not message_type:
            raise ValueError(f"Message type '{message_type_slug}' not found or inactive")
        
        max_retries = message_type['max_retries']
        
        # Get prompt template if available
        prompt_template = message_type.get('prompt_template')
        if prompt_template:
            # Format the prompt with the unique_prompt
            formatted_prompt = prompt_template.format(query=unique_prompt)
        else:
            formatted_prompt = unique_prompt
        
        # Create AIMessage object to track retries
        aimessage = AIMessage(
            session_uuid=session_uuid,
            message_type_slug=message_type_slug,
            unique_prompt=unique_prompt
        )
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Make API call with formatted prompt
                raw_response = await self._call_api_async(
                    prompt=formatted_prompt,
                    model=message_type['model_slug'],
                    temperature=message_type['temperature'],
                    additional_settings=message_type['additional_model_settings']
                )
                
                # Mark success
                aimessage.mark_success(raw_response)
                
                # Save successful message to database
                await self.db_port.create_message_with_type(
                    session_uuid=session_uuid,
                    message_type_slug=message_type_slug,
                    unique_prompt=unique_prompt,
                    raw_response=raw_response,
                    num_tries=aimessage.num_tries
                )
                
                return aimessage
                
            except (APITimeoutError, APIConnectionError) as e:
                last_error = e
                aimessage.mark_failure(str(e), increment_tries=True)
                
                if attempt < max_retries - 1:
                    backoff_time = min(1.0 * (2 ** attempt), 30.0)
                    logger.warning(f"API call failed, retrying in {backoff_time}s: {e}")
                    await asyncio.sleep(backoff_time)
                else:
                    # Final attempt failed - save failure to database
                    await self.db_port.create_message_with_type(
                        session_uuid=session_uuid,
                        message_type_slug=message_type_slug,
                        unique_prompt=unique_prompt,
                        num_tries=aimessage.num_tries,
                        error_text=str(e)
                    )
                    logger.error(f"API call failed after {max_retries} attempts: {e}")
                    raise MaxRetriesExceededError(f"API call failed after {max_retries} attempts: {e}")
                
            except Exception as e:
                # Other errors - mark failure and save
                aimessage.mark_failure(str(e), increment_tries=True)
                await self.db_port.create_message_with_type(
                    session_uuid=session_uuid,
                    message_type_slug=message_type_slug,
                    unique_prompt=unique_prompt,
                    num_tries=aimessage.num_tries,
                    error_text=str(e)
                )
                raise
        
        raise MaxRetriesExceededError(f"Max retries exceeded for message type '{message_type_slug}'")
    
    async def _call_api_async(self, prompt: str, model: str, temperature: float = 0.1,
                            additional_settings: Optional[Dict[str, Any]] = None) -> str:
        """Async API call using aiohttp.
        
        Args:
            prompt: The prompt to send
            model: Model slug
            temperature: Temperature setting
            additional_settings: Additional model settings
            
        Returns:
            Raw response text
            
        Raises:
            APITimeoutError: If timeout occurs
            APIConnectionError: If connection fails
            APIResponseError: If API returns error
            ModelNotFoundError: If model not found
        """
        url = f"{self.base_url}/chat/completions"
        
        # Build payload with additional settings
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature
        }
        
        # Merge additional settings
        if additional_settings:
            payload.update(additional_settings)
        
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
    
    def sync_call_api(self, message_type_slug: str, unique_prompt: str, 
                     session_uuid: str) -> AIMessage:
        """Synchronous wrapper for API call.
        
        Args:
            message_type_slug: Slug of the message type from database
            unique_prompt: The core message content
            session_uuid: UUID of the session
            
        Returns:
            AIMessage object with the result
        """
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.call_api(message_type_slug, unique_prompt, session_uuid)
        )
    
    def close(self):
        """Close both synchronous and asynchronous database connections and cache."""
        self.db.close()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.db_port.close())
        else:
            asyncio.create_task(self.db_port.close())
        self.cache.close()