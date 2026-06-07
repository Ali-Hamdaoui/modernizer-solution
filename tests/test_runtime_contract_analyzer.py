from __future__ import annotations

import json
from pathlib import Path

from migration_factory.tools.runtime_contract_analyzer import analyze_runtime_contract, main


PROJECT_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.acme.platform</groupId>
  <artifactId>demo-service</artifactId>
  <version>1.0.0</version>
  <properties>
    <java.version>17</java.version>
    <maven.compiler.release>17</maven.compiler.release>
  </properties>
  <repositories>
    <repository>
      <id>private-releases</id>
      <url>https://packages.example.internal/maven/releases</url>
    </repository>
  </repositories>
  <dependencies>
    <dependency>
      <groupId>com.acme.platform.libs</groupId>
      <artifactId>shared-contract</artifactId>
      <version>1.2.3-SNAPSHOT</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter</artifactId>
      <version>3.5.14</version>
    </dependency>
    <dependency>
      <groupId>org.mockito</groupId>
      <artifactId>mockito-core</artifactId>
      <version>5.16.0</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.13.0</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


APP_SOURCE = """package com.example;
import java.io.File;
import java.io.FileInputStream;
import java.nio.file.Paths;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.ResourceLoader;
public class RuntimeConfig {
  @Value("${demo.url}")
  private String demoUrl;
  private final Environment environment;
  private final ResourceLoader resourceLoader;
  public RuntimeConfig(Environment environment, ResourceLoader resourceLoader) {
    this.environment = environment;
    this.resourceLoader = resourceLoader;
  }
  public void load() throws Exception {
    new File("demo.txt");
    new FileInputStream("keystore.jks");
    Paths.get("src/main/resources/application.yml");
    new ClassPathResource("tls/client.crt");
    new FileSystemResource("config/runtime.properties");
  }
}
"""


TEST_SOURCE = """package com.example;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
@SpringBootTest
@ActiveProfiles("test")
class RuntimeConfigTest {
  @Test
  void works() {
    Mockito.mock(Object.class);
  }
}
"""


WORKFLOW = """name: build
on: [push]
jobs:
  build:
    steps:
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '11'
      - run: mvn -s .mvn/settings.xml clean verify
      - run: echo $JAVA_HOME_17
      - run: echo $CODEARTIFACT_AUTH_TOKEN
      - run: echo $AWS_SECRET_ACCESS_KEY
      - run: echo /opt/maven/apache-maven-3.9.8/bin/mvn
      - run: echo C:\\Java\\jdk-17
"""


REFERENCE_DELTA = {
    "runtime_environment": {
        "detected_indicators": ["codeartifact", "maven-settings-injection", "aws-secrets"],
    },
    "dependency_delta": {
        "added": [{"coordinate": "com.acme.platform.libs:shared-contract"}],
        "version_changed": [],
    },
    "recommended_capability_packs": ["runtime-environment-contract", "internal-dependency-graph"],
}


