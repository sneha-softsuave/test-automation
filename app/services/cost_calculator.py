# USD per token — update as provider pricing changes
MODEL_PRICING = {
    "gpt-4o":                    {"input": 0.000005,   "output": 0.000015},
    "gpt-4o-mini":               {"input": 0.00000015, "output": 0.0000006},
    "gpt-4":                     {"input": 0.00003,    "output": 0.00006},
    "claude-opus-4-6":           {"input": 0.000015,   "output": 0.000075},
    "claude-sonnet-4-5-20250929":{"input": 0.000003,   "output": 0.000015},
    "claude-haiku-4-5-20251001": {"input": 0.0000008,  "output": 0.000004},
    "llama-3.1-8b-instant":      {"input": 0.0000001,  "output": 0.0000001},
    "llama-3.3-70b-versatile":   {"input": 0.00000059, "output": 0.00000079},
    "mixtral-8x7b-32768":        {"input": 0.00000027, "output": 0.00000027},
}

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
    return round(input_tokens * pricing["input"] + output_tokens * pricing["output"], 8)
