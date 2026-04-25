"""
key_pool.py — Groq API Key Rotation Pool

Manages a pool of Groq API keys loaded from environment variables.
When a key's quota is exhausted (HTTP 429 with limit:0), the pool
automatically rotates to the next available key.

Environment variable convention:
    GROQ_API_KEY_1=gsk_...   # Primary key
    GROQ_API_KEY_2=gsk_...   # Secondary key
    GROQ_API_KEY_3=gsk_...   # Tertiary key
    ...up to any number...

Backward compatible: if no numbered keys are found, falls back to
the bare GROQ_API_KEY variable.

Thread-safe: uses threading.Lock for all state mutations.
"""

import os
import time
import threading
from dotenv import load_dotenv

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

# How long (seconds) before a quota-exhausted key is retried (1 hour)
KEY_COOLDOWN_SECONDS = 3600

# Maximum number of numbered keys to look for (GROQ_API_KEY_1 … _MAX_KEYS)
MAX_KEYS = 10


# ── State ─────────────────────────────────────────────────────────────────────

_lock = threading.Lock()
_keys: list[str] = []           # ordered list of API key strings
_exhausted_until: dict[str, float] = {}  # key -> expiry timestamp
_current_index: int = 0         # index of the key last successfully used


# ── Initialization ────────────────────────────────────────────────────────────

def _load_keys() -> list[str]:
    """
    Discover all Groq API keys from environment variables.

    Search order:
    1. GROQ_API_KEY_1, GROQ_API_KEY_2, … GROQ_API_KEY_N  (numbered, preferred)
    2. GROQ_API_KEY  (legacy fallback if no numbered keys found)

    Returns a deduplicated, ordered list of non-empty key strings.
    """
    found: list[str] = []
    seen: set[str] = set()

    for i in range(1, MAX_KEYS + 1):
        key = os.getenv(f"GROQ_API_KEY_{i}", "").strip()
        if key and key not in seen:
            found.append(key)
            seen.add(key)

    # Fallback to bare key if no numbered keys present
    if not found:
        bare = os.getenv("GROQ_API_KEY", "").strip()
        if bare:
            found.append(bare)

    return found


def _ensure_loaded() -> None:
    """Lazy-load keys on first access."""
    global _keys
    if not _keys:
        _keys = _load_keys()


# ── Public API ────────────────────────────────────────────────────────────────

def reload_keys() -> int:
    """
    Re-read keys from environment (useful after .env changes at runtime).
    Returns the number of keys loaded.
    """
    global _keys, _current_index
    with _lock:
        _keys = _load_keys()
        _current_index = 0
        return len(_keys)


def get_key_count() -> int:
    """Return total number of configured keys."""
    _ensure_loaded()
    return len(_keys)


def is_key_exhausted(key: str) -> bool:
    """Return True if this key is still in cooldown."""
    expiry = _exhausted_until.get(key, 0)
    if time.time() < expiry:
        return True
    _exhausted_until.pop(key, None)
    return False


def get_key_cooldown_eta(key: str) -> int:
    """Seconds until this key's cooldown expires, or 0 if available."""
    return max(0, int(_exhausted_until.get(key, 0) - time.time()))


def mark_key_exhausted(key: str, cooldown: int = KEY_COOLDOWN_SECONDS) -> None:
    """
    Mark a key as quota-exhausted for `cooldown` seconds.
    The pool will skip this key until the cooldown expires.
    """
    with _lock:
        _exhausted_until[key] = time.time() + cooldown


def get_active_key() -> str | None:
    """
    Return the best available (non-exhausted) Groq API key.

    Selection strategy:
    - Start from _current_index, walk forward through the key list.
    - Return the first key that is not quota-exhausted.
    - If all keys are exhausted, return the key whose cooldown expires
      soonest (caller must handle the resulting API error gracefully).

    Returns None if no keys are configured at all.
    """
    global _current_index
    _ensure_loaded()

    with _lock:
        if not _keys:
            return None

        n = len(_keys)
        start = _current_index

        for i in range(n):
            idx = (start + i) % n
            key = _keys[idx]
            if not is_key_exhausted(key):
                _current_index = idx
                return key

        # All keys exhausted — return the one with the shortest remaining cooldown
        best_idx = min(range(n), key=lambda i: _exhausted_until.get(_keys[i], 0))
        _current_index = best_idx
        return _keys[best_idx]


def rotate_key() -> str | None:
    """
    Explicitly advance to the next key in the pool (regardless of exhaustion).
    Returns the new active key, or None if the pool is empty.
    """
    global _current_index
    _ensure_loaded()

    with _lock:
        if not _keys:
            return None
        _current_index = (_current_index + 1) % len(_keys)
        return _keys[_current_index]


def get_status() -> list[dict]:
    """
    Return a list of status dicts for each configured key, suitable for display.

    Each dict contains:
        index     (int)  1-based position
        key_hint  (str)  first 8 + "..." + last 4 chars for safe display
        status    (str)  "available" | "exhausted (Xs remaining)"
        is_active (bool) True if this is the currently selected key
    """
    _ensure_loaded()
    rows = []
    for i, key in enumerate(_keys):
        eta = get_key_cooldown_eta(key)
        if eta > 0:
            status = f"exhausted ({eta}s cooldown)"
        else:
            status = "available"

        hint = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else key

        rows.append({
            "index":     i + 1,
            "key_hint":  hint,
            "status":    status,
            "is_active": (i == _current_index and not is_key_exhausted(key)),
        })
    return rows


def get_active_key_index() -> int:
    """Return the 1-based index of the currently active key, or 0 if none."""
    _ensure_loaded()
    if not _keys:
        return 0
    return _current_index + 1
