"""Mistral provider client adapter for V2 model calls.

Provides a MistralLarge-compatible chat completion adapter that
follows the same call pattern as the Azure OpenAI adapter but
targets the Mistral API endpoint.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any


class MistralProviderClient:
    provider = "mistral"

    def chat_completion(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        response_format: dict | None = None,
        max_tokens: int = 20000,
        temperature: float = 0.2,
        timeout: int = 30,
    ) -> dict[str, Any]:
        url = f"{endpoint.rstrip('/')}/chat/completions"
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data

    @staticmethod
    def extract_content(response: dict[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("missing choices in Mistral response")
        first = choices[0]
        if not isinstance(first, dict):
            raise RuntimeError("malformed choice in Mistral response")
        message = first.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("missing message in Mistral response")
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("missing content in Mistral response message")
        if not content.strip():
            raise RuntimeError("empty content in Mistral response")
        return content

    @staticmethod
    def extract_usage(response: dict[str, Any]) -> dict[str, int]:
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    @staticmethod
    def build_json_mode_system_instruction() -> str:
        return "Output only valid JSON. No markdown. No code fences. No commentary."
