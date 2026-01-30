"""
Base Sub-Agent Class

All sub-agents inherit from this base class which provides:
- LLM initialization
- Common utilities
- Logging and broadcasting
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
from datetime import datetime

from app.agents.base_agent import LLMProvider
from app.core.config import settings


class SubAgentLLM:
    """Simple LLM wrapper for sub-agents."""

    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        anthropic_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
    ):
        self.provider = provider
        self.model = model
        self.max_tokens = 8000

        # Initialize client based on provider (lazy imports)
        if provider == LLMProvider.ANTHROPIC:
            import anthropic
            self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        elif provider == LLMProvider.OPENAI:
            import openai
            self.client = openai.OpenAI(api_key=openai_api_key)
        elif provider == LLMProvider.GROQ:
            from groq import Groq
            self.client = Groq(api_key=groq_api_key)

    def call_llm(self, prompt: str) -> str:
        """Call the LLM with the given prompt."""
        try:
            if self.provider == LLMProvider.ANTHROPIC:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.content[0].text.strip()

            elif self.provider == LLMProvider.OPENAI:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()

            elif self.provider == LLMProvider.GROQ:
                response = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                return response.choices[0].message.content.strip()

        except Exception as e:
            print(f"[SubAgentLLM] Error calling LLM: {e}")
            raise


class BaseSubAgent(ABC):
    """Base class for all sub-agents in the multi-agent system."""

    def __init__(
        self,
        name: str,
        role: str,
        llm_provider: str = "groq",
        model: Optional[str] = None,
        broadcast_func: Optional[Callable] = None
    ):
        self.name = name
        self.role = role
        self.llm_provider = llm_provider
        self.model = model or self._get_default_model(llm_provider)
        self.broadcast_func = broadcast_func

        # Initialize LLM
        provider = LLMProvider(llm_provider.lower())
        self.llm = SubAgentLLM(
            provider=provider,
            model=self.model,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            openai_api_key=settings.OPENAI_API_KEY,
            groq_api_key=settings.GROQ_API_KEY,
        )

        self.execution_log = []

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        return {
            "groq": settings.GROQ_MODEL or "llama-3.1-8b-instant",
            "openai": settings.OPENAI_MODEL or "gpt-4o-mini",
            "anthropic": settings.ANTHROPIC_MODEL or "claude-3-haiku-20240307"
        }.get(provider.lower(), "llama-3.1-8b-instant")

    def log(self, message: str, level: str = "info"):
        """Log a message."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "level": level,
            "message": message
        }
        self.execution_log.append(log_entry)
        print(f"[{self.name}] {message}")

    def broadcast(self, message: Dict):
        """Send SSE broadcast."""
        if self.broadcast_func:
            # Add agent info to message
            message["agent"] = self.name
            self.broadcast_func(message)

    def think(self, prompt: str) -> str:
        """Use LLM to think/reason about something."""
        self.log(f"Thinking: {prompt[:50]}...")
        response = self.llm.call_llm(prompt)
        self.log(f"Thought: {response[:100]}...")
        return response

    @abstractmethod
    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the sub-agent's main task.
        Must be implemented by each specialized sub-agent.
        """
        pass

    def report_status(self) -> Dict[str, Any]:
        """Report current status of the sub-agent."""
        return {
            "agent": self.name,
            "role": self.role,
            "log_count": len(self.execution_log),
            "last_activity": self.execution_log[-1] if self.execution_log else None
        }
