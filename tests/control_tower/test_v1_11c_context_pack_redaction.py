"""Focused tests for V1-11C: Redaction filtering for context packs."""

from __future__ import annotations

import json

import pytest

from migration_factory.control_tower.application.retrievers import EvidenceRef
from migration_factory.control_tower.application.context_pack_redaction import (
    FORBIDDEN_EVIDENCE_PATTERNS,
    contains_forbidden_evidence_pattern,
    filter_evidence_refs,
    redact_bounds_json,
    redact_evidence_ref,
    redact_evidence_refs_json,
    redact_manifest_description,
    redact_manifest_field,
    redact_manifest_title,
)


# ── Forbidden evidence pattern tests ───────────────────────────────


class TestForbiddenEvidencePatterns:
    """contains_forbidden_evidence_pattern detection."""

    def test_detects_log_path(self) -> None:
        assert contains_forbidden_evidence_pattern("logs/app.log")
        assert contains_forbidden_evidence_pattern("var/log/output.log")

    def test_detects_db_path(self) -> None:
        assert contains_forbidden_evidence_pattern("data/mydb.db")
        assert contains_forbidden_evidence_pattern("cache/sqlite.db")

    def test_detects_cache_path(self) -> None:
        assert contains_forbidden_evidence_pattern("src/__pycache__/module.pyc")
        assert contains_forbidden_evidence_pattern(".cache/pip/http")

    def test_detects_build_artifact(self) -> None:
        assert contains_forbidden_evidence_pattern("target/classes/Main.class")
        assert contains_forbidden_evidence_pattern("build/output.jar")

    def test_detects_node_modules(self) -> None:
        assert contains_forbidden_evidence_pattern("node_modules/express/index.js")

    def test_passes_clean_source_path(self) -> None:
        assert not contains_forbidden_evidence_pattern("src/main/java/App.java")
        assert not contains_forbidden_evidence_pattern("pom.xml")
        assert not contains_forbidden_evidence_pattern("application.properties")


# ── Evidence ref redaction tests ───────────────────────────────────


class TestRedactEvidenceRef:
    """redact_evidence_ref behavior."""

    def test_preserves_clean_ref(self) -> None:
        ref = EvidenceRef(
            source_type="artifact",
            source_id="art-001",
            relative_path="src/main/java/App.java",
            size_bytes=100,
            checksum="abc123",
        )
        redacted = redact_evidence_ref(ref)
        assert redacted.relative_path == "src/main/java/App.java"
        assert redacted.source_id == "art-001"

    def test_redacts_absolute_path_in_ref(self) -> None:
        ref = EvidenceRef(
            source_type="artifact",
            source_id="art-001",
            relative_path="/home/user/project/src/Main.java",
            size_bytes=100,
            checksum="abc123",
        )
        redacted = redact_evidence_ref(ref)
        assert "/home/user" not in redacted.relative_path
        assert "[redacted" in redacted.relative_path

    def test_redacts_runtime_artifact_path(self) -> None:
        ref = EvidenceRef(
            source_type="artifact",
            source_id="art-001",
            relative_path="target/classes/Main.class",
            size_bytes=500,
            checksum="def456",
        )
        redacted = redact_evidence_ref(ref)
        assert "[redacted-runtime-artifact]" in redacted.relative_path

    def test_redacts_metadata_json(self) -> None:
        ref = EvidenceRef(
            source_type="artifact",
            source_id="art-001",
            relative_path="src/Main.java",
            size_bytes=100,
            checksum="abc123",
            metadata_json='{"path":"/etc/secrets/key.txt","bytes_read":50}',
        )
        redacted = redact_evidence_ref(ref)
        assert "/etc/secrets" not in redacted.metadata_json
        assert "[redacted" in redacted.metadata_json


class TestFilterEvidenceRefs:
    """filter_evidence_refs filtering behavior."""

    def test_filters_log_refs(self) -> None:
        refs = (
            EvidenceRef(
                source_type="artifact",
                source_id="art-001",
                relative_path="src/Main.java",
                size_bytes=100,
                checksum="a",
            ),
            EvidenceRef(
                source_type="artifact",
                source_id="art-001",
                relative_path="logs/stdout.log",
                size_bytes=5000,
                checksum="b",
            ),
        )
        filtered = filter_evidence_refs(refs)
        assert len(filtered) == 1
        assert filtered[0].relative_path == "src/Main.java"

    def test_filters_cache_refs(self) -> None:
        refs = (
            EvidenceRef(
                source_type="artifact",
                source_id="art-002",
                relative_path=".cache/packages/lib.so",
                size_bytes=1000,
                checksum="c",
            ),
        )
        filtered = filter_evidence_refs(refs)
        assert len(filtered) == 0

    def test_filters_node_modules(self) -> None:
        refs = (
            EvidenceRef(
                source_type="artifact",
                source_id="art-003",
                relative_path="node_modules/lodash/index.js",
                size_bytes=2000,
                checksum="d",
            ),
        )
        filtered = filter_evidence_refs(refs)
        assert len(filtered) == 0

    def test_passes_clean_refs_through(self) -> None:
        refs = (
            EvidenceRef(
                source_type="artifact",
                source_id="art-004",
                relative_path="src/main/java/com/example/App.java",
                size_bytes=200,
                checksum="e",
            ),
            EvidenceRef(
                source_type="artifact",
                source_id="art-004",
                relative_path="src/main/resources/application.properties",
                size_bytes=50,
                checksum="f",
            ),
        )
        filtered = filter_evidence_refs(refs)
        assert len(filtered) == 2


