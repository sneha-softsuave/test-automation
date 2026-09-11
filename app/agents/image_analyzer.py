"""
ImageAnalyzer
Sends a page screenshot to a Groq vision model and asks it to suggest
Playwright selectors + interaction types for an element that could not be
found by the normal text/DOM-based lookup.

Only invoked when IMAGE_ANALYSIS_ENABLED=True in settings.

Usage counter resets every calendar day (not on process restart).
"""
import json
import logging
import threading
from datetime import date, datetime
from typing import Dict, List

from app.services.token_counter import extract_tokens
from app.services.cost_calculator import calculate_cost
from app.utils.logger import log_async

from app.core.config import settings

logger = logging.getLogger(__name__)

IMAGE_ANALYSIS_PROMPT = """You are a Playwright automation expert analyzing a browser screenshot to fix a failed test step.

FAILED ACTION:
- Instruction: "{instruction}"
- Action type attempted: {action_type}
- Selector tried: {selector}
- Error: {error}

Look at the screenshot carefully. Find the element the instruction refers to.

Return a JSON array of up to 3 fix attempts, ordered best-first. Each object:
{{
  "selector": "<playwright selector string>",
  "widget_type": "input|combobox|select|button|other",
  "interaction": "fill|type_and_select|select_option|click",
  "reasoning": "<one sentence: what you see and why this will work>"
}}

interaction guide:
- "fill"            → plain text/number/email input
- "type_and_select" → autocomplete/combobox: type value to trigger dropdown, then click matching option
- "select_option"   → native <select> HTML element
- "click"           → button, link, icon, toggle

Selector priority:
1. page.get_by_label('...')
2. page.get_by_placeholder('...')
3. page.get_by_role('...', name='...')
4. page.get_by_text('...', exact=True)
5. page.locator('[aria-label="..."]') or attribute selector

Return ONLY the JSON array. No prose."""

# ---------------------------------------------------------------------------
# Daily usage counter — resets at midnight (calendar day boundary).
# Stored in memory; survives navigation but not server restarts.
# A server restart resets to 0 for that day, which is acceptable.
# ---------------------------------------------------------------------------

_counter_lock = threading.Lock()
_usage_count: int = 0
_usage_date: date = date.today()


def _increment_counter() -> int:
    """Increment daily usage counter, resetting if the calendar day changed."""
    global _usage_count, _usage_date
    with _counter_lock:
        today = date.today()
        if today != _usage_date:
            _usage_count = 0
            _usage_date = today
        _usage_count += 1
        return _usage_count


def get_usage_stats() -> dict:
    """Return current usage count and the date it applies to."""
    global _usage_count, _usage_date
    with _counter_lock:
        today = date.today()
        if today != _usage_date:
            return {"count": 0, "date": today.isoformat()}
        return {"count": _usage_count, "date": _usage_date.isoformat()}


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def analyze_screenshot_for_selector(
    screenshot_b64: str,
    action_type: str,
    instruction: str,
    selector: str,
    error: str = "",
) -> List[Dict]:
    """
    Send screenshot to the configured vision model and get back fix suggestions.

    Each suggestion is a dict with keys: selector, widget_type, interaction, reasoning.
    Supports VISION_PROVIDER="groq" (llama-4-scout) or "openai" (gpt-4o-mini).
    Returns a list of suggestion dicts (may be empty if the model cannot help).
    Never raises — failures are logged and an empty list is returned.
    """
    if not settings.IMAGE_ANALYSIS_ENABLED:
        return []

    vision_provider = settings.VISION_PROVIDER.lower()

    if vision_provider == "openai":
        api_key = settings.OPENAI_API_KEY
        model_name = settings.OPENAI_VISION_MODEL
    else:
        api_key = settings.GROQ_VISION_API_KEY or settings.GROQ_API_KEY
        model_name = settings.GROQ_VISION_MODEL

    if not api_key:
        logger.warning(f"[ImageAnalysis] No API key configured for vision provider '{vision_provider}'")
        return []

    count = _increment_counter()
    logger.info(
        f"[ImageAnalysis] Invoking vision model '{model_name}' via {vision_provider} "
        f"(usage today: #{count}) | action={action_type!r} | "
        f"failed_selector={selector!r} | instruction={instruction!r}"
    )

    prompt = IMAGE_ANALYSIS_PROMPT.format(
        action_type=action_type,
        instruction=instruction,
        selector=selector,
        error=error or "(not provided)",
    )

    try:
        if vision_provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}",
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
                temperature=0.1,
                max_tokens=512,
            )
        else:
            from groq import Groq
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_b64}",
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
                temperature=0.1,
                max_completion_tokens=512,
            )

        raw = response.choices[0].message.content or ""

        # Track tokens through the central logger
        _usage = getattr(response, "usage", None)
        _provider = vision_provider  # "openai" or "groq"
        _tokens = extract_tokens(_provider, _usage, prompt=prompt, output=raw)
        _cost = calculate_cost(model_name, _tokens["input_tokens"], _tokens["output_tokens"])
        log_async({
            "timestamp": datetime.now().isoformat(),
            "agent": "ImageAnalyzer",
            "provider": _provider,
            "model": model_name,
            "input_tokens": _tokens["input_tokens"],
            "output_tokens": _tokens["output_tokens"],
            "total_tokens": _tokens["total_tokens"],
            "cost_usd": _cost,
        })

        raw = raw.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        # Extract the JSON array substring — model sometimes adds prose around it
        bracket_start = raw.find("[")
        bracket_end = raw.rfind("]")
        if bracket_start != -1 and bracket_end > bracket_start:
            raw = raw[bracket_start:bracket_end + 1]

        # Attempt strict parse first, then try to salvage
        suggestions: List[Dict] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and item.get("selector"):
                        suggestions.append(item)
                    elif isinstance(item, str) and item.strip():
                        # Backward compat: plain selector string — wrap as dict
                        suggestions.append({
                            "selector": item,
                            "widget_type": "input",
                            "interaction": "fill",
                            "reasoning": "",
                        })
        except json.JSONDecodeError:
            # Salvage: extract quoted selector strings as fallback
            import re as _re
            salvaged = _re.findall(r'"((?:[^"\\]|\\.)+)"', raw)
            plain_sels = [s for s in salvaged if "page." in s or "locator(" in s or "get_by" in s]
            if plain_sels:
                logger.warning(
                    f"[ImageAnalysis] JSON parse failed — salvaged {len(plain_sels)} selector(s) via regex"
                )
                suggestions = [
                    {"selector": s, "widget_type": "input", "interaction": "fill", "reasoning": ""}
                    for s in plain_sels
                ]

        if suggestions:
            logger.info(
                f"[ImageAnalysis] Vision model returned {len(suggestions)} suggestion(s): "
                + str([f"{s['selector']} ({s.get('interaction','?')})" for s in suggestions])
            )
            return suggestions

        logger.warning("[ImageAnalysis] Vision model returned no usable suggestions")

    except Exception as e:
        logger.warning(f"[ImageAnalysis] Vision model call failed: {e}")

    return []
