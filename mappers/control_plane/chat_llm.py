"""ChatLLM protocol, FakeChatLLM, and provider factory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from mappers.control_plane.gsm_secret import access_secret
from mappers.control_plane.settings import Settings

# Secret Manager resource names (not secret values).
_DEFAULT_GEMINI_SECRET = "mm-mapping-bot-gemini-key"  # nosec B105
_DEFAULT_OPENAI_SECRET = "mm-mapping-bot-openai-key"  # nosec B105
_DEFAULT_DEEPSEEK_SECRET = "mm-mapping-bot-deepseek-key"  # nosec B105


@dataclass
class ToolCall:
    """One model-requested tool invocation."""

    name: str
    args: dict[str, Any]
    call_id: str = ""


@dataclass
class ChatLLMResult:
    """Non-stream turn result (token stream can wrap later)."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    # Provider-native assistant turn, replayed verbatim when the transcript is
    # continued. Gemini rejects reconstructed function calls (thought_signature).
    raw_content: Any = None


class ChatLLM(Protocol):
    """Provider-agnostic chat + function calling."""

    provider: str
    model: str

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatLLMResult: ...


@dataclass
class FakeChatLLM:
    """Scripted LLM for pytest (no network)."""

    provider: str = "fake"
    model: str = "fake"
    script: list[ChatLLMResult] = field(default_factory=list)
    _i: int = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatLLMResult:
        _ = (messages, tools)
        if self._i >= len(self.script):
            return ChatLLMResult(text="(fake exhausted)", finish_reason="stop")
        item = self.script[self._i]
        self._i += 1
        return item


def resolve_chat_api_key(settings: Settings) -> str:
    """Env override first, else GSM secret for the configured provider."""
    env_key = (os.environ.get("MAPPING_CP_CHAT_API_KEY") or "").strip()
    if env_key:
        return env_key
    secret = settings.chat_api_key_secret
    if not secret:
        secret = {
            "gemini": _DEFAULT_GEMINI_SECRET,
            "openai": _DEFAULT_OPENAI_SECRET,
            "deepseek": _DEFAULT_DEEPSEEK_SECRET,
        }.get(settings.chat_provider, _DEFAULT_GEMINI_SECRET)
    return access_secret(secret, settings.gcp_project)


def build_chat_llm(settings: Settings, *, api_key: str | None = None) -> ChatLLM:
    """Construct the configured provider LLM (lazy vendor imports)."""
    if settings.chat_provider == "fake":
        return FakeChatLLM(script=[ChatLLMResult(text="(fake reply)")])
    key = api_key if api_key is not None else resolve_chat_api_key(settings)
    if not key:
        raise RuntimeError("chat API key empty")
    provider = settings.chat_provider
    model = settings.chat_model
    if provider == "gemini":
        from mappers.control_plane.chat_llm_gemini import GeminiChatLLM

        return GeminiChatLLM(api_key=key, model=model)
    if provider in {"openai", "deepseek"}:
        from mappers.control_plane.chat_llm_openai import OpenAIChatLLM

        base = (
            "https://api.deepseek.com/v1"
            if provider == "deepseek"
            else "https://api.openai.com/v1"
        )
        return OpenAIChatLLM(api_key=key, model=model, provider=provider, base_url=base)
    raise RuntimeError(f"unsupported chat provider: {provider}")
