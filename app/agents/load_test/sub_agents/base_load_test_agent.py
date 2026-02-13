"""Base agent class for load testing agents."""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime

from app.agents.base_agent import BaseAgent, LLMProvider
from app.agents.load_test.state import AgenticLoadTestState, AgentThought


class BaseLoadTestAgent(BaseAgent, ABC):
    """Base class for all load testing agents."""

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.GROQ,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        anthropic_model: Optional[str] = None
    ):
        """Initialize agent with LLM configuration."""
        super().__init__(
            provider=provider,
            groq_api_key=groq_api_key,
            groq_model=groq_model,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            anthropic_api_key=anthropic_api_key,
            anthropic_model=anthropic_model
        )

    @abstractmethod
    def execute(self, state: AgenticLoadTestState) -> AgenticLoadTestState:
        """
        Execute agent's task and update state.

        Args:
            state: Current state of the agentic workflow

        Returns:
            Updated state with agent's output
        """
        pass

    def add_thought(
        self,
        state: AgenticLoadTestState,
        thought: str,
        reasoning: str,
        phase: str
    ) -> AgenticLoadTestState:
        """
        Add an agent thought to the state for SSE streaming.

        Args:
            state: Current state
            thought: What the agent is doing
            reasoning: Why the agent is doing it
            phase: Current phase name

        Returns:
            Updated state with new thought
        """
        if 'agent_thoughts' not in state:
            state['agent_thoughts'] = []

        thought_entry: AgentThought = {
            'agent': self.__class__.__name__,
            'thought': thought,
            'reasoning': reasoning,
            'timestamp': datetime.now(),
            'phase': phase
        }

        state['agent_thoughts'].append(thought_entry)
        state['current_agent'] = self.__class__.__name__
        state['agent_phase'] = phase

        return state

    def add_error(
        self,
        state: AgenticLoadTestState,
        error: str
    ) -> AgenticLoadTestState:
        """Add an error to the state."""
        if 'errors' not in state:
            state['errors'] = []

        state['errors'].append(f"[{self.__class__.__name__}] {error}")

        return state

    def get_agent_name(self) -> str:
        """Get human-readable agent name."""
        return self.__class__.__name__.replace('Agent', ' Agent')
