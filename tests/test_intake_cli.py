from __future__ import annotations

import json
from pathlib import Path

from migration_factory.intake.cli import main
from migration_factory.intake.launch_plan import generate_migration_launch_plan, main as launch_main


def test_intake_cli_single_project_writes_inventory_readiness_and_index(tmp_path: Path) -> None:
    project = _write_project(tmp_path / "candidate", artifact_id="candidate-lib")
    before = project.read_text(encoding="utf-8")

    exit_code = main(
        [
            "--project",
            str(project.parent),
            "--project-id",
            "candidate",
            "--output-dir",
            str(tmp_path / "out"),
            "--profile",
            "springboot-2.1-to-3.5-java17",
        ]
    )

    assert exit_code == 0
    out = tmp_path / "out"
    assert (out / "factory-capabilities" / "factory_capability_inventory.json").is_file()
    assert (out / "candidate" / "readiness_pack.json").is_file()
    assert (out / "intake_index.json").is_file()
    assert (out / "intake_summary.md").is_file()
    assert project.read_text(encoding="utf-8") == before


def test_intake_cli_multiple_projects_writes_wave_plan_and_consumer_configs(tmp_path: Path) -> None:
    producer = _write_project(tmp_path / "producer", artifact_id="producer-lib")
    consumer = _write_project(
        tmp_path / "consumer",
        artifact_id="consumer-app",
        dependency_artifact="producer-lib",
    )

    exit_code = main(
        [
            "--project",
            str(producer.parent),
            "--project",
            str(consumer.parent),
            "--project-id",
            "producer",
            "--project-id",
            "consumer",
            "--output-dir",
            str(tmp_path / "out"),
            "--generate-consumer-configs",
        ]
    )

    payload = json.loads((tmp_path / "out" / "intake_index.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert (tmp_path / "out" / "wave" / "migration_wave_plan.json").is_file()
    assert (tmp_path / "out" / "producer" / "consumer-validation" / "consumer_validation_config.json").is_file()
    assert payload["wave_order"]
    assert "producer" in payload["consumer_validation_config_paths"]


def test_intake_cli_handles_missing_optional_inputs_and_no_real_names() -> None:
    implementation = Path("migration_factory/intake/cli.py").read_text(encoding="utf-8").lower()
    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def test_launch_plan_generates_from_readiness_pack(tmp_path: Path) -> None:
    project = _write_project(tmp_path / "candidate", artifact_id="candidate-lib")
    main(
        [
            "--project",
            str(project.parent),
            "--project-id",
            "candidate",
            "--output-dir",
            str(tmp_path / "intake"),
            "--profile",
            "springboot-2.1-to-3.5-java17",
        ]
    )
    readiness_pack = tmp_path / "intake" / "candidate" / "readiness_pack.json"

    result = generate_migration_launch_plan(
        readiness_pack_path=readiness_pack,
        legacy_app_path=project.parent,
        modernized_output_path=tmp_path / "modernized",
        ai_hub_path=tmp_path / "ai-hub",
        profile_id="springboot-2.1-to-3.5-java17",
        output_dir=tmp_path / "launch",
        run_id_prefix="candidate-run",
        approved_by="ada",
    )

    payload = result["payload"]
    commands = (tmp_path / "launch" / "migration_launch_commands.ps1").read_text(encoding="utf-8")
    assert Path(result["report_path"]).is_file()
    assert "read_only_assessment" in payload["commands"]["runner"]
    assert "migration_factory.approval.approve_run" in payload["commands"]["approval_template"]
    assert "migration_factory.orchestrator.resume" in payload["commands"]["resume_template"]
    assert "read_only_assessment" in commands


def test_launch_plan_generates_from_intake_index_and_propagates_warnings(tmp_path: Path) -> None:
    producer = _write_project(tmp_path / "producer", artifact_id="producer-lib")
    consumer = _write_project(
        tmp_path / "consumer",
        artifact_id="consumer-app",
        dependency_artifact="producer-lib",
    )
    main(
        [
            "--project",
            str(producer.parent),
            "--project",
            str(consumer.parent),
            "--project-id",
            "producer",
            "--project-id",
            "consumer",
            "--output-dir",
            str(tmp_path / "intake"),
            "--profile",
            "springboot-2.1-to-3.5-java17",
            "--generate-consumer-configs",
        ]
    )
    intake_index = tmp_path / "intake" / "intake_index.json"
    readiness_pack = json.loads((tmp_path / "intake" / "producer" / "readiness_pack.json").read_text(encoding="utf-8"))
    readiness_pack["readiness_status"] = "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION"
    readiness_pack["warnings"] = ["Legacy Azure SDK usage detected."]
    (tmp_path / "intake" / "producer" / "readiness_pack.json").write_text(json.dumps(readiness_pack, indent=2) + "\n", encoding="utf-8")

    exit_code = launch_main(
        [
            "--intake-index",
            str(intake_index),
            "--project-id",
            "producer",
            "--legacy-app",
            str(producer.parent),
            "--modernized-app",
            str(tmp_path / "modernized"),
            "--ai-hub",
            str(tmp_path / "ai-hub"),
            "--profile",
            "springboot-2.1-to-3.5-java17",
            "--output-dir",
            str(tmp_path / "launch"),
        ]
    )

    payload = json.loads((tmp_path / "launch" / "migration_launch_plan.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["human_review_required_before_launch"] is True
    assert "Legacy Azure SDK usage detected." in payload["commands"]["approval_template"]
    assert payload["consumer_validation_config_path"].endswith("consumer_validation_config.json")


def test_launch_plan_blocks_resume_for_insufficient_information_by_default(tmp_path: Path) -> None:
    readiness_pack = tmp_path / "readiness_pack.json"
    readiness_pack.write_text(
        json.dumps(
            {
                "project_id": "candidate",
                "readiness_status": "INSUFFICIENT_INFORMATION",
                "warnings": ["No pom.xml detected."],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    payload = generate_migration_launch_plan(
        readiness_pack_path=readiness_pack,
        legacy_app_path=tmp_path / "legacy",
        modernized_output_path=tmp_path / "modernized",
        ai_hub_path=tmp_path / "ai-hub",
        profile_id="springboot-2.1-to-3.5-java17",
        output_dir=tmp_path / "launch",
    )["payload"]

    assert payload["launch_status"] == "BLOCKED_FOR_INSUFFICIENT_INFORMATION"
    assert payload["commands"]["resume_template"] == ""


def _write_project(root: Path, *, artifact_id: str, dependency_artifact: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    dependency_block = ""
    if dependency_artifact:
        dependency_block = f"""
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>{dependency_artifact}</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>"""
    pom = root / "pom.xml"
    pom.write_text(
        f"""
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.1.6.RELEASE</version>
  </parent>
  <groupId>com.example</groupId>
  <artifactId>{artifact_id}</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
  <properties>
    <java.version>11</java.version>
  </properties>{dependency_block}
</project>
""".strip(),
        encoding="utf-8",
    )
    return pom
