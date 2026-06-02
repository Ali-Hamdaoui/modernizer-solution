import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from migration_factory.agents.planning_agent.node import planning_node
from migration_factory.assessment.writer import write_assessment_artifacts


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "boot21-contract-library"
AI_HUB = REPO_ROOT / "modernizer-solution-ai-hub"
PROFILE_ID = "springboot-2.1-to-3.5-java17"
ANALYSIS_AGENT_DIR = REPO_ROOT / "migration_factory" / "agents" / "analysis_agent" / "analysis_agent"

if str(ANALYSIS_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_AGENT_DIR))

from context_manager import MigrationContext  # type: ignore[import-not-found]  # noqa: E402
from main import run_analysis_agent  # type: ignore[import-not-found]  # noqa: E402


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _fake_maven(cmd, *args, **kwargs):
    cmd_text = " ".join(str(part) for part in cmd)
    if len(cmd) > 1 and str(cmd[0]).endswith(("java.exe", "java")) and cmd[1] == "-version":
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr='openjdk version "11.0.31"\n')
    if "dependency:tree" in cmd_text and "-DoutputType=json" in cmd_text:
        payload = {
            "artifact": "com.example.contracts:customer-api-contracts:jar:1.0.0",
            "children": [
                {"artifact": "org.springframework:spring-web:jar:5.1.8.RELEASE", "children": []},
                {"artifact": "org.apache.juneau:juneau-rest-client:jar:8.2.0", "children": []},
                {"artifact": "javax.persistence:javax.persistence-api:jar:2.2", "children": []},
                {"artifact": "javax.xml.bind:jaxb-api:jar:2.3.1", "children": []},
                {"artifact": "com.total.corp:shared-kernel:jar:1.4.0", "children": []},
                {"artifact": "org.projectlombok:lombok:jar:1.16.20", "children": []},
            ],
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
    if "rewrite-maven-plugin" in cmd_text:
        return subprocess.CompletedProcess(cmd, 0, stdout="rewrite dry run ok", stderr="")
    raise RuntimeError(f"Unexpected command: {cmd}")


def test_read_only_assessment_boot21_contract_library_end_to_end(monkeypatch, tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    shutil.copytree(FIXTURE_ROOT, legacy)
    modernized.mkdir()
    fake_java_home = tmp_path / "jdk11"
    (fake_java_home / "bin").mkdir(parents=True)
    (fake_java_home / "bin" / "java.exe").write_text("", encoding="utf-8")

    before_hash = _hash_tree(legacy)

    monkeypatch.setattr("dependency_adapter.subprocess.run", _fake_maven)
    monkeypatch.setattr("openrewrite_adapter.subprocess.run", _fake_maven)
    monkeypatch.setenv("JAVA_HOME_11", str(fake_java_home))

    run_id = "boot21-contract-e2e"
    context = MigrationContext(run_id, str(legacy), str(modernized), str(AI_HUB), PROFILE_ID)
    analysis_result = run_analysis_agent(context)

    assert analysis_result.status == "COMPLETED"

    analysis_report_path = Path(analysis_result.artifact_paths["analysis_report"])
    internal_dependencies_path = Path(analysis_result.artifact_paths["internal_dependencies"])
    read_only_path = Path(analysis_result.artifact_paths["read_only_verification"])
    assert analysis_report_path.exists()
    assert internal_dependencies_path.exists()
    assert read_only_path.exists()

    analysis_report = json.loads(analysis_report_path.read_text(encoding="utf-8"))
    internal_dependencies = json.loads(internal_dependencies_path.read_text(encoding="utf-8"))
    read_only = json.loads(read_only_path.read_text(encoding="utf-8"))

    assert analysis_report["source_stack"]["java"] == "11"
    assert analysis_report["source_stack"]["spring_boot"] == "2.1.6.RELEASE"
    assert analysis_report["project_kind"] == "contract_library"
    assert analysis_report["has_spring_boot_main"] is False
    assert analysis_report["has_rest_contracts"] is True
    assert analysis_report["has_juneau_contracts"] is True
    assert analysis_report["packaging"] == "jar"
    assert analysis_report["internal_dependencies_count"] > 0
    assert internal_dependencies["internal_dependencies_count"] > 0
    assert read_only["source_modified"] is False
    assert read_only["status"] == "PASS"

    planning_result = planning_node(
        {
            "run_id": run_id,
            "profile": PROFILE_ID,
            "modernized_app_path": str(modernized),
            "ai_hub_path": str(AI_HUB),
        }
    )

    assert planning_result["planning_status"] == "PASS"

    planning_dir = modernized / ".migration" / "runs" / run_id / "planning"
    migration_plan_path = planning_dir / "migration_plan.yaml"
    migration_units_path = planning_dir / "migration_units.yaml"
    approval_request_path = planning_dir / "approval_request.json"
    assert migration_plan_path.exists()
    assert migration_units_path.exists()
    assert approval_request_path.exists()

    migration_plan = yaml.safe_load(migration_plan_path.read_text(encoding="utf-8"))
    migration_units = yaml.safe_load(migration_units_path.read_text(encoding="utf-8"))
    approval_request = json.loads(approval_request_path.read_text(encoding="utf-8"))

    assert migration_plan["selected_route_id"] == "boot-2.1-to-3.5-java17"
    assert migration_plan["route_strategy"] == "multi_hop"
    assert [hop["id"] for hop in migration_plan["selected_hops"]] == [
        "boot-2.1-to-2.7-java11",
        "boot-2.7-to-3.5-java17",
    ]
    assert migration_plan["unit_references"] == [
        "baseline",
        "spring-boot-2-7-stabilization",
        "java-17",
        "spring-boot-3-5-14",
        "jakarta",
        "jaxb-jakarta",
        "dependency-cleanup",
        "contract-compatibility-review",
        "existing-test-migration",
    ]
    assert [unit["id"] for unit in migration_units["units"]] == migration_plan["unit_references"]

    assert any("BOOT_PRE_27_TO_BOOT3_MULTI_HOP" in risk for risk in migration_plan["risks"])
    assert any("CONTRACT_LIBRARY_HUMAN_REVIEW" in risk for risk in migration_plan["risks"])
    assert any("JAVAX_PERSISTENCE_BOOT3" in risk for risk in migration_plan["risks"])
    assert any("JAVAX_XML_BIND_BOOT3" in risk for risk in migration_plan["risks"])
    assert any(
        "INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW" in warning for warning in migration_plan["warnings"]
    )
    assert any("BOOT_PRE_27_TO_BOOT3_MULTI_HOP" in risk for risk in approval_request["risks"])

    assessment_result = write_assessment_artifacts(modernized, run_id)
    assessment_report = assessment_result.report
    assessment_report_path = modernized / ".migration" / "runs" / run_id / "assessment" / "assessment_report.json"
    assert assessment_report_path.exists()
    assert assessment_report["approval_readiness"]["status"] == "READY_FOR_REVIEW"
    assert assessment_report["overall_risk"] == "HIGH"
    assert any("BOOT_PRE_27_TO_BOOT3_MULTI_HOP" in risk for risk in assessment_report["planning_risks"])

    after_hash = _hash_tree(legacy)
    assert after_hash == before_hash
