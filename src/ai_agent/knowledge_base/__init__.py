"""Read-only adapters for user-owned research knowledge bases."""

from .ima import ImaKnowledgeBaseClient, ImaKnowledgeBaseError

__all__ = ["ImaKnowledgeBaseClient", "ImaKnowledgeBaseError"]
