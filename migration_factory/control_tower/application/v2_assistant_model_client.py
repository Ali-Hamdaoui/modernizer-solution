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


@dataclass(frozen=True)
class V2ModelSmokeResult:
    success: bool
    deployment: str
    provider: str
    failure_reason: str
    redacted_summary: str
    response_snippet: str
    latency_ms: float


class V2AssistantModelClient:
    provider = "azure_openai"
    role = "assistant"

    def smoke(self) -> V2ModelSmokeResult:
        """Perform a real model smoke call to verify the Azure/OpenAI endpoint.

        Sends a tiny prompt (``Reply with OK.``) with low token limit and
        short timeout.  Captures sanitised failure reasons without exposing
        secrets.
        """
        import time as _time
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "").strip()

        if not endpoint:
            return V2ModelSmokeResult(
                success=False, deployment="", provider=self.provider,
                failure_reason="missing_endpoint",
                redacted_summary="Azure OpenAI endpoint not configured.",
                response_snippet="", latency_ms=0,
            )
        if not api_key:
            return V2ModelSmokeResult(
                success=False, deployment=deployment, provider=self.provider,
                failure_reason="missing_key",
                redacted_summary="Azure OpenAI API key not configured.",
                response_snippet="", latency_ms=0,
            )
        if not deployment:
            return V2ModelSmokeResult(
                success=False, deployment="", provider=self.provider,
                failure_reason="missing_deployment",
                redacted_summary="Azure OpenAI deployment name not configured.",
                response_snippet="", latency_ms=0,
            )

        t0 = _time.monotonic()
        try:
            self._chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                deployment=deployment,
                prompt="Reply with OK.",
                max_tokens=10,
                timeout=15,
            )
        except urllib.error.HTTPError as exc:
            code = getattr(exc, "code", 0)
            snippet = _sanitize_body_snippet(exc)
            latency = (_time.monotonic() - t0) * 1000
            reason_map = {401: "http_401", 404: "http_404", 400: "http_400"}
            reason = reason_map.get(code, f"http_{code}" if code else "invalid_response")
            return V2ModelSmokeResult(
                success=False, deployment=deployment, provider=self.provider,
                failure_reason=reason,
                redacted_summary=f"Azure OpenAI smoke failed (HTTP {code}).",
                response_snippet=str(redact_model_summary(snippet)),
                latency_ms=round(latency, 1),
            )
        except urllib.error.URLError as exc:
            latency = (_time.monotonic() - t0) * 1000
            reason_str = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            is_timeout = "time" in reason_str.lower() or "timed" in reason_str.lower()
            return V2ModelSmokeResult(
                success=False, deployment=deployment, provider=self.provider,
                failure_reason="timeout" if is_timeout else "invalid_response",
                redacted_summary="Azure OpenAI smoke timed out." if is_timeout else f"Azure OpenAI smoke failed: {redact_model_summary(reason_str)}.",
                response_snippet="", latency_ms=round(latency, 1),
            )
        except Exception as exc:
            latency = (_time.monotonic() - t0) * 1000
            return V2ModelSmokeResult(
                success=False, deployment=deployment, provider=self.provider,
                failure_reason="invalid_response",
                redacted_summary=redact_model_summary(f"Azure OpenAI smoke failed ({type(exc).__name__})."),
                response_snippet="", latency_ms=round(latency, 1),
            )

        latency = (_time.monotonic() - t0) * 1000
        return V2ModelSmokeResult(
            success=True, deployment=deployment, provider=self.provider,
            failure_reason="",
            redacted_summary="Azure OpenAI smoke succeeded.",
            response_snippet="", latency_ms=round(latency, 1),
        )

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
            content = self._chat_completion(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt, max_tokens=700, timeout=30)
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

    def _chat_completion(self, *, endpoint: str, api_key: str, deployment: str, prompt: str, max_tokens: int = 700, timeout: int = 30) -> str:
        if self._is_v1_endpoint(endpoint):
            return self._chat_completion_v1(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt, max_tokens=max_tokens, timeout=timeout)
        return self._chat_completion_legacy(endpoint=endpoint, api_key=api_key, deployment=deployment, prompt=prompt, max_tokens=max_tokens, timeout=timeout)

    def _chat_completion_v1(self, *, endpoint: str, api_key: str, deployment: str, prompt: str, max_tokens: int = 700, timeout: int = 30) -> str:
        url = f"{endpoint}/chat/completions"
        payload = {
            "model": deployment,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only AI Migration Factory coach. Your role is to help the operator understand "
                        "migration status, pipeline progress, failures, approvals, and next steps using only the evidence "
                        "supplied in the prompt.\n"
                        "RULES:\n"
                        "- Explain what happened, what failed, what artifacts were generated, and what the operator should do next.\n"
                        "- Answer questions like: 'What is happening?', 'What failed?', 'What should I approve?', "
                        "'What did the analysis find?', 'What should I do next?', 'Is AI model connected?'\n"
                        "- NEVER: approve, reject, execute commands, write files, change route or stage, "
                        "choose Maven goals, choose deployments, or override proof.\n"
                        "- All execution is backend-owned and human-gated.\n"
                        "- If the prompt shows model status 'fallback', explain that AI coaching is running in deterministic mode.\n"
                        "- Keep answers concise (3-8 sentences)."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise RuntimeError("missing choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise RuntimeError("missing assistant content")
        return content

    def _chat_completion_legacy(self, *, endpoint: str, api_key: str, deployment: str, prompt: str, max_tokens: int = 700, timeout: int = 30) -> str:
        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21"
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a read-only AI Migration Factory coach. Your role is to help the operator understand "
                        "migration status, pipeline progress, failures, approvals, and next steps using only the evidence "
                        "supplied in the prompt.\n"
                        "RULES:\n"
                        "- Explain what happened, what failed, what artifacts were generated, and what the operator should do next.\n"
                        "- Answer questions like: 'What is happening?', 'What failed?', 'What should I approve?', "
                        "'What did the analysis find?', 'What should I do next?', 'Is AI model connected?'\n"
                        "- NEVER: approve, reject, execute commands, write files, change route or stage, "
                        "choose Maven goals, choose deployments, or override proof.\n"
                        "- All execution is backend-owned and human-gated.\n"
                        "- If the prompt shows model status 'fallback', explain that AI coaching is running in deterministic mode.\n"
                        "- Keep answers concise (3-8 sentences)."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
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


def _sanitize_body_snippet(http_error: urllib.error.HTTPError) -> str:
    """Return a bounded, sanitised snippet from an HTTPError response body.

    Secrets (API keys, bearer tokens) and raw JSON are redacted.
    """
    import re as _re
    try:
        raw = http_error.read()
    except Exception:
        return ""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    text = str(raw)[:500]
    # Redact secret-like patterns
    text = _re.sub(r'(?i)(api[_-]?key|bearer\s+)[^\s"]+', r'\1[REDACTED]', text)
    text = _re.sub(r'"access_token"\s*:\s*"[^"]*"', '"access_token":"[REDACTED]"', text)
    return text


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
