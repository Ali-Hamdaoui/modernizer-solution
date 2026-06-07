from __future__ import annotations

import unittest
from pathlib import Path

from helpers import workspace_temp_dir
from migration_factory.agents.transformation_agent.maven_pom_patcher import (
    MavenPomPatchError,
    apply_maven_pom_patch,
)


POM_TEMPLATE = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
  <properties>
    <java.version>11</java.version>
    <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>javax.xml.bind</groupId>
      <artifactId>jaxb-api</artifactId>
      <version>2.3.1</version>
    </dependency>
    <dependency>
      <groupId>org.example</groupId>
      <artifactId>demo-lib</artifactId>
      <version>1.0.0</version>
    </dependency>
  </dependencies>
</project>
"""


class MavenPomPatcherTests(unittest.TestCase):
    def test_update_property_existing_property(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "update_property", "name": "java.version", "value": "17"}],
            )

            self.assertEqual(result.status, "applied")
            self.assertIn("<java.version>17</java.version>", _pom_text(project))

    def test_add_property_if_missing(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project><modelVersion>4.0.0</modelVersion></project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "add_property_if_missing", "name": "java.version", "value": "17"}],
            )

            self.assertEqual(result.operations_applied[0]["status"], "added")
            self.assertIn("<java.version>17</java.version>", _pom_text(project))

    def test_apply_patch_falls_back_to_nested_single_module_pom_from_repo_root(self) -> None:
        with workspace_temp_dir() as tmp:
            project = tmp / "repo"
            module = project / "common-utils"
            module.mkdir(parents=True)
            (module / "pom.xml").write_text(POM_TEMPLATE, encoding="utf-8")

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "update_property", "name": "java.version", "value": "17"}],
            )

            self.assertEqual(result.status, "applied")
            self.assertEqual(result.pom_file, "common-utils/pom.xml")
            self.assertIn("<java.version>17</java.version>", (module / "pom.xml").read_text(encoding="utf-8"))

    def test_update_dependency_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="dependency-cleanup",
                operations=[
                    {
                        "op": "update_dependency_version",
                        "group_id": "org.example",
                        "artifact_id": "demo-lib",
                        "new_version": "2.0.0",
                    }
                ],
            )

            self.assertEqual(result.operations_applied[0]["updated_dependencies"], 1)
            self.assertIn("<artifactId>demo-lib</artifactId>", _pom_text(project))
            self.assertIn("<version>2.0.0</version>", _pom_text(project))

    def test_remove_dependency_if_version_matches_removes_placeholder_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project>
  <dependencies>
    <dependency>
      <groupId>org.mockito</groupId>
      <artifactId>mockito-inline</artifactId>
      <version>3.x</version>
      <scope>test</scope>
    </dependency>
    <dependency>
      <groupId>org.mockito</groupId>
      <artifactId>mockito-core</artifactId>
      <version>3.12.4</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-2-7-stabilization",
                operations=[
                    {
                        "op": "remove_dependency_if_version_matches",
                        "group_id": "org.mockito",
                        "artifact_id": "mockito-inline",
                        "version_pattern": r"^[0-9]+(?:\.[0-9]+)*\.x$",
                    }
                ],
            )

            self.assertEqual(result.operations_applied[0]["status"], "removed")
            self.assertEqual(result.operations_applied[0]["removed_dependencies"], 1)
            pom_text = _pom_text(project)
            self.assertNotIn("<artifactId>mockito-inline</artifactId>", pom_text)
            self.assertIn("<artifactId>mockito-core</artifactId>", pom_text)

    def test_replace_dependency_jaxb_to_jakarta(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="jaxb-jakarta",
                operations=[
                    {
                        "op": "replace_dependency",
                        "old_group_id": "javax.xml.bind",
                        "old_artifact_id": "jaxb-api",
                        "new_group_id": "jakarta.xml.bind",
                        "new_artifact_id": "jakarta.xml.bind-api",
                        "new_version": "4.0.2",
                    }
                ],
            )

            self.assertEqual(result.operations_applied[0]["status"], "replaced")
            pom_text = _pom_text(project)
            self.assertIn("<groupId>jakarta.xml.bind</groupId>", pom_text)
            self.assertIn("<artifactId>jakarta.xml.bind-api</artifactId>", pom_text)
            self.assertIn("<version>4.0.2</version>", pom_text)
            self.assertNotIn("<groupId>javax.xml.bind</groupId>", pom_text)

    def test_add_dependency_management_bom(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "add_dependency_management_bom",
                        "group_id": "org.springframework.boot",
                        "artifact_id": "spring-boot-dependencies",
                        "version": "3.5.14",
                        "scope": "import",
                        "type": "pom",
                    }
                ],
            )

            self.assertEqual(result.operations_applied[0]["status"], "added")
            pom_text = _pom_text(project)
            self.assertIn("<dependencyManagement>", pom_text)
            self.assertIn("<artifactId>spring-boot-dependencies</artifactId>", pom_text)
            self.assertIn("<scope>import</scope>", pom_text)

    def test_remove_duplicate_dependencies(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project>
  <dependencies>
    <dependency><groupId>org.example</groupId><artifactId>dup</artifactId><version>1.0.0</version></dependency>
    <dependency><groupId>org.example</groupId><artifactId>dup</artifactId><version>1.0.0</version></dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="dependency-cleanup",
                operations=[{"op": "remove_duplicate_dependencies"}],
            )

            self.assertEqual(result.operations_applied[0]["removed_dependencies"], 1)
            self.assertEqual(_pom_text(project).count("<artifactId>dup</artifactId>"), 1)

    def test_align_jackson_dependency_management_detects_mixed_versions_and_adds_management(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <fasterxml-jackson.version>2.10.0</fasterxml-jackson.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-jackson</artifactId>
      <version>0.10.5</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.dataformat</groupId>
      <artifactId>jackson-dataformat-csv</artifactId>
      <version>${fasterxml-jackson.version}</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-core</artifactId>
      <version>2.9.6</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-2-7-stabilization",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.13.5",
                    }
                ],
            )

            operation = result.operations_applied[0]
            pom_text = _pom_text(project)
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["target_version"], "2.13.5")
            self.assertEqual(operation["detected_versions"], ["2.10.0", "2.9.6"])
            self.assertIn("fasterxml-jackson.version", operation["updated_properties"])
            self.assertIn("com.fasterxml.jackson.core:jackson-core", operation["updated_direct_dependencies"])
            self.assertIn("<fasterxml-jackson.version>2.13.5</fasterxml-jackson.version>", pom_text)
            self.assertIn("<artifactId>jackson-core</artifactId>", pom_text)
            self.assertIn("<version>2.13.5</version>", pom_text)
            self.assertIn("<dependencyManagement>", pom_text)
            self.assertIn("<artifactId>jackson-databind</artifactId>", pom_text)
            self.assertIn("<artifactId>jackson-datatype-jsr310</artifactId>", pom_text)
            self.assertIn("<artifactId>jackson-dataformat-csv</artifactId>", pom_text)

    def test_align_jackson_dependency_management_is_idempotent_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-core</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-annotations</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.datatype</groupId>
        <artifactId>jackson-datatype-jsr310</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.datatype</groupId>
        <artifactId>jackson-datatype-jdk8</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.module</groupId>
        <artifactId>jackson-module-parameter-names</artifactId>
        <version>2.13.5</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-core</artifactId>
      <version>2.13.5</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-2-7-stabilization",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.13.5",
                    }
                ],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.files_changed, [])
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_jackson_dependency_management_skips_optional_artifacts_not_present(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.10.0</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-2-7-stabilization",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.13.5",
                    }
                ],
            )

            managed_artifacts = result.operations_applied[0]["managed_artifacts"]
            self.assertIn("com.fasterxml.jackson.core:jackson-databind", managed_artifacts)
            self.assertIn("com.fasterxml.jackson.core:jackson-core", managed_artifacts)
            self.assertIn("com.fasterxml.jackson.core:jackson-annotations", managed_artifacts)
            self.assertNotIn("com.fasterxml.jackson.dataformat:jackson-dataformat-xml", managed_artifacts)
            self.assertNotIn(
                "com.fasterxml.jackson.module:jackson-module-jaxb-annotations",
                managed_artifacts,
            )

    def test_align_jackson_dependency_management_adds_optional_artifacts_from_dependency_facts(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.10.0</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-2-7-stabilization",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.13.5",
                        "present_artifacts": [
                            "com.fasterxml.jackson.dataformat:jackson-dataformat-xml",
                            "com.fasterxml.jackson.module:jackson-module-jaxb-annotations",
                        ],
                    }
                ],
            )

            managed_artifacts = result.operations_applied[0]["managed_artifacts"]
            self.assertIn("com.fasterxml.jackson.dataformat:jackson-dataformat-xml", managed_artifacts)
            self.assertIn(
                "com.fasterxml.jackson.module:jackson-module-jaxb-annotations",
                managed_artifacts,
            )

    def test_align_jackson_dependency_management_realigns_boot3_unit_from_213x_to_221x(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-core</artifactId>
        <version>2.13.5</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.dataformat</groupId>
      <artifactId>jackson-dataformat-csv</artifactId>
      <version>2.13.5</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.21.2",
                        "version_overrides": {
                            "com.fasterxml.jackson.core:jackson-annotations": "2.21",
                        },
                        "present_artifacts": ["com.fasterxml.jackson.dataformat:jackson-dataformat-csv"],
                    }
                ],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["target_version"], "2.21.2")
            self.assertEqual(operation["detected_versions"], ["2.13.5"])
            self.assertGreaterEqual(operation["managed_dependencies_updated"], 2)
            pom_text = _pom_text(project)
            self.assertIn("<version>2.21.2</version>", pom_text)
            self.assertIn("<artifactId>jackson-annotations</artifactId>", pom_text)
            self.assertIn("<version>2.21</version>", pom_text)
            self.assertNotIn("<version>2.13.5</version>", pom_text)

    def test_align_jackson_dependency_management_updates_boot3_property_based_versions(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <jackson.version>2.13.5</jackson.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>${jackson.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.21.2",
                        "version_overrides": {
                            "com.fasterxml.jackson.core:jackson-annotations": "2.21",
                        },
                    }
                ],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertIn("jackson.version", operation["updated_properties"])
            self.assertIn("<jackson.version>2.21.2</jackson.version>", _pom_text(project))

    def test_align_jackson_dependency_management_updates_boot3_dependency_management_entries(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-core</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-annotations</artifactId>
        <version>2.13.5</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.21.2",
                        "version_overrides": {
                            "com.fasterxml.jackson.core:jackson-annotations": "2.21",
                        },
                    }
                ],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertGreaterEqual(operation["managed_dependencies_updated"], 3)
            self.assertNotIn("<version>2.13.5</version>", _pom_text(project))

    def test_align_jackson_dependency_management_is_no_change_when_boot3_stack_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>2.21.2</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-core</artifactId>
        <version>2.21.2</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-annotations</artifactId>
        <version>2.21</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.datatype</groupId>
        <artifactId>jackson-datatype-jsr310</artifactId>
        <version>2.21.2</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.datatype</groupId>
        <artifactId>jackson-datatype-jdk8</artifactId>
        <version>2.21.2</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.module</groupId>
        <artifactId>jackson-module-parameter-names</artifactId>
        <version>2.21.2</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.21.2</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_jackson_dependency_management",
                        "version": "2.21.2",
                        "version_overrides": {
                            "com.fasterxml.jackson.core:jackson-annotations": "2.21",
                        },
                    }
                ],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_lombok_version_updates_direct_dependency_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>0.11.8</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_lombok_version", "version": "1.18.34"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["0.11.8"])
            self.assertEqual(operation["new_version"], "1.18.34")
            self.assertIn("<version>1.18.34</version>", _pom_text(project))

    def test_align_lombok_version_updates_property_based_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <lombok.version>1.16.20</lombok.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>${lombok.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_lombok_version", "version": "1.18.34"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["updated_properties"], ["lombok.version"])
            self.assertIn("<lombok.version>1.18.34</lombok.version>", _pom_text(project))

    def test_align_lombok_version_is_not_applicable_when_lombok_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_lombok_version", "version": "1.18.34"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_lombok_version_is_no_change_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>1.18.34</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_lombok_version", "version": "1.18.34"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_jacoco_version_updates_property_based_plugin_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <jacoco-maven-plugin.version>0.8.2</jacoco-maven-plugin.version>
  </properties>
  <build>
    <pluginManagement>
      <plugins>
        <plugin>
          <groupId>org.jacoco</groupId>
          <artifactId>jacoco-maven-plugin</artifactId>
          <version>${jacoco-maven-plugin.version}</version>
        </plugin>
      </plugins>
    </pluginManagement>
  </build>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_jacoco_version", "version": "0.8.12"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["0.8.2"])
            self.assertEqual(operation["new_version"], "0.8.12")
            self.assertEqual(operation["updated_properties"], ["jacoco-maven-plugin.version"])
            self.assertIn(
                "<jacoco-maven-plugin.version>0.8.12</jacoco-maven-plugin.version>",
                _pom_text(project),
            )

    def test_align_jacoco_version_updates_direct_plugin_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <build>
    <plugins>
      <plugin>
        <groupId>org.jacoco</groupId>
        <artifactId>jacoco-maven-plugin</artifactId>
        <version>0.8.2</version>
      </plugin>
    </plugins>
  </build>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_jacoco_version", "version": "0.8.12"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["updated_plugins"], 1)
            self.assertIn("<version>0.8.12</version>", _pom_text(project))

    def test_align_jacoco_version_is_not_applicable_when_jacoco_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_jacoco_version", "version": "0.8.12"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_jacoco_version_is_no_change_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <build>
    <plugins>
      <plugin>
        <groupId>org.jacoco</groupId>
        <artifactId>jacoco-maven-plugin</artifactId>
        <version>0.8.12</version>
      </plugin>
    </plugins>
  </build>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="java-17",
                operations=[{"op": "align_jacoco_version", "version": "0.8.12"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_thymeleaf_dependencies_replaces_spring5_with_spring6(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring5</artifactId>
      <version>3.0.11.RELEASE</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_thymeleaf_dependencies", "version": "3.1.3.RELEASE"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["replacements"][0]["old_artifact_id"], "thymeleaf-spring5")
            self.assertEqual(operation["replacements"][0]["new_artifact_id"], "thymeleaf-spring6")
            pom_text = _pom_text(project)
            self.assertIn("<artifactId>thymeleaf-spring6</artifactId>", pom_text)
            self.assertIn("<version>3.1.3.RELEASE</version>", pom_text)

    def test_align_thymeleaf_dependencies_removes_invalid_explicit_version_when_bom_managed(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring6</artifactId>
      <version>3.0.11.RELEASE</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_thymeleaf_dependencies", "prefer_bom_managed": True}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertTrue(operation["used_bom_management"])
            self.assertEqual(operation["removed_versions"][0]["old_version"], "3.0.11.RELEASE")
            pom_text = _pom_text(project)
            self.assertIn("<artifactId>thymeleaf-spring6</artifactId>", pom_text)
            self.assertNotIn("<version>3.0.11.RELEASE</version>", pom_text)

    def test_align_thymeleaf_dependencies_updates_explicit_version_when_configured(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring6</artifactId>
      <version>3.0.11.RELEASE</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_thymeleaf_dependencies", "version": "3.1.3.RELEASE"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["updated_versions"][0]["new_version"], "3.1.3.RELEASE")
            self.assertIn("<version>3.1.3.RELEASE</version>", _pom_text(project))

    def test_align_thymeleaf_dependencies_is_not_applicable_when_thymeleaf_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_thymeleaf_dependencies", "version": "3.1.3.RELEASE"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_thymeleaf_dependencies_is_no_change_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring6</artifactId>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_thymeleaf_dependencies", "prefer_bom_managed": True}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_validation_dependencies_adds_boot_starter_when_jakarta_usage_detected(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_validation_dependencies",
                        "prefer_boot_starter": True,
                        "detected_validation_usage": ["jakarta.validation.Valid"],
                    }
                ],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "added")
            self.assertEqual(
                operation["dependency_added"],
                "org.springframework.boot:spring-boot-starter-validation",
            )
            pom_text = _pom_text(project)
            self.assertIn("<artifactId>spring-boot-starter-validation</artifactId>", pom_text)
            self.assertNotIn("<version>", pom_text.split("<artifactId>spring-boot-starter-validation</artifactId>")[1].split("</dependency>")[0])

    def test_align_validation_dependencies_adds_boot_starter_when_javax_usage_detected(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_validation_dependencies",
                        "prefer_boot_starter": True,
                        "detected_validation_usage": ["javax.validation.Valid", "ConstraintViolationException"],
                    }
                ],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "added")
            self.assertIn("javax.validation.Valid", operation["detected_validation_usage"])
            self.assertIn("<artifactId>spring-boot-starter-validation</artifactId>", _pom_text(project))

    def test_align_validation_dependencies_does_not_duplicate_existing_starter(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-validation</artifactId>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_validation_dependencies",
                        "prefer_boot_starter": True,
                        "detected_validation_usage": ["jakarta.validation.Valid"],
                    }
                ],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")
            self.assertEqual(_pom_text(project).count("<artifactId>spring-boot-starter-validation</artifactId>"), 1)

    def test_align_validation_dependencies_is_not_applicable_without_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_validation_dependencies",
                        "prefer_boot_starter": True,
                        "detected_validation_usage": [],
                    }
                ],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_validation_dependencies_adds_api_for_non_bom_project_when_configured(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <spring-boot.version>3.5.14</spring-boot.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>${spring-boot.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[
                    {
                        "op": "align_validation_dependencies",
                        "prefer_boot_starter": True,
                        "non_boot_api_version": "3.0.2",
                        "detected_validation_usage": ["jakarta.validation.Valid"],
                    }
                ],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "added")
            self.assertEqual(
                operation["dependency_added"],
                "jakarta.validation:jakarta.validation-api",
            )
            pom_text = _pom_text(project)
            self.assertIn("<artifactId>jakarta.validation-api</artifactId>", pom_text)
            self.assertIn("<version>3.0.2</version>", pom_text)

    def test_align_slf4j_logging_updates_old_explicit_slf4j_version_when_not_bom_managed(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <org.slf4j.version>1.7.25</org.slf4j.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>${org.slf4j.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_slf4j_logging", "slf4j_api_version": "2.0.17"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["1.7.25"])
            self.assertEqual(operation["new_versions"], ["2.0.17"])
            self.assertEqual(operation["updated_properties"], ["org.slf4j.version"])
            self.assertIn("<org.slf4j.version>2.0.17</org.slf4j.version>", _pom_text(project))

    def test_align_slf4j_logging_removes_explicit_version_when_bom_managed(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>1.7.25</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_slf4j_logging", "slf4j_api_version": "2.0.17"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertTrue(operation["managed_by_bom"])
            self.assertEqual(operation["removed_versions"], ["1.7.25"])
            pom_text = _pom_text(project)
            self.assertIn("<artifactId>slf4j-api</artifactId>", pom_text)
            self.assertNotIn("<version>1.7.25</version>", pom_text)

    def test_align_slf4j_logging_is_noop_when_already_2x(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>2.0.17</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_slf4j_logging", "slf4j_api_version": "2.0.17"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_slf4j_logging_is_not_applicable_when_logging_dependencies_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_slf4j_logging", "slf4j_api_version": "2.0.17"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_spring_security_dependencies_updates_old_explicit_version_when_not_bom_managed(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <spring-security.version>5.8.16</spring-security.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>${spring-security.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_spring_security_dependencies", "spring_security_version": "6.5.10"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["5.8.16"])
            self.assertEqual(operation["new_versions"], ["6.5.10"])
            self.assertEqual(operation["updated_properties"], ["spring-security.version"])
            self.assertIn("<spring-security.version>6.5.10</spring-security.version>", _pom_text(project))

    def test_align_spring_security_dependencies_updates_multiple_artifacts_consistently(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>5.8.16</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-test</artifactId>
      <version>5.8.16</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_spring_security_dependencies", "spring_security_version": "6.5.10"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["5.8.16"])
            self.assertEqual(operation["new_versions"], ["6.5.10"])
            self.assertIn("org.springframework.security:spring-security-core", operation["updated_dependencies"])
            self.assertIn("org.springframework.security:spring-security-test", operation["updated_dependencies"])
            self.assertEqual(_pom_text(project).count("<version>6.5.10</version>"), 2)

    def test_align_spring_security_dependencies_removes_explicit_versions_when_bom_managed(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>5.8.16</version>
    </dependency>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-test</artifactId>
      <version>5.8.16</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_spring_security_dependencies", "spring_security_version": "6.5.10"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertTrue(operation["managed_by_bom"])
            self.assertEqual(operation["removed_versions"], ["5.8.16"])
            pom_text = _pom_text(project)
            self.assertIn("<artifactId>spring-security-core</artifactId>", pom_text)
            self.assertIn("<artifactId>spring-security-test</artifactId>", pom_text)
            self.assertNotIn("<version>5.8.16</version>", pom_text)

    def test_align_spring_security_dependencies_is_noop_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-core</artifactId>
      <version>6.5.10</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_spring_security_dependencies", "spring_security_version": "6.5.10"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_spring_security_dependencies_is_not_applicable_when_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_spring_security_dependencies", "spring_security_version": "6.5.10"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_maven_compiler_parameters_adds_parameters_to_existing_plugin(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.8.1</version>
        <configuration>
          <source>17</source>
          <target>17</target>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_maven_compiler_parameters", "plugin_version": "3.14.1"}],
            )

            operation = result.operations_applied[0]
            pom_text = _pom_text(project)
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_compiler_configuration_summary"]["source"], "17")
            self.assertEqual(operation["new_compiler_configuration_summary"]["source"], "17")
            self.assertEqual(operation["new_compiler_configuration_summary"]["target"], "17")
            self.assertTrue(operation["new_compiler_configuration_summary"]["parameters_enabled"])
            self.assertIn("<parameters>true</parameters>", pom_text)
            self.assertIn("<source>17</source>", pom_text)
            self.assertIn("<target>17</target>", pom_text)

    def test_align_maven_compiler_parameters_adds_plugin_when_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_maven_compiler_parameters", "plugin_version": "3.14.1"}],
            )

            operation = result.operations_applied[0]
            pom_text = _pom_text(project)
            self.assertEqual(operation["status"], "updated")
            self.assertTrue(operation["plugin_added"])
            self.assertIn("<artifactId>maven-compiler-plugin</artifactId>", pom_text)
            self.assertIn("<version>3.14.1</version>", pom_text)
            self.assertIn("<parameters>true</parameters>", pom_text)

    def test_align_maven_compiler_parameters_is_noop_when_already_enabled(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <configuration>
          <parameters>true</parameters>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_maven_compiler_parameters", "plugin_version": "3.14.1"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_maven_compiler_parameters_is_not_applicable_without_plugin_version_when_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_maven_compiler_parameters"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_jjwt_version_updates_direct_dependency(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-jackson</artifactId>
      <version>0.10.5</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_jjwt_version", "version": "0.13.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["0.10.5"])
            self.assertEqual(operation["new_version"], "0.13.0")
            self.assertEqual(operation["updated_dependencies"], ["io.jsonwebtoken:jjwt-jackson"])
            self.assertIn("<version>0.13.0</version>", _pom_text(project))

    def test_align_jjwt_version_updates_property_based_version(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <jjwt.version>0.10.5</jjwt.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-jackson</artifactId>
      <version>${jjwt.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_jjwt_version", "version": "0.13.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["updated_properties"], ["jjwt.version"])
            self.assertIn("io.jsonwebtoken:jjwt-jackson", operation["updated_dependencies"])
            self.assertIn("<jjwt.version>0.13.0</jjwt.version>", _pom_text(project))

    def test_align_jjwt_version_aligns_split_modules_together(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-api</artifactId>
      <version>0.10.5</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-impl</artifactId>
      <version>0.10.5</version>
    </dependency>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-jackson</artifactId>
      <version>0.10.5</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_jjwt_version", "version": "0.13.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(
                operation["updated_dependencies"],
                [
                    "io.jsonwebtoken:jjwt-api",
                    "io.jsonwebtoken:jjwt-impl",
                    "io.jsonwebtoken:jjwt-jackson",
                ],
            )
            self.assertEqual(_pom_text(project).count("<version>0.13.0</version>"), 3)

    def test_align_jjwt_version_updates_dependency_management_entries(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-api</artifactId>
        <version>0.10.5</version>
      </dependency>
      <dependency>
        <groupId>io.jsonwebtoken</groupId>
        <artifactId>jjwt-impl</artifactId>
        <version>0.10.5</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_jjwt_version", "version": "0.13.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(
                operation["updated_managed_dependencies"],
                [
                    "io.jsonwebtoken:jjwt-api",
                    "io.jsonwebtoken:jjwt-impl",
                ],
            )
            self.assertEqual(_pom_text(project).count("<version>0.13.0</version>"), 2)

    def test_align_jjwt_version_is_not_applicable_when_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_jjwt_version", "version": "0.13.0"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_jjwt_version_is_noop_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-jackson</artifactId>
      <version>0.13.0</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_jjwt_version", "version": "0.13.0"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_align_juneau_version_detects_direct_dependencies(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-marshall</artifactId>
      <version>8.2.0</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(result.status, "no_change")
            self.assertEqual(operation["status"], "review_only")
            self.assertEqual(operation["detected_juneau_dependencies"], ["org.apache.juneau:juneau-marshall"])
            self.assertEqual(operation["action_taken"], "REVIEW_ONLY")
            self.assertTrue(operation["human_review_required"])
            self.assertIn("<version>8.2.0</version>", _pom_text(project))

    def test_align_juneau_version_detects_property_based_versions(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <juneau.version>8.2.0</juneau.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-dto</artifactId>
      <version>${juneau.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "review_only")
            self.assertEqual(operation["old_versions"], ["8.2.0"])
            self.assertEqual(operation["review_item"], "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW")

    def test_align_juneau_version_detects_dependency_management_entries(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.apache.juneau</groupId>
        <artifactId>juneau-rest-client</artifactId>
        <version>8.2.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "review_only")
            self.assertEqual(operation["detected_juneau_dependencies"], ["org.apache.juneau:juneau-rest-client"])

    def test_align_juneau_version_updates_direct_dependency_when_target_configured(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-marshall</artifactId>
      <version>8.2.0</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version", "version": "9.0.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["updated_dependencies"], ["org.apache.juneau:juneau-marshall"])
            self.assertEqual(operation["new_version"], "9.0.0")
            self.assertIn("<version>9.0.0</version>", _pom_text(project))

    def test_align_juneau_version_updates_property_when_target_configured(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <juneau.version>8.2.0</juneau.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-dto</artifactId>
      <version>${juneau.version}</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version", "version": "9.0.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["updated_properties"], ["juneau.version"])
            self.assertEqual(operation["updated_dependencies"], ["org.apache.juneau:juneau-dto"])
            self.assertIn("<juneau.version>9.0.0</juneau.version>", _pom_text(project))

    def test_align_juneau_version_updates_dependency_management_when_target_configured(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.apache.juneau</groupId>
        <artifactId>juneau-core</artifactId>
        <version>8.2.0</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version", "version": "9.0.0"}],
            )

            operation = result.operations_applied[0]
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["updated_managed_dependencies"], ["org.apache.juneau:juneau-core"])
            self.assertIn("<version>9.0.0</version>", _pom_text(project))

    def test_align_juneau_version_is_not_applicable_when_absent(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "not_applicable")

    def test_align_juneau_version_is_noop_when_already_aligned(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(
                tmp,
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-all</artifactId>
      <version>9.0.0</version>
    </dependency>
  </dependencies>
</project>""",
            )

            result = apply_maven_pom_patch(
                project,
                unit_id="spring-boot-3-5-14",
                operations=[{"op": "align_juneau_version", "version": "9.0.0"}],
            )

            self.assertEqual(result.status, "no_change")
            self.assertEqual(result.operations_applied[0]["status"], "no_change")

    def test_idempotency_where_applicable(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)
            operations = [
                {
                    "op": "replace_dependency",
                    "old_group_id": "javax.xml.bind",
                    "old_artifact_id": "jaxb-api",
                    "new_group_id": "jakarta.xml.bind",
                    "new_artifact_id": "jakarta.xml.bind-api",
                    "new_version": "4.0.2",
                },
                {"op": "add_property_if_missing", "name": "maven.compiler.release", "value": "17"},
            ]

            first = apply_maven_pom_patch(project, unit_id="jaxb-jakarta", operations=operations)
            second = apply_maven_pom_patch(project, unit_id="jaxb-jakarta", operations=operations)

            self.assertEqual(first.status, "applied")
            self.assertEqual(second.status, "no_change")
            self.assertEqual(second.files_changed, [])

    def test_failure_when_pom_is_missing(self) -> None:
        with workspace_temp_dir() as tmp:
            project = tmp / "sandbox"
            project.mkdir()

            with self.assertRaises(MavenPomPatchError) as context:
                apply_maven_pom_patch(
                    project,
                    unit_id="java-17",
                    operations=[{"op": "update_property", "name": "java.version", "value": "17"}],
                )

            self.assertEqual(context.exception.code, "POM_FILE_MISSING")

    def test_failure_when_patch_tries_to_escape_sandbox(self) -> None:
        with workspace_temp_dir() as tmp:
            project = _write_project(tmp, POM_TEMPLATE)

            with self.assertRaises(MavenPomPatchError) as context:
                apply_maven_pom_patch(
                    project,
                    unit_id="java-17",
                    operations=[{"op": "update_property", "name": "java.version", "value": "17"}],
                    pom_path="../outside/pom.xml",
                )

            self.assertEqual(context.exception.code, "POM_PATH_OUTSIDE_SANDBOX")

    def test_module_has_no_project_specific_names(self) -> None:
        source = Path(
            "migration_factory/agents/transformation_agent/maven_pom_patcher.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("msa-dto", source)
        self.assertNotIn("common-utils", source)


def _write_project(tmp: Path, pom_text: str) -> Path:
    project = tmp / "sandbox"
    project.mkdir()
    (project / "pom.xml").write_text(pom_text, encoding="utf-8")
    return project


def _pom_text(project: Path) -> str:
    return (project / "pom.xml").read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
