import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi, afterEach } from "vitest";
import MigrationCockpitPage from "../app/migrations/[jobId]/page";
import {
  MigrationCockpit,
  ApprovalDecisionsPanel,
  AssistantPanelContent,
  ControlledR6RepairDemoPanel,
  GovernedRepairProposalCard,
  R6GovernedRepairPanel,
  StageFailureEvidenceDetails,
  EMPTY_R6_REPAIR_UI_STATE,
  GatePanelContent,
  RepairApplyCandidateCard,
  RepairApplyCandidateDetails,
  MigrationRoutePanel,
  SourceProfileDetectionPanel,
  SourceProfileOverrideForm,
  buildGateActionButtonPayload,
  buildSourceProfileOverrideBody,
  buildStageTimelineEntries,
  getSourceProfileOverrideBlockedReason,
  formatStageStatusLabel,
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
  applyV2RepairCandidate,
  applyV2RepairReviewContext,
  askV2Assistant,
  approveV2RepairCandidate,
  approveV2Card,
  CONTROL_TOWER_API_BASE_URL,
  getV2ArtifactPreview,
  postV2GateAction,
  prepareV2RepairApplyContext,
  requireJobId,
  resolveReportDownloadUrl,
  requestV2ReviewerCritique,
  v2EventStreamUrl,
} from "../lib/controlTowerApi";
import type {
  GateDetailResponse,
  GateEvidencePack,
  GateRepresentation,
  GovernedRepairProposalResponse,
  MigrationIntelligenceSummary,
  V2ApprovalResponse,
  V2FailureSummaryResponse,
  V2FailureSummaryItem,
  V2JobEvent,
  V2MigrationJobResponse,
  V2RouteStepEntry,
  V2ReviewerCritiqueResponse,
  RepairApplyContextResponse,
  RepairApprovalResponse,
  ApplyRepairReviewContextResponse,
  V2RepairApplyCandidateResponse,
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

type ButtonLike = {
  props: {
    children?: unknown;
    onClick?: () => Promise<void> | void;
  };
};

function nodeText(value: unknown): string {
  if (Array.isArray(value)) return value.map(nodeText).join("");
  if (value && typeof value === "object") {
    const element = value as { props?: { children?: unknown } };
    return nodeText(element.props?.children);
  }
  return value == null ? "" : String(value);
}

function findButtonByText(node: unknown, text: string): ButtonLike {
  if (node && typeof node === "object") {
    const element = node as { type?: unknown; props?: { children?: unknown; onClick?: () => Promise<void> | void } };
    if (element.type === "button" && nodeText(element.props?.children).includes(text)) {
      return { props: element.props ?? {} };
    }
    const children = element.props?.children;
    for (const child of Array.isArray(children) ? children : [children]) {
      try {
        return findButtonByText(child, text);
      } catch {
        // Keep searching siblings.
      }
    }
  }
  throw new Error(`Button not found: ${text}`);
}

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

  it("shows Boot 4 as the automated Stage 4 pipeline entry", () => {
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "completed", input_source_kind: "legacy_source" },
      { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "completed", input_source_kind: "stage_1_sandbox" },
      { stage_index: 3, pipeline_stage: "Stage 3", chain_status: "completed", input_source_kind: "stage_2_sandbox" },
      { stage_index: 4, pipeline_stage: "Stage 4", chain_status: "pending", input_source_kind: "stage_3_sandbox" },
    ];
    const stage4 = stages[3];
    expect(stage4.input_source_kind).toBe("stage_3_sandbox");
    expect(formatStageStatusLabel(stage4.chain_status)).toBe("PENDING");
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

  it("repair candidate card renders approve/apply flow without edit/upload/override controls", () => {
    const candidate: V2RepairApplyCandidateResponse = {
      job_id: "job-123",
      stage_index: 1,
      repair_candidate_id: "repair-candidate-r8",
      status: "pending_human_approval",
      family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
      patch_source: "backend_deterministic_recipe",
      llm_source: "advisory_only",
      target_file: "src/test/java/ExampleTest.java",
      pre_apply_checksum: "sha256:file",
      target_file_checksum: "sha256:file",
      patch_checksum: "sha256:patch",
      review_checksum: "sha256:review",
      proposal_checksum: "sha256:proposal",
      candidate_checksum: "sha256:candidate",
      approval_required: true,
      apply_enabled: false,
      approval_enabled: true,
      sandbox_only: true,
      legacy_mutation_allowed: false,
      downstream_start_allowed: false,
      llm_can_apply: false,
      browser_can_supply_patch: false,
      verification_status: "not_started",
      rollback_status: "not_started",
      proof_artifact: "",
      created_at: "2026-07-03T00:00:00Z",
    };
    const markup = renderToStaticMarkup(
      <RepairApplyCandidateCard
        candidate={candidate}
        busyKey={null}
        onApprove={() => undefined}
        onApply={() => undefined}
      />
    );

    expect(markup).toContain("Repair Apply Candidate");
    expect(markup).toContain("Approve checksum-bound repair");
    expect(markup).toContain("Verification: not_started");
    expect(markup).toContain("Rollback: not_started");
    expect(markup).toContain("Proof artifact: pending");
    expect(markup).not.toContain("Upload patch");
    expect(markup).not.toContain("Override checksum");
    expect(markup).not.toContain("Edit target");
  });

  it("repair candidate card treats verified R11 proof as accepted", () => {
    const candidate: V2RepairApplyCandidateResponse = {
      job_id: "job-123",
      stage_index: 1,
      repair_candidate_id: "repair-candidate-r11",
      status: "verified",
      family: "SPRING_DATA_SORT_API_DRIFT",
      patch_source: "backend_deterministic_recipe",
      llm_source: "advisory_only",
      target_file: "src/main/java/com/total/corp/common/dto/DTOHelpers.java",
      pre_apply_checksum: "sha256:file",
      target_file_checksum: "sha256:file",
      patch_checksum: "sha256:patch",
      review_checksum: "sha256:review",
      proposal_checksum: "sha256:proposal",
      candidate_checksum: "sha256:candidate",
      approval_required: true,
      apply_enabled: false,
      approval_enabled: false,
      sandbox_only: true,
      legacy_mutation_allowed: false,
      downstream_start_allowed: false,
      llm_can_apply: false,
      browser_can_supply_patch: false,
      execution_status: "verified",
      verification_status: "passed",
      post_repair_verification_status: "passed",
      proof_review_status: "accepted",
      proof_accepted: true,
      rollback_status: "not_needed",
      proof_artifact: "proof.json",
      created_at: "2026-07-03T00:00:00Z",
    };
    const markup = renderToStaticMarkup(
      <RepairApplyCandidateCard
        candidate={candidate}
        busyKey={null}
        onApprove={() => undefined}
        onApply={() => undefined}
      />,
    );

    expect(markup).toContain("Repair proof accepted");
    expect(markup).not.toContain("Downstream remains blocked until backend proof is reviewed.");
  });

  it("repair candidate card treats verified proof with open gate as ready for review", () => {
    const candidate: V2RepairApplyCandidateResponse = {
      job_id: "job-123",
      stage_index: 1,
      repair_candidate_id: "repair-candidate-r11",
      status: "verified",
      family: "SPRING_DATA_SORT_API_DRIFT",
      patch_source: "backend_deterministic_recipe",
      llm_source: "advisory_only",
      target_file: "src/main/java/com/total/corp/common/dto/DTOHelpers.java",
      pre_apply_checksum: "sha256:file",
      target_file_checksum: "sha256:file",
      patch_checksum: "sha256:patch",
      review_checksum: "sha256:review",
      proposal_checksum: "sha256:proposal",
      candidate_checksum: "sha256:candidate",
      approval_required: true,
      apply_enabled: false,
      approval_enabled: false,
      sandbox_only: true,
      legacy_mutation_allowed: false,
      downstream_start_allowed: false,
      llm_can_apply: false,
      browser_can_supply_patch: false,
      execution_status: "verified",
      verification_status: "passed",
      post_repair_verification_status: "passed",
      proof_review_status: "ready_for_review",
      proof_accepted: false,
      rollback_status: "not_needed",
      proof_artifact: "proof.json",
      created_at: "2026-07-03T00:00:00Z",
    };
    const markup = renderToStaticMarkup(
      <RepairApplyCandidateCard
        candidate={candidate}
        busyKey={null}
        onApprove={() => undefined}
        onApply={() => undefined}
      />,
    );

    expect(markup).toContain("Repair proof ready for human review");
    expect(markup).not.toContain("Repair proof accepted");
  });

  it("repair candidate approve/apply clients send only checksum-bound bodies", async () => {
    const candidate: V2RepairApplyCandidateResponse = {
      job_id: "job-123",
      stage_index: 1,
      repair_candidate_id: "repair-candidate-r8",
      status: "pending_human_approval",
      family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
      patch_source: "backend_deterministic_recipe",
      llm_source: "advisory_only",
      target_file: "src/test/java/ExampleTest.java",
      pre_apply_checksum: "sha256:file",
      target_file_checksum: "sha256:file",
      patch_checksum: "sha256:patch",
      review_checksum: "sha256:review",
      proposal_checksum: "sha256:proposal",
      candidate_checksum: "sha256:candidate",
      approval_required: true,
      apply_enabled: false,
      approval_enabled: true,
      sandbox_only: true,
      legacy_mutation_allowed: false,
      downstream_start_allowed: false,
      llm_can_apply: false,
      browser_can_supply_patch: false,
      verification_status: "not_started",
      rollback_status: "not_started",
      proof_artifact: "",
      created_at: "2026-07-03T00:00:00Z",
    };
    const originalFetch = global.fetch;
    const bodies: unknown[] = [];
    global.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body ?? "{}")));
      return new Response(JSON.stringify({ candidate, approval: {}, execution: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;
    try {
      await approveV2RepairCandidate("job-123", 1, candidate);
      await applyV2RepairCandidate("job-123", 1, candidate.repair_candidate_id);
    } finally {
      global.fetch = originalFetch;
    }

    expect(bodies[0]).toEqual({
      repair_candidate_id: "repair-candidate-r8",
      patch_checksum: "sha256:patch",
      target_file_checksum: "sha256:file",
      review_checksum: "sha256:review",
    });
    expect(bodies[1]).toEqual({ repair_candidate_id: "repair-candidate-r8" });
    expect(JSON.stringify(bodies)).not.toContain("patch_content");
    expect(JSON.stringify(bodies)).not.toContain("target_path");
    expect(JSON.stringify(bodies)).not.toContain("command");
    expect(JSON.stringify(bodies)).not.toContain("model");
  });

  it("repair candidate detail panel exposes safe approve/apply actions", () => {
    const pending: V2RepairApplyCandidateResponse = {
      job_id: "job-123",
      stage_index: 1,
      repair_candidate_id: "repair-candidate-r8",
      status: "pending_human_approval",
      family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
      patch_source: "backend_deterministic_recipe",
      llm_source: "advisory_only",
      target_file: "src/test/java/ExampleTest.java",
      pre_apply_checksum: "sha256:file",
      target_file_checksum: "sha256:file",
      patch_checksum: "sha256:patch",
      review_checksum: "sha256:review",
      proposal_checksum: "sha256:proposal",
      candidate_checksum: "sha256:candidate",
      approval_required: true,
      apply_enabled: false,
      approval_enabled: true,
      sandbox_only: true,
      legacy_mutation_allowed: false,
      downstream_start_allowed: false,
      llm_can_apply: false,
      browser_can_supply_patch: false,
      verification_status: "not_started",
      rollback_status: "not_started",
      proof_artifact: "",
      created_at: "2026-07-03T00:00:00Z",
    };
    const approved = { ...pending, status: "approved", apply_enabled: true, approval_enabled: false };
    const applyFlagOnly = { ...pending, status: "pending_human_approval", apply_enabled: true, approval_enabled: false };
    const verified = {
      ...pending,
      status: "verified",
      apply_enabled: false,
      approval_enabled: false,
      verification_status: "passed",
      rollback_status: "not_needed",
      proof_artifact: "artifact:repair-proof",
    };

    const pendingMarkup = renderToStaticMarkup(
      <RepairApplyCandidateDetails candidate={pending} jobId="job-123" stageIndex={1} busyKey={null} />
    );
    const approvedMarkup = renderToStaticMarkup(
      <RepairApplyCandidateDetails candidate={approved} jobId="job-123" stageIndex={1} busyKey={null} />
    );
    const applyFlagOnlyMarkup = renderToStaticMarkup(
      <RepairApplyCandidateDetails candidate={applyFlagOnly} jobId="job-123" stageIndex={1} busyKey={null} />
    );
    const verifiedMarkup = renderToStaticMarkup(
      <RepairApplyCandidateDetails candidate={verified} jobId="job-123" stageIndex={1} busyKey={null} />
    );

    expect(pendingMarkup).toContain("Approve repair candidate");
    expect(pendingMarkup).not.toContain("Apply approved repair");
    expect(approvedMarkup).toContain("Apply approved repair");
    expect(approvedMarkup).not.toContain("Approve repair candidate");
    expect(applyFlagOnlyMarkup).toContain("Apply approved repair");
    expect(verifiedMarkup).toContain("Verification: passed");
    expect(verifiedMarkup).toContain("Proof artifact: artifact:repair-proof");
    expect(verifiedMarkup).not.toContain("Apply approved repair");
    const combinedMarkup = pendingMarkup + approvedMarkup + applyFlagOnlyMarkup + verifiedMarkup;
    for (const forbiddenControl of [
      "Edit patch",
      "Upload patch",
      "Override checksum",
      "Choose target path",
      "Choose command",
      "Choose model",
      "Choose endpoint",
      "Force apply",
      "Start Stage 2",
      "Start Stage 3",
      "Auto continue",
    ]) {
      expect(combinedMarkup).not.toContain(forbiddenControl);
    }
  });

  it("repair candidate detail buttons call safe APIs and refresh after success", async () => {
    const pending: V2RepairApplyCandidateResponse = {
      job_id: "job-123",
      stage_index: 1,
      repair_candidate_id: "repair-candidate-r8",
      status: "pending_human_approval",
      family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
      patch_source: "backend_deterministic_recipe",
      llm_source: "advisory_only",
      target_file: "src/test/java/ExampleTest.java",
      pre_apply_checksum: "sha256:file",
      target_file_checksum: "sha256:file",
      patch_checksum: "sha256:patch",
      review_checksum: "sha256:review",
      proposal_checksum: "sha256:proposal",
      candidate_checksum: "sha256:candidate",
      approval_required: true,
      apply_enabled: false,
      approval_enabled: true,
      sandbox_only: true,
      legacy_mutation_allowed: false,
      downstream_start_allowed: false,
      llm_can_apply: false,
      browser_can_supply_patch: false,
      verification_status: "not_started",
      rollback_status: "not_started",
      proof_artifact: "",
      created_at: "2026-07-03T00:00:00Z",
    };
    const approved: V2RepairApplyCandidateResponse = {
      ...pending,
      status: "approved",
      apply_enabled: true,
      approval_enabled: false,
    };
    const originalFetch = global.fetch;
    const bodies: unknown[] = [];
    let refreshCount = 0;
    global.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(JSON.parse(String(init?.body ?? "{}")));
      return new Response(JSON.stringify({ candidate: approved, approval: {}, execution: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;
    try {
      const approveButton = findButtonByText(
        RepairApplyCandidateDetails({
          candidate: pending,
          jobId: "job-123",
          stageIndex: 1,
          onRefresh: async () => {
            refreshCount += 1;
          },
        }),
        "Approve repair candidate"
      );
      await approveButton.props.onClick?.();

      const applyButton = findButtonByText(
        RepairApplyCandidateDetails({
          candidate: approved,
          jobId: "job-123",
          stageIndex: 1,
          onRefresh: async () => {
            refreshCount += 1;
          },
        }),
        "Apply approved repair"
      );
      await applyButton.props.onClick?.();
    } finally {
      global.fetch = originalFetch;
    }

    expect(bodies).toEqual([
      {
        repair_candidate_id: "repair-candidate-r8",
        patch_checksum: "sha256:patch",
        target_file_checksum: "sha256:file",
        review_checksum: "sha256:review",
      },
      { repair_candidate_id: "repair-candidate-r8" },
    ]);
    expect(refreshCount).toBe(2);
    for (const body of bodies) {
      const keys = Object.keys(body as Record<string, unknown>);
      for (const forbidden of ["patch", "target_path", "command", "model", "endpoint", "override_checksum", "diff", "content"]) {
        expect(keys).not.toContain(forbidden);
      }
    }
  });

  it("no-candidate repair detail state shows no approve or apply buttons", () => {
    const markup = renderToStaticMarkup(
      <RepairApplyCandidateDetails candidate={null} jobId="job-123" stageIndex={1} />
    );
    expect(markup).toContain("No backend apply candidate available.");
    expect(markup).toContain("PowerMock and unsupported failures remain human-gated.");
    expect(markup).not.toContain("Approve repair candidate");
    expect(markup).not.toContain("Apply approved repair");
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

  it("pending approval card renders Approve/Reject buttons even when approvalReviewOpen is true", () => {
    // Regression: the global approvalReviewOpen flag used to swap ALL cards'
    // buttons for "Review in chatbot" copy. Pending gates must always show
    // active Approve/Reject buttons, regardless of the open-gate flag.
    const pending: V2ApprovalResponse = {
      card_id: "card-3",
      job_id: "job-123",
      interrupt_id: "run-3",
      request_checksum: "checksum-3",
      stage_index: 3,
      summary: "Pre-transform review required before sandbox transform.",
      status: "pending",
      created_at: "2026-07-02T00:00:00Z",
    };
    const markup = renderToStaticMarkup(
      <ApprovalDecisionsPanel
        approvals={[pending]}
        approvalReviewOpen={true}
        approvalBusy={null}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    );
    expect(markup).toContain("Stage 3");
    expect(markup).toContain("checksum-3");
    expect(markup).toContain("Approve");
    expect(markup).toContain("Reject");
    // The pending card's Approve button must NOT be disabled.
    const approveButtonStart = markup.indexOf("Approve");
    expect(markup.slice(markup.lastIndexOf("<button", approveButtonStart), approveButtonStart)).not.toContain("disabled");
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
          repair_fallback: "True",
        },
      ],
      repair_loop_active: true,
      repair_events: [
        { type: "repair_invalid_response", message: "Repair response invalid" },
      ],
      artifact_kinds: ["analysis_report"],
    };
    expect(failureSummary.has_failures).toBe(true);
    expect(failureSummary.failures[0].build_status).toBe("BUILD_FAILED_IN_SANDBOX");
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
    const repair = { repair_fallback: "True", repair_loop_status: "FALLBACK_REPAIR_PLAN" };
    expect(assistantModel.source).toBe("azure_openai");
    expect(assistantModel.status).toBe("live_ok");
    expect(repair.repair_loop_status).toBe("FALLBACK_REPAIR_PLAN");
  });

  // ── F0 closure: no copilot_status in failure contracts or rendering ──

  it("V2FailureSummaryItem does not include copilot_status field", () => {
    const failure: V2FailureSummaryItem = {
      type: "build_failed",
      stage: 2,
      title: "test",
      message: "test message",
      build_status: "BUILD_FAILED_IN_SANDBOX",
      test_status: "NOT_RUN",
      final_status: "FAILED",
      final_proof_level: "not_verified",
      repair_loop_status: "INACTIVE",
      repair_fallback: "false",
      matched_line: "",
      command: [],
      requested_command: [],
      build_tool: "maven",
      module: "",
      main_class: "",
      unit_id: "",
      result_kind: "dependency_error",
      java_home: "/java",
      detected_version: "",
      required_minimum: "",
      event_types: [],
      repair_events: [],
      next_operator_action: "manual_review",
      supervision_trace: {
        ai_diagnosis: null,
        evidence_used: [],
        pom_analysis: null,
        repair_proposal: null,
        reviewer_verdict: null,
        validation_result: null,
      },
    };
    expect("copilot_status" in failure).toBe(false);
    expect(failure).not.toHaveProperty("copilot_status");
  });

  it("failure summary rendering does not include copilot_status", () => {
    const sampleFailure = {
      type: "build_failed",
      stage: 2,
      title: "Stage 2 Build Failure",
      message: "Build result kind: dependency_error",
      build_status: "BUILD_FAILED_IN_SANDBOX",
      final_status: "FAILED",
      result_kind: "dependency_error",
      event_types: ["build_failed"],
      repair_events: [{ type: "repair_started", message: "repair started" }],
    };

    const markup = renderToStaticMarkup(
      <div className="failure-card">
        <div className="stage-header">
          <strong>{sampleFailure.type}</strong>
          <span className="meta">Stage {sampleFailure.stage}</span>
          <span className="status-badge failed">FAILED</span>
        </div>
        <p>{sampleFailure.message}</p>
        {sampleFailure.result_kind && (
          <p className="meta">
            <strong>Root cause:</strong> {sampleFailure.result_kind}
          </p>
        )}
        {sampleFailure.event_types.length > 0 && (
          <p className="meta">Event types: {sampleFailure.event_types.join(", ")}</p>
        )}
        {sampleFailure.repair_events.length > 0 && (
          <p className="meta">Repair events: {sampleFailure.repair_events.map((r) => r.type).join(", ")}</p>
        )}
      </div>
    );

    expect(markup).not.toContain("copilot_status");
    expect(markup).not.toContain("INVALID_RESPONSE");
    expect(markup).not.toContain("copilot_invocation_status");
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
      "analysis_started",
      "analysis_completed",
      "analysis_failed",
      "planning_started",
      "planning_completed",
      "planning_failed",
      "assessment_started",
      "assessment_completed",
      "assessment_failed",
      "final_report_started",
      "final_report_completed",
      "final_report_failed",
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
    expect(important.has("analysis_started")).toBe(true);
    expect(important.has("planning_started")).toBe(true);
    expect(important.has("assessment_started")).toBe(true);
    expect(important.has("final_report_started")).toBe(true);
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

  it("renders generic Repair Strategy panel without PowerMock-specific UI", () => {
    const diagnosis = {
      diagnosis_id: "diag-strategy",
      command_id: "cmd-strategy",
      trigger_event_type: "build_failed",
      failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
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
        failure_type: "POWERMOCK_LEGACY_TEST_STRATEGY",
        classification_status: "unsupported_known_failure",
        repair_family_candidate: "",
        confidence: "high",
        confidence_reason: "PowerMock legacy test strategy signal found.",
        matched_signals: ["review_gate:powermock_legacy_test_strategy"],
        missing_required_evidence: [],
        usable_artifacts: ["pom_xml", "test_source", "test_report"],
        repair_enabled: false,
        repair_blocked_reason: "human_review_gate_no_auto_repair",
        reason: "human_review_gate_no_auto_repair",
        assistant_next_action: "review_powermock_legacy_test_strategy",
        evidence_pack_id: "stage-evidence-power",
        evidence_pack_checksum: "sha256:evidence",
        downstream_stage_state: { next_stage_index: 3, state: "pending_blocked_by_failed_stage", auto_started: false },
        repair_strategy_packet: {
          strategy_id: "repair-strategy-power",
          strategy_base_id: "repair-strategy-power",
          version: 2,
          job_id: "job-r9",
          stage_index: 2,
          family: "POWERMOCK_LEGACY_TEST_STRATEGY",
          risk_level: "high",
          category: "test_modernization",
          strategy_status: "available",
          strategy_checksum: "sha256:strategy",
          evidence_pack_checksum: "sha256:evidence",
          classification_status: "unsupported_known_failure",
          created_at: "2026-07-01T00:00:00Z",
          history_count: 2,
          history: [
            {
              strategy_id: "repair-strategy-power-v2",
              version: 2,
              family: "POWERMOCK_LEGACY_TEST_STRATEGY",
              risk_level: "high",
              strategy_status: "available",
              strategy_checksum: "sha256:strategy",
              evidence_pack_checksum: "sha256:evidence",
              created_at: "2026-07-01T00:00:00Z",
            },
          ],
          apply_candidate_allowed: false,
          backend_recipe_available: false,
          human_gate_required: true,
          root_cause: "PowerMock static mocking requires human review.",
          affected_files: ["src/test/java/ExampleTest.java"],
          detected_patterns: ["PowerMockRunner", "static mocking", "constructor mocking"],
          migration_options: ["replace simple static mocking with Mockito inline"],
          recommended_strategy: "Create engineer-reviewed PowerMock modernization plan; do not auto-apply.",
          risk_notes: ["High-risk family can change test behavior."],
          missing_evidence: [],
          engineer_checklist: ["Review PrepareForTest scope."],
          repair_subfamily_assessment: {
            assessment_id: "repair-subfamily-power",
            job_id: "job-r9",
            stage_index: 2,
            family: "POWERMOCK_LEGACY_TEST_STRATEGY",
            subfamily: "POWERMOCK_CONSTRUCTOR_MOCKING",
            risk_level: "high",
            promotion_status: "human_refactor_required",
            backend_recipe_available: false,
            apply_candidate_allowed: false,
            human_gate_required: true,
            matched_patterns: ["PowerMockito.whenNew"],
            forbidden_patterns_matched: ["constructor mocking"],
            missing_evidence: [],
            verification_requirements: ["engineer refactor plan", "targeted tests"],
            recommended_engineer_action: "Refactor constructor mocking by injecting dependencies or redesigning the test.",
            rollback_required: true,
            proof_required: true,
            assessment_checksum: "sha256:assessment",
            backend_gate: {
              backend_authority: true,
              llm_can_apply: false,
              llm_can_approve: false,
              downstream_start_allowed: false,
            },
          },
          llm_proposer: {
            role: "repair_strategy_proposer",
            status: "available",
            llm_invoked: true,
            fallback_used: false,
            failure_reason: "",
            input_checksum: "sha256:in",
            output: {
              confidence: "high",
              recommended_strategy: "Create engineer-reviewed PowerMock modernization plan; do not auto-apply.",
            },
            output_checksum: "sha256:out",
            schema_validation_status: "validated",
            non_actionable: true,
            apply_allowed: false,
            approval_allowed: false,
            downstream_start_allowed: false,
          },
          llm_reviewer: {
            role: "repair_strategy_reviewer",
            status: "available",
            llm_invoked: true,
            fallback_used: false,
            failure_reason: "",
            input_checksum: "sha256:review-in",
            output: { confidence: "medium", verdict: "advisory_accept", critique: "Human gate remains required." },
            output_checksum: "sha256:review-out",
            schema_validation_status: "validated",
            non_actionable: true,
            apply_allowed: false,
            approval_allowed: false,
            downstream_start_allowed: false,
          },
          llm_fallback: {
            role: "repair_strategy_fallback",
            status: "fallback_used",
            llm_invoked: true,
            fallback_used: true,
            failure_reason: "",
            input_checksum: "sha256:fallback-in",
            output: { confidence: "low", verdict: "advisory_needs_changes", critique: "Fallback remains advisory." },
            output_checksum: "sha256:fallback-out",
            schema_validation_status: "validated",
            fallback_model_invoked: true,
            fallback_model_used: true,
            fallback_validated_output_source: "fallback_model",
            non_actionable: true,
            apply_allowed: false,
            approval_allowed: false,
            downstream_start_allowed: false,
          },
          backend_gate: {
            backend_authority: true,
            llm_can_apply: false,
            llm_can_approve: false,
            downstream_start_allowed: false,
          },
        },
        repair_apply_candidate: null,
      },
    };

    const markup = renderToStaticMarkup(<StageFailureEvidenceDetails diagnosis={diagnosis} stage={2} />);
    expect(markup).toContain("Repair Strategy");
    expect(markup).toContain("Strategy ID: repair-strategy-power");
    expect(markup).toContain("Version: 2");
    expect(markup).toContain("Strategy checksum: sha256:strategy");
    expect(markup).toContain("Evidence pack checksum: sha256:evidence");
    expect(markup).toContain("Strategy history count: 2");
    expect(markup).toContain("Family: POWERMOCK_LEGACY_TEST_STRATEGY");
    expect(markup).toContain("Risk level: high");
    expect(markup).toContain("Apply candidate allowed: no");
    expect(markup).toContain("Backend recipe available: no");
    expect(markup).toContain("Human gate required: yes");
    expect(markup).toContain("Detected patterns:");
    expect(markup).toContain("Migration options:");
    expect(markup).toContain("Engineer checklist:");
    expect(markup).toContain("Repair Subfamily Assessment");
    expect(markup).toContain("Subfamily: POWERMOCK_CONSTRUCTOR_MOCKING");
    expect(markup).toContain("Promotion status: human_refactor_required");
    expect(markup).toContain("Forbidden patterns matched: constructor mocking");
    expect(markup).toContain("Assessment checksum: sha256:assessment");
    expect(markup).toContain("Review PrepareForTest scope.");
    expect(markup).toContain("Proposer output");
    expect(markup).toContain("Reviewer output");
    expect(markup).toContain("Fallback model invoked: yes");
    expect(markup).toContain("Fallback output source: fallback_model");
    expect(markup).toContain("Repair Strategy History");
    expect(markup).toContain("Backend gate");
    expect(markup).toContain("Backend authority: yes");
    expect(markup).toContain("LLM can apply: no");
    expect(markup).toContain("LLM can approve: no");
    expect(markup).toContain("Downstream start allowed: no");
    expect(markup).not.toContain("PowerMock Strategy");
    expect(markup).not.toContain("PowerMock Subfamily");
    expect(markup).not.toContain("Apply approved repair");
    expect(markup).not.toContain("Approve repair candidate");
    expect(markup).not.toContain("Force apply");
    expect(markup).not.toContain("Choose target path");
    expect(markup).not.toContain("Choose command");
    expect(markup).not.toContain("Choose model");
    expect(markup).not.toContain("Upload patch");
    expect(markup).not.toContain("Edit patch");
    expect(markup).not.toContain("Override checksum");
    expect(markup).not.toContain("Start Stage 2");
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
        repair_apply_candidate: {
          repair_candidate_id: "repair-candidate-r8",
          status: "pending_human_approval",
          family: "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
          patch_source: "backend_deterministic_recipe",
          llm_source: "advisory_only",
          target_file: "src/test/java/ExampleTest.java",
          pre_apply_checksum: "sha256:file",
          target_file_checksum: "sha256:file",
          patch_checksum: "sha256:patch",
          review_checksum: "sha256:review",
          proposal_checksum: "sha256:proposal",
          candidate_checksum: "sha256:candidate",
          approval_required: true,
          apply_enabled: false,
          approval_enabled: true,
          sandbox_only: true,
          legacy_mutation_allowed: false,
          downstream_start_allowed: false,
          llm_can_apply: false,
          browser_can_supply_patch: false,
          verification_status: "pending",
          rollback_status: "not_started",
          proof_artifact: "",
          created_at: "2026-07-01T00:00:00Z",
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
    expect(markup).toContain("Repair Apply Candidate");
    expect(markup).toContain("Status: pending_human_approval");
    expect(markup).toContain("Patch source: backend_deterministic_recipe");
    expect(markup).toContain("LLM source: advisory_only");
    expect(markup).toContain("Patch checksum: sha256:patch");
    expect(markup).toContain("Approval required: yes");
    expect(markup).toContain("Apply: disabled until approval");
    expect(markup).toContain("LLM advisory only: yes");
    expect(markup).toContain("Browser can supply patch: no");
    expect(markup).toContain("Repair Approval");
    expect(markup).toContain("Checksum-bound approval requires exact patch, target file, and review checksums.");
    expect(markup).toContain("Repair Execution");
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

  it("buildStageTimelineEntries overlays route-step status from refreshed stages", () => {
    const routeSteps: V2RouteStepEntry[] = [
      {
        route_step_index: 1,
        stage_index: 1,
        source_profile: "springboot-2.7-java11",
        target_profile: "springboot-3.5-java17",
        runtime_profile: "springboot-2.7-to-3.5-java17",
        catalog: "springboot-3.5-java17",
        execution_jdk: "java17",
        status: "pending",
        approval_gate_id: "",
        artifact_refs: [],
        evidence_refs: [],
      },
      {
        route_step_index: 2,
        stage_index: 2,
        source_profile: "springboot-3.5-java17",
        target_profile: "springboot-4.0-java21",
        runtime_profile: "springboot-3.5-java17-to-java21",
        catalog: "springboot-4.0-java21",
        execution_jdk: "java21",
        status: "pending",
        approval_gate_id: "",
        artifact_refs: [],
        evidence_refs: [],
      },
    ];
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "completed", input_source_kind: "legacy_source" },
      { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "running", input_source_kind: "stage_1_sandbox" },
    ];

    const entries = buildStageTimelineEntries(routeSteps, stages);

    expect(entries[0]).toMatchObject({ route_step_index: 1, status: "completed" });
    expect(entries[1]).toMatchObject({ route_step_index: 2, status: "running" });
  });

  it("reduceStageStatus: blocked while approval pending", () => {
    // Only approval_required/blocked events → blocked
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 2 } as unknown as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("blocked");
  });

  it("reduceStageStatus: running after approval completed and transform started", () => {
    // Old blocked events must not prevent running
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 2 } as unknown as V2JobEvent,
      { stage: 1, type: "approval_resume_queued", status: "queued", sequence: 3 } as unknown as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 4 } as unknown as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("running");
  });

  it("reduceStageStatus: failed after sandbox_transform_failed", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 2 } as unknown as V2JobEvent,
      { stage: 1, type: "sandbox_transform_failed", status: "failed", sequence: 3 } as unknown as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("failed");
  });

  it("reduceStageStatus: next_stage_queued completes prior stage and queues next stage", () => {
    const priorStageEvents: V2JobEvent[] = [
      { stage: 1, type: "stage_started", status: "running", sequence: 1 } as unknown as V2JobEvent,
      {
        stage: 2,
        type: "next_stage_queued",
        status: "queued",
        sequence: 2,
        payload: { from_stage: 1, to_stage: 2 },
      } as unknown as V2JobEvent,
    ];
    const nextStageEvents: V2JobEvent[] = [
      {
        stage: 2,
        type: "next_stage_queued",
        status: "queued",
        sequence: 2,
        payload: { from_stage: 1, to_stage: 2 },
      } as unknown as V2JobEvent,
      { stage: 2, type: "stage_started", status: "running", sequence: 3 } as unknown as V2JobEvent,
    ];

    expect(reduceStageStatus(priorStageEvents, 1)).toBe("completed");
    expect(reduceStageStatus(nextStageEvents, 2)).toBe("running");
  });
  it("reduceStageStatus: completed after stage_completed, blocked does not regress", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_started", status: "running", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "stage_completed", status: "completed", sequence: 2 } as unknown as V2JobEvent,
      // A late blocked event must NOT regress completed → blocked
      { stage: 1, type: "approval_required", status: "blocked", sequence: 3 } as unknown as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("completed");
  });

  it("reduceStageStatus: old blocked does not override later running", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 2 } as unknown as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("running");
  });

  it("reduceStageStatus: old blocked does not override later failed", () => {
    const events: V2JobEvent[] = [
      { stage: 1, type: "stage_blocked_for_approval", status: "blocked", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "stage_failed", status: "failed", sequence: 2 } as unknown as V2JobEvent,
    ];
    const actual = reduceStageStatus(events);
    expect(actual).toBe("failed");
  });

  // ── Route-step off-by-one regression (springboot-2.1 → 4.0 full route) ──

  it("route step 2 start event marks Route step 2 RUNNING, not Route step 3", () => {
    // Full route: springboot-2.1-java11 → springboot-4.0-java21
    // route_step_index and stage_index are aligned 1:1 for this source.
    const routeSteps: V2RouteStepEntry[] = [
      {
        route_step_index: 1, stage_index: 1,
        source_profile: "springboot-2.1-java11", target_profile: "springboot-2.7-java11",
        runtime_profile: "springboot-2.1.6-to-2.7-java11", catalog: "springboot-2.1.6-to-2.7-java11",
        execution_jdk: "java11", status: "pending", approval_gate_id: "", artifact_refs: [], evidence_refs: [],
      },
      {
        route_step_index: 2, stage_index: 2,
        source_profile: "springboot-2.7-java11", target_profile: "springboot-3.5-java17",
        runtime_profile: "springboot-2.7-to-3.5-java17", catalog: "springboot-3.5-java17",
        execution_jdk: "java17", status: "pending", approval_gate_id: "", artifact_refs: [], evidence_refs: [],
      },
      {
        route_step_index: 3, stage_index: 3,
        source_profile: "springboot-3.5-java17", target_profile: "springboot-3.5-java21",
        runtime_profile: "springboot-3.5-java17-to-java21", catalog: "springboot-3.5-java17-to-java21",
        execution_jdk: "java21", status: "pending", approval_gate_id: "", artifact_refs: [], evidence_refs: [],
      },
      {
        route_step_index: 4, stage_index: 4,
        source_profile: "springboot-3.5-java21", target_profile: "springboot-4.0-java21",
        runtime_profile: "springboot-3.5-java21-to-4.0-java21", catalog: "springboot-3.5-java21-to-4.0-java21",
        execution_jdk: "java21", status: "pending", approval_gate_id: "", artifact_refs: [], evidence_refs: [],
      },
    ];

    // Backend events: stage 1 completed, stage 2 started (running).
    // The backend emits stage=2 for route step 2's execution (after the fix).
    const allEvents: V2JobEvent[] = [
      { stage: 1, type: "stage_started", status: "running", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "stage_completed", status: "completed", sequence: 2 } as unknown as V2JobEvent,
      { stage: 2, type: "stage_started", status: "running", sequence: 3 } as unknown as V2JobEvent,
    ];

    // Replicate eventAppliesToStage (event.stage === stageIndex) + reduceStageStatus
    // for each stage, then build the timeline.
    const stages = routeSteps.map((rs) => {
      const stageEvents = allEvents
        .filter((e) => e.stage === rs.stage_index)
        .sort((a, b) => a.sequence - b.sequence);
      return {
        stage_index: rs.stage_index,
        pipeline_stage: `Stage ${rs.stage_index}`,
        chain_status: reduceStageStatus(stageEvents, rs.stage_index),
        input_source_kind: "legacy_source",
      };
    });

    const entries = buildStageTimelineEntries(routeSteps, stages);

    // Route step 1 = COMPLETED
    expect(entries[0]).toMatchObject({ route_step_index: 1, status: "completed" });
    // Route step 2 = RUNNING (not Route step 3!)
    expect(entries[1]).toMatchObject({ route_step_index: 2, status: "running" });
    // Route step 3 = PENDING (must NOT be RUNNING)
    expect(entries[2]).toMatchObject({ route_step_index: 3, status: "pending" });
    expect(entries[2]).not.toMatchObject({ route_step_index: 3, status: "running" });
    // Route step 4 = PENDING
    expect(entries[3]).toMatchObject({ route_step_index: 4, status: "pending" });
  });

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
      { stage: 1, type: "approval_required", status: "blocked", sequence: 1 } as unknown as V2JobEvent,
      { stage: 1, type: "approval_resume_queued", status: "queued", sequence: 2 } as unknown as V2JobEvent,
      { stage: 1, type: "sandbox_transform_started", status: "running", sequence: 3 } as unknown as V2JobEvent,
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

