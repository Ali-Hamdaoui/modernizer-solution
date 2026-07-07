"use client";

import { useMemo, useState } from "react";
import { applyStage4TargetVersionChanges, getV2RootPomPreview } from "../../../lib/controlTowerApi";
import type { Stage4TargetVersionApplyResponse } from "../../../lib/contracts";

type ComparisonStatus = "matches" | "different" | "missing_in_pom" | "no_explicit_pom_version" | "blocked";

export type TargetVersionRow = {
  rowNumber: number;
  coordinate: string;
  groupId: string;
  artifactId: string;
  targetVersion: string;
};

export type TargetVersionComparisonRow = TargetVersionRow & {
  pomVersion: string | null;
  versionSource: string;
  status: ComparisonStatus;
  reason: string;
  canApply: boolean;
};

type Props = {
  jobId: string;
  stage4Completed: boolean;
};

type PomVersion = {
  version: string | null;
  source: string;
  duplicate: boolean;
};

export default function Stage4TargetVersionComparison({ jobId, stage4Completed }: Props) {
  const [fileName, setFileName] = useState("");
  const [rows, setRows] = useState<TargetVersionComparisonRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState<Stage4TargetVersionApplyResponse | null>(null);

  async function loadComparison(targetRows: TargetVersionRow[]) {
    const pomPreview = await getV2RootPomPreview(jobId, 4);
    const pomText = pomPreview.content ?? pomPreview.preview;
    if (!pomPreview.exists || !pomText.trim()) {
      throw new Error("Stage 4 root pom.xml is not available yet.");
    }
    setRows(compareTargetVersionsToPom(targetRows, pomText));
  }

  async function handleFileSelected(file: File | null) {
    setError(null);
    setRows([]);
    setApplyResult(null);
    setFileName(file?.name ?? "");
    if (!file) return;
    if (!stage4Completed) {
      setError("Stage 4 must complete before comparing target versions.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setError("Upload a CSV file with groupId, artifactId, and targetVersion columns.");
      return;
    }
    setLoading(true);
    try {
      const targetRows = parseTargetVersionsCsv(await file.text());
      if (targetRows.length === 0) {
        throw new Error("CSV did not contain any dependency rows.");
      }
      await loadComparison(targetRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to compare target versions.");
    } finally {
      setLoading(false);
    }
  }

  async function handleApplyChanges() {
    const candidates = rows.filter((row) => row.canApply && row.status === "different");
    if (candidates.length === 0) return;
    setError(null);
    setApplyResult(null);
    setApplying(true);
    try {
      const result = await applyStage4TargetVersionChanges(jobId, {
        idempotency_key: createIdempotencyKey(),
        changes: candidates.map((row) => ({
          group_id: row.groupId,
          artifact_id: row.artifactId,
          target_version: row.targetVersion,
        })),
      });
      setApplyResult(result);
      if (result.applied_count > 0) {
        await loadComparison(rows);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply target versions.");
    } finally {
      setApplying(false);
    }
  }

  const summary = useMemo(() => summarizeComparison(rows), [rows]);
  const applyableCount = rows.filter((row) => row.canApply && row.status === "different").length;

  return (
    <section className="panel cockpit-panel target-version-panel">
      <h2>Target Dependency Versions</h2>
      <p className="meta">
        Upload a CSV file to compare target dependency versions with the Stage 4 root pom.xml. No file is changed until Change is clicked.
      </p>
      <div className="csv-upload-row">
        <input
          aria-label="Upload target dependency version CSV"
          accept=".csv,text/csv"
          disabled={loading || applying || !stage4Completed}
          type="file"
          onChange={(event) => void handleFileSelected(event.currentTarget.files?.[0] ?? null)}
        />
        <button type="button" disabled={applying || applyableCount === 0} onClick={() => void handleApplyChanges()}>
          {applying ? "Changing..." : "Change"}
        </button>
      </div>
      {!stage4Completed && <p className="meta">CSV comparison unlocks after Stage 4 completes successfully.</p>}
      {fileName && <p className="meta">File: <code>{fileName}</code></p>}
      {loading && <p className="meta">Reading CSV and Stage 4 POM...</p>}
      {error && <p className="target-version-error" role="alert">{error}</p>}
      {rows.length > 0 && (
        <>
          <div className="target-version-summary">
            <span className="status-badge completed">{summary.matches} match</span>
            <span className="status-badge running">{summary.different} different</span>
            <span className="status-badge blocked">{summary.noExplicitVersion} managed/no version</span>
            <span className="status-badge failed">{summary.missing} missing</span>
            <span className="status-badge blocked">{summary.blocked} blocked</span>
          </div>
          <div className="target-version-table-wrap">
            <table className="target-version-table">
              <thead>
                <tr>
                  <th>Dependency</th>
                  <th>CSV target</th>
                  <th>Stage 4 POM</th>
                  <th>Source</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.rowNumber}-${row.coordinate}`} className={`target-version-${row.status}`}>
                    <td><code>{row.coordinate}</code></td>
                    <td>{row.targetVersion}</td>
                    <td>{row.pomVersion ?? "not explicit"}</td>
                    <td>{row.versionSource}</td>
                    <td>{row.reason || formatComparisonStatus(row.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {applyResult && (
        <div className="target-version-apply-result" role="status">
          <strong>{applyResult.message}</strong>
          <p className="meta">
            Applied {applyResult.applied_count}, skipped {applyResult.skipped_count}, blocked {applyResult.blocked_count}.
          </p>
          {applyResult.items.length > 0 && (
            <ul>
              {applyResult.items.map((item) => (
                <li key={item.coordinate}>{item.coordinate}: {item.status} ({item.reason})</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <style>{`
        .target-version-panel { max-height: 560px; }
        .csv-upload-row { align-items: center; display: flex; flex-wrap: wrap; gap: 0.6rem; margin: 0.75rem 0; }
        .csv-upload-row button { border: 1px solid #1f6f43; background: #1f6f43; color: #fff; border-radius: 4px; padding: 0.45rem 0.8rem; font-weight: 700; }
        .csv-upload-row button:disabled { opacity: 0.55; cursor: not-allowed; }
        .target-version-error { background: #fff0f0; border: 1px solid #e7b4b4; border-radius: 6px; color: #9f1d1d; font-size: 0.86rem; padding: 0.65rem 0.75rem; }
        .target-version-summary { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.75rem 0; }
        .target-version-table-wrap { overflow: auto; }
        .target-version-table { border-collapse: collapse; font-size: 0.85rem; min-width: 760px; width: 100%; }
        .target-version-table th, .target-version-table td { border-bottom: 1px solid #e6ece9; padding: 0.55rem 0.45rem; text-align: left; vertical-align: top; }
        .target-version-table th { color: #44524c; font-weight: 800; }
        .target-version-table code { overflow-wrap: anywhere; white-space: normal; }
        .target-version-different td { background: #fffaf0; }
        .target-version-missing_in_pom td { background: #fff4f4; }
        .target-version-no_explicit_pom_version td, .target-version-blocked td { background: #faf7ff; }
        .target-version-apply-result { border: 1px solid #b7d7c1; border-radius: 6px; background: #f1fbf4; margin-top: 0.75rem; padding: 0.75rem; }
      `}</style>
    </section>
  );
}

export function parseTargetVersionsCsv(csvText: string): TargetVersionRow[] {
  return parseTargetVersionRows(parseCsv(csvText), "CSV");
}

export function parseTargetVersionRows(parsedRows: string[][], sourceLabel: string): TargetVersionRow[] {
  if (parsedRows.length < 2) return [];
  const headers = parsedRows[0].map(normalizeHeader);
  const groupIndex = findHeaderIndex(headers, ["groupid", "group", "group_id"]);
  const artifactIndex = findHeaderIndex(headers, ["artifactid", "artifact", "artifact_id", "dependency"]);
  const versionIndex = findHeaderIndex(headers, ["targetversion", "target_version", "version", "target"]);
  const coordinateIndex = findHeaderIndex(headers, ["coordinate", "gav", "dependencycoordinate", "dependency_coordinate"]);
  if (coordinateIndex < 0 && (groupIndex < 0 || artifactIndex < 0 || versionIndex < 0)) {
    throw new Error(`${sourceLabel} must include either coordinate or groupId, artifactId, and targetVersion columns.`);
  }
  const seen = new Map<string, string>();
  return parsedRows.slice(1).flatMap((cells, index) => {
    const rowNumber = index + 2;
    const coordinateCell = readCell(cells, coordinateIndex);
    const groupCell = readCell(cells, groupIndex);
    const artifactCell = readCell(cells, artifactIndex);
    const versionCell = readCell(cells, versionIndex);
    const coordinateParts = coordinateCell.split(":").map((part) => part.trim()).filter(Boolean);
    const groupId = groupCell || coordinateParts[0] || "";
    const artifactId = artifactCell || coordinateParts[1] || "";
    const targetVersion = versionCell || coordinateParts[2] || "";
    if (!groupId && !artifactId && !targetVersion) return [];
    if (!groupId || !artifactId || !targetVersion) {
      throw new Error(`${sourceLabel} row ${rowNumber} must include groupId, artifactId, and target version.`);
    }
    if (!isSafeCoordinatePart(groupId) || !isSafeCoordinatePart(artifactId)) {
      throw new Error(`${sourceLabel} row ${rowNumber} has an invalid dependency coordinate.`);
    }
    if (!isSafeVersion(targetVersion)) {
      throw new Error(`${sourceLabel} row ${rowNumber} has an invalid target version.`);
    }
    const coordinate = `${groupId}:${artifactId}`;
    const existing = seen.get(coordinate);
    if (existing && existing !== targetVersion) {
      throw new Error(`${sourceLabel} row ${rowNumber} duplicates ${coordinate} with a different target version.`);
    }
    if (existing) return [];
    seen.set(coordinate, targetVersion);
    return [{ rowNumber, coordinate, groupId, artifactId, targetVersion }];
  });
}

export function compareTargetVersionsToPom(targetRows: TargetVersionRow[], pomText: string): TargetVersionComparisonRow[] {
  const pomVersions = parsePomDependencyVersions(pomText);
  return targetRows.map((row) => {
    const pomVersion = pomVersions.get(row.coordinate);
    if (!pomVersion) {
      return { ...row, pomVersion: null, versionSource: "not_found", status: "missing_in_pom", reason: "Missing from POM", canApply: false };
    }
    if (pomVersion.duplicate) {
      return { ...row, pomVersion: pomVersion.version, versionSource: pomVersion.source, status: "blocked", reason: "Duplicate POM entries require manual review", canApply: false };
    }
    if (!pomVersion.version) {
      return { ...row, pomVersion: null, versionSource: pomVersion.source, status: "no_explicit_pom_version", reason: "No explicit version to update", canApply: false };
    }
    const matches = normalizeVersion(pomVersion.version) === normalizeVersion(row.targetVersion);
    return {
      ...row,
      pomVersion: pomVersion.version,
      versionSource: pomVersion.source,
      status: matches ? "matches" : "different",
      reason: matches ? "Matches target" : "Different version",
      canApply: !matches && ["dependency", "dependency_management", "property"].includes(pomVersion.source),
    };
  });
}

function parsePomDependencyVersions(pomText: string): Map<string, PomVersion> {
  const properties = parsePomProperties(pomText);
  const versions = new Map<string, PomVersion>();
  const seen = new Set<string>();
  const dependencyManagementRanges = findXmlBlocksWithSpans(pomText, "dependencyManagement");
  for (const block of findXmlBlocksWithSpans(pomText, "dependency")) {
    const groupId = extractXmlTag(block.text, "groupId");
    const artifactId = extractXmlTag(block.text, "artifactId");
    if (!groupId || !artifactId) continue;
    const coordinate = `${groupId}:${artifactId}`;
    const rawVersion = extractXmlTag(block.text, "version");
    const propertyName = rawVersion ? /^\$\{([^}]+)\}$/.exec(rawVersion.trim())?.[1] : undefined;
    const source = propertyName ? "property" : isInsideRange(block, dependencyManagementRanges) ? "dependency_management" : "dependency";
    const version = propertyName ? properties.get(propertyName) ?? rawVersion : rawVersion;
    const duplicate = seen.has(coordinate);
    seen.add(coordinate);
    versions.set(coordinate, { version, source, duplicate: duplicate || versions.get(coordinate)?.duplicate === true });
  }
  const parentBlock = findXmlBlocksWithSpans(pomText, "parent")[0];
  if (parentBlock) {
    const groupId = extractXmlTag(parentBlock.text, "groupId");
    const artifactId = extractXmlTag(parentBlock.text, "artifactId");
    const version = extractXmlTag(parentBlock.text, "version");
    if (groupId && artifactId && !versions.has(`${groupId}:${artifactId}`)) {
      versions.set(`${groupId}:${artifactId}`, { version, source: "parent", duplicate: false });
    }
  }
  return versions;
}

function parsePomProperties(pomText: string): Map<string, string> {
  const properties = new Map<string, string>();
  const propertiesBlock = findXmlBlocksWithSpans(pomText, "properties")[0]?.text ?? "";
  const tagPattern = /<([\w.-]+)>\s*([^<]+?)\s*<\/\1>/g;
  let match: RegExpExecArray | null;
  while ((match = tagPattern.exec(propertiesBlock)) !== null) {
    properties.set(match[1], decodeXmlText(match[2].trim()));
  }
  return properties;
}

function findXmlBlocksWithSpans(xmlText: string, tagName: string): Array<{ start: number; end: number; text: string }> {
  const pattern = new RegExp(`<${tagName}\\b[^>]*>[\\s\\S]*?<\\/${tagName}>`, "g");
  return [...xmlText.matchAll(pattern)].map((match) => ({ start: match.index ?? 0, end: (match.index ?? 0) + match[0].length, text: match[0] }));
}

function isInsideRange(block: { start: number; end: number }, ranges: Array<{ start: number; end: number }>): boolean {
  return ranges.some((range) => block.start >= range.start && block.end <= range.end);
}

function extractXmlTag(block: string, tagName: string): string | null {
  const pattern = new RegExp(`<${tagName}\\b[^>]*>\\s*([\\s\\S]*?)\\s*<\\/${tagName}>`);
  const match = pattern.exec(block);
  return match ? decodeXmlText(match[1].trim()) : null;
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (char === '"' && quoted && next === '"') {
      cell += '"';
      index += 1;
      continue;
    }
    if (char === '"') {
      quoted = !quoted;
      continue;
    }
    if (char === "," && !quoted) {
      row.push(cell.trim());
      cell = "";
      continue;
    }
    if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && next === "\n") index += 1;
      row.push(cell.trim());
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = "";
      continue;
    }
    cell += char;
  }
  row.push(cell.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

function summarizeComparison(rows: TargetVersionComparisonRow[]) {
  return {
    matches: rows.filter((row) => row.status === "matches").length,
    different: rows.filter((row) => row.status === "different").length,
    missing: rows.filter((row) => row.status === "missing_in_pom").length,
    noExplicitVersion: rows.filter((row) => row.status === "no_explicit_pom_version").length,
    blocked: rows.filter((row) => row.status === "blocked").length,
  };
}

function formatComparisonStatus(status: ComparisonStatus): string {
  if (status === "matches") return "Matches target";
  if (status === "different") return "Different version";
  if (status === "missing_in_pom") return "Missing from POM";
  if (status === "no_explicit_pom_version") return "No explicit POM version";
  return "Blocked";
}

function findHeaderIndex(headers: string[], names: string[]): number {
  return headers.findIndex((header) => names.includes(header));
}

function normalizeHeader(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function readCell(cells: string[], index: number): string {
  return index >= 0 ? (cells[index] ?? "").trim() : "";
}

function normalizeVersion(value: string): string {
  return value.trim().toLowerCase();
}

function isSafeCoordinatePart(value: string): boolean {
  return /^[A-Za-z0-9_.-]+$/.test(value);
}

function isSafeVersion(value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._+\-]*$/.test(value);
}

function decodeXmlText(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `csv-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}