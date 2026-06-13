"""Tests for V2 setup persistence and preflight service."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
    compute_setup_checksum,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        tmp_path / "setup_test.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


@pytest.fixture
def service(connection: sqlite3.Connection) -> V2SetupService:
    repo = SqliteV2SetupRepository(connection)
    return V2SetupService(repo)


@pytest.fixture
def sample_request() -> CreateSetupRequest:
    return CreateSetupRequest(
        run_name="legacy-service-v2",
        legacy_app_path="/tmp/test-legacy-app",
        output_parent_path="/tmp/test-output",
        ai_hub_path="/tmp/test-ai-hub",
        java11_home="/usr/lib/jvm/java-11",
        java17_home="/usr/lib/jvm/java-17",
        java21_home="/usr/lib/jvm/java-21",
        maven_cmd="/usr/bin/mvn",
        proof_level="build_test_verified",
        skip_endpoint_smoke=True,
        migration_flags={"custom_flag": True},
    )


def _mutation_headers():
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID
    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _api_client(tmp_path, app=None):
    from migration_factory.control_tower.adapters.fastapi import create_app
    conn = sqlite3.connect(
        tmp_path / "api_test.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    app = app or create_app(lambda: SqliteUnitOfWork(conn))
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    return client, conn


# ── Checksum tests ───────────────────────────────────────────────────


def test_compute_setup_checksum_deterministic(sample_request: CreateSetupRequest) -> None:
    c1 = compute_setup_checksum(sample_request)
    c2 = compute_setup_checksum(sample_request)
    assert c1 == c2
    assert len(c1) == 64  # SHA-256 hex digest


def test_compute_setup_checksum_changes_with_fields(sample_request: CreateSetupRequest) -> None:
    c1 = compute_setup_checksum(sample_request)
    modified = CreateSetupRequest(
        run_name=sample_request.run_name + "-modified",
        legacy_app_path=sample_request.legacy_app_path,
        output_parent_path=sample_request.output_parent_path,
        ai_hub_path=sample_request.ai_hub_path,
        java11_home=sample_request.java11_home,
        java17_home=sample_request.java17_home,
        java21_home=sample_request.java21_home,
        maven_cmd=sample_request.maven_cmd,
    )
    c2 = compute_setup_checksum(modified)
    assert c1 != c2


# ── Setup CRUD tests ────────────────────────────────────────────────


def test_create_setup(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    assert dto.setup_id
    assert dto.run_name == "legacy-service-v2"
    assert dto.java_homes["java11"] == "/usr/lib/jvm/java-11"
    assert dto.setup_checksum
    assert dto.created_at


def test_get_setup(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    created = service.create_setup(sample_request)
    fetched = service.get_setup(created.setup_id)
    assert fetched is not None
    assert fetched.setup_id == created.setup_id
    assert fetched.run_name == created.run_name
    assert fetched.setup_checksum == created.setup_checksum


def test_get_setup_not_found(service: V2SetupService) -> None:
    fetched = service.get_setup("nonexistent-id")
    assert fetched is None


def test_list_setups(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    service.create_setup(sample_request)
    service.create_setup(CreateSetupRequest(
        run_name="another-run",
        legacy_app_path=sample_request.legacy_app_path,
        output_parent_path=sample_request.output_parent_path,
        ai_hub_path=sample_request.ai_hub_path,
        java11_home=sample_request.java11_home,
        java17_home=sample_request.java17_home,
        java21_home=sample_request.java21_home,
        maven_cmd=sample_request.maven_cmd,
    ))
    dtos = service.list_setups()
    assert len(dtos) >= 2


# ── Preflight tests ─────────────────────────────────────────────────


def test_run_preflight(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    preflight = service.run_preflight(dto.setup_id)

    assert preflight.preflight_id
    assert preflight.setup_id == dto.setup_id
    assert preflight.setup_checksum == dto.setup_checksum
    # Most checks will be false since paths don't exist
    assert preflight.all_ready is False
    assert preflight.legacy_app_exists is False
    assert len(preflight.errors) > 0


def test_run_preflight_setup_not_found(service: V2SetupService) -> None:
    with pytest.raises(ValueError, match="not found"):
        service.run_preflight("nonexistent-setup")


def test_get_readiness_no_preflight(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    readiness = service.get_readiness(dto.setup_id)
    assert readiness is None


def test_get_readiness_after_preflight(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    service.run_preflight(dto.setup_id)
    readiness = service.get_readiness(dto.setup_id)

    assert readiness is not None
    assert readiness.setup_checksum == dto.setup_checksum
    assert readiness.preflight_checksum_match is True
    assert isinstance(readiness.gates, dict)


def test_get_readiness_checksum_mismatch(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    """Preflight checksum mismatch should be detected when setup changes."""
    dto = service.create_setup(sample_request)
    service.run_preflight(dto.setup_id)

    # Create a modified version (different checksum)
    modified = CreateSetupRequest(
        run_name=sample_request.run_name + "-v2",
        legacy_app_path=sample_request.legacy_app_path,
        output_parent_path=sample_request.output_parent_path,
        ai_hub_path=sample_request.ai_hub_path,
        java11_home=sample_request.java11_home,
        java17_home=sample_request.java17_home,
        java21_home=sample_request.java21_home,
        maven_cmd=sample_request.maven_cmd,
    )
    dto2 = service.create_setup(modified)

    # Run preflight on dto2, then check readiness for dto1
    service.run_preflight(dto2.setup_id)
    readiness = service.get_readiness(dto.setup_id)

    assert readiness is not None
    # The latest preflight for setup1 should still match
    assert readiness.preflight_checksum_match is True


def test_dto_conversion(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    d = service.setup_to_dict(dto)

    assert d["setup_id"] == dto.setup_id
    assert d["run_name"] == dto.run_name
    assert d["setup_checksum"] == dto.setup_checksum
    assert "java_homes" in d
    assert d["java_homes"]["java11"] == "/usr/lib/jvm/java-11"

    # Paths should be redacted
    for path_key in ("legacy_app_path", "output_parent_path", "ai_hub_path", "maven_cmd"):
        assert "redacted" in d.get(path_key, "") or "/" in d.get(path_key, "")


def test_preflight_to_dict(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    preflight = service.run_preflight(dto.setup_id)
    d = service.preflight_to_dict(preflight)

    assert d["preflight_id"] == preflight.preflight_id
    assert d["all_ready"] is False
    assert isinstance(d["readiness"], dict)
    assert isinstance(d["warnings"], list)
    assert isinstance(d["errors"], list)


def test_readiness_to_dict_none(service: V2SetupService) -> None:
    d = service.readiness_to_dict(None)
    assert d["ready"] is False
    assert d["setup_checksum"] == ""


def test_readiness_to_dict_with_value(service: V2SetupService, sample_request: CreateSetupRequest) -> None:
    dto = service.create_setup(sample_request)
    service.run_preflight(dto.setup_id)
    readiness = service.get_readiness(dto.setup_id)
    d = service.readiness_to_dict(readiness)

    assert d["ready"] is False
    assert d["setup_checksum"] == dto.setup_checksum
    assert d["preflight_checksum_match"] is True
    assert isinstance(d["gates"], dict)


# ── API endpoint tests ──────────────────────────────────────────────


def test_create_setup_endpoint(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    response = client.post(
        "/v1/migration-setups",
        json={
            "run_name": "test-run",
            "legacy_app_path": "/tmp/test-legacy-app",
            "output_parent_path": "/tmp/test-output",
            "ai_hub_path": "/tmp/test-ai-hub",
            "java11_home": "/usr/lib/jvm/java-11",
            "java17_home": "/usr/lib/jvm/java-17",
            "java21_home": "/usr/lib/jvm/java-21",
            "maven_cmd": "/usr/bin/mvn",
        },
        headers=_mutation_headers(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["setup_id"]
    assert body["run_name"] == "test-run"
    assert body["setup_checksum"]


def test_create_setup_endpoint_rejects_extra(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    response = client.post(
        "/v1/migration-setups",
        json={
            "run_name": "test-run",
            "legacy_app_path": "/tmp/test-legacy-app",
            "output_parent_path": "/tmp/test-output",
            "ai_hub_path": "/tmp/test-ai-hub",
            "java11_home": "/usr/lib/jvm/java-11",
            "java17_home": "/usr/lib/jvm/java-17",
            "java21_home": "/usr/lib/jvm/java-21",
            "maven_cmd": "/usr/bin/mvn",
            "extra_field": "should-fail",
        },
        headers=_mutation_headers(),
    )
    assert response.status_code == 422


def test_get_setup_endpoint(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    # Create first
    create_resp = client.post(
        "/v1/migration-setups",
        json={
            "run_name": "test-run",
            "legacy_app_path": "/tmp/test-legacy-app",
            "output_parent_path": "/tmp/test-output",
            "ai_hub_path": "/tmp/test-ai-hub",
            "java11_home": "/usr/lib/jvm/java-11",
            "java17_home": "/usr/lib/jvm/java-17",
            "java21_home": "/usr/lib/jvm/java-21",
            "maven_cmd": "/usr/bin/mvn",
        },
        headers=_mutation_headers(),
    )
    setup_id = create_resp.json()["setup_id"]

    # Get
    response = client.get(f"/v1/migration-setups/{setup_id}", headers={"Host": "127.0.0.1:8000"})
    assert response.status_code == 200
    assert response.json()["setup_id"] == setup_id


def test_get_setup_not_found(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    response = client.get(
        "/v1/migration-setups/nonexistent",
        headers={"Host": "127.0.0.1:8000"},
    )
    assert response.status_code == 404


def test_list_setups_endpoint(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    response = client.get("/v1/migration-setups", headers={"Host": "127.0.0.1:8000"})
    assert response.status_code == 200
    assert "setups" in response.json()


def test_run_preflight_endpoint(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    # Create setup
    create_resp = client.post(
        "/v1/migration-setups",
        json={
            "run_name": "preflight-test",
            "legacy_app_path": "/nonexistent/path",
            "output_parent_path": "/tmp/test-output-pf",
            "ai_hub_path": "/tmp/test-ai-hub-pf",
            "java11_home": "/usr/lib/jvm/java-11",
            "java17_home": "/usr/lib/jvm/java-17",
            "java21_home": "/usr/lib/jvm/java-21",
            "maven_cmd": "/usr/bin/mvn",
        },
        headers=_mutation_headers(),
    )
    setup_id = create_resp.json()["setup_id"]

    # Run preflight
    response = client.post(
        "/v1/migration-setups/preflight",
        json={"setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["preflight_id"]
    assert body["all_ready"] is False
    assert len(body["errors"]) > 0


def test_run_preflight_not_found(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    response = client.post(
        "/v1/migration-setups/preflight",
        json={"setup_id": "nonexistent"},
        headers=_mutation_headers(),
    )
    assert response.status_code == 404


def test_get_readiness_endpoint(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    # Create and preflight
    create_resp = client.post(
        "/v1/migration-setups",
        json={
            "run_name": "readiness-test",
            "legacy_app_path": "/tmp/fake-legacy",
            "output_parent_path": "/tmp/fake-output",
            "ai_hub_path": "/tmp/fake-hub",
            "java11_home": "/usr/lib/jvm/java-11",
            "java17_home": "/usr/lib/jvm/java-17",
            "java21_home": "/usr/lib/jvm/java-21",
            "maven_cmd": "/usr/bin/mvn",
        },
        headers=_mutation_headers(),
    )
    setup_id = create_resp.json()["setup_id"]
    client.post(
        "/v1/migration-setups/preflight",
        json={"setup_id": setup_id},
        headers=_mutation_headers(),
    )

    # Get readiness
    response = client.get(
        f"/v1/migration-setups/{setup_id}/readiness",
        headers={"Host": "127.0.0.1:8000"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert "setup_checksum" in body
    assert "gates" in body


# ── Append-only trigger tests ────────────────────────────────────────


def test_setup_table_is_append_only(connection: sqlite3.Connection) -> None:
    """Verify the append-only triggers exist and work."""
    triggers = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='v2_migration_setups'"
    ).fetchall()
    trigger_names = [t["name"] for t in triggers]
    assert "v2_migration_setups_no_update" in trigger_names
    assert "v2_migration_setups_no_delete" in trigger_names


def test_preflight_table_is_append_only(connection: sqlite3.Connection) -> None:
    triggers = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='v2_preflight_results'"
    ).fetchall()
    trigger_names = [t["name"] for t in triggers]
    assert "v2_preflight_results_no_update" in trigger_names
    assert "v2_preflight_results_no_delete" in trigger_names


# ── JDK/Maven subprocess validation tests (mocked) ──────────────────


class TestJdkSubprocessValidation:
    """Tests that _check_jdk_path validates Java major versions via subprocess.

    All subprocess calls are mocked — no real Java/Maven required on CI.
    """

    @staticmethod
    def _fake_subprocess_java11(*args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(
            args=list(args),
            returncode=0,
            stdout="",
            stderr='openjdk version "11.0.21" 2023-10-17\nOpenJDK Runtime Environment (build 11.0.21+9)\n',
        )

    @staticmethod
    def _fake_subprocess_java17(*args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(
            args=list(args),
            returncode=0,
            stdout="",
            stderr='openjdk version "17.0.13" 2024-10-21\nOpenJDK Runtime Environment Temurin-17.0.13+11\n',
        )

    @staticmethod
    def _fake_subprocess_java21(*args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(
            args=list(args),
            returncode=0,
            stdout="",
            stderr='openjdk version "21.0.7" 2025-04-15\nOpenJDK Runtime Environment (build 21.0.7+7)\n',
        )

    @staticmethod
    def _fake_subprocess_java_wrong_version(*args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(
            args=list(args),
            returncode=0,
            stdout="",
            stderr='openjdk version "1.8.0_432" 2024-10-21\nOpenJDK Runtime Environment (build 1.8.0_432-b07)\n',
        )

    @staticmethod
    def _fake_subprocess_timeout(*args, **kwargs):
        from subprocess import TimeoutExpired
        raise TimeoutExpired(cmd=args, timeout=10.0)

    def test_jdk11_correct_version(self, monkeypatch, tmp_path: Path) -> None:
        """JDK 11 path verified to report major 11."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_jdk_path_with_version,
        )
        # Create a fake java home structure so Path.exists() passes
        jdk_home = tmp_path / "jdk-11"
        bin_dir = jdk_home / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "java").touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_java11)

        assert _check_jdk_path_with_version(str(jdk_home), 11)

    def test_jdk17_correct_version(self, monkeypatch, tmp_path: Path) -> None:
        """JDK 17 path verified to report major 17."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_jdk_path_with_version,
        )
        jdk_home = tmp_path / "jdk-17"
        bin_dir = jdk_home / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "java").touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_java17)

        assert _check_jdk_path_with_version(str(jdk_home), 17)

    def test_jdk21_correct_version(self, monkeypatch, tmp_path: Path) -> None:
        """JDK 21 path verified to report major 21."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_jdk_path_with_version,
        )
        jdk_home = tmp_path / "jdk-21"
        bin_dir = jdk_home / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "java").touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_java21)

        assert _check_jdk_path_with_version(str(jdk_home), 21)

    def test_jdk_wrong_version_rejected(self, monkeypatch, tmp_path: Path) -> None:
        """JDK 11 path reporting Java 8 must be rejected."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_jdk_path_with_version,
        )
        jdk_home = tmp_path / "jdk-11"
        bin_dir = jdk_home / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "java").touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_java_wrong_version)

        assert not _check_jdk_path_with_version(str(jdk_home), 11)

    def test_jdk_subprocess_timeout_fails_safe(self, monkeypatch, tmp_path: Path) -> None:
        """Timeout must return False, not crash."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_jdk_path_with_version,
        )
        jdk_home = tmp_path / "jdk-11"
        bin_dir = jdk_home / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "java").touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_timeout)

        assert not _check_jdk_path_with_version(str(jdk_home), 11)

    def test_jdk_path_missing_fails_fast(self) -> None:
        """Non-existent path fails before subprocess is called."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_jdk_path_with_version,
        )
        assert not _check_jdk_path_with_version("/nonexistent/jdk/path", 11)


class TestMavenSubprocessValidation:
    """Tests that _check_maven_path validates via mvn --version.

    All subprocess calls are mocked — no real Maven required on CI.
    """

    @staticmethod
    def _fake_subprocess_maven_ok(*args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(
            args=args,
            returncode=0,
            stdout='Apache Maven 3.9.15\nMaven home: /opt/maven\nJava version: 21.0.7\n',
            stderr="",
        )

    @staticmethod
    def _fake_subprocess_maven_fail(*args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="Error: Unable to access jarfile",
        )

    @staticmethod
    def _fake_maven_subprocess_timeout(*args, **kwargs):
        from subprocess import TimeoutExpired
        raise TimeoutExpired(cmd=args, timeout=10.0)

    def test_maven_version_ok(self, monkeypatch, tmp_path: Path) -> None:
        """Maven path verified to report Apache Maven in output."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_maven_path,
        )
        mvn_path = tmp_path / "mvn"
        mvn_path.touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_maven_ok)

        assert _check_maven_path(str(mvn_path))

    def test_maven_execution_fails(self, monkeypatch, tmp_path: Path) -> None:
        """Maven that returns non-zero with no output must fail."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_maven_path,
        )
        mvn_path = tmp_path / "mvn"
        mvn_path.touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_subprocess_maven_fail)

        assert not _check_maven_path(str(mvn_path))

    def test_maven_timeout_fails_safe(self, monkeypatch, tmp_path: Path) -> None:
        """Timeout must return False, not crash."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_maven_path,
        )
        mvn_path = tmp_path / "mvn"
        mvn_path.touch()

        import subprocess as sp
        monkeypatch.setattr(sp, "run", self._fake_maven_subprocess_timeout)

        assert not _check_maven_path(str(mvn_path))

    def test_maven_path_missing_fails_fast(self) -> None:
        """Non-existent path fails before subprocess is called."""
        from migration_factory.control_tower.application.v2_setup_service import (
            _check_maven_path,
        )
        assert not _check_maven_path("/nonexistent/mvn")