def test_runtime_contract_analyzer_detects_generic_runtime_contract_and_writes_json(tmp_path: Path) -> None:
    project = tmp_path / "project"
    output = tmp_path / "runtime_contract.json"
    _write_project_fixture(project)

    payload = analyze_runtime_contract(project_path=project, output_path=output).payload

    assert output.is_file()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["schema_version"] == "1.0.0"
    assert payload["project"]["primary_pom"] == "pom.xml"
    assert payload["jdk_requirements"]["java_version"] == "17"
    assert payload["jdk_requirements"]["compiler_release"] == "17"
    assert payload["jdk_requirements"]["workflow_setup_java_versions"] == ["11", "temurin"]
    assert "JAVA_HOME_17" in payload["jdk_requirements"]["environment_variables"]
    assert ".github/workflows/build.yml" in {item["path"] for item in payload["workflow_indicators"]}
    assert ".mvn/settings.xml" in payload["maven_requirements"]["settings_files"]
    assert payload["private_registry_requirements"]["repository_urls"] == ["https://packages.example.internal/maven/releases"]
    assert "CODEARTIFACT_AUTH_TOKEN" in payload["private_registry_requirements"]["environment_variables"]
    assert {"path": "src/main/resources/application.yml", "location": "main-resources"} in payload["configuration_files"]
    assert {"path": "src/test/resources/application-test.yml", "location": "test-resources"} in payload["configuration_files"]
    resource_types = {item["type"] for item in payload["resource_access"]}
    assert {"@Value", "Environment", "ResourceLoader", "FileSystemResource", "ClassPathResource", "Paths.get", "FileInputStream", "new File"} <= resource_types
    security_paths = {item["path"] for item in payload["security_materials"]}
    assert "src/main/resources/tls/client.crt" in security_paths
    assert "src/main/resources/keystore.jks" in security_paths
    internal = {item["coordinate"] for item in payload["internal_dependencies"]}
    assert "com.acme.platform.libs:shared-contract" in internal
    test_types = {item["type"] for item in payload["test_runtime_requirements"]}
    assert {"test-resource-config", "junit5", "mockito", "spring-boot-test", "active-profiles"} <= test_types
    risk_codes = {item["code"] for item in payload["detected_risks"]}
    assert {
        "MISSING_PRIVATE_MAVEN_SETTINGS",
        "PRIVATE_REGISTRY_AUTH_REQUIRED",
        "JDK_VERSION_MISMATCH_RISK",
        "INTERNAL_DEPENDENCY_BUILD_ORDER_REQUIRED",
        "RESOURCE_FILES_REQUIRED",
        "SECURITY_MATERIALS_REQUIRED",
        "TEST_RUNTIME_CONFIG_REQUIRED",
        "WORKFLOW_ONLY_ENVIRONMENT_RISK",
    } <= risk_codes
    action_codes = {item["code"] for item in payload["recommended_actions"]}
    assert {
        "BUILD_INTERNAL_DEPENDENCIES_FIRST",
        "PROVIDE_MAVEN_SETTINGS",
        "SET_REQUIRED_JDK_ENV_VARS",
        "COPY_REQUIRED_CONFIG_FILES",
        "PROVIDE_TEST_RUNTIME_CONFIG",
        "PROVIDE_SECURITY_MATERIALS",
        "REVIEW_WORKFLOW_ENVIRONMENT",
        "AVOID_COMMITTING_SECRETS",
    } <= action_codes


def test_runtime_contract_analyzer_enriches_from_reference_delta_and_cli(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    output = tmp_path / "runtime_contract.json"
    reference_delta = tmp_path / "reference-delta.json"
    _write_project_fixture(project)
    reference_delta.write_text(json.dumps(REFERENCE_DELTA), encoding="utf-8")

    exit_code = main(
        [
            "--project",
            str(project),
            "--reference-delta",
            str(reference_delta),
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr().out
    payload = json.loads(output.read_text(encoding="utf-8"))
    risk_codes = {item["code"] for item in payload["detected_risks"]}
    action_codes = {item["code"] for item in payload["recommended_actions"]}
    internal = {item["coordinate"]: item["reason"] for item in payload["internal_dependencies"]}

    assert exit_code == 0
    assert "Runtime contract report written." in captured
    assert "REFERENCE_DELTA_RUNTIME_CONTEXT_PRESENT" in risk_codes
    assert "REVIEW_REFERENCE_DELTA_CAPABILITY_PACKS" in action_codes
    assert "reference_delta_context" in internal["com.acme.platform.libs:shared-contract"]
    assert "CODEARTIFACT_AUTH_TOKEN" in {item["name"] for item in payload["environment_variables"]}
    assert all("value" not in item for item in payload["environment_variables"])


def _write_project_fixture(project: Path) -> None:
    (project / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (project / ".mvn").mkdir(parents=True, exist_ok=True)
    (project / "src" / "main" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)
    (project / "src" / "main" / "resources" / "tls").mkdir(parents=True, exist_ok=True)
    (project / "src" / "test" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)
    (project / "src" / "test" / "resources").mkdir(parents=True, exist_ok=True)

    (project / "pom.xml").write_text(PROJECT_POM, encoding="utf-8")
    (project / "mvnw").write_text("@echo off\r\n", encoding="utf-8")
    (project / ".github" / "workflows" / "build.yml").write_text(WORKFLOW, encoding="utf-8")
    (project / ".mvn" / "settings.xml").write_text("<settings />\n", encoding="utf-8")
    (project / "src" / "main" / "resources" / "application.yml").write_text("demo:\n  enabled: true\n", encoding="utf-8")
    (project / "src" / "test" / "resources" / "application-test.yml").write_text("demo:\n  enabled: false\n", encoding="utf-8")
    (project / "src" / "main" / "resources" / "keystore.jks").write_text("placeholder\n", encoding="utf-8")
    (project / "src" / "main" / "resources" / "tls" / "client.crt").write_text("placeholder\n", encoding="utf-8")
    (project / "src" / "main" / "java" / "com" / "example" / "RuntimeConfig.java").write_text(APP_SOURCE, encoding="utf-8")
    (project / "src" / "test" / "java" / "com" / "example" / "RuntimeConfigTest.java").write_text(TEST_SOURCE, encoding="utf-8")
