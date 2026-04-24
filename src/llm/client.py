import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

MAX_ATTEMPTS = 7  # max total attempts across all model switches


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


def _generate_groq(messages, tools, task_type="mid"):
    from groq import Groq
    from llm import model_router
    from utils.ui import console

    client = Groq(api_key=os.getenv("GROQ_API_KEY"), max_retries=0)

    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    last_model = None
    exhausted_count = 0

    for attempt in range(MAX_ATTEMPTS):
        model = model_router.select_model(task_type)

        if last_model and model != last_model:
            info = model_router.GROQ_MODELS.get(model, {})
            console.print(f"  [dim]🔄 → {info.get('display', model)} ({model})[/dim]")
        last_model = model

        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0.2,
                messages=messages,
                **kwargs
            )
            message = response.choices[0].message
            if not tools:
                return message.content.strip() if message.content else ""
            return message

        except Exception as e:
            if _is_quota_exhausted(e):
                # Hard quota — mark for 1 hour, try next model
                model_router.mark_rate_limited(model, retry_after=3600)
                exhausted_count += 1
                if exhausted_count >= len(model_router.AUTO_ROTATION):
                    raise QuotaExhaustedError("All Groq models quota-exhausted.") from e
                console.print(f"  [red]✗ {model} quota exhausted. Switching...[/red]")
                continue

            if _is_rate_limit(e):
                retry_after = _extract_retry_after(e)
                model_router.mark_rate_limited(model, retry_after=retry_after)
                console.print(f"  [yellow]⏳ {model} rate limited ({retry_after}s cooldown). Switching model...[/yellow]")
                # No sleep — immediately try a different model
                continue

            # Non-rate-limit error: small backoff, retry same model selection
            wait = min(2 ** attempt * 2, 20)
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"Groq: all {MAX_ATTEMPTS} attempts failed across available models.")


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
                messages=messages,
                **kwargs
            )
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
