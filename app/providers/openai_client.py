"""OpenAI / Waymore provider client. Returns text + raw usage object."""


def call_openai(model: str, prompt: str, client, max_tokens: int) -> dict:
    response = client.chat.completions.create(
        model=model, max_tokens=max_tokens, temperature=0,
        messages=[{"role": "user", "content": prompt}]
    )
    return {
        "text":  response.choices[0].message.content.strip(),
        "usage": response.usage,   # .prompt_tokens / .completion_tokens / .total_tokens
    }
