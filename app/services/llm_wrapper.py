"""
Central LLM dispatcher. ALL provider calls flow through here.
Returns {"text": str, "tokens": int, "cost": float}
"""
from app.providers.openai_client  import call_openai
from app.providers.claude_client  import call_claude
from app.providers.groq_client    import call_groq
from app.services.token_counter   import extract_tokens
from app.services.cost_calculator import calculate_cost
from app.utils.logger             import log_async
from datetime import datetime

def call_llm(provider: str, model: str, prompt: str,
             client, max_tokens: int, agent_name: str = "unknown") -> dict:
    if provider in ("openai", "waymore"):
        result = call_openai(model, prompt, client, max_tokens)
    elif provider == "anthropic":
        result = call_claude(model, prompt, client, max_tokens)
    elif provider == "groq":
        result = call_groq(model, prompt, client, max_tokens)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    text   = result["text"]
    tokens = extract_tokens(provider, result.get("usage"), prompt=prompt, output=text)
    cost   = calculate_cost(model, tokens["input_tokens"], tokens["output_tokens"])

    log_async({"timestamp": datetime.now().isoformat(), "agent": agent_name,
               "provider": provider, "model": model,
               "input_tokens": tokens["input_tokens"], "output_tokens": tokens["output_tokens"],
               "total_tokens": tokens["total_tokens"], "cost_usd": cost})

    return {"text": text, "tokens": tokens["total_tokens"], "cost": cost}


def call_llm_chat(provider: str, model: str, system: str, messages: list,
                  client, max_tokens: int, agent_name: str = "unknown") -> dict:
    """
    Multi-turn chat call — ALL chat conversations flow through here for token tracking.
    Returns {"text": str, "tokens": int, "cost": float}
    """
    if provider == "anthropic":
        response = client.messages.create(
            model=model, max_tokens=max_tokens, temperature=0,
            system=system, messages=messages,
        )
        text  = response.content[0].text.strip()
        usage = response.usage
    else:  # openai, groq, waymore
        full_messages = [{"role": "system", "content": system}] + messages
        response = client.chat.completions.create(
            model=model, max_tokens=max_tokens, messages=full_messages,
        )
        text  = response.choices[0].message.content.strip()
        usage = response.usage

    # Use system + all message content as the "prompt" for token estimation
    combined_prompt = system + "\n" + "\n".join(m["content"] for m in messages)
    tokens = extract_tokens(provider, usage, prompt=combined_prompt, output=text)
    cost   = calculate_cost(model, tokens["input_tokens"], tokens["output_tokens"])

    log_async({"timestamp": datetime.now().isoformat(), "agent": agent_name,
               "provider": provider, "model": model,
               "input_tokens": tokens["input_tokens"], "output_tokens": tokens["output_tokens"],
               "total_tokens": tokens["total_tokens"], "cost_usd": cost})

    return {"text": text, "tokens": tokens["total_tokens"], "cost": cost}
