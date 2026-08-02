#!/usr/bin/env python3
"""Test final concise prompt"""

import asyncio
import sys
sys.path.insert(0, 'src')

from config.cache import GlobalReferenceCache
from services.llm.wrapper import LLMWrapper
from services.llm.aimessage import AIMessage

def test_final_system():
    """Test final system with concise prompt"""
    print("=== Testing Final Intent Classification System ===\n")

    try:
        cache = GlobalReferenceCache()
        cache.refresh_cache()
        llm_wrapper = LLMWrapper()

        intent_config = cache.get_message_type("intent_classification")
        print("✓ System Configuration:")
        print(f"  Model: {intent_config['model_slug']}")
        print(f"  Schema: {intent_config['request_schema']['title']}")
        print(f"  Max Retries: {intent_config['max_retries']}")

        # Test with multiple queries
        test_queries = [
            "What does the Bible say about faith and hope?",
            "Tell me about love",
            "How to be patient?"
        ]

        for i, query in enumerate(test_queries, 1):
            print(f"\n{i}. Testing Query: '{query}'")

            intent_message = asyncio.run(
                llm_wrapper.call_api(
                    message_type_slug="intent_classification",
                    unique_prompt=query,
                    session_uuid=f"test-session-{i}",
                )
            )
            
            print(f"   Successful: {intent_message.is_successful()}")
            
            if intent_message.is_successful():
                try:
                    parsed_response = intent_message.get_parsed_response(intent_config["request_schema"])
                    if parsed_response:
                        print("   ✓ Parsed Successfully")
                        print(f"   Complexity: {parsed_response.get('query_analysis', {}).get('query_complexity', 'unknown')}")
                        print(f"   Intents: {len(parsed_response.get('intents', []))}")
                        
                        # Show first intent
                        if parsed_response.get('intents'):
                            first_intent = parsed_response['intents'][0]
                            print(f"   Primary Intent: {first_intent.get('intent_id')}")
                            print(f"   Keywords: {first_intent.get('keywords', [])[:3]}...")
                            print(f"   Framing: {first_intent.get('framing', {})}")
                        
                        print(f"   Search Approach: {parsed_response.get('recommended_search_approach', 'N/A')}")
                        
                        # Schema validation
                        schema = intent_config["request_schema"]
                        required_fields = schema['required']
                        valid = True
                        for field in required_fields:
                            if field not in parsed_response:
                                print(f"   ✗ Missing required field: {field}")
                                valid = False
                        
                        if valid:
                            print("   ✅ Schema Valid")
                        else:
                            print("   ❌ Schema Invalid")
                    
                except Exception as e:
                    print(f"   ✗ Parse Error: {e}")
            else:
                print(f"   ✗ API Failed: {intent_message.error_text}")
        
        llm_wrapper.close()
        print("\n🎉 Testing Complete!")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_final_system()