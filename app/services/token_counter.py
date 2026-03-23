"""Provider-specific token counting. API usage is always preferred; counting is fallback."""
import tiktoken

_openai_enc = tiktoken.get_encoding("cl100k_base")

# Optional: transformers Llama tokenizer (more accurate for Groq).
# Requires: pip install transformers  + HuggingFace token for meta-llama/Llama-2-7b-hf
# Falls back silently to tiktoken (~5% off for Llama models).
try:
    from transformers import AutoTokenizer
    _llama_tok = AutoTokenizer.from_pretrained("meta-llama/Llama-2-7b-hf")
    def _llama_count(text: str) -> int:
        return len(_llama_tok.encode(text)) if text else 0
except Exception:
    def _llama_count(text: str) -> int:
        return len(_openai_enc.encode(text)) if text else 0


def count_tokens(provider: str, text: str) -> int:
    if not text:
        return 0
    if provider in ("openai", "waymore"):
        return len(_openai_enc.encode(text))
    elif provider == "groq":
        return _llama_count(text)
    elif provider == "anthropic":
        return int(len(text.split()) * 1.3)   # no public tokenizer
    return len(text) // 4


def extract_tokens(provider: str, usage, prompt: str = None, output: str = None) -> dict:
    """Normalise token data from any provider's response.usage object."""
    if provider in ("openai", "waymore") and usage:
        return {"input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
                "total_tokens":  usage.total_tokens}
    if provider == "anthropic" and usage:
        return {"input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens":  usage.input_tokens + usage.output_tokens}
    if provider == "groq":
        if usage and getattr(usage, "prompt_tokens", None) is not None:
            return {"input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_tokens":  usage.total_tokens}
        inp = count_tokens("groq", prompt)
        out = count_tokens("groq", output)
        return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
    # final fallback
    inp = count_tokens(provider, prompt)
    out = count_tokens(provider, output)
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}
