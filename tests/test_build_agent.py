from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from helpers import workspace_temp_dir
from migration_factory.agents.build_agent import run_build_agent
from migration_factory.agents.build_agent.classifier import BuildClassification, BuildResultKind, classify_line
from migration_factory.agents.build_agent.detection import (
    BuildTool,
    JavaProjectInfo,
    build_run_command,
    detect_java_project,
    discover_maven_run_target,
)
from migration_factory.agents.build_agent.runner import ProcessRunResult
from migration_factory.contracts.migration import (
    BuildValidationStatus,
    initialize_ledger,
    load_ledger,
    mark_unit_awaiting_build,
    mark_unit_in_progress,
)


class BuildAgentTests(unittest.TestCase):
    def test_detects_maven_wrapper(self) -> None:
        with workspace_temp_dir() as project:
            (project / "pom.xml").write_text("<project />", encoding="utf-8")
            wrapper_name = "mvnw.cmd" if os.name == "nt" else "mvnw"
            (project / wrapper_name).write_text("", encoding="utf-8")

            info = detect_java_project(project)

            self.assertEqual(info.build_tool, BuildTool.MAVEN)
            self.assertTrue(info.uses_wrapper)

    def test_build_command_adds_maven_module_and_main_class(self) -> None:
        command = build_run_command(
            ["mvn", "spring-boot:run"],
            BuildTool.MAVEN,
            module="app-service",
            main_class="com.example.Application",
        )

        self.assertEqual(
            command,
            [
                "mvn",
                "-f",
                os.path.join("app-service", "pom.xml"),
                "-Dspring-boot.run.mainClass=com.example.Application",
                "spring-boot:run",
            ],
        )

    def test_classifies_compilation_error(self) -> None:
        result = classify_line("[ERROR] COMPILATION ERROR")

        self.assertIsNotNone(result)
        self.assertEqual(result.kind, BuildResultKind.COMPILATION_ERROR)

    def test_discovers_maven_module_and_main_class_from_parent_project(self) -> None:
        with workspace_temp_dir() as project:
            (project / "pom.xml").write_text(
                """<project>
  <modelVersion>4.0.0</modelVersion>
  <packaging>pom</packaging>
  <modules>
    <module>shoppoc-app</module>
  </modules>
</project>""",
                encoding="utf-8",
            )
            app_source = project / "shoppoc-app" / "src" / "main" / "java" / "com" / "example"
            app_source.mkdir(parents=True)
            (app_source / "Application.java").write_text(
                """package com.example;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
""",
                encoding="utf-8",
            )

            target = discover_maven_run_target(project)

            self.assertEqual(target.module, "shoppoc-app")
            self.assertEqual(target.main_class, "com.example.Application")

    def test_writes_json_contract_when_project_detection_fails(self) -> None:
        with workspace_temp_dir() as tmp:
            output_dir = tmp / "contracts" / "build"
            result = run_build_agent(tmp / "missing-project", output_dir=output_dir, stream_output=False)

            self.assertFalse(result.succeeded)
            self.assertIsNotNone(result.error_contract_path)
            contract = json.loads(result.error_contract_path.read_text(encoding="utf-8"))

            self.assertEqual(contract["agent"], "build-agent")
            self.assertEqual(contract["status"], "failed")
            self.assertEqual(contract["result_kind"], "command_error")
            self.assertEqual(contract["build_tool"], None)

    def test_successful_build_updates_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
            initialize_ledger(
                ledger_file,
                migration_id="test",
                migration_name="Test",
                total_units=1,
                target_path=tmp,
            )
            mark_unit_in_progress(ledger_file, unit_id="unit-001", unit_index=0, title="Unit 1")
            mark_unit_awaiting_build(ledger_file, unit_id="unit-001")

            project_info = JavaProjectInfo(
                path=tmp,
                build_tool=BuildTool.MAVEN,
                base_command=["mvn", "spring-boot:run"],
                uses_wrapper=False,
            )
            process_result = ProcessRunResult(
                classification=BuildClassification(
                    BuildResultKind.SUCCESS,
                    "Application started successfully",
                    "Started DemoApplication",
                ),
                exit_code=0,
            )

            with patch("migration_factory.agents.build_agent.agent.detect_java_project", return_value=project_info):
                with patch("migration_factory.agents.build_agent.agent.run_until_build_result", return_value=process_result):
                    result = run_build_agent(tmp, ledger_file=ledger_file, stream_output=False)

            ledger = load_ledger(ledger_file)
            self.assertTrue(result.succeeded)
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.PASSED)
            self.assertEqual(ledger["completed_units"], ["unit-001"])


if __name__ == "__main__":
    unittest.main()
