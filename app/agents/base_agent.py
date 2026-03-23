from abc import ABC, abstractmethod
from typing import Any, Optional
from enum import Enum

# Lazy imports - only import when provider is actually used
# This prevents ModuleNotFoundError when a provider SDK isn't installed
openai = None
anthropic = None
Groq = None

from app.core.config import settings


def _get_anthropic():
    """Lazy import for Anthropic SDK."""
    global anthropic
    if anthropic is None:
        try:
            import anthropic as _anthropic
            anthropic = _anthropic
        except ImportError:
            raise ImportError(
                "Anthropic SDK not installed. Install with: pip install anthropic"
            )
    return anthropic


def _get_openai():
    """Lazy import for OpenAI SDK."""
    global openai
    if openai is None:
        try:
            import openai as _openai
            openai = _openai
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed. Install with: pip install openai"
            )
    return openai


def _get_groq():
    """Lazy import for Groq SDK."""
    global Groq
    if Groq is None:
        try:
            from groq import Groq as _Groq
            Groq = _Groq
        except ImportError:
            raise ImportError(
                "Groq SDK not installed. Install with: pip install groq"
            )
    return Groq


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GROQ = "groq"
    WAYMORE = "waymore"


class BaseAgent(ABC):
    """Base class for all AI agents."""

    def __init__(
        self,
        provider: LLMProvider = LLMProvider.ANTHROPIC,
        anthropic_api_key: str = None,
        openai_api_key: str = None,
        groq_api_key: str = None,
        waymore_api_key: str = None,
        openai_model: str = None,
        openai_max_tokens: int = None,
        groq_model: str = None,
        anthropic_model: str = None,
        waymore_model: str = None,
    ):
        self.provider = provider
        self.anthropic_api_key = anthropic_api_key
        self.openai_api_key = openai_api_key
        self.groq_api_key = groq_api_key
        self.waymore_api_key = waymore_api_key

        # Use settings from config if not provided
        self.openai_model = openai_model or settings.OPENAI_MODEL
        self.openai_max_tokens = openai_max_tokens or settings.OPENAI_MAX_TOKENS
        self.groq_model = groq_model or settings.GROQ_MODEL
        self.anthropic_model = anthropic_model or settings.ANTHROPIC_MODEL
        self.waymore_model = waymore_model or settings.WAYMORE_MODEL

        # Initialize the appropriate client
        self._init_client()

    def _init_client(self):
        """Initialize the LLM client based on selected provider."""
        if self.provider == LLMProvider.ANTHROPIC:
            if not self.anthropic_api_key:
                raise ValueError(
                    "Anthropic provider selected but ANTHROPIC_API_KEY is not set in .env"
                )
            anthropic_sdk = _get_anthropic()
            self.client = anthropic_sdk.Anthropic(api_key=self.anthropic_api_key)
            self.model = self.anthropic_model
            self.max_tokens = 8000
        elif self.provider == LLMProvider.OPENAI:
            if not self.openai_api_key:
                raise ValueError(
                    "OpenAI provider selected but OPENAI_API_KEY is not set in .env"
                )
            openai_sdk = _get_openai()
            self.client = openai_sdk.OpenAI(api_key=self.openai_api_key)
            self.model = self.openai_model
            self.max_tokens = self.openai_max_tokens
        elif self.provider == LLMProvider.GROQ:
            if not self.groq_api_key:
                raise ValueError(
                    "Groq provider selected but GROQ_API_KEY is not set in .env"
                )
            Groq_cls = _get_groq()
            self.client = Groq_cls(api_key=self.groq_api_key)
            self.model = self.groq_model.strip()
            self.max_tokens = 8000
        elif self.provider == LLMProvider.WAYMORE:
            if not self.waymore_api_key:
                raise ValueError(
                    "Waymore provider selected but WAYMORE_API_KEY is not set in .env"
                )
            openai_sdk = _get_openai()
            self.client = openai_sdk.OpenAI(
                api_key=self.waymore_api_key,
                base_url=settings.WAYMORE_BASE_URL
            )
            self.model = self.waymore_model
            self.max_tokens = 8000
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        print(f"Initialized {self.provider.value} with model: {self.model}")

    def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic Claude API."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()

    def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API."""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()

    def _call_groq(self, prompt: str) -> str:
        """Call Groq API."""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()

    def _call_waymore(self, prompt: str) -> str:
        """Call Waymore API (OpenAI-compatible)."""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()

    def call_llm(self, prompt: str) -> str:
        """Call the appropriate LLM based on provider. Signature unchanged."""
        print(f"Calling {self.provider.value} API with model: {self.model}...")
        try:
            from app.services.llm_wrapper import call_llm as _wrap
            result = _wrap(
                provider=self.provider.value, model=self.model,
                prompt=prompt, client=self.client, max_tokens=self.max_tokens,
                agent_name=self.__class__.__name__,
            )
            return result["text"]
        except Exception:
            # Fallback to original direct calls if wrapper fails
            if self.provider.value == "anthropic":
                return self._call_anthropic(prompt)
            elif self.provider.value == "openai":
                return self._call_openai(prompt)
            elif self.provider.value == "groq":
                return self._call_groq(prompt)
            elif self.provider.value == "waymore":
                return self._call_waymore(prompt)
            raise

    def call_llm_chat(self, system: str, messages: list) -> str:
        """
        Multi-turn conversation call.
        system  : system/context prompt (page summary, test suite, etc.)
        messages: [{role: "user"|"assistant", content: str}, ...]
                  The final entry should be the current user turn.
        """
        print(f"[call_llm_chat] {self.provider.value} | turns={len(messages)}")
        try:
            if self.provider == LLMProvider.ANTHROPIC:
                response = self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, temperature=0,
                    system=system, messages=messages,
                )
                return response.content[0].text.strip()
            else:  # OpenAI-compatible: OpenAI, Groq, Waymore
                full_messages = [{"role": "system", "content": system}] + messages
                response = self.client.chat.completions.create(
                    model=self.model, max_tokens=self.max_tokens, messages=full_messages,
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[call_llm_chat] failed ({e}), falling back to single-turn")
            combined = f"{system}\n\n"
            for m in messages:
                role = "User" if m["role"] == "user" else "Assistant"
                combined += f"{role}: {m['content']}\n\n"
            return self.call_llm(combined.strip())

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """Execute the agent's main task. Must be implemented by subclasses."""
        pass
