#!/usr/bin/env python3
"""Test the intent classification API directly"""

import sys
sys.path.insert(0, 'src')

from config.cache import GlobalReferenceCache
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage

def test_intent_api():
    """Test the intent classification API directly"""
    print("=== Testing Intent Classification API ===\n")
    
    try:
        cache = GlobalReferenceCache()
        llm_wrapper = LLMWrapper()
        
        # Get the intent classification schema
        intent_config = cache.get_message_type("intent_classification")
        print("1. Intent Schema:")
        print(f"   Slug: {intent_config['slug']}")
        print(f"   Model: {intent_config['model_slug']}")
        print(f"   Schema: {intent_config['request_schema']}")
        
        # Test mock API call
        print("\n2. Testing Mock API Call:")
        intent_message = llm_wrapper.sync_call_api(
            message_type_slug="intent_classification",
            unique_prompt="hello there",
            session_uuid="test-session"
        )
        
        print(f"   Raw Response: {intent_message.raw_response}")
        print(f"   Message Type: {intent_message.message_type_slug}")
        print(f"   Success: {intent_message.success}")
        
        # Test parsing
        print("\n3. Testing Response Parsing:")
        parsed_response = intent_message.get_parsed_response(intent_config["request_schema"])
        print(f"   Parsed: {parsed_response}")
        
        llm_wrapper.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_intent_api()