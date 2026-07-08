"use client";

import { useMemo, useState } from "react";
import type { ReviewedDiffProposal, SafeDiffPreview as SafeDiffPreviewType } from "../../../lib/contracts";
import { formatSafeRelativePath } from "../../../lib/safeDisplay";
import { SafeDiffPreview } from "./SafeDiffPreview";
import { ReviewerVerdictCard } from "./ReviewerVerdictCard";

type TabId = "diff" | "validation" | "files-changed" | "reviewer-opinion";

export function ReviewedDiffTabs({
  proposal,
  diff,
  diffMessage,
  candidateDiff,
  onTabChange,
}: {
  proposal: ReviewedDiffProposal;
  diff: SafeDiffPreviewType | null;
  diffMessage?: string | null;
  candidateDiff?: boolean;
  onTabChange?: (tab: TabId) => void;
}) {
  const tabs: { id: TabId; label: string }[] = useMemo(() => {
    if (candidateDiff) {
      return [
        { id: "diff", label: "Proposed Diff (Candidate)" },
        { id: "validation", label: "Validation" },
        { id: "files-changed", label: "Files Changed" },
        { id: "reviewer-opinion", label: "Reviewer Findings" },
      ];
    }
    return [
      { id: "diff", label: "Reviewed Diff" },
      { id: "validation", label: "Validation" },
      { id: "files-changed", label: "Files Changed" },
      { id: "reviewer-opinion", label: "Reviewer Verdict" },
    ];
  }, [candidateDiff]);
  const [activeTab, setActiveTab] = useState<TabId>("diff");

  function handleTabClick(tab: TabId) {
    setActiveTab(tab);
    onTabChange?.(tab);
  }

  return (
    <div className="reviewed-diff-tabs" data-testid="reviewed-diff-tabs">
      <div className="tab-bar" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            type="button"
            className={activeTab === tab.id ? "tab-active" : ""}
            onClick={() => handleTabClick(tab.id)}
            data-testid={`tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tab-content" role="tabpanel">
        {activeTab === "diff" && (
          <div data-testid="tabpanel-diff">
            {diff ? (
              <SafeDiffPreview diff={diff} />
            ) : (
              <div className="safe-diff-missing" data-testid="safe-diff-missing">
                <p className="meta">No diff preview available.</p>
                {proposal.diff_ref && <p className="meta">Diff could not be loaded.</p>}
                {diffMessage && <p className="meta warning-text">{diffMessage}</p>}
              </div>
            )}
          </div>
        )}
        {activeTab === "validation" && (
          <div data-testid="tabpanel-validation">
            <p className="meta">Backend policy and validation requirements:</p>
            <div className="table-list">
              {proposal.risk && (
                <div className="table-row">
                  <span className="meta">Risk</span>
                  <strong>{proposal.risk}</strong>
                </div>
              )}
              {proposal.required_validation.length > 0 && (
                <div className="table-row">
                  <span className="meta">Required validation</span>
                  <strong>{proposal.required_validation.join(", ") || "None"}</strong>
                </div>
              )}
              {proposal.redactions.length > 0 && (
                <div className="table-row">
                  <span className="meta">Redactions</span>
                  <strong className="warning-text">{proposal.redactions.join(", ")}</strong>
                </div>
              )}
            </div>
          </div>
        )}
        {activeTab === "files-changed" && (
          <div data-testid="tabpanel-files-changed">
            {proposal.files_changed.length === 0 ? (
              <p className="meta">No files changed.</p>
            ) : (
              <div className="table-list">
                {proposal.files_changed.map((fc, i) => (
                  <div key={i} className="table-row" data-testid="files-changed-row">
                    <span className="meta">{fc.change_type}</span>
                    <strong>{formatSafeRelativePath(fc.path)}</strong>
                    <span className="meta">+{fc.additions} / -{fc.deletions}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {activeTab === "reviewer-opinion" && (
          <div data-testid="tabpanel-reviewer-opinion">
            <ReviewerVerdictCard verdict={proposal.reviewer_verdict} />
          </div>
        )}
      </div>
    </div>
  );
}

export type { TabId };
