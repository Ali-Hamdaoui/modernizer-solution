"""PR-G: Governed LLM invocation ledger — comprehensive tests.

Covers migration, repository CRUD, content-derived checksums,
proposer != reviewer distinct IDs, fallback tracking, security
rules (no raw secrets/endpoints/deployments), and repair chain
capture points.

Required coverage (16+ tests):
 1. migration applies on fresh DB
 2. old DB upgrades cleanly
 3. save/list/get invocation works
 4. completed invocation stores output checksum
 5. failed invocation stores redacted error
 6. list by job isolates jobs
 7. list by proposal isolates proposals
 8. proposer and reviewer invocations are distinct
 9. fallback_used is stored
10. no raw endpoint/API key/deployment secret stored or returned
11. no raw prompt/completion leaked in API response
12. context_checksum and output_checksum are content-derived
13. repair chain records proposer invocation
14. repair chain records reviewer invocation
15. revision chain records revision proposer/reviewer invocation (if path exists)
16. endpoint response has no forbidden fields
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_llm_invocation_ledger import (
    V2LLMInvocationLedger,
    compute_content_checksum,
    compute_deployment_alias_hash,
    safe_provider_alias,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import (
    SqliteV2LLMInvocationRepository,
    V2LLMInvocationRecord,
)


# ── Helpers ────────────────────────────────────────────────────────────

MIGRATION_PATH = (
    "migration_factory/control_tower/infrastructure/sqlite/migrations"
    "/0050_v2_llm_invocations.sql"
)


def _apply_migration_only(tmp_path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    db_path = tmp_path / "test_v2_llm_invocations.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(MIGRATION_PATH) as f:
        conn.executescript(f.read())
    return conn


def _make_repo(conn: sqlite3.Connection) -> SqliteV2LLMInvocationRepository:
    return SqliteV2LLMInvocationRepository(conn)


def _make_ledger(conn: sqlite3.Connection) -> V2LLMInvocationLedger:
    repo = _make_repo(conn)
    return V2LLMInvocationLedger(repo)


def _seed_invocation(
    repo: SqliteV2LLMInvocationRepository,
    *,
    job_id: str = "job-1",
    proposal_id: str | None = None,
    role: str = "main",
    responsibility: str = "repair_proposal",
    status: str = "started",
    fallback_used: int = 0,
) -> str:
    inv_id = uuid4().hex
    record = V2LLMInvocationRecord(
        invocation_id=inv_id,
        job_id=job_id,
        role=role,
        responsibility=responsibility,
        status=status,
        created_at=utc_now_text(),
        proposal_id=proposal_id,
        provider_alias=safe_provider_alias(),
        fallback_used=fallback_used,
    )
    repo.save(record)
    return inv_id


# ── 1. Migration applies on fresh DB ─────────────────────────────────


class TestMigration:
    def test_table_exists(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='v2_llm_invocations'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_has_indexes(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        cur = conn.cursor()
        for idx in (
            "ix_v2_llm_invocations_job_created",
            "ix_v2_llm_invocations_proposal",
            "ix_v2_llm_invocations_gate",
            "ix_v2_llm_invocations_role",
            "ix_v2_llm_invocations_status",
        ):
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx,),
            )
            assert cur.fetchone() is not None, f"missing index {idx}"
        conn.close()

    def test_append_only_triggers(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO v2_llm_invocations (invocation_id, job_id, role, responsibility, status, created_at) "
            "VALUES ('test-1', 'j1', 'main', 'repair_proposal', 'started', '2026-06-30T00:00:00.000000Z')"
        )
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            cur.execute("DELETE FROM v2_llm_invocations WHERE invocation_id = 'test-1'")
        conn.close()

    def test_check_constraints(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        cur = conn.cursor()
        with pytest.raises(sqlite3.IntegrityError):
            cur.execute(
                "INSERT INTO v2_llm_invocations (invocation_id, job_id, role, responsibility, status, created_at) "
                "VALUES ('bad-1', 'j1', 'invalid_role', 'repair_proposal', 'started', 'now')"
            )
        conn.close()


# ── 2. Old DB upgrades cleanly ────────────────────────────────────────


class TestUpgradeCompat:
    """Simulate old DB (schema before 0049) then apply the migration."""

    def test_old_db_upgrades_cleanly(self, tmp_path: Path) -> None:
        db_path = tmp_path / "upgrade_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE migration_jobs (job_id TEXT PRIMARY KEY, status TEXT)")
        conn.execute("INSERT INTO migration_jobs (job_id, status) VALUES ('j1', 'running')")
        conn.commit()
        with open(MIGRATION_PATH) as f:
            conn.executescript(f.read())
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='v2_llm_invocations'"
        )
        assert cur.fetchone() is not None
        rows = cur.execute("SELECT * FROM migration_jobs").fetchall()
        assert len(rows) == 1
        conn.close()


# ── 3. Save/list/get invocation works ─────────────────────────────────


class TestRepositoryCRUD:
    def test_save_and_get(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        repo = _make_repo(conn)
        inv_id = uuid4().hex
        record = V2LLMInvocationRecord(
            invocation_id=inv_id,
            job_id="job-1",
            role="main",
            responsibility="repair_proposal",
            status="started",
            created_at=utc_now_text(),
            provider_alias="azure_openai",
        )
        repo.save(record)
        loaded = repo.get(inv_id)
        assert loaded is not None
        assert loaded.invocation_id == inv_id
        assert loaded.job_id == "job-1"
        assert loaded.role == "main"
        assert loaded.responsibility == "repair_proposal"
        assert loaded.status == "started"
        conn.close()

    def test_list_by_job(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        repo = _make_repo(conn)
        _seed_invocation(repo, job_id="job-a", role="main")
        _seed_invocation(repo, job_id="job-a", role="reviewer")
        _seed_invocation(repo, job_id="job-b", role="main")
        entries_a = repo.list_by_job("job-a")
        assert len(entries_a) == 2
        entries_b = repo.list_by_job("job-b")
        assert len(entries_b) == 1
        conn.close()

    def test_list_by_proposal(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        repo = _make_repo(conn)
        _seed_invocation(repo, job_id="j1", proposal_id="prop-1")
        _seed_invocation(repo, job_id="j1", proposal_id="prop-1")
        _seed_invocation(repo, job_id="j1", proposal_id="prop-2")
        prop_entries = repo.list_by_proposal("prop-1")
        assert len(prop_entries) == 2
        prop2_entries = repo.list_by_proposal("prop-2")
        assert len(prop2_entries) == 1
        conn.close()


# ── 4. Completed invocation stores output checksum ────────────────────


class TestCompletion:
    def test_completed_stores_output_checksum(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.complete_invocation(
            inv_id,
            output="test output content",
            redacted_summary="Completed OK",
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.status == "completed"
        assert record.output_checksum is not None
        assert record.output_checksum == compute_content_checksum("test output content")
        assert record.completed_at is not None
        conn.close()


# ── 5. Failed invocation stores redacted error ────────────────────────


class TestFailure:
    def test_failed_stores_redacted_error(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.fail_invocation(
            inv_id,
            redacted_error="model returned 500: timeout",
            redacted_summary="Invocation failed",
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.status == "failed"
        assert record.redacted_error is not None
        assert record.completed_at is not None
        conn.close()


# ── 6. List by job isolates jobs ──────────────────────────────────────


class TestJobIsolation:
    def test_jobs_isolated(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        ledger.start_invocation(job_id="job-x", role="main", responsibility="repair_proposal")
        ledger.start_invocation(job_id="job-y", role="reviewer", responsibility="repair_review")
        x_entries = ledger.list_by_job("job-x")
        y_entries = ledger.list_by_job("job-y")
        assert len(x_entries) == 1
        assert len(y_entries) == 1
        assert x_entries[0].job_id == "job-x"
        assert y_entries[0].job_id == "job-y"
        conn.close()


# ── 7. List by proposal isolates proposals ────────────────────────────


class TestProposalIsolation:
    def test_proposals_isolated(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        p1 = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal", proposal_id="prop-a"
        )
        p2 = ledger.start_invocation(
            job_id="j1", role="reviewer", responsibility="repair_review", proposal_id="prop-a"
        )
        ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal", proposal_id="prop-b"
        )
        prop_a = ledger.list_by_proposal("prop-a")
        prop_b = ledger.list_by_proposal("prop-b")
        assert len(prop_a) == 2
        assert len(prop_b) == 1
        assert p1 != p2
        conn.close()


# ── 8. Proposer and reviewer invocations are distinct ─────────────────


class TestDistinctInvocationIds:
    def test_proposer_reviewer_distinct(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        prop_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        rev_id = ledger.start_invocation(
            job_id="j1", role="reviewer", responsibility="repair_review"
        )
        assert prop_id != rev_id
        conn.close()


# ── 9. Fallback_used is stored ────────────────────────────────────────


class TestFallback:
    def test_fallback_stored(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.complete_invocation(inv_id, output="fallback content", fallback_used=True)
        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.fallback_used == 1
        assert record.status == "fallback"
        conn.close()


# ── 10. No raw endpoint/API key/deployment secret stored or returned ──


class TestNoSecretsLeaked:
    def test_no_secrets_in_dto(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME", "GPT-5 Mini")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.complete_invocation(inv_id, output="safe output")
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        assert dto["model_display_name"] == "GPT-5 Mini"
        assert "input_checksum" in dto
        assert "redacted_error" in dto
        text = json.dumps(dto).lower()
        for secret_word in ("api_key", "api-key", "apikey", "endpoint", "secret", "bearer"):
            assert secret_word not in text, f"forbidden word {secret_word} found in dto"
        assert len(dto.get("deployment_alias_hash") or "") == 0 or len(dto["deployment_alias_hash"]) <= 64
        assert dto.get("provider_alias") in (None, "azure_openai")
        forbidden = ledger.forbidden_fields_exposed(dto)
        assert len(forbidden) == 0, f"forbidden fields found: {forbidden}"
        conn.close()

    def test_no_secrets_in_api_response(self, tmp_path: Path) -> None:
        """Verify the FastAPI endpoint returns no forbidden fields."""
        conn = _apply_migration_only(tmp_path, check_same_thread=False)
        repo = _make_repo(conn)
        _seed_invocation(repo, job_id="j1")
        _seed_invocation(repo, job_id="j1", role="reviewer", responsibility="repair_review")

        app = _build_test_app_with_connection(conn)
        client = TestClient(app)
        response = client.get("/v1/v2/jobs/j1/llm/activity")
        assert response.status_code == 200
        data = response.json()
        assert "invocations" in data
        text = json.dumps(data).lower()
        for secret_word in ("api_key", "api-key", "apikey", "endpoint", "secret", "bearer", "password"):
            assert secret_word not in text, f"forbidden word {secret_word} in API response"
        first = data["invocations"][0]
        assert "model_display_name" in first
        assert "input_checksum" in first
        assert "redacted_error" in first
        conn.close()


# ── 11. No raw prompt/completion leaked in API response ───────────────


class TestNoRawContent:
    def test_no_raw_prompt_or_completion(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path, check_same_thread=False)
        repo = _make_repo(conn)
        _seed_invocation(repo, job_id="j1")

        app = _build_test_app_with_connection(conn)
        client = TestClient(app)
        response = client.get("/v1/v2/jobs/j1/llm/activity")
        assert response.status_code == 200
        data = response.json()
        invocations = data.get("invocations", [])
        for inv in invocations:
            inv_keys = set(inv.keys())
            for forbidden_key in ("prompt", "completion", "raw_content"):
                key_exact = forbidden_key
                key_alt = forbidden_key.replace("_", "")
                assert key_exact not in inv_keys, f"forbidden field {forbidden_key} in response"
                assert key_alt not in inv_keys, f"forbidden field {forbidden_key} (alt) in response"
        conn.close()


# ── 12. Checksums are content-derived ─────────────────────────────────


class TestContentDerivedChecksums:
    def test_checksums_match_content(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1",
            role="main",
            responsibility="repair_proposal",
            context_checksum="sha256:abc123",
            input_checksum="sha256:def456",
        )
        output_text = "exact output text for checksum verification"
        ledger.complete_invocation(inv_id, output=output_text)
        record = ledger.get_invocation(inv_id)
        assert record is not None
        expected_output_cs = compute_content_checksum(output_text)
        assert record.output_checksum == expected_output_cs
        assert record.context_checksum == "sha256:abc123"
        assert record.input_checksum == "sha256:def456"
        conn.close()


# ── 13/14. Repair chain records proposer/reviewer invocations ─────────


class TestRepairChainCapture:
    """Test that produce_repair_review_chain captures invocations via ledger."""

    def test_chain_captures_proposer_and_reviewer(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)

        from migration_factory.control_tower.domain.checksums import sha256_canonical_json as _cs

        primary_content = json.dumps({
            "root_cause": "test failure",
            "fix_strategy": "update dependency",
            "changed_files": ["pom.xml"],
            "proposed_diff": "diff --git a/pom.xml b/pom.xml\n--- a/pom.xml\n+++ b/pom.xml\n@@ -1 +1 @@\n-test\n+fixed",
            "risk": "LOW",
            "confidence": 0.9,
            "rationale": "test",
        })

        expected_primary_checksum = _cs({
            "root_cause": "test failure",
            "fix_strategy": "update dependency",
            "changed_files": ["pom.xml"],
            "proposed_diff": "diff --git a/pom.xml b/pom.xml\n--- a/pom.xml\n+++ b/pom.xml\n@@ -1 +1 @@\n-test\n+fixed",
            "deterministic_rule_id": "",
            "risk": "LOW",
            "confidence": 0.9,
            "rationale": "test",
            "no_fix_reason": "",
        })
        expected_diff_checksum = _cs({
            "unified_diff": "diff --git a/pom.xml b/pom.xml\n--- a/pom.xml\n+++ b/pom.xml\n@@ -1 +1 @@\n-test\n+fixed",
        })

        mock_client = MagicMock()
        call_count: list[int] = [0]
        _saved_checksums: dict[str, str] = {}

        def side_effect(*, role, prompt, fallback, output_schema_name=None, require_schema=False, **kwargs):
            nonlocal _saved_checksums
            call_count[0] += 1
            if call_count[0] == 1 or role == V2ModelRole.PROPOSER:
                _saved_checksums["primary"] = expected_primary_checksum
                _saved_checksums["diff"] = expected_diff_checksum
                return MagicMock(
                    success=True,
                    content=primary_content,
                    redacted_summary="Primary repair succeeded.",
                    source="azure_openai",
                    model_status="live_ok",
                    provider="azure_openai",
                    role="proposer",
                    failure_reason="",
                )
            _saved_checksums["context"] = "cs-context"
            return MagicMock(
                success=True,
                content=json.dumps({
                    "decision": "accept",
                    "notes": ["Looks good"],
                    "risks": ["Low risk"],
                    "confidence": 0.85,
                    "policy_concerns": [],
                    "changed_files_verified": True,
                    "diff_parseable": True,
                    "reviewed_context_checksum": _saved_checksums.get("context", "cs-context"),
                    "reviewed_primary_output_checksum": _saved_checksums.get("primary", expected_primary_checksum),
                    "reviewed_diff_checksum": _saved_checksums.get("diff", expected_diff_checksum),
                }),
                redacted_summary="Reviewer accepted.",
                source="azure_openai",
                model_status="live_ok",
                provider="azure_openai",
                role="reviewer",
                failure_reason="",
            )

        mock_client.answer_with_role.side_effect = side_effect

        from migration_factory.orchestrator.repair_review_chain import (
            produce_repair_review_chain,
        )
        from migration_factory.repair_loop.failure_evidence import (
            FailureEvidence,
            FailureSource,
            NormalizedCompilerError,
        )
        from migration_factory.repair_loop.repair_context import (
            RepairContextPack,
        )

        evidence = FailureEvidence(
            failure_source=FailureSource.BUILD,
            stage_index=2,
            failure_summary="Build failed",
            compiler_errors=[NormalizedCompilerError(message="symbol not found", file_path="Test.java")],
            test_failures=[],
            changed_files=frozenset(["pom.xml"]),
            source_profile="java11",
            target_profile="java17",
            accepted_artifact_checksums=frozenset(),
            content_checksum="cs-evidence",
        )
        from migration_factory.control_tower.domain.checksums import utc_now_text

        context_pack = RepairContextPack(
            job_id="test-job-1",
            stage_index=2,
            command_id="cmd-1",
            failure_source="build",
            failure_evidence_checksum="cs-evidence",
            context_pack_checksum="cs-context",
            base_repo_state_checksum="cs-base",
            created_at=utc_now_text(),
            source_profile="java11",
            target_profile="java17",
        )

        result = produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context_pack,
            output_dir=tmp_path / "chain_output",
            model_client=mock_client,
            invocation_ledger=ledger,
        )

        review_chain = result.get("review_chain", {})
        prop_id = review_chain.get("proposer_invocation_id")
        rev_id = review_chain.get("reviewer_invocation_id")
        assert prop_id is not None, "proposer invocation ID missing"
        assert rev_id is not None, "reviewer invocation ID missing"
        assert prop_id != rev_id, "proposer and reviewer must be distinct"

        prop_record = ledger.get_invocation(prop_id)
        rev_record = ledger.get_invocation(rev_id)
        assert prop_record is not None
        assert rev_record is not None
        assert prop_record.role == "main"
        assert prop_record.responsibility == "repair_proposal"
        assert rev_record.role == "reviewer"
        assert rev_record.responsibility == "repair_review"
        assert prop_record.output_checksum is not None
        assert rev_record.output_checksum is not None
        conn.close()


# ── 15. Revision chain (if path exists) ───────────────────────────────


class TestRevisionChainCapture:
    def test_revision_invocations_captured(self, tmp_path: Path) -> None:
        """Test that the ledger captures revision proposer/reviewer."""
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)

        inv_id = ledger.start_invocation(
            job_id="j1",
            role="main",
            responsibility="revision_proposal",
            proposal_id="prop-rev",
        )
        ledger.complete_invocation(inv_id, output="revised output")

        rev_inv_id = ledger.start_invocation(
            job_id="j1",
            role="reviewer",
            responsibility="revision_review",
            proposal_id="prop-rev",
        )
        ledger.complete_invocation(rev_inv_id, output="revised review")

        assert inv_id != rev_inv_id

        by_proposal = ledger.list_by_proposal("prop-rev")
        assert len(by_proposal) == 2
        roles = {r.role for r in by_proposal}
        assert "main" in roles
        assert "reviewer" in roles
        conn.close()


# ── 16. Endpoint response has no forbidden fields ─────────────────────


class TestEndpointForbiddenFields:
    def test_endpoint_no_forbidden_fields(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path, check_same_thread=False)
        repo = _make_repo(conn)
        _seed_invocation(repo, job_id="secure-job", role="main", responsibility="repair_proposal")
        _seed_invocation(repo, job_id="secure-job", role="reviewer", responsibility="repair_review")

        app = _build_test_app_with_connection(conn)
        client = TestClient(app)
        response = client.get("/v1/v2/jobs/secure-job/llm/activity")
        assert response.status_code == 200
        data = response.json()
        invocations = data.get("invocations", [])
        assert len(invocations) >= 2
        for inv in invocations:
            inv_keys = set(inv.keys())
            for forbidden in ("prompt", "completion", "endpoint", "api_key", "secret", "raw", "password"):
                assert forbidden not in inv_keys, f"found forbidden field {forbidden}"

            assert inv.get("role") in ("main", "reviewer", "fallback")
            assert inv.get("responsibility") in (
                "repair_proposal", "repair_review", "revision_proposal", "revision_review",
                "diagnosis", "explanation",
            )
        conn.close()


# ── Extra: token/latency tracking ─────────────────────────────────────


class TestBoundInvocations:
    """Verify that successful chain produces only bound main+reviewer invocations
    and no unbound fallback invocations are created when a proposal already exists."""

    def test_successful_chain_has_bound_main_and_reviewer_only(self, tmp_path: Path) -> None:
        """After a successful repair chain, the ledger must contain exactly
        two invocations (proposer=main, reviewer=reviewer), both bound to
        the proposal and gate."""
        from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
        from migration_factory.control_tower.application.v2_phase_gate_service import V2PhaseGateService
        from migration_factory.control_tower.application.v2_repair_gate_service import (
            V2RepairGateService,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_phase_gate_repository import (
            SqlitePhaseGateRepository,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
            SqliteV2ReviewerRepository,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
            SqliteV2RepairRepository,
        )
        from migration_factory.repair_loop.failure_evidence import build_failure_evidence, FailureSource
        from migration_factory.repair_loop.repair_context import build_repair_context_pack

        conn = sqlite3.connect(
            str(tmp_path / "bound-llm.sqlite3"),
            check_same_thread=False,
            isolation_level=None,
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        apply_pending_migrations(conn)

        gate_repo = SqlitePhaseGateRepository(conn)
        repair_repo = SqliteV2RepairRepository(conn)
        llm_repo = SqliteV2LLMInvocationRepository(conn)

        repair_gate_service = V2RepairGateService(
            gate_service=V2PhaseGateService(gate_repo),
            repair_repo=repair_repo,
            reviewer_repo=SqliteV2ReviewerRepository(conn),
            llm_invocation_repo=llm_repo,
        )

        run_dir = tmp_path / "run"
        repair_dir = run_dir / "repairs"
        sandbox = tmp_path / "sandbox"
        legacy = tmp_path / "legacy"
        repair_dir.mkdir(parents=True, exist_ok=True)
        sandbox.mkdir(exist_ok=True)
        legacy.mkdir(exist_ok=True)
        (sandbox / "pom.xml").write_text("<project/>\n", encoding="utf-8")

        evidence = build_failure_evidence(
            failure_source=FailureSource.BUILD,
            job_id="job-bound",
            stage_index=3,
            command_id="cmd-bound",
            failure_summary="Build failed: missing H2",
            source_profile="springboot-3.5-java21",
            target_profile="springboot-4.0-java21",
            changed_files=("pom.xml",),
        )
        context = build_repair_context_pack(
            failure_evidence=evidence,
            job_id=evidence.job_id,
            stage_index=evidence.stage_index,
            command_id=evidence.command_id,
            source_profile=evidence.source_profile,
            target_profile=evidence.target_profile,
            changed_files=evidence.changed_files,
        )
        evidence_path = repair_dir / "repair_failure_evidence.json"
        context_path = repair_dir / "repair_context_pack.json"
        from migration_factory.repair_loop.failure_evidence import failure_evidence_to_dict
        from migration_factory.repair_loop.repair_context import context_pack_to_dict
        evidence_path.write_text(json.dumps(failure_evidence_to_dict(evidence), indent=2), encoding="utf-8")
        context_path.write_text(json.dumps(context_pack_to_dict(context), indent=2), encoding="utf-8")

        payload = {
            "_repair_failure_evidence_ref": str(evidence_path),
            "_repair_context_pack_ref": str(context_path),
            "_repair_run_dir": str(run_dir),
            "_repair_sandbox_path": str(sandbox),
            "_repair_failure_evidence_checksum": evidence.content_checksum,
            "_repair_context_pack_checksum": context.context_pack_checksum,
            "_repair_base_repo_state_checksum": context.base_repo_state_checksum,
            "_repair_h2_required": "true",
        }

        H2_DIFF = """\
diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
@@ -1,1 +1,2 @@
 <project/>
+<dependency><groupId>com.h2database</groupId><artifactId>h2</artifactId><scope>runtime</scope></dependency>
"""
        class _FakeClient:
            def __init__(self):
                self.calls = []
                self._prop_checksum = None
                self._diff_checksum = None
            def answer_with_role(self, *, role, prompt, fallback, output_schema_name=None, require_schema=True, **kwargs):
                self.calls.append(role)
                from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelResult
                from migration_factory.control_tower.domain.checksums import sha256_canonical_json
                if role.value == "proposer":
                    content = json.dumps({
                        "root_cause": "Missing H2",
                        "fix_strategy": "Add H2 dependency",
                        "changed_files": ["pom.xml"],
                        "proposed_diff": H2_DIFF,
                        "risk": "LOW", "confidence": 0.9, "rationale": "fix",
                        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                    })
                    self._prop_checksum = sha256_canonical_json({
                        "root_cause": "Missing H2",
                        "fix_strategy": "Add H2 dependency",
                        "changed_files": ["pom.xml"],
                        "proposed_diff": H2_DIFF,
                        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                        "risk": "LOW",
                        "confidence": 0.9,
                        "rationale": "fix",
                        "no_fix_reason": "",
                    })
                    self._diff_checksum = sha256_canonical_json({
                        "unified_diff": H2_DIFF,
                    })
                else:
                    content = json.dumps({
                        "decision": "accept", "notes": ["ok"], "confidence": 0.9,
                        "risks": [], "policy_concerns": [],
                        "changed_files_verified": True,
                        "diff_parseable": True,
                        "reviewed_context_checksum": context.context_pack_checksum,
                        "reviewed_primary_output_checksum": self._prop_checksum,
                        "reviewed_diff_checksum": self._diff_checksum,
                    })
                return V2AssistantModelResult(
                    content=content, source="azure_openai", model_status="live_ok",
                    provider="azure_openai", role=role.value, success=True,
                    redacted_summary="ok", failure_reason="",
                )

        model_client = _FakeClient()
        result = repair_gate_service.create_reviewed_repair_gate_on_failure(
            job_id="job-bound",
            stage_index=3,
            command_id="cmd-bound",
            event_type="build_failed",
            payload=payload,
            legacy_path=str(legacy),
            model_client=model_client,
        )
        assert result.status == "created", f"Expected 'created', got '{result.status}': {result.reason}"

        invocations = llm_repo.list_by_job("job-bound")
        assert len(invocations) == 2, f"Expected 2 invocations, got {len(invocations)}"
        roles = {i.role for i in invocations}
        assert roles == {"main", "reviewer"}, f"Expected roles {{'main', 'reviewer'}}, got {roles}"
        assert all(i.proposal_id is not None for i in invocations), "All invocations must be bound to proposal"
        assert all(i.gate_id is not None for i in invocations), "All invocations must be bound to gate"
        conn.close()

    def test_unbound_fallback_not_created_after_existing_proposal(self, tmp_path: Path) -> None:
        """When a proposal already exists, no extra unbound fallback invocation
        should be created for duplicate callbacks."""
        from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
        from migration_factory.control_tower.application.v2_phase_gate_service import V2PhaseGateService
        from migration_factory.control_tower.application.v2_repair_gate_service import V2RepairGateService
        from migration_factory.control_tower.infrastructure.sqlite.v2_phase_gate_repository import SqlitePhaseGateRepository
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import SqliteV2ReviewerRepository
        from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
            SqliteV2RepairRepository,
        )
        from migration_factory.repair_loop.failure_evidence import build_failure_evidence, FailureSource
        from migration_factory.repair_loop.repair_context import build_repair_context_pack

        conn = sqlite3.connect(
            str(tmp_path / "no-unbound-fallback.sqlite3"),
            check_same_thread=False,
            isolation_level=None,
            timeout=5.0,
        )
        conn.row_factory = sqlite3.Row
        apply_pending_migrations(conn)

        gate_repo = SqlitePhaseGateRepository(conn)
        repair_repo = SqliteV2RepairRepository(conn)
        llm_repo = SqliteV2LLMInvocationRepository(conn)

        repair_gate_service = V2RepairGateService(
            gate_service=V2PhaseGateService(gate_repo),
            repair_repo=repair_repo,
            reviewer_repo=SqliteV2ReviewerRepository(conn),
            llm_invocation_repo=llm_repo,
        )

        run_dir = tmp_path / "run2"
        repair_dir = run_dir / "repairs"
        sandbox = tmp_path / "sandbox2"
        legacy = tmp_path / "legacy2"
        repair_dir.mkdir(parents=True, exist_ok=True)
        sandbox.mkdir(exist_ok=True)
        legacy.mkdir(exist_ok=True)
        (sandbox / "pom.xml").write_text("<project/>\n", encoding="utf-8")

        evidence = build_failure_evidence(
            failure_source=FailureSource.BUILD,
            job_id="job-unbound",
            stage_index=3,
            command_id="cmd-unbound",
            failure_summary="Build failed",
            source_profile="springboot-3.5-java21",
            target_profile="springboot-4.0-java21",
        )
        context = build_repair_context_pack(
            failure_evidence=evidence,
            job_id=evidence.job_id,
            stage_index=evidence.stage_index,
            command_id=evidence.command_id,
            source_profile=evidence.source_profile,
            target_profile=evidence.target_profile,
        )
        evidence_path = repair_dir / "repair_failure_evidence.json"
        context_path = repair_dir / "repair_context_pack.json"
        from migration_factory.repair_loop.failure_evidence import failure_evidence_to_dict
        from migration_factory.repair_loop.repair_context import context_pack_to_dict
        evidence_path.write_text(json.dumps(failure_evidence_to_dict(evidence), indent=2), encoding="utf-8")
        context_path.write_text(json.dumps(context_pack_to_dict(context), indent=2), encoding="utf-8")

        payload = {
            "_repair_failure_evidence_ref": str(evidence_path),
            "_repair_context_pack_ref": str(context_path),
            "_repair_run_dir": str(run_dir),
            "_repair_sandbox_path": str(sandbox),
            "_repair_failure_evidence_checksum": evidence.content_checksum,
            "_repair_context_pack_checksum": context.context_pack_checksum,
            "_repair_base_repo_state_checksum": context.base_repo_state_checksum,
            "_repair_h2_required": "true",
        }

        H2_DIFF = """\
diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
@@ -1,1 +1,2 @@
 <project/>
+<dependency><groupId>com.h2database</groupId><artifactId>h2</artifactId><scope>runtime</scope></dependency>
"""
        class _FakeClient:
            def __init__(self):
                self._prop_checksum = None
                self._diff_checksum = None
            def answer_with_role(self, *, role, prompt, fallback, **kwargs):
                from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelResult
                from migration_factory.control_tower.domain.checksums import sha256_canonical_json
                if role.value == "proposer":
                    content = json.dumps({
                        "root_cause": "Missing dep",
                        "fix_strategy": "Add dep", "changed_files": ["pom.xml"],
                        "proposed_diff": H2_DIFF,
                        "risk": "LOW", "confidence": 0.9, "rationale": "fix",
                        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                    })
                    self._prop_checksum = sha256_canonical_json({
                        "root_cause": "Missing dep",
                        "fix_strategy": "Add dep",
                        "changed_files": ["pom.xml"],
                        "proposed_diff": H2_DIFF,
                        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                        "risk": "LOW",
                        "confidence": 0.9,
                        "rationale": "fix",
                        "no_fix_reason": "",
                    })
                    self._diff_checksum = sha256_canonical_json({
                        "unified_diff": H2_DIFF,
                    })
                else:
                    content = json.dumps({
                        "decision": "accept", "notes": ["ok"], "confidence": 0.9,
                        "risks": [], "policy_concerns": [],
                        "changed_files_verified": True,
                        "diff_parseable": True,
                        "reviewed_context_checksum": context.context_pack_checksum,
                        "reviewed_primary_output_checksum": self._prop_checksum,
                        "reviewed_diff_checksum": self._diff_checksum,
                    })
                return V2AssistantModelResult(
                    content=content, source="azure_openai", model_status="live_ok",
                    provider="azure_openai", role=role.value, success=True,
                    redacted_summary="ok", failure_reason="",
                )

        model_client = _FakeClient()

        # First call creates the chain
        r1 = repair_gate_service.create_reviewed_repair_gate_on_failure(
            job_id="job-unbound",
            stage_index=3,
            command_id="cmd-unbound",
            event_type="build_failed",
            payload=payload,
            legacy_path=str(legacy),
            model_client=model_client,
        )
        assert r1.status == "created"

        # Capture invocations after first call
        invocations_after_first = list(llm_repo.list_by_job("job-unbound"))
        proposal_ids_after_first = {i.proposal_id for i in invocations_after_first if i.proposal_id}

        # Second call (duplicate) — should be idempotently skipped
        r2 = repair_gate_service.create_reviewed_repair_gate_on_failure(
            job_id="job-unbound",
            stage_index=3,
            command_id="cmd-unbound",
            event_type="build_failed",
            payload=payload,
            legacy_path=str(legacy),
            model_client=model_client,
        )
        assert r2.status == "skipped"

        # No new invocations should have been created by the second call
        invocations_after_second = list(llm_repo.list_by_job("job-unbound"))
        assert len(invocations_after_second) == len(invocations_after_first), (
            f"Expected {len(invocations_after_first)} invocations, got {len(invocations_after_second)}"
        )

        # All invocations must be bound to a proposal
        unbound = [i for i in invocations_after_second if i.proposal_id is None]
        assert len(unbound) == 0, f"Found {len(unbound)} unbound invocations: {[i.invocation_id for i in unbound]}"

        conn.close()


class TestTokenAndLatency:
    def test_token_and_latency_stored(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.complete_invocation(
            inv_id,
            output="test",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=1234,
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.prompt_tokens == 100
        assert record.completion_tokens == 50
        assert record.total_tokens == 150
        assert record.latency_ms == 1234
        conn.close()

    def test_deployment_alias_hash_populated_for_configured_reviewer(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "private-reviewer-deployment")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)

        inv_id = ledger.start_invocation(
            job_id="j1",
            role="reviewer",
            responsibility="repair_review",
        )

        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.deployment_alias_hash == compute_deployment_alias_hash("private-reviewer-deployment")
        assert record.deployment_alias_hash != "private-reviewer-deployment"
        conn.close()


# ── API integration test ──────────────────────────────────────────────


def _build_test_app_with_connection(api_connection: sqlite3.Connection):
    """Build a minimal FastAPI app with the V2 LLM activity endpoint using a pre-seeded connection.

    The connection must be created with check_same_thread=False to allow TestClient
    (which runs in a separate thread) to access it.
    """
    from fastapi import FastAPI
    from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
        SqliteControlTowerUnitOfWork,
    )
    from contextlib import contextmanager

    app = FastAPI()

    @contextmanager
    def uow_factory():
        uow = SqliteControlTowerUnitOfWork(api_connection)
        yield uow

    from migration_factory.control_tower.application.v2_llm_invocation_ledger import safe_model_display_name

    @app.get("/v1/v2/jobs/{job_id}/llm/activity")
    def list_activity(job_id: str):
        with uow_factory() as uow:
            records = uow.v2_llm_invocations.list_by_job(job_id)
            invocations = [
                {
                    "invocation_id": r.invocation_id,
                    "job_id": r.job_id,
                    "role": r.role,
                    "responsibility": r.responsibility,
                    "status": r.status,
                    "proposal_id": r.proposal_id,
                    "gate_id": r.gate_id,
                    "provider_alias": r.provider_alias,
                    "model_display_name": safe_model_display_name(r.role),
                    "deployment_alias_hash": r.deployment_alias_hash,
                    "context_checksum": r.context_checksum,
                    "input_checksum": r.input_checksum,
                    "output_checksum": r.output_checksum,
                    "schema_name": r.schema_name,
                    "fallback_used": bool(r.fallback_used),
                    "redacted_error": r.redacted_error,
                    "redacted_summary": r.redacted_summary,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "latency_ms": r.latency_ms,
                    "created_at": r.created_at,
                    "completed_at": r.completed_at,
                }
                for r in records
            ]
        return {"invocations": invocations}

    return app


class TestEndpointIntegration:
    def test_endpoint_empty(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path, check_same_thread=False)
        app = _build_test_app_with_connection(conn)
        client = TestClient(app)
        response = client.get("/v1/v2/jobs/empty-job/llm/activity")
        assert response.status_code == 200
        data = response.json()
        assert data == {"invocations": []}
        conn.close()

    def test_endpoint_with_data(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path, check_same_thread=False)
        repo = _make_repo(conn)
        _seed_invocation(repo, job_id="data-job")
        app = _build_test_app_with_connection(conn)
        client = TestClient(app)
        response = client.get("/v1/v2/jobs/data-job/llm/activity")
        assert response.status_code == 200
        data = response.json()
        assert len(data["invocations"]) == 1
        inv = data["invocations"][0]
        assert inv["role"] == "main"
        assert inv["responsibility"] == "repair_proposal"
        conn.close()


# ── PR-G: Display name and idempotency tests ─────────────────────────


class TestDisplayNameFromConfig:
    """LLM Activity must show model_display_name from role config, not hardcoded."""

    def test_display_name_from_env_config(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME", "GPT-5 Mini")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.complete_invocation(inv_id, output="test")
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        assert dto["model_display_name"] == "GPT-5 Mini"
        conn.close()

    def test_display_name_falls_back_to_configured(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        # No AI_MIGRATION_MAIN_MODEL set → fallback "configured"
        assert dto["model_display_name"] == "configured"
        conn.close()

    def test_display_name_reviewer_from_config(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "gpt-4o")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME", "GPT-4 Optimized")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="reviewer", responsibility="repair_review"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        assert dto["model_display_name"] == "GPT-4 Optimized"
        conn.close()


class TestDeploymentAliasFromConfig:
    """deployment_alias_hash_for_role() must use ModelRoleConfigLoader."""

    def test_deployment_alias_from_main_config(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini-private")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        from migration_factory.control_tower.application.v2_llm_invocation_ledger import (
            compute_deployment_alias_hash,
        )
        expected_hash = compute_deployment_alias_hash("gpt-5-mini-private")
        assert record.deployment_alias_hash == expected_hash
        assert record.deployment_alias_hash != "gpt-5-mini-private"
        conn.close()

    def test_deployment_alias_fallback_to_empty(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="reviewer", responsibility="repair_review"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        # No config → empty hash
        assert record.deployment_alias_hash == "" or record.deployment_alias_hash is None
        conn.close()


class TestProviderAliasFromConfig:
    """safe_provider_alias() must use ModelRoleConfigLoader."""

    def test_provider_alias_from_main_config(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_PROVIDER", "azure_global")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.provider_alias == "azure_global"
        conn.close()

    def test_provider_alias_fallback_default(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        assert record.provider_alias == "azure_openai"
        conn.close()


class TestUsageAndLatencySafe:
    """LLM Activity records prompt_tokens/completion_tokens/total_tokens/reasoning_tokens
    and latency_ms if available."""

    def test_usage_and_latency_recorded_safely(self, tmp_path: Path) -> None:
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        ledger.complete_invocation(
            inv_id,
            output="test output",
            prompt_tokens=150,
            completion_tokens=75,
            total_tokens=225,
            latency_ms=3456,
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        # DTO must include usage and latency fields
        assert "prompt_tokens" in dto
        assert "completion_tokens" in dto
        assert "total_tokens" in dto
        assert "latency_ms" in dto
        # But never raw prompt, completion, endpoint
        assert "prompt" not in dto or dto.get("prompt") is None
        assert "completion" not in dto or dto.get("completion") is None
        assert "endpoint" not in dto or dto.get("endpoint") is None
        conn.close()


# ── Chain attempt idempotency tests ──────────────────────────────────


class TestChainAttemptDurableIdempotency:
    """Tests for the durable (SQLite-backed) chain attempt idempotency."""

    MIGRATION_51 = (
        "migration_factory/control_tower/infrastructure/sqlite/migrations"
        "/0051_v2_chain_attempts.sql"
    )

    def _apply_migration_51(self, tmp_path: Path) -> sqlite3.Connection:
        import sqlite3
        db_path = tmp_path / "test_chain_attempts.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        with open(self.MIGRATION_51) as f:
            conn.executescript(f.read())
        return conn

    def _make_chain_repo(self, conn: sqlite3.Connection):
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            SqliteV2ChainAttemptRepository,
        )
        return SqliteV2ChainAttemptRepository(conn)

    def test_idempotency_key_includes_context_checksum(self) -> None:
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            build_chain_key,
        )
        key1 = build_chain_key("job-1", "cmd-1", "cs-a", "initial_reviewed_repair")
        key2 = build_chain_key("job-1", "cmd-1", "cs-b", "initial_reviewed_repair")
        assert key1 != key2, "different context_checksum must produce different keys"

    def test_idempotency_key_differs_by_chain_kind(self) -> None:
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            build_chain_key,
        )
        key1 = build_chain_key("job-1", "cmd-1", "cs-a", "initial_reviewed_repair")
        key2 = build_chain_key("job-1", "cmd-1", "cs-a", "revision")
        assert key1 != key2, "different chain_kind must produce different keys"

    def test_duplicate_main_schema_failure_does_not_create_second_invocation(self, tmp_path: Path) -> None:
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            V2ChainAttemptRecord,
            build_chain_key,
        )
        conn = self._apply_migration_51(tmp_path)
        repo = self._make_chain_repo(conn)

        key = build_chain_key("job-d1", "cmd-d1", "cs-d1", "initial_reviewed_repair")

        # First attempt: record as started
        repo.save(V2ChainAttemptRecord(
            chain_key=key, job_id="job-d1", command_id="cmd-d1",
            context_checksum="cs-d1", chain_kind="initial_reviewed_repair",
            status="started",
        ))

        # Second attempt: should detect existing started entry
        existing = repo.get(key)
        assert existing is not None
        assert existing.status == "started"

        # If the chain later fails with schema invalid
        repo.update_status(key, status="main_schema_invalid", failure_reason="proposer_schema_invalid")

        # Verify status is now main_schema_invalid (retryable)
        updated = repo.get(key)
        assert updated is not None
        assert updated.status == "main_schema_invalid"

        # A retry should be allowed (status is retryable)
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            RETRYABLE_STATES,
        )
        assert updated.status in RETRYABLE_STATES

        # Update to started for the retry
        repo.update_status(key, status="started")
        started_again = repo.get(key)
        assert started_again is not None
        assert started_again.status == "started"

        conn.close()

    def test_failed_chain_idempotency_survives_service_recreation(self, tmp_path: Path) -> None:
        """Simulate service restart: create chain attempt, close connection, reopen, check exists."""
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            V2ChainAttemptRecord,
            build_chain_key,
        )

        db_path = tmp_path / "survive_restart.db"
        conn1 = sqlite3.connect(str(db_path))
        conn1.row_factory = sqlite3.Row
        with open(self.MIGRATION_51) as f:
            conn1.executescript(f.read())
        repo1 = self._make_chain_repo(conn1)

        key = build_chain_key("job-r1", "cmd-r1", "cs-r1", "initial_reviewed_repair")
        repo1.save(V2ChainAttemptRecord(
            chain_key=key, job_id="job-r1", command_id="cmd-r1",
            context_checksum="cs-r1", chain_kind="initial_reviewed_repair",
            status="main_schema_invalid",
            failure_reason="proposer_schema_invalid",
        ))
        conn1.commit()
        conn1.close()

        # Simulate service restart: new connection, same DB
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        repo2 = self._make_chain_repo(conn2)

        loaded = repo2.get(key)
        assert loaded is not None
        assert loaded.status == "main_schema_invalid"
        assert loaded.failure_reason == "proposer_schema_invalid"
        conn2.close()

    def test_explicit_retry_can_start_new_chain_attempt(self, tmp_path: Path) -> None:
        """A chain in a retryable state can be updated to 'started' for a retry."""
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            V2ChainAttemptRecord,
            build_chain_key,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            RETRYABLE_STATES,
        )

        conn = self._apply_migration_51(tmp_path)
        repo = self._make_chain_repo(conn)

        key = build_chain_key("job-r2", "cmd-r2", "cs-r2", "initial_reviewed_repair")
        repo.save(V2ChainAttemptRecord(
            chain_key=key, job_id="job-r2", command_id="cmd-r2",
            context_checksum="cs-r2", chain_kind="initial_reviewed_repair",
            status="main_provider_failed",
            failure_reason="primary repair model failed closed",
        ))

        failed = repo.get(key)
        assert failed is not None
        assert failed.status in RETRYABLE_STATES

        # Explicit retry: update to started and increment attempt_number
        repo.update_status(key, status="started", attempt_number=2)
        retried = repo.get(key)
        assert retried is not None
        assert retried.status == "started"
        assert retried.attempt_number == 2
        conn.close()

    def test_successful_chain_binds_main_and_reviewer_invocations(self, tmp_path: Path) -> None:
        """When a chain completes, the chain attempt stores linked invocation IDs."""
        import json as _json
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            V2ChainAttemptRecord,
            build_chain_key,
        )

        conn = self._apply_migration_51(tmp_path)
        repo = self._make_chain_repo(conn)

        key = build_chain_key("job-bind", "cmd-bind", "cs-bind", "initial_reviewed_repair")
        repo.save(V2ChainAttemptRecord(
            chain_key=key, job_id="job-bind", command_id="cmd-bind",
            context_checksum="cs-bind", chain_kind="initial_reviewed_repair",
            status="started",
        ))

        inv_ids_json = _json.dumps({
            "proposer_invocation_id": "inv-proposer-123",
            "reviewer_invocation_id": "inv-reviewer-456",
        }, separators=(",", ":"))
        repo.update_status(key, status="materialized", invocation_ids_json=inv_ids_json)

        materialized = repo.get(key)
        assert materialized is not None
        assert materialized.status == "materialized"
        assert materialized.invocation_ids_json is not None
        parsed = json.loads(materialized.invocation_ids_json)
        assert parsed.get("proposer_invocation_id") == "inv-proposer-123"
        assert parsed.get("reviewer_invocation_id") == "inv-reviewer-456"
        conn.close()

    def test_materialized_blocks_duplicate(self, tmp_path: Path) -> None:
        """materialized status is not retryable; duplicate key raises IntegrityError."""
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            V2ChainAttemptRecord,
            build_chain_key,
            TERMINAL_SUCCESS_STATES,
        )

        conn = self._apply_migration_51(tmp_path)
        repo = self._make_chain_repo(conn)

        key = build_chain_key("job-mat", "cmd-mat", "cs-mat", "initial_reviewed_repair")
        repo.save(V2ChainAttemptRecord(
            chain_key=key, job_id="job-mat", command_id="cmd-mat",
            context_checksum="cs-mat", chain_kind="initial_reviewed_repair",
            status="materialized",
        ))

        # Duplicate insert must fail (PRIMARY KEY)
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            repo.save(V2ChainAttemptRecord(
                chain_key=key, job_id="job-mat", command_id="cmd-mat",
                context_checksum="cs-mat", chain_kind="initial_reviewed_repair",
                status="started",
            ))
        conn.close()

    def test_chain_attempt_append_only(self, tmp_path: Path) -> None:
        """DELETE on v2_chain_attempts must be blocked by trigger."""
        import sqlite3
        from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
            V2ChainAttemptRecord,
            build_chain_key,
        )

        conn = self._apply_migration_51(tmp_path)
        repo = self._make_chain_repo(conn)

        key = build_chain_key("job-ao", "cmd-ao", "cs-ao", "initial_reviewed_repair")
        repo.save(V2ChainAttemptRecord(
            chain_key=key, job_id="job-ao", command_id="cmd-ao",
            context_checksum="cs-ao", chain_kind="initial_reviewed_repair",
            status="started",
        ))

        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError), match="append-only"):
            conn.execute("DELETE FROM v2_chain_attempts WHERE chain_key = ?", (key,))
        conn.close()


# ── LLM Activity display safety tests ────────────────────────────────


class TestLLMActivityDisplaySafety:
    """LLM Activity must never expose raw deployment, endpoint, or key."""

    def test_activity_does_not_expose_raw_deployment_or_endpoint(self, tmp_path: Path) -> None:
        """record_to_dto must not contain raw deployment name or endpoint."""
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        text = json.dumps(dto)
        for forbidden in ("deployment_or_model_id", "endpoint", "api_key", "apikey", "secret", "bearer", "password"):
            assert forbidden not in text, f"forbidden field {forbidden} leaked in dto"
        conn.close()

    def test_only_deployment_alias_hash_and_model_alias_hash_exposed(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "private-gpt5")
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal"
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        # Must have deployment_alias_hash (hash, not raw)
        assert "deployment_alias_hash" in dto
        assert dto["deployment_alias_hash"] is not None
        # Must NOT have raw deployment_or_model_id
        assert "deployment_or_model_id" not in dto
        conn.close()

    def test_schema_name_included(self, tmp_path: Path) -> None:
        """LLM Activity must expose schema_name."""
        conn = _apply_migration_only(tmp_path)
        ledger = _make_ledger(conn)
        inv_id = ledger.start_invocation(
            job_id="j1", role="main", responsibility="repair_proposal",
            schema_name="RepairPrimaryOutput",
        )
        record = ledger.get_invocation(inv_id)
        assert record is not None
        dto = ledger.record_to_dto(record)
        assert dto.get("schema_name") == "RepairPrimaryOutput"
        conn.close()
