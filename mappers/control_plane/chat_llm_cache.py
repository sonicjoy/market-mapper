"""Process-local cache for ChatLLM clients and resolved API keys."""

from __future__ import annotations

import threading
import time

from mappers.control_plane.chat_llm import ChatLLM, build_chat_llm, resolve_chat_api_key
from mappers.control_plane.settings import Settings

_TTL_SEC = 3600.0
_lock = threading.Lock()
_key_cache: dict[tuple[str, str], tuple[float, str]] = {}
_llm_cache: dict[tuple[str, str, str], tuple[float, ChatLLM]] = {}


def cached_chat_api_key(settings: Settings) -> str:
    """Resolve GSM/env key with TTL."""
    key_id = (settings.chat_provider, settings.chat_model)
    now = time.time()
    with _lock:
        hit = _key_cache.get(key_id)
        if hit and now - hit[0] < _TTL_SEC:
            return hit[1]
    key = resolve_chat_api_key(settings)
    with _lock:
        _key_cache[key_id] = (now, key)
    return key


def cached_chat_llm(settings: Settings) -> ChatLLM:
    """Build or reuse provider LLM for (provider, model, key fingerprint)."""
    api_key = cached_chat_api_key(settings)
    fp = api_key[:8] if api_key else ""
    cache_id = (settings.chat_provider, settings.chat_model, fp)
    now = time.time()
    with _lock:
        hit = _llm_cache.get(cache_id)
        if hit and now - hit[0] < _TTL_SEC:
            return hit[1]
    llm = build_chat_llm(settings, api_key=api_key)
    with _lock:
        _llm_cache[cache_id] = (now, llm)
    return llm


def clear_chat_llm_cache() -> None:
    """Test helper."""
    with _lock:
        _key_cache.clear()
        _llm_cache.clear()
