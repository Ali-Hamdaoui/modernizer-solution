"use client";

import { useState } from "react";
import type { ReviewedDiffProposal, SafeDiffPreview as SafeDiffPreviewType } from "../../../lib/contracts";
import { SafeDiffPreview } from "./SafeDiffPreview";
import { ReviewerVerdictCard } from "./ReviewerVerdictCard";

type TabId = "diff" | "static-analysis" | "files-changed" | "reviewer-opinion" | "chat";

const TABS: { id: TabId; label: string }[] = [
  { id: "diff", label: "Diff" },
  { id: "static-analysis", label: "Static Analysis" },
  { id: "files-changed", label: "Files Changed" },
  { id: "reviewer-opinion", label: "Reviewer Opinion" },
  { id: "chat", label: "Chat" },
];

export function ReviewedDiffTabs({
  proposal,
  diff,
  onTabChange,
}: {
  proposal: ReviewedDiffProposal;
  diff: SafeDiffPreviewType | null;
  onTabChange?: (tab: TabId) => void;
}) {
  const [activeTab, setActiveTab] = useState<TabId>("diff");

  function handleTabClick(tab: TabId) {
    setActiveTab(tab);
    onTabChange?.(tab);
  }

  return (
    <div className="reviewed-diff-tabs" data-testid="reviewed-diff-tabs">
      <div className="tab-bar" role="tablist">
        {TABS.map((tab) => (
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
              </div>
            )}
          </div>
        )}
        {activeTab === "static-analysis" && (
          <div data-testid="tabpanel-static-analysis">
            <p className="meta">Static analysis summary:</p>
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
                    <strong>{fc.path}</strong>
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
        {activeTab === "chat" && (
          <div data-testid="tabpanel-chat">
            <p className="meta">
              Chat is read-only in the current view. Use the assistant panel to ask questions about this proposal.
            </p>
            <p className="meta">
              Use the "Request revision" button in the actions bar to request changes.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export type { TabId };
