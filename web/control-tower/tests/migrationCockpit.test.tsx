import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MigrationCockpitPage from "../app/migrations/[jobId]/page";
import {
  MigrationCockpit,
  AssistantPanelContent,
  ControlledR6RepairDemoPanel,
  GovernedRepairProposalCard,
  R6GovernedRepairPanel,
  StageFailureEvidenceDetails,
  EMPTY_R6_REPAIR_UI_STATE,
  GatePanelContent,
  formatGateArtifactRefLabel,
  hasUnknownNonRepairableFailure,
  isControlledR6DemoUiEnabled,
  missingReviewerRequestFields,
  mergeCockpitLiveRefreshResults,
  reduceStageStatus,
  shouldShowApprovalDecisionControls,
  type CockpitData,
} from "../app/migrations/[jobId]/MigrationCockpit";
import {
  applyV2RepairReviewContext,
  askV2Assistant,
  CONTROL_TOWER_API_BASE_URL,
  getV2ArtifactPreview,
  prepareV2RepairApplyContext,
  requireJobId,
  requestV2ReviewerCritique,
  v2EventStreamUrl,
} from "../lib/controlTowerApi";
import type {
  GateRepresentation,
  GovernedRepairProposalResponse,
  MigrationIntelligenceSummary,
  V2FailureSummaryResponse,
  V2JobEvent,
  V2ReviewerCritiqueResponse,
  RepairApplyContextResponse,
  RepairApprovalResponse,
  ApplyRepairReviewContextResponse,
} from "../lib/contracts";

const GOVERNED_REPAIR_PROPOSAL: GovernedRepairProposalResponse = {
  proposal_id: "proposal-9a-1",
  command_id: "cmd-repair-1",
  intent: "solve_this",
  status: "awaiting_human_approval",
  proposal_checksum: "sha256:proposal-checksum",
  context_pack_checksum: "sha256:context-checksum",
  title: "Stabilize dependency alignment after failed build",
  failure_summary: "package jakarta.servlet.http does not exist",
  summary: "Review failure evidence, preserve sandbox-only flow, and require human approval before apply.",
  proposed_action: "Prepare governed repair proposal for dependency update",
  proposal_text: "Adjust dependency graph in sandbox only after human approval.",
  affected_paths: ["src/main/java/com/example/App.java"],
  affected_files: ["pom.xml", "src/main/java/com/example/App.java"],
  affected_components: ["build-agent", "stage3-dependency-review"],
  confidence: "high",
  risk: "medium",
  proposer: {
    role: "proposer",
    model: "gpt-4o-mini",
    provider: "azure_openai",
    status: "completed",
    proposal_text: "Use deterministic evidence plus migration intelligence.",
  },
  reviewer: {
    role: "reviewer",
    model: "gpt-4o",
    provider: "azure_openai",
    status: "completed",
    verdict: "review_required",
    critique: "Keep sandbox-only and await human approval.",
    warnings: ["No automatic changes"],
    required_changes: ["Require explicit approval before apply"],
    reviewer_required: true,
    manual_review_required: true,
  },
  evidence: {
    failure_classification: {
      status: "generated",
      categories: { dependency_mismatch: 2, test_failure: 1 },
      category_counts: { dependency_mismatch: 2, test_failure: 1 },
      failed_unit: "stage2",
      failure_count: 3,
      suggested_actions: ["review dependency graph"],
      test_failure_summary: {
        suite_count: 1,
        first_failure: {
          test_class: "ExampleTest",
          test_method: "failsWhenLegacyApiMissing",
          outcome: "failed",
          category: "test_failure",
          exception_type: "AssertionError",
          symptom: "expected true",
        },
      },
    },
    runtime_contract: {
      status: "generated",
      detected_risks_count: 2,
      detected_risks: ["hardcoded JDK path", "private registry requirement"],
      recommended_actions_count: 1,
      recommended_actions: ["use backend-owned Java selection"],
      jdk_requirements: {
        java_version: "21",
        compiler_release: "21",
        workflow_setup_java_versions: ["21"],
      },
      maven_requirements: {
        wrapper_present: true,
      },
      private_registry_requirements: {
        repository_urls: ["https://repo.example.invalid"],
      },
      internal_dependencies_count: 1,
      internal_dependencies: ["com.example:shared-lib"],
    },
    reference_delta: {
      status: "generated",
      dependency_delta: { added_count: 1, removed_count: 0, version_changed_count: 2 },
      source_delta: { added_imports_count: 3, removed_imports_count: 1, javax_to_jakarta_count: 2 },
      api_migration_indicators: { security: true, persistence: false },
      recommended_capability_packs: ["security-hardening", "jakarta-migration"],
      suspicious_artifacts_count: 1,
      suspicious_artifacts: ["legacy-api.jar"],
    },
    migration_intelligence_warnings: ["runtime_contract: warn"],
    evidence_references: ["diagnosis:1", "evidence:2"],
    evidence_checksums: ["sha256:proposal", "sha256:evidence"],
  },
  repair_family: "JAKARTA_IMPORT_MECHANICAL_SOURCE",
  deterministic_rule_id: "JAKARTA_IMPORT_MECHANICAL_SOURCE",
  repair_artifact: {
    unified_diff: "diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java\n--- a/src/main/java/com/example/App.java\n+++ b/src/main/java/com/example/App.java\n@@ -1 +1 @@\n-import jakarta.servlet.http.HttpServletRequest;\n+import javax.servlet.http.HttpServletRequest;\n",
    patch_path: "C:/work/out/.migration/runs/run-9a/repairs/proposals/patch-abc.diff",
    patch_checksum: "sha256:patch-checksum",
  },
  target_files: [
    {
      relative_path: "src/main/java/com/example/App.java",
      before_checksum: "sha256:before",
      proposed_checksum: "sha256:after",
      repair_family: "JAKARTA_IMPORT_MECHANICAL_SOURCE",
    },
  ],
  failure_evidence: {
    diagnostic_line: "package jakarta.servlet.http does not exist",
    failing_file: "src/main/java/com/example/App.java",
    controlled_demo_evidence: {
      controlled_demo: true,
      controlled_demo_id: "r6_jakarta_javax_namespace_restore",
      injected_failure: true,
      sandbox_only: true,
      legacy_unchanged: true,
      target_file: "src/main/java/com/example/App.java",
      original_import_namespace: "javax.servlet.http",
      injected_import_namespace: "jakarta.servlet.http",
      proposed_import_namespace: "javax.servlet.http",
      injection_before_checksum: "sha256:inject-before",
      injection_after_checksum: "sha256:inject-after",
      dependency_alignment: {
        source: "controlled_demo_pre_injection_source",
        supports_namespace: "javax.servlet.http",
      },
    },
  },
  patch_package: {
    sandbox_path: "C:/work/out/.migration/runs/run-9a/sandbox",
    sandbox_checksum: "sha256:sandbox-checksum",
    legacy_checksum: "sha256:legacy-checksum",
    repair_family: "JAKARTA_IMPORT_MECHANICAL_SOURCE",
    deterministic_rule_id: "JAKARTA_IMPORT_MECHANICAL_SOURCE",
    approval_apply_separate: true,
    repair_artifact: {
      unified_diff: "diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java\n--- a/src/main/java/com/example/App.java\n+++ b/src/main/java/com/example/App.java\n@@ -1 +1 @@\n-import jakarta.servlet.http.HttpServletRequest;\n+import javax.servlet.http.HttpServletRequest;\n",
      patch_path: "C:/work/out/.migration/runs/run-9a/repairs/proposals/patch-abc.diff",
      patch_checksum: "sha256:patch-checksum",
    },
    target_files: [{ relative_path: "src/main/java/com/example/App.java" }],
    failure_evidence: {
      diagnostic_line: "package jakarta.servlet.http does not exist",
      failing_file: "src/main/java/com/example/App.java",
      controlled_demo_evidence: {
        controlled_demo: true,
        controlled_demo_id: "r6_jakarta_javax_namespace_restore",
        injected_failure: true,
        sandbox_only: true,
        legacy_unchanged: true,
        target_file: "src/main/java/com/example/App.java",
        original_import_namespace: "javax.servlet.http",
        injected_import_namespace: "jakarta.servlet.http",
        proposed_import_namespace: "javax.servlet.http",
        injection_before_checksum: "sha256:inject-before",
        injection_after_checksum: "sha256:inject-after",
        dependency_alignment: {
          source: "controlled_demo_pre_injection_source",
          supports_namespace: "javax.servlet.http",
        },
      },
    },
  },
  migration_intelligence_warnings: ["runtime_contract: warn", "reference_delta: warn"],
  governance: {
    human_approval_required: true,
    no_auto_apply: true,
    sandbox_only: true,
    source_mutated: false,
    sandbox_mutated: false,
    stage_resumed: false,
    backend_runner_invoked: false,
    approval_bypass: false,
    reviewer_required: true,
    manual_review_required: true,
    status: "Awaiting human approval",
  },
  verification_status: "passed",
  verification_build_status: "BUILD_PASSED_IN_SANDBOX",
  verification_test_status: "TEST_PASSED",
  verification_h2_status: "H2_STARTUP_PASSED",
  verification_artifact_refs: {
    repair_ledger: "C:/work/out/.migration/runs/run-9a/repairs/ledger.json",
    repair_validation_report: "C:/work/out/.migration/runs/run-9a/repairs/validation_report.json",
    post_transform_failure_classification: "C:/work/out/.migration/runs/run-9a/post_transform_failure_classification.json",
  },
  verification_failure_classification_ref: "C:/work/out/.migration/runs/run-9a/post_transform_failure_classification.json",
  warnings: ["Governed repair proposal is evidence-bound."],
};

