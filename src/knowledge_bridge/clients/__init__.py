"""HTTP clients for inter-server communication."""

from .knowledge_store import KnowledgeStoreClient
from .session_intel import SessionIntelligenceClient

# Backward compatibility alias
from .uckn import MockUCKNClient

__all__ = [
    "SessionIntelligenceClient",
    "KnowledgeStoreClient",
    "MockUCKNClient",  # Deprecated: use KnowledgeStoreClient
]
