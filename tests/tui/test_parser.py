from migration_factory.tui.config import TuiConfig
from pathlib import Path

from migration_factory.tui.parser import config_from_paste, config_from_powershell, parse_config_variables, parse_powershell_variables


def test_parse_powershell_variables_supports_quotes_env_jdks_and_semicolons() -> None:
    parsed = parse_powershell_variables(
        """
        $LEGACY_APP = "/legacy";
        $modernized_app='/modernized'
        $env:AI_HUB = "/ai-hub";
        $profile = java17;
        $RUN_ID=run-001
        $mode = "full_sandbox_migration"
        $approvedBy = 'ada'
        $env:JAVA_HOME = "C:\\Java\\jdk-21"
        """
    )

    assert parsed == {
        "legacy_app_path": "/legacy",
        "modernized_app_path": "/modernized",
        "ai_hub_path": "/ai-hub",
        "profile_id": "java17",
        "run_id": "run-001",
        "mode": "full_sandbox_migration",
        "approved_by": "ada",
        "active_java_home": "C:\\Java\\jdk-21",
    }


def test_parse_config_variables_expands_home_without_evaluating_commands() -> None:
    parsed = parse_config_variables(
        """
        $LEGACY_APP = "$HOME/src"
        $PROFILE = "$(Get-Content secret)"
        Write-Host "ignored"
        """,
        home=Path("/home/ada"),
    )

    assert parsed["legacy_app_path"] == "/home/ada/src"
    assert parsed["profile_id"] == "$(Get-Content secret)"
    assert "Write-Host" not in parsed


def test_parse_bash_export_block_supports_expected_aliases_and_ignored_commands() -> None:
    parsed = parse_config_variables(
        """
        export LEGACY_APP="$HOME/apps/legacy"
        export MODERNIZED_APP=~/apps/modernized
        export AI_HUB="/opt/ai-hub"
        export PROFILE="java17"
        export APPROVED_BY="ada"
        export RUN_ID="run-003"
        export JAVA8_HOME="/usr/lib/jvm/java-8"
        export JAVA21_HOME="/usr/lib/jvm/java-21"
        export JAVA_HOME="$JAVA21_HOME"
        java -version
        mvn -version
        python3 --version
        cd ~/apps/legacy
        """,
        home=Path("/home/ada"),
    )

    assert parsed == {
        "legacy_app_path": "/home/ada/apps/legacy",
        "modernized_app_path": "/home/ada/apps/modernized",
        "ai_hub_path": "/opt/ai-hub",
        "profile_id": "java17",
        "approved_by": "ada",
        "run_id": "run-003",
        "source_jdk_home": "/usr/lib/jvm/java-8",
        "target_jdk_home": "/usr/lib/jvm/java-21",
        "active_java_home": "/usr/lib/jvm/java-21",
    }


def test_intra_block_variable_expansion_only_uses_previous_assignments() -> None:
    parsed = parse_config_variables(
        """
        export JAVA_HOME="$JAVA21_HOME"
        export JAVA21_HOME="/usr/lib/jvm/java-21"
        export MODERNIZED_APP="$JAVA21_HOME/output"
        """
    )

    assert parsed["active_java_home"] == "$JAVA21_HOME"
    assert parsed["modernized_app_path"] == "/usr/lib/jvm/java-21/output"


def test_config_from_powershell_preserves_unspecified_base_values() -> None:
    config = config_from_powershell(
        "$RUN_ID = 'run-002'",
        base=TuiConfig(legacy_app_path="/legacy", run_id="run-001"),
    )

    assert config.legacy_app_path == "/legacy"
    assert config.run_id == "run-002"


def test_config_from_paste_imports_bash_values() -> None:
    config = config_from_paste(
        'export JAVA8_HOME="/java8"\nexport JAVA21_HOME="/java21"',
        base=TuiConfig(legacy_app_path="/legacy"),
    )

    assert config.legacy_app_path == "/legacy"
    assert config.source_jdk_home == "/java8"
    assert config.target_jdk_home == "/java21"
