from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "healthy"}


@router.get("/llm-providers")
async def get_llm_providers():
    """Get available LLM providers and their configuration status."""
    return {
        "providers": [
            {
                "name": "anthropic",
                "display_name": "Anthropic Claude",
                "model": settings.ANTHROPIC_MODEL,
                "configured": bool(settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY != "your_anthropic_api_key_here")
            },
            {
                "name": "openai",
                "display_name": "OpenAI",
                "model": settings.OPENAI_MODEL,
                "max_tokens": settings.OPENAI_MAX_TOKENS,
                "configured": bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key_here")
            },
            {
                "name": "groq",
                "display_name": "Groq",
                "model": settings.GROQ_MODEL,
                "configured": bool(settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key_here")
            }
        ],
        "default": settings.DEFAULT_LLM_PROVIDER
    }
