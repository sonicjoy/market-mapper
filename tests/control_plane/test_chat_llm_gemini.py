"""Gemini request config: AFC stays off so the router owns tool calls."""

from __future__ import annotations

from mappers.control_plane.chat_llm_gemini import _gemini_request_config


def test_gemini_request_config_disables_afc() -> None:
    config = _gemini_request_config(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}],
        [{"name": "lookup_leagues", "description": "Find leagues", "parameters": {}}],
    )
    assert config["automatic_function_calling"] == {"disable": True}
    assert config["system_instruction"] == "Be brief."
    assert config["tools"][0]["function_declarations"][0]["name"] == "lookup_leagues"
