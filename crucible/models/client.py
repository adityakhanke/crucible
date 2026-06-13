"""Thin LLM client for OpenAI-compatible endpoints.

All inference servers (llama.cpp, vLLM, SGLang) expose the same
/v1/chat/completions endpoint. This client talks to whichever is active.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """Stateless client — just needs a base_url to talk to."""

    def __init__(self, base_url: str, model: str = "local"):
        self._client = OpenAI(base_url=base_url, api_key="not-needed")
        self._model = model

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """Send a chat completion request. Returns the raw text response."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = self._client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        return content

    def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> dict | list:
        """Chat expecting JSON output. Attempts to parse; retries on failure."""
        raw = self.chat(system, user, temperature, max_tokens, json_mode=True)
        return _extract_json(raw)


def _extract_json(text: str) -> dict | list:
    """Best-effort JSON extraction from LLM output."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { or [
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        end = text.rfind(end_char)
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not extract JSON from LLM output:\n{text[:500]}")
