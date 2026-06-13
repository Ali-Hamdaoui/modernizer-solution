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
    failure_reason: str


class V2AssistantModelClient:
    provider = "azure_openai"
    role = "assistant"

    def answer(self, *, prompt: str, fallback: str) -> V2AssistantModelResult:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "").strip()
        if not endpoint:
            return _fallback_result(fallback, "Azure OpenAI endpoint not configured.", "missing_endpoint")
        if not api_key:
            return _fallback_result(fallback, "Azure OpenAI API key not configured.", "missing_key")
        if not deployment:
            return _fallback_result(fallback, "Azure OpenAI deployment name not configured.", "missing_deployment")

        try:
            content = self._chat_completion(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt)
        except urllib.error.HTTPError as exc:
            code = getattr(exc, "code", 0)
            if code == 401:
                return _fallback_result(fallback, "Azure OpenAI authentication failed (HTTP 401).", "http_401")
            if code == 404:
                return _fallback_result(fallback, "Azure OpenAI deployment or endpoint not found (HTTP 404).", "http_404")
            return _fallback_result(
                fallback,
                f"Azure OpenAI request failed (HTTP {code}).",
                f"http_{code}",
            )
        except urllib.error.URLError as exc:
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            if "time" in reason.lower() or "timed" in reason.lower():
                return _fallback_result(fallback, "Azure OpenAI request timed out.", "timeout")
            return _fallback_result(fallback, f"Azure OpenAI request failed: {reason}.", "invalid_response")
        except Exception as exc:
            return _fallback_result(
                fallback,
                f"Azure OpenAI assistant unavailable ({type(exc).__name__}).",
                "invalid_response",
            )

        safe_content = str(redact_public_value(redact_model_summary(content))).strip()
        if not safe_content:
            return _fallback_result(fallback, "Azure OpenAI returned an empty response.", "invalid_response")
        return V2AssistantModelResult(
            content=safe_content,
            source="azure_openai",
            model_status="live_ok",
            provider=self.provider,
            role=self.role,
            success=True,
            redacted_summary="Azure OpenAI assistant invocation succeeded.",
            failure_reason="",
        )

    @staticmethod
    def _is_v1_endpoint(endpoint: str) -> bool:
        return endpoint.endswith("/openai/v1")

    def _chat_completion(self, *, endpoint: str, api_key: str, deployment: str, prompt: str) -> str:
        if self._is_v1_endpoint(endpoint):
            return self._chat_completion_v1(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt)
        return self._chat_completion_legacy(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt)

    def _chat_completion_v1(self, *, endpoint: str, api_key: str, deployment: str, prompt: str) -> str:
        url = f"{endpoint}/chat/completions"
        payload = {
            "model": deployment,
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
        headers = {"Content-Type": "application/json"}
        if self._prefer_bearer_header(api_key):
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers["api-key"] = api_key
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
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

    def _chat_completion_legacy(self, *, endpoint: str, api_key: str, deployment: str, prompt: str) -> str:
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

    @staticmethod
    def _prefer_bearer_header(api_key: str) -> bool:
        return bool(api_key) and not api_key.startswith("sk-")


def _fallback_result(fallback: str, summary: str, failure_reason: str = "") -> V2AssistantModelResult:
    return V2AssistantModelResult(
        content=f"{fallback}\n\nModel: fallback\nSource: deterministic\nReason: {summary}",
        source="deterministic",
        model_status="fallback",
        provider="deterministic",
        role="assistant",
        success=False,
        redacted_summary=str(redact_model_summary(summary)),
        failure_reason=failure_reason,
    )
