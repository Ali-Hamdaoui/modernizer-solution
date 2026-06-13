"""Tests for V2 structured output schemas and context packs."""

import json
import pytest

from migration_factory.control_tower.application.v2_model_schemas import (
    SCHEMA_REGISTRY,
    REQUIRED_SCHEMAS,
    TOKEN_BUDGETS,
    PLAN_PROPOSAL_SCHEMA,
    REPAIR_PROPOSAL_SCHEMA,
    REVIEWER_CRITIQUE_SCHEMA,
    ACTION_REQUEST_SCHEMA,
    ASSISTANT_ANSWER_SCHEMA,
    ContextPackBuilder,
)


def test_all_required_schemas_exist() -> None:
    for name in REQUIRED_SCHEMAS:
        assert name in SCHEMA_REGISTRY, f"Missing schema: {name}"


def test_schemas_have_additional_properties_false() -> None:
    for name, schema in SCHEMA_REGISTRY.items():
        assert schema.get("additionalProperties") is False, f"{name} allows extra properties"
        assert "required" in schema, f"{name} missing required fields"
        assert "properties" in schema, f"{name} missing properties"


def test_plan_proposal_schema() -> None:
    s = PLAN_PROPOSAL_SCHEMA
    assert "summary" in s["required"]
    assert "approval_checksum" in s["required"]
    assert "stage_impacts" in s["properties"]
    assert "risks" in s["properties"]


def test_repair_proposal_schema() -> None:
    s = REPAIR_PROPOSAL_SCHEMA
    assert "failure_hypothesis" in s["required"]
    assert "patch_summary" in s["required"]
    assert "affected_paths" in s["required"]


def test_reviewer_critique_schema() -> None:
    s = REVIEWER_CRITIQUE_SCHEMA
    assert s["properties"]["decision"]["enum"] == ["accept", "revise", "reject"]
    assert "reasoning" in s["required"]


def test_action_request_schema() -> None:
    s = ACTION_REQUEST_SCHEMA
    assert "action_type" in s["required"]
    assert "payload_checksum" in s["required"]
    assert s["properties"]["stage_index"]["minimum"] == 1
    assert s["properties"]["stage_index"]["maximum"] == 3


def test_assistant_answer_schema() -> None:
    s = ASSISTANT_ANSWER_SCHEMA
    assert "answer" in s["required"]
    assert "evidence_refs" in s["properties"]
    assert "follow_up_action" in s["properties"]


def test_context_pack_builder() -> None:
    pack = ContextPackBuilder.build_context_pack(
        pack_type="plan_proposal",
        title="Stage 1 plan",
        description="Plan for stage 1 with paths",
        evidence_refs=("/tmp/evidence/log.txt",),
    )
    assert pack.pack_id
    assert pack.pack_type == "plan_proposal"
    assert pack.token_budget_input == 24000
    assert pack.token_budget_output == 6000


def test_context_pack_to_dict_redacts_paths() -> None:
    pack = ContextPackBuilder.build_context_pack(
        pack_type="repair_proposal",
        title="Repair",
        description="Path: /home/user/secret/file.txt",
        evidence_refs=("/tmp/test.txt",),
    )
    d = ContextPackBuilder.pack_to_dict(pack)
    assert "redacted" in d["description"] or "/home/user" not in d["description"]


def test_schema_to_dict() -> None:
    result = ContextPackBuilder.schema_to_dict("PlanProposal")
    assert result is not None
    assert result["schema_name"] == "PlanProposal"
    assert "schema" in result


def test_schema_to_dict_unknown() -> None:
    assert ContextPackBuilder.schema_to_dict("UnknownSchema") is None


def test_token_budgets_defined() -> None:
    assert "plan_proposal" in TOKEN_BUDGETS
    assert "repair_proposal" in TOKEN_BUDGETS
    assert "reviewer_critique" in TOKEN_BUDGETS
    assert "action_request" in TOKEN_BUDGETS
    assert "assistant_answer" in TOKEN_BUDGETS
