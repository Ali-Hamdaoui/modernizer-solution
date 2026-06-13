from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary, redact_public_value


@dataclass(frozen=True)
class V2AssistantModelResult:
    content: str
    source: str
    model_status: str
    provider: str
    role: str
    success: bool
    redacted_summary: str


class V2AssistantModelClient:
    provider = "azure_openai"
    role = "assistant"

    def answer(self, *, prompt: str, fallback: str) -> V2AssistantModelResult:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "").strip()
        if not endpoint or not api_key or not deployment:
            return _fallback_result(fallback, "fallback: deterministic; Azure OpenAI assistant is not configured.")

        try:
            content = self._chat_completion(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt)
        except Exception as exc:
            return _fallback_result(
                fallback,
                f"fallback: deterministic; Azure OpenAI assistant unavailable ({type(exc).__name__}).",
            )

        safe_content = str(redact_public_value(redact_model_summary(content))).strip()
        if not safe_content:
            return _fallback_result(fallback, "fallback: deterministic; Azure OpenAI returned an empty response.")
        return V2AssistantModelResult(
            content=safe_content,
            source="azure_openai",
            model_status="configured",
            provider=self.provider,
            role=self.role,
            success=True,
            redacted_summary="Azure OpenAI assistant invocation succeeded.",
        )

    def _chat_completion(self, *, endpoint: str, api_key: str, deployment: str, prompt: str) -> str:
        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21"
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only migration cockpit assistant. Explain status from supplied evidence. "
                        "Never approve, execute, write files, change route/stage, choose deployments, or override proof."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise RuntimeError("missing choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise RuntimeError("missing assistant content")
        return content


def _fallback_result(fallback: str, summary: str) -> V2AssistantModelResult:
    return V2AssistantModelResult(
        content=f"{fallback}\n\nModel: fallback\nSource: deterministic",
        source="deterministic",
        model_status="fallback",
        provider="deterministic",
        role="assistant",
        success=False,
        redacted_summary=str(redact_model_summary(summary)),
    )
