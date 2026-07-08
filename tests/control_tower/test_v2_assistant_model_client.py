from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO

import pytest

from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole


class _UrlopenRecorder:
    def __init__(self, responses: list[dict[str, object]] | None = None) -> None:
        self._responses = list(responses or [{"body": {"output_text": "{\"ok\": true}"}}])
        self.calls: list[tuple[urllib.request.Request, int | None]] = []

    def __call__(self, request: urllib.request.Request, timeout: int | None = None):
        self.calls.append((request, timeout))
        if not self._responses:
            raise AssertionError("No queued response")
        response = self._responses.pop(0)
        status = int(response.get("status", 200))
        body = response.get("body", {})
        if status >= 400:
            raw = json.dumps(body).encode("utf-8")
            raise urllib.error.HTTPError(request.full_url, status, "error", hdrs=None, fp=BytesIO(raw))
        return _Response(body if isinstance(body, dict) else {"output_text": str(body)})


class _Response:
    def __init__(self, body: dict[str, object]) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._body).encode("utf-8")


def _request_body(call: tuple[urllib.request.Request, int | None]) -> dict[str, object]:
    request, _timeout = call
    return json.loads(request.data.decode("utf-8")) if request.data else {}


@pytest.fixture()
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_REVIEWER_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_ASSISTANT_MAX_COMPLETION_TOKENS",
        "AZURE_OPENAI_FALLBACK_MAX_OUTPUT_TOKENS",
        "AZURE_OPENAI_MAIN_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_PROPOSER_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_ASSISTANT_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_FALLBACK_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS",
        "AI_MIGRATION_PROPOSER_TIMEOUT_SECONDS",
        "AI_MIGRATION_REVIEWER_TIMEOUT_SECONDS",
        "AI_MIGRATION_ASSISTANT_TIMEOUT_SECONDS",
        "AI_MIGRATION_MAIN_TIMEOUT_SECONDS",
        "AI_MIGRATION_FALLBACK_TIMEOUT_SECONDS",
        "AZURE_OPENAI_REASONING_EFFORT",
        "CONTROL_TOWER_AZURE_FOUNDRY_FALLBACK_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "gpt-proposer")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "gpt-reviewer")
    monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "gpt-assistant")
    monkeypatch.delenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", raising=False)


def _answer_with_role(monkeypatch: pytest.MonkeyPatch, recorder: _UrlopenRecorder, role: V2ModelRole):
    from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelClient

    monkeypatch.setattr(urllib.request, "urlopen", recorder)
    return V2AssistantModelClient().answer_with_role(role=role, prompt="prompt", fallback="fallback")


