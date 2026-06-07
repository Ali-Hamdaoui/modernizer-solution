$env:PYTHONPATH="."
$env:JAVA_HOME_11="C:\jdks\11"
$env:JAVA_HOME_17="C:\jdks\17"
$env:MAVEN_OPTS="demo-opts"
$RUN_ID="candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$LEGACY_APP="C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\candidate"
$MODERNIZED_APP="C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\modernized"
$AI_HUB="C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\ai-hub"
$PROFILE="springboot-2.1-to-3.5-java17"
$RUN_DIR="C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\modernized\.migration\runs\candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

python -m migration_factory.orchestrator.runner --run-id "candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')" --legacy "C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\candidate" --modernized "C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\modernized" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment

# Approval template
python -m migration_factory.approval.approve_run --run-dir "C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\modernized\.migration\runs\candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')" --run-id "candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')" --approved-by "ada" --decision approved --comments "Approved for sandbox-only migration after readiness review. No production promotion approved. Sandbox-only migration. No production promotion approved."

# Resume template
python -m migration_factory.orchestrator.resume --run-id "candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')" --run-dir "C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\launch-plan-sample\modernized\.migration\runs\candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')" --decision approved --approved-by "ada" --comments "Approved for sandbox-only migration after readiness review. No production promotion approved. Sandbox-only migration. No production promotion approved."
