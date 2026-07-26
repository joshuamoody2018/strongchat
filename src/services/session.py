"""Session object for pipeline processing"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List
from services.llm.aimessage import AIMessage


@dataclass
class ChatSession:
    """Session object that gets passed through the pipeline"""
    uuid: str
    name: str
    created_by: str
    created_at: datetime
    context: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Initialize default context if not provided"""
        if not self.context:
            self.context = {
                'messages': [],
                'metadata': {},
                'pipeline_state': {}
            }
    
    def add_message(self, message: AIMessage):
        """Add message to session context"""
        self.context['messages'].append(message)
    
    def get_messages(self) -> List[AIMessage]:
        """Get all messages in session"""
        return self.context.get('messages', [])
    
    def get_last_message(self) -> AIMessage:
        """Get the last message in session"""
        messages = self.get_messages()
        return messages[-1] if messages else None
    
    def set_pipeline_state(self, key: str, value: Any):
        """Set pipeline state value"""
        self.context['pipeline_state'][key] = value
    
    def get_pipeline_state(self, key: str, default: Any = None) -> Any:
        """Get pipeline state value"""
        return self.context['pipeline_state'].get(key, default)
    
    def add_metadata(self, key: str, value: Any):
        """Add metadata to session"""
        self.context['metadata'][key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value"""
        return self.context['metadata'].get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary"""
        return {
            'uuid': self.uuid,
            'name': self.name,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'context': self.context
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatSession':
        """Create session from dictionary"""
        return cls(
            uuid=data['uuid'],
            name=data['name'],
            created_by=data['created_by'],
            created_at=datetime.fromisoformat(data['created_at']),
            context=data.get('context', {})
        )