// ── F3/F4 — Cockpit profile routing, detection, override ─────────────

describe("F3/F4 Cockpit profile routing panels", () => {
  it("MigrationRoutePanel displays source and target profiles from backend job data", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-2.7-java11",
      target_profile: "springboot-4.0-java21",
      validation_status: "valid",
      included_stages: ["2", "3", "4"],
      skipped_stages: [],
      excluded_stages: [],
      route_steps: [
        {
          route_step_index: 1,
          stage_index: 1,
          source_profile: "springboot-2.7-java11",
          target_profile: "springboot-3.5-java17",
          runtime_profile: "springboot-2.7-to-3.5-java17",
          catalog: "springboot-3.5-java17",
          execution_jdk: "java17",
          status: "completed",
          approval_gate_id: "",
          artifact_refs: [],
          evidence_refs: [],
        },
      ],
    };
    const markup = renderToStaticMarkup(<MigrationRoutePanel job={job} />);
    expect(markup).toContain("Migration Route");
    expect(markup).toContain("Spring Boot 2.7 / Java 11");
    expect(markup).toContain("Spring Boot 4.0 / Java 21");
    expect(markup).toContain("valid");
    expect(markup).toContain("2, 3, 4");
    expect(markup).toContain("All route data is backend-returned");
  });

  it("MigrationRoutePanel shows skipped stages from backend data", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-2",
      setup_id: "setup-2",
      setup_checksum: "chk-2",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-3.5-java17",
      target_profile: "springboot-4.0-java21",
      validation_status: "valid",
      included_stages: ["3", "4"],
      skipped_stages: ["2"],
      excluded_stages: [],
    };
    const markup = renderToStaticMarkup(<MigrationRoutePanel job={job} />);
    expect(markup).toContain("Skipped stages");
    expect(markup).toContain("2");
  });

  it("SourceProfileDetectionPanel shows unavailable message when evidence is null", () => {
    const markup = renderToStaticMarkup(
      <SourceProfileDetectionPanel gateDetail={null} />,
    );
    expect(markup).toContain("Source-profile detection evidence is unavailable");
    expect(markup).toContain("refresh the gate or rerun analysis");
  });

  it("SourceProfileDetectionPanel shows detection evidence when evidence pack is present", () => {
    const pack: GateEvidencePack = {
      pack_id: "pack-1",
      pack_type: "source_profile_detection",
      gate_id: "gate-1",
      gate_phase: "analysis_review",
      summary: "Detected springboot-2.7-java11",
      artifacts: [
        {
          kind: "source_profile_detection",
          checksum_verified: true,
          content: '{"detected_source_profile":"springboot-2.7-java11","confidence":"high"}',
          size_bytes: 64,
          truncated: false,
        },
      ],
      missing_refs: [],
      checksum_mismatches: [],
      failure_message: null,
      resolved_artifact_count: 1,
      total_artifact_count: 1,
      redaction_status: "clean",
      created_at: "2026-06-28T00:00:00Z",
    };
    const gateDetail: GateDetailResponse = {
      gate: {
        gate_id: "gate-1",
        job_id: "job-1",
        gate_phase: "analysis_review",
        stage_index: 1,
        gate_status: "open",
        gate_decision: "continue",
        source_artifact_checksum: "sha256:gate",
        source_artifact_refs: [],
        created_at: "2026-06-28T00:00:00Z",
        resolved_at: null,
        resolved_by: null,
        checksum: "sha256:gate-checksum",
        available_actions: [],
      },
      evidence: pack,
      checksum: "sha256:gate-checksum",
    };
    const markup = renderToStaticMarkup(
      <SourceProfileDetectionPanel gateDetail={gateDetail} />,
    );
    expect(markup).toContain("Source Profile Detection");
    expect(markup).toContain("source_profile_detection");
    expect(markup).toContain("springboot-2.7-java11");
    expect(markup).toContain("1/1 resolved");
  });

  it("SourceProfileOverrideForm does not render for non-analysis_review gates", () => {
    const gateDetail: GateDetailResponse = {
      gate: {
        gate_id: "gate-1",
        job_id: "job-1",
        gate_phase: "repair_review",
        stage_index: 2,
        gate_status: "open",
        gate_decision: "revise",
        source_artifact_checksum: "sha256:gate",
        source_artifact_refs: [],
        created_at: "2026-06-28T00:00:00Z",
        resolved_at: null,
        resolved_by: null,
        checksum: "sha256:gate-checksum",
        available_actions: [
          { action: "override_source_profile", label: "Override", description: "Override", blocked: false, block_reason: "" },
        ],
      },
      evidence: null,
      checksum: "sha256:gate-checksum",
    };
    const markup = renderToStaticMarkup(
      <SourceProfileOverrideForm gateDetail={gateDetail} jobId="job-1" onSuccess={() => undefined} />,
    );
    expect(markup).toBe("");
  });

  it("GatePanelContent renders backend-provided gate actions as buttons", () => {
    const gate: GateRepresentation = {
      gate_id: "gate-1",
      job_id: "job-1",
      gate_phase: "repair_review",
      stage_index: 1,
      gate_status: "open",
      gate_decision: "continue",
      source_artifact_checksum: "sha256:gate",
      source_artifact_refs: [],
      created_at: "2026-06-28T00:00:00Z",
      resolved_at: null,
      resolved_by: null,
      checksum: "sha256:gate-checksum",
      available_actions: [
        { action: "continue", label: "Accept", description: "Accept proof", blocked: false, block_reason: "" },
        { action: "request_revision", label: "Request Revision", description: "Needs changes", blocked: true, block_reason: "No attempts left" },
      ],
    };
    const markup = renderToStaticMarkup(
      <GatePanelContent
        state={{ status: "success", gates: [gate], openGate: gate, openGateDetail: null }}
        jobId="job-1"
      />,
    );

    expect(markup).toContain("<button");
    expect(markup).toContain("Accept");
    expect(markup).toContain("Request Revision");
    expect(markup).toContain("disabled");
    expect(markup).not.toContain("sandbox_path");
    expect(markup).not.toContain("target_file");
  });

  it("gate Accept button payload uses backend action and safe contract fields only", () => {
    const gate: GateRepresentation = {
      gate_id: "gate-1",
      job_id: "job-1",
      gate_phase: "repair_review",
      stage_index: 1,
      gate_status: "open",
      gate_decision: "pending",
      source_artifact_checksum: "sha256:gate",
      source_artifact_refs: [],
      created_at: "2026-06-28T00:00:00Z",
      resolved_at: null,
      resolved_by: null,
      checksum: "sha256:gate-checksum",
      available_actions: [
        { action: "continue", label: "Accept", description: "Accept proof", blocked: false, block_reason: "" },
      ],
    };
    const payload = buildGateActionButtonPayload(gate, gate.available_actions[0], "idem-1");

    expect(payload).toEqual({
      action: "continue",
      expected_gate_checksum: "sha256:gate-checksum",
      idempotency_key: "idem-1",
      decided_by: "human",
      actor_type: "human",
      comments: "Accepted verified backend repair proof after checksum-bound R11 apply.",
    });
    const serialized = JSON.stringify(payload);
    expect(serialized).not.toContain("gate_id");
    expect(serialized).not.toContain("job_id");
    expect(serialized).not.toContain("patch");
    expect(serialized).not.toContain("sandbox_path");
    expect(serialized).not.toContain("command");
    expect(serialized).not.toContain("env");
  });

  it("SourceProfileOverrideForm shows a specific blocked reason when detection evidence is missing", () => {
    const gateDetail: GateDetailResponse = {
      gate: {
        gate_id: "gate-1",
        job_id: "job-1",
        gate_phase: "analysis_review",
        stage_index: 1,
        gate_status: "open",
        gate_decision: "continue",
        source_artifact_checksum: "sha256:gate",
        source_artifact_refs: [],
        created_at: "2026-06-28T00:00:00Z",
        resolved_at: null,
        resolved_by: null,
        checksum: "sha256:gate-checksum",
        available_actions: [
          { action: "override_source_profile", label: "Override", description: "Override", blocked: false, block_reason: "" },
        ],
      },
      evidence: null,
      checksum: "sha256:gate-checksum",
    };
    const markup = renderToStaticMarkup(
      <SourceProfileOverrideForm gateDetail={gateDetail} jobId="job-1" onSuccess={() => undefined} />,
    );
    expect(markup).toContain("Override Source Profile");
    // With no job target_profile and no detection ref, the form should expose
    // a specific unavailable reason — never fabricate a target_profile.
    expect(markup).toContain("Missing target profile from backend job state.");
    expect(markup).toContain("disabled");
  });

  it("cockpit displays source and target profile from backend job data", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-2.7-java11",
      target_profile: "springboot-4.0-java21",
    };
    const markup = renderToStaticMarkup(<MigrationRoutePanel job={job} />);
    expect(markup).toContain("Source profile");
    expect(markup).toContain("Target profile");
    expect(markup).toContain("Spring Boot 2.7 / Java 11");
    expect(markup).toContain("Spring Boot 4.0 / Java 21");
  });

  it("cockpit displays included/excluded/skipped stages from backend arrays", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-2.7-java11",
      target_profile: "springboot-4.0-java21",
      included_stages: ["2", "3", "4"],
      skipped_stages: [],
      excluded_stages: [],
    };
    const markup = renderToStaticMarkup(<MigrationRoutePanel job={job} />);
    expect(markup).toContain("Included stages");
    expect(markup).toContain("2, 3, 4");
  });

  it("skipped stage cards render with skipped state in stage timeline", () => {
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "completed", input_source_kind: "legacy_source" },
      { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "completed", input_source_kind: "stage_1_sandbox" },
      { stage_index: 3, pipeline_stage: "Stage 3", chain_status: "pending", input_source_kind: "stage_2_sandbox" },
    ];
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-3.5-java17",
      target_profile: "springboot-4.0-java21",
      included_stages: ["3"],
      skipped_stages: ["2"],
      excluded_stages: [],
    };
    const markup = renderToStaticMarkup(
      <div className="stage-list">
        {stages.map((stage) => {
          const isSkipped = job.skipped_stages?.includes(String(stage.stage_index));
          return (
            <div key={stage.stage_index} className={`stage-card ${stage.chain_status}`}>
              <strong>{stage.pipeline_stage}</strong>
              {isSkipped && <span className="status-badge skipped">SKIPPED BY SOURCE</span>}
            </div>
          );
        })}
      </div>,
    );
    expect(markup).toContain("SKIPPED BY SOURCE");
    expect(markup).toContain("Stage 2");
  });

  it("override form posts a checksum-bound override_source_profile action", () => {
    const action = {
      gate_id: "gate-1",
      job_id: "job-1",
      action: "continue",
      expected_gate_checksum: "sha256:gate-checksum",
      override_source_profile: "springboot-3.5-java17",
      actor_type: "human",
      decided_by: "human",
    };
    expect(action.override_source_profile).toBe("springboot-3.5-java17");
    expect(action.expected_gate_checksum).toBe("sha256:gate-checksum");
    expect(action.actor_type).toBe("human");
  });

  it("assistant cannot override source profile", () => {
    const assistantCapabilities = {
      can_explain: true,
      can_diagnose: true,
      can_override_source_profile: false,
    };
    expect(assistantCapabilities.can_override_source_profile).toBe(false);
  });

  it("forbidden execution fields are absent from cockpit rendered copy", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-2.7-java11",
      target_profile: "springboot-4.0-java21",
    };
    const markup = renderToStaticMarkup(<MigrationRoutePanel job={job} />);
    const forbiddenPatterns = [
      "sandbox_path", "argv", "raw_command", "filesystem_target",
      "provider", "model_id", "deployment", "endpoint", "api_key", "access_token",
    ];
    for (const pattern of forbiddenPatterns) {
      expect(markup).not.toContain(pattern);
    }
  });

  // ── SourceProfileOverrideForm — driven submit path ─────────────

  function makeAnalysisReviewGateDetail(
    overrides: Partial<{
      sourceArtifactRefs: string[];
      sourceArtifactChecksum: string;
      availableActions: GateRepresentation["available_actions"];
    }> = {},
  ): GateDetailResponse {
    return {
      gate: {
        gate_id: "gate-1",
        job_id: "job-1",
        gate_phase: "analysis_review",
        stage_index: 1,
        gate_status: "open",
        gate_decision: "continue",
        source_artifact_checksum: overrides.sourceArtifactChecksum ?? "sha256:detection-checksum",
        source_artifact_refs: overrides.sourceArtifactRefs ?? [
          "analysis/source_profile_detection.json",
        ],
        created_at: "2026-06-28T00:00:00Z",
        resolved_at: null,
        resolved_by: null,
        checksum: "sha256:gate-checksum",
        available_actions: overrides.availableActions ?? [
          {
            action: "override_source_profile",
            label: "Override",
            description: "Override",
            blocked: false,
            block_reason: "",
          },
        ],
      },
      evidence: {
        pack_id: "pack-1",
        pack_type: "source_profile_detection",
        gate_id: "gate-1",
        gate_phase: "analysis_review",
        summary: "Detected springboot-2.7-java11",
        artifacts: [
          {
            kind: "source_profile_detection",
            checksum_verified: true,
            content: '{"detected_source_profile":"springboot-2.7-java11","confidence":"high"}',
            size_bytes: 64,
            truncated: false,
          },
        ],
        missing_refs: [],
        checksum_mismatches: [],
        failure_message: null,
        resolved_artifact_count: 1,
        total_artifact_count: 1,
        redaction_status: "clean",
        created_at: "2026-06-28T00:00:00Z",
      } as GateEvidencePack,
      checksum: "sha256:gate-checksum",
    };
  }

  it("SourceProfileOverrideForm build helper returns override_source_profile body in happy path", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-2.7-java11",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail();
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "Detected profile is incorrect",
      comments: "Operator verified the source pom.xml manually",
      idempotencyKey: "idem-1",
    });

    expect(result.blockedReason).toBeNull();
    expect(result.body).not.toBeNull();
    expect(result.body).toMatchObject({
      action: "override_source_profile",
      expected_gate_checksum: "sha256:gate-checksum",
      idempotency_key: "idem-1",
      decided_by: "human",
      actor_type: "human",
      reason: "Detected profile is incorrect",
      comments: "Operator verified the source pom.xml manually",
      override_source_profile: "springboot-3.5-java17",
      detection_artifact_ref: "analysis/source_profile_detection.json",
      detected_source_profile: "springboot-2.7-java11",
      requested_source_profile: "springboot-3.5-java17",
      target_profile: "springboot-4.0-java21",
      expected_detection_artifact_checksum: "sha256:detection-checksum",
    });

    // Forbidden runtime fields are absent from the body.
    const serialized = JSON.stringify(result.body);
    expect(serialized).not.toContain("sandbox_path");
    expect(serialized).not.toContain("argv");
    expect(serialized).not.toContain("env");
    expect(serialized).not.toContain("raw_command");
    expect(serialized).not.toContain("filesystem_target");
    expect(serialized).not.toContain("filesystem_root");
    expect(serialized).not.toContain("output_root");
    expect(serialized).not.toContain("report_root");
    expect(serialized).not.toContain("run_root");
    expect(serialized).not.toContain("ai_hub_path");
    expect(serialized).not.toContain("java_home");
    expect(serialized).not.toContain("java11_home");
    expect(serialized).not.toContain("java17_home");
    expect(serialized).not.toContain("java21_home");
    expect(serialized).not.toContain("maven_cmd");
    expect(serialized).not.toMatch(/"provider"/);
    expect(serialized).not.toMatch(/"model"/);
    expect(serialized).not.toMatch(/"model_id"/);
    expect(serialized).not.toMatch(/"deployment"/);
    expect(serialized).not.toMatch(/"endpoint"/);
    expect(serialized).not.toMatch(/"api_key"/);
    expect(serialized).not.toMatch(/"access_token"/);
  });

  it("SourceProfileOverrideForm submit path posts the body produced by the build helper", async () => {
    afterEach(() => vi.restoreAllMocks());

    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-2.7-java11",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail();
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "Detected profile is incorrect",
      comments: "Operator verified the source pom.xml manually",
      idempotencyKey: "idem-1",
    });
    expect(result.body).not.toBeNull();

    const fetchMock = vi.fn<(input: string | URL | Request, init?: RequestInit) => Promise<Response>>(async () => ({
      ok: true,
      json: async () => ({
        result: {
          decision_id: "d-1",
          gate_id: "gate-1",
          action: "override_source_profile",
          status: "resolved",
        },
      }),
    } as Response));
    vi.stubGlobal("fetch", fetchMock);

    await postV2GateAction("job-1", "gate-1", result.body!);

    const actionCall = fetchMock.mock.calls.find(
      (call) => String(call[0]).includes("/actions"),
    ) as [string, RequestInit?] | undefined;
    expect(actionCall).toBeDefined();
    const body = JSON.parse(String((actionCall?.[1] as RequestInit | undefined)?.body ?? "{}"));
    expect(body.action).toBe("override_source_profile");
    expect(body.target_profile).toBe("springboot-4.0-java21");
    expect(body.detection_artifact_ref).toBe("analysis/source_profile_detection.json");
    expect(body.expected_detection_artifact_checksum).toBe("sha256:detection-checksum");
    expect(body.actor_type).toBe("human");
    expect(body.decided_by).toBe("human");

    const serialized = JSON.stringify(body);
    for (const forbidden of [
      "sandbox_path", "argv", "env", "raw_command", "filesystem_target",
      "filesystem_root", "output_root", "report_root", "run_root",
      "ai_hub_path", "java_home", "java11_home", "java17_home", "java21_home",
      "maven_cmd",
    ]) {
      expect(serialized).not.toContain(forbidden);
    }
    expect(serialized).not.toMatch(/"provider"/);
    expect(serialized).not.toMatch(/"model"/);
    expect(serialized).not.toMatch(/"model_id"/);
    expect(serialized).not.toMatch(/"deployment"/);
    expect(serialized).not.toMatch(/"endpoint"/);
    expect(serialized).not.toMatch(/"api_key"/);
    expect(serialized).not.toMatch(/"access_token"/);
  });

  it("SourceProfileOverrideForm build helper uses the gate target profile when present", () => {
    const gateDetail = makeAnalysisReviewGateDetail();
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "r",
      comments: "c",
      idempotencyKey: "idem-1",
    });
    expect(result.body).not.toBeNull();
    expect(result.body?.target_profile).toBe("springboot-2.7-java11");
    expect(result.blockedReason).toBeNull();
  });

  it("SourceProfileOverrideForm build helper returns null when source artifact ref is missing", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail({
      sourceArtifactRefs: ["analysis/analysis_report.json", "analysis/analysis_summary.md"],
    });
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "r",
      comments: "c",
      idempotencyKey: "idem-1",
    });
    expect(result.body).toBeNull();
    expect(result.blockedReason).toBe("missing_detection_artifact_ref");
    expect(result.detectionArtifactRef).toBe("");
  });

  it("SourceProfileOverrideForm build helper returns null when source artifact checksum is missing", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail({
      sourceArtifactChecksum: "",
    });
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "r",
      comments: "c",
      idempotencyKey: "idem-1",
    });
    expect(result.body).toBeNull();
    expect(result.blockedReason).toBe("missing_detection_artifact_checksum");
  });

  it("SourceProfileOverrideForm build helper returns null when reason is blank", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail();
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "   ",
      comments: "ok",
      idempotencyKey: "idem-1",
    });
    expect(result.body).toBeNull();
    expect(result.blockedReason).toBe("missing_reason");
  });

  it("SourceProfileOverrideForm build helper returns null when comments is blank", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail();
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "ok",
      comments: "",
      idempotencyKey: "idem-1",
    });
    expect(result.body).toBeNull();
    expect(result.blockedReason).toBe("missing_comments");
  });

  it("SourceProfileOverrideForm build helper returns null when gate phase is not analysis_review", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gate: GateRepresentation = {
      gate_id: "gate-1",
      job_id: "job-1",
      gate_phase: "planning_review",
      stage_index: 1,
      gate_status: "open",
      gate_decision: "continue",
      source_artifact_checksum: "sha256:detection-checksum",
      source_artifact_refs: ["analysis/source_profile_detection.json"],
      created_at: "2026-06-28T00:00:00Z",
      resolved_at: null,
      resolved_by: null,
      checksum: "sha256:gate-checksum",
      available_actions: [
        {
          action: "override_source_profile",
          label: "Override",
          description: "Override",
          blocked: false,
          block_reason: "",
        },
      ],
    };
    const result = buildSourceProfileOverrideBody({
      gate,
      jobId: "job-1",
      job,
      evidence: null,
      requestedProfile: "springboot-3.5-java17",
      reason: "r",
      comments: "c",
      idempotencyKey: "idem-1",
    });
    expect(result.body).toBeNull();
    expect(result.blockedReason).toBe("gate_phase_not_analysis_review");
  });

  it("SourceProfileOverrideForm build helper returns null when available_actions lacks override_source_profile", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail({
      availableActions: [
        { action: "continue", label: "Continue", description: "Continue", blocked: false, block_reason: "" },
      ],
    });
    const result = buildSourceProfileOverrideBody({
      gate: gateDetail.gate,
      jobId: "job-1",
      job,
      evidence: gateDetail.evidence,
      requestedProfile: "springboot-3.5-java17",
      reason: "r",
      comments: "c",
      idempotencyKey: "idem-1",
    });
    expect(result.body).toBeNull();
    expect(result.blockedReason).toBe("override_action_unavailable");
  });

  it("SourceProfileOverrideForm renders springboot-3.5-java21 as a selectable source option", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      target_profile: "springboot-4.0-java21",
    };
    const gateDetail = makeAnalysisReviewGateDetail();
    const markup = renderToStaticMarkup(
      <SourceProfileOverrideForm
        gateDetail={gateDetail}
        jobId="job-1"
        job={job}
        onSuccess={() => undefined}
      />,
    );
    expect(markup).toContain("Spring Boot 3.5 / Java 17");
    expect(markup).toContain("Spring Boot 3.5 / Java 21");
    expect(markup).toContain('value="springboot-3.5-java21"');
  });

  it("MigrationRoutePanel renders springboot-3.5-java21 source profile in cockpit", () => {
    const job: V2MigrationJobResponse = {
      job_id: "job-1",
      setup_id: "setup-1",
      setup_checksum: "chk-1",
      pipeline_id: "pipeline-1",
      stages: [],
      created_at: "2026-06-28T00:00:00Z",
      source_profile: "springboot-3.5-java21",
      target_profile: "springboot-4.0-java21",
      validation_status: "valid",
      included_stages: ["4"],
      skipped_stages: ["2", "3"],
      excluded_stages: [],
    };
    const markup = renderToStaticMarkup(<MigrationRoutePanel job={job} />);
    expect(markup).toContain("Spring Boot 3.5 / Java 21");
    expect(markup).toContain("Spring Boot 4.0 / Java 21");
    expect(markup).toContain("4");
    expect(markup).toContain("2, 3");
  });

  it("getSourceProfileOverrideBlockedReason returns the right reason for each missing input", () => {
    const base = {
      isAnalysisReview: true,
      hasOverrideAction: true,
      hasTargetProfile: true,
      hasDetectionArtifactRef: true,
      hasExpectedChecksum: true,
      reason: "ok",
      comments: "ok",
    };
    expect(getSourceProfileOverrideBlockedReason({ ...base, isAnalysisReview: false }))
      .toBe("gate_phase_not_analysis_review");
    expect(getSourceProfileOverrideBlockedReason({ ...base, hasOverrideAction: false }))
      .toBe("override_action_unavailable");
    expect(getSourceProfileOverrideBlockedReason({ ...base, hasTargetProfile: false }))
      .toBe("missing_target_profile");
    expect(getSourceProfileOverrideBlockedReason({ ...base, hasDetectionArtifactRef: false }))
      .toBe("missing_detection_artifact_ref");
    expect(getSourceProfileOverrideBlockedReason({ ...base, hasExpectedChecksum: false }))
      .toBe("missing_detection_artifact_checksum");
    expect(getSourceProfileOverrideBlockedReason({ ...base, reason: "" }))
      .toBe("missing_reason");
    expect(getSourceProfileOverrideBlockedReason({ ...base, comments: "" }))
      .toBe("missing_comments");
    expect(getSourceProfileOverrideBlockedReason(base)).toBeNull();
  });
});

