# Debug Agent

Runs deterministic repair commands for failures reported by the Build Agent.

The current version does not edit Java source. It reads a Build Agent error
contract, chooses commands based on `result_kind` and `build_tool`, then records
the attempt in the migration ledger.

## Manual CLI

When the Build Agent fails with `--ledger-file`, the ledger points at the latest
failure contract. Run:

```powershell
python -m migration_factory.agents.debug_agent --ledger-file C:\path\to\modernized-app\.migration\ledger.json
```

You can also pass the contract explicitly:

```powershell
python -m migration_factory.agents.debug_agent C:\path\to\modernized-app --error-contract C:\path\to\build-error.json --ledger-file C:\path\to\modernized-app\.migration\ledger.json
```

If all debug commands succeed, the agent marks the blocked unit as awaiting
Build Agent validation again. Then rerun:

```powershell
python -m migration_factory.agents.build_agent C:\path\to\modernized-app --ledger-file C:\path\to\modernized-app\.migration\ledger.json
```

## Current Automatic Commands

For Maven dependency errors:

```text
mvn -U dependency:resolve
mvn -U clean install -DskipTests
```

For Maven compilation, main class, config, early exit, timeout, and unknown
failures:

```text
mvn clean compile -DskipTests
mvn clean install -DskipTests
```

For Gradle dependency errors:

```text
gradle --refresh-dependencies build -x test
```

For Gradle compilation, main class, config, early exit, timeout, and unknown
failures:

```text
gradle clean compileJava -x test
gradle clean build -x test
```

Java version mismatches currently run diagnostics only:

```text
mvn -version / gradle --version
java -version
```
