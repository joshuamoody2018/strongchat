#!/usr/bin/env python3
"""Simple test for the LLM framework without aiohttp dependencies"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.llm.parser import ResponseParser, BaseResponseModel
from services.llm.exceptions import ResponseValidationError, ResponseParsingError
from config.schemas import INTENT_DISAMBIGUATION_SCHEMA


class MockResponseModel(BaseResponseModel):
    """Mock response model for testing"""
    def __init__(self, test_field: str):
        self.test_field = test_field


class TestParser(unittest.TestCase):
    """Test the response parser"""
    
    def setUp(self):
        """Set up test environment"""
        self.parser = ResponseParser(INTENT_DISAMBIGUATION_SCHEMA, MockResponseModel)
    
    def test_json_extraction_plain(self):
        """Test JSON extraction from plain text"""
        plain_json = '{"test": "value"}'
        result = self.parser._extract_json(plain_json)
        self.assertEqual(result, plain_json)
    
    def test_json_extraction_markdown(self):
        """Test JSON extraction from markdown format"""
        markdown_json = "```json\n{\"test\": \"value\"}\n```"
        result = self.parser._extract_json(markdown_json)
        self.assertEqual(result, "{\"test\": \"value\"}")
    
    def test_json_extraction_complex(self):
        """Test JSON extraction from complex response"""
        complex_response = """
        Here's the analysis:
        {
          "query_analysis": {
            "original_query": "test query",
            "ambiguous_elements": ["part1", "part2"],
            "core_question": "What is the question?",
            "context_clues": ["clue1", "clue2"]
          },
          "interpretive_framings": [],
          "recommended_framing": "framing1"
        }
        End of response.
        """
        result = self.parser._extract_json(complex_response)
        self.assertIn("query_analysis", result)
        self.assertIn("original_query", result)
    
    def test_valid_json_parsing(self):
        """Test parsing valid JSON"""
        valid_json = """
        {
          "query_analysis": {
            "original_query": "why do bad things happen",
            "ambiguous_elements": ["bad things"],
            "core_question": "Why does suffering occur?",
            "context_clues": ["suffering", "pain"]
          },
          "interpretive_framings": [
            {
              "framing_id": "framing1",
              "interpretation": "Understanding causes of suffering",
              "keywords": ["suffering", "causes", "pain"],
              "disambiguation_note": "Focuses on general problem",
              "confidence": 0.8
            },
            {
              "framing_id": "framing2",
              "interpretation": "Personal comfort in suffering",
              "keywords": ["comfort", "personal", "pain"],
              "disambiguation_note": "Focuses on individual experience",
              "confidence": 0.6
            }
          ],
          "recommended_framing": "framing1"
        }
        """
        
        # Mock the response model creation
        with patch.object(MockResponseModel, 'from_json') as mock_from_json:
            mock_from_json.return_value = MockResponseModel("test")
            result = self.parser.parse(valid_json)
            self.assertIsInstance(result, MockResponseModel)
            mock_from_json.assert_called_once()
    
    def test_invalid_json_error(self):
        """Test error handling for invalid JSON"""
        invalid_json = "This is not valid JSON {"
        
        with self.assertRaises(ResponseParsingError):
            self.parser.parse(invalid_json)
    
    def test_schema_validation_error(self):
        """Test error handling for schema validation"""
        # JSON with missing required fields
        incomplete_json = """
        {
          "query_analysis": {
            "original_query": "test query"
          }
        }
        """
        
        with self.assertRaises(ResponseValidationError):
            self.parser.parse(incomplete_json)


def run_tests():
    """Run all tests"""
    print("Testing LLM Parser Framework...")
    print("=" * 50)
    
    # Create test suite
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestParser))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 50)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    print("=" * 50)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)