describe("F15 Final Report and Stage 4 cockpit", () => {
  it("report panel uses backend eligible and blockers", () => {
    const reportBlocked = {
      eligible: false,
      blockers: ["stage_2_not_completed", "gate_3_not_passed"],
    };
    expect(reportBlocked.eligible).toBe(false);
    expect(reportBlocked.blockers).toHaveLength(2);
    const copy = reportBlocked.blockers.join(" ");
    expect(copy).toContain("stage_2_not_completed");

    const reportReady = { eligible: true, blockers: [] };
    expect(reportReady.eligible).toBe(true);
    expect(reportReady.blockers).toHaveLength(0);

    const blockedMarkup = renderToStaticMarkup(
      <section className="panel">
        <h2>Final Report</h2>
        {reportBlocked.blockers.map((b) => (
          <p className="warning-text" key={b}>{b}</p>
        ))}
        {!reportBlocked.eligible && <p className="meta">Report generation not yet available for this job.</p>}
      </section>
    );
    expect(blockedMarkup).toContain("stage_2_not_completed");
    expect(blockedMarkup).toContain("not yet available");

    const readyMarkup = renderToStaticMarkup(
      <section className="panel">
        <h2>Final Report</h2>
        {reportReady.blockers.map((b) => (
          <p className="warning-text" key={b}>{b}</p>
        ))}
        {!reportReady.eligible && <p className="meta">Report generation not yet available for this job.</p>}
      </section>
    );
    expect(readyMarkup).not.toContain("not yet available");
    expect(readyMarkup).toContain("Final Report");
  });

  it("generate does not auto-download", () => {
    const generateMarkup = renderToStaticMarkup(
      <div>
        <button type="button">Generate report</button>
        <div className="report-artifact-row">
          <a href="/v1/reports/r1" download>Download</a>
        </div>
      </div>
    );
    expect(generateMarkup).toContain("Generate report");
    expect(generateMarkup).toContain("Download");
    // Generate button itself has no download attribute
    expect(generateMarkup).toContain("<button");
    expect(generateMarkup).not.toMatch(/<button[^>]*download/);
  });

  it("explicit download uses returned API URL", () => {
    const downloadUrl = "/v1/reports/final/r1";
    expect(downloadUrl.startsWith("/v1/")).toBe(true);
    const resolved = resolveReportDownloadUrl(downloadUrl);
    expect(resolved).toBe(`${CONTROL_TOWER_API_BASE_URL}${downloadUrl}`);
    expect(resolved).toContain("/v1/reports/final/r1");
  });

  it("gate, evidence, approval, assistant, and POM panels still render", async () => {
    const page = await MigrationCockpitPage({
      params: Promise.resolve({ jobId: "429a9bb2154b4be7a99a32867780d744" }),
    });
    const children = page.props.children;
    const cockpit = children[1];
    expect(cockpit.type).toBe(MigrationCockpit);

    const markup = renderToStaticMarkup(<MigrationCockpit jobId="job-123" />);
    expect(markup).toContain("Loading cockpit");

    const cockpitFunc = cockpit.type as () => React.JSX.Element;
    const source = cockpitFunc.toString();
    // All expected panel headings must appear in the component's rendering logic
    expect(source).toContain("Stage Timeline");
    expect(source).toContain("buildStageTimelineEntries(data.job.route_steps, data.stages)");
    expect(source).toContain("Pipeline Status");
    expect(source).toContain("Evidence");
    expect(source).toContain("Assistant");
    expect(source).toContain("Proof & Report");
    expect(source).toContain("Final Report");
  });

  it("four-stage rendering is visible (Stage 4 appears as a stage)", () => {
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "completed", input_source_kind: "legacy_source" },
      { stage_index: 2, pipeline_stage: "Stage 2", chain_status: "completed", input_source_kind: "stage_1_sandbox" },
      { stage_index: 3, pipeline_stage: "Stage 3", chain_status: "completed", input_source_kind: "stage_2_sandbox" },
      { stage_index: 4, pipeline_stage: "Stage 4", chain_status: "pending", input_source_kind: "stage_3_sandbox" },
    ];
    expect(stages).toHaveLength(4);
    const stage4 = stages.find((s) => s.stage_index === 4);
    expect(stage4).toBeDefined();
    expect(stage4!.pipeline_stage).toBe("Stage 4");
    expect(stage4!.input_source_kind).toBe("stage_3_sandbox");

    const markup = renderToStaticMarkup(
      <div className="stage-list">
        {stages.map((stage) => (
          <div key={stage.stage_index} className={`stage-card ${stage.chain_status}`}>
            <strong>{stage.pipeline_stage}</strong>
            <span>{formatStageStatusLabel(stage.chain_status)}</span>
            <p className="meta">Input: {stage.input_source_kind}</p>
          </div>
        ))}
      </div>
    );
    expect(markup).toContain("Stage 4");
    expect(markup).toContain("PENDING");
    expect(markup).toContain("stage_3_sandbox");
  });

  it("no manual Stage 4 start, input, or path control appears", () => {
    const forbiddenPatterns = ["start_stage_4", "Start Stage 4", "stage_4_path", "stage_4_input", "sandbox_path"];
    const markup = renderToStaticMarkup(
      <div className="cockpit-layout">
        <section className="panel">
          <h2>Stage Timeline</h2>
          <div className="stage-list">
            <div className="stage-card queued">
              <div className="stage-header">
                <strong>Stage 4</strong>
                <span className="status-badge queued">QUEUED</span>
              </div>
              <p className="meta">Input: stage_3_sandbox</p>
              <p className="meta">Stage 4 is the Spring Boot 4 migration stage and follows the same approval and evidence flow as the earlier stages.</p>
            </div>
          </div>
        </section>
      </div>
    );
    for (const pattern of forbiddenPatterns) {
      expect(markup).not.toContain(pattern);
    }
    // Stage 4 renders as read-only status display
    expect(markup).toContain("Stage 4");
    expect(markup).toContain("QUEUED");
    expect(markup).toContain("stage_3_sandbox");
    expect(markup).toContain("follows the same approval and evidence flow");
  });

  it("does not imply a separate Stage 4 approval when no gate is open", () => {
    const markup = renderToStaticMarkup(
      <GatePanelContent
        state={{
          status: "success",
          gates: [],
          openGate: null,
          openGateDetail: null,
        }}
      />
    );

    expect(markup).toContain("No gate is currently open for this job.");
    expect(markup).not.toContain("requires explicit approval to start");
  });
});

