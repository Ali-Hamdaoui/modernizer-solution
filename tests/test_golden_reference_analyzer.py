from __future__ import annotations

import json
from pathlib import Path

from migration_factory.golden_reference import analyze_golden_reference


LEGACY_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
  <properties>
    <java.version>11</java.version>
    <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
    <lombok.version>0.11.8</lombok.version>
    <jacoco.version>0.8.2</jacoco.version>
    <org.slf4j.version>1.7.25</org.slf4j.version>
    <jackson.version>2.13.5</jackson.version>
    <spring-security.version>5.8.16</spring-security.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>${lombok.version}</version>
    </dependency>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>${org.slf4j.version}</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>${jackson.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>${spring-security.version}</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt</artifactId>
      <version>0.10.5</version>
    </dependency>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-all</artifactId>
      <version>8.1.1</version>
    </dependency>
    <dependency>
      <groupId>org.powermock</groupId>
      <artifactId>powermock-module-junit4</artifactId>
      <version>2.0.2</version>
    </dependency>
    <dependency>
      <groupId>com.microsoft.azure</groupId>
      <artifactId>azure-servicebus</artifactId>
      <version>3.1.0</version>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.jacoco</groupId>
        <artifactId>jacoco-maven-plugin</artifactId>
        <version>${jacoco.version}</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

REFERENCE_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.5.14</version>
  </parent>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>2.0.0</version>
  <properties>
    <java.version>17</java.version>
    <lombok.version>1.18.34</lombok.version>
    <jacoco.version>0.8.12</jacoco.version>
    <org.slf4j.version>2.0.17</org.slf4j.version>
    <jackson.version>2.21.2</jackson.version>
    <spring-security.version>6.5.10</spring-security.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>${jackson.version}</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>${lombok.version}</version>
    </dependency>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>${org.slf4j.version}</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>${jackson.version}</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>${spring-security.version}</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt</artifactId>
      <version>0.12.6</version>
    </dependency>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-all</artifactId>
      <version>9.1.0</version>
    </dependency>
    <dependency>
      <groupId>org.powermock</groupId>
      <artifactId>powermock-module-junit4</artifactId>
      <version>2.0.9</version>
    </dependency>
    <dependency>
      <groupId>jakarta.validation</groupId>
      <artifactId>jakarta.validation-api</artifactId>
      <version>3.0.2</version>
    </dependency>
    <dependency>
      <groupId>com.azure</groupId>
      <artifactId>azure-messaging-servicebus</artifactId>
      <version>7.17.10</version>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.jacoco</groupId>
        <artifactId>jacoco-maven-plugin</artifactId>
        <version>${jacoco.version}</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

LEGACY_SOURCE = """package com.example;
import javax.validation.ConstraintViolationException;
import javax.xml.bind.JAXBElement;
import javax.servlet.http.HttpServletRequest;
import org.springframework.data.domain.Sort;
public class DemoService {
  public Object sortBy(String field) {
    return new Sort(Sort.Direction.ASC, field);
  }
}
"""

REFERENCE_SOURCE = """package com.example;
import jakarta.validation.ConstraintViolationException;
import jakarta.xml.bind.JAXBElement;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.data.domain.Sort;
public class DemoService {
  public Object sortBy(String field) {
    return Sort.by(Sort.Direction.ASC, field);
  }
  public String newApi(String value) {
    return value;
  }
}
"""

LEGACY_TEST = """package com.example;
import org.mockito.MockitoAnnotations;
import org.springframework.boot.test.mock.mockito.MockBean;
public class DemoTest {
  void setup() {
    MockitoAnnotations.initMocks(this);
  }
}
"""

REFERENCE_TEST = """package com.example;
import org.mockito.MockitoAnnotations;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
public class DemoTest {
  void setup() {
    MockitoAnnotations.openMocks(this);
  }
}
"""

FACTORY_SOURCE = """package com.example;
import jakarta.validation.ConstraintViolationException;
import javax.xml.bind.JAXBElement;
import javax.servlet.http.HttpServletRequest;
import org.springframework.data.domain.Sort;
public class DemoService {
  public Object sortBy(String field) {
    return new Sort(Sort.Direction.ASC, field);
  }
}
"""


def test_golden_reference_analyzer_detects_versions_patterns_and_reports(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "out"
    _write_fixture(legacy, LEGACY_POM, LEGACY_SOURCE, LEGACY_TEST)
    _write_fixture(reference, REFERENCE_POM, REFERENCE_SOURCE, REFERENCE_TEST)

    result = analyze_golden_reference(
        legacy_path=legacy,
        migrated_reference_path=reference,
        output_dir=output,
        project_id="demo-project",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    summary = result.summary_path.read_text(encoding="utf-8")
    assert result.report_path.is_file()
    assert result.summary_path.is_file()
    assert payload["project_id"] == "demo-project"
    assert payload["java_version_change"] == {"legacy": "11", "reference": "17"}
    assert payload["spring_boot_version_change"] == {"legacy": "2.1.6.RELEASE", "reference": "3.5.14"}
    assert any(item["coordinate"] == "org.projectlombok:lombok" for item in payload["dependency_version_changes"])
    assert any(item["coordinate"] == "org.jacoco:jacoco-maven-plugin" for item in payload["plugin_tooling_changes"])
    assert any(item["rule_id"] == "IMPORT_JAVAX_VALIDATION_TO_JAKARTA" for item in payload["javax_to_jakarta_import_changes"])
    assert any(item["rule_id"] == "SPRING_DATA_SORT_BY_MIGRATION" for item in payload["source_code_transformation_patterns"])
    assert any(item["rule_id"] == "MOCKBEAN_TO_MOCKITOBEAN" for item in payload["test_modernization_patterns"])
    assert any(item["rule_id"] == "INITMOCKS_TO_OPENMOCKS" for item in payload["test_modernization_patterns"])
    assert any(item["rule_id"] == "AZURE_SDK_API_MIGRATION" for item in payload["candidate_human_review_items"])
    assert any(item["rule_id"] == "PUBLIC_API_SIGNATURE_CHANGE" for item in payload["candidate_human_review_items"])
    signal_ids = {item["signal_id"] for item in payload["framework_library_signals"]}
    assert {"JJWT", "JUNEAU", "POWERMOCK", "AZURE_OLD_SDK", "AZURE_NEW_SDK"} <= signal_ids
    assert "Golden Reference Summary" in summary
    assert "Java: 11 -> 17" in summary
    assert "Framework Signals" in summary


def test_golden_reference_analyzer_reports_factory_gap_statuses(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    factory = tmp_path / "factory"
    output = tmp_path / "out"
    _write_fixture(legacy, LEGACY_POM, LEGACY_SOURCE, LEGACY_TEST)
    _write_fixture(reference, REFERENCE_POM, REFERENCE_SOURCE, REFERENCE_TEST)
    _write_fixture(factory, REFERENCE_POM, FACTORY_SOURCE, LEGACY_TEST)

    result = analyze_golden_reference(
        legacy_path=legacy,
        migrated_reference_path=reference,
        factory_sandbox_path=factory,
        output_dir=output,
    )

    payload = result.payload
    statuses = {item["rule_id"]: item["status"] for item in payload["factory_gap_analysis"]["gap_statuses"]}
    assert statuses["IMPORT_JAVAX_VALIDATION_TO_JAKARTA"] == "BOTH_APPLIED"
    assert statuses["SPRING_DATA_SORT_BY_MIGRATION"] == "REFERENCE_APPLIED_FACTORY_MISSING"
    assert statuses["MOCKBEAN_TO_MOCKITOBEAN"] == "REFERENCE_APPLIED_FACTORY_MISSING"


def test_golden_reference_analyzer_finds_nested_module_pom_generically(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "out"
    _write_fixture(legacy / "module-a", LEGACY_POM, LEGACY_SOURCE, LEGACY_TEST)
    _write_fixture(reference / "module-a", REFERENCE_POM, REFERENCE_SOURCE, REFERENCE_TEST)

    result = analyze_golden_reference(
        legacy_path=legacy,
        migrated_reference_path=reference,
        output_dir=output,
    )

    assert result.payload["java_version_change"] == {"legacy": "11", "reference": "17"}
    assert any(item["rule_id"] == "SPRING_BOOT_VERSION_ALIGNMENT" for item in result.payload["candidate_deterministic_rules"])


def test_golden_reference_analyzer_works_under_migration_directory_name(tmp_path: Path) -> None:
    root = tmp_path / ".migration" / "golden"
    legacy = root / "legacy"
    reference = root / "reference"
    output = root / "out"
    _write_fixture(legacy / "module-a", LEGACY_POM, LEGACY_SOURCE, LEGACY_TEST)
    _write_fixture(reference / "module-a", REFERENCE_POM, REFERENCE_SOURCE, REFERENCE_TEST)

    result = analyze_golden_reference(
        legacy_path=legacy,
        migrated_reference_path=reference,
        output_dir=output,
    )

    assert result.payload["spring_boot_version_change"] == {"legacy": "2.1.6.RELEASE", "reference": "3.5.14"}
    assert any(item["signal_id"] == "JUNEAU" for item in result.payload["framework_library_signals"])


def _write_fixture(root: Path, pom_text: str, source_text: str, test_text: str) -> None:
    (root / "src" / "main" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)
    (root / "src" / "test" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(pom_text, encoding="utf-8")
    (root / "src" / "main" / "java" / "com" / "example" / "DemoService.java").write_text(
        source_text,
        encoding="utf-8",
    )
    (root / "src" / "test" / "java" / "com" / "example" / "DemoTest.java").write_text(
        test_text,
        encoding="utf-8",
    )
