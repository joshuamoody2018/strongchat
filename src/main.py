#!/usr/bin/env python3
import os
import uuid
import sqlite3
from datetime import datetime
import sys
sys.path.insert(0, 'src')

from services.sqlite.database import ChatDatabase
from services.llm.wrapper import LLMWrapper
from services.session import ChatSession
from services.llm.aimessage import AIMessage
from config.cache import GlobalReferenceCache

try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    print("Warning: python-dotenv not available. Using fallback environment loading.")

# Load environment variables
if DOTENV_AVAILABLE:
    load_dotenv()

def main():
    db = ChatDatabase()
    cache = GlobalReferenceCache()
    llm_wrapper = LLMWrapper()
    
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
                    session_uuid = db.create_session(session_name)
                    current_session = ChatSession(
                        uuid=session_uuid,
                        name=session_name,
                        created_by="user",
                        created_at=datetime.now()
                    )
                    print(f"Created new session: {current_session.uuid}")
                    print(f"Session name: {current_session.name}")
            elif user_input.lower() == 'sessions':
                sessions = db.get_sessions()
                print("\nSessions:")
                for session in sessions:
                    print(f"  {session[0]} - {session[1]} ({session[2]})")
            else:
                # Check if it's a valid UUID
                try:
                    uuid.UUID(user_input)
                    session_data = db.get_session_name(user_input)
                    if session_data:
                        current_session = ChatSession(
                            uuid=user_input,
                            name=session_data,
                            created_by="user",
                            created_at=datetime.now()
                        )
                        print(f"Joined session: {current_session.uuid} ({current_session.name})")
                    else:
                        print("Invalid session UUID. Type 'new' to create a session.")
                except ValueError:
                    print("Invalid session UUID. Type 'new' to create a session.")
        
        else:
            user_input = input(f"[{current_session.uuid}] > ").strip()
            
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
                try:
                    # Use LLM wrapper for intent classification
                    intent_message = llm_wrapper.sync_call_api(
                        message_type_slug="intent_classification",
                        unique_prompt=user_input,
                        session_uuid=current_session.uuid
                    )
                    
                    # Add message to session
                    current_session.add_message(intent_message)
                    
                    # Extract intent from parsed response using cached schema
                    intent_config = cache.get_message_type("intent_classification")
                    intent_data = intent_message.get_parsed_response(intent_config["request_schema"])
                    intent = intent_data.get("intent", "unknown")
                    confidence = intent_data.get("confidence", 0.0)
                    
                    print(f"Intent: {intent} (confidence: {confidence:.2f})")
                    
                    # For demonstration, use a simple response
                    if intent == "greeting":
                        ai_response = f"Hello! I'm here to help you with biblical questions. What would you like to know?"
                    elif intent == "question":
                        ai_response = f"I understand you're asking about: '{user_input}'. Let me help you with that biblical question."
                    elif intent == "goodbye":
                        ai_response = "Goodbye! Feel free to come back anytime with your biblical questions."
                    else:
                        ai_response = f"I understand you said: '{user_input}'. How can I help you today?"
                    
                    # Create AI response message
                    ai_message = AIMessage(
                        session_uuid=current_session.uuid,
                        message_type_slug="llm_response",
                        unique_prompt=ai_response
                    )
                    ai_message.mark_success(ai_response)
                    current_session.add_message(ai_message)
                    
                    # Store messages in database
                    db.create_message_with_type(
                        session_uuid=current_session.uuid,
                        message_type_slug="human_input",
                        unique_prompt=user_input
                    )
                    db.create_message_with_type(
                        session_uuid=current_session.uuid,
                        message_type_slug="llm_response",
                        unique_prompt=ai_response
                    )
                    
                    print(f"AI: {ai_response}")
                    
                except Exception as e:
                    print(f"Error: {e}")
                    # Store error in database and session
                    error_message = AIMessage(
                        session_uuid=current_session.uuid,
                        message_type_slug="error",
                        unique_prompt=user_input
                    )
                    error_message.mark_failure(str(e))
                    current_session.add_message(error_message)
                    
                    db.create_message_with_type(
                        session_uuid=current_session.uuid,
                        message_type_slug="error",
                        unique_prompt=user_input,
                        error_text=str(e)
                    )
    
    llm_wrapper.close()
    db.close()
    print("Goodbye!")

if __name__ == "__main__":
    main()