from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork


@dataclass(frozen=True)
class _FakeAzureResult:
    content: str
    role: str
    deployment: str
    provider: str = "azure_openai"
    source: str = "azure_openai"
    model_status: str = "live_ok"
    success: bool = True
    redacted_summary: str = "ok"
    failure_reason: str = ""
    primary_failure_reason: str = ""
    fallback_used: bool = False
    schema_validated: bool = False
    endpoint_metadata: str = "endpoint_host=[redacted-endpoint]"


class _FakeAzureRoleClient:
    provider = "azure_openai"
    endpoint_metadata = "endpoint_host=[redacted-endpoint]"

    def __init__(self, *, invalid_reviewer: bool = False) -> None:
        self.invalid_reviewer = invalid_reviewer
        self.calls: list[dict[str, str]] = []

    def answer_with_role(self, *, role: Any, prompt: str, fallback: str, **_: Any) -> _FakeAzureResult:
        role_value = getattr(role, "value", str(role))
        deployment = {
            "proposer": "gpt5-mini",
            "reviewer": "Llama-3.3-70B-Instruct",
            "fallback": "Mistral-Large-3",
        }[role_value]
        self.calls.append({"role": role_value, "deployment": deployment, "prompt": prompt, "fallback": fallback})
        if role_value == V2ModelRole.REVIEWER.value and self.invalid_reviewer:
            return _FakeAzureResult(
                content="not json",
                role=role_value,
                deployment=deployment,
                failure_reason="invalid_json_model_output",
            )
        if role_value == V2ModelRole.FALLBACK.value:
            return _FakeAzureResult(
                content=json.dumps({
                    "status": "available",
                    "role": "repair_fallback",
                    "verdict": "advisory_needs_changes",
                    "critique": "Fallback model saw reviewer schema failure.",
                    "risks": ["backend gate still required"],
                    "missing_evidence": [],
                    "unsafe_assumptions": [],
                    "recommended_next_action": "use_deterministic_backend_gate",
                    "confidence": "low",
                    "apply_allowed": True,
                    "approval_allowed": True,
                    "downstream_start_allowed": True,
                }),
                role=role_value,
                deployment=deployment,
            )
        if role_value == V2ModelRole.REVIEWER.value:
            return _FakeAzureResult(
                content=json.dumps({
                    "status": "available",
                    "role": "repair_reviewer",
                    "verdict": "advisory_accept",
                    "critique": "Shadow reviewer accepts for future gate only.",
                    "risks": ["backend gate still required"],
                    "missing_evidence": [],
                    "unsafe_assumptions": [],
                    "recommended_next_action": "keep_non_actionable",
                    "confidence": "medium",
                    "apply_allowed": True,
                    "approval_allowed": True,
                    "downstream_start_allowed": True,
                }),
                role=role_value,
                deployment=deployment,
            )
        return _FakeAzureResult(
            content=json.dumps({
                "status": "available",
                "role": "repair_proposer",
                "summary": "initMocks can move to openMocks.",
                "root_cause": "legacy Mockito init",
                "repair_intent": "replace initMocks with openMocks",
                "expected_change": "one test-local replacement",
                "affected_files": ["src/test/java/ExampleTest.java"],
                "risk_notes": ["future backend gate required"],
                "missing_evidence": [],
                "confidence": "medium",
                "apply_allowed": True,
                "approval_allowed": True,
                "downstream_start_allowed": True,
            }),
            role=role_value,
            deployment=deployment,
        )


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "shadow-runtime.sqlite3"), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _diagnose_initmocks(app: Any, tmp_path: Path) -> dict[str, Any]:
    sandbox = tmp_path / "sandbox"
    test_file = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("MockitoAnnotations.initMocks(this);\n", encoding="utf-8")
    diagnosis = app.state.v2_failure_diagnosis_service.diagnose(
        job_id="job-shadow-runtime",
        stage_index=2,
        command_id="cmd-shadow-runtime",
        event_type="build_failed",
        payload={
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(sandbox),
            "message": "MockitoAnnotations.initMocks(this);",
            "artifact_refs": {"sandbox": str(sandbox), "test_source": str(test_file)},
        },
    )
    assert diagnosis.classification_envelope is not None
    return diagnosis.classification_envelope["llm_repair_shadow_trace"]


def test_runtime_app_wires_existing_model_client_when_shadow_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("V2_LLM_REPAIR_SHADOW_ENABLED", "true")
    conn = _conn(tmp_path)
    fake_client = _FakeAzureRoleClient()
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=fake_client)

    trace = _diagnose_initmocks(app, tmp_path)

    assert trace["runtime_mode"] == "configured_llm_shadow_mode"
    assert [call["role"] for call in fake_client.calls] == ["proposer", "reviewer"]
    assert trace["proposer_trace"]["model_metadata"]["role"] == "repair_proposer_model"
    assert trace["reviewer_trace"]["model_metadata"]["role"] == "repair_reviewer_model"
    assert trace["proposer_trace"]["model_metadata"]["expected_model"] == "gpt5-mini"
    assert trace["reviewer_trace"]["model_metadata"]["expected_model"] == "Llama-3.3-70B-Instruct"
    assert trace["proposer_trace"]["model_metadata"]["deployment"] == "gpt5-mini"
    assert trace["reviewer_trace"]["model_metadata"]["deployment"] == "Llama-3.3-70B-Instruct"
    assert trace["llm_fallback_trace"]["model_metadata"]["expected_model"] == "Mistral-Large-3"
    assert trace["fallback_trace"]["deterministic_gate_authority"] is True
    assert trace["llm_can_apply"] is False


def test_runtime_fallback_role_invoked_on_invalid_reviewer(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("V2_LLM_REPAIR_SHADOW_ENABLED", "true")
    conn = _conn(tmp_path)
    fake_client = _FakeAzureRoleClient(invalid_reviewer=True)
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=fake_client)

    trace = _diagnose_initmocks(app, tmp_path)

    assert [call["role"] for call in fake_client.calls] == ["proposer", "reviewer", "fallback"]
    fallback = trace["llm_fallback_trace"]
    assert fallback["llm_invoked"] is True
    assert fallback["model_metadata"]["role"] == "repair_fallback_model"
    assert fallback["model_metadata"]["deployment"] == "Mistral-Large-3"
    assert fallback["failure_reason"] == ""
    assert "reviewer" in fallback["input_preview"]
    assert fallback["output"]["apply_allowed"] is False
    assert fallback["output"]["approval_allowed"] is False
    assert fallback["output"]["downstream_start_allowed"] is False
    assert trace["fallback_trace"]["deterministic_gate_authority"] is True


def test_runtime_disabled_shadow_uses_fallback_only_and_no_live_call(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CONTROL_TOWER_LLM_REPAIR_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("V2_LLM_REPAIR_SHADOW_ENABLED", raising=False)
    conn = _conn(tmp_path)
    fake_client = _FakeAzureRoleClient()
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=fake_client)

    trace = _diagnose_initmocks(app, tmp_path)

    assert trace["runtime_mode"] == "fallback_only_mode"
    assert fake_client.calls == []
    assert trace["proposer_trace"]["fallback_used"] is True
    assert trace["reviewer_trace"]["fallback_used"] is True
    assert trace["llm_fallback_trace"]["fallback_used"] is True
    assert trace["fallback_trace"]["deterministic_gate_authority"] is True
