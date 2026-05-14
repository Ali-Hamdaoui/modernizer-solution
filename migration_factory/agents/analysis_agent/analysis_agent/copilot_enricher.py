import os
import json
import datetime
import copy


class CopilotConfigError(Exception):
    """Raised when Copilot configuration invalid."""


class CopilotAuthResolver:
    SUPPORTED_AUTH_MODES = {"github_signed_in_user", "oauth_github_app"}

    @staticmethod
    def resolve_auth_mode():
        mode = os.environ.get("AIMF_COPILOT_AUTH_MODE", "github_signed_in_user").strip()
        if mode not in CopilotAuthResolver.SUPPORTED_AUTH_MODES:
            raise CopilotConfigError(f"Unsupported auth mode: {mode}")
        return mode

    @staticmethod
    def get_token(auth_mode):
        if auth_mode == "github_signed_in_user":
            token = os.environ.get("GITHUB_COPILOT_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not token:
                raise PermissionError("Auth Resolver : github_signed_in_user token missing.")
            return token

        if auth_mode == "oauth_github_app":
            token = os.environ.get("AIMF_GITHUB_APP_OAUTH_TOKEN", "").strip()
            if not token:
                raise PermissionError("Auth Resolver : oauth_github_app token missing.")
            return token

        raise CopilotConfigError(f"Unsupported auth mode: {auth_mode}")


class ModelResolver:
    @staticmethod
    def resolve():
        analysis_override = os.environ.get("AIMF_ANALYSIS_COPILOT_MODEL", "").strip()
        if analysis_override:
            return analysis_override

        fallback = os.environ.get("COPILOT_ANALYSIS_MODEL", "").strip()
        if fallback:
            return fallback

        raise CopilotConfigError("Model Resolver : Aucun modèle Copilot configuré.")


class CopilotSDKWrapper:
    """Boundary for real Copilot SDK usage for aimf-analysis-assist."""

    def __init__(self, model, token):
        self.model = model
        self.token = token

    @staticmethod
    def is_available():
        try:
            import github_copilot_sdk  # type: ignore # noqa: F401
            return True
        except Exception:
            return False

    def enrich(self, report_data):
        raise RuntimeError(
            "Copilot SDK runtime call not configured for aimf-analysis-assist in this build."
        )


class GuardrailValidator:
    _ALLOWED_ADVISORY_KEYS = {
        "risks",
        "unknowns",
        "recommendations",
        "planning_hints",
        "summary_notes",
        "confidence",
        "warnings",
    }

    _FORBIDDEN_MUTATION_PATH_HINTS = (
        "source_stack",
        "target_stack",
        "maven",
        "dependency_graph",
        "test",
        "import",
        "config",
        "module",
        "path",
    )

    @staticmethod
    def _to_json_object(ai_response):
        if isinstance(ai_response, str):
            try:
                ai_response = json.loads(ai_response)
            except json.JSONDecodeError as exc:
                raise ValueError("Guardrail Violation : Invalid Copilot JSON output.") from exc
        if not isinstance(ai_response, dict):
            raise ValueError("Guardrail Violation : Copilot output must be a JSON object.")
        return ai_response

    @staticmethod
    def _validate_confidence(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Guardrail Violation : Invalid confidence value.")
        if value < 0 or value > 1:
            raise ValueError("Guardrail Violation : Invalid confidence value.")

    @classmethod
    def _contains_forbidden_mutation(cls, key):
        k = key.lower()
        return any(hint in k for hint in cls._FORBIDDEN_MUTATION_PATH_HINTS)

    @classmethod
    def extract_advisory_fields(cls, ai_response):
        payload = cls._to_json_object(ai_response)
        advisory = {}
        warnings = []

        for key, value in payload.items():
            if key in cls._ALLOWED_ADVISORY_KEYS:
                if key == "confidence":
                    cls._validate_confidence(value)
                advisory[key] = value
                continue

            if cls._contains_forbidden_mutation(key):
                warnings.append(f"Guardrail ignored deterministic mutation attempt: {key}")

        return advisory, warnings

    @staticmethod
    def validate_no_tampering(original_report, enriched_report):
        if original_report.get("source_stack") != enriched_report.get("source_stack"):
            raise ValueError("Guardrail Violation : L'IA a tenté de modifier la stack source !")

        if original_report.get("target_stack") != enriched_report.get("target_stack"):
            raise ValueError("Guardrail Violation : L'IA a tenté de modifier la stack cible !")

        if original_report.get("project_metadata", {}).get("import_stats") != enriched_report.get("project_metadata", {}).get("import_stats"):
            raise ValueError("Guardrail Violation : L'IA a falsifié les statistiques du code !")

        return True


def enrich_with_ai(context, report_data):
    original_data_backup = copy.deepcopy(report_data)
    ai_assist_enabled = os.environ.get("AIMF_AI_ASSIST_ENABLED", "true").lower() == "true"

    assist_artifact = {
        "run_id": context.run_id,
        "status": "SKIPPED",
        "auth_mode": None,
        "model": None,
        "input_artifacts": ["analysis_report.json"],
        "suggestions_count": 0,
        "agent": "aimf-analysis-assist",
        "warnings": [],
        "timestamp": datetime.datetime.now().isoformat(),
    }

    if not ai_assist_enabled:
        report_data["ai_enrichment"]["status"] = "SKIPPED"
        assist_artifact["warnings"].append("AI assist disabled by AIMF_AI_ASSIST_ENABLED=false")
    else:
        try:
            auth_mode = CopilotAuthResolver.resolve_auth_mode()
            token = CopilotAuthResolver.get_token(auth_mode)
            model = ModelResolver.resolve()

            if not model:
                raise CopilotConfigError("Model Resolver : Empty model not allowed.")

            assist_artifact["auth_mode"] = auth_mode
            assist_artifact["model"] = model

            if not CopilotSDKWrapper.is_available():
                raise ModuleNotFoundError(
                    "Copilot SDK package 'github_copilot_sdk' unavailable in project dependencies."
                )

            sdk = CopilotSDKWrapper(model=model, token=token)
            ai_response = sdk.enrich(report_data)
            advisory_fields, advisory_warnings = GuardrailValidator.extract_advisory_fields(ai_response)

            report_data["ai_enrichment"].update(advisory_fields)
            report_data["ai_enrichment"]["status"] = "USED"
            GuardrailValidator.validate_no_tampering(original_data_backup, report_data)

            assist_artifact["warnings"].extend(advisory_warnings)
            assist_artifact["status"] = "USED"
            recs = report_data["ai_enrichment"].get("recommendations", [])
            assist_artifact["suggestions_count"] = len(recs) if isinstance(recs, list) else 0

        except Exception as e:
            report_data = original_data_backup
            report_data["ai_enrichment"]["status"] = "FAILED"
            assist_artifact["status"] = "FAILED"
            assist_artifact["warnings"].append(str(e))

    output_file = context.get_output_path("copilot_assist.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(assist_artifact, f, indent=4)

    return report_data
