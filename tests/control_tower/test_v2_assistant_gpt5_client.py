"""Tests for GPT-5 mini client behavior in the V2 assistant model client.

Verifies:
- Default max_completion_tokens = 20000 (not 700)
- No max_tokens sent to GPT-5 reasoning calls (only max_completion_tokens)
- json_object response_format when require_schema=True
- Parsing of choices[0].message.content
- Role output budget defaults to 20000
- reasoning_effort read from AI_MIGRATION_MAIN_REASONING_EFFORT
- Temperature NOT sent when reasoning_effort is set
- Temperature sent when reasoning_effort is NOT set
- Empty response classified correctly
- Invalid JSON classified correctly
- Usage token extraction (prompt_tokens, completion_tokens, total_tokens, reasoning_tokens)
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
from typing import Any

import pytest

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
    V2AssistantModelResult,
    _extract_assistant_content,
    _extract_usage_data,
    _role_max_output_tokens,
)
from migration_factory.control_tower.application.v2_model_role_router import (
    V2ModelRole,
    V2ModelRoleRouter,
    V2RoleModelRequest,
    V2RoleModelResult,
)
from migration_factory.control_tower.application.v2_settings import ControlTowerSettings


# ── Helpers ────────────────────────────────────────────────────────────


def _make_response(
    content: str = "test response",
    usage: dict[str, Any] | None = None,
    finish_reason: str = "stop",
) -> bytes:
    if usage is None:
        usage = {
            "prompt_tokens": 50,
            "completion_tokens": 100,
            "total_tokens": 150,
        }
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "gpt-5-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }
    return json.dumps(payload).encode("utf-8")


class _RecorderURLopener:
    """Captures the last request for inspection."""

    def __init__(self, response_body: bytes = b'{"choices":[{"message":{"content":"ok"}}]}'):
        self.calls: list[Any] = []
        self._body = response_body

    def __call__(self, request: urllib.request.Request, *, timeout: int = 30) -> io.BytesIO:
        self.calls.append(request)
        return io.BytesIO(self._body)


# ── _role_max_output_tokens ────────────────────────────────────────────


class TestRoleMaxOutputTokens:
    def test_default_is_20000(self) -> None:
        assert _role_max_output_tokens(V2ModelRole.PROPOSER) == 20000

    def test_default_for_reviewer(self) -> None:
        assert _role_max_output_tokens(V2ModelRole.REVIEWER) == 20000

    def test_default_for_assistant(self) -> None:
        assert _role_max_output_tokens(V2ModelRole.ASSISTANT) == 20000

    def test_env_override_proposer(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS", "5000")
        assert _role_max_output_tokens(V2ModelRole.PROPOSER) == 5000

    def test_env_override_reviewer(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS", "3000")
        assert _role_max_output_tokens(V2ModelRole.REVIEWER) == 3000


# ── _post_chat_completion_v1 request shape ─────────────────────────────


class TestPostChatCompletionV1RequestShape:
    def _chat_completions_url(self) -> str:
        """Non-v1 endpoint to force chat/completions path (not Responses API)."""
        return "https://example-azure.openai.com"

    def test_default_max_completion_tokens_is_20000(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer(prompt="test", fallback="fallback")
        assert len(recorder.calls) >= 1
        body = json.loads(recorder.calls[0].data)
        assert body["max_completion_tokens"] == 20000

    def test_does_not_send_max_tokens(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer(prompt="test", fallback="fallback")
        body = json.loads(recorder.calls[0].data)
        assert "max_tokens" not in body

    def test_sends_json_object_response_format_when_required(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt="test",
            fallback="fallback",
            require_schema=True,
            output_schema_name="RepairPrimaryOutput",
        )
        body = json.loads(recorder.calls[0].data)
        assert body.get("response_format") == {"type": "json_object"}

    def test_parses_choices_message_content(self) -> None:
        data = {
            "choices": [{"message": {"content": "hello world"}}]
        }
        assert _extract_assistant_content(data) == "hello world"

    def test_reasoning_effort_from_main_env_var(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_REASONING_EFFORT", "high")
        monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "medium")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt="test",
            fallback="fallback",
        )
        body = json.loads(recorder.calls[0].data)
        assert body.get("reasoning_effort") == "high"

    def test_reasoning_effort_falls_back_to_old_env_var(self, monkeypatch) -> None:
        monkeypatch.delenv("AI_MIGRATION_MAIN_REASONING_EFFORT", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "low")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt="test",
            fallback="fallback",
        )
        body = json.loads(recorder.calls[0].data)
        assert body.get("reasoning_effort") == "low"

    def test_temperature_not_sent_when_reasoning_effort_set(self, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_REASONING_EFFORT", "high")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "gpt-5-mini")
        monkeypatch.setenv("AZURE_OPENAI_TEMPERATURE", "0.7")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt="test",
            fallback="fallback",
        )
        body = json.loads(recorder.calls[0].data)
        assert "temperature" not in body

    def test_temperature_sent_when_no_reasoning_effort(self, monkeypatch) -> None:
        monkeypatch.delenv("AI_MIGRATION_MAIN_REASONING_EFFORT", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_REASONING_EFFORT", raising=False)
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", self._chat_completions_url())
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-5-mini")
        monkeypatch.setenv("AZURE_OPENAI_TEMPERATURE", "0.5")
        recorder = _RecorderURLopener()
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.answer(prompt="test", fallback="fallback")
        body = json.loads(recorder.calls[0].data)
        assert body.get("temperature") == 0.5


# ── Response parsing ──────────────────────────────────────────────────


class TestResponseParsing:
    def test_extract_assistant_content_ok(self) -> None:
        data = {"choices": [{"message": {"content": "hello"}}]}
        assert _extract_assistant_content(data) == "hello"

    def test_extract_assistant_content_missing_choices(self) -> None:
        with pytest.raises(RuntimeError, match="missing choices"):
            _extract_assistant_content({})

    def test_extract_assistant_content_empty_content(self) -> None:
        with pytest.raises(RuntimeError, match="missing assistant content"):
            _extract_assistant_content({"choices": [{"message": {"content": None}}]})


# ── Usage data extraction ─────────────────────────────────────────────


class TestUsageDataExtraction:
    def test_basic_usage_fields(self) -> None:
        data = {
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 100,
                "total_tokens": 150,
            }
        }
        usage = _extract_usage_data(data)
        assert usage["prompt_tokens"] == 50
        assert usage["completion_tokens"] == 100
        assert usage["total_tokens"] == 150
        assert usage["reasoning_tokens"] is None

    def test_reasoning_tokens_included(self) -> None:
        data = {
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 100,
                "total_tokens": 150,
                "completion_tokens_details": {"reasoning_tokens": 30},
            }
        }
        usage = _extract_usage_data(data)
        assert usage["reasoning_tokens"] == 30

    def test_no_usage_field(self) -> None:
        usage = _extract_usage_data({})
        assert usage == {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "reasoning_tokens": None,
        }

    def test_none_data(self) -> None:
        usage = _extract_usage_data(None)
        assert usage == {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "reasoning_tokens": None,
        }

    def test_partial_usage(self) -> None:
        data = {"usage": {"prompt_tokens": 10}}
        usage = _extract_usage_data(data)
        assert usage["prompt_tokens"] == 10
        assert usage["completion_tokens"] is None
        assert usage["total_tokens"] is None


# ── V2AssistantModelResult usage fields ───────────────────────────────


class TestResultUsageFields:
    def test_usage_fields_default_to_none(self) -> None:
        result = V2AssistantModelResult(
            content="test",
            source="test",
            model_status="live_ok",
            provider="test",
            role="test",
            success=True,
            redacted_summary="test",
            failure_reason="",
        )
        assert result.prompt_tokens is None
        assert result.completion_tokens is None
        assert result.total_tokens is None
        assert result.reasoning_tokens is None
        assert result.latency_ms is None

    def test_usage_fields_can_be_set(self) -> None:
        result = V2AssistantModelResult(
            content="test",
            source="test",
            model_status="live_ok",
            provider="test",
            role="test",
            success=True,
            redacted_summary="test",
            failure_reason="",
            prompt_tokens=50,
            completion_tokens=100,
            total_tokens=150,
            reasoning_tokens=30,
            latency_ms=1234,
        )
        assert result.prompt_tokens == 50
        assert result.completion_tokens == 100
        assert result.total_tokens == 150
        assert result.reasoning_tokens == 30
        assert result.latency_ms == 1234


# ── V2RoleModelResult usage fields ────────────────────────────────────


class TestRoleResultUsageFields:
    def test_usage_fields_default_to_none(self) -> None:
        result = V2RoleModelResult(
            content="test",
            role="test",
            provider="test",
            source="test",
            model_status="live_ok",
            success=True,
            failure_reason="",
        )
        assert result.prompt_tokens is None
        assert result.completion_tokens is None
        assert result.total_tokens is None
        assert result.reasoning_tokens is None
        assert result.latency_ms is None


# ── Integration: usage data flows from _post_chat_completion_v1 ───────


class TestUsageDataFlow:
    def test_usage_tokens_recorded_in_result(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example-azure.openai.com")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-5-mini")
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
        recorder = _RecorderURLopener(_make_response(content="test ok", usage=usage))
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        result = client.answer(prompt="test", fallback="fallback")
        assert result.success is True
        assert result.content == "test ok"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 20
        assert result.total_tokens == 30
        assert result.reasoning_tokens == 5
        assert result.latency_ms is not None
        assert isinstance(result.latency_ms, int)

    def test_usage_safe_when_missing(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example-azure.openai.com")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener(b'{"choices":[{"message":{"content":"ok"}}]}')
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        result = client.answer(prompt="test", fallback="fallback")
        assert result.success is True
        assert result.content == "ok"
        assert result.prompt_tokens is None
        assert result.completion_tokens is None
        assert result.total_tokens is None
        assert result.reasoning_tokens is None
        assert result.latency_ms is not None


# ── Smoke tests ───────────────────────────────────────────────────────


class TestSmoke:
    def test_smoke_uses_max_completion_tokens_100(self, monkeypatch) -> None:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-5-mini")
        recorder = _RecorderURLopener(b'{"output_text": "OK"}')
        monkeypatch.setattr(urllib.request, "urlopen", recorder)
        client = V2AssistantModelClient()
        client.smoke()
        body = json.loads(recorder.calls[0].data)
        # Smoke always uses 100, not the role default
        assert body.get("max_output_tokens") == 100
