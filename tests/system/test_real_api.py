#!/usr/bin/env python3
"""Test real API call with intent classification"""

import asyncio
import sys
sys.path.insert(0, 'src')

from config.cache import GlobalReferenceCache
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage

def test_real_api():
    """Test real API call with intent classification"""
    print("=== Testing Real API Call with Intent Classification ===\n")

    try:
        cache = GlobalReferenceCache()
        llm_wrapper = LLMWrapper()

        # Check updated schema
        intent_config = cache.get_message_type("intent_classification")
        print("1. Schema Configuration:")
        print(f"   Model: {intent_config['model_slug']}")
        print(f"   Temperature: {intent_config['temperature']}")
        print(f"   Max Retries: {intent_config['max_retries']}")

        # Test real API call
        print("\n2. Real API Call:")
        test_query = "What does the Bible say about faith and hope?"
        print(f"   Query: '{test_query}'")

        intent_message = asyncio.run(
            llm_wrapper.call_api(
                message_type_slug="intent_classification",
                unique_prompt=test_query,
                session_uuid="test-session",
            )
        )
        
        print(f"   Successful: {intent_message.is_successful()}")
        print(f"   Tries: {intent_message.num_tries}")
        
        # Show raw response
        if intent_message.raw_response:
            print("\n3. Raw Response:")
            print(f"   {intent_message.raw_response}")
        
        # Test parsing
        if intent_message.is_successful():
            try:
                parsed_response = intent_message.get_parsed_response(intent_config["request_schema"])
                if parsed_response:
                    print("\n4. Parsed Response:")
                    print(f"   ✓ Response parsed successfully")
                    print(f"   Query Complexity: {parsed_response.get('query_analysis', {}).get('query_complexity', 'unknown')}")
                    print(f"   Number of Intents: {len(parsed_response.get('intents', []))}")
                    
                    # Show first intent structure
                    if parsed_response.get('intents'):
                        first_intent = parsed_response['intents'][0]
                        print(f"   First Intent ID: {first_intent.get('intent_id')}")
                        print(f"   Primary Intent: {first_intent.get('is_primary')}")
                        print(f"   Keywords: {first_intent.get('keywords', [])}")
                        print(f"   Framing Perspective: {first_intent.get('framing', {}).get('perspective', 'unknown')}")
                        print(f"   Framing Context: {first_intent.get('framing', {}).get('context', 'unknown')}")
                        print(f"   Framing Approach: {first_intent.get('framing', {}).get('approach', 'unknown')}")
                        print(f"   Confidence: {first_intent.get('confidence')}")
                    
                    # Show all intents if multiple
                    if len(parsed_response.get('intents', [])) > 1:
                        print(f"\n   All Intents:")
                        for i, intent in enumerate(parsed_response['intents']):
                            print(f"     {i+1}. {intent.get('intent_id')} (primary: {intent.get('is_primary')})")
                    

                else:
                    print("\n   ✗ Response parsing failed - no valid JSON found")
            except Exception as e:
                print(f"\n   ✗ Response parsing failed: {e}")
                print(f"   Raw response first 200 chars: {intent_message.raw_response[:200]}...")
        else:
            print(f"\n   ✗ API call failed: {intent_message.error_text}")
        
        llm_wrapper.close()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_real_api()