"""Tests for V2 role-based model routing."""

from __future__ import annotations

import json

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
    V2AssistantModelResult,
)
from migration_factory.control_tower.application.v2_model_role_router import (
    V2ModelRole,
    V2ModelRoleRouter,
    V2RoleModelRequest,
    V2RoleModelResult,
    _build_diagnostic_summary_from_diag,
    _build_schema_failure_summary,
    _classify_diff_failure,
    _parse_model_json_safe,
)
from migration_factory.control_tower.application.v2_settings import ControlTowerSettings


def test_router_plans_role_specific_deployments(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "proposer-deployment")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "reviewer-deployment")
    monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "assistant-deployment")
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "fallback-deployment")

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=True))
    plan = router.plan(
        V2RoleModelRequest(
            role=V2ModelRole.PROPOSER,
            prompt="draft a proposal",
            fallback="fallback",
        )
    )

    assert plan.primary_env_ref == "AZURE_OPENAI_PROPOSER_DEPLOYMENT"
    assert plan.primary_deployment == "proposer-deployment"
    assert plan.fallback_env_ref == "AZURE_OPENAI_FALLBACK_DEPLOYMENT"
    assert plan.fallback_deployment == "fallback-deployment"
    assert plan.fallback_enabled is True


def test_router_uses_fallback_deployment_when_primary_missing(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "fallback-deployment")

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=True))
    calls: list[str] = []

    def invoke(deployment: str) -> V2AssistantModelResult:
        calls.append(deployment)
        return V2AssistantModelResult(
            content="fallback response",
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role="proposer",
            success=True,
            redacted_summary="fallback response",
            failure_reason="",
        )

    result = router.route(
        V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="draft", fallback="fallback"),
        invoke=invoke,
    )

    assert calls == ["fallback-deployment"]
    assert result.success is True
    assert result.fallback_used is True
    assert result.primary_failure_reason == "missing_proposer_deployment"
    assert result.content == "fallback response"


def test_router_does_not_select_static_fallback_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", raising=False)

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=True))
    calls: list[str] = []

    result = router.route(
        V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="draft", fallback="fallback"),
        invoke=lambda deployment: calls.append(deployment),
    )

    assert calls == []
    assert result.success is False
    assert result.provider == "deterministic"
    assert result.failure_reason == "missing_proposer_deployment"
    assert result.fallback_used is False


def test_router_uses_user_selected_reviewer_deployment(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "reviewer-selected")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "proposer-selected")
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "fallback-selected")

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=True))
    calls: list[str] = []

    def invoke(deployment: str) -> V2AssistantModelResult:
        calls.append(deployment)
        return V2AssistantModelResult(
            content='{"decision":"accept","reasoning":"ok","missing_evidence":[],"unsafe_assumptions":[]}',
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role="reviewer",
            success=True,
            redacted_summary="ok",
            failure_reason="",
        )

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.REVIEWER,
            prompt="review",
            fallback="fallback",
            output_schema_name="ReviewerCritique",
            require_schema=True,
        ),
        invoke=invoke,
    )

    assert calls == ["reviewer-selected"]
    assert result.success is True
    assert result.fallback_used is False


def test_router_reports_missing_reviewer_deployment_as_reviewer_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", raising=False)

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=False))
    calls: list[str] = []

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.REVIEWER,
            prompt="review",
            fallback="fallback",
            output_schema_name="RepairReviewerOutput",
            require_schema=True,
        ),
        invoke=lambda deployment: calls.append(deployment),
    )

    assert calls == []
    assert result.success is False
    assert result.failure_reason == "reviewer_model_unavailable"
    assert result.primary_failure_reason == "reviewer_model_unavailable"


def test_router_does_not_use_fallback_deployment_for_reviewer(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "fallback-selected")

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=True))
    calls: list[str] = []

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.REVIEWER,
            prompt="review",
            fallback="fallback",
            output_schema_name="RepairReviewerOutput",
            require_schema=True,
        ),
        invoke=lambda deployment: calls.append(deployment),
    )

    assert calls == []
    assert result.success is False
    assert result.failure_reason == "reviewer_model_unavailable"
    assert result.fallback_used is False


def test_router_reports_reviewer_schema_invalid(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "reviewer-selected")

    router = V2ModelRoleRouter()

    def invoke(_: str) -> V2AssistantModelResult:
        return V2AssistantModelResult(
            content='{"decision":"accept"}',
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role="reviewer",
            success=True,
            redacted_summary="schema mismatch",
            failure_reason="",
        )

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.REVIEWER,
            prompt="review",
            fallback="fallback",
            output_schema_name="RepairReviewerOutput",
            require_schema=True,
        ),
        invoke=invoke,
    )

    assert result.success is False
    assert result.failure_reason == "reviewer_schema_invalid"
    assert result.primary_failure_reason == "reviewer_schema_invalid"


