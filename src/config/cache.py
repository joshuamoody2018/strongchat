"""Global reference data cache for frequently accessed lookup tables"""

import json
from typing import Dict, Any, Optional


class GlobalReferenceCache:
    """Global singleton cache for reference data tables"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialize_cache()
            self._initialized = True
    
    def _initialize_cache(self):
        """Load all reference data from database"""
        try:
            from services.sqlite.database import ChatDatabase
            self.db = ChatDatabase()
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
    
    def get_all_message_types(self) -> Dict[str, Dict[str, Any]]:
        """Get all message types from cache"""
        return self.ref_message_types.copy()
    
    def refresh_cache(self):
        """Refresh all cached data"""
        self._initialize_cache()
    
    def add_message_type(self, message_type: Dict[str, Any]):
        """Add new message type to cache"""
        self.ref_message_types[message_type['slug']] = message_type
    
    def invalidate_message_type(self, slug: str):
        """Invalidate specific message type cache"""
        if slug in self.ref_message_types:
            del self.ref_message_types[slug]