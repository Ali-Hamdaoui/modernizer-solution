"""Tests for Mistral provider client adapter and reviewer role integration."""

from __future__ import annotations

import json
import os

from migration_factory.control_tower.application.v2_mistral_provider_client import (
    MistralProviderClient,
)
from migration_factory.control_tower.application.v2_model_role_config import (
    ModelRoleConfigLoader,
)
from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
    V2AssistantModelResult,
)
from migration_factory.control_tower.application.v2_model_role_router import (
    V2ModelRole,
    V2ModelRoleRouter,
    V2RoleModelRequest,
)
from migration_factory.control_tower.application.v2_model_schemas import (
    validate_model_output,
    REPAIR_REVIEWER_OUTPUT_SCHEMA,
)
from migration_factory.orchestrator.repair_review_chain import (
    _reviewer_repair_prompt,
    _coerce_reviewer_repair_output,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_reviewer_result(content: str, success: bool = True) -> V2AssistantModelResult:
    return V2AssistantModelResult(
        content=content,
        source="mistral",
        model_status="live_ok",
        provider="mistral",
        role="reviewer",
        success=success,
        redacted_summary="test invocation",
        failure_reason="",
    )


# ── 1. Reviewer role loads Mistral Large 3 config ─────────────────────


def test_reviewer_role_loads_mistral_large_3_config(monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_PROVIDER", "mistral")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "mistral-large-2512")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME", "Mistral Large 3")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_ENDPOINT_TYPE", "mistral_chat")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_RESPONSE_FORMAT", "json_object")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS", "50000")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS", "20000")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_TIMEOUT_SECONDS", "30")

    config = ModelRoleConfigLoader.load_role("reviewer")

    assert config.provider_alias == "mistral"
    assert config.deployment_or_model_id == "mistral-large-2512"
    assert config.model_display_name == "Mistral Large 3"
    assert config.endpoint_type == "mistral_chat"
    assert config.response_format == "json_object"
    assert config.max_input_tokens == 50000
    assert config.max_output_tokens == 20000
    assert config.timeout_seconds == 30


# ── 2. Mistral reviewer uses Mistral provider adapter ─────────────────