def test_proposer_reads_azure_role_output_budget(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS", "20000")

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert result.success is True
    assert _request_body(recorder.calls[0])["max_output_tokens"] == 20000


def test_reviewer_reads_azure_role_output_budget(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_MAX_OUTPUT_TOKENS", "18000")

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.REVIEWER)

    assert result.success is True
    assert _request_body(recorder.calls[0])["max_output_tokens"] == 18000


def test_assistant_budget_does_not_override_proposer_budget(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS", "19000")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS", "12000")

    _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert _request_body(recorder.calls[0])["max_output_tokens"] == 12000


def test_ai_migration_role_budget_fallback_works(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder()
    monkeypatch.setenv("AI_MIGRATION_PROPOSER_MAX_OUTPUT_TOKENS", "15000")

    _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert _request_body(recorder.calls[0])["max_output_tokens"] == 15000


def test_invalid_role_budget_is_rejected_and_excessive_budget_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    invalid = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS", "0")
    _answer_with_role(monkeypatch, invalid, V2ModelRole.PROPOSER)
    assert _request_body(invalid.calls[0])["max_output_tokens"] == 700

    bounded = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS", "999999")
    _answer_with_role(monkeypatch, bounded, V2ModelRole.PROPOSER)
    assert _request_body(bounded.calls[0])["max_output_tokens"] == 20000


def test_role_timeout_uses_ai_migration_timeout(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder()
    monkeypatch.setenv("AI_MIGRATION_PROPOSER_TIMEOUT_SECONDS", "300")

    _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert recorder.calls[0][1] == 300


def test_responses_incomplete_max_output_tokens_becomes_output_truncated(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder(
        [
            {
                "body": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output_text": "{\"schema_version\":\"1.0\",\"root_cause\":\"partial",
                }
            }
        ]
    )

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert result.success is False
    assert result.failure_reason == "output_truncated"
    assert result.primary_failure_reason == "output_truncated"


def test_incomplete_response_is_not_schema_validated(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    import migration_factory.control_tower.application.v2_model_role_router as router_module
    from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelClient

    recorder = _UrlopenRecorder(
        [
            {
                "body": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output_text": "{\"schema_version\":\"1.0\",\"root_cause\":\"partial",
                }
            }
        ]
    )

    def fail_if_schema_validated(*_: object, **__: object) -> None:
        raise AssertionError("incomplete provider content must not be schema validated")

    monkeypatch.setattr(router_module, "validate_model_output", fail_if_schema_validated)
    monkeypatch.setattr(urllib.request, "urlopen", recorder)

    result = V2AssistantModelClient().answer_with_role(
        role=V2ModelRole.PROPOSER,
        prompt="prompt",
        fallback="fallback",
        output_schema_name="RepairPrimaryOutput",
        require_schema=True,
    )

    assert result.success is False
    assert result.failure_reason == "output_truncated"


def test_chat_completion_length_finish_reason_becomes_output_truncated(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder(
        [
            {"status": 404, "body": {"error": {"message": "responses unavailable"}}},
            {
                "body": {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": "{\"schema_version\":\"1.0\""},
                        }
                    ]
                }
            },
        ]
    )

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert result.success is False
    assert result.failure_reason == "output_truncated"
    assert _request_body(recorder.calls[1])["max_completion_tokens"] == 700


def test_responses_incomplete_without_text_is_classified_before_text_extraction(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder(
        [
            {
                "body": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                }
            }
        ]
    )

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert result.success is False
    assert result.failure_reason == "output_truncated"
    assert result.provider_completion_status == "incomplete"
    assert result.provider_incomplete_reason == "max_output_tokens"


def test_chat_length_without_content_is_classified_before_content_extraction(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder(
        [
            {"status": 404, "body": {"error": {"message": "responses unavailable"}}},
            {
                "body": {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {},
                        }
                    ]
                }
            },
        ]
    )

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert result.success is False
    assert result.failure_reason == "output_truncated"
    assert result.provider_finish_reason == "length"


def test_provider_fallback_uses_fallback_role_budget_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    recorder = _UrlopenRecorder(
        [
            {
                "body": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                }
            },
            {"body": {"output_text": "fallback provider response"}},
        ]
    )
    monkeypatch.setenv("CONTROL_TOWER_AZURE_FOUNDRY_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "gpt-fallback")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS", "12000")
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_MAX_OUTPUT_TOKENS", "9000")
    monkeypatch.setenv("AI_MIGRATION_PROPOSER_TIMEOUT_SECONDS", "111")
    monkeypatch.setenv("AI_MIGRATION_FALLBACK_TIMEOUT_SECONDS", "222")

    result = _answer_with_role(monkeypatch, recorder, V2ModelRole.PROPOSER)

    assert result.success is True
    assert result.fallback_used is True
    assert _request_body(recorder.calls[0])["model"] == "gpt-proposer"
    assert _request_body(recorder.calls[0])["max_output_tokens"] == 12000
    assert recorder.calls[0][1] == 111
    assert _request_body(recorder.calls[1])["model"] == "gpt-fallback"
    assert _request_body(recorder.calls[1])["max_output_tokens"] == 9000
    assert recorder.calls[1][1] == 222


def test_legacy_assistant_completion_budget_is_assistant_only_and_low_priority(
    monkeypatch: pytest.MonkeyPatch,
    configured_env: None,
) -> None:
    legacy_only = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_MAX_COMPLETION_TOKENS", "13000")

    _answer_with_role(monkeypatch, legacy_only, V2ModelRole.ASSISTANT)

    assert _request_body(legacy_only.calls[0])["max_output_tokens"] == 13000

    preferred = _UrlopenRecorder()
    monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_MAX_OUTPUT_TOKENS", "14000")

    _answer_with_role(monkeypatch, preferred, V2ModelRole.ASSISTANT)

    assert _request_body(preferred.calls[0])["max_output_tokens"] == 14000

    proposer = _UrlopenRecorder()

    _answer_with_role(monkeypatch, proposer, V2ModelRole.PROPOSER)

    assert _request_body(proposer.calls[0])["max_output_tokens"] == 700
