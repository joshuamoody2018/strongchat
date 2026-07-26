#!/usr/bin/env python3
import os
import uuid
import sqlite3
from datetime import datetime
from services.sqlite.database import ChatDatabase

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    print("Warning: python-dotenv not available. Using fallback environment loading.")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Warning: requests not available. API functionality will be limited.")

# Load environment variables
if DOTENV_AVAILABLE:
    load_dotenv()

def call_openrouter_api(prompt, model_slug="openai/gpt-3.5-turbo"):
    if not REQUESTS_AVAILABLE:
        return "Error: requests library not available. Install with: pip install requests"
    
    api_key = os.getenv('OPENROUTER_API_KEY')
    if not api_key or api_key == 'your_openrouter_api_key_here':
        return "Error: OpenRouter API key not configured. Please update your .env file."
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "SQLite Chat App"
    }
    
    data = {
        "model": model_slug,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Error calling API: {str(e)}"

def get_message_intent(message_text):
    if not REQUESTS_AVAILABLE:
        # Simple fallback intent detection
        message_lower = message_text.lower()
        # Use word boundaries to avoid partial matches
        import re
        if re.search(r'\bhello\b|\bhi\b|\bhey\b|\bgreetings\b', message_lower):
            return 'greeting'
        elif re.search(r'\b\?|\bwhat\b|\bhow\b|\bwhy\b|\bwhen\b|\bwhere\b', message_lower):
            return 'question'
        elif re.search(r'\bbye\b|\bgoodbye\b|\bquit\b|\bexit\b', message_lower):
            return 'goodbye'
        elif re.search(r'\bhelp\b|\bassist\b|\bsupport\b', message_lower):
            return 'help'
        else:
            return 'statement'
    
    intents_model = os.getenv('MODEL_SLUG_INTENTS', 'openai/gpt-3.5-turbo')
    
    # Simple intent detection - in a real app, you'd use a proper classification model
    prompt = f"""Analyze the following message and return the primary intent as a single word or short phrase:
    Message: "{message_text}"
    
    Possible intents: greeting, question, statement, command, goodbye, help
    
    Intent:"""
    
    return call_openrouter_api(prompt, intents_model).strip().lower()

def main():
    db = ChatDatabase()
    
    print("SQLite Chat Application")
    print("Type 'quit' to exit, 'new' to create new session, 'sessions' to list sessions")
    
    current_session = None
    
    while True:
        if not current_session:
            print("\nNo active session. Type 'new' to create one or enter session UUID:")
            user_input = input("> ").strip()
            
            if user_input.lower() == 'quit':
                break
            elif user_input.lower() == 'new':
                session_name = input("Enter session name: ").strip()
                if session_name:
                    current_session = db.create_session(session_name)
                    print(f"Created new session: {current_session}")
                    print(f"Session name: {session_name}")
            elif user_input.lower() == 'sessions':
                sessions = db.get_sessions()
                print("\nSessions:")
                for session in sessions:
                    print(f"  {session[0]} - {session[1]} ({session[2]})")
            else:
                # Check if it's a valid UUID
                try:
                    uuid.UUID(user_input)
                    current_session = user_input
                    session_name = db.get_session_name(current_session)
                    print(f"Joined session: {current_session} ({session_name})")
                except ValueError:
                    print("Invalid session UUID. Type 'new' to create a session.")
        
        else:
            user_input = input(f"[{current_session}] > ").strip()
            
            if user_input.lower() == 'quit':
                break
            elif user_input.lower() == 'new':
                current_session = None
                continue
            elif user_input.lower() == 'sessions':
                sessions = db.get_sessions()
                print("\nSessions:")
                for session in sessions:
                    print(f"  {session[0]} - {session[1]} ({session[2]})")
                continue
            elif user_input.lower() == 'help':
                print("Commands: quit, new, sessions, help")
                continue
            
            if user_input:
                # Get AI response
                ai_response = call_openrouter_api(user_input)
                
                # Store in database
                message_uuid = db.create_message(current_session, user_input, ai_response)
                
                # Get intent
                intent = get_message_intent(user_input)
                db.create_intent(message_uuid, intent)
                
                print(f"AI: {ai_response}")
                print(f"Intent: {intent}")
    
    db.close()
    print("Goodbye!")

if __name__ == "__main__":
    main()