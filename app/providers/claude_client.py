"""Anthropic Claude provider client."""


def call_claude(model: str, prompt: str, client, max_tokens: int) -> dict:
    response = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    return {
        "text":  response.content[0].text.strip(),
        "usage": response.usage,   # .input_tokens / .output_tokens
    }
