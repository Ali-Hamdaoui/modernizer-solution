from migration_factory.agents.planning_agent.assist_config import PlanningAssistConfig
from migration_factory.contracts.planning_assist import (
    PlanningAssistRequest,
    PlanningAssistResult,
)


class CopilotPlanningAssistClient:
    """Provider-neutral planning assist interface. No external SDK calls yet."""

    _FAILURE_REASON_WARNING_PREFIX = "[WARNING] Planning assist failed-open:"

    def _build_failed_result(self, reason: str) -> PlanningAssistResult:
        return PlanningAssistResult(
            status="FAILED",
            warnings=[f"{self._FAILURE_REASON_WARNING_PREFIX} {reason}"],
            error=reason,
        )

    def _normalize_failure_reason(self, error: Exception) -> str:
        message = str(error).strip()
        lowered = message.lower()
        if isinstance(error, TimeoutError) or "timeout" in lowered:
            return "Planning assist timeout."
        if "missing auth" in lowered or "auth missing" in lowered:
            return "Planning assist missing authentication."
        if "invalid token" in lowered or "bad credentials" in lowered:
            return "Planning assist invalid token."
        if "entitlement" in lowered:
            return "Planning assist entitlement error."
        if "model unavailable" in lowered or "model not found" in lowered:
            return "Planning assist model unavailable."
        if "invalid output" in lowered:
            return "Planning assist invalid output."
        return "Planning assist runtime error."

    def _perform_provider_review(
        self, request: PlanningAssistRequest, config: PlanningAssistConfig
    ) -> PlanningAssistResult:
        raise RuntimeError(
            "Planning assist provider not bound. "
            "No SDK/MCP adapter configured yet."
        )

    def _validate_output(self, result: PlanningAssistResult) -> PlanningAssistResult:
        if result.status == "SKIPPED":
            return result
        if result.status != "USED":
            return self._build_failed_result("Planning assist invalid output.")
        return result

    def review_plan(
        self, request: PlanningAssistRequest, config: PlanningAssistConfig
    ) -> PlanningAssistResult:
        if not config.enabled:
            return PlanningAssistResult(
                status="SKIPPED",
                warnings=["Planning assist disabled by config."],
            )
        try:
            raw_result = self._perform_provider_review(request=request, config=config)
            return self._validate_output(raw_result)
        except Exception as error:
            return self._build_failed_result(self._normalize_failure_reason(error))
