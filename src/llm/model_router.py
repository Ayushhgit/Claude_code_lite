"""
Model router — multi-model Groq routing with rate-limit-aware selection.

Auto mode cycles across models based on task type so no single model
hits its rate/token limit during a long run.
"""
import time
import threading

# ── Model Registry ────────────────────────────────────────────────────────────

GROQ_MODELS = {
    "llama-3.1-8b-instant": {
        "display": "LLaMA 3.1 8B Instant",
        "tier": "fast",
        "description": "Fastest, lowest latency. Simple tool calls and quick questions.",
    },
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "display": "LLaMA 4 Scout 17B",
        "tier": "mid",
        "description": "Balanced speed/quality. Multi-step tasks and code generation.",
    },
    "openai/gpt-oss-20b": {
        "display": "GPT OSS 20B",
        "tier": "mid",
        "description": "Mid-size open model. Strong tool-schema compliance.",
    },
    "qwen/qwen3-32b": {
        "display": "Qwen3 32B",
        "tier": "large",
        "description": "Large reasoning model. Excellent code and planning.",
    },
    "openai/gpt-oss-120b": {
        "display": "GPT OSS 120B",
        "tier": "large",
        "description": "Largest model. Best for complex architecture and deep analysis.",
    },
    "openai/gpt-oss-safeguard-20b": {
        "display": "GPT OSS Safeguard 20B",
        "tier": "safety",
        "description": "Safety-tuned. Used for review and validation passes.",
    },
    "groq/compound": {
        "display": "Groq Compound Beta",
        "tier": "compound",
        "description": "Compound AI with built-in search. Best for research tasks.",
    },
}

GEMINI_MODELS = {
    "gemini-2.5-flash": {
        "display": "Gemini 2.5 Flash",
        "tier": "fast",
        "description": "Fast Gemini model for general tasks.",
    },
    "gemini-2.5-pro": {
        "display": "Gemini 2.5 Pro",
        "tier": "large",
        "description": "Most capable Gemini model.",
    },
}

# Task type → preferred model order (first non-rate-limited wins)
TASK_MODEL_MAP = {
    "fast":     ["llama-3.1-8b-instant", "openai/gpt-oss-20b"],
    "mid":      ["meta-llama/llama-4-scout-17b-16e-instruct", "openai/gpt-oss-20b", "qwen/qwen3-32b"],
    "complex":  ["openai/gpt-oss-120b", "qwen/qwen3-32b", "meta-llama/llama-4-scout-17b-16e-instruct"],
    "review":   ["openai/gpt-oss-120b", "qwen/qwen3-32b"],
    "safety":   ["openai/gpt-oss-safeguard-20b", "openai/gpt-oss-120b"],
    "compound": ["groq/compound", "openai/gpt-oss-120b"],
}

# Round-robin pool for auto mode (excludes safety/compound — only used when explicitly routed)
AUTO_ROTATION = [
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "groq/compound",
]

# ── State ─────────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_rate_limited_until: dict[str, float] = {}  # model_id -> expiry timestamp
_auto_idx = 0                                # current rotation position
_mode = "auto"                               # "auto" or a specific model id
_last_used: str | None = None               # last model selected (for display)


# ── Public API ────────────────────────────────────────────────────────────────

def get_all_models(provider: str = "groq") -> dict:
    return GEMINI_MODELS if provider == "gemini" else GROQ_MODELS


def get_current_mode() -> str:
    return _mode


def get_last_used() -> str | None:
    return _last_used


def set_mode(mode: str) -> None:
    """Set 'auto' or a specific model ID."""
    global _mode
    if mode == "auto":
        _mode = "auto"
    elif mode in GROQ_MODELS or mode in GEMINI_MODELS:
        _mode = mode
    else:
        available = list(GROQ_MODELS.keys()) + list(GEMINI_MODELS.keys())
        raise ValueError(f"Unknown model '{mode}'. Available: {available}")


def mark_rate_limited(model_id: str, retry_after: int = 60) -> None:
    """Mark model as unavailable for retry_after seconds."""
    with _lock:
        _rate_limited_until[model_id] = time.time() + retry_after


def is_rate_limited(model_id: str) -> bool:
    expiry = _rate_limited_until.get(model_id, 0)
    if time.time() < expiry:
        return True
    _rate_limited_until.pop(model_id, None)
    return False


def get_rate_limit_eta(model_id: str) -> int:
    """Seconds until rate limit clears, or 0 if available."""
    return max(0, int(_rate_limited_until.get(model_id, 0) - time.time()))


def select_model(task_type: str = "mid") -> str:
    """
    Return the best available model ID for the given task type.
    Falls back gracefully if preferred models are rate-limited.
    """
    global _auto_idx, _last_used

    with _lock:
        if _mode != "auto":
            # User forced a specific model
            if not is_rate_limited(_mode):
                _last_used = _mode
                return _mode
            # That model is rate-limited — fall through to auto selection

        # Try task-specific preference list first
        preferred = TASK_MODEL_MAP.get(task_type, TASK_MODEL_MAP["mid"])
        for model in preferred:
            if not is_rate_limited(model):
                _last_used = model
                return model

        # All preferred models exhausted — round-robin full rotation
        start = _auto_idx
        for i in range(len(AUTO_ROTATION)):
            idx = (start + i) % len(AUTO_ROTATION)
            model = AUTO_ROTATION[idx]
            if not is_rate_limited(model):
                _auto_idx = (idx + 1) % len(AUTO_ROTATION)
                _last_used = model
                return model

        # Every model rate-limited — return the next in rotation and let caller handle it
        fallback = AUTO_ROTATION[_auto_idx % len(AUTO_ROTATION)]
        _last_used = fallback
        return fallback


def get_status_summary() -> list[tuple[str, str, str, str]]:
    """
    Returns list of (model_id, display_name, tier, status_str) for display.
    """
    rows = []
    for mid, info in GROQ_MODELS.items():
        eta = get_rate_limit_eta(mid)
        if eta > 0:
            status = f"⏳ {eta}s cooldown"
        elif _mode == mid:
            status = "✓ forced"
        elif mid == _last_used:
            status = "◆ last used"
        else:
            status = "available"
        rows.append((mid, info["display"], info["tier"], status))
    return rows