def test_router_reports_reviewer_model_failed_on_call_exception(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "reviewer-deployment")
    monkeypatch.setenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "fallback-deployment")

    router = V2ModelRoleRouter(ControlTowerSettings(azure_foundry_fallback_enabled=True))

    def invoke(_: str) -> V2AssistantModelResult:
        msg = "reviewer_model_failed"
        raise RuntimeError(msg)

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.REVIEWER,
            prompt="review",
            fallback="fallback",
            output_schema_name="RepairReviewerOutput",
            require_schema=True,
        ),
        invoke=invoke,
    )

    assert result.success is False
    assert result.failure_reason == "reviewer_model_failed"
    assert result.primary_failure_reason == "reviewer_model_failed"


def test_router_translates_generic_http_failure_to_reviewer_model_failed(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "reviewer-deployment")

    router = V2ModelRoleRouter()

    def invoke(_: str) -> V2AssistantModelResult:
        return V2AssistantModelResult(
            content="",
            source="azure_openai",
            model_status="fallback",
            provider="azure_openai",
            role="reviewer",
            success=False,
            redacted_summary="HTTP 400 error",
            failure_reason="http_400",
        )

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.REVIEWER,
            prompt="review",
            fallback="fallback",
            output_schema_name="RepairReviewerOutput",
            require_schema=True,
        ),
        invoke=invoke,
    )

    assert result.success is False
    assert result.failure_reason == "reviewer_model_failed"
    assert result.primary_failure_reason == "reviewer_model_failed"


def test_router_fail_closes_on_schema_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "assistant-deployment")

    router = V2ModelRoleRouter()

    def invoke(_: str) -> V2AssistantModelResult:
        return V2AssistantModelResult(
            content="not json",
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role="assistant",
            success=True,
            redacted_summary="not json",
            failure_reason="",
        )

    result = router.route(
        V2RoleModelRequest(
            role=V2ModelRole.ASSISTANT,
            prompt="status?",
            fallback="fallback answer",
            output_schema_name="AssistantAnswer",
            require_schema=True,
        ),
        invoke=invoke,
    )

    assert result.success is False
    assert result.model_status == "fallback"
    assert result.schema_validated is True
    assert result.content.startswith("{")
    assert "fallback answer" in result.content


def test_client_answer_with_role_uses_requested_role_deployment(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "proposer-deployment")

    deployments: list[str] = []

    def fake_chat_completion(*, deployment: str, **_: object) -> str:
        deployments.append(deployment)
        return "proposer draft"

    client = V2AssistantModelClient()
    monkeypatch.setattr(client, "_chat_completion", fake_chat_completion)

    result = client.answer_with_role(
        role=V2ModelRole.PROPOSER,
        prompt="Draft a proposal",
        fallback="fallback",
    )

    assert deployments == ["proposer-deployment"]
    assert result.success is True
    assert result.role == "proposer"
    assert result.content == "proposer draft"


def test_answer_delegates_to_assistant_role(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_answer_with_role(*, role, prompt, fallback, conversation_history=None, output_schema_name=None, require_schema=False):
        seen["role"] = role.value
        seen["prompt"] = prompt
        seen["fallback"] = fallback
        return V2AssistantModelResult(
            content="ok",
            source="deterministic",
            model_status="fallback",
            provider="deterministic",
            role=role.value,
            success=False,
            redacted_summary="ok",
            failure_reason="",
        )

    client = V2AssistantModelClient()
    monkeypatch.setattr(client, "answer_with_role", fake_answer_with_role)

    result = client.answer(prompt="status?", fallback="fallback")

    assert seen["role"] == "assistant"
    assert seen["prompt"] == "status?"
    assert seen["fallback"] == "fallback"
    assert result.role == "assistant"


# ── Schema diagnostic tests ───────────────────────────────────────────


def test_parse_invalid_json_detects_invalid_json() -> None:
    parsed, category = _parse_model_json_safe("not json at all")
    assert parsed is None
    assert category == "invalid_json"


def test_parse_markdown_wrapped_json_detects_markdown() -> None:
    content = '```json\n{"root_cause": "test"}\n```'
    parsed, category = _parse_model_json_safe(content)
    assert parsed is not None
    assert category == "markdown_wrapped_json"


def test_parse_truncated_output_detects_truncation() -> None:
    content = '{"root_cause": "test", "fix_strategy": "fix...'
    parsed, category = _parse_model_json_safe(content)
    assert parsed is None
    assert category == "truncated_output"


def test_schema_diagnostics_include_parse_failure_category() -> None:
    router = V2ModelRoleRouter()
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    diag = router._schema_diagnostics(request, "not json")
    assert diag["schema_validated"] is False
    assert diag["parse_failure_category"] in ("invalid_json",)
    assert diag["reason_code"] == "proposer_schema_invalid"


def test_schema_diagnostics_missing_required_fields() -> None:
    router = V2ModelRoleRouter()
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    data = json.dumps({"root_cause": "test"})
    diag = router._schema_diagnostics(request, data)
    assert diag["schema_validated"] is False
    assert "missing_fields" in diag
    missing = set(diag["missing_fields"])
    assert "proposed_diff" in missing or "fix_strategy" in missing or "changed_files" in missing or "risk" in missing or "confidence" in missing or "rationale" in missing


def test_schema_diagnostics_wrong_field_type() -> None:
    router = V2ModelRoleRouter()
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    data = json.dumps({
        "root_cause": "test", "fix_strategy": "fix", "changed_files": ["file1"],
        "proposed_diff": "diff", "risk": "LOW", "confidence": "not-a-number", "rationale": "reason",
    })
    diag = router._schema_diagnostics(request, data)
    assert diag["schema_validated"] is False
    assert "wrong_field_types" in diag
    assert any("confidence" in wt for wt in diag["wrong_field_types"])


def test_schema_diagnostics_include_output_checksum() -> None:
    router = V2ModelRoleRouter()
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    diag = router._schema_diagnostics(request, '{"root_cause": "test"}')
    assert "output_checksum" in diag
    assert len(diag["output_checksum"]) > 0


def test_schema_diagnostics_include_response_format_requested() -> None:
    router = V2ModelRoleRouter()
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    diag = router._schema_diagnostics(request, '{}')
    assert diag.get("response_format_requested") is True


def test_route_returns_schema_diagnostics_on_schema_failure() -> None:
    router = V2ModelRoleRouter()
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)

    def invoke(deployment: str) -> V2AssistantModelResult:
        return V2AssistantModelResult(
            content='{"root_cause": "test"}',
            source="azure_openai", model_status="live_ok", provider="azure_openai",
            role="proposer", success=True, redacted_summary="", failure_reason="",
        )

    result = router.route(request, invoke=invoke)
    assert result.success is False
    assert result.schema_diagnostics is not None
    assert result.schema_diagnostics.get("schema_validated") is False
    assert "missing_fields" in result.schema_diagnostics


