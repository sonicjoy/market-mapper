"""OpenAI-compatible ChatLLM (OpenAI + DeepSeek) via requests."""

from __future__ import annotations

import json
from typing import Any

import requests

from mappers.control_plane.chat_llm import ChatLLMResult, ToolCall


class OpenAIChatLLM:
    """Chat Completions + tools against an OpenAI-compatible base URL."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        provider: str = "openai",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.provider = provider
        self.model = model
        self._api_key = api_key
        self._base = base_url.rstrip("/")

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatLLMResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_openai_message(m) for m in messages],
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters") or {"type": "object", "properties": {}},
                }}
                for t in tools
            ]
        response = requests.post(
            f"{self._base}/chat/completions",
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            data=json.dumps(body),
            timeout=30,
        )
        response.raise_for_status()
        return _parse_openai(response.json())


def _openai_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role", "user")
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.get("tool_call_id") or message.get("name", ""),
            "content": str(message.get("content", "")),
        }
    calls = message.get("tool_calls") or [] if role == "assistant" else []
    if calls:
        return {
            "role": "assistant",
            "content": str(message.get("content") or ""),
            "tool_calls": [
                {
                    "id": str(c.get("id") or c.get("name", "")),
                    "type": "function",
                    "function": {
                        "name": str(c.get("name", "")),
                        "arguments": json.dumps(c.get("args") or {}),
                    },
                }
                for c in calls
            ],
        }
    return {"role": role, "content": str(message.get("content", ""))}


def _parse_openai(payload: dict[str, Any]) -> ChatLLMResult:
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    calls: list[ToolCall] = []
    for raw in msg.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {}
        calls.append(
            ToolCall(
                name=str(fn.get("name") or ""),
                args=args if isinstance(args, dict) else {},
                call_id=str(raw.get("id") or ""),
            )
        )
    usage = payload.get("usage") or {}
    return ChatLLMResult(
        text=str(msg.get("content") or "").strip(),
        tool_calls=calls,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        finish_reason="tool_calls" if calls else "stop",
    )
