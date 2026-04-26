import os
import re
import time
from dotenv import load_dotenv
from llm import key_pool

load_dotenv()

MAX_ATTEMPTS = 7  # max total attempts across all model switches

# ── Session token accumulator ────────────────────────────────────────────────
# Tracks REAL usage from API responses (not char/4 estimates).
_session_stats: dict = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "calls": 0,
    "cache_read_tokens": 0,   # Groq auto-cache hits when available
}

def get_session_stats() -> dict:
    """Return copy of real token usage accumulated this session."""
    return dict(_session_stats)

def reset_session_stats() -> None:
    _session_stats.update({"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "cache_read_tokens": 0})

def _record_usage(usage) -> None:
    """Update accumulator from a Groq/Gemini usage object."""
    if not usage:
        return
    _session_stats["prompt_tokens"]     += getattr(usage, "prompt_tokens", 0) or 0
    _session_stats["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
    _session_stats["calls"]             += 1
    # Groq exposes prompt_cache_hit_tokens on some models
    _session_stats["cache_read_tokens"] += getattr(usage, "prompt_cache_hit_tokens", 0) or 0


def generate(messages, tools=None, task_type="mid"):
    """
    Unified LLM generation.
    Routes to Groq (multi-model, auto-routing) or Gemini based on PROVIDER env var.
    task_type hint: "fast" | "mid" | "complex" | "review" | "safety" | "compound"
    """
    provider = os.getenv("PROVIDER", "groq").lower()
    if provider == "gemini":
        return _generate_gemini(messages, tools)
    else:
        return _generate_groq(messages, tools, task_type)


class QuotaExhaustedError(RuntimeError):
    """All models quota-exhausted — not a transient rate limit."""
    pass


def _extract_retry_after(exception) -> int:
    """Parse retry-after seconds from error message."""
    s = str(exception)
    m = re.search(r'retry.after[:\s]+(\d+)', s, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)\s*second', s, re.IGNORECASE)
    if m:
        return min(int(m.group(1)), 300)
    return 60


def _is_quota_exhausted(exception) -> bool:
    s = str(exception)
    return ('limit: 0' in s or 'RESOURCE_EXHAUSTED' in s) and ('429' in s or 'quota' in s.lower())


def _is_rate_limit(exception) -> bool:
    if _is_quota_exhausted(exception):
        return False
    s = str(exception).lower()
    return any(code in s for code in ['429', 'rate_limit', 'rate limit', '503', '502', '500'])


def _sanitize_str(s: str) -> str:
    """Strip surrogate characters that break JSON serialization."""
    return s.encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_messages(messages: list) -> list:
    """Recursively sanitize all string values in messages list."""
    result = []
    for msg in messages:
        m = dict(msg)
        if isinstance(m.get("content"), str):
            m["content"] = _sanitize_str(m["content"])
        elif isinstance(m.get("content"), list):
            sanitized_parts = []
            for part in m["content"]:
                if isinstance(part, dict):
                    p = dict(part)
                    if isinstance(p.get("text"), str):
                        p["text"] = _sanitize_str(p["text"])
                    sanitized_parts.append(p)
                else:
                    sanitized_parts.append(part)
            m["content"] = sanitized_parts
        # Sanitize tool_calls if present
        if m.get("tool_calls"):
            clean_calls = []
            for tc in m["tool_calls"]:
                if isinstance(tc, dict):
                    tc = dict(tc)
                    if isinstance(tc.get("function"), dict):
                        fn = dict(tc["function"])
                        if isinstance(fn.get("arguments"), str):
                            fn["arguments"] = _sanitize_str(fn["arguments"])
                        tc["function"] = fn
                clean_calls.append(tc)
            m["tool_calls"] = clean_calls
        result.append(m)
    return result


def _generate_groq(messages, tools, task_type="mid"):
    from groq import Groq
    from llm import model_router
    from utils.ui import console

    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    # Constrained Decoding for small models: force JSON mode for classification
    if task_type == "fast" and not tools:
        kwargs["response_format"] = {"type": "json_object"}

    # Lower temperature for fast models to reduce hallucination
    temperature = 0.1 if task_type == "fast" else 0.2

    total_keys = key_pool.get_key_count()
    if total_keys == 0:
        raise RuntimeError("No Groq API keys configured. Set GROQ_API_KEY_1 or GROQ_API_KEY in .env")

    # Outer loop: iterate over API keys
    # Inner loop: iterate over models per key
    # This gives us key_count × MAX_ATTEMPTS total attempts
    keys_tried = 0
    last_model = None

    while keys_tried <= total_keys:
        active_key = key_pool.get_active_key()
        if active_key is None:
            break

        # Build a fresh client for this key
        client = Groq(api_key=active_key, max_retries=0)
        model_exhausted_count = 0

        for attempt in range(MAX_ATTEMPTS):
            model = model_router.select_model(task_type)

            if last_model and model != last_model:
                info = model_router.GROQ_MODELS.get(model, {})
                console.print(f"  [dim]🔄 → {info.get('display', model)} ({model})[/dim]")
            last_model = model

            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    messages=_sanitize_messages(messages),
                    **kwargs
                )
                _record_usage(getattr(response, "usage", None))
                message = response.choices[0].message
                if not tools:
                    return message.content.strip() if message.content else ""
                return message

            except Exception as e:
                if _is_quota_exhausted(e):
                    # Hard quota on this model — mark it and try next model
                    model_router.mark_rate_limited(model, retry_after=3600)
                    model_exhausted_count += 1
                    console.print(f"  [red]✗ {model} quota exhausted. Switching model...[/red]")

                    # All models for this key are exhausted — rotate API key
                    if model_exhausted_count >= len(model_router.AUTO_ROTATION):
                        key_pool.mark_key_exhausted(active_key)
                        keys_tried += 1
                        next_key = key_pool.get_active_key()
                        if next_key and next_key != active_key and keys_tried < total_keys:
                            key_hint = f"{next_key[:8]}..."
                            console.print(
                                f"  [bold red]✗ All models quota-exhausted on key {key_pool.get_active_key_index()}/{total_keys}."
                                f" Rotating to next API key ({key_hint})[/bold red]"
                            )
                            break  # break inner loop → outer while retries with new key
                        raise QuotaExhaustedError(
                            f"All {total_keys} Groq API key(s) and all models are quota-exhausted."
                        ) from e
                    continue

                if _is_rate_limit(e):
                    retry_after = _extract_retry_after(e)
                    model_router.mark_rate_limited(model, retry_after=retry_after)
                    console.print(
                        f"  [yellow]⏳ {model} rate limited ({retry_after}s cooldown). Switching model...[/yellow]"
                    )
                    # No sleep — immediately try a different model
                    continue

                # Non-rate-limit error: small backoff, retry same model selection
                wait = min(2 ** attempt * 2, 20)
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(wait)
                    continue
                raise
        else:
            # Inner for-loop completed without a successful return or a key-rotation break
            break

    raise QuotaExhaustedError(
        f"Groq: all API keys ({total_keys}) and models exhausted after maximum attempts."
    )


def _generate_gemini(messages, tools):
    from openai import OpenAI

    client = OpenAI(
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        max_retries=0,
    )
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    kwargs = {}
    if tools:
        kwargs["tools"] = tools

    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=_sanitize_messages(messages),
                **kwargs
            )
            _record_usage(getattr(response, "usage", None))
            message = response.choices[0].message
            if not tools:
                return message.content.strip() if message.content else ""
            return message

        except Exception as e:
            if _is_quota_exhausted(e):
                raise QuotaExhaustedError(f"Gemini quota exhausted: {e}") from e
            if _is_rate_limit(e):
                wait = min(2 ** attempt * 5, 60)
                from utils.ui import console
                console.print(f"  [yellow]⏳ Gemini rate limited. Waiting {wait}s...[/yellow]")
                time.sleep(wait)
                last_err = e
                continue
            raise

    raise last_err or RuntimeError("Gemini: all attempts failed.")