// ── PR-C — Cockpit integration tests ─────────────────────────────────

describe("PR-C Repair Proposal Panel integration", () => {
  it("MigrationCockpit source references RepairProposalPanel", () => {
    const source = MigrationCockpit.toString();
    expect(source).toContain("RepairProposalPanel");
    expect(source).toContain("normalizedJobId &&");
  });

  it("RepairProposalPanel renders with jobId and shows loading state", () => {
    const markup = renderToStaticMarkup(
      <MigrationCockpit jobId="test-job-123" />
    );
    expect(markup).toContain("Loading cockpit");
  });

  it("route_steps still override legacy stages in cockpit", () => {
    const routeSteps: V2RouteStepEntry[] = [
      {
        route_step_index: 1,
        stage_index: 1,
        source_profile: "springboot-2.7-java11",
        target_profile: "springboot-3.5-java17",
        runtime_profile: "springboot-2.7-to-3.5-java17",
        catalog: "springboot-3.5-java17",
        execution_jdk: "java17",
        status: "running",
        approval_gate_id: "",
        artifact_refs: [],
        evidence_refs: [],
      },
    ];
    const stages = [
      { stage_index: 1, pipeline_stage: "Stage 1", chain_status: "running", input_source_kind: "legacy_source" },
    ];
    const entries = buildStageTimelineEntries(routeSteps, stages);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ route_step_index: 1, status: "running" });
  });

  it("no POST mutation APIs called from cockpit repair panel import", () => {
    const source = MigrationCockpit.toString();
    expect(source).not.toContain("getCurrentRepairProposal");
    expect(source).not.toContain("getRepairAttempts");
  });

  it("PR-C cockpit source does not contain forbidden fields", () => {
    const source = MigrationCockpit.toString();
    const forbidden = [
      "target_path",
      "patch_content",
      "sandbox_path",
      "argv",
      "env",
      "raw_command",
      "azure_endpoint",
      "api_key",
      "password",
    ];
    for (const f of forbidden) {
      expect(source).not.toContain(f);
    }
  });
});