# ── Manifest field redaction tests ────────────────────────────────


class TestRedactManifestField:
    """redact_manifest_field behavior."""

    def test_redacts_absolute_path_in_field(self) -> None:
        result = redact_manifest_field("Analyzed /home/user/project")
        assert "/home/user/project" not in result

    def test_redacts_env_assignment(self) -> None:
        result = redact_manifest_field("KEY=secret")
        assert "KEY=secret" not in result

    def test_redacts_deployment_id(self) -> None:
        result = redact_manifest_field("Model: deployment-id=abc-123")
        assert "deployment-id" not in result.lower() or "[redacted" in result

    def test_preserves_clean_field(self) -> None:
        result = redact_manifest_field("Migration analysis for springboot 2.7.18")
        assert result == "Migration analysis for springboot 2.7.18"

    def test_returns_none_for_empty(self) -> None:
        assert redact_manifest_field("") == ""
        assert redact_manifest_field(None) is None


class TestRedactManifestTitle:
    """redact_manifest_title behavior."""

    def test_preserves_clean_title(self) -> None:
        result = redact_manifest_title("Stage 1 analysis")
        assert result == "Stage 1 analysis"

    def test_redacts_path_in_title(self) -> None:
        result = redact_manifest_title("Analysis of /home/user/project")
        assert "[redacted" in result


class TestRedactManifestDescription:
    """redact_manifest_description behavior."""

    def test_preserves_clean_description(self) -> None:
        result = redact_manifest_description("Contains stage 1 migration analysis")
        assert result == "Contains stage 1 migration analysis"

    def test_returns_none_for_none(self) -> None:
        assert redact_manifest_description(None) is None


# ── Bounds JSON redaction tests ───────────────────────────────────


class TestRedactBoundsJson:
    """redact_bounds_json behavior."""

    def test_preserves_clean_bounds(self) -> None:
        bounds = json.dumps({"max_tokens": 4000, "max_depth": 5})
        result = redact_bounds_json(bounds)
        parsed = json.loads(result)
        assert parsed["max_tokens"] == 4000

    def test_redacts_path_in_bounds(self) -> None:
        bounds = json.dumps({"evidence_path": "/home/user/project/src"})
        result = redact_bounds_json(bounds)
        assert "/home/user" not in result

    def test_returns_none_for_none(self) -> None:
        assert redact_bounds_json(None) is None

    def test_handles_invalid_json(self) -> None:
        result = redact_bounds_json("not json at all")
        # Falls back to manifest field redaction
        assert result is not None


# ── Evidence refs JSON redaction tests ─────────────────────────────


class TestRedactEvidenceRefsJson:
    """redact_evidence_refs_json behavior."""

    def test_preserves_clean_entries(self) -> None:
        entries = json.dumps([
            {"source_type": "artifact", "relative_path": "src/Main.java"},
        ])
        result = redact_evidence_refs_json(entries)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["relative_path"] == "src/Main.java"

    def test_redacts_absolute_paths_in_entries(self) -> None:
        entries = json.dumps([
            {"source_type": "artifact", "relative_path": "/home/user/src/Main.java"},
        ])
        result = redact_evidence_refs_json(entries)
        assert "/home/user" not in result

    def test_returns_none_for_none(self) -> None:
        assert redact_evidence_refs_json(None) is None

    def test_handles_empty_list(self) -> None:
        result = redact_evidence_refs_json("[]")
        parsed = json.loads(result)
        assert parsed == []


# ── Integration: full context pack filtering pipeline ──────────────


class TestContextPackFilteringPipeline:
    """End-to-end context pack redaction filtering."""

    def test_filters_evidence_and_redacts_remaining(self) -> None:
        refs = (
            EvidenceRef(
                source_type="artifact",
                source_id="art-001",
                relative_path="src/main/java/App.java",
                size_bytes=200,
                checksum="a",
            ),
            EvidenceRef(
                source_type="artifact",
                source_id="art-001",
                relative_path="logs/stdout.log",
                size_bytes=5000,
                checksum="b",
            ),
            EvidenceRef(
                source_type="artifact",
                source_id="art-001",
                relative_path="/root/.ssh/id_rsa",
                size_bytes=300,
                checksum="c",
            ),
        )

        filtered = filter_evidence_refs(refs)

        # Only the clean src ref should survive
        assert len(filtered) == 1
        assert filtered[0].relative_path == "src/main/java/App.java"

    def test_manifest_title_and_description_redacted(self) -> None:
        title = redact_manifest_title("Analyzing /home/user/my-project")
        desc = redact_manifest_description(
            "Found config with SECRET_KEY=abc123 and deployment_id=abc-123"
        )

        assert "[redacted" in title
        assert "SECRET_KEY=abc123" not in desc
        assert "deployment_id" not in desc or "[redacted" in desc

    def test_bounds_with_sensitive_path_redacted(self) -> None:
        bounds = redact_bounds_json(
            json.dumps({
                "evidence_root": "/home/user/project",
                "max_files": 50,
                "forbidden_dirs": ["/etc", "/var/log"],
            })
        )
        parsed = json.loads(bounds)
        assert "/home/user" not in parsed["evidence_root"]
        assert "[redacted" in parsed["evidence_root"]
        assert parsed["max_files"] == 50
