#!/usr/bin/env python3
import os
import uuid
import sqlite3
from datetime import datetime
import sys
sys.path.insert(0, 'src')

from services.sqlite.database import ChatDatabase
from services.pipeline import PipelineRunner
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

async def main():
    db = ChatDatabase()
    cache = GlobalReferenceCache()
    pipeline_runner = PipelineRunner()
    
    print("StrongChat - Bible Verse Retrieval System")
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
                    # Use PipelineRunner for intent generation
                    result = await pipeline_runner.run_intent_only(query=user_input, session_uuid=current_session.uuid)
                    
                    intent_message = AIMessage(
                        session_uuid=current_session.uuid,
                        message_type_slug="intent_generation",
                        unique_prompt=f"Intent analysis for: {user_input}"
                    )
                    intent_message.mark_success(str(result['intents']))
                    current_session.add_message(intent_message)
                    
                    # Extract the primary intent for response
                    primary_intent = None
                    for intent in result['intents']:
                        if intent.get('is_primary'):
                            primary_intent = intent
                            break
                    
                    if primary_intent:
                        intent_text = primary_intent.get('interpretation', 'unknown')
                        themes = primary_intent.get('themes', [])
                        confidence = primary_intent.get('confidence', 0.0)
                        
                        print(f"Primary Intent: {intent_text}")
                        print(f"Themes: {', '.join(themes)}")
                        print(f"Confidence: {confidence:.2f}")
                        
                        # Simple response based on intent
                        if any(theme in themes for theme in ['greeting', 'hello']):
                            ai_response = f"Hello! I understand you're asking about: {intent_text}"
                        elif any(theme in themes for theme in ['goodbye', 'farewell']):
                            ai_response = f"Goodbye! Feel free to return with more questions about {intent_text}"
                        else:
                            ai_response = f"I understand you're asking about: {intent_text}. Let me help you find biblical insights on this topic."
                        
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
                    else:
                        print("Could not determine primary intent.")
                
                except Exception as e:
                    print(f"Error: {e}")
                    # Store error in database using error_text field
                    db.create_message_with_type(
                        session_uuid=current_session.uuid,
                        message_type_slug="human_input",
                        unique_prompt=user_input,
                        error_text=str(e)
                    )
    
    pipeline_runner.close()
    cache.close()
    db.close()
    print("Goodbye!")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())