def test_mistral_reviewer_uses_mistral_provider_adapter(monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_PROVIDER", "mistral")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "mistral-large-2512")
    monkeypatch.setenv("MISTRAL_ENDPOINT", "https://api.mistral.ai/v1")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key-12345")

    client = V2AssistantModelClient()
    call_record: dict = {}

    def fake_chat_completion(self, *, endpoint, api_key, model, messages, **_):
        call_record["endpoint"] = endpoint
        call_record["api_key"] = api_key
        call_record["model"] = model
        return {
            "choices": [{"message": {"content": '{"decision":"accept","notes":[],"risks":[],"policy_concerns":[],"changed_files_verified":true,"diff_parseable":true,"checksum_bindings":{"reviewed_context_checksum":"abc","reviewed_primary_output_checksum":"def","reviewed_diff_checksum":"ghi"}}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

    monkeypatch.setattr(MistralProviderClient, "chat_completion", fake_chat_completion)

    result = client.answer_with_role(
        role=V2ModelRole.REVIEWER,
        prompt="Review this diff",
        fallback="reviewer unavailable",
    )

    assert call_record.get("endpoint") == "https://api.mistral.ai/v1"
    assert call_record.get("api_key") == "test-key-12345"
    assert call_record.get("model") == "mistral-large-2512"
    assert result.provider == "mistral"
    assert result.success is True


# ── 3. Mistral reviewer prompt explicitly requires JSON ───────────────


def test_mistral_reviewer_prompt_explicitly_requires_json() -> None:
    primary_output = {
        "root_cause": "test failure",
        "fix_strategy": "fix it",
        "changed_files": ["src/main.java"],
        "proposed_diff": "diff --git a/src/main.java b/src/main.java\n--- a/src/main.java\n+++ b/src/main.java\n@@ -1 +1 @@\n-old\n+new\n",
        "risk": "LOW",
        "confidence": 0.9,
        "rationale": "test",
    }
    prompt = _reviewer_repair_prompt(
        primary_output=primary_output,
        deterministic_checksum="det123",
        context_checksum="ctx123",
        primary_checksum="pri123",
        diff_checksum="diff123",
    )

    assert "Output only valid JSON. No markdown. No code fences. No commentary." in prompt
    assert "Match the RepairReviewerOutput schema exactly." in prompt
    assert "changed_files_verified" in prompt
    assert "diff_parseable" in prompt
    assert "checksum_bindings" in prompt
    assert "reason_for_rejection" in prompt
    assert "revision_request" in prompt


# ── 4. Mistral reviewer uses 20k output budget ────────────────────────


def test_mistral_reviewer_uses_20k_output_budget(monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_PROVIDER", "mistral")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "mistral-large-2512")
    monkeypatch.setenv("AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS", "20000")

    config = ModelRoleConfigLoader.load_role("reviewer")
    assert config.max_output_tokens == 20000

    # Verify the runtime reads it correctly
    from migration_factory.control_tower.application.v2_assistant_model_client import _role_max_output_tokens
    tokens = _role_max_output_tokens(V2ModelRole.REVIEWER)
    assert tokens == 20000


# ── 5. Mistral reviewer schema validation required ────────────────────


def test_mistral_reviewer_schema_validation_required() -> None:
    valid_output = {
        "decision": "accept",
        "notes": ["diff looks correct"],
        "risks": ["low risk"],
        "policy_concerns": [],
        "changed_files_verified": True,
        "diff_parseable": True,
        "reviewed_context_checksum": "abc123",
        "reviewed_primary_output_checksum": "def456",
        "reviewed_diff_checksum": "ghi789",
    }
    validate_model_output("RepairReviewerOutput", valid_output)

    # Missing changed_files_verified should fail
    invalid_output = {k: v for k, v in valid_output.items() if k != "changed_files_verified"}
    try:
        validate_model_output("RepairReviewerOutput", invalid_output)
        assert False, "expected schema validation error"
    except Exception:
        pass

    # Missing diff_parseable should fail
    invalid_output2 = {k: v for k, v in valid_output.items() if k != "diff_parseable"}
    try:
        validate_model_output("RepairReviewerOutput", invalid_output2)
        assert False, "expected schema validation error"
    except Exception:
        pass

    # Wrong type for changed_files_verified should fail
    wrong_type = dict(valid_output)
    wrong_type["changed_files_verified"] = "not_a_boolean"
    try:
        validate_model_output("RepairReviewerOutput", wrong_type)
        assert False, "expected schema validation error"
    except Exception:
        pass


# ── 6. Reviewer does not run when main schema invalid ─────────────────


def test_reviewer_does_not_run_when_main_schema_invalid(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "proposer-deployment")

    router = V2ModelRoleRouter()
    invoked: list[str] = []

    def invoke(deployment: str, provider: str = "azure_openai") -> V2AssistantModelResult:
        invoked.append(deployment)
        return V2AssistantModelResult(
            content='{"root_cause": "test"}',
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role="proposer",
            success=True,
            redacted_summary="",
            failure_reason="",
        )

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.PROPOSER,
            prompt="test",
            fallback="fallback",
            output_schema_name="RepairPrimaryOutput",
            require_schema=True,
        ),
        invoke=invoke,
    )

    # Proposer schema failed -> should not proceed to reviewer
    assert result.success is False
    assert result.failure_reason == "main_schema_invalid"


# ── 7. Reviewer reviews normalized diff content ───────────────────────


def test_reviewer_reviews_normalized_diff_content(monkeypatch) -> None:
    from migration_factory.orchestrator.repair_review_chain import _normalize_to_git_diff

    raw_diff = "--- a/src/main.java\n+++ b/src/main.java\n@@ -1 +1 @@\n-old\n+new\n"
    normalized_diff, was_normalized = _normalize_to_git_diff(raw_diff)
    assert was_normalized is True
    assert normalized_diff.startswith("diff --git ")
    assert "src/main.java" in normalized_diff

    # The reviewer prompt receives the normalized diff
    primary_output = {
        "root_cause": "test",
        "fix_strategy": "fix",
        "changed_files": ["src/main.java"],
        "proposed_diff": normalized_diff,
        "risk": "LOW",
        "confidence": 0.9,
        "rationale": "test",
    }
    prompt = _reviewer_repair_prompt(
        primary_output=primary_output,
        deterministic_checksum="det",
        context_checksum="ctx",
        primary_checksum="pri",
        diff_checksum="diff",
    )

    assert "diff --git a/src/main.java b/src/main.java" in prompt
    # The diff in the JSON-encoded primary output uses escaped newlines
    assert "diff --git a/src/main.java b/src/main.java" in prompt


# ── 8. Reviewer rejects unparseable diff ──────────────────────────────


def test_reviewer_rejects_unparseable_diff() -> None:
    # Coercing a reviewer output that flags diff as unparseable
    reviewer_content = json.dumps({
        "decision": "reject",
        "notes": ["diff is unparseable"],
        "risks": ["cannot validate"],
        "policy_concerns": ["malformed diff"],
        "changed_files_verified": False,
        "diff_parseable": False,
        "reviewed_context_checksum": "ctx123",
        "reviewed_primary_output_checksum": "pri123",
        "reviewed_diff_checksum": "diff123",
        "reason_for_rejection": "diff is not valid unified diff format",
    })

    output = _coerce_reviewer_repair_output(
        reviewer_content,
        deterministic_checksum="det123",
        context_checksum="ctx123",
        primary_checksum="pri123",
        diff_checksum="diff123",
    )

    assert output["decision"] == "reject"
    assert output["diff_parseable"] is False
    assert output["changed_files_verified"] is False


# ── MistralProviderClient unit tests ──────────────────────────────────


def test_mistral_provider_client_extract_content() -> None:
    client = MistralProviderClient()
    response = {
        "choices": [
            {"message": {"content": '{"decision": "accept"}'}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    content = client.extract_content(response)
    assert content == '{"decision": "accept"}'


def test_mistral_provider_client_extract_usage() -> None:
    client = MistralProviderClient()
    response = {
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    usage = client.extract_usage(response)
    assert usage["prompt_tokens"] == 100
    assert usage["completion_tokens"] == 50
    assert usage["total_tokens"] == 150


def test_mistral_provider_client_build_json_mode_instruction() -> None:
    instruction = MistralProviderClient.build_json_mode_system_instruction()
    assert "Output only valid JSON" in instruction
    assert "No markdown" in instruction
