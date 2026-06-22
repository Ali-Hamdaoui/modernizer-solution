from __future__ import annotations

import json
from pathlib import Path

from migration_factory.capabilities import export_factory_capability_inventory
from migration_factory.readiness import generate_candidate_project_readiness_pack
from migration_factory.wave_planner import plan_migration_wave


def test_readiness_pack_generates_json_and_markdown_and_detects_coordinates(tmp_path: Path) -> None:
    candidate = _write_candidate_project(tmp_path / "candidate")

    result = generate_candidate_project_readiness_pack(
        candidate_project_path=candidate,
        output_dir=tmp_path / "out",
        project_id="candidate-a",
    )

    assert result.report_path.is_file()
    assert result.summary_path.is_file()
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    summary = result.summary_path.read_text(encoding="utf-8")
    assert payload["project_id"] == "candidate-a"
    assert payload["detected_maven_coordinates"]["artifactId"] == "candidate-lib"
    assert payload["detected_packaging"] == "jar"
    assert "# Candidate Project Readiness Summary" in summary


def test_readiness_pack_detects_java_spring_boot_and_known_risk_signals(tmp_path: Path) -> None:
    candidate = _write_candidate_project(tmp_path / "candidate")

    payload = generate_candidate_project_readiness_pack(
        candidate_project_path=candidate,
        output_dir=tmp_path / "out",
        target_profile_id="springboot-2.1-to-3.5-java17",
    ).payload

    signal_ids = {item["signal_id"] for item in payload["detected_risk_signals"]}
    assert payload["detected_java_version"] == "11"
    assert payload["detected_spring_boot_version"] == "2.1.6.RELEASE"
    assert "JAVA_VERSION_ALIGNMENT" in signal_ids
    assert "SPRING_BOOT_VERSION_ALIGNMENT" in signal_ids
    assert "SPRING_BOOT_MULTI_HOP_ROUTE" in signal_ids
    assert "IMPORT_JAVAX_VALIDATION_TO_JAKARTA" in signal_ids
    assert "JJWT_VERSION_ALIGNMENT" in signal_ids
    assert "POWERMOCK_LEGACY_TEST_STRATEGY" in signal_ids


def test_readiness_pack_maps_signals_to_capabilities_with_inventory_and_wave_plan(tmp_path: Path) -> None:
    producer = _write_candidate_project(tmp_path / "producer")
    consumer = _write_consumer_project(tmp_path / "consumer")
    inventory = export_factory_capability_inventory(output_dir=tmp_path / "inventory")
    wave = plan_migration_wave(
        [
            {"path": producer, "project_id": "producer"},
            {"path": consumer, "project_id": "consumer"},
        ],
        output_dir=tmp_path / "wave",
    )

    payload = generate_candidate_project_readiness_pack(
        candidate_project_path=producer,
        output_dir=tmp_path / "out",
        project_id="producer",
        factory_capability_inventory_path=inventory.report_path,
        migration_wave_plan_path=wave["report_path"],
        target_profile_id="springboot-2.1-to-3.5-java17",
    ).payload

    capability_ids = {item["capability_id"] for item in payload["matching_factory_capabilities"]}
    assert "JAVA_VERSION_ALIGNMENT" in capability_ids
    assert "SPRING_BOOT_VERSION_ALIGNMENT" in capability_ids
    assert "IMPORT_JAVAX_VALIDATION_TO_JAKARTA" in capability_ids
    assert "AZURE_SDK_MIGRATION_PLAYBOOK" in capability_ids
    assert payload["consumer_validation_suggestions"]
    assert payload["consumer_validation_suggestions"][0]["consumers"][0]["consumer_project_id"] == "consumer"


def test_readiness_pack_lists_uncovered_signals_when_inventory_missing(tmp_path: Path) -> None:
    candidate = _write_candidate_project(tmp_path / "candidate")

    payload = generate_candidate_project_readiness_pack(
        candidate_project_path=candidate,
        output_dir=tmp_path / "out",
        target_profile_id="springboot-2.1-to-3.5-java17",
    ).payload

    uncovered = {item["signal_id"] for item in payload["uncovered_risk_signals"]}
    assert "JAVA_VERSION_ALIGNMENT" in uncovered
    assert payload["readiness_status"] == "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION"


def test_readiness_pack_missing_optional_inputs_do_not_crash_and_no_hardcoded_names(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    payload = generate_candidate_project_readiness_pack(
        candidate_project_path=candidate,
        output_dir=tmp_path / "out",
    ).payload
    implementation = Path("migration_factory/readiness/pack.py").read_text(encoding="utf-8").lower()

    assert payload["readiness_status"] == "INSUFFICIENT_INFORMATION"
    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _write_candidate_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>2.1.6.RELEASE</version>
  </parent>
  <groupId>com.example</groupId>
  <artifactId>candidate-lib</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>
  <properties>
    <java.version>11</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>shared-contract</artifactId>
      <version>1.0.0</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>5.8.16</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt</artifactId>
      <version>0.10.5</version>
    </dependency>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>1.18.20</version>
    </dependency>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-all</artifactId>
      <version>8.2.0</version>
    </dependency>
    <dependency>
      <groupId>org.powermock</groupId>
      <artifactId>powermock-module-junit4</artifactId>
      <version>2.0.9</version>
    </dependency>
    <dependency>
      <groupId>com.microsoft.azure</groupId>
      <artifactId>azure-servicebus</artifactId>
      <version>3.1.0</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.13.5</version>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.jacoco</groupId>
        <artifactId>jacoco-maven-plugin</artifactId>
        <version>0.8.2</version>
      </plugin>
    </plugins>
  </build>
</project>
""".strip(),
        encoding="utf-8",
    )
    source = root / "src" / "main" / "java" / "com" / "example" / "dto"
    source.mkdir(parents=True, exist_ok=True)
    (source / "SampleDto.java").write_text(
        """
package com.example.dto;
import javax.validation.ConstraintViolationException;
import javax.xml.bind.JAXBElement;
import javax.servlet.http.HttpServletRequest;
import com.microsoft.azure.servicebus.QueueClient;
import org.springframework.web.bind.annotation.ControllerAdvice;
public class SampleDto {
  QueueClient client;
}
""".strip(),
        encoding="utf-8",
    )
    test_source = root / "src" / "test" / "java" / "com" / "example"
    test_source.mkdir(parents=True, exist_ok=True)
    (test_source / "SampleTest.java").write_text(
        """
package com.example;
import org.mockito.MockitoAnnotations;
import org.springframework.boot.test.mock.mockito.MockBean;
public class SampleTest {
  void setup() {
    MockitoAnnotations.initMocks(this);
  }
}
""".strip(),
        encoding="utf-8",
    )
    return root


def _write_consumer_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>consumer-app</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>com.example</groupId>
      <artifactId>candidate-lib</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>
</project>
""".strip(),
        encoding="utf-8",
    )
    return root
