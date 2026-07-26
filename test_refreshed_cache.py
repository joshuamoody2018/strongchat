#!/usr/bin/env python3
"""Test real API call with refreshed cache"""

import sys
sys.path.insert(0, 'src')

from config.cache import GlobalReferenceCache
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage

def test_with_refreshed_cache():
    """Test real API call with refreshed cache"""
    print("=== Testing Real API Call with Refreshed Cache ===\n")
    
    try:
        # Refresh cache to get updated database schema
        cache = GlobalReferenceCache()
        cache.refresh_cache()
        llm_wrapper = LLMWrapper()
        
        # Check updated schema and prompt
        intent_config = cache.get_message_type("intent_classification")
        print("1. Configuration Check:")
        print(f"   ✓ Model: {intent_config['model_slug']}")
        print(f"   ✓ Temperature: {intent_config['temperature']}")
        print(f"   ✓ Max Retries: {intent_config['max_retries']}")
        print(f"   ✓ Schema loaded: {intent_config['request_schema']['title']}")
        
        # Check if prompt template exists
        if 'prompt_template' in intent_config:
            print(f"   ✓ Prompt template loaded")
            print(f"   Prompt preview: {intent_config['prompt_template'][:100]}...")
        else:
            print("   ✗ No prompt template found")
        
        # Test real API call
        print("\n2. Real API Call:")
        test_query = "What does the Bible say about faith and hope?"
        print(f"   Query: '{test_query}'")
        
        intent_message = llm_wrapper.sync_call_api(
            message_type_slug="intent_classification",
            unique_prompt=test_query,
            session_uuid="test-session"
        )
        
        print(f"   Successful: {intent_message.is_successful()}")
        print(f"   Tries: {intent_message.num_tries}")
        
        # Show raw response
        if intent_message.raw_response:
            print("\n3. Raw Response:")
            print(f"   {intent_message.raw_response}")
        
        # Test parsing with schema validation
        if intent_message.is_successful():
            try:
                parsed_response = intent_message.get_parsed_response(intent_config["request_schema"])
                if parsed_response:
                    print("\n4. ✓ Parsed Response (Valid JSON):")
                    print(f"   Query Complexity: {parsed_response.get('query_analysis', {}).get('query_complexity', 'unknown')}")
                    print(f"   Core Questions: {parsed_response.get('query_analysis', {}).get('core_questions', [])}")
                    print(f"   Number of Intents: {len(parsed_response.get('intents', []))}")
                    
                    # Show all intents
                    for i, intent in enumerate(parsed_response.get('intents', [])):
                        print(f"\n   Intent {i+1}:")
                        print(f"     ID: {intent.get('intent_id')}")
                        print(f"     Primary: {intent.get('is_primary')}")
                        print(f"     Confidence: {intent.get('confidence')}")
                        print(f"     Keywords: {intent.get('keywords', [])}")
                        print(f"     Framing: {intent.get('framing', {})}")
                    
                    print(f"\n   Recommended Search: {parsed_response.get('recommended_search_approach', 'N/A')}")
                    
                    # Verify schema compliance
                    schema = intent_config["request_schema"]
                    required_fields = schema['required']
                    print(f"\n5. Schema Compliance Check:")
                    for field in required_fields:
                        if field in parsed_response:
                            print(f"   ✓ {field}")
                        else:
                            print(f"   ✗ {field} - MISSING")
                    
                    # Check intent structure
                    print(f"\n6. Intent Structure Check:")
                    for i, intent in enumerate(parsed_response.get('intents', [])):
                        intent_required = schema['properties']['intents']['items']['required']
                        print(f"   Intent {i+1}:")
                        for prop in intent_required:
                            if prop in intent:
                                print(f"     ✓ {prop}")
                            else:
                                print(f"     ✗ {prop} - MISSING")
                    
                else:
                    print("\n   ✗ Response parsing failed - no valid JSON found")
            except Exception as e:
                print(f"\n   ✗ Response parsing failed: {e}")
                print(f"   Raw response first 500 chars: {intent_message.raw_response[:500]}...")
        else:
            print(f"\n   ✗ API call failed: {intent_message.error_text}")
        
        llm_wrapper.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_with_refreshed_cache()