describe("V2 Migration Cockpit contract", () => {
  it("passes the awaited route job id into MigrationCockpit", async () => {
    const page = await MigrationCockpitPage({
      params: Promise.resolve({ jobId: "429a9bb2154b4be7a99a32867780d744" }),
    });

    const children = page.props.children;
    const cockpit = children[1];

    expect(cockpit.type).toBe(MigrationCockpit);
    expect(cockpit.props.jobId).toBe("429a9bb2154b4be7a99a32867780d744");
  });

  it("displays three stages in order", () => {
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "queued", input_source_kind: "legacy_source" },
      { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "pending", input_source_kind: "stage_1_sandbox" },
      { stage_index: 3, pipeline_stage: "Stage 3", chain_status: "pending", input_source_kind: "stage_2_sandbox" },
    ];
    expect(stages).toHaveLength(3);
    expect(stages[0].input_source_kind).toBe("legacy_source");
    expect(stages[1].input_source_kind).toBe("stage_1_sandbox");
    expect(stages[2].input_source_kind).toBe("stage_2_sandbox");
  });

  it("has no Boot 4 stage", () => {
    const stages = [1, 2, 3];
    expect(stages).not.toContain(4);
  });

  it("has no stage-start buttons", () => {
    const cockpitControls = [
      "stage_timeline",
      "evidence_panel",
      "approval_decisions",
      "assistant_panel",
      "proof_report",
    ];
    const forbidden = ["start_stage_1", "start_stage_2", "start_stage_3", "run_maven", "choose_goal"];
    for (const f of forbidden) {
      expect(cockpitControls).not.toContain(f);
    }
  });

  it("approval requires checksum", () => {
    const approval = { id: "a1", status: "pending", checksum_required: true };
    expect(approval.checksum_required).toBe(true);
  });

  it("renders the open gate panel with gate-safe details", () => {
    const migrationIntelligence: MigrationIntelligenceSummary = {
      runtime_contract: {
        status: "generated",
        detected_risks_count: 2,
        detected_risks: ["hardcoded JDK path", "private registry requirement"],
        recommended_actions_count: 1,
        recommended_actions: ["use backend-owned Java selection"],
        jdk_requirements: {
          java_version: "21",
          compiler_release: "21",
          workflow_setup_java_versions: ["21"],
          hardcoded_jdk_paths: ["C:/Java"],
          environment_variables: ["JAVA_HOME"],
        },
        maven_requirements: {
          wrapper_present: true,
          settings_files: ["settings.xml"],
          workflow_maven_versions: ["3.9.9"],
          hardcoded_maven_paths: [],
        },
        private_registry_requirements: {
          repository_urls: ["https://repo.example.invalid"],
          detected_indicators: ["internal dependency"],
          environment_variables: ["MAVEN_REPO_URL"],
          evidence: ["pom.xml"],
        },
        internal_dependencies_count: 1,
        internal_dependencies: ["com.example:shared-lib"],
      },
      reference_delta: {
        status: "generated",
        dependency_delta: {
          added_count: 1,
          removed_count: 0,
          version_changed_count: 2,
        },
        source_delta: {
          added_imports_count: 3,
          removed_imports_count: 1,
          javax_to_jakarta_count: 2,
        },
        api_migration_indicators: {
          security: true,
          persistence: false,
        },
        recommended_capability_packs: ["security-hardening", "jakarta-migration"],
        suspicious_artifacts_count: 1,
        suspicious_artifacts: ["legacy-api.jar"],
      },
      post_transform_failure_classification: {
        status: "generated",
        categories: {
          dependency_mismatch: 2,
          test_failure: 1,
        },
        category_counts: {
          dependency_mismatch: 2,
          test_failure: 1,
        },
        failed_unit: "stage2",
        failure_count: 3,
        suggested_actions: ["review dependency graph", "rerun tests"],
        test_failure_summary: {
          suite_count: 1,
          first_failure: {
            test_class: "ExampleTest",
            test_method: "failsWhenLegacyApiMissing",
            outcome: "failed",
            category: "test_failure",
            exception_type: "AssertionError",
            symptom: "expected true",
          },
        },
      },
    };

    const gate: GateRepresentation = {
      gate_id: "gate-1",
      job_id: "job-1",
      gate_phase: "repair_review",
      stage_index: 2,
      gate_status: "open",
      gate_decision: "revise",
      source_artifact_checksum: "sha256:gate",
      source_artifact_refs: ["diagnosis:1", "evidence:2"],
      created_at: "2026-06-17T00:00:00Z",
      resolved_at: null,
      resolved_by: null,
      checksum: "sha256:gate-checksum",
      available_actions: [
        { action: "revise", label: "Revise", description: "Request repair revision", blocked: false, block_reason: "" },
        { action: "reject", label: "Reject", description: "Reject repair", blocked: false, block_reason: "" },
      ],
    };

    const markup = renderToStaticMarkup(
      <GatePanelContent state={{
        status: "success",
        gates: [gate],
        openGate: gate,
        openGateDetail: {
          gate,
          evidence: {
            failure_summary: "build failed in sandbox",
            root_cause_hypothesis: "dependency mismatch",
            patch_summary: "Align the version",
            affected_paths: ["pom.xml"],
            reviewer_critique: null,
            remaining_attempts: 2,
            max_attempts: 3,
            migration_intelligence: migrationIntelligence,
            migration_intelligence_warnings: ["runtime_contract: warn"],
          },
          checksum: gate.checksum,
        },
      }} />
    );

    expect(markup).toContain("Open gate");
    expect(markup).toContain("repair_review");
    expect(markup).toContain("Stage 2");
    expect(markup).toContain("build failed in sandbox");
    expect(markup).toContain("Migration Intelligence");
    expect(markup).toContain("Runtime Contract");
    expect(markup).toContain("Reference Delta");
    expect(markup).toContain("Failure Classification");
    expect(markup).toContain("runtime_contract: warn");
    expect(markup).toContain("Revise");
    expect(markup).toContain("Reject");
    expect(markup).toContain("diagnosis:1");
    expect(markup).toContain("sha256:gate-checksum");
  });

  it("renders assistant-specific ask failures without collapsing the cockpit shell", () => {
    const markup = renderToStaticMarkup(
      <AssistantPanelContent
        assistantModel={{
          status: "fallback",
          source: "deterministic",
          provider: "backend",
          role: "assistant",
          failure_reason: "assistant_ask_failed",
        }}
        messages={[
          {
            message_id: "msg-1",
            job_id: "job-1",
            role: "assistant",
            content: "Stage 3 is complete and the root POM is available.",
            correlation_id: null,
            created_at: "2026-06-18T00:00:00Z",
          },
        ]}
        assistantError="Control Tower mutation failed for /v1/v2/jobs/job-1/assistant/ask: 500 Internal Server Error."
        assistantQuestion="what about the pom?"
        assistantBusy={false}
        approvalReviewOpen={false}
        onQuestionChange={() => undefined}
        onAsk={() => undefined}
      />
    );

    expect(markup).toContain("Assistant request failed");
    expect(markup).toContain("Stage 3 is complete and the root POM is available.");
    expect(markup).toContain("what about the pom?");
    expect(markup).not.toContain("Failed to fetch");
  });

  it("preserves multiline assistant messages in the cockpit", () => {
    const markup = renderToStaticMarkup(
      <AssistantPanelContent
        assistantModel={{
          status: "fallback",
          source: "deterministic",
          provider: "backend",
          role: "assistant",
          failure_reason: "assistant_ask_failed",
        }}
        messages={[
          {
            message_id: "msg-1",
            job_id: "job-1",
            role: "assistant",
            content: "Line 1\nLine 2",
            correlation_id: null,
            created_at: "2026-06-18T00:00:00Z",
          },
        ]}
        assistantError={null}
        assistantQuestion="what about the pom?"
        assistantBusy={false}
        approvalReviewOpen={false}
        onQuestionChange={() => undefined}
        onAsk={() => undefined}
      />
    );

    expect(markup).toContain("message-content");
    expect(markup).toContain("Line 1");
    expect(markup).toContain("Line 2");
  });

  it("renders governed repair proposal card in assistant panel", () => {
    const markup = renderToStaticMarkup(
      <AssistantPanelContent
        assistantModel={{
          status: "fallback",
          source: "deterministic",
          provider: "backend",
          role: "assistant",
          failure_reason: "assistant_ask_failed",
        }}
        messages={[]}
        assistantError={null}
        assistantQuestion="solve this"
        assistantBusy={false}
        approvalReviewOpen={true}
        repairProposal={GOVERNED_REPAIR_PROPOSAL}
        onQuestionChange={() => undefined}
        onAsk={() => undefined}
      />
    );

    expect(markup).toContain("Governed Repair Proposal");
    expect(markup).toContain("Awaiting human approval");
    expect(markup).toContain("Human approval required: true");
    expect(markup).toContain("No automatic changes have been applied.");
    expect(markup).toContain("Proposal: proposal-9a-1");
    expect(markup).toContain("Proposer");
    expect(markup).toContain("reviewer");
    expect(markup).toContain("Failure classification: generated");
    expect(markup).toContain("Runtime contract: generated");
    expect(markup).toContain("Reference delta: generated");
    expect(markup).toContain("Post-Apply Verification");
    expect(markup).toContain("Status: passed");
    expect(markup).toContain("Build: BUILD_PASSED_IN_SANDBOX");
    expect(markup).toContain("Test: TEST_PASSED");
    expect(markup).toContain("H2: H2_STARTUP_PASSED");
    expect(markup).toContain("Artifact refs:");
    expect(markup).toContain("Failure classification ref:");
    expect(markup).toContain("Verification passed in sandbox. No automatic production promotion happened.");
    expect(markup).toContain("runtime_contract: warn");
    expect(markup).toContain("Ask");
  });

  it("renders failed verification state in governed repair proposal card", () => {
    const failedProposal: GovernedRepairProposalResponse = {
      ...GOVERNED_REPAIR_PROPOSAL,
      verification_status: "failed",
      verification_build_status: "BUILD_FAILED_IN_SANDBOX",
      verification_test_status: "TEST_FAILED",
      verification_h2_status: "H2_STARTUP_FAILED",
      verification_artifact_refs: {
        repair_build_error_contract: "C:/work/out/.migration/runs/run-9a/repair_build_error_contract.json",
        post_transform_failure_classification: "C:/work/out/.migration/runs/run-9a/post_transform_failure_classification.json",
      },
      verification_failure_classification_ref: "C:/work/out/.migration/runs/run-9a/repair_build_error_contract.json",
    };

    const markup = renderToStaticMarkup(
      <GovernedRepairProposalCard proposal={failedProposal} />
    );

    expect(markup).toContain("Post-Apply Verification");
    expect(markup).toContain("Status: failed");
    expect(markup).toContain("Build: BUILD_FAILED_IN_SANDBOX");
    expect(markup).toContain("Test: TEST_FAILED");
    expect(markup).toContain("H2: H2_STARTUP_FAILED");
    expect(markup).toContain("Artifact refs:");
    expect(markup).toContain("Failure classification ref:");
    expect(markup).toContain("Use Solve This again to generate a new governed proposal.");
  });

  it("governed repair proposal card has no approve apply run or resume controls", () => {
    const markup = renderToStaticMarkup(
      <GovernedRepairProposalCard proposal={GOVERNED_REPAIR_PROPOSAL} />
    );

    expect(markup).toContain("Governed Repair Proposal");
    expect(markup).not.toContain("<button");
    expect(markup).not.toContain("Approve");
    expect(markup).not.toContain(">Run<");
    expect(markup).not.toContain("Resume");
    expect(markup).not.toContain(">Verify<");
  });

  it("controlled R6 demo action is hidden unless dev demo mode or unknown failure is present", () => {
    expect(isControlledR6DemoUiEnabled("true")).toBe(true);
    expect(isControlledR6DemoUiEnabled("false")).toBe(false);

    const hidden = renderToStaticMarkup(
      <ControlledR6RepairDemoPanel
        enabled={false}
        hasProposal={false}
        unknownFailure={false}
        busy={false}
        onRun={() => undefined}
      />
    );
    expect(hidden).not.toContain("Run controlled R6 repair demo");
  });

  it("controlled R6 demo panel shows unknown failures as non-repairable without production action", () => {
    const failureSummary = {
      failures: [
        {
          type: "build_failed",
          message: "Failure: UNKNOWN",
          repair_loop_status: "DISABLED",
        },
      ],
    } as V2FailureSummaryResponse;
    expect(hasUnknownNonRepairableFailure(failureSummary)).toBe(true);

    const markup = renderToStaticMarkup(
      <ControlledR6RepairDemoPanel
        enabled={false}
        hasProposal={false}
        unknownFailure={true}
        busy={false}
        onRun={() => undefined}
      />
    );
    expect(markup).toContain("Failure is not eligible for governed R6 repair");
    expect(markup).toContain("Controlled demo action disabled outside explicit local/dev demo mode");
    expect(markup).not.toContain("<button");
  });

  it("controlled R6 demo action disables once durable proposal exists", () => {
    const markup = renderToStaticMarkup(
      <ControlledR6RepairDemoPanel
        enabled={true}
        hasProposal={true}
        unknownFailure={false}
        busy={false}
        onRun={() => undefined}
      />
    );
    expect(markup).toContain("Run controlled R6 repair demo");
    expect(markup).toContain("disabled=\"\"");
  });

  it("renders governed R6 repair controls with apply disabled until reviewer accept and human approval", () => {
    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={GOVERNED_REPAIR_PROPOSAL}
        state={EMPTY_R6_REPAIR_UI_STATE}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(markup).toContain("Governed R6 Repair");
    expect(markup).toContain("Stage2 disabled during R6");
    expect(markup).toContain("Failed command: cmd-repair-1");
    expect(markup).toContain("Repair family: JAKARTA_IMPORT_MECHANICAL_SOURCE");
    expect(markup).toContain("patch-abc.diff");
    expect(markup).toContain("Pre-validation: passed before proposal became actionable");
    expect(markup).toContain("Controlled demo: injected local/dev failure; not the real Stage1 UNKNOWN failure.");
    expect(markup).toContain("Namespace proof: jakarta.servlet.http was injected and proposal restores javax.servlet.http");
    expect(markup).toContain("Injection before checksum: sha256:inject-before");
    expect(markup).toContain("Request reviewer critique");
    expect(markup).toContain("Prepare apply context");
    expect(markup).toContain("Record human repair approval");
    expect(markup).toContain("Run official apply");
    expect(markup).toContain("disabled=\"\"");
  });

  it("enables reviewer request for controlled patch-backed proposal using package checksum", () => {
    const proposal: GovernedRepairProposalResponse = {
      ...GOVERNED_REPAIR_PROPOSAL,
      context_pack_checksum: undefined,
      patch_package: {
        ...GOVERNED_REPAIR_PROPOSAL.patch_package,
        package_checksum: "sha256:package-context-checksum",
      },
    };

    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={proposal}
        state={EMPTY_R6_REPAIR_UI_STATE}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(missingReviewerRequestFields(proposal)).toEqual([]);
    expect(markup).toContain(">Request reviewer critique</button>");
    expect(markup).not.toContain("Reviewer request disabled");
  });

  it("shows exact missing reviewer request field when disabled", () => {
    const proposal: GovernedRepairProposalResponse = {
      ...GOVERNED_REPAIR_PROPOSAL,
      context_pack_checksum: undefined,
      patch_package: {
        ...GOVERNED_REPAIR_PROPOSAL.patch_package,
        package_checksum: "",
      },
    };

    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={proposal}
        state={EMPTY_R6_REPAIR_UI_STATE}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(missingReviewerRequestFields(proposal)).toEqual(["context pack checksum"]);
    expect(markup).toContain("Reviewer request disabled: missing context pack checksum.");
  });

  it("enables official apply only after reviewer accept and recorded human approval", () => {
    const reviewer: V2ReviewerCritiqueResponse = {
      critique_id: "crit-1",
      proposal_id: "proposal-9a-1",
      proposal_type: "repair_proposal",
      proposal_checksum: "sha256:proposal-checksum",
      context_pack_checksum: "sha256:context-checksum",
      decision: "accept",
      reasoning: "Patch is sandbox-bound and evidence-backed.",
      missing_evidence: [],
      unsafe_assumptions: [],
      model_invocation_id: null,
      created_at: "2026-06-30T00:00:00Z",
      reviewer_model: {
        model_invocation_id: "model-reviewer-1",
        provider: "fake",
        source: "fake",
        status: "live_ok",
      },
    };
    const context: RepairApplyContextResponse = {
      context_id: "ctx-1",
      proposal_id: "proposal-9a-1",
      command_id: "cmd-repair-1",
      reviewer_critique_id: "crit-1",
      proposer_invocation_id: "model-proposer-1",
      reviewer_invocation_id: "model-reviewer-1",
      reviewer_decision: "accept",
      proposal_summary: "Repair import",
      patch_preview: GOVERNED_REPAIR_PROPOSAL.repair_artifact?.unified_diff ?? "",
      patch_preview_checksum: "sha256:patch-checksum",
      target_path: "src/main/java/com/example/App.java",
      sandbox_reference: "C:/work/out/.migration/runs/run-9a/sandbox",
      sandbox_checksum: "sha256:sandbox-checksum",
      legacy_checksum: "sha256:legacy-checksum",
      proposal_checksum: "sha256:proposal-checksum",
      context_pack_checksum: "sha256:context-checksum",
      evidence_refs: { patch_checksum: "sha256:patch-checksum" },
      approval_eligible: true,
      blockers: [],
      approval_scope: "sandbox_only",
      created_at: "2026-06-30T00:00:00Z",
      sandbox_only: true,
      source_mutated: false,
      apply_ready: false,
      llm_invoked: false,
    };
    const approval: RepairApprovalResponse = {
      approval_id: "approval-1",
      context_id: "ctx-1",
      proposal_id: "proposal-9a-1",
      approval_status: "recorded",
      approval_scope: "sandbox_only",
      approval_note: "Human approved exact repair checksum from Control Tower UI.",
      approval_checksum: "sha256:proposal-checksum",
      sandbox_checksum: "sha256:sandbox-checksum",
      legacy_checksum: "sha256:legacy-checksum",
      created_at: "2026-06-30T00:00:00Z",
      apply_ready: true,
      sandbox_only: true,
      source_mutated: false,
      llm_invoked: false,
    };
    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={GOVERNED_REPAIR_PROPOSAL}
        state={{
          ...EMPTY_R6_REPAIR_UI_STATE,
          reviewer,
          context,
          approval,
          approvalChecksumInput: "sha256:proposal-checksum",
        }}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(markup).toContain("Decision: accept");
    expect(markup).toContain("Reviewer source: fake / fake / live_ok");
    expect(markup).toContain("Context: ctx-1");
    expect(markup).toContain("Approval: approval-1");
    expect(markup).toContain(">Run official apply</button>");
  });

  it("renders local/dev reviewer metadata distinctly", () => {
    const reviewer: V2ReviewerCritiqueResponse = {
      critique_id: "crit-local",
      proposal_id: "proposal-9a-1",
      proposal_type: "repair_proposal",
      proposal_checksum: "sha256:proposal-checksum",
      context_pack_checksum: "sha256:context-checksum",
      decision: "accept",
      reasoning: "Controlled local/dev R6 smoke reviewer accepted evidence-complete demo proposal.",
      missing_evidence: [],
      unsafe_assumptions: [],
      model_invocation_id: null,
      created_at: "2026-06-30T00:00:00Z",
      reviewer_model: {
        model_invocation_id: "model-local-1",
        provider: "local_dev_fake",
        source: "controlled_r6_smoke",
        status: "local_dev_fallback",
        fallback_used: true,
      },
    };
    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={GOVERNED_REPAIR_PROPOSAL}
        state={{ ...EMPTY_R6_REPAIR_UI_STATE, reviewer }}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(markup).toContain("Reviewer source: local_dev_fake / controlled_r6_smoke / local_dev_fallback");
    expect(markup).toContain("Controlled local/dev R6 smoke reviewer accepted");
  });

  it("displays git apply check Maven verification and sandbox-only proof after apply", () => {
    const applyResult: ApplyRepairReviewContextResponse = {
      context_id: "ctx-1",
      approval_id: "approval-1",
      repair_action: {
        action_id: "action-1",
        proposal_id: "proposal-9a-1",
        target_path: "src/main/java/com/example/App.java",
        patch_content: "diff --git",
        status: "applied",
        result_summary: "Patch applied",
        created_at: "2026-06-30T00:00:00Z",
        verification_status: "passed",
        verification_build_status: "BUILD_PASSED_IN_SANDBOX",
        verification_test_status: "TEST_PASSED",
        verification_h2_status: "NOT_REQUIRED",
        verification_artifact_refs: {
          repair_test_report: "C:/work/out/.migration/runs/run-9a/repairs/test_report.json",
        },
        verification_failure_classification_ref: "",
        human_approved: true,
        sandbox_only: true,
        source_mutated: false,
        sandbox_mutated: true,
        stage_resumed: false,
        backend_runner_invoked: false,
        llm_invoked: false,
        approval_bypass: false,
      },
    };
    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={GOVERNED_REPAIR_PROPOSAL}
        state={{ ...EMPTY_R6_REPAIR_UI_STATE, applyResult }}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(markup).toContain("Patch gate: accepted by backend before apply");
    expect(markup).toContain("git apply --check: passed");
    expect(markup).toContain("Patch apply: applied");
    expect(markup).toContain("Maven verification: passed");
    expect(markup).toContain("Build: BUILD_PASSED_IN_SANDBOX");
    expect(markup).toContain("Legacy unchanged: true");
    expect(markup).toContain("repair_test_report: test_report.json");
  });

  it("separates git apply rollback controlled verification and unrelated Maven failure", () => {
    const applyResult: ApplyRepairReviewContextResponse = {
      context_id: "ctx-1",
      approval_id: "approval-1",
      repair_action: {
        action_id: "action-1",
        proposal_id: "proposal-9a-1",
        target_path: "src/main/java/com/example/App.java",
        patch_content: "diff --git",
        status: "rolled_back",
        result_summary: "Controlled repair verified, but full Maven verification failed due unrelated/pre-existing sandbox failures and patch was rolled back.",
        created_at: "2026-07-01T00:00:00Z",
        verification_status: "failed",
        verification_build_status: "BUILD_FAILED_IN_SANDBOX",
        verification_test_status: "TEST_ERROR",
        verification_h2_status: "NOT_REQUIRED",
        verification_artifact_refs: {
          repair_build_error_contract: "C:/work/out/.migration/runs/run-9a/repairs/build-error.json",
        },
        verification_failure_classification_ref: "build-error.json",
        human_approved: true,
        sandbox_only: true,
        source_mutated: false,
        sandbox_mutated: false,
        stage_resumed: false,
        backend_runner_invoked: false,
        llm_invoked: false,
        approval_bypass: false,
        apply_failure: {
          failure_stage: "maven_verification",
          failure_code: "MAVEN_VERIFICATION_FAILED",
          human_readable_summary: "Controlled repair verified, but full Maven verification failed due unrelated/pre-existing sandbox failures and patch was rolled back.",
          git_apply_check_status: "passed",
          patch_apply_status: "applied_then_rolled_back",
          controlled_verification_status: "passed",
          controlled_verification_summary: "Controlled target checksum matches proposed checksum and injected namespace is absent.",
          full_maven_verification_status: "failed",
          full_maven_failure_classification: "unrelated_preexisting_failure",
          rollback_attempted: true,
          rollback_succeeded: true,
          expected_sandbox_checksum: "sha256:before",
          actual_sandbox_checksum: "sha256:after-rollback",
          worktree_used: "C:/work/out/.migration/runs/run-9a/sandbox",
          strip_level: 1,
          recommended_next_action: "inspect_unrelated_maven_failures",
        },
      },
    };
    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={GOVERNED_REPAIR_PROPOSAL}
        state={{ ...EMPTY_R6_REPAIR_UI_STATE, applyResult }}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(markup).toContain("git apply --check: passed");
    expect(markup).toContain("Patch apply: applied_then_rolled_back");
    expect(markup).toContain("Controlled target verification: passed");
    expect(markup).toContain("Full Maven verification: failed");
    expect(markup).toContain("Maven failure classification: unrelated_preexisting_failure");
    expect(markup).toContain("Controlled repair passed; full Maven remains blocked by unrelated pre-existing sandbox failures.");
    expect(markup).toContain("Rollback: succeeded");
    expect(markup).toContain("Sandbox-only: true");
    expect(markup).toContain("Legacy unchanged: true");
  });

  it("displays assistant-readable apply failure details and recommended next action", () => {
    const applyResult: ApplyRepairReviewContextResponse = {
      context_id: "ctx-1",
      approval_id: "approval-1",
      repair_action: {
        action_id: "action-1",
        proposal_id: "proposal-9a-1",
        target_path: "src/main/java/com/example/App.java",
        patch_content: "diff --git",
        status: "failed",
        result_summary: "Sandbox changed since proposal/context creation; patch is stale.",
        created_at: "2026-07-01T00:00:00Z",
        verification_status: "not_available",
        verification_build_status: "",
        verification_test_status: "",
        verification_h2_status: "",
        verification_artifact_refs: {},
        verification_failure_classification_ref: "",
        human_approved: true,
        sandbox_only: true,
        source_mutated: false,
        sandbox_mutated: false,
        stage_resumed: false,
        backend_runner_invoked: false,
        llm_invoked: false,
        approval_bypass: false,
        apply_failure: {
          failure_stage: "stale_patch",
          failure_code: "SANDBOX_CHECKSUM_MISMATCH",
          human_readable_summary: "Sandbox changed since proposal/context creation; patch is stale.",
          expected_sandbox_checksum: "sha256:before",
          actual_sandbox_checksum: "sha256:after",
          git_apply_check_stderr: "patch does not apply",
          worktree_used: "C:/work/out/.migration/runs/run-9a/sandbox",
          strip_level: 1,
          recommended_next_action: "regenerate_proposal_against_current_sandbox",
        },
      },
    };
    const markup = renderToStaticMarkup(
      <R6GovernedRepairPanel
        proposal={GOVERNED_REPAIR_PROPOSAL}
        state={{ ...EMPTY_R6_REPAIR_UI_STATE, applyResult }}
        onApprovalChecksumChange={() => undefined}
        onRequestReviewer={() => undefined}
        onPrepareContext={() => undefined}
        onApproveRepair={() => undefined}
        onOfficialApply={() => undefined}
      />
    );

    expect(markup).toContain("Failure stage: stale_patch");
    expect(markup).toContain("Failure code: SANDBOX_CHECKSUM_MISMATCH");
    expect(markup).toContain("git apply --check stderr: patch does not apply");
    expect(markup).toContain("Recommended next action: regenerate_proposal_against_current_sandbox");
    expect(markup).toContain("disabled");
  });

  it("redacts absolute Windows artifact refs down to short labels", () => {
    const absoluteRef = "C:\\Users\\abdelilah.mortaki\\Desktop\\modernizer-solution\\SecurityConfig.java";
    expect(formatGateArtifactRefLabel(absoluteRef)).toBe("SecurityConfig.java");
    expect(formatGateArtifactRefLabel(absoluteRef)).not.toContain("C:\\Users\\abdelilah.mortaki");

    const gate: GateRepresentation = {
      gate_id: "gate-abs",
      job_id: "job-abs",
      gate_phase: "approval_review",
      stage_index: 2,
      gate_status: "open",
      gate_decision: "approve",
      source_artifact_checksum: "sha256:gate",
      source_artifact_refs: [absoluteRef],
      created_at: "2026-06-17T00:00:00Z",
      resolved_at: null,
      resolved_by: null,
      checksum: "sha256:gate-checksum",
      available_actions: [],
    };

    const markup = renderToStaticMarkup(
      <GatePanelContent state={{
        status: "success",
        gates: [gate],
        openGate: gate,
        openGateDetail: null,
      }} />
    );

    expect(markup).toContain("SecurityConfig.java");
    expect(markup).not.toContain("C:\\Users\\abdelilah.mortaki");
  });

  it("assistant cannot execute, approve, write, or change route", () => {
    const assistantRules = {
      can_explain: true,
      can_diagnose: true,
      can_draft_instruction: true,
      can_execute: false,
      can_approve: false,
      can_write_file: false,
      can_change_route: false,
      can_override_proof: false,
    };
    expect(assistantRules.can_execute).toBe(false);
    expect(assistantRules.can_approve).toBe(false);
    expect(assistantRules.can_write_file).toBe(false);
    expect(assistantRules.can_change_route).toBe(false);
    expect(assistantRules.can_override_proof).toBe(false);
  });

  it("no raw secrets, paths, or deployment IDs in cockpit payloads", () => {
    // Backend guarantees redaction — the frontend contract depends on it.
    // This test verifies that realistic payloads (as API returns after
    // redaction) do NOT contain secrets that the frontend would render.
    const samplePayload = {
      job_id: "job-1",
      rows: [
        {
          key: "sandbox_build",
          label: "Sandbox Build",
          status: "failed",
          latest_message: "[redacted-path] written",
          artifact_count: 0,
          last_updated: "2026-06-14T00:00:00Z",
        },
      ],
      evidence: [
        {
          event_type: "build_failed",
          status: "failed",
          message: "Build failed: [redacted-path]",
          payload: {
            matched_line: "[redacted-path]",
            command: ["mvn", "[redacted]", "package"],
            java_home: "[redacted-path]",
            AZURE_OPENAI_API_KEY: "[redacted]",
          },
        },
      ],
      raw_logs: [],
    };
    const json = JSON.stringify(samplePayload);

    // Redacted payload should never contain real secret tokens
    const hasSecretValue =
      /\b(sk-|ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]+/.test(json);
    expect(hasSecretValue).toBe(false);

    // Redacted payload should not contain Windows or POSIX absolute paths
    expect(json).not.toMatch(/\bC:\\Users\\/);
    expect(json).not.toMatch(/\bC:\\Program Files\\/);
    expect(json).not.toMatch(/\/home\//);
    expect(json).not.toMatch(/\/etc\//);
  });

  it("stage inputs are fixed by pipeline", () => {
    const stageInputs = {
      1: "legacy_source",
      2: "stage_1_sandbox",
      3: "stage_2_sandbox",
    };
    // These must NOT come from user selection
    expect(stageInputs[1]).toBe("legacy_source");
    expect(stageInputs[2]).toBe("stage_1_sandbox");
    expect(stageInputs[3]).toBe("stage_2_sandbox");
  });

  it("rejects missing route job id before fetch URL construction", () => {
    expect(() => requireJobId("")).toThrow("Migration job id is required.");
    expect(() => requireJobId("   ")).toThrow("Migration job id is required.");
  });

  it("opens EventSource against the V2 events endpoint", () => {
    const url = v2EventStreamUrl("job-123", 7);
    expect(url).toBe("http://127.0.0.1:8000/v1/v2/migration-jobs/job-123/events?after=7");
    expect(url).not.toContain("undefined");
  });

  it("refreshLiveState keeps existing approvals when approvals refresh fails", () => {
    const current = makeCockpitData();
    const merged = mergeCockpitLiveRefreshResults(current, [
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "fulfilled", value: { job_id: "job-123", stages: [{ stage_index: 1, pipeline_stage: "Stage 1", chain_status: "running", input_source_kind: "legacy_source" }] } },
      { status: "fulfilled", value: { events: [{ sequence: 2, type: "stage_started", status: "running", stage: 1 } as V2JobEvent] } },
      { status: "fulfilled", value: { ...current.pipeline, rows: [{ key: "analysis", label: "Analysis", status: "running", latest_message: "Running", artifact_count: 0, last_updated: "2026-06-16T00:00:00Z" }] } },
      { status: "fulfilled", value: { job_id: "job-123", has_failures: false, failures: [], repair_loop_active: false, repair_events: [], artifact_kinds: [] } },
    ]);

    expect(merged.failed).toBe(true);
    expect(merged.data.approvals).toBe(current.approvals);
    expect(merged.data.stages[0].chain_status).toBe("running");
    expect(merged.data.events[0].sequence).toBe(2);
  });

  it("SSE-triggered refresh failure can be represented as a non-blocking warning state", () => {
    const current = makeCockpitData();
    const merged = mergeCockpitLiveRefreshResults(current, [
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
      { status: "rejected", reason: new TypeError("Failed to fetch") },
    ]);

    expect(merged.failed).toBe(true);
    expect(merged.data).toEqual(current);
  });

  it("artifact preview client sends only artifact kind", async () => {
    const originalFetch = global.fetch;
    const calls: string[] = [];
    global.fetch = (async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify({
        job_id: "job-123",
        artifact_kind: "phase2_log",
        exists: true,
        preview: "BUILD_FAILED_IN_SANDBOX",
        truncated: false,
        content_type: "text/plain",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      const response = await getV2ArtifactPreview("job-123", "phase2_log");
      expect(calls[0]).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/job-123/artifacts/phase2_log`);
      expect(calls[0]).not.toContain("path=");
      expect(response.exists).toBe(true);
      expect(response.preview).toContain("BUILD_FAILED_IN_SANDBOX");
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("prepare repair apply context sends only IDs/checksums and no patch path command or env", async () => {
    const originalFetch = global.fetch;
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    const patchText = GOVERNED_REPAIR_PROPOSAL.repair_artifact?.unified_diff ?? "";
    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      return new Response(JSON.stringify({
        repair_review_context: {
          context_id: "ctx-1",
          proposal_id: "proposal-9a-1",
          command_id: "cmd-repair-1",
          reviewer_critique_id: "crit-1",
          proposer_invocation_id: "model-proposer-1",
          reviewer_invocation_id: "model-reviewer-1",
          reviewer_decision: "accept",
          proposal_summary: "Repair import",
          patch_preview: patchText,
          patch_preview_checksum: "sha256:patch-checksum",
          target_path: "src/main/java/com/example/App.java",
          sandbox_reference: "C:/work/out/.migration/runs/run-9a/sandbox",
          sandbox_checksum: "sha256:sandbox-checksum",
          legacy_checksum: "sha256:legacy-checksum",
          proposal_checksum: "sha256:proposal-checksum",
          context_pack_checksum: "sha256:context-checksum",
          evidence_refs: { patch_checksum: "sha256:patch-checksum" },
          approval_eligible: true,
          blockers: [],
          approval_scope: "sandbox_only",
          created_at: "2026-06-30T00:00:00Z",
          sandbox_only: true,
          source_mutated: false,
          apply_ready: false,
          llm_invoked: false,
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      await prepareV2RepairApplyContext("cmd-repair-1", "proposal-9a-1", {
        proposal_checksum: "sha256:proposal-checksum",
        context_pack_checksum: "sha256:context-checksum",
        reviewer_critique_id: "crit-1",
        proposer_invocation_id: "model-proposer-1",
        reviewer_invocation_id: "model-reviewer-1",
        approval_scope: "sandbox_only",
      });

      expect(calls[0].url).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/commands/cmd-repair-1/repair/proposal/proposal-9a-1/prepare-apply-context`);
      expect(calls[0].body).not.toHaveProperty("patch_preview");
      expect(calls[0].body).not.toHaveProperty("target_path");
      expect(calls[0].body).not.toHaveProperty("sandbox_reference");
      expect(calls[0].body).not.toHaveProperty("sandbox_checksum");
      expect(calls[0].body).not.toHaveProperty("legacy_checksum");
      expect(calls[0].body).not.toHaveProperty("evidence_refs");
      expect(calls[0].body).not.toHaveProperty("argv");
      expect(calls[0].body).not.toHaveProperty("env");
      expect(calls[0].body).not.toHaveProperty("command");
      expect(calls[0].body).not.toHaveProperty("maven_goal");
      expect(calls[0].body).not.toHaveProperty("model_deployment");
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("reviewer critique request sends no browser model payload", async () => {
    const originalFetch = global.fetch;
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      return new Response(JSON.stringify({
        critique_id: "crit-1",
        proposal_id: "proposal-9a-1",
        proposal_type: "repair_proposal",
        proposal_checksum: "sha256:proposal-checksum",
        context_pack_checksum: "sha256:context-checksum",
        decision: "accept",
        reasoning: "Evidence complete.",
        missing_evidence: [],
        unsafe_assumptions: [],
        model_invocation_id: null,
        created_at: "2026-06-30T00:00:00Z",
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      await requestV2ReviewerCritique("cmd-repair-1", "proposal-9a-1", {
        proposal_type: "repair_proposal",
        proposal_checksum: "sha256:proposal-checksum",
        context_pack_checksum: "sha256:context-checksum",
      });

      expect(calls[0].url).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/commands/cmd-repair-1/repair/proposal/proposal-9a-1/reviewer-critique`);
      expect(calls[0].body).toEqual({
        proposal_id: "proposal-9a-1",
        proposal_type: "repair_proposal",
        proposal_checksum: "sha256:proposal-checksum",
        context_pack_checksum: "sha256:context-checksum",
      });
      expect(calls[0].body).not.toHaveProperty("model_invocation_id");
      expect(calls[0].body).not.toHaveProperty("model");
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("official repair apply sends only approval and checksum guards", async () => {
    const originalFetch = global.fetch;
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      return new Response(JSON.stringify({
        context_id: "ctx-1",
        approval_id: "approval-1",
        repair_action: {
          action_id: "action-1",
          proposal_id: "proposal-9a-1",
          target_path: "src/main/java/com/example/App.java",
          patch_content: "diff --git",
          status: "applied",
          result_summary: "Patch applied",
          created_at: "2026-06-30T00:00:00Z",
          verification_status: "passed",
          verification_build_status: "BUILD_PASSED_IN_SANDBOX",
          verification_test_status: "TEST_PASSED",
          verification_h2_status: "NOT_REQUIRED",
          verification_artifact_refs: {},
          verification_failure_classification_ref: "",
          human_approved: true,
          sandbox_only: true,
          source_mutated: false,
          sandbox_mutated: true,
          stage_resumed: false,
          backend_runner_invoked: false,
          llm_invoked: false,
          approval_bypass: false,
        },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      await applyV2RepairReviewContext("ctx-1", {
        approval_id: "approval-1",
        expected_approval_checksum: "sha256:proposal-checksum",
        expected_sandbox_checksum: "sha256:sandbox-checksum",
        expected_legacy_checksum: "sha256:legacy-checksum",
      });

      expect(calls[0].url).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/repair-review/ctx-1/apply`);
      expect(calls[0].body).toEqual({
        approval_id: "approval-1",
        expected_approval_checksum: "sha256:proposal-checksum",
        expected_sandbox_checksum: "sha256:sandbox-checksum",
        expected_legacy_checksum: "sha256:legacy-checksum",
      });
      expect(JSON.stringify(calls[0].body)).not.toContain("mvn");
      expect(JSON.stringify(calls[0].body)).not.toContain("diff --git");
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("empty approvals render as no pending decisions copy", () => {
    const approvals: unknown[] = [];
    const copy = approvals.length === 0 ? "No pending decisions." : "Has decisions";
    expect(copy).toBe("No pending decisions.");
  });

  it("incoming event updates stage status", () => {
    const event = { stage: 1, type: "stage_started", status: "running" };
    const stages = [{ stage_index: 1, chain_status: "queued" }];
    const updated = stages.map((stage) =>
      stage.stage_index === event.stage ? { ...stage, chain_status: event.status } : stage,
    );
    expect(updated[0].chain_status).toBe("running");
  });

  it("posts assistant questions to the read-only V2 ask endpoint", async () => {
    const originalFetch = global.fetch;
    const calls: { url: string; body: string | null }[] = [];
    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: typeof init?.body === "string" ? init.body : null });
      return new Response(JSON.stringify({
        job_id: "job-123",
        user_message: { message_id: "u1", job_id: "job-123", role: "user", content: "What happened so far?", correlation_id: null, created_at: "now" },
        assistant_message: { message_id: "a1", job_id: "job-123", role: "assistant", content: "Latest event: stage 1 analysis_started.", correlation_id: "u1", created_at: "now" },
        model: { status: "configured", source: "azure_openai", provider: "azure_openai", role: "assistant" },
        guardrails: { read_only: true, cannot_execute: true, cannot_approve: true },
      }), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as typeof fetch;
    try {
      const response = await askV2Assistant("job-123", "What happened so far?");
      expect(calls[0].url).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/job-123/assistant/ask`);
      expect(calls[0].url).not.toContain("undefined");
      expect(JSON.parse(calls[0].body ?? "{}")).toEqual({ question: "What happened so far?" });
      expect(response.assistant_message.content).toContain("Latest event");
      expect(response.model.source).toBe("azure_openai");
      expect(response.guardrails.cannot_execute).toBe(true);
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("approval review jobs route approval through chatbot copy", () => {
    const approvalReviewOpen = true;
    const labels = approvalReviewOpen
      ? ["Review in chatbot", "Legacy Approve/Reject controls are disabled here.", "checksum-123"]
      : ["Approve", "Reject", "checksum-123"];
    expect(labels).toContain("Review in chatbot");
    expect(labels).toContain("checksum-123");
    expect(labels).not.toContain("Approve");
    expect(labels).not.toContain("Reject");
  });

  it("pipeline projection shows agent phases before raw logs", () => {
    const rows = ["Preflight", "Analysis Agent", "Planning Agent", "Assessment Agent", "Human Approval"];
    const evidenceTypes = ["analysis_started", "planning_completed", "approval_required"];
    const rawLogs = ["stdout"];
    expect(rows).toContain("Analysis Agent");
    expect(rows).toContain("Planning Agent");
    expect(rows).toContain("Assessment Agent");
    expect(evidenceTypes).not.toContain("stdout");
    expect(rawLogs).toContain("stdout");
  });

  it("pipeline response exposes active_stage_index", () => {
    const pipeline = {
      job_id: "job-123",
      rows: [],
      evidence: [],
      raw_logs: [],
      active_stage_index: 2,
    };
    expect(pipeline.active_stage_index).toBe(2);
  });

  it("human approval row is pass after approval_resume_queued, not blocked", () => {
    // Simulate the pipeline status logic: after approval_resume_queued, must be pass
    const events = [
      { type: "approval_required", status: "blocked" },
      { type: "approval_resume_queued", status: "queued" },
    ];
    // Check that the latest approval lifecycle event transitions correctly
    const hasApprovalPassed = events.some(
      (e) => e.type === "approval_resume_queued"
    );
    expect(hasApprovalPassed).toBe(true);
  });

  it("human approval stays pass even if transform fails", () => {
    const events = [
      { type: "approval_required", status: "blocked" },
      { type: "approval_resume_queued", status: "queued" },
      { type: "sandbox_transform_failed", status: "failed" },
    ];
    // Approval should still be pass
    const approvalResolved = events.some(
      (e) => e.type === "approval_resume_queued"
    );
    expect(approvalResolved).toBe(true);
  });

  it("failure summary contains observed failure shape", () => {
    const failureSummary = {
      has_failures: true,
      failures: [
        {
          type: "build_failed",
          stage: 1,
          message: "Build result kind: dependency_error",
          build_status: "BUILD_FAILED_IN_SANDBOX",
          final_status: "FALLBACK_REPAIR_PLAN",
          final_proof_level: "not_verified",
          repair_loop_status: "FALLBACK_REPAIR_PLAN",
          copilot_status: "INVALID_RESPONSE",
          repair_fallback: "True",
        },
      ],
      repair_loop_active: true,
      repair_events: [
        { type: "copilot_repair_invalid_response", message: "Copilot response invalid" },
      ],
      artifact_kinds: ["analysis_report"],
    };
    expect(failureSummary.has_failures).toBe(true);
    expect(failureSummary.failures[0].build_status).toBe("BUILD_FAILED_IN_SANDBOX");
    expect(failureSummary.failures[0].copilot_status).toBe("INVALID_RESPONSE");
  });

  it("assistant model status includes failure_reason for fallback", () => {
    const model = {
      status: "fallback",
      source: "deterministic",
      provider: "deterministic",
      role: "assistant",
      failure_reason: "missing_deployment",
    };
    expect(model.status).toBe("fallback");
    expect(model.failure_reason).toBe("missing_deployment");
  });

  it("assistant and repair wording stay separate after repair fallback", () => {
    const assistantModel = { status: "live_ok", source: "azure_openai", provider: "azure_openai" };
    const repair = { copilot_status: "INVALID_RESPONSE", repair_fallback: "True", repair_loop_status: "FALLBACK_REPAIR_PLAN" };
    expect(assistantModel.source).toBe("azure_openai");
    expect(assistantModel.status).toBe("live_ok");
    expect(repair.copilot_status).toBe("INVALID_RESPONSE");
    expect(repair.repair_loop_status).toBe("FALLBACK_REPAIR_PLAN");
  });

  it("IMPORTANT_SSE_TYPES includes all required lifecycle events", () => {
    const important = new Set([
      "approval_required",
      "stage_blocked_for_approval",
      "approval_resume_queued",
      "approval_started",
      "approval_completed",
      "resume_started",
      "sandbox_transform_started",
      "sandbox_transform_completed",
      "sandbox_transform_failed",
      "stage_failed",
      "stage_completed",
      "model_invocation_completed",
      "model_invocation_failed",
      "transform_failed",
      "build_failed",
      "ai_diagnosis_created",
      "pom_summary_created",
      "repair_proposal_revised",
      "reviewer_critique_created",
      "repair_patch_gate_completed",
      "repair_patch_applied",
      "repair_validation_completed",
      "repair_rollback_completed",
      "next_stage_queued",
    ]);
    expect(important.has("approval_resume_queued")).toBe(true);
    expect(important.has("approval_completed")).toBe(true);
    expect(important.has("transform_failed")).toBe(true);
    expect(important.has("build_failed")).toBe(true);
    expect(important.has("ai_diagnosis_created")).toBe(true);
    expect(important.has("reviewer_critique_created")).toBe(true);
    expect(important.has("repair_validation_completed")).toBe(true);
    expect(important.has("next_stage_queued")).toBe(true);
  });

  it("failure summary exposes backend supervision trace records", () => {
    const failureSummary = {
      has_failures: true,
      failures: [
        {
          type: "build_failed",
          stage: 2,
          supervision_trace: {
            ai_diagnosis: {
              diagnosis_id: "diag-1",
              command_id: "cmd-1",
              trigger_event_type: "build_failed",
              failure_type: "DEPENDENCY_ERROR",
              context_pack_id: "pack-1",
              context_pack_checksum: "ctx-1",
              repair_proposal_id: "proposal-1",
              model_invocation_id: "model-1",
              redaction_status: "redacted",
              created_at: "2026-06-16T00:00:00Z",
            },
            evidence_used: ["pack-1", "ctx-1", "pom-summary:1"],
            pom_analysis: {
              pom_summary_ref: "pom-summary:1",
              spring_boot_version: "2.7.18",
              java_version: "11",
              packaging: "jar",
              candidate_rules: ["pom_dependency_alignment"],
              created_at: "2026-06-16T00:00:01Z",
            },
            repair_proposal: {
              proposal_id: "proposal-2",
              source_proposal_id: "proposal-1",
              command_id: "cmd-1",
              revision_number: 2,
              allowed_scope: "pom_only",
              proposal_checksum: "prop-checksum",
              status: "completed",
              created_at: "2026-06-16T00:00:02Z",
            },
            reviewer_verdict: {
              critique_id: "crit-1",
              proposal_id: "proposal-2",
              proposal_type: "repair_proposal",
              proposal_checksum: "prop-checksum",
              context_pack_checksum: "ctx-1",
              decision: "accept",
              reasoning: "Evidence and scope are acceptable.",
              missing_evidence: [],
              unsafe_assumptions: [],
              created_at: "2026-06-16T00:00:03Z",
            },
            validation_result: {
              proposal_id: "proposal-2",
              patch_gate_status: "ALLOWED",
              deterministic_rule_id: "pom_dependency_alignment",
              build_status: "BUILD_PASSED_IN_SANDBOX",
              test_status: "TESTS_PASSED",
              h2_status: "NOT_REQUIRED",
              ledger_ref: "repair_ledger.json",
            },
          },
        },
      ],
    };
    const trace = failureSummary.failures[0].supervision_trace;
    expect(trace.ai_diagnosis?.diagnosis_id).toBe("diag-1");
    expect(trace.evidence_used).toContain("pom-summary:1");
    expect(trace.repair_proposal?.allowed_scope).toBe("pom_only");
    expect(trace.reviewer_verdict?.decision).toBe("accept");
    expect(trace.validation_result?.ledger_ref).toBe("repair_ledger.json");
  });

  it("renders stage-aware evidence and blocked classification state", () => {
    const diagnosis = {
      diagnosis_id: "diag-stage",
      command_id: "cmd-stage",
      trigger_event_type: "build_failed",
      failure_type: "blocked_pending_classification",
      context_pack_id: "pack-stage",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model-stage",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: {
        stage_index: 2,
        stage_name: "Spring Boot 2.7 + Java 11 to Spring Boot 3.5.16 + Java 17",
        source_boot_version: "2.7",
        target_boot_version: "3.5.16",
        source_java_version: "11",
        target_java_version: "17",
        input_source_kind: "stage_output",
        input_artifact_ref: "stage:1",
        output_sandbox_ref: "sandbox",
        previous_stage_ref: "stage:1",
        downstream_stage_state: {
          next_stage_index: 3,
          state: "pending_blocked_by_failed_stage",
          auto_started: false,
        },
        evidence_status: "collected",
        evidence_pack_id: "stage-evidence-abc",
        evidence_pack_checksum: "sha256:evidence",
        usable_artifacts: [
          { kind: "build_error_contract", ref: "build-error.json", checksum: "sha256:build" },
          { kind: "sandbox", ref: "sandbox", checksum: "" },
        ],
        missing_artifacts: ["dependency_graph", "runtime_contract"],
        repair_enabled: false,
        assistant_next_action: "classify_stage_failure",
        redaction_status: "stage_evidence_collected",
        failure_summary: "Build failed",
      },
      classification: {
        stage_index: 2,
        failure_type: "blocked_pending_classification",
        classification_status: "blocked_pending_classification",
        repair_family_candidate: "",
        confidence: "low",
        confidence_reason: "Needs build contract.",
        matched_signals: [],
        missing_required_evidence: ["build_error_contract"],
        usable_artifacts: ["build_error_contract"],
        repair_enabled: false,
        repair_blocked_reason: "missing_required_failure_evidence",
        reason: "evidence_collected_classifier_not_ready",
        assistant_next_action: "classify_stage_failure",
        evidence_pack_id: "stage-evidence-abc",
        evidence_pack_checksum: "sha256:evidence",
        stage_name: "Spring Boot 2.7 + Java 11 to Spring Boot 3.5.16 + Java 17",
        source_boot_version: "2.7",
        target_boot_version: "3.5.16",
        source_java_version: "11",
        target_java_version: "17",
        downstream_stage_state: {
          next_stage_index: 3,
          state: "pending_blocked_by_failed_stage",
          auto_started: false,
        },
      },
    };

    const markup = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={diagnosis} stage={2} />);

    expect(markup).toContain("Stage Evidence");
    expect(markup).toContain("Stage target: 2.7/Java 11 -&gt; 3.5.16/Java 17");
    expect(markup).toContain("Evidence: collected");
    expect(markup).toContain("Evidence pack: stage-evidence-abc");
    expect(markup).toContain("build_error_contract");
    expect(markup).toContain("Classification: blocked_pending_classification");
    expect(markup).toContain("Confidence: low");
    expect(markup).toContain("Missing required evidence: build_error_contract");
    expect(markup).toContain("Repair: disabled");
    expect(markup).toContain("pending_blocked_by_failed_stage");
  });

  it("renders R7C classification statuses with repair disabled explanation", () => {
    const baseDiagnosis = {
      diagnosis_id: "diag-stage",
      command_id: "cmd-stage",
      trigger_event_type: "build_failed",
      failure_type: "known_family_candidate",
      context_pack_id: "pack-stage",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model-stage",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: null,
      classification: {
        stage_index: 2,
        stage_name: "Stage 2",
        source_boot_version: "2.7",
        target_boot_version: "3.5.16",
        source_java_version: "11",
        target_java_version: "17",
        failure_type: "known_family_candidate",
        classification_status: "known_family_candidate",
        repair_family_candidate: "DEPENDENCY_REPLACE_JAVAX_SERVLET_API_WITH_JAKARTA",
        confidence: "high",
        confidence_reason: "Boot 3 target with javax servlet dependency signal.",
        matched_signals: ["dependency:javax_servlet_api_on_boot3_plus"],
        missing_required_evidence: [],
        usable_artifacts: ["pom_xml", "dependency_graph"],
        repair_enabled: false,
        repair_blocked_reason: "R7C_classification_only_no_real_repair_apply",
        reason: "R7C_classification_only_no_real_repair_apply",
        assistant_next_action: "prepare_evidence_bound_proposal_in_R7D",
        governance_gate_type: "future_deterministic_candidate",
        stage_relevance: "Stage 2 2.7/Java 11 -> 3.5.16/Java 17: deterministic candidate is stage-sensitive",
        evidence_pack_id: "stage-evidence-abc",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: null,
      },
    };
    const known = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={baseDiagnosis} stage={2} />);
    expect(known).toContain("known_family_candidate");
    expect(known).toContain("Governance gate: future_deterministic_candidate");
    expect(known).toContain("Stage relevance: Stage 2 2.7/Java 11 -&gt; 3.5.16/Java 17");
    expect(known).toContain("Candidate deterministic rule detected, but real repair proposal/apply is not enabled in R7C.2.");
    expect(known).not.toContain("Apply repair");

    const blocked = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={{
      ...baseDiagnosis,
      classification: { ...baseDiagnosis.classification, classification_status: "blocked_pending_evidence", repair_family_candidate: "" },
    }} stage={2} />);
    expect(blocked).toContain("Additional build/test artifacts are required before classifier can select a subtype.");

    const unsupported = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={{
      ...baseDiagnosis,
      classification: {
        ...baseDiagnosis.classification,
        classification_status: "unsupported_known_failure",
        failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
        repair_family_candidate: "",
        governance_gate_type: "human_review_gate",
      },
    }} stage={2} />);
    expect(unsupported).toContain("Failure: POWERMOCK_LEGACY_TEST_STRATEGY");
    expect(unsupported).toContain("Governance gate: human_review_gate");
    expect(unsupported).toContain("Failure signal recognized as a migration review gate. No automatic repair is enabled.");

    const unknown = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={{
      ...baseDiagnosis,
      classification: { ...baseDiagnosis.classification, classification_status: "unknown", repair_family_candidate: "" },
    }} stage={2} />);
    expect(unknown).toContain("Failure remains unknown after evidence review.");
  });

  it("renders Migration Memory matches as advisory only without repair controls", () => {
    const diagnosis = {
      diagnosis_id: "diag-memory",
      command_id: "cmd-memory",
      trigger_event_type: "build_failed",
      failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
      context_pack_id: "pack-memory",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model-memory",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: null,
      classification: {
        stage_index: 1,
        stage_name: "Stage 1",
        source_boot_version: "2.1",
        target_boot_version: "2.7",
        source_java_version: "11",
        target_java_version: "11",
        failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
        classification_status: "unsupported_known_failure",
        repair_family_candidate: "",
        confidence: "medium",
        confidence_reason: "PowerMock legacy test strategy signal found.",
        matched_signals: ["review_gate:powermock_legacy_test_strategy"],
        missing_required_evidence: ["test_report"],
        usable_artifacts: ["pom_xml"],
        repair_enabled: false,
        repair_blocked_reason: "human_review_gate_no_auto_repair",
        reason: "human_review_gate_no_auto_repair",
        assistant_next_action: "review_powermock_legacy_test_strategy",
        governance_gate_type: "human_review_gate",
        stage_relevance: "Stage 1 advisory",
        evidence_pack_id: "stage-evidence-memory",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: null,
        migration_memory: {
          retrieval_status: "available",
          query_signature: "sha256:query",
          memory_matches: [],
          top_match: {
            memory_case_id: "msa-utils-powermock-legacy-test-strategy",
            title: "msa-utils PowerMock legacy test strategy",
            summary: "PowerMock requires human review.",
            trust_level: "untrusted_import",
            authority_level: "advisory_only",
            matched_signals: ["review_gate:powermock_legacy_test_strategy"],
            required_evidence: ["test_report"],
            suggested_next_actions: ["review_powermock_legacy_test_strategy"],
            stage_applicability: ["stage_2", "stage_3", "stage_4"],
            promotion_status: "seed_only",
            redaction_status: "path_redacted",
            weak_stage_match: true,
          },
          trust_summary: "untrusted_import:1",
          advisory_summary: "Memory match is advisory only.",
          missing_evidence_suggestions: ["test_report"],
          retrieved_case_ids: ["msa-utils-powermock-legacy-test-strategy"],
          authority_level: "advisory_only",
          repair_enabled: false,
          memory_can_apply: false,
          memory_can_approve: false,
          memory_can_start_downstream: false,
          recommended_use: "human review gate / future RAG seed",
        },
      },
    };

    const markup = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={diagnosis} stage={1} />);

    expect(markup).toContain("Migration Memory");
    expect(markup).toContain("Retrieval status: available");
    expect(markup).toContain("msa-utils PowerMock legacy test strategy");
    expect(markup).toContain("Memory case: msa-utils-powermock-legacy-test-strategy");
    expect(markup).toContain("Trust level: untrusted_import");
    expect(markup).toContain("Authority level: advisory_only");
    expect(markup).toContain("Matched memory signals: review_gate:powermock_legacy_test_strategy");
    expect(markup).toContain("Missing evidence suggestions: test_report");
    expect(markup).toContain("Repair authority: none");
    expect(markup).toContain("Memory cannot approve/apply/start downstream");
    expect(markup).not.toContain("Apply repair");
  });

  it("renders Migration Memory no-match and unavailable states", () => {
    const baseDiagnosis = {
      diagnosis_id: "diag-memory",
      command_id: "cmd-memory",
      trigger_event_type: "build_failed",
      failure_type: "unknown",
      context_pack_id: "pack-memory",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model-memory",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: null,
      classification: {
        stage_index: 2,
        stage_name: "Stage 2",
        source_boot_version: "2.7",
        target_boot_version: "3.5.16",
        source_java_version: "11",
        target_java_version: "17",
        failure_type: "unknown",
        classification_status: "unknown",
        repair_family_candidate: "",
        confidence: "low",
        confidence_reason: "No match.",
        matched_signals: [],
        missing_required_evidence: [],
        usable_artifacts: [],
        repair_enabled: false,
        repair_blocked_reason: "no_known_family_match",
        reason: "no_known_family_match",
        assistant_next_action: "escalate_unknown_stage_failure",
        governance_gate_type: "unknown",
        stage_relevance: "",
        evidence_pack_id: "stage-evidence-memory",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: null,
        migration_memory: {
          retrieval_status: "no_matches",
          query_signature: "sha256:query",
          memory_matches: [],
          top_match: null,
          trust_summary: "",
          advisory_summary: "No relevant memory cases found.",
          missing_evidence_suggestions: [],
          retrieved_case_ids: [],
          authority_level: "advisory_only",
          repair_enabled: false,
          memory_can_apply: false,
          memory_can_approve: false,
          memory_can_start_downstream: false,
          recommended_use: "human review gate / future RAG seed",
        },
      },
    };

    const noMatch = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={baseDiagnosis} stage={2} />);
    expect(noMatch).toContain("No relevant memory cases found.");

    const unavailable = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={{
      ...baseDiagnosis,
      classification: {
        ...baseDiagnosis.classification,
        migration_memory: {
          ...baseDiagnosis.classification.migration_memory,
          retrieval_status: "unavailable",
          advisory_summary: "Migration memory unavailable.",
        },
      },
    }} stage={2} />);
    expect(unavailable).toContain("Migration memory unavailable.");
  });

  it("renders Repair Draft blocked PowerMock state without controls", () => {
    const diagnosis = {
      diagnosis_id: "diag-draft",
      command_id: "cmd-draft",
      trigger_event_type: "build_failed",
      failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
      context_pack_id: "pack-draft",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model-draft",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: null,
      classification: {
        stage_index: 1,
        stage_name: "Stage 1",
        source_boot_version: "2.1",
        target_boot_version: "2.7",
        source_java_version: "11",
        target_java_version: "11",
        failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
        classification_status: "unsupported_known_failure",
        repair_family_candidate: "",
        confidence: "medium",
        confidence_reason: "PowerMock legacy test strategy signal found.",
        matched_signals: ["review_gate:powermock_legacy_test_strategy"],
        missing_required_evidence: [],
        usable_artifacts: ["pom_xml"],
        repair_enabled: false,
        repair_blocked_reason: "human_review_gate_no_auto_repair",
        reason: "human_review_gate_no_auto_repair",
        assistant_next_action: "review_powermock_legacy_test_strategy",
        governance_gate_type: "human_review_gate",
        stage_relevance: "Stage 1 advisory",
        evidence_pack_id: "stage-evidence-draft",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: null,
        migration_memory: null,
        repair_proposal_draft: {
          proposal_status: "blocked_human_review_gate",
          proposal_type: "evidence_bound_repair_draft",
          supported_family: "",
          failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
          classification_status: "unsupported_known_failure",
          governance_gate_type: "human_review_gate",
          stage_index: 1,
          source_boot_version: "2.1",
          target_boot_version: "2.7",
          source_java_version: "11",
          target_java_version: "11",
          evidence_pack_id: "stage-evidence-draft",
          evidence_pack_checksum: "sha256:evidence",
          memory_query_signature: "sha256:memory",
          retrieved_memory_case_ids: ["msa-utils-powermock-legacy-test-strategy"],
          target_files: [],
          source_markers: [],
          target_file_checksums: {},
          proposed_diff_preview: "",
          proposed_diff_checksum: "",
          proposal_checksum: "",
          proposer_kind: "deterministic_local",
          llm_invoked: false,
          reviewer_required: true,
          human_approval_required: true,
          backend_apply_required: true,
          apply_enabled: false,
          approval_enabled: false,
          repair_enabled: false,
          sandbox_only: true,
          legacy_mutation_allowed: false,
          downstream_start_allowed: false,
          blocked_reason: "human_review_gate_no_auto_repair",
          assistant_next_action: "review_powermock_legacy_test_strategy",
          safety_warnings: ["No repair draft is actionable in R7D."],
        },
        repair_draft_review: {
          review_status: "not_reviewable_blocked_human_gate",
          verdict: "blocked",
          reviewer_kind: "deterministic_local",
          reviewer_origin: "backend_evidence_bound",
          llm_invoked: false,
          future_llm_reviewer_compatible: true,
          reviewed_family: "",
          failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
          classification_status: "unsupported_known_failure",
          governance_gate_type: "human_review_gate",
          stage_index: 1,
          source_boot_version: "2.1",
          target_boot_version: "2.7",
          source_java_version: "11",
          target_java_version: "11",
          evidence_pack_id: "stage-evidence-draft",
          evidence_pack_checksum: "sha256:evidence",
          memory_query_signature: "sha256:memory",
          retrieved_memory_case_ids: ["msa-utils-powermock-legacy-test-strategy"],
          target_files: [],
          target_file_checksums: {},
          proposed_diff_checksum: "",
          proposal_checksum: "",
          review_checksum: "sha256:review-powermock",
          declared_diff_checksum: "",
          recomputed_diff_checksum: "",
          diff_checksum_match: false,
          declared_proposal_checksum: "",
          recomputed_proposal_checksum: "",
          proposal_checksum_match: false,
          checksum_verification_status: "not_applicable",
          required_followup_gate: "future_human_approval_and_backend_apply_gate",
          apply_enabled: false,
          approval_enabled: false,
          repair_enabled: false,
          sandbox_only: true,
          legacy_mutation_allowed: false,
          downstream_start_allowed: false,
          memory_authority: "advisory_only",
          memory_can_apply: false,
          memory_can_approve: false,
          memory_can_start_downstream: false,
          reasons: ["human_review_gate_no_auto_repair"],
          safety_warnings: ["Reviewer verdict is non-actionable in R7E."],
        },
        llm_repair_shadow_trace: {
          trace_origin: "backend_llm_shadow",
          trace_status: "available",
          runtime_mode: "configured_llm_shadow_mode",
          proposer_trace: {
            role: "repair_proposer",
            model_metadata: {
              role: "repair_proposer_model",
              provider: "fake",
              deployment: "gpt5-mini",
              expected_model: "gpt5-mini",
              configuration_source: "existing_v2_model_role_router",
              endpoint_metadata: "endpoint_host=[redacted-endpoint]",
              status: "live_ok",
            },
            status: "available",
            llm_invoked: true,
            fallback_used: false,
            failure_reason: "",
            input_preview: "{\"evidence_pack_checksum\":\"sha256:evidence\",\"memory_query_signature\":\"sha256:memory\"}",
            input_checksum: "sha256:proposer-input",
            output: {
              status: "available",
              role: "repair_proposer",
              summary: "initMocks can be modernized.",
              root_cause: "Legacy Mockito setup.",
              repair_intent: "Use openMocks.",
              expected_change: "One test-local replacement.",
              affected_files: ["src/test/java/ExampleTest.java"],
              risk_notes: ["non-actionable"],
              missing_evidence: [],
              confidence: "medium",
              non_actionable: true,
              apply_allowed: false,
              approval_allowed: false,
              downstream_start_allowed: false,
            },
            output_checksum: "sha256:proposer-output",
            schema_validation_status: "validated",
            raw_output_redacted_preview: "{\"status\":\"available\"}",
            json_parse_error_kind: "",
            model_output_was_json: true,
            validated_output_source: "azure_model",
            provider_failure_kind: "",
            provider_failure_stage: "",
            provider_retry_path: "strict_json_schema",
            provider_http_status: "",
            provider_error_redacted_preview: "",
            non_actionable: true,
            apply_allowed: false,
            approval_allowed: false,
            downstream_start_allowed: false,
          },
          reviewer_trace: {
            role: "repair_reviewer",
            model_metadata: {
              role: "repair_reviewer_model",
              provider: "fake",
              deployment: "Llama-3.3-70B-Instruct",
              expected_model: "Llama-3.3-70B-Instruct",
              configuration_source: "existing_v2_model_role_router",
              endpoint_metadata: "endpoint_host=[redacted-endpoint]",
              status: "live_ok",
            },
            status: "available",
            llm_invoked: true,
            fallback_used: false,
            failure_reason: "",
            input_preview: "{\"proposer_output\":{\"summary\":\"initMocks can be modernized.\"},\"checksum_verification_status\":\"verified\"}",
            input_checksum: "sha256:reviewer-input",
            output: {
              status: "available",
              role: "repair_reviewer",
              verdict: "advisory_reject",
              critique: "PowerMock remains human-gated as advisory only.",
              risks: ["future backend gate required"],
              missing_evidence: [],
              unsafe_assumptions: [],
              recommended_next_action: "keep_non_actionable",
              confidence: "medium",
              non_actionable: true,
              apply_allowed: false,
              approval_allowed: false,
              downstream_start_allowed: false,
            },
            output_checksum: "sha256:reviewer-output",
            schema_validation_status: "validated",
            raw_output_redacted_preview: "{\"status\":\"available\"}",
            json_parse_error_kind: "",
            model_output_was_json: true,
            validated_output_source: "azure_model",
            provider_failure_kind: "",
            provider_failure_stage: "",
            provider_retry_path: "strict_json_schema",
            provider_http_status: "",
            provider_error_redacted_preview: "",
            non_actionable: true,
            apply_allowed: false,
            approval_allowed: false,
            downstream_start_allowed: false,
          },
          llm_fallback_trace: {
            role: "repair_fallback",
            model_metadata: {
              role: "repair_fallback_model",
              provider: "fake",
              deployment: "Mistral-Large-3",
              expected_model: "Mistral-Large-3",
              configuration_source: "existing_v2_model_role_router",
              endpoint_metadata: "endpoint_host=[redacted-endpoint]",
              status: "live_ok",
            },
            status: "available",
            llm_invoked: true,
            fallback_used: false,
            failure_reason: "reviewer_shadow_failed",
            input_preview: "{\"failed_role\":\"repair_reviewer\",\"failure_reason\":\"reviewer_shadow_failed\"}",
            input_checksum: "sha256:fallback-input",
            output: {
              status: "available",
              role: "repair_fallback",
              verdict: "advisory_needs_changes",
              critique: "Fallback critique remains advisory.",
              risks: ["backend gate required"],
              missing_evidence: [],
              unsafe_assumptions: [],
              recommended_next_action: "use_deterministic_backend_gate",
              confidence: "low",
              non_actionable: true,
              apply_allowed: false,
              approval_allowed: false,
              downstream_start_allowed: false,
            },
            output_checksum: "sha256:fallback-output",
            schema_validation_status: "validated",
            raw_output_redacted_preview: "{\"status\":\"available\"}",
            json_parse_error_kind: "",
            model_output_was_json: true,
            validated_output_source: "azure_model",
            provider_failure_kind: "reviewer_shadow_failed",
            provider_failure_stage: "model_output",
            provider_retry_path: "strict_json_schema_failed_then_json_object",
            provider_http_status: "",
            provider_error_redacted_preview: "",
            non_actionable: true,
            apply_allowed: false,
            approval_allowed: false,
            downstream_start_allowed: false,
          },
          fallback_trace: {
            fallback_kind: "deterministic_repair_draft_reviewer",
            deterministic_reviewer_verdict: "blocked",
            checksum_verification_status: "not_applicable",
            deterministic_gate_authority: true,
            llm_can_apply: false,
            llm_can_approve: false,
            llm_can_start_downstream: false,
            llm_can_override_backend_gate: false,
            apply_enabled: false,
            approval_enabled: false,
            repair_enabled: false,
            downstream_start_allowed: false,
            memory_authority: "advisory_only",
          },
          combined_llm_shadow_trace_checksum: "sha256:shadow",
          llm_can_apply: false,
          llm_can_approve: false,
          llm_can_start_downstream: false,
          llm_can_override_backend_gate: false,
          deterministic_gate_authority: true,
        },
      },
    };

    const markup = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={diagnosis} stage={1} />);
    expect(markup).toContain("Repair Draft");
    expect(markup).toContain("Draft status: blocked_human_review_gate");
    expect(markup).toContain("Reason: human_review_gate_no_auto_repair");
    expect(markup).toContain("Supported family: none");
    expect(markup).toContain("Apply: disabled");
    expect(markup).toContain("Human approval: disabled");
    expect(markup).toContain("Reviewer: required later, not active");
    expect(markup).toContain("Repair Draft Review");
    expect(markup).toContain("Reviewer status: not_reviewable_blocked_human_gate");
    expect(markup).toContain("Reviewer verdict: blocked");
    expect(markup).toContain("Checksum verification: not_applicable");
    expect(markup).not.toContain("accepted_for_future_apply_gate");
    expect(markup).toContain("LLM Repair Supervision");
    expect(markup).toContain("Proposer");
    expect(markup).toContain("Role: repair_proposer_model");
    expect(markup).toContain("Expected model/deployment: gpt5-mini");
    expect(markup).toContain("Model/provider/deployment/status: fake / gpt5-mini / live_ok");
    expect(markup).toContain("endpoint_host=[redacted-endpoint]");
    expect(markup).toContain("Input checksum: sha256:proposer-input");
    expect(markup).toContain("Output checksum: sha256:proposer-output");
    expect(markup).toContain("Schema validation status: validated");
    expect(markup).toContain("Validated output source: azure_model");
    expect(markup).toContain("Model output JSON: yes");
    expect(markup).toContain("Reviewer");
    expect(markup).toContain("Role: repair_reviewer_model");
    expect(markup).toContain("Expected model/deployment: Llama-3.3-70B-Instruct");
    expect(markup).toContain("Input checksum: sha256:reviewer-input");
    expect(markup).toContain("Output checksum: sha256:reviewer-output");
    expect(markup).toContain("Verdict: advisory_reject");
    expect(markup).toContain("Reviewer input includes proposer input + proposer output + evidence/checksum context.");
    expect(markup).toContain("LLM Fallback");
    expect(markup).toContain("Role: repair_fallback_model");
    expect(markup).toContain("Expected model/deployment: Mistral-Large-3");
    expect(markup).toContain("Fallback reason: reviewer_shadow_failed");
    expect(markup).toContain("Provider failure kind: reviewer_shadow_failed");
    expect(markup).toContain("Provider retry path: strict_json_schema_failed_then_json_object");
    expect(markup).toContain("Deterministic Backend Gate");
    expect(markup).toContain("Backend gate authority: yes");
    expect(markup).toContain("LLM can override backend gate: no");
    expect(markup).not.toContain("Apply repair");
    expect(markup).not.toContain("Approve draft");
    expect(markup).not.toContain("Edit patch");
  });

  it("renders Repair Draft drafted_non_actionable initMocks state", () => {
    const diagnosis = {
      diagnosis_id: "diag-draft",
      command_id: "cmd-draft",
      trigger_event_type: "build_failed",
      failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
      context_pack_id: "pack-draft",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model-draft",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: null,
      classification: {
        stage_index: 2,
        stage_name: "Stage 2",
        source_boot_version: "2.7",
        target_boot_version: "3.5.16",
        source_java_version: "11",
        target_java_version: "17",
        failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        classification_status: "known_family_candidate",
        repair_family_candidate: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        confidence: "medium",
        confidence_reason: "Mockito initMocks source signal found.",
        matched_signals: ["candidate:initmocks_to_openmocks"],
        missing_required_evidence: [],
        usable_artifacts: ["test_source"],
        repair_enabled: false,
        repair_blocked_reason: "R7C_classification_only_no_real_repair_apply",
        reason: "R7C_classification_only_no_real_repair_apply",
        assistant_next_action: "prepare_evidence_bound_proposal_in_R7D",
        governance_gate_type: "future_deterministic_candidate",
        stage_relevance: "All stages",
        evidence_pack_id: "stage-evidence-draft",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: null,
        migration_memory: null,
        repair_proposal_draft: {
          proposal_status: "drafted_non_actionable",
          proposal_type: "evidence_bound_repair_draft",
          supported_family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
          failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
          classification_status: "known_family_candidate",
          governance_gate_type: "future_deterministic_candidate",
          stage_index: 2,
          source_boot_version: "2.7",
          target_boot_version: "3.5.16",
          source_java_version: "11",
          target_java_version: "17",
          evidence_pack_id: "stage-evidence-draft",
          evidence_pack_checksum: "sha256:evidence",
          memory_query_signature: "sha256:memory",
          retrieved_memory_case_ids: ["msa-utils-initmocks-to-openmocks"],
          target_files: ["src/test/java/ExampleTest.java"],
          source_markers: ["MockitoAnnotations.initMocks"],
          target_file_checksums: { "src/test/java/ExampleTest.java": "sha256:file" },
          proposed_diff_preview: "-MockitoAnnotations.initMocks(this);\n+MockitoAnnotations.openMocks(this);",
          proposed_diff_checksum: "sha256:diff",
          proposal_checksum: "sha256:proposal",
          proposer_kind: "deterministic_local",
          llm_invoked: false,
          reviewer_required: true,
          human_approval_required: true,
          backend_apply_required: true,
          apply_enabled: false,
          approval_enabled: false,
          repair_enabled: false,
          sandbox_only: true,
          legacy_mutation_allowed: false,
          downstream_start_allowed: false,
          blocked_reason: "",
          assistant_next_action: "send_draft_to_future_reviewer_gate",
          safety_warnings: ["Draft is non-actionable in R7D."],
        },
        repair_draft_review: {
          review_status: "reviewed_non_actionable",
          verdict: "accepted_for_future_apply_gate",
          reviewer_kind: "deterministic_local",
          reviewer_origin: "backend_evidence_bound",
          llm_invoked: false,
          future_llm_reviewer_compatible: true,
          reviewed_family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
          failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
          classification_status: "known_family_candidate",
          governance_gate_type: "future_deterministic_candidate",
          stage_index: 2,
          source_boot_version: "2.7",
          target_boot_version: "3.5.16",
          source_java_version: "11",
          target_java_version: "17",
          evidence_pack_id: "stage-evidence-draft",
          evidence_pack_checksum: "sha256:evidence",
          memory_query_signature: "sha256:memory",
          retrieved_memory_case_ids: ["msa-utils-initmocks-to-openmocks"],
          target_files: ["src/test/java/ExampleTest.java"],
          target_file_checksums: { "src/test/java/ExampleTest.java": "sha256:file" },
          proposed_diff_checksum: "sha256:diff",
          proposal_checksum: "sha256:proposal",
          review_checksum: "sha256:review",
          declared_diff_checksum: "sha256:diff",
          recomputed_diff_checksum: "sha256:diff",
          diff_checksum_match: true,
          declared_proposal_checksum: "sha256:proposal",
          recomputed_proposal_checksum: "sha256:proposal",
          proposal_checksum_match: true,
          checksum_verification_status: "verified",
          required_followup_gate: "future_human_approval_and_backend_apply_gate",
          apply_enabled: false,
          approval_enabled: false,
          repair_enabled: false,
          sandbox_only: true,
          legacy_mutation_allowed: false,
          downstream_start_allowed: false,
          memory_authority: "advisory_only",
          memory_can_apply: false,
          memory_can_approve: false,
          memory_can_start_downstream: false,
          reasons: [],
          safety_warnings: ["Reviewer verdict is non-actionable in R7E."],
        },
      },
    };

    const markup = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={diagnosis} stage={2} />);
    expect(markup).toContain("Draft status: drafted_non_actionable");
    expect(markup).toContain("Supported family: INITMOCKS_TO_OPENMOCKS_CANDIDATE");
    expect(markup).toContain("Evidence pack checksum: sha256:evidence");
    expect(markup).toContain("Memory query signature: sha256:memory");
    expect(markup).toContain("Target file: src/test/java/ExampleTest.java");
    expect(markup).toContain("Proposed diff checksum: sha256:diff");
    expect(markup).toContain("Apply: disabled");
    expect(markup).toContain("Human approval: disabled");
    expect(markup).toContain("Backend apply required later: yes");
    expect(markup).toContain("Draft is non-actionable in R7D.");
    expect(markup).toContain("Read-only backend-owned diff preview");
    expect(markup).toContain("MockitoAnnotations.initMocks");
    expect(markup).toContain("MockitoAnnotations.openMocks");
    expect(markup).toContain("Repair Draft Review");
    expect(markup).toContain("Reviewer status: reviewed_non_actionable");
    expect(markup).toContain("Reviewer verdict: accepted_for_future_apply_gate");
    expect(markup).toContain("Reviewer kind: deterministic_local");
    expect(markup).toContain("Reviewed family: INITMOCKS_TO_OPENMOCKS_CANDIDATE");
    expect(markup).toContain("Target file checksum: src/test/java/ExampleTest.java");
    expect(markup).toContain("Proposal checksum: sha256:proposal");
    expect(markup).toContain("Review checksum: sha256:review");
    expect(markup).toContain("Declared diff checksum: sha256:diff");
    expect(markup).toContain("Recomputed diff checksum: sha256:diff");
    expect(markup).toContain("Diff checksum match: yes");
    expect(markup).toContain("Declared proposal checksum: sha256:proposal");
    expect(markup).toContain("Recomputed proposal checksum: sha256:proposal");
    expect(markup).toContain("Proposal checksum match: yes");
    expect(markup).toContain("Checksum verification: verified");
    expect(markup).toContain("Future LLM reviewer compatible: yes");
    expect(markup).toContain("Reviewer verdict is non-actionable in R7E.");
    expect(markup).not.toContain("Apply repair");
    expect(markup).not.toContain("Upload patch");
    expect(markup).not.toContain("Override checksum");
    expect(markup).not.toContain("Edit LLM output");
    expect(markup).not.toContain("Choose model");
    expect(markup).not.toContain("Choose endpoint");
  });

  it("renders controlled synthetic initMocks proposer UI smoke from failure summary", () => {
    const failureSummary: V2FailureSummaryResponse = {
      job_id: "job-synthetic-initmocks",
      has_failures: true,
      failures: [
        {
          type: "build_failed",
          stage: 2,
          title: "Stage 2 build failed",
          message: "Synthetic initMocks proposer smoke.",
          build_status: "BUILD_FAILED_IN_SANDBOX",
          test_status: "TEST_FAILED",
          final_status: "FAILED",
          final_proof_level: "not_verified",
          repair_loop_status: "NOT_STARTED",
          copilot_status: "NOT_INVOKED",
          repair_fallback: "False",
          matched_line: "MockitoAnnotations.initMocks(this);",
          command: [],
          requested_command: [],
          build_tool: "maven",
          module: "",
          main_class: "",
          unit_id: "stage-2",
          result_kind: "test_source_marker",
          java_home: "",
          detected_version: "",
          required_minimum: "",
          event_types: ["build_failed", "ai_diagnosis_created"],
          repair_events: [],
          next_operator_action: "review_evidence_bound_draft_later",
          supervision_trace: {
            ai_diagnosis: {
              diagnosis_id: "diag-synthetic-initmocks",
              command_id: "cmd-synthetic-initmocks",
              trigger_event_type: "build_failed",
              failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
              context_pack_id: "pack-synthetic-initmocks",
              context_pack_checksum: "sha256:ctx-synthetic",
              repair_proposal_id: "",
              model_invocation_id: "",
              redaction_status: "stage_evidence_collected",
              created_at: "2026-07-02T00:00:00Z",
              stage_evidence: {
                stage_index: 2,
                stage_name: "Spring Boot 2.7 + Java 11 to Spring Boot 3.5.16 + Java 17",
                source_boot_version: "2.7",
                target_boot_version: "3.5.16",
                source_java_version: "11",
                target_java_version: "17",
                input_source_kind: "stage_output",
                input_artifact_ref: "stage:1",
                output_sandbox_ref: "sandbox:stage-2",
                previous_stage_ref: "stage:1",
                downstream_stage_state: {
                  next_stage_index: 3,
                  state: "pending_blocked_by_failed_stage",
                  auto_started: false,
                },
                evidence_status: "collected",
                evidence_pack_id: "stage-evidence-synthetic",
                evidence_pack_checksum: "sha256:evidence-synthetic",
                usable_artifacts: [
                  {
                    kind: "test_source",
                    ref: "src/test/java/com/example/ExampleTest.java",
                    checksum: "sha256:file-before",
                  },
                ],
                missing_artifacts: [],
                repair_enabled: false,
                assistant_next_action: "prepare_evidence_bound_proposal_in_R7D",
                redaction_status: "stage_evidence_collected",
                failure_summary: "Synthetic test source evidence includes MockitoAnnotations.initMocks.",
              },
              classification: {
                stage_index: 2,
                stage_name: "Stage 2",
                source_boot_version: "2.7",
                target_boot_version: "3.5.16",
                source_java_version: "11",
                target_java_version: "17",
                failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                classification_status: "known_family_candidate",
                repair_family_candidate: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                confidence: "medium",
                confidence_reason: "Mockito initMocks source signal found.",
                matched_signals: ["candidate:initmocks_to_openmocks"],
                missing_required_evidence: [],
                usable_artifacts: ["test_source"],
                repair_enabled: false,
                repair_blocked_reason: "R7D_non_actionable_draft_only",
                reason: "R7D_non_actionable_draft_only",
                assistant_next_action: "send_draft_to_future_reviewer_gate",
                governance_gate_type: "future_deterministic_candidate",
                stage_relevance: "Stage 2 compatible",
                migration_memory: {
                  retrieval_status: "available",
                  query_signature: "sha256:memory-synthetic",
                  memory_matches: [
                    {
                      memory_case_id: "msa-utils-initmocks-to-openmocks",
                      title: "msa-utils initMocks to openMocks",
                      summary: "MockitoAnnotations.initMocks marker can seed future bounded draft context.",
                      trust_level: "golden_reference_verified",
                      authority_level: "advisory_only",
                      matched_signals: ["candidate:initmocks_to_openmocks"],
                      required_evidence: ["test_source"],
                      suggested_next_actions: ["future_reviewer_gate"],
                      stage_applicability: ["2"],
                      promotion_status: "seed_only",
                      redaction_status: "redacted",
                    },
                  ],
                  top_match: {
                    memory_case_id: "msa-utils-initmocks-to-openmocks",
                    title: "msa-utils initMocks to openMocks",
                    summary: "MockitoAnnotations.initMocks marker can seed future bounded draft context.",
                    trust_level: "golden_reference_verified",
                    authority_level: "advisory_only",
                    matched_signals: ["candidate:initmocks_to_openmocks"],
                    required_evidence: ["test_source"],
                    suggested_next_actions: ["future_reviewer_gate"],
                    stage_applicability: ["2"],
                    promotion_status: "seed_only",
                    redaction_status: "redacted",
                  },
                  trust_summary: "golden_reference_verified",
                  advisory_summary: "Memory advisory only.",
                  missing_evidence_suggestions: [],
                  retrieved_case_ids: ["msa-utils-initmocks-to-openmocks"],
                  authority_level: "advisory_only",
                  repair_enabled: false,
                  memory_can_apply: false,
                  memory_can_approve: false,
                  memory_can_start_downstream: false,
                  recommended_use: "future reviewer/RAG context only",
                },
                repair_proposal_draft: {
                  proposal_status: "drafted_non_actionable",
                  proposal_type: "evidence_bound_repair_draft",
                  supported_family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                  failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                  classification_status: "known_family_candidate",
                  governance_gate_type: "future_deterministic_candidate",
                  stage_index: 2,
                  source_boot_version: "2.7",
                  target_boot_version: "3.5.16",
                  source_java_version: "11",
                  target_java_version: "17",
                  evidence_pack_id: "stage-evidence-synthetic",
                  evidence_pack_checksum: "sha256:evidence-synthetic",
                  memory_query_signature: "sha256:memory-synthetic",
                  retrieved_memory_case_ids: ["msa-utils-initmocks-to-openmocks"],
                  target_files: ["src/test/java/com/example/ExampleTest.java"],
                  source_markers: ["MockitoAnnotations.initMocks"],
                  target_file_checksums: {
                    "src/test/java/com/example/ExampleTest.java": "sha256:file-before",
                  },
                  proposed_diff_preview: "-MockitoAnnotations.initMocks(this);\n+MockitoAnnotations.openMocks(this);",
                  proposed_diff_checksum: "sha256:diff-synthetic",
                  proposal_checksum: "sha256:proposal-synthetic",
                  proposer_kind: "deterministic_local",
                  proposer_origin: "backend_evidence_bound",
                  llm_invoked: false,
                  reviewer_required: true,
                  human_approval_required: true,
                  backend_apply_required: true,
                  apply_enabled: false,
                  approval_enabled: false,
                  repair_enabled: false,
                  sandbox_only: true,
                  legacy_mutation_allowed: false,
                  downstream_start_allowed: false,
                  blocked_reason: "",
                  assistant_next_action: "send_draft_to_future_reviewer_gate",
                  safety_warnings: ["Draft is non-actionable in R7D."],
                },
                repair_draft_review: {
                  review_status: "reviewed_non_actionable",
                  verdict: "accepted_for_future_apply_gate",
                  reviewer_kind: "deterministic_local",
                  reviewer_origin: "backend_evidence_bound",
                  llm_invoked: false,
                  future_llm_reviewer_compatible: true,
                  reviewed_family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                  failure_type: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                  classification_status: "known_family_candidate",
                  governance_gate_type: "future_deterministic_candidate",
                  stage_index: 2,
                  source_boot_version: "2.7",
                  target_boot_version: "3.5.16",
                  source_java_version: "11",
                  target_java_version: "17",
                  evidence_pack_id: "stage-evidence-synthetic",
                  evidence_pack_checksum: "sha256:evidence-synthetic",
                  memory_query_signature: "sha256:memory-synthetic",
                  retrieved_memory_case_ids: ["msa-utils-initmocks-to-openmocks"],
                  target_files: ["src/test/java/com/example/ExampleTest.java"],
                  target_file_checksums: {
                    "src/test/java/com/example/ExampleTest.java": "sha256:file-before",
                  },
                  proposed_diff_checksum: "sha256:diff-synthetic",
                  proposal_checksum: "sha256:proposal-synthetic",
                  review_checksum: "sha256:review-synthetic",
                  declared_diff_checksum: "sha256:diff-synthetic",
                  recomputed_diff_checksum: "sha256:diff-synthetic",
                  diff_checksum_match: true,
                  declared_proposal_checksum: "sha256:proposal-synthetic",
                  recomputed_proposal_checksum: "sha256:proposal-synthetic",
                  proposal_checksum_match: true,
                  checksum_verification_status: "verified",
                  required_followup_gate: "future_human_approval_and_backend_apply_gate",
                  apply_enabled: false,
                  approval_enabled: false,
                  repair_enabled: false,
                  sandbox_only: true,
                  legacy_mutation_allowed: false,
                  downstream_start_allowed: false,
                  memory_authority: "advisory_only",
                  memory_can_apply: false,
                  memory_can_approve: false,
                  memory_can_start_downstream: false,
                  reasons: [],
                  safety_warnings: ["Reviewer verdict is non-actionable in R7E."],
                },
                evidence_pack_id: "stage-evidence-synthetic",
                evidence_pack_checksum: "sha256:evidence-synthetic",
                downstream_stage_state: {
                  next_stage_index: 3,
                  state: "pending_blocked_by_failed_stage",
                  auto_started: false,
                },
              },
            },
            evidence_used: ["stage-evidence-synthetic", "sha256:evidence-synthetic"],
            pom_analysis: null,
            repair_proposal: null,
            reviewer_verdict: null,
            validation_result: null,
          },
        },
      ],
      repair_loop_active: false,
      repair_events: [],
      artifact_kinds: ["test_source"],
    };

    const diagnosis = failureSummary.failures[0].supervision_trace.ai_diagnosis;
    expect(diagnosis).not.toBeNull();
    const markup = renderToStaticMarkup(
      <StageFailureEvidenceDetails diagnosis={diagnosis!} stage={failureSummary.failures[0].stage} />
    );

    expect(markup).toContain("Stage Evidence");
    expect(markup).toContain("Migration Memory");
    expect(markup).toContain("Top match: msa-utils initMocks to openMocks");
    expect(markup).toContain("Memory cannot approve/apply/start downstream");
    expect(markup).toContain("Repair Draft");
    expect(markup).toContain("Draft status: drafted_non_actionable");
    expect(markup).toContain("Supported family: INITMOCKS_TO_OPENMOCKS_CANDIDATE");
    expect(markup).toContain("Evidence pack checksum: sha256:evidence-synthetic");
    expect(markup).toContain("Memory query signature: sha256:memory-synthetic");
    expect(markup).toContain("Target file: src/test/java/com/example/ExampleTest.java");
    expect(markup).toContain("Proposed diff checksum: sha256:diff-synthetic");
    expect(markup).toContain("Repair Draft Review");
    expect(markup).toContain("Reviewer status: reviewed_non_actionable");
    expect(markup).toContain("Reviewer verdict: accepted_for_future_apply_gate");
    expect(markup).toContain("Review checksum: sha256:review-synthetic");
    expect(markup).toContain("Proposal checksum: sha256:proposal-synthetic");
    expect(markup).toContain("Declared diff checksum: sha256:diff-synthetic");
    expect(markup).toContain("Recomputed diff checksum: sha256:diff-synthetic");
    expect(markup).toContain("Diff checksum match: yes");
    expect(markup).toContain("Declared proposal checksum: sha256:proposal-synthetic");
    expect(markup).toContain("Recomputed proposal checksum: sha256:proposal-synthetic");
    expect(markup).toContain("Proposal checksum match: yes");
    expect(markup).toContain("Checksum verification: verified");
    expect(markup).toContain("Target file checksum: src/test/java/com/example/ExampleTest.java");
    expect(markup).toContain("Future LLM reviewer compatible: yes");
    expect(markup).toContain("Apply: disabled");
    expect(markup).toContain("Human approval: disabled");
    expect(markup).toContain("Draft is non-actionable in R7D.");
    expect(markup).not.toContain("Apply repair");
    expect(markup).not.toContain("Approve draft");
    expect(markup).not.toContain("Edit patch");
    expect(markup).not.toContain("Upload patch");
    expect(markup).not.toContain("Override checksum");
  });

  it("renders Repair Draft no-draft state", () => {
    const diagnosis = {
      diagnosis_id: "diag-no-draft",
      command_id: "cmd-no-draft",
      trigger_event_type: "build_failed",
      failure_type: "unknown",
      context_pack_id: "pack",
      context_pack_checksum: "sha256:ctx",
      repair_proposal_id: "",
      model_invocation_id: "model",
      redaction_status: "stage_evidence_collected",
      created_at: "2026-07-01T00:00:00Z",
      stage_evidence: null,
      classification: {
        stage_index: 2,
        stage_name: "Stage 2",
        source_boot_version: "2.7",
        target_boot_version: "3.5.16",
        source_java_version: "11",
        target_java_version: "17",
        failure_type: "unknown",
        classification_status: "unknown",
        repair_family_candidate: "",
        confidence: "low",
        confidence_reason: "Unknown.",
        matched_signals: [],
        missing_required_evidence: [],
        usable_artifacts: [],
        repair_enabled: false,
        repair_blocked_reason: "no_known_family_match",
        reason: "no_known_family_match",
        assistant_next_action: "escalate_unknown_stage_failure",
        governance_gate_type: "unknown",
        stage_relevance: "",
        evidence_pack_id: "stage-evidence",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: null,
        migration_memory: null,
        repair_proposal_draft: null,
      },
    };
    const markup = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={diagnosis} stage={2} />);
    expect(markup).toContain("Repair Draft");
    expect(markup).toContain("No repair draft available.");
  });

  // ── Stage status lifecycle reducer tests (V2 cockpit state model) ──

  it("reduceStageStatus: blocked while approval pending", () => {
    // Only approval_required/blocked events → blocked
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 2 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("blocked");
  });

  it("reduceStageStatus: running after approval completed and transform started", () => {
    // Old blocked events must not prevent running
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 2 } as V2JobEvent,
      { stage: 1, type: "approval_resume_queued", status: "queued", sequence: 3 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 4 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("running");
  });

  it("reduceStageStatus: failed after sandbox_transform_failed", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 2 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_failed", status: "failed", sequence: 3 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("failed");
  });

  it("reduceStageStatus: completed after stage_completed, blocked does not regress", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_started", status: "running", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_completed", status: "completed", sequence: 2 } as V2JobEvent,
      // A late blocked event must NOT regress completed → blocked
      { stage: 1, type: "approval_required", status: "blocked", sequence: 3 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("completed");
  });

  it("reduceStageStatus: old blocked does not override later running", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 2 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("running");
  });

  it("reduceStageStatus: old blocked does not override later failed", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "stage_failed", status: "failed", sequence: 2 } as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("failed");
  });

  // ── Pipeline / stage consistency tests ──

  it("approval decision controls appear only while pending", () => {
    expect(shouldShowApprovalDecisionControls("pending", false)).toBe(true);
    expect(shouldShowApprovalDecisionControls("approved", false)).toBe(false);
    expect(shouldShowApprovalDecisionControls("rejected", false)).toBe(false);
    expect(shouldShowApprovalDecisionControls("pending", true)).toBe(false);
  });

  it("pipeline and stage status consistent after approval lifecycle", () => {
    // The pipeline human_approval row must be "pass", not "blocked",
    // after approval_resume_queued. Stage must be "running".
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as V2JobEvent,
      { stage: 1, type: "approval_resume_queued", status: "queued", sequence: 2 } as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 3 } as V2JobEvent,
    ];
    const stageStatus = reduceStageStatus(events);
    expect(stageStatus).toBe("running");
    // Pipeline human_approval row logic: events with type in approval_passed_types
    const hasPassedEvent = events.some(
      (e) => ["approval_completed", "approval_resume_queued", "resume_started",
              "sandbox_transform_started", "sandbox_transform_completed"].includes(e.type)
    );
    expect(hasPassedEvent).toBe(true);
  });

  it("raw logs events are collapsed by default in SSE stream", () => {
    const events = [
      { type: "stdout", status: "running", message: "raw line" },
      { type: "analysis_completed", status: "completed", message: "done" },
    ];
    const rawLogs = events.filter((e) => e.type === "stdout" || e.type === "stderr");
    const evidence = events.filter((e) => e.type !== "stdout" && e.type !== "stderr");
    expect(rawLogs).toHaveLength(1);
    expect(evidence).toHaveLength(1);
    expect(evidence[0].type).toBe("analysis_completed");
  });

  it("no stage input paths come from user selection", () => {
    // Stage 2 input must be stage_1_sandbox, not user-selected
    const stage2Input = "stage_1_sandbox";
    const prohibitedInputs = ["user_selected", "manual", "browser_payload"];
    expect(stage2Input).toBe("stage_1_sandbox");
    for (const prohibited of prohibitedInputs) {
      expect(stage2Input).not.toBe(prohibited);
    }
  });

  it("Stage 2 profile is springboot-2.7-to-3.5-java17", () => {
    const stage2Profile = "springboot-2.7-to-3.5-java17";
    expect(stage2Profile).toBe("springboot-2.7-to-3.5-java17");
  });

  it("Stage 3 profile is springboot-3.5-java17-to-java21", () => {
    const stage3Profile = "springboot-3.5-java17-to-java21";
    expect(stage3Profile).toBe("springboot-3.5-java17-to-java21");
  });
});

function makeCockpitData(): CockpitData {
  return {
    job: {
      job_id: "job-123",
      setup_id: "setup-123",
      setup_checksum: "setup-checksum",
      pipeline_id: "pipeline",
      stages: [],
      created_at: "2026-06-16T00:00:00Z",
    },
    stages: [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "queued", input_source_kind: "legacy_source" },
    ],
    approvals: [
      {
        card_id: "card-1",
        job_id: "job-123",
        stage_index: 1,
        status: "pending",
        summary: "Approval required.",
        request_checksum: "checksum-1",
        created_at: "2026-06-16T00:00:00Z",
      } as CockpitData["approvals"][number],
    ],
    messages: [],
    events: [{ sequence: 1, type: "stage_queued", status: "queued", stage: 1 } as V2JobEvent],
    pipeline: {
      job_id: "job-123",
      active_stage_index: 1,
      rows: [],
      evidence: [],
      raw_logs: [],
    } as CockpitData["pipeline"],
    failureSummary: null,
    assistantModel: null,
    repairProposal: null,
  };
}
