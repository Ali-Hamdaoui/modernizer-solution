import json

import pytest

from copilot_enricher import GuardrailValidator, enrich_with_ai, CopilotSDKWrapper


class DummyContext:
    def __init__(self, run_id, out_dir):
        self.run_id = run_id
        self._out_dir = out_dir

    def get_output_path(self, filename):
        return str(self._out_dir / filename)


def _base_report():
    return {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "target_stack": {"java": "17", "spring_boot": "3.2.x"},
        "project_metadata": {"import_stats": {"javax_count": 1}},
        "ai_enrichment": {
            "status": "SKIPPED",
            "additional_risks": [],
            "recommendations": [],
        },
    }


def _enable_ai(monkeypatch):
    monkeypatch.setenv("AIMF_AI_ASSIST_ENABLED", "true")
    monkeypatch.setenv("AIMF_COPILOT_AUTH_MODE", "oauth_github_app")
    monkeypatch.setenv("AIMF_GITHUB_APP_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setenv("COPILOT_ANALYSIS_MODEL", "gpt-4o")
    monkeypatch.setattr(CopilotSDKWrapper, "is_available", staticmethod(lambda: True))


def test_guardrail_blocks_stack_tampering():
    original_report = {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 50}},
    }
    tampered_report = {
        "source_stack": {"java": "17", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 50}},
    }

    with pytest.raises(ValueError, match="L'IA a tenté de modifier la stack source"):
        GuardrailValidator.validate_no_tampering(original_report, tampered_report)


def test_guardrail_blocks_stats_tampering():
    original_report = {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 50}},
    }
    tampered_report = {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 0}},
    }

    with pytest.raises(ValueError, match="L'IA a falsifié les statistiques du code"):
        GuardrailValidator.validate_no_tampering(original_report, tampered_report)


def test_enrich_skipped_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("AIMF_AI_ASSIST_ENABLED", "false")
    ctx = DummyContext("run_1", tmp_path)

    result = enrich_with_ai(ctx, _base_report())

    assert result["ai_enrichment"]["status"] == "SKIPPED"
    artifact = json.loads((tmp_path / "copilot_assist.json").read_text(encoding="utf-8"))
    assert artifact["status"] == "SKIPPED"


def test_allowed_advisory_fields_appended(monkeypatch, tmp_path):
    _enable_ai(monkeypatch)
    monkeypatch.setattr(
        CopilotSDKWrapper,
        "enrich",
        lambda self, report: json.dumps(
            {
                "risks": ["risk-1"],
                "unknowns": ["unknown-1"],
                "planning_hints": ["hint-1"],
                "summary_notes": "note",
                "confidence": 0.8,
                "warnings": ["warn-1"],
                "recommendations": ["rec-1", "rec-2"],
            }
        ),
    )

    ctx = DummyContext("run_2", tmp_path)
    result = enrich_with_ai(ctx, _base_report())

    assert result["ai_enrichment"]["status"] == "USED"
    assert result["ai_enrichment"]["risks"] == ["risk-1"]
    assert result["ai_enrichment"]["unknowns"] == ["unknown-1"]
    assert result["ai_enrichment"]["planning_hints"] == ["hint-1"]
    assert result["ai_enrichment"]["summary_notes"] == "note"
    assert result["ai_enrichment"]["confidence"] == 0.8
    assert result["ai_enrichment"]["warnings"] == ["warn-1"]
    assert result["ai_enrichment"]["recommendations"] == ["rec-1", "rec-2"]


def test_forbidden_deterministic_mutation_ignored_with_warning(monkeypatch, tmp_path):
    _enable_ai(monkeypatch)
    monkeypatch.setattr(
        CopilotSDKWrapper,
        "enrich",
        lambda self, report: {
            "source_stack": {"java": "21"},
            "dependency_graph": {"changed": True},
            "recommendations": ["safe-rec"],
        },
    )

    ctx = DummyContext("run_3", tmp_path)
    result = enrich_with_ai(ctx, _base_report())

    assert result["ai_enrichment"]["status"] == "USED"
    assert result["source_stack"]["java"] == "11"
    assert result["ai_enrichment"]["recommendations"] == ["safe-rec"]

    artifact = json.loads((tmp_path / "copilot_assist.json").read_text(encoding="utf-8"))
    assert artifact["status"] == "USED"
    assert any("deterministic mutation attempt" in w for w in artifact["warnings"])


def test_invalid_json_rejected(monkeypatch, tmp_path):
    _enable_ai(monkeypatch)
    monkeypatch.setattr(CopilotSDKWrapper, "enrich", lambda self, report: "{bad-json")

    ctx = DummyContext("run_4", tmp_path)
    result = enrich_with_ai(ctx, _base_report())

    assert result["ai_enrichment"]["status"] == "FAILED"
    artifact = json.loads((tmp_path / "copilot_assist.json").read_text(encoding="utf-8"))
    assert artifact["status"] == "FAILED"
    assert any("Invalid Copilot JSON output" in warning for warning in artifact["warnings"])


def test_invalid_confidence_rejected(monkeypatch, tmp_path):
    _enable_ai(monkeypatch)
    monkeypatch.setattr(CopilotSDKWrapper, "enrich", lambda self, report: {"confidence": 1.5})

    ctx = DummyContext("run_5", tmp_path)
    result = enrich_with_ai(ctx, _base_report())

    assert result["ai_enrichment"]["status"] == "FAILED"
    artifact = json.loads((tmp_path / "copilot_assist.json").read_text(encoding="utf-8"))
    assert artifact["status"] == "FAILED"
    assert any("Invalid confidence value" in warning for warning in artifact["warnings"])