def test_route_does_not_invoke_reviewer_when_primary_schema_invalid() -> None:
    router = V2ModelRoleRouter()
    reviewer_called: list[str] = []
    request = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)

    def invoke(deployment: str) -> V2AssistantModelResult:
        return V2AssistantModelResult(
            content='{"root_cause": "test"}',
            source="azure_openai_success", model_status="live_ok", provider="azure_openai",
            role="proposer", success=True, redacted_summary="", failure_reason="",
        )

    result = router.route(request, invoke=invoke)
    assert result.success is False
    assert result.schema_validated is False


def test_classify_diff_failure_missing_git_header() -> None:
    diff = "--- a/file.java\n+++ b/file.java\n@@ -1 +1 @@\n-old\n+new\n"
    assert _classify_diff_failure(diff) == "missing_diff_git_header"


def test_classify_diff_failure_missing_hunk() -> None:
    diff = "diff --git a/file.java b/file.java\n--- a/file.java\n+++ b/file.java\n-old\n+new\n"
    assert _classify_diff_failure(diff) == "missing_hunk"


def test_classify_diff_failure_invalid_diff() -> None:
    diff = "diff --git a/file.java b/file.java\n@@ -1 +1 @@\n-old\n+new\n"
    assert _classify_diff_failure(diff) == "invalid_diff"


def test_classify_diff_failure_valid() -> None:
    diff = "diff --git a/file.java b/file.java\n--- a/file.java\n+++ b/file.java\n@@ -1 +1 @@\n-old\n+new\n"
    assert _classify_diff_failure(diff) == ""


def test_build_diagnostic_summary_from_diag_invalid_json() -> None:
    summary = _build_diagnostic_summary_from_diag({"parse_failure_category": "invalid_json"})
    assert "invalid JSON" in summary


def test_build_diagnostic_summary_from_diag_missing_fields() -> None:
    summary = _build_diagnostic_summary_from_diag({"missing_fields": ["proposed_diff", "confidence"]})
    assert "missing required fields" in summary


def test_build_diagnostic_summary_from_diag_wrong_types() -> None:
    summary = _build_diagnostic_summary_from_diag({"wrong_field_types": ["confidence (expected number, got string)"]})
    assert "wrong field types" in summary


def test_build_diagnostic_summary_from_diag_azure_rejected() -> None:
    summary = _build_diagnostic_summary_from_diag({"response_format_used": False})
    assert "Azure rejected response_format" in summary


def test_build_schema_failure_summary_missing_diff_git_header() -> None:
    from migration_factory.control_tower.application.v2_model_role_router import V2RoleModelRequest
    req = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    content = json.dumps({
        "root_cause": "test", "fix_strategy": "fix", "changed_files": ["x"],
        "proposed_diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n",
        "risk": "LOW", "confidence": 0.9, "rationale": "r",
    })
    summary = _build_schema_failure_summary(req, content)
    assert "diff --git" in summary


def test_build_schema_failure_summary_missing_hunk() -> None:
    from migration_factory.control_tower.application.v2_model_role_router import V2RoleModelRequest
    req = V2RoleModelRequest(role=V2ModelRole.PROPOSER, prompt="test", fallback="fallback", output_schema_name="RepairPrimaryOutput", require_schema=True)
    content = json.dumps({
        "root_cause": "test", "fix_strategy": "fix", "changed_files": ["x"],
        "proposed_diff": "diff --git a/x b/x\n--- a/x\n+++ b/x\n-old\n+new\n",
        "risk": "LOW", "confidence": 0.9, "rationale": "r",
    })
    summary = _build_schema_failure_summary(req, content)
    assert "@@ hunk" in summary
