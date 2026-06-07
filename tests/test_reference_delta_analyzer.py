from __future__ import annotations

import json
from pathlib import Path

from migration_factory.tools.reference_delta_analyzer import analyze_reference_delta, main


LEGACY_ROOT_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo-parent</artifactId>
  <version>1.0.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>service</module>
  </modules>
</project>
"""


LEGACY_MODULE_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>com.example</groupId>
    <artifactId>demo-parent</artifactId>
    <version>1.0.0</version>
  </parent>
  <artifactId>service</artifactId>
  <properties>
    <java.version>11</java.version>
    <spring-boot.version>2.7.18</spring-boot.version>
    <jjwt.version>0.11.5</jjwt.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>${spring-boot.version}</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-api</artifactId>
      <version>${jjwt.version}</version>
    </dependency>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-rest-client</artifactId>
      <version>8.2.0</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-config</artifactId>
      <version>5.8.16</version>
    </dependency>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring5</artifactId>
      <version>3.0.15.RELEASE</version>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
        <version>2.7.18</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


REFERENCE_ROOT_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo-parent</artifactId>
  <version>2.0.0</version>
  <packaging>pom</packaging>
  <modules>
    <module>service</module>
  </modules>
</project>
"""


REFERENCE_MODULE_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.5.14</version>
  </parent>
  <groupId>com.example</groupId>
  <artifactId>service</artifactId>
  <version>2.0.0</version>
  <properties>
    <java.version>17</java.version>
    <jjwt.version>0.12.6</jjwt.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>3.5.14</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-api</artifactId>
      <version>${jjwt.version}</version>
    </dependency>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-rest-client</artifactId>
      <version>9.0.0</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-config</artifactId>
      <version>6.5.10</version>
    </dependency>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring6</artifactId>
      <version>3.1.3.RELEASE</version>
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
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
        <version>3.5.14</version>
      </plugin>
    </plugins>
  </build>
