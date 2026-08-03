"""Global reference data cache for frequently accessed lookup tables"""

import json
from typing import Dict, Any, Optional


class GlobalReferenceCache:
    """Global singleton cache for reference data tables"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, db_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if not self._initialized:
            self._db_path = db_path or 'data/chat_database.db'
            self._initialize_cache()
            self._initialized = True

    @classmethod
    def reset(cls, db_path: Optional[str] = None):
        """Clear the singleton and re-instantiate, optionally against a new DB path.

        Test-only helper: required by fixture tests that point the singleton
        cache at a temp database before each test. Not part of the production
        API; production code uses the singleton as-is.
        """
        cls._instance = None
        cls._initialized = False
        return cls(db_path)

    def _initialize_cache(self):
        """Load all reference data from database"""
        try:
            from services.sqlite.database import ChatDatabase
            self.db = ChatDatabase(self._db_path)
            self.ref_message_types = {}
            self._load_ref_message_types()
        except ImportError:
            # Fallback for testing without database
            self.db = None
            self.ref_message_types = {}
    
    def _load_ref_message_types(self):
        """Load ref_message_types into cache"""
        if self.db:
            message_types = self.db.get_active_message_types()
            for msg_type in message_types:
                self.ref_message_types[msg_type['slug']] = msg_type
    def get_message_type(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get message type from cache"""
        return self.ref_message_types.get(slug)
    
    def close(self):
        """Close the underlying database connection if it is open."""
        if self.db is not None:
            self.db.close()
            self.db = None