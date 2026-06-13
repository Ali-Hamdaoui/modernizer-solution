"""V2 structured output schemas and context pack builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.application.redaction import (
    redact_absolute_paths,
)


REQUIRED_SCHEMAS = (
    "PlanProposal",
    "RepairProposal",
    "ReviewerCritique",
    "ActionRequest",
    "AssistantAnswer",
)

TOKEN_BUDGETS = {
    "plan_proposal": {"input": 24000, "output": 6000},
    "plan_revision": {"input": 18000, "output": 5000},
    "repair_proposal": {"input": 20000, "output": 6000},
    "reviewer_critique": {"input": 16000, "output": 4000},
    "assistant_answer": {"input": 8000, "output": 2000},
    "action_request": {"input": 6000, "output": 1500},
}


# ── Structured output schemas (strict) ──────────────────────────────

PLAN_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "stage_impacts", "risks", "approval_checksum"],
    "properties": {
        "summary": {"type": "string"},
        "stage_impacts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["stage_index", "impact"],
                "properties": {
                    "stage_index": {"type": "integer", "minimum": 1, "maximum": 3},
                    "impact": {"type": "string"},
                },
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "approval_checksum": {"type": "string"},
    },
}

REPAIR_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["failure_hypothesis", "patch_summary", "affected_paths", "validation_plan"],
    "properties": {
        "failure_hypothesis": {"type": "string"},
        "patch_summary": {"type": "string"},
        "affected_paths": {"type": "array", "items": {"type": "string"}},
        "validation_plan": {"type": "string"},
        "rollback_note": {"type": "string"},
    },
}

REVIEWER_CRITIQUE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "reasoning"],
    "properties": {
        "decision": {"type": "string", "enum": ["accept", "revise", "reject"]},
        "reasoning": {"type": "string"},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "unsafe_assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

ACTION_REQUEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action_type", "reason", "stage_index", "payload_checksum"],
    "properties": {
        "action_type": {"type": "string"},
        "reason": {"type": "string"},
        "stage_index": {"type": "integer", "minimum": 1, "maximum": 3},
        "payload_checksum": {"type": "string"},
    },
}

ASSISTANT_ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {
        "answer": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "follow_up_action": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action_type": {"type": "string"},
                "reason": {"type": "string"},
            },
        },
    },
}

SCHEMA_REGISTRY = {
    "PlanProposal": PLAN_PROPOSAL_SCHEMA,
    "RepairProposal": REPAIR_PROPOSAL_SCHEMA,
    "ReviewerCritique": REVIEWER_CRITIQUE_SCHEMA,
    "ActionRequest": ACTION_REQUEST_SCHEMA,
    "AssistantAnswer": ASSISTANT_ANSWER_SCHEMA,
}


# ── Schema validation ────────────────────────────────────────────────


class SchemaValidationError(Exception):
    """Raised when data does not match the expected schema."""


class SchemaValidator:
    """Lightweight JSON Schema validator for V2 model schemas.

    Validates data against the registered schemas without requiring
    an external jsonschema library. Covers the subset of JSON Schema
    used by the V2 structured output schemas.
    """

    @staticmethod
    def validate(schema_name: str, data: Any) -> None:
        """Validate data against the named schema.

        Args:
            schema_name: One of the REQUIRED_SCHEMAS names.
            data: The data dict to validate.

        Raises:
            SchemaValidationError: If validation fails.
            ValueError: If schema_name is unknown.
        """
        schema = SCHEMA_REGISTRY.get(schema_name)
        if schema is None:
            raise ValueError(f"Unknown schema: {schema_name!r}")

        SchemaValidator._validate_value(data, schema, [schema_name])

    @staticmethod
    def _validate_value(value: Any, schema: dict[str, Any], path: list[str]) -> None:
        """Validate a single value against a schema fragment."""
        if not isinstance(schema, dict):
            return

        schema_type = schema.get("type")

        # Check additionalProperties
        if schema.get("additionalProperties") is False and isinstance(value, dict):
            allowed = set(schema.get("properties", {}).keys())
            for key in value:
                if key not in allowed:
                    raise SchemaValidationError(
                        f"Unexpected property {'.'.join(path + [key])!r}. "
                        f"Allowed: {sorted(allowed)}"
                    )

        # Check type constraints
        if schema_type == "object" and not isinstance(value, dict):
            raise SchemaValidationError(
                f"Expected object at {'.'.join(path)!r}, got {type(value).__name__}"
            )
        if schema_type == "array" and not isinstance(value, (list, tuple)):
            raise SchemaValidationError(
                f"Expected array at {'.'.join(path)!r}, got {type(value).__name__}"
            )
        if schema_type == "string" and not isinstance(value, str):
            raise SchemaValidationError(
                f"Expected string at {'.'.join(path)!r}, got {type(value).__name__}"
            )
        if schema_type == "integer" and not isinstance(value, int):
            raise SchemaValidationError(
                f"Expected integer at {'.'.join(path)!r}, got {type(value).__name__}"
            )

        # Check required fields
        if schema_type == "object" and isinstance(value, dict):
            required = schema.get("required", [])
            for field in required:
                if field not in value:
                    raise SchemaValidationError(
                        f"Missing required field {'.'.join(path + [field])!r}"
                    )

        # Check enum constraint
        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            raise SchemaValidationError(
                f"Value {value!r} at {'.'.join(path)!r} is not one of {enum_values}"
            )

        # Check numeric constraints
        if isinstance(value, (int, float)):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                raise SchemaValidationError(
                    f"Value {value} at {'.'.join(path)!r} is less than minimum {minimum}"
                )
            if maximum is not None and value > maximum:
                raise SchemaValidationError(
                    f"Value {value} at {'.'.join(path)!r} is greater than maximum {maximum}"
                )

        # Check array items
        if schema_type == "array" and isinstance(value, (list, tuple)):
            items_schema = schema.get("items")
            if items_schema:
                for i, item in enumerate(value):
                    SchemaValidator._validate_value(
                        item, items_schema, path + [str(i)]
                    )

        # Check property values
        if schema_type == "object" and isinstance(value, dict):
            properties = schema.get("properties", {})
            for key, prop_schema in properties.items():
                if key in value:
                    SchemaValidator._validate_value(
                        value[key], prop_schema, path + [key]
                    )


# ── Context pack ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContextPack:
    pack_id: str
    pack_type: str
    title: str
    description: str
    evidence_refs: tuple[str, ...]
    token_budget_input: int
    token_budget_output: int
    checksum: str
    created_at: str


class ContextPackBuilder:
    """Build bounded context packs for model calls."""

    @staticmethod
    def build_context_pack(
        pack_type: str,
        title: str,
        description: str,
        evidence_refs: tuple[str, ...],
    ) -> ContextPack:
        budgets = TOKEN_BUDGETS.get(pack_type, {"input": 8000, "output": 2000})
        now = utc_now_text()
        pack_id = uuid4().hex

        return ContextPack(
            pack_id=pack_id,
            pack_type=pack_type,
            title=title,
            description=description,
            evidence_refs=evidence_refs,
            token_budget_input=budgets["input"],
            token_budget_output=budgets["output"],
            checksum=f"cp-{pack_id[:8]}",
            created_at=now,
        )

    @staticmethod
    def pack_to_dict(pack: ContextPack) -> dict[str, Any]:
        return {
            "pack_id": pack.pack_id,
            "pack_type": pack.pack_type,
            "title": pack.title,
            "description": redact_absolute_paths(pack.description),
            "evidence_refs": list(pack.evidence_refs),
            "token_budget_input": pack.token_budget_input,
            "token_budget_output": pack.token_budget_output,
            "checksum": pack.checksum,
            "created_at": pack.created_at,
        }

    @staticmethod
    def schema_to_dict(schema_name: str) -> dict[str, Any] | None:
        schema = SCHEMA_REGISTRY.get(schema_name)
        if schema is None:
            return None
        return {
            "schema_name": schema_name,
            "schema": schema,
            "checksum": f"schema-{schema_name.lower()}",
        }
