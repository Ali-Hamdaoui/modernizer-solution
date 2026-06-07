from __future__ import annotations

import json
from pathlib import Path

from migration_factory.wave_planner import (
    build_consumer_validation_config,
    load_consumer_validation_gate_config,
    plan_migration_wave,
)


def test_wave_planner_detects_coordinates_and_parent_managed_values(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = parent / "child"
    _write_pom(
        parent / "pom.xml",
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
</project>
""",
    )
    _write_pom(
        child / "pom.xml",
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>com.example</groupId>
    <artifactId>parent</artifactId>
    <version>1.0.0</version>
    <relativePath>../pom.xml</relativePath>
  </parent>
  <artifactId>child-lib</artifactId>
</project>
""",
    )

    result = plan_migration_wave([{"path": child, "project_id": "child"}], output_dir=tmp_path / "out")
    payload = result["payload"]

    assert payload["detected_coordinates"]["child"]["groupId"] == "com.example"
    assert payload["detected_coordinates"]["child"]["artifactId"] == "child-lib"
    assert payload["detected_coordinates"]["child"]["version"] == "1.0.0"
    assert Path(result["report_path"]).is_file()
    assert Path(result["summary_path"]).is_file()


def test_wave_planner_detects_internal_dependency_and_orders_producer_first(tmp_path: Path) -> None:
    producer = tmp_path / "producer"
    consumer = tmp_path / "consumer"
    _write_simple_project(producer, artifact_id="producer-lib")
    _write_pom(
        consumer / "pom.xml",
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>consumer-app</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>producer-lib</artifactId>
      <version>1.0.0</version>
      <scope>compile</scope>
    </dependency>
  </dependencies>
</project>
""",
    )

    result = plan_migration_wave(
        [
            {"path": consumer, "project_id": "consumer"},
            {"path": producer, "project_id": "producer"},
        ],
        output_dir=tmp_path / "out",
    )
    payload = result["payload"]

    assert payload["internal_dependency_edges"] == [
        {
            "consumer_project_id": "consumer",
            "producer_project_id": "producer",
            "scope": "compile",
            "version": "1.0.0",
        }
    ]
    assert payload["migration_waves"][0] == ["producer"]
    assert payload["migration_waves"][1] == ["consumer"]
    assert payload["consumer_validation_plan"][0]["migrated_project"] == "consumer"
    producer_plan = next(item for item in payload["consumer_validation_plan"] if item["migrated_project"] == "producer")
    assert producer_plan["consumers"] == ["consumer"]
    assert producer_plan["suggested_command"] == "mvn clean test"


def test_wave_planner_handles_multiple_independent_projects(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_simple_project(a, artifact_id="a-lib")
    _write_simple_project(b, artifact_id="b-lib")

    payload = plan_migration_wave([a, b], output_dir=tmp_path / "out")["payload"]

    assert len(payload["migration_waves"]) == 1
    assert sorted(payload["migration_waves"][0]) == ["a", "b"]
    assert payload["cycles"] == []


def test_wave_planner_detects_cycles_and_requires_human_review(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    _write_pom(
        a / "pom.xml",
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>a-lib</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>b-lib</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>
</project>
""",
    )
    _write_pom(
        b / "pom.xml",
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>b-lib</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>a-lib</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>
</project>
""",
    )

    payload = plan_migration_wave([a, b], output_dir=tmp_path / "out")["payload"]

    assert payload["human_review_required"] is True
    assert payload["cycles"] == [["a", "b"]]
    assert any("cycles detected" in warning.lower() for warning in payload["warnings"])


def test_wave_planner_warns_on_missing_coordinates_without_crashing(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    _write_pom(
        broken / "pom.xml",
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <version>1.0.0</version>
</project>
""",
    )

    payload = plan_migration_wave([broken], output_dir=tmp_path / "out")["payload"]

    assert payload["projects"][0]["coordinates"]["artifactId"] == ""
    assert payload["missing_or_ambiguous_coordinates"][0]["reason"] == "missing_coordinates"
    assert any("coordinates could not be detected" in warning.lower() for warning in payload["warnings"])


def test_wave_planner_artifacts_and_no_hardcoded_real_names(tmp_path: Path) -> None:
    project = tmp_path / "fixture"
    _write_simple_project(project, artifact_id="fixture-lib")

    result = plan_migration_wave([project], output_dir=tmp_path / "out")
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    summary = Path(result["summary_path"]).read_text(encoding="utf-8")
    implementation = Path("migration_factory/wave_planner/planner.py").read_text(encoding="utf-8").lower()

    assert "projects" in report
    assert "migration_waves" in report
    assert "# Migration Wave Summary" in summary
    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def test_bridge_generates_one_consumer_config_entry(tmp_path: Path) -> None:
    plan_path = _write_wave_plan(
        tmp_path,
        {
            "projects": [
                _project("producer", "C:/tmp/producer", "com.example", "producer", "1.0.0"),
                _project("consumer-a", "C:/tmp/consumer-a", "com.example", "consumer-a", "1.0.0"),
            ],
            "consumer_validation_plan": [
                {"migrated_project": "producer", "consumers": ["consumer-a"], "suggested_command": "mvn clean test"}
            ],
            "cycles": [],
            "warnings": [],
        },
    )

    result = build_consumer_validation_config(
        migration_wave_plan_path=plan_path,
        project_id="producer",
        output_dir=tmp_path / "cfg",
    )
    payload = result["payload"]

    assert payload["status"] == "READY"
    assert len(payload["consumers"]) == 1
    assert payload["consumers"][0]["consumer_project_id"] == "consumer-a"


def test_bridge_generates_multiple_consumers_and_honors_command_override(tmp_path: Path) -> None:
    plan_path = _write_wave_plan(
        tmp_path,
        {
            "projects": [
                _project("producer", "C:/tmp/producer", "com.example", "producer", "1.0.0"),
                _project("a", "C:/tmp/a", "com.example", "a", "1.0.0"),
                _project("b", "C:/tmp/b", "com.example", "b", "1.0.0"),
            ],
            "consumer_validation_plan": [
                {"migrated_project": "producer", "consumers": ["a", "b"], "suggested_command": "mvn clean test"}
            ],
            "cycles": [],
            "warnings": [],
        },
    )

    payload = build_consumer_validation_config(
        migration_wave_plan_path=plan_path,
        project_id="producer",
        output_dir=tmp_path / "cfg",
        command_override="mvn verify",
    )["payload"]

    assert [row["consumer_project_id"] for row in payload["consumers"]] == ["a", "b"]
    assert {row["suggested_command"] for row in payload["consumers"]} == {"mvn verify"}


def test_bridge_no_consumers_returns_no_consumers_found(tmp_path: Path) -> None:
    plan_path = _write_wave_plan(
        tmp_path,
        {
            "projects": [_project("solo", "C:/tmp/solo", "com.example", "solo", "1.0.0")],
            "consumer_validation_plan": [
                {"migrated_project": "solo", "consumers": [], "suggested_command": "mvn clean test"}
            ],
            "cycles": [],
            "warnings": [],
        },
    )

    payload = build_consumer_validation_config(
        migration_wave_plan_path=plan_path,
        project_id="solo",
        output_dir=tmp_path / "cfg",
    )["payload"]

    assert payload["status"] == "NO_CONSUMERS_FOUND"
    assert payload["consumers"] == []


def test_bridge_unknown_project_returns_project_not_found(tmp_path: Path) -> None:
    plan_path = _write_wave_plan(
        tmp_path,
        {
            "projects": [_project("known", "C:/tmp/known", "com.example", "known", "1.0.0")],
            "consumer_validation_plan": [],
            "cycles": [],
            "warnings": [],
        },
    )

    payload = build_consumer_validation_config(
        migration_wave_plan_path=plan_path,
        project_id="missing",
        output_dir=tmp_path / "cfg",
    )["payload"]

    assert payload["status"] == "PROJECT_NOT_FOUND"
    assert payload["human_review_required"] is True


def test_bridge_cycle_warning_propagates_and_gate_shape_loader_works(tmp_path: Path) -> None:
    plan_path = _write_wave_plan(
        tmp_path,
        {
            "projects": [
                _project("producer", "C:/tmp/producer", "com.example", "producer", "1.0.0"),
                _project("consumer", "C:/tmp/consumer", "com.example", "consumer", "1.0.0"),
            ],
            "consumer_validation_plan": [
                {"migrated_project": "producer", "consumers": ["consumer"], "suggested_command": "mvn clean test"}
            ],
            "cycles": [["producer", "consumer"]],
            "warnings": ["Internal dependency cycles detected; human review required before planning migration waves."],
        },
    )

    result = build_consumer_validation_config(
        migration_wave_plan_path=plan_path,
        coordinates={"groupId": "com.example", "artifactId": "producer", "version": "1.0.0"},
        output_dir=tmp_path / "cfg",
    )
    payload = result["payload"]
    gate_shape = load_consumer_validation_gate_config(result["config_path"])
    implementation = Path("migration_factory/wave_planner/consumer_config.py").read_text(encoding="utf-8").lower()

    assert payload["human_review_required"] is True
    assert any("cycles" in warning.lower() for warning in payload["warnings"])
    assert gate_shape == {
        "consumers": [{"path": "C:/tmp/consumer", "command": "mvn clean test"}],
        "consumer_command": "mvn clean test",
    }
    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _write_simple_project(root: Path, *, artifact_id: str) -> None:
    _write_pom(
        root / "pom.xml",
        f"""
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
</project>
""",
    )


def _write_pom(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip(), encoding="utf-8")


def _write_wave_plan(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "migration_wave_plan.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _project(project_id: str, project_path: str, group_id: str, artifact_id: str, version: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "project_path": project_path,
        "coordinates": {
            "groupId": group_id,
            "artifactId": artifact_id,
            "version": version,
            "packaging": "jar",
        },
        "packaging": "jar",
    }
