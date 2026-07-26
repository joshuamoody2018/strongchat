"""Exception classes for LLM service"""

class LLMError(Exception):
    """Base LLM error"""
    pass

class APITimeoutError(LLMError):
    """API timeout error"""
    pass

class APIConnectionError(LLMError):
    """API connection error"""
    pass

class APIResponseError(LLMError):
    """API returned error response"""
    pass

class ResponseValidationError(LLMError):
    """Response validation error"""
    pass

class ResponseParsingError(LLMError):
    """Response parsing error"""
    pass

class MaxRetriesExceededError(LLMError):
    """Max retries exceeded"""
    pass

class ConfigurationError(LLMError):
    """Configuration error"""
    pass

class ModelNotFoundError(LLMError):
    """Model not found error"""
    pass