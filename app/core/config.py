from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "Test Automation Agent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 9000

    # Test Execution Timeouts (in milliseconds)
    DEFAULT_ACTION_TIMEOUT: int = 10000  # Default timeout for actions
    STEP_MAX_RETRIES: int = 2  # Max retries per step
    RETRY_TIMEOUT_MULTIPLIER: float = 1.2  # Timeout multiplier for retries
    WAIT_TIMEOUT: int = 5000  # Wait operations timeout
    NAVIGATION_TIMEOUT: int = 30000  # Navigation timeout

    # OpenAI Configuration
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 4096

    # Groq Configuration
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"  # Default model (70b-versatile is decommissioned)

    # Anthropic Configuration
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"

    # Default LLM provider used if none specified (groq is cost-effective and fast)
    DEFAULT_LLM_PROVIDER: str = "groq"

    class Config:
        env_file = ".env"


settings = Settings()
