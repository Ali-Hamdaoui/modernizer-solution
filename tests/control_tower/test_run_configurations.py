from __future__ import annotations

import pytest
from pydantic import ValidationError

from migration_factory.control_tower.schemas.run_configuration import RunConfiguration


def _run_configuration_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "run_configuration_id": "run-config-default",
        "job_id": "job-123",
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "pipeline_id": "pipeline-default",
        "pipeline_version": "2026.06",
        "target_proof_level": "BUILD_TEST_VERIFIED",
        "enabled_gates": ("build", "test"),
        "policy": {
            "continue_after_warning": False,
            "enable_runtime_gate": True,
            "enable_endpoint_gate": False,
            "allow_ai_assistance": True,
            "allow_ai_repair": False,
        },
    }


def test_valid_run_configuration() -> None:
    configuration = RunConfiguration.model_validate(_run_configuration_payload())

    assert configuration.job_id == "job-123"
    assert configuration.target_proof_level == "BUILD_TEST_VERIFIED"


def test_unknown_field_rejected() -> None:
    payload = _run_configuration_payload()
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        RunConfiguration.model_validate(payload)


def test_run_configuration_is_immutable() -> None:
    configuration = RunConfiguration.model_validate(_run_configuration_payload())

    with pytest.raises(ValidationError):
        configuration.job_id = "job-456"


def test_run_policy_is_immutable() -> None:
    configuration = RunConfiguration.model_validate(_run_configuration_payload())

    with pytest.raises(ValidationError):
        configuration.policy.allow_ai_repair = True


def test_strict_booleans_reject_string_values() -> None:
    payload = _run_configuration_payload()
    payload["policy"]["allow_ai_assistance"] = "true"

    with pytest.raises(ValidationError):
        RunConfiguration.model_validate(payload)


def test_invalid_target_proof_level_rejected() -> None:
    payload = _run_configuration_payload()
    payload["target_proof_level"] = "INVALID"

    with pytest.raises(ValidationError):
        RunConfiguration.model_validate(payload)


def test_production_ready_rejected() -> None:
    payload = _run_configuration_payload()
    payload["target_proof_level"] = "PRODUCTION_READY"

    with pytest.raises(ValidationError):
        RunConfiguration.model_validate(payload)


def test_enabled_gates_collection_is_immutable() -> None:
    configuration = RunConfiguration.model_validate(_run_configuration_payload())

    with pytest.raises(AttributeError):
        configuration.enabled_gates.append("runtime")


@pytest.mark.parametrize(
    "field",
    [
        "runner_profile_id",
        "runner_profile_version",
        "pipeline_id",
        "pipeline_version",
    ],
)
def test_runner_and_pipeline_references_are_required(field: str) -> None:
    payload = _run_configuration_payload()
    payload.pop(field)

    with pytest.raises(ValidationError):
        RunConfiguration.model_validate(payload)


def test_job_id_is_required() -> None:
    payload = _run_configuration_payload()
    payload.pop("job_id")

    with pytest.raises(ValidationError):
        RunConfiguration.model_validate(payload)
