#!/usr/bin/env python3
"""Test script for main.py functionality"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import uuid

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from services.sqlite.database import ChatDatabase
from main import get_message_intent, call_openrouter_api


class TestMainFunctionality(unittest.TestCase):
    """Test suite for main.py functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_db_path = 'test_chat_database.db'
        # Create database tables first
        from services.sqlite.utils import create_database
        create_database(self.test_db_path)
        self.db = ChatDatabase(self.test_db_path)
    
    def tearDown(self):
        """Clean up test environment"""
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
    
    def test_create_session(self):
        """Test session creation"""
        session_uuid = self.db.create_session("Test Session", "test_user")
        self.assertIsInstance(session_uuid, str)
        self.assertTrue(len(session_uuid) > 0)
        
        # Verify session was created
        session_name = self.db.get_session_name(session_uuid)
        self.assertEqual(session_name, "Test Session")
    
    def test_create_message(self):
        """Test message creation"""
        session_uuid = self.db.create_session("Test Session")
        message_uuid = self.db.create_message(session_uuid, "Hello", "Hi there!")
        
        self.assertIsInstance(message_uuid, str)
        self.assertTrue(len(message_uuid) > 0)
        
        # Verify message was created
        messages = self.db.get_messages(session_uuid)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][1], "Hello")  # input text
        self.assertEqual(messages[0][2], "Hi there!")  # output text
    
    def test_create_intent(self):
        """Test intent creation"""
        session_uuid = self.db.create_session("Test Session")
        message_uuid = self.db.create_message(session_uuid, "Hello", "Hi there!")
        intent_uuid = self.db.create_intent(message_uuid, "greeting")
        
        self.assertIsInstance(intent_uuid, str)
        self.assertTrue(len(intent_uuid) > 0)
        
        # Verify intent was created
        intents = self.db.get_intents_for_message(message_uuid)
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0][1], "greeting")
    
    def test_get_sessions(self):
        """Test getting all sessions"""
        session1 = self.db.create_session("Session 1")
        session2 = self.db.create_session("Session 2")
        
        sessions = self.db.get_sessions()
        self.assertEqual(len(sessions), 2)
        
        # Check session names
        session_names = [s[1] for s in sessions]
        self.assertIn("Session 1", session_names)
        self.assertIn("Session 2", session_names)
    
    def test_get_message_intent_fallback(self):
        """Test intent detection with fallback when requests not available"""
        with patch('main.REQUESTS_AVAILABLE', False):
            # Test greeting intent
            intent = get_message_intent("Hello there!")
            self.assertEqual(intent, 'greeting')
            
            # Test question intent
            intent = get_message_intent("How are you?")
            self.assertEqual(intent, 'question')
            
            # Test goodbye intent
            intent = get_message_intent("Goodbye!")
            self.assertEqual(intent, 'goodbye')
            
            # Test help intent
            intent = get_message_intent("I need help with this")
            self.assertEqual(intent, 'help')
            
            # Test statement intent
            intent = get_message_intent("This is a statement")
            self.assertEqual(intent, 'statement')
            
            # Test command intent (should default to statement)
            intent = get_message_intent("Do this now")
            self.assertEqual(intent, 'statement')
    
    @patch('main.REQUESTS_AVAILABLE', True)
    @patch('main.call_openrouter_api')
    def test_get_message_intent_with_api(self, mock_api):
        """Test intent detection with API when requests available"""
        mock_api.return_value = "question"
        
        with patch('main.REQUESTS_AVAILABLE', True):
            intent = get_message_intent("What is the meaning of life?")
            self.assertEqual(intent, 'question')
            mock_api.assert_called_once()
    
    @patch('main.REQUESTS_AVAILABLE', False)
    def test_call_openrouter_api_fallback(self):
        """Test API call fallback when requests not available"""
        response = call_openrouter_api("test prompt")
        self.assertIn("Error: requests library not available", response)
    
    @patch('main.REQUESTS_AVAILABLE', True)
    @patch('main.os.getenv')
    def test_call_openrouter_api_no_key(self, mock_getenv):
        """Test API call when no API key is configured"""
        mock_getenv.return_value = 'your_openrouter_api_key_here'
        
        response = call_openrouter_api("test prompt")
        self.assertIn("Error: OpenRouter API key not configured", response)
    
    @patch('main.REQUESTS_AVAILABLE', True)
    @patch('main.os.getenv')
    @patch('main.requests.post')
    def test_call_openrouter_api_success(self, mock_post, mock_getenv):
        """Test successful API call"""
        mock_getenv.return_value = 'test_api_key'
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'Test response'}}]
        }
        mock_post.return_value = mock_response
        
        response = call_openrouter_api("test prompt")
        self.assertEqual(response, "Test response")
    
    @patch('main.REQUESTS_AVAILABLE', True)
    @patch('main.os.getenv')
    @patch('main.requests.post')
    def test_call_openrouter_api_error(self, mock_post, mock_getenv):
        """Test API call error handling"""
        mock_getenv.return_value = 'test_api_key'
        mock_post.side_effect = Exception("Network error")
        
        response = call_openrouter_api("test prompt")
        self.assertIn("Error calling API", response)


class TestMainIntegration(unittest.TestCase):
    """Integration tests for main.py functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_db_path = 'test_integration_database.db'
        # Create database tables first
        from services.sqlite.utils import create_database
        create_database(self.test_db_path)
        self.db = ChatDatabase(self.test_db_path)
    
    def tearDown(self):
        """Clean up test environment"""
        self.db.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
    
    def test_full_session_flow(self):
        """Test complete session flow"""
        # Create session
        session_uuid = self.db.create_session("Integration Test")
        
        # Create message
        message_uuid = self.db.create_message(session_uuid, "Test input", "Test output")
        
        # Create intent
        intent_uuid = self.db.create_intent(message_uuid, "question")
        
        # Verify all data is stored correctly
        session_name = self.db.get_session_name(session_uuid)
        self.assertEqual(session_name, "Integration Test")
        
        messages = self.db.get_messages(session_uuid)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][1], "Test input")
        
        intents = self.db.get_intents_for_message(message_uuid)
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0][1], "question")


def run_tests():
    """Run all tests"""
    print("Running main.py functionality tests...")
    print("=" * 50)
    
    # Change to src directory to import from main.py
    original_cwd = os.getcwd()
    os.chdir(os.path.join(os.path.dirname(__file__), '..', 'src'))
    
    try:
        # Create test suite
        suite = unittest.TestSuite()
        
        # Add test cases
        suite.addTest(unittest.makeSuite(TestMainFunctionality))
        suite.addTest(unittest.makeSuite(TestMainIntegration))
        
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
    finally:
        # Change back to original directory
        os.chdir(original_cwd)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)