"""Gemini ChatLLM adapter (google.genai)."""

from __future__ import annotations

from typing import Any, cast

from mappers.control_plane.chat_llm import ChatLLMResult, ToolCall


class GeminiChatLLM:
    """Gemini function-calling turn via google.genai."""

    def __init__(self, *, api_key: str, model: str) -> None:
        from google import genai

        self.provider = "gemini"
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ChatLLMResult:
        contents: list[Any] = [
            _gemini_content(m) for m in messages if m.get("role") != "system"
        ]
        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=cast(Any, _gemini_request_config(messages, tools)),
        )
        return _parse_gemini(response)


def _gemini_request_config(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build generate_content config; AFC off because the router runs tools."""
    config: dict[str, Any] = {"automatic_function_calling": {"disable": True}}
    system_text = "\n\n".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "system"
    ).strip()
    if system_text:
        config["system_instruction"] = system_text
    decls = [_gemini_tool(t) for t in tools]
    if decls:
        config["tools"] = [{"function_declarations": decls}]
    return config


def _gemini_content(message: dict[str, Any]) -> Any:
    role = message.get("role", "user")
    if role == "assistant":
        # Replay the SDK's own Content: rebuilt function calls lose thought_signature.
        if message.get("provider_content") is not None:
            return message["provider_content"]
        role = "model"
    if role == "tool":
        return {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "name": message.get("name", ""),
                        "response": {"result": message.get("content", "")},
                    }
                }
            ],
        }
    return {"role": role, "parts": [{"text": str(message.get("content", ""))}]}


def _gemini_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
    }


def _parse_gemini(response: Any) -> ChatLLMResult:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    raw_content: Any = None
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if content is not None and raw_content is None:
            raw_content = content
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            fn = getattr(part, "function_call", None)
            if fn is not None:
                args = dict(getattr(fn, "args", None) or {})
                calls.append(ToolCall(name=str(fn.name), args=args))
    usage = getattr(response, "usage_metadata", None)
    return ChatLLMResult(
        text="".join(text_parts).strip(),
        tool_calls=calls,
        input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        finish_reason="tool_calls" if calls else "stop",
        raw_content=raw_content,
    )
