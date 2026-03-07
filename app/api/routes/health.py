from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings
import time
from datetime import datetime

router = APIRouter()


# ---------------------------------------------------------------------------
# In-memory image analysis toggle
# (persists for the lifetime of the server process; survives navigation)
# ---------------------------------------------------------------------------
_image_analysis_enabled: bool = settings.IMAGE_ANALYSIS_ENABLED
_vision_provider: str = settings.VISION_PROVIDER


class ImageAnalysisToggle(BaseModel):
    enabled: bool


class VisionProviderSet(BaseModel):
    provider: str  # "groq" or "openai"


@router.get("/health")
async def health_check():
    return {"status": "healthy"}


@router.get("/llm-providers")
async def get_llm_providers():
    """Get available LLM providers and their configuration status."""
    return {
        "providers": [
            {
                "id": "groq",
                "display_name": "Groq",
                "model": settings.GROQ_MODEL,
                "api_key_configured": bool(settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key_here"),
                "is_default": settings.DEFAULT_LLM_PROVIDER == "groq"
            },
            {
                "id": "openai",
                "display_name": "OpenAI",
                "model": settings.OPENAI_MODEL,
                "max_tokens": settings.OPENAI_MAX_TOKENS,
                "api_key_configured": bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key_here"),
                "is_default": settings.DEFAULT_LLM_PROVIDER == "openai"
            },
            {
                "id": "anthropic",
                "display_name": "Anthropic Claude",
                "model": settings.ANTHROPIC_MODEL,
                "api_key_configured": bool(settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY != "your_anthropic_api_key_here"),
                "is_default": settings.DEFAULT_LLM_PROVIDER == "anthropic"
            }
        ],
        "default_provider": settings.DEFAULT_LLM_PROVIDER
    }


@router.post("/ai-providers/validate")
async def validate_ai_providers():
    """
    Test actual API connectivity for all configured providers.
    Makes lightweight API calls to verify keys are valid.

    Returns:
        {
            "groq": {"available": bool, "model": str, "latency_ms": float, "error": str?},
            "openai": {"available": bool, "model": str, "latency_ms": float, "error": str?},
            "anthropic": {"available": bool, "model": str, "latency_ms": float, "error": str?},
            "checked_at": ISO timestamp
        }
    """
    results = {}

    # Test Groq
    if settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key_here":
        start = time.time()
        try:
            from groq import Groq
            client = Groq(api_key=settings.GROQ_API_KEY)
            # Make minimal API call
            response = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,
                timeout=5.0
            )
            latency = (time.time() - start) * 1000
            results["groq"] = {
                "available": True,
                "model": settings.GROQ_MODEL,
                "latency_ms": round(latency, 2)
            }
        except Exception as e:
            results["groq"] = {
                "available": False,
                "model": settings.GROQ_MODEL,
                "error": str(e)
            }
    else:
        results["groq"] = {
            "available": False,
            "model": settings.GROQ_MODEL,
            "error": "API key not configured"
        }

    # Test OpenAI
    if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key_here":
        start = time.time()
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=5.0)
            # Make minimal API call
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1
            )
            latency = (time.time() - start) * 1000
            results["openai"] = {
                "available": True,
                "model": settings.OPENAI_MODEL,
                "latency_ms": round(latency, 2)
            }
        except Exception as e:
            results["openai"] = {
                "available": False,
                "model": settings.OPENAI_MODEL,
                "error": str(e)
            }
    else:
        results["openai"] = {
            "available": False,
            "model": settings.OPENAI_MODEL,
            "error": "API key not configured"
        }

    # Test Anthropic
    if settings.ANTHROPIC_API_KEY and settings.ANTHROPIC_API_KEY != "your_anthropic_api_key_here":
        start = time.time()
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=5.0)
            # Make minimal API call
            response = client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=1,
                messages=[{"role": "user", "content": "test"}]
            )
            latency = (time.time() - start) * 1000
            results["anthropic"] = {
                "available": True,
                "model": settings.ANTHROPIC_MODEL,
                "latency_ms": round(latency, 2)
            }
        except Exception as e:
            results["anthropic"] = {
                "available": False,
                "model": settings.ANTHROPIC_MODEL,
                "error": str(e)
            }
    else:
        results["anthropic"] = {
            "available": False,
            "model": settings.ANTHROPIC_MODEL,
            "error": "API key not configured"
        }

    return {
        **results,
        "checked_at": datetime.now().isoformat()
    }


# ---------------------------------------------------------------------------
# Image Analysis endpoints
# ---------------------------------------------------------------------------

@router.get("/image-analysis/status")
async def get_image_analysis_status():
    """Return the current image analysis (vision) toggle state and daily usage."""
    from app.agents.image_analyzer import get_usage_stats
    usage = get_usage_stats()
    vision_key = settings.GROQ_VISION_API_KEY or ""
    openai_key = settings.OPENAI_API_KEY or ""
    return {
        "enabled": _image_analysis_enabled,
        "vision_provider": _vision_provider,
        "models": {
            "groq": settings.GROQ_VISION_MODEL,
            "openai": settings.OPENAI_VISION_MODEL,
        },
        # legacy field — keep for backwards compat
        "model": settings.GROQ_VISION_MODEL if _vision_provider == "groq" else settings.OPENAI_VISION_MODEL,
        "vision_key_configured": bool(vision_key and vision_key not in {"", "your_groq_vision_api_key_here"}),
        "openai_key_configured": bool(openai_key and openai_key not in {"", "your_openai_api_key_here"}),
        "usage_today": usage["count"],
        "usage_date": usage["date"],
    }


@router.post("/image-analysis/toggle")
async def toggle_image_analysis(body: ImageAnalysisToggle):
    """Enable or disable image analysis at runtime (no server restart required)."""
    global _image_analysis_enabled
    _image_analysis_enabled = body.enabled
    # Patch settings so the agent picks up the change immediately
    settings.IMAGE_ANALYSIS_ENABLED = body.enabled
    return {"enabled": _image_analysis_enabled}


@router.post("/image-analysis/set-vision-provider")
async def set_vision_provider(body: VisionProviderSet):
    """Switch the active vision provider between 'groq' and 'openai' at runtime."""
    global _vision_provider
    provider = body.provider.lower()
    if provider not in ("groq", "openai"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="provider must be 'groq' or 'openai'")
    _vision_provider = provider
    settings.VISION_PROVIDER = provider
    return {"vision_provider": _vision_provider}
