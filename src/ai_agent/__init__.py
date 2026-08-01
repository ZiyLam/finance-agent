"""Finance-research application components built around LangChain."""

from .config import AgentSettings
from .langchain.agent import Agent, AgentResult

__all__ = ["Agent", "AgentResult", "AgentSettings"]
