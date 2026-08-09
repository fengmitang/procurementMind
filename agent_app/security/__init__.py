"""Security boundaries shared by future knowledge and model adapters."""

from agent_app.security.prompt_boundary import KnowledgeChunk, build_knowledge_messages

__all__ = ["KnowledgeChunk", "build_knowledge_messages"]
