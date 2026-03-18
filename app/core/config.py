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
    OPENAI_MAX_TOKENS: int = 16000

    # Groq Configuration
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"  # Default model (70b-versatile is decommissioned)

    # Anthropic Configuration
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"

    # Waymore Configuration
    WAYMORE_API_KEY: str = ""
    WAYMORE_MODEL: str = "Waymore-A1-Instruct-1011"
    WAYMORE_BASE_URL: str = "https://chat.waymore.ai/api"

    # Default LLM provider used if none specified (groq is cost-effective and fast)
    DEFAULT_LLM_PROVIDER: str = "groq"

    # Image Analysis (Vision) — OFF by default
    # When ON: if a selector fails during recording, a screenshot is sent to the
    # vision model which suggests alternative selectors based on what it sees.
    IMAGE_ANALYSIS_ENABLED: bool = False
    GROQ_VISION_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    # Dedicated API key for the vision model (separate from the text model key)
    GROQ_VISION_API_KEY: str = ""
    OPENAI_VISION_MODEL: str = "gpt-4o-mini"
    # Which provider to use for vision: "groq" or "openai"
    VISION_PROVIDER: str = "groq"

    class Config:
        env_file = ".env"


settings = Settings()
