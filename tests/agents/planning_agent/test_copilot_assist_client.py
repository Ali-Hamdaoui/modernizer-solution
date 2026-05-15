from migration_factory.agents.planning_agent.assist_config import PlanningAssistConfig
from migration_factory.agents.planning_agent.copilot_assist_client import (
    CopilotPlanningAssistClient,
)
from migration_factory.contracts.planning_assist import PlanningAssistRequest


def _request() -> PlanningAssistRequest:
    return PlanningAssistRequest(
        run_id="r1",
        agent="planning-agent",
        phase="planning",
        model="gpt-test",
        prompt="review plan",
        context={"migration_units": []},
    )


def test_review_plan_returns_failed_when_adapter_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("MF_PLANNING_ASSIST_AUTH_MODE", raising=False)
    client = CopilotPlanningAssistClient()

    result = client.review_plan(
        request=_request(),
        config=PlanningAssistConfig(enabled=True),
    )

    assert result.status == "FAILED"
    assert (
        result.error
        == "adapter_unavailable: Planning assist provider adapter is not configured."
    )
    assert result.warnings


def test_review_plan_normalizes_provider_exception_to_failed(monkeypatch) -> None:
    monkeypatch.delenv("MF_PLANNING_ASSIST_AUTH_MODE", raising=False)

    class RaisingClient(CopilotPlanningAssistClient):
        def _perform_provider_review(self, request, config):
            raise TimeoutError("request timeout")

    client = RaisingClient()
    result = client.review_plan(
        request=_request(),
        config=PlanningAssistConfig(enabled=True),
    )

    assert result.status == "FAILED"
    assert result.error == "Planning assist timeout."
    assert result.warnings


def test_review_plan_rejects_non_object_payload_as_controlled_failed(monkeypatch) -> None:
    monkeypatch.delenv("MF_PLANNING_ASSIST_AUTH_MODE", raising=False)

    class InvalidPayloadClient(CopilotPlanningAssistClient):
        def _perform_provider_review(self, request, config):
            return "not-json-object"

    client = InvalidPayloadClient()
    result = client.review_plan(
        request=_request(),
        config=PlanningAssistConfig(enabled=True),
    )

    assert result.status == "FAILED"
    assert result.error == "Planning assist invalid JSON/non-object payload."
