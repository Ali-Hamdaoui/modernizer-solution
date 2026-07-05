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
from migration_factory.control_tower.application.v2_mistral_provider_client import (
    MistralProviderClient,
)
from migration_factory.control_tower.application.v2_model_role_config import (
    ModelRoleConfigLoader,
)
from migration_factory.control_tower.application.v2_model_role_router import (
    V2ModelRole,
    V2ModelRoleRouter,
    V2RoleModelRequest,
    V2RoleModelResult,
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
    schema_diagnostics: dict[str, Any] | None = None
    response_format_requested: bool = False
    response_format_used: bool | None = None
    deployment_alias_hash: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    latency_ms: int | None = None


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

    def answer(
        self,
        *,
        prompt: str,
        fallback: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> V2AssistantModelResult:
        return self.answer_with_role(
            role=V2ModelRole.ASSISTANT,
            prompt=prompt,
            fallback=fallback,
            conversation_history=conversation_history,
        )

    def answer_with_role(
        self,
        *,
        role: V2ModelRole,
        prompt: str,
        fallback: str,
        conversation_history: list[dict[str, str]] | None = None,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> V2AssistantModelResult:
        router = V2ModelRoleRouter()
        request = V2RoleModelRequest(
            role=role,
            prompt=prompt,
            fallback=fallback,
            output_schema_name=output_schema_name,
            require_schema=require_schema,
            conversation_history=tuple(conversation_history or ()),
        )
        routed = router.route(
            request,
            invoke=lambda deployment, provider="azure_openai", prompt_override=None: self._answer_with_deployment(
                role=role,
                deployment=deployment,
                prompt=prompt_override if prompt_override is not None else prompt,
                fallback=fallback,
                conversation_history=conversation_history,
                output_schema_name=output_schema_name,
                require_schema=require_schema,
            ),
        )
        return self._to_assistant_result(routed)

    def _answer_with_deployment(
        self,
        *,
        role: V2ModelRole,
        deployment: str,
        prompt: str,
        fallback: str,
        conversation_history: list[dict[str, str]] | None = None,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> V2AssistantModelResult:
        role_config = _model_role_config(role)
        provider_alias = (role_config.provider_alias if role_config else "azure_openai")

        if provider_alias == "mistral":
            return self._answer_with_mistral(
                role=role,
                deployment=deployment,
                prompt=prompt,
                fallback=fallback,
                role_config=role_config,
                conversation_history=conversation_history,
                output_schema_name=output_schema_name,
                require_schema=require_schema,
            )

        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()

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
                f"Azure OpenAI deployment name not configured for role {role.value}.",
                "missing_deployment",
            )

        import time as _time
        t0 = _time.monotonic()
        try:
            content, usage_data = self._chat_completion(
                endpoint=endpoint,
                api_key=api_key,
                deployment=deployment,
                prompt=prompt,
                role=role,
                max_completion_tokens=role_config.max_output_tokens if role_config else None,
                timeout=role_config.timeout_seconds if role_config else 30,
                conversation_history=conversation_history,
                output_schema_name=output_schema_name,
                require_schema=require_schema,
            )
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            snippet = _redact_smoke_text(
                _sanitize_body_snippet(exc),
                endpoint=endpoint,
                deployment=deployment,
                api_key=api_key,
            )
            # Detect response_format rejection
            if require_schema and code == 400 and ("response_format" in snippet.lower() or "json_object" in snippet.lower() or "json mode" in snippet.lower()):
                summary = "Azure rejected response_format=json_object. The deployment does not support structured output."
            else:
                summary = _summary_with_snippet(
                    _http_error_summary(code),
                    snippet,
                )
            return _fallback_result(
                fallback,
                summary,
                "azure_response_format_rejected" if (require_schema and code == 400 and ("response_format" in snippet.lower() or "json_object" in snippet.lower())) else _http_failure_reason(code),
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

        latency_ms = int((_time.monotonic() - t0) * 1000)
        safe_content = str(redact_public_value(redact_model_summary(content))).strip()
        if not safe_content:
            _log_empty_azure_result_summary(endpoint=endpoint, deployment=deployment)
            return _fallback_result(
                fallback,
                "Azure OpenAI returned an empty response.",
                "empty_response",
            )

        return V2AssistantModelResult(
            content=safe_content,
            source="azure_openai",
            model_status="live_ok",
            provider=self.provider,
            role=role.value,
            success=True,
            redacted_summary="Azure OpenAI assistant invocation succeeded.",
            failure_reason="",
            response_format_requested=bool(require_schema),
            response_format_used=bool(require_schema and (role_config.supports_json_object if role_config else True)),
            prompt_tokens=usage_data.get("prompt_tokens"),
            completion_tokens=usage_data.get("completion_tokens"),
            total_tokens=usage_data.get("total_tokens"),
            reasoning_tokens=usage_data.get("reasoning_tokens"),
            latency_ms=latency_ms,
        )

    def _answer_with_mistral(
        self,
        *,
        role: V2ModelRole,
        deployment: str,
        prompt: str,
        fallback: str,
        role_config: Any = None,
        conversation_history: list[dict[str, str]] | None = None,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> V2AssistantModelResult:
        _mistral_endpoint = os.environ.get("MISTRAL_ENDPOINT", "").strip().rstrip("/")
        _mistral_api_key = os.environ.get("MISTRAL_API_KEY", "").strip()

        if not _mistral_endpoint:
            return _fallback_result(
                fallback,
                "Mistral endpoint not configured.",
                "missing_endpoint",
            )
        if not _mistral_api_key:
            return _fallback_result(
                fallback,
                "Mistral API key not configured.",
                "missing_key",
            )
        if not deployment:
            return _fallback_result(
                fallback,
                f"Mistral model not configured for role {role.value}.",
                "missing_model",
            )

        messages = V2AssistantModelClient._build_messages(
            prompt=prompt,
            conversation_history=conversation_history,
        )

        response_format: dict | None = None
        if require_schema:
            response_format = {"type": "json_object"}
            # Inject JSON-only instruction into the system message
            if messages and messages[0].get("role") == "system":
                existing = str(messages[0].get("content", ""))
                json_instr = MistralProviderClient.build_json_mode_system_instruction()
                if json_instr not in existing:
                    messages[0]["content"] = f"{json_instr}\n\n{existing}"

        max_tokens = _role_max_output_tokens(role)
        temperature = float(role_config.temperature if role_config and hasattr(role_config, "temperature") else 0.2)

        client = MistralProviderClient()
        try:
            response = client.chat_completion(
                endpoint=_mistral_endpoint,
                api_key=_mistral_api_key,
                model=deployment,
                messages=messages,
                response_format=response_format,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=role_config.timeout_seconds if role_config else 30,
            )
            content = client.extract_content(response)
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            snippet = _sanitize_body_snippet(exc)
            return _fallback_result(
                fallback,
                f"Mistral API request failed (HTTP {code}). Detail: {snippet}" if snippet else f"Mistral API request failed (HTTP {code}).",
                f"http_{code}" if code else "invalid_response",
            )
        except urllib.error.URLError as exc:
            reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
            if _looks_like_timeout(reason):
                return _fallback_result(
                    fallback,
                    "Mistral request timed out.",
                    "timeout",
                )
            return _fallback_result(
                fallback,
                f"Mistral request failed: {redact_model_summary(reason)}.",
                "invalid_response",
            )
        except Exception as exc:
            return _fallback_result(
                fallback,
                f"Mistral assistant unavailable ({type(exc).__name__}).",
                "invalid_response",
            )

        safe_content = str(redact_public_value(redact_model_summary(content))).strip()
        if not safe_content:
            return _fallback_result(
                fallback,
                "Mistral returned an empty response.",
                "empty_response",
            )

        return V2AssistantModelResult(
            content=safe_content,
            source="mistral",
            model_status="live_ok",
            provider=client.provider,
            role=role.value,
            success=True,
            redacted_summary="Mistral invocation succeeded.",
            failure_reason="",
            response_format_requested=require_schema,
            response_format_used=bool(response_format),
        )

    def _to_assistant_result(self, routed: V2RoleModelResult) -> V2AssistantModelResult:
        redacted_summary = str(routed.redacted_summary or "").strip()
        if not redacted_summary:
            redacted_summary = str(redact_model_summary(routed.content)).strip()
        return V2AssistantModelResult(
            content=routed.content,
            source=routed.source,
            model_status=routed.model_status,
            provider=routed.provider,
            role=routed.role,
            success=routed.success,
            redacted_summary=redacted_summary,
            failure_reason=routed.failure_reason,
            schema_diagnostics=routed.schema_diagnostics,
            response_format_requested=routed.response_format_requested,
            response_format_used=routed.response_format_used,
            deployment_alias_hash=routed.deployment_alias_hash,
            prompt_tokens=routed.prompt_tokens,
            completion_tokens=routed.completion_tokens,
            total_tokens=routed.total_tokens,
            reasoning_tokens=routed.reasoning_tokens,
            latency_ms=routed.latency_ms,
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
        role: V2ModelRole = V2ModelRole.ASSISTANT,
        max_completion_tokens: int | None = None,
        timeout: int = 30,
        conversation_history: list[dict[str, str]] | None = None,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> tuple[str, dict[str, int | None]]:
        if max_completion_tokens is None:
            max_completion_tokens = _role_max_output_tokens(role)
        # When require_schema is True, the Responses API does not support
        # response_format=json_object. Go directly to chat/completions which does.
        if require_schema or not self._is_v1_endpoint(endpoint):
            target = endpoint if not self._is_v1_endpoint(endpoint) else self._normalize_v1_endpoint(endpoint)
            try:
                content, usage = self._chat_completion_v1(
                    endpoint=target,
                    api_key=api_key,
                    deployment=deployment,
                    prompt=prompt,
                    role=role,
                    max_completion_tokens=max_completion_tokens,
                    timeout=timeout,
                    conversation_history=conversation_history,
                    output_schema_name=output_schema_name,
                    require_schema=require_schema,
                )
                return content, usage
            except urllib.error.HTTPError as exc:
                snippet = _sanitize_body_snippet(exc).lower()
                code = int(getattr(exc, "code", 0) or 0)
                # Azure rejects json_object mode — do NOT silently retry
                if require_schema and code == 400 and ("response_format" in snippet or "json_object" in snippet or "json mode" in snippet):
                    raise
                if _should_retry_with_legacy_endpoint(exc):
                    content = self._chat_completion_legacy(
                        endpoint=_legacy_endpoint_from_v1(target),
                        api_key=api_key,
                        deployment=deployment,
                        prompt=prompt,
                        max_tokens=max_completion_tokens,
                        timeout=timeout,
                        conversation_history=conversation_history,
                        output_schema_name=output_schema_name,
                        require_schema=require_schema,
                    )
                    return content, {}
                raise

        # require_schema=False, non-chat endpoint path
        # Try Responses API first, fall back to chat/completions
        # Note: Responses API does not support response_format
        endpoint = self._normalize_v1_endpoint(endpoint)
        try:
            content = self._responses_completion_v1(
                endpoint=endpoint,
                api_key=api_key,
                deployment=deployment,
                prompt=prompt,
                role=role,
                max_completion_tokens=max_completion_tokens,
                timeout=timeout,
                conversation_history=conversation_history,
            )
            return content, {}
        except urllib.error.HTTPError as exc:
            if _should_retry_with_chat_completions(exc):
                try:
                    content, usage = self._chat_completion_v1(
                        endpoint=endpoint,
                        api_key=api_key,
                        deployment=deployment,
                        prompt=prompt,
                        role=role,
                        max_completion_tokens=max_completion_tokens,
                        timeout=timeout,
                        conversation_history=conversation_history,
                        output_schema_name=output_schema_name,
                        require_schema=require_schema,
                    )
                    return content, usage
                except urllib.error.HTTPError as chat_exc:
                    snippet = _sanitize_body_snippet(chat_exc).lower()
                    code = int(getattr(chat_exc, "code", 0) or 0)
                    if require_schema and code == 400 and ("response_format" in snippet or "json_object" in snippet or "json mode" in snippet):
                        raise
                    if _should_retry_with_legacy_endpoint(chat_exc):
                        content = self._chat_completion_legacy(
                            endpoint=_legacy_endpoint_from_v1(endpoint),
                            api_key=api_key,
                            deployment=deployment,
                            prompt=prompt,
                            max_tokens=max_completion_tokens,
                            timeout=timeout,
                            conversation_history=conversation_history,
                            output_schema_name=output_schema_name,
                            require_schema=require_schema,
                        )
                        return content, {}
                    raise
            snippet = _sanitize_body_snippet(exc).lower()
            code = int(getattr(exc, "code", 0) or 0)
            if require_schema and code == 400 and ("response_format" in snippet or "json_object" in snippet or "json mode" in snippet):
                raise
            if _should_retry_with_legacy_endpoint(exc):
                content = self._chat_completion_legacy(
                    endpoint=_legacy_endpoint_from_v1(endpoint),
                    api_key=api_key,
                    deployment=deployment,
                    prompt=prompt,
                    max_tokens=max_completion_tokens,
                    timeout=timeout,
                    conversation_history=conversation_history,
                    output_schema_name=output_schema_name,
                    require_schema=require_schema,
                )
                return content, {}
            raise

    def _chat_completion_v1(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt: str,
        role: V2ModelRole = V2ModelRole.ASSISTANT,
        max_completion_tokens: int = 20000,
        timeout: int = 30,
        conversation_history: list[dict[str, str]] | None = None,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> tuple[str, dict[str, int | None]]:
        content, usage = self._post_chat_completion_v1(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            messages=self._build_messages(prompt=prompt, conversation_history=conversation_history),
            role=role,
            max_completion_tokens=_role_max_output_tokens(role, max_completion_tokens),
            timeout=timeout,
            output_schema_name=output_schema_name,
            require_schema=require_schema,
        )
        return content, usage

    def _responses_completion_v1(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt: str,
        role: V2ModelRole = V2ModelRole.ASSISTANT,
        max_completion_tokens: int = 20000,
        timeout: int = 30,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        return self._post_responses_v1(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            input_items=self._build_response_input_items(
                prompt=prompt,
                conversation_history=conversation_history,
            ),
            role=role,
            max_output_tokens=max_completion_tokens,
            timeout=timeout,
        )

    @staticmethod
    def _build_messages(
        *,
        prompt: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _assistant_system_prompt()},
        ]
        if conversation_history:
            for entry in conversation_history[-6:]:
                role = str(entry.get("role", "user") or "user")
                content = str(entry.get("content", "") or "")
                if content.strip():
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _build_response_input_items(
        *,
        prompt: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = [
            {"type": "message", "role": "system", "content": _assistant_system_prompt()},
        ]
        if conversation_history:
            for entry in conversation_history[-6:]:
                role = str(entry.get("role", "user") or "user")
                content = str(entry.get("content", "") or "")
                if content.strip():
                    items.append({"type": "message", "role": role, "content": content})
        items.append({"type": "message", "role": "user", "content": prompt})
        return items

    def _smoke_completion(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        timeout: int = 15,
    ) -> str:
        if self._is_v1_endpoint(endpoint):
            endpoint = self._normalize_v1_endpoint(endpoint)
            try:
                return self._post_responses_v1(
                    endpoint=endpoint,
                    api_key=api_key,
                    deployment=deployment,
                    input_items=[{"type": "message", "role": "user", "content": "Reply with OK."}],
                    max_output_tokens=100,
                    timeout=timeout,
                )
            except urllib.error.HTTPError as exc:
                if _should_retry_with_chat_completions(exc):
                    try:
                        content, _usage = self._post_chat_completion_v1(
                            endpoint=endpoint,
                            api_key=api_key,
                            deployment=deployment,
                            messages=[{"role": "user", "content": "Reply with OK."}],
                            role=V2ModelRole.ASSISTANT,
                            max_completion_tokens=100,
                            timeout=timeout,
                        )
                        return content
                    except urllib.error.HTTPError as chat_exc:
                        if _should_retry_with_legacy_endpoint(chat_exc):
                            return self._post_chat_completion_legacy(
                                endpoint=_legacy_endpoint_from_v1(endpoint),
                                api_key=api_key,
                                deployment=deployment,
                                messages=[{"role": "user", "content": "Reply with OK."}],
                                max_tokens=100,
                                timeout=timeout,
                            )
                        raise
                if _should_retry_with_legacy_endpoint(exc):
                    return self._post_chat_completion_legacy(
                        endpoint=_legacy_endpoint_from_v1(endpoint),
                        api_key=api_key,
                        deployment=deployment,
                        messages=[{"role": "user", "content": "Reply with OK."}],
                        max_tokens=100,
                        timeout=timeout,
                    )
                raise
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
        role: V2ModelRole = V2ModelRole.ASSISTANT,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> tuple[str, dict[str, int | None]]:
        role_config = _model_role_config(role)
        supports_json_object = role_config.supports_json_object if role_config else True
        # Safe log: response_format usage for diagnostics
        _log_response_format_event(
            endpoint=endpoint,
            deployment=deployment,
            require_schema=bool(require_schema and supports_json_object),
            schema_name=output_schema_name or "",
            role=role.value,
        )

        url = f"{endpoint.rstrip('/')}/chat/completions"
        payload: dict[str, object] = {
            "model": deployment,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
        }
        # Schema-required calls always get prompt-enforced JSON. Only roles that
        # advertise JSON mode support receive response_format=json_object.
        if require_schema:
            if messages and messages[0].get("role") == "system":
                existing = str(messages[0].get("content", ""))
                json_instruction = (
                    "You are a JSON-only assistant. Return only valid JSON. "
                    "No markdown, no prose, no code fences. "
                )
                if "json-only assistant" not in existing.lower():
                    messages[0]["content"] = json_instruction + existing
        if require_schema and supports_json_object:
            payload["response_format"] = {"type": "json_object"}
        # Only add one of temperature / reasoning_effort when explicitly configured.
        # Sending an unsupported parameter to a model that does not recognise it
        # causes a 400 "badly formed" rejection at the Azure infrastructure layer.
        reasoning_effort = (role_config.reasoning_effort or "").strip() if role_config else ""
        if role_config and role_config.supports_reasoning_effort and reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        else:
            temperature = os.environ.get("AZURE_OPENAI_TEMPERATURE", "").strip()
            supports_temperature = role_config.supports_temperature if role_config else True
            if supports_temperature and temperature:
                try:
                    payload["temperature"] = float(temperature)
                except ValueError:
                    payload["temperature"] = 0.2
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = _extract_assistant_content(data)
        if not str(content).strip():
            # Empty response — log redacted diagnostics
            _log_empty_azure_response(data, deployment)
        usage = _extract_usage_data(data)
        return content, usage

    def _post_responses_v1(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        input_items: list[dict[str, object]],
        max_output_tokens: int,
        timeout: int,
        role: V2ModelRole = V2ModelRole.ASSISTANT,
    ) -> str:
        url = f"{endpoint.rstrip('/')}/responses"
        payload: dict[str, object] = {
            "model": deployment,
            "input": input_items,
            "store": False,
        }
        if max_output_tokens > 0:
            payload["max_output_tokens"] = max_output_tokens
        role_config = _model_role_config(role)
        reasoning_effort = (role_config.reasoning_effort or "").strip() if role_config else ""
        if role_config and role_config.supports_reasoning_effort and reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "api-key": api_key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = _extract_responses_output_text(data)
        if not str(content).strip():
            _log_empty_azure_response(data, deployment)
        return content

    def _chat_completion_legacy(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt: str,
        max_tokens: int = 20000,
        timeout: int = 30,
        conversation_history: list[dict[str, str]] | None = None,
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> str:
        return self._post_chat_completion_legacy(
            endpoint=endpoint,
            api_key=api_key,
            deployment=deployment,
            messages=self._build_messages(prompt=prompt, conversation_history=conversation_history),
            max_tokens=max_tokens,
            timeout=timeout,
            output_schema_name=output_schema_name,
            require_schema=require_schema,
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
        output_schema_name: str | None = None,
        require_schema: bool = False,
    ) -> str:
        api_version = _azure_api_version()
        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/"
            f"{deployment}/chat/completions?api-version={api_version}"
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
        "migration evidence using only the data supplied in the prompt.\n"
        "RULES:\n"
        "- Answer the user's actual question directly first. Do not always recite an operational checklist.\n"
        "- Use the operational status format (what happened, what failed, what artifacts were generated, "
        "what to do next) ONLY when the user asks about status, progress, failure, approval, or next steps.\n"
        "- Mention model/Azure/provider ONLY if the user asks about model connectivity or if model.status "
        "is explicitly fallback.\n"
        "- NEVER: approve, reject, execute commands, write files, change route or stage, choose Maven goals, "
        "choose deployments, or override proof.\n"
        "- All execution is backend-owned and human-gated.\n"
        "- Keep answers concise.\n"
        "STAGE-AWARE POM RULES:\n"
        "- Stage 1 and Stage 2 POMs are transitional. Explain, compare, and identify obvious risks, "
        "but do NOT propose final app-specific dependency modernization by default.\n"
        "- Stage 3 is the dependency modernization point. If Stage 3 root_pom exists and is stable, "
        "detect Java/Spring Boot baseline from the POM/evidence and review dependencies against that baseline.\n"
        "- Never guess Java or Spring Boot target versions. Read them from Stage 3 evidence.\n"
        "- Never recommend updating every dependency to latest.\n"
        "- Use target_dependency_plan, dependency_policy_report, dependency_graph, rewrite_preview, "
        "test reports, and operator-provided target versions.\n"
        "- For Boot-managed/transitive dependencies, prefer BOM/parent management; "
        "do not inject direct versions unless policy requires it.\n"
        "- For explicit dependency change requests, produce exact before/after XML, risk, evidence, "
        "OpenRewrite/backend recipe candidate, and approval path.\n"
        "- Never apply, write, approve, execute, or claim a change was made.\n"
        "POM / DEPENDENCY QUESTIONS:\n"
        "- If artifact_previews contains a root_pom entry (source_type='file_alias') with exists=true, "
        "explain the POM content directly: focus on dependencies, plugins, properties, versions, "
        "parent POM, repositories, and migration-relevant changes.\n"
        "- Use the backend-resolved preview as your primary source.\n"
        "- If root_pom exists=false, briefly explain the reason using the reason field and offer available artifact kinds.\n"
        "- NEVER suggest rewrite_dry_run.patch as a substitute for the full pom.xml.\n"
        "- When the user asks about dependencies, use root_pom content (if exists=true) as primary source. "
        "Do not fall back to dependency_graph unless root_pom is unavailable.\n"
        "POM CHANGE PROPOSAL QUESTIONS:\n"
        "- If the user asks to propose/change/upgrade/modify POM dependencies/plugins/properties, "
        "do NOT dump the full POM. Draft a human-reviewable proposal.\n"
        "- Include: 1) Proposed change with exact XML edits, 2) Why, 3) Risk, "
        "4) Evidence artifact names, 5) Required approval/gate, 6) Statement that nothing was applied.\n"
        "- Use root_pom plus available migration artifacts as evidence.\n"
        "- If the user asks you to apply/write/execute the change, refuse direct execution "
        "and offer to draft or create a gated proposal instead.\n"
        "- Never claim the POM was changed unless backend evidence says a command completed.\n"
        "- When root_pom has Spring Boot 2.x / javax dependencies, propose preparation "
        "(BOM alignment, dependencyManagement) and migration (java 11→17, javax→jakarta).\n"
        "- Target Spring Boot 3.x version must come from target_dependency_plan or migration_plan.yaml.\n"
        "Do not hardcode a version unless evidence provides one.\n"
        "STAGE 3 DEPENDENCY REVIEW RULES:\n"
        "- When the user asks for broad dependency modernization at Stage 3, "
        "detect the Java/Spring Boot baseline from the prompt's root_pom and artifact_previews.\n"
        "- Report the detected baseline with source.\n"
        "- Classify dependencies into buckets: Boot-managed, Jakarta/platform, "
        "app-specific third-party, build plugins, transitive/BOM-managed risk.\n"
        "- Recommend only evidence-backed changes. Use target_dependency_plan, "
        "dependency_policy_report, dependency_graph, and operator-provided targets.\n"
        "- Never recommend 'latest' without evidence.\n"
        "- For dependencies without target versions, mark as 'needs policy decision.'\n"
        "- For explicit dependency change requests (e.g., 'update library-name to 1.2.3 at stage 3'), "
        "produce exact before/after XML, risk, evidence, and backend recipe candidate.\n"
        "- If a dependency is transitive/BOM-managed (e.g., Tomcat), explain management "
        "and do not inject a direct dependency unless policy requires it.\n"
        "- Never apply, write, approve, execute, or claim a change was made.\n"
        "CAPABILITY BOUNDARY / FRUSTRATION:\n"
        "- Briefly explain that the assistant cannot approve, execute, write files, or change stages.\n"
        "- Then explain what it can do: explain POM, summarize evidence, compare artifacts, "
        "draft a repair request, identify what needs approval or evidence next.\n"
        "- Do not repeat the full pipeline status.\n"
        "STATUS QUESTIONS:\n"
        "- Use the operational format: what happened, what failed, what artifacts were generated, "
        "what to do next. Include stage status, approvals, and repair state.\n"
        "ROOT_POM REASON CODES (when exists=false):\n"
        "  stage_running — stage is still running; pom.xml may be incomplete\n"
        "  stage_not_completed — stage has not reached a completed state\n"
        "  sandbox_unresolved — backend could not locate the sandbox\n"
        "  file_missing_or_unsafe — pom.xml is not present or path safety check failed\n"
        "  file_unreadable — pom.xml exists but could not be read"
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


def _extract_responses_output_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise RuntimeError("missing responses payload")
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    output = data.get("output")
    if not isinstance(output, list):
        raise RuntimeError("missing responses output")
    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if str(part.get("type", "")) == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text)
    combined = "\n".join(text_parts).strip()
    if combined:
        return combined
    raise RuntimeError("missing responses output text")


def _extract_usage_data(data: Any) -> dict[str, int | None]:
    """Extract usage token counts from an Azure OpenAI response dict."""
    if not isinstance(data, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "reasoning_tokens": None}
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "reasoning_tokens": None}
    prompt_tokens: int | None = int(usage["prompt_tokens"]) if usage.get("prompt_tokens") is not None else None
    completion_tokens: int | None = int(usage["completion_tokens"]) if usage.get("completion_tokens") is not None else None
    total_tokens: int | None = int(usage["total_tokens"]) if usage.get("total_tokens") is not None else None
    reasoning_tokens: int | None = None
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        rt = details.get("reasoning_tokens")
        if rt is not None:
            reasoning_tokens = int(rt)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _log_empty_azure_response(data: dict[str, Any], deployment: str) -> None:
    """Log redacted diagnostic for empty Azure OpenAI responses.

    Captures: response id, model, finish_reason, usage, choice count,
    content_filter_results presence — all without leaking prompts, keys, or paths.
    """
    import logging
    logger = logging.getLogger("v2_assistant_model_client")
    try:
        diag: dict[str, Any] = {
            "event": "azure_empty_response",
            "deployment": str(deployment)[:64] if deployment else "",
        }
        if isinstance(data, dict):
            resp_id = str(data.get("id", ""))[:64]
            if resp_id:
                diag["response_id"] = resp_id
            model_name = str(data.get("model", ""))[:64]
            if model_name:
                diag["model"] = model_name
            choices = data.get("choices")
            if isinstance(choices, list):
                diag["choice_count"] = len(choices)
                if choices:
                    first = choices[0] if isinstance(choices[0], dict) else {}
                    finish = first.get("finish_reason", "")
                    if finish:
                        diag["finish_reason"] = str(finish)[:64]
                    msg = first.get("message")
                    diag["message_present"] = bool(msg)
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        diag["content_present"] = content is not None
                        diag["content_length"] = len(str(content or ""))
            usage = data.get("usage")
            if isinstance(usage, dict):
                diag["usage"] = {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                }
            cfr = data.get("content_filter_results")
            diag["content_filter_results_present"] = cfr is not None
        logger.warning("AZURE_EMPTY_RESPONSE: %s", json.dumps(diag, default=str))
    except Exception:
        logger.warning("AZURE_EMPTY_RESPONSE: could not build diagnostic")


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


def _role_max_output_tokens(role: V2ModelRole, default_tokens: int = 20000) -> int:
    """Read role-specific max output tokens from env var or return default."""
    role_config = _model_role_config(role)
    if role_config is not None and role_config.max_output_tokens > 0:
        return role_config.max_output_tokens
    role_env_map = {
        V2ModelRole.PROPOSER: "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS",
        V2ModelRole.REVIEWER: "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS",
        V2ModelRole.ASSISTANT: "AZURE_OPENAI_ASSISTANT_MAX_COMPLETION_TOKENS",
    }
    env_name = role_env_map.get(role, "")
    if env_name:
        value = os.environ.get(env_name, "").strip()
        if value and value.isdigit():
            return int(value)
    return default_tokens


def _model_role_config(role: V2ModelRole):
    if role in (V2ModelRole.PROPOSER, V2ModelRole.ASSISTANT):
        return ModelRoleConfigLoader.try_load_role("main")
    if role == V2ModelRole.REVIEWER:
        return ModelRoleConfigLoader.try_load_role("reviewer")
    if role == V2ModelRole.FALLBACK:
        return ModelRoleConfigLoader.try_load_role("fallback")
    return ModelRoleConfigLoader.try_load_role("main")


def _azure_api_version() -> str:
    return os.environ.get("AZURE_OPENAI_API_VERSION", "").strip() or "2024-10-21"


def _legacy_endpoint_from_v1(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.lower().endswith("/openai/v1"):
        return normalized[:-10]
    return normalized


def _should_retry_with_legacy_endpoint(http_error: urllib.error.HTTPError) -> bool:
    code = int(getattr(http_error, "code", 0) or 0)
    if code != 400:
        return False
    snippet = _sanitize_body_snippet(http_error).lower()
    if not snippet:
        return True
    return "<html" in snippet and "bad request" in snippet and "badly formed" in snippet


def _should_retry_with_chat_completions(http_error: urllib.error.HTTPError) -> bool:
    code = int(getattr(http_error, "code", 0) or 0)
    if code in {404, 405}:
        return True
    if code != 400:
        return False
    snippet = _sanitize_body_snippet(http_error).lower()
    if not snippet:
        return True
    return (
        "<html" in snippet
        or "badly formed" in snippet
        or "unsupported" in snippet
        or "not supported" in snippet
        or "unknown parameter" in snippet
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


def _log_empty_azure_result_summary(*, endpoint: str, deployment: str) -> None:
    """Log a redacted summary when Azure returns empty content and fallback is used.

    Does NOT leak endpoint, deployment, or keys.
    """
    import logging
    logger = logging.getLogger("v2_assistant_model_client")
    safe_deployment = _public_deployment_label(deployment)
    logger.warning(
        "AZURE_EMPTY_RESULT: deployment=%s (empty response from Azure; using deterministic fallback)",
        safe_deployment or "unset",
    )


def _log_response_format_event(
    *,
    endpoint: str,
    deployment: str,
    require_schema: bool,
    schema_name: str,
    role: str,
) -> None:
    """Log a safe response_format event for schema-required Azure calls.

    No raw endpoint, deployment, key, or prompt is exposed.
    Only a deployment_alias_hash is included.
    """
    import logging
    logger = logging.getLogger("v2_assistant_model_client")
    safe_deployment = _public_deployment_label(deployment)
    dep_hash = ""
    if deployment:
        import hashlib
        dep_hash = hashlib.sha256(deployment.encode("utf-8")).hexdigest()[:16]
    logger.info(
        "RESPONSE_FORMAT_REQUESTED: require_schema=%s schema_name=%s role=%s deployment_alias_hash=%s",
        require_schema,
        schema_name,
        role,
        dep_hash or "unset",
    )