</project>
"""


LEGACY_SOURCE = """package com.example;
import javax.validation.ConstraintViolationException;
import javax.servlet.http.HttpServletRequest;
import io.jsonwebtoken.Jwts;
import org.apache.juneau.rest.client.RestClient;
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;
import org.thymeleaf.spring5.SpringTemplateEngine;
public class DemoService {
  public Object parse(String token) {
    return Jwts.parser().setSigningKey("k").parseClaimsJws(token);
  }
  public RestClient client() {
    return RestClient.create().build();
  }
}
"""


REFERENCE_SOURCE = """package com.example;
import jakarta.validation.ConstraintViolationException;
import jakarta.servlet.http.HttpServletRequest;
import io.jsonwebtoken.Jwts;
import org.apache.juneau.rest.client.RestClient;
import org.springframework.context.annotation.Bean;
import org.springframework.security.web.SecurityFilterChain;
import org.thymeleaf.spring6.SpringTemplateEngine;
public class DemoService {
  public Object parse(String token) {
    return Jwts.parserBuilder().build().parseClaimsJws(token);
  }
  public RestClient client() {
    return RestClient.create().rootUrl("http://localhost").build();
  }
  @Bean
  public SecurityFilterChain filterChain() {
    return null;
  }
}
"""


def test_reference_delta_analyzer_detects_nested_poms_and_core_deltas(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "report.json"
    _write_fixture(legacy, LEGACY_ROOT_POM, LEGACY_MODULE_POM, LEGACY_SOURCE, workflow=False)
    _write_fixture(reference, REFERENCE_ROOT_POM, REFERENCE_MODULE_POM, REFERENCE_SOURCE, workflow=False)

    result = analyze_reference_delta(
        legacy_path=legacy,
        reference_path=reference,
        output_path=output,
    )

    payload = result.payload
    assert output.is_file()
    assert payload["legacy"]["primary_pom"] == "service/pom.xml"
    assert payload["reference"]["primary_pom"] == "service/pom.xml"
    assert payload["legacy"]["discovered_poms"] == ["pom.xml", "service/pom.xml"]
    assert payload["pom_delta"]["java_version_change"] == {"legacy": "11", "reference": "17"}
    assert payload["pom_delta"]["spring_boot_version_change"] == {"legacy": "2.7.18", "reference": "3.5.14"}
    assert payload["pom_delta"]["parent_pom_change"]["reference"]["artifact_id"] == "spring-boot-starter-parent"


def test_reference_delta_analyzer_detects_dependency_added_removed_and_changed(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "report.json"
    _write_fixture(legacy, LEGACY_ROOT_POM, LEGACY_MODULE_POM, LEGACY_SOURCE, workflow=False)
    _write_fixture(reference, REFERENCE_ROOT_POM, REFERENCE_MODULE_POM, REFERENCE_SOURCE, workflow=False)

    payload = analyze_reference_delta(legacy_path=legacy, reference_path=reference, output_path=output).payload

    changed = {item["coordinate"] for item in payload["dependency_delta"]["version_changed"]}
    added = {item["coordinate"] for item in payload["dependency_delta"]["added"]}
    removed = {item["coordinate"] for item in payload["dependency_delta"]["removed"]}
    assert "io.jsonwebtoken:jjwt-api" in changed
    assert "org.apache.juneau:juneau-rest-client" in changed
    assert "org.springframework.security:spring-security-config" in changed
    assert "jakarta.validation:jakarta.validation-api" in added
    assert "com.azure:azure-messaging-servicebus" in added
    assert "org.thymeleaf:thymeleaf-spring5" in removed


def test_reference_delta_analyzer_detects_import_api_runtime_and_suspicious_indicators(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "report.json"
    _write_fixture(legacy, LEGACY_ROOT_POM, LEGACY_MODULE_POM, LEGACY_SOURCE, workflow=False)
    _write_fixture(reference, REFERENCE_ROOT_POM, REFERENCE_MODULE_POM, REFERENCE_SOURCE, workflow=True)

    payload = analyze_reference_delta(legacy_path=legacy, reference_path=reference, output_path=output).payload

    javax_changes = payload["source_delta"]["javax_to_jakarta_imports"]
    assert any(item["legacy_prefix"] == "javax.validation." for item in javax_changes)
    assert any(item["legacy_prefix"] == "javax.servlet." for item in javax_changes)
    assert payload["api_migration_indicators"]["jjwt_parser_api"]["detected"] is True
    assert payload["api_migration_indicators"]["juneau_restclient_api"]["detected"] is True
    assert payload["api_migration_indicators"]["spring_security_5_to_6"]["detected"] is True
    assert payload["api_migration_indicators"]["thymeleaf_spring_compatibility"]["detected"] is True
    assert ".github/workflows/build.yml" in payload["runtime_environment"]["workflow_files"]
    assert "codeartifact" in payload["runtime_environment"]["detected_indicators"]
    assert "aws-secrets" in payload["runtime_environment"]["detected_indicators"]
    assert "maven-settings-injection" in payload["runtime_environment"]["detected_indicators"]
    assert "jdk-path-assumptions" in payload["runtime_environment"]["detected_indicators"]
    suspicious_types = {item["type"] for item in payload["suspicious_artifacts"]}
    assert {"backup_file", "duplicate_pom", "copied_java_file", "duplicate_pom_like_file"} <= suspicious_types


def test_reference_delta_analyzer_generates_generic_capability_packs_and_writes_json(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "out" / "reference-delta.json"
    _write_fixture(legacy, LEGACY_ROOT_POM, LEGACY_MODULE_POM, LEGACY_SOURCE, workflow=False)
    _write_fixture(reference, REFERENCE_ROOT_POM, REFERENCE_MODULE_POM, REFERENCE_SOURCE, workflow=True)

    payload = analyze_reference_delta(legacy_path=legacy, reference_path=reference, output_path=output).payload
    written = json.loads(output.read_text(encoding="utf-8"))

    assert written["schema_version"] == "1.0.0"
    packs = set(payload["recommended_capability_packs"])
    assert {
        "javax-to-jakarta",
        "spring-boot-2-to-3",
        "spring-security-5-to-6",
        "jjwt-modernization",
        "juneau-modernization",
        "runtime-environment-contract",
        "maven-build-environment",
        "internal-dependency-graph",
    } <= packs


def test_reference_delta_analyzer_cli_writes_report_and_prints_summary(tmp_path: Path, capsys) -> None:
    legacy = tmp_path / "legacy"
    reference = tmp_path / "reference"
    output = tmp_path / "report.json"
    _write_fixture(legacy, LEGACY_ROOT_POM, LEGACY_MODULE_POM, LEGACY_SOURCE, workflow=False)
    _write_fixture(reference, REFERENCE_ROOT_POM, REFERENCE_MODULE_POM, REFERENCE_SOURCE, workflow=False)

    exit_code = main(
        [
            "--legacy",
            str(legacy),
            "--reference",
            str(reference),
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert output.is_file()
    assert "Reference delta report written." in captured
    assert "java=11 -> 17" in captured


def _write_fixture(root: Path, root_pom: str, module_pom: str, source_text: str, *, workflow: bool) -> None:
    (root / "service" / "src" / "main" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(root_pom, encoding="utf-8")
    (root / "service" / "pom.xml").write_text(module_pom, encoding="utf-8")
    (root / "service" / "src" / "main" / "java" / "com" / "example" / "DemoService.java").write_text(
        source_text,
        encoding="utf-8",
    )
    if workflow:
        (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        (root / ".github" / "workflows" / "build.yml").write_text(
            """
name: build
on: [push]
jobs:
  build:
    steps:
      - uses: actions/setup-java@v4
      - run: mvn -s settings.xml clean verify
      - run: echo $JAVA_HOME_17
      - run: echo $CODEARTIFACT_AUTH_TOKEN
      - run: echo $AWS_SECRET_ACCESS_KEY
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (root / "settings.xml").write_text("<settings><servers><server><id>codeartifact</id></server></servers></settings>\n", encoding="utf-8")
        (root / "src" / "main" / "resources").mkdir(parents=True, exist_ok=True)
        (root / "src" / "main" / "resources" / "application.yml").write_text(
            "spring:\n  config:\n    import: aws-secretsmanager:/demo\n",
            encoding="utf-8",
        )
        (root / "service" / "pom copy.xml").write_text("<project />\n", encoding="utf-8")
        (root / "service" / "pom.backup").write_text("<project />\n", encoding="utf-8")
        (root / "service" / "notes.bak").write_text("old\n", encoding="utf-8")
        (root / "service" / "DemoService copy.java").write_text("class Copy {}\n", encoding="utf-8")
