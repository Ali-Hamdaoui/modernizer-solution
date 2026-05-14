import json
from pathlib import Path

import jsonschema

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load(name: str):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_analysis_report_schema_accepts_expected_payload():
    schema = _load("analysis_report.schema.json")
    sample = {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "agent": "analysis_agent",
        "status": "COMPLETED",
        "timestamp": "2026-05-14T00:00:00",
        "source_stack": {},
        "target_stack": {},
        "project_metadata": {},
        "rewrite": {},
        "ai_enrichment": {"status": "SKIPPED"}
    }
    jsonschema.validate(sample, schema)


def test_dependency_graph_schema_accepts_expected_payload():
    schema = _load("dependency_graph.schema.json")
    sample = {
        "available": True,
        "raw_file": "dependency-tree.raw.json",
        "format": "json",
        "warning": None,
        "root": {"name": "a:b", "version": "1", "dependencies": []}
    }
    jsonschema.validate(sample, schema)


def test_rewrite_plugin_plan_schema_enforces_status_enum():
    schema = _load("rewrite_plugin_plan.schema.json")
    jsonschema.validate({"status": "USED", "transformer_guidance": "x", "openrewrite": {}}, schema)

    try:
        jsonschema.validate({"status": "SUCCESS", "transformer_guidance": "x", "openrewrite": {}}, schema)
        assert False, "Expected enum validation failure"
    except jsonschema.ValidationError:
        pass


def test_rewrite_impact_summary_schema_enforces_impact_enum():
    schema = _load("rewrite_impact_summary.schema.json")
    jsonschema.validate({"impact": "UNKNOWN"}, schema)
    jsonschema.validate({"status": "FAILED", "impact": "BLOCKED", "error": "boom"}, schema)
