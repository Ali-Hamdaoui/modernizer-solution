from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.application.redaction import (
    redact_model_summary,
    redact_public_value,
)
from migration_factory.control_tower.domain.checksums import utc_now_text


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
    checked_at: str


class V2AssistantModelClient:
    provider = "azure_openai"
    role = "assistant"

    def smoke(self) -> V2ModelSmokeResult:
        """Perform a real model smoke call against the configured Azure/OpenAI endpoint."""
        import time as _time

        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "").strip()
        checked_at = utc_now_text()

        if not endpoint:
            return V2ModelSmokeResult(
                success=False,
                deployment="",
                provider=self.provider,
                failure_reason="missing_endpoint",
                redacted_summary="Azure OpenAI endpoint not configured.",
                response_snippet="",
                latency_ms=0,
                checked_at=checked_at,
            )
        if not api_key:
            return V2ModelSmokeResult(
                success=False,
                deployment=_public_deployment_label(deployment),
                provider=self.provider,
                failure_reason="missing_key",
                redacted_summary="Azure OpenAI API key not configured.",
                response_snippet="",
                latency_ms=0,
                checked_at=checked_at,
            )
        if not deployment:
            return V2ModelSmokeResult(
                success=False,
                deployment="",
                provider=self.provider,
                failure_reason="missing_deployment",
                redacted_summary="Azure OpenAI deployment name not configured.",
                response_snippet="",
                latency_ms=0,
                checked_at=checked_at,
            )

        t0 = _time.monotonic()
        try:
            content = self._smoke_completion(
                endpoint=endpoint,
                api_key=api_key,
                deployment=deployment,
                timeout=15,
            )
        except urllib.error.HTTPError as exc:
            latency = (_time.monotonic() - t0) * 1000
            code = int(getattr(exc, "code", 0) or 0)
            snippet = _redact_smoke_text(
                _sanitize_body_snippet(exc),
                endpoint=endpoint,
                deployment=deployment,
                api_key=api_key,
            )
            return V2ModelSmokeResult(
                success=False,
                deployment=_public_deployment_label(deployment),
                provider=self.provider,
                failure_reason=_http_failure_reason(code),
                redacted_summary=_summary_with_snippet(
                    f"Azure OpenAI smoke failed (HTTP {code}).",
                    snippet,
                ),
                response_snippet=snippet,
                latency_ms=round(latency, 1),
                checked_at=checked_at,
            )
        except urllib.error.URLError as exc:
            latency = (_time.monotonic() - t0) * 1000
            reason_text = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            is_timeout = _looks_like_timeout(reason_text)
            return V2ModelSmokeResult(
                success=False,
                deployment=_public_deployment_label(deployment),
                provider=self.provider,
                failure_reason="timeout" if is_timeout else "invalid_response",
                redacted_summary=(
                    "Azure OpenAI smoke timed out."
                    if is_timeout
                    else f"Azure OpenAI smoke failed: {redact_model_summary(reason_text)}."
                ),
                response_snippet="",
                latency_ms=round(latency, 1),
                checked_at=checked_at,
            )
        except Exception as exc:
            latency = (_time.monotonic() - t0) * 1000
            return V2ModelSmokeResult(
                success=False,
                deployment=_public_deployment_label(deployment),
                provider=self.provider,
                failure_reason="invalid_response",
                redacted_summary=redact_model_summary(
                    f"Azure OpenAI smoke failed ({type(exc).__name__})."
                ),
                response_snippet="",
                latency_ms=round(latency, 1),
                checked_at=checked_at,
            )

        latency = (_time.monotonic() - t0) * 1000
        if str(content).strip() != "OK":
            snippet = _redact_smoke_text(
                str(content),
                endpoint=endpoint,
                deployment=deployment,
                api_key=api_key,
            )
            return V2ModelSmokeResult(
                success=False,
                deployment=_public_deployment_label(deployment),
                provider=self.provider,
                failure_reason="invalid_response",
                redacted_summary="Azure OpenAI smoke returned unexpected content.",
                response_snippet=snippet,
                latency_ms=round(latency, 1),
                checked_at=checked_at,
            )

        return V2ModelSmokeResult(
            success=True,
            deployment=_public_deployment_label(deployment),
            provider=self.provider,
            failure_reason="",
            redacted_summary="Azure OpenAI smoke succeeded.",
            response_snippet="",
            latency_ms=round(latency, 1),
            checked_at=checked_at,
        )

    def answer(self, *, prompt: str, fallback: str) -> V2AssistantModelResult:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "").strip()

        if not endpoint:
            return _fallback_result(
                fallback,
                "Azure OpenAI endpoint not configured.",
                "missing_endpoint",
            )
        if not api_key:
            return _fallback_result(
                fallback,
                "Azure OpenAI API key not configured.",
                "missing_key",
            )
        if not deployment:
            return _fallback_result(
                fallback,
                "Azure OpenAI deployment name not configured.",
                "missing_deployment",
            )

        try:
            content = self._chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                deployment=deployment,
                prompt=prompt,
                max_completion_tokens=700,
                timeout=30,
            )
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            snippet = _redact_smoke_text(
                _sanitize_body_snippet(exc),
                endpoint=endpoint,
                deployment=deployment,
                api_key=api_key,
            )
            summary = _summary_with_snippet(
                _http_error_summary(code),
                snippet,
            )
            return _fallback_result(
                fallback,
                summary,
                _http_failure_reason(code),
            )
        except urllib.error.URLError as exc:
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            if _looks_like_timeout(reason):
                return _fallback_result(
                    fallback,
                    "Azure OpenAI request timed out.",
                    "timeout",
                )
            return _fallback_result(
                fallback,
                f"Azure OpenAI request failed: {redact_model_summary(reason)}.",
                "invalid_response",
            )
        except Exception as exc:
            return _fallback_result(
                fallback,
                f"Azure OpenAI assistant unavailable ({type(exc).__name__}).",
                "invalid_response",
            )

        safe_content = str(redact_public_value(redact_model_summary(content))).strip()
        if not safe_content:
            return _fallback_result(
                fallback,
                "Azure OpenAI returned an empty response.",
                "invalid_response",
            )

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
        endpoint = endpoint.rstrip("/").lower()
        return endpoint.endswith("/openai/v1") or endpoint.endswith(".openai.azure.com")

    @staticmethod
    def _normalize_v1_endpoint(endpoint: str) -> str:
        endpoint = endpoint.rstrip("/")
        if endpoint.lower().endswith("/openai/v1"):
            return endpoint
        return f"{endpoint}/openai/v1"

    def _chat_completion(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt: str,
        max_completion_tokens: int = 700,
        timeout: int = 30,
    ) -> str:
        if self._is_v1_endpoint(endpoint):
            normalized_endpoint = self._normalize_v1_endpoint(endpoint)
            try:
                return self._chat_completion_v1(
                    endpoint=normalized_endpoint,
                    api_key=api_key,
                    deployment=deployment,
                    prompt=prompt,
                    max_completion_tokens=max_completion_tokens,
                    timeout=timeout,
                )
            except urllib.error.HTTPError as exc:
                if not _should_retry_legacy_azure_route(exc, endpoint):
                    raise
                return self._chat_completion_legacy(
                    endpoint=_legacy_endpoint_from_v1ish(endpoint),
                    api_key=api_key,
                    deployment=deployment,
                    prompt=prompt,
                    max_tokens=max_completion_tokens,
                    timeout=timeout,
                )
        return self._chat_completion_legacy(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            prompt=prompt,
            max_tokens=max_completion_tokens,
            timeout=timeout,
        )

    def _chat_completion_v1(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt: str,
        max_completion_tokens: int = 700,
        timeout: int = 30,
    ) -> str:
        return self._post_chat_completion_v1(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            messages=[
                {"role": "system", "content": _assistant_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_completion_tokens=max_completion_tokens,
            timeout=timeout,
        )

    def _smoke_completion(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        timeout: int = 15,
    ) -> str:
        if self._is_v1_endpoint(endpoint):
            normalized_endpoint = self._normalize_v1_endpoint(endpoint)
            try:
                return self._post_chat_completion_v1(
                    endpoint=normalized_endpoint,
                    api_key=api_key,
                    deployment=deployment,
                    messages=[{"role": "user", "content": "Reply with OK."}],
                    max_completion_tokens=100,
                    timeout=timeout,
                )
            except urllib.error.HTTPError as exc:
                if not _should_retry_legacy_azure_route(exc, endpoint):
                    raise
                return self._post_chat_completion_legacy(
                    endpoint=_legacy_endpoint_from_v1ish(endpoint),
                    api_key=api_key,
                    deployment=deployment,
                    messages=[{"role": "user", "content": "Reply with OK."}],
                    max_tokens=100,
                    timeout=timeout,
                )
        return self._post_chat_completion_legacy(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=100,
            timeout=timeout,
        )

    def _post_chat_completion_v1(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        messages: list[dict[str, str]],
        max_completion_tokens: int,
        timeout: int,
    ) -> str:
        url = f"{endpoint.rstrip('/')}/chat/completions"
        payload = {
            "model": deployment,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "reasoning_effort": os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "minimal").strip() or "minimal",
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return _extract_assistant_content(data)

    def _chat_completion_legacy(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt: str,
        max_tokens: int = 700,
        timeout: int = 30,
    ) -> str:
        return self._post_chat_completion_legacy(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            messages=[
                {"role": "system", "content": _assistant_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def _post_chat_completion_legacy(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout: int,
    ) -> str:
        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/"
            f"{deployment}/chat/completions?api-version=2024-10-21"
        )
        payload = {
            "messages": messages,
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
        return _extract_assistant_content(data)


def _assistant_system_prompt() -> str:
    return (
        "You are a read-only AI Migration Factory coach. Your role is to help the operator understand "
        "migration status, pipeline progress, failures, approvals, and next steps using only the evidence "
        "supplied in the prompt.\n"
        "RULES:\n"
        "- Explain what happened, what failed, what artifacts were generated, and what the operator should do next.\n"
        "- Answer questions like: 'What is happening?', 'What failed?', 'What should I approve?', "
        "'What did the analysis find?', 'What should I do next?', 'Is AI model connected?'\n"
        "- NEVER: approve, reject, execute commands, write files, change route or stage, choose Maven goals, "
        "choose deployments, or override proof.\n"
        "- All execution is backend-owned and human-gated.\n"
        "- If the prompt shows model status 'fallback', explain that AI coaching is running in deterministic mode.\n"
        "- Keep answers concise: 3-8 sentences."
    )


def _extract_assistant_content(data: Any) -> str:
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError("missing choices")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise RuntimeError("missing assistant content")
    return content


def _sanitize_body_snippet(http_error: urllib.error.HTTPError) -> str:
    try:
        raw = http_error.read()
    except Exception:
        return ""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    text = str(raw)[:500]
    text = re.sub(r'(?i)(api[_-]?key|bearer\s+)[^\s",}]+', r"\1[REDACTED]", text)
    text = re.sub(r'(?i)("api[_-]?key"\s*:\s*")[^"]*"', r'\1[REDACTED]"', text)
    text = re.sub(r'(?i)("access_token"\s*:\s*")[^"]*"', r'\1[REDACTED]"', text)
    text = re.sub(r'(?i)("authorization"\s*:\s*")[^"]*"', r'\1[REDACTED]"', text)
    return redact_model_summary(text)


def _redact_smoke_text(text: str, *, endpoint: str, deployment: str, api_key: str) -> str:
    result = redact_model_summary(str(text or ""))
    for secret in (api_key, deployment, endpoint):
        if secret:
            result = result.replace(secret, "[redacted]")
    return result[:500]


def _fallback_result(fallback: str, summary: str, failure_reason: str = "") -> V2AssistantModelResult:
    safe_summary = str(redact_model_summary(summary))
    return V2AssistantModelResult(
        content=f"{fallback}\n\nModel: fallback\nSource: deterministic\nReason: {safe_summary}",
        source="deterministic",
        model_status="fallback",
        provider="deterministic",
        role="assistant",
        success=False,
        redacted_summary=safe_summary,
        failure_reason=failure_reason,
    )


def _looks_like_timeout(value: str) -> bool:
    lowered = str(value).lower()
    return "timeout" in lowered or "timed out" in lowered or "time out" in lowered


def _legacy_endpoint_from_v1ish(endpoint: str) -> str:
    cleaned = endpoint.rstrip("/")
    if cleaned.lower().endswith("/openai/v1"):
        return cleaned[:-len("/openai/v1")]
    return cleaned


def _should_retry_legacy_azure_route(exc: urllib.error.HTTPError, endpoint: str) -> bool:
    cleaned = endpoint.rstrip("/").lower()
    if ".openai.azure.com" not in cleaned:
        return False
    if int(getattr(exc, "code", 0) or 0) not in {400, 404}:
        return False
    snippet = _sanitize_body_snippet(exc).lower()
    return (
        "<html" in snippet
        or "<!doctype html" in snippet
        or "bad request" in snippet
        or "deploymentnotfound" in snippet
    )


def _http_failure_reason(code: int) -> str:
    if code == 400:
        return "http_400"
    if code == 401:
        return "http_401"
    if code == 404:
        return "http_404"
    return f"http_{code}" if code else "invalid_response"


def _http_error_summary(code: int) -> str:
    if code == 400:
        return "Azure OpenAI request failed (HTTP 400)."
    if code == 401:
        return "Azure OpenAI authentication failed (HTTP 401)."
    if code == 404:
        return "Azure OpenAI deployment or endpoint not found (HTTP 404)."
    return f"Azure OpenAI request failed (HTTP {code})."


def _summary_with_snippet(summary: str, snippet: str) -> str:
    safe_snippet = str(redact_model_summary(snippet or "")).strip()
    if not safe_snippet:
        return summary
    return f"{summary} Detail: {safe_snippet}"


def _public_deployment_label(deployment: str) -> str:
    return "configured" if str(deployment or "").strip() else ""