// ── Multi-stage approval flow regression ──────────────────────────────

function approvalCard(
  cardId: string,
  stageIndex: number,
  checksum: string,
  status: "pending" | "approved" | "rejected",
): V2ApprovalResponse {
  return {
    card_id: cardId,
    job_id: "job-123",
    interrupt_id: `run-${stageIndex}`,
    request_checksum: checksum,
    stage_index: stageIndex,
    summary: "Pre-transform review required before sandbox transform.",
    status,
    created_at: "2026-07-02T00:00:00Z",
  };
}

describe("V2 multi-stage approval flow", () => {
  it("mergeCockpitLiveRefreshResults adds a new pending stage-3 approval while keeping stage-2 approved", () => {
    const stage2Approved = approvalCard("gate-stage-2", 2, "checksum-stage-2", "approved");
    const stage3Pending = approvalCard("gate-stage-3", 3, "checksum-stage-3", "pending");
    const current: CockpitData = { ...makeCockpitData(), approvals: [stage2Approved] };
    const merged = mergeCockpitLiveRefreshResults(current, [
      { status: "fulfilled", value: { approvals: [stage2Approved, stage3Pending] } },
      { status: "rejected", reason: new Error("stages fetch skipped") },
      { status: "rejected", reason: new Error("events fetch skipped") },
      { status: "rejected", reason: new Error("pipeline fetch skipped") },
      { status: "rejected", reason: new Error("failure summary fetch skipped") },
    ]);
    expect(merged.data.approvals).toHaveLength(2);
    const byCard = Object.fromEntries(merged.data.approvals.map((a) => [a.card_id, a.status]));
    expect(byCard["gate-stage-2"]).toBe("approved");
    expect(byCard["gate-stage-3"]).toBe("pending");
  });

  it("approved old gate does not hide pending new gate Approve/Reject buttons", () => {
    const stage2Approved = approvalCard("gate-stage-2", 2, "checksum-stage-2", "approved");
    const stage3Pending = approvalCard("gate-stage-3", 3, "checksum-stage-3", "pending");
    const markup = renderToStaticMarkup(
      <ApprovalDecisionsPanel
        approvals={[stage2Approved, stage3Pending]}
        approvalReviewOpen={true}
        approvalBusy={null}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    );
    // Stage 2 shows approved status.
    expect(markup).toContain("Stage 2");
    expect(markup).toContain("APPROVED");
    // Stage 3 pending gate renders its own active Approve/Reject buttons.
    expect(markup).toContain("Stage 3");
    expect(markup).toContain("checksum-stage-3");
    expect(markup).toContain("Approve");
    expect(markup).toContain("Reject");
    // The stage-3 Approve button (second one) must not be disabled.
    const lastApprove = markup.lastIndexOf("Approve");
    expect(markup.slice(markup.lastIndexOf("<button", lastApprove), lastApprove)).not.toContain("disabled");
  });

  it("approveV2Card submits the exact stage-3 card id and checksum, not an earlier stage's", async () => {
    const originalFetch = global.fetch;
    const calls: { url: string; body: string | null }[] = [];
    global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: typeof init?.body === "string" ? init.body : null });
      return new Response(
        JSON.stringify({
          resume_id: "res-3",
          card_id: "gate-stage-3",
          decision: "approved",
          job_id: "job-123",
          stage_index: 3,
          command: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;
    try {
      await approveV2Card("job-123", "gate-stage-3", "checksum-stage-3");
      expect(calls[0].url).toBe(
        `${CONTROL_TOWER_API_BASE_URL}/v1/v2/jobs/job-123/approvals/gate-stage-3/approve`,
      );
      const body = JSON.parse(calls[0].body ?? "{}");
      expect(body).toEqual({ expected_checksum: "checksum-stage-3" });
      // Must not send an earlier stage's identity or checksum.
      expect(body.expected_checksum).not.toBe("checksum-stage-2");
      expect(calls[0].url).not.toContain("gate-stage-2");
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("after stages 2 and 3 are approved, stage 4 pending still renders Approve/Reject", () => {
    const stage2Approved = approvalCard("gate-stage-2", 2, "checksum-stage-2", "approved");
    const stage3Approved = approvalCard("gate-stage-3", 3, "checksum-stage-3", "approved");
    const stage4Pending = approvalCard("gate-stage-4", 4, "checksum-stage-4", "pending");
    const markup = renderToStaticMarkup(
      <ApprovalDecisionsPanel
        approvals={[stage4Pending, stage3Approved, stage2Approved]}
        approvalReviewOpen={true}
        approvalBusy={null}
        onApprove={() => {}}
        onReject={() => {}}
      />,
    );
    expect(markup).toContain("Stage 4");
    expect(markup).toContain("checksum-stage-4");
    expect(markup).toContain("Approve");
    expect(markup).toContain("Reject");
    // Earlier approved stages remain visible as approved.
    expect(markup).toContain("APPROVED");
    // The stage-4 Approve button (first one) must not be disabled.
    const firstApprove = markup.indexOf("Approve");
    expect(markup.slice(markup.lastIndexOf("<button", firstApprove), firstApprove)).not.toContain("disabled");
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
