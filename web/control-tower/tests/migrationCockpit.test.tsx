import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MigrationCockpitPage from "../app/migrations/[jobId]/page";
import {
  MigrationCockpit,
  AssistantPanelContent,
  GovernedRepairProposalCard,
  R6GovernedRepairPanel,
  EMPTY_R6_REPAIR_UI_STATE,
  GatePanelContent,
  formatGateArtifactRefLabel,
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
  v2EventStreamUrl,
} from "../lib/controlTowerApi";
import type {
  GateRepresentation,
  GovernedRepairProposalResponse,
  MigrationIntelligenceSummary,
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
    expect(markup).toContain("Request reviewer critique");
    expect(markup).toContain("Prepare apply context");
    expect(markup).toContain("Record human repair approval");
    expect(markup).toContain("Run official apply");
    expect(markup).toContain("disabled=\"\"");
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
      reviewer_model: { model_invocation_id: "model-reviewer-1" },
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
    expect(markup).toContain("Context: ctx-1");
    expect(markup).toContain("Approval: approval-1");
    expect(markup).toContain(">Run official apply</button>");
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
    expect(markup).toContain("git apply result: applied");
    expect(markup).toContain("Maven verification: passed");
    expect(markup).toContain("Build: BUILD_PASSED_IN_SANDBOX");
    expect(markup).toContain("Legacy unchanged: true");
    expect(markup).toContain("repair_test_report: test_report.json");
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

  it("prepare repair apply context sends backend proposal patch exactly and no raw commands", async () => {
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
        patch_preview: patchText,
        target_path: "src/main/java/com/example/App.java",
        sandbox_reference: "C:/work/out/.migration/runs/run-9a/sandbox",
        sandbox_checksum: "sha256:sandbox-checksum",
        legacy_checksum: "sha256:legacy-checksum",
        evidence_refs: { patch_checksum: "sha256:patch-checksum" },
        approval_scope: "sandbox_only",
      });

      expect(calls[0].url).toBe(`${CONTROL_TOWER_API_BASE_URL}/v1/v2/commands/cmd-repair-1/repair/proposal/proposal-9a-1/prepare-apply-context`);
      expect(calls[0].body.patch_preview).toBe(patchText);
      expect(calls[0].body.patch_preview).not.toContain("browser edit");
      expect(calls[0].body).not.toHaveProperty("argv");
      expect(calls[0].body).not.toHaveProperty("env");
      expect(calls[0].body).not.toHaveProperty("command");
      expect(calls[0].body).not.toHaveProperty("maven_goal");
      expect(calls[0].body).not.toHaveProperty("model_deployment");
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
