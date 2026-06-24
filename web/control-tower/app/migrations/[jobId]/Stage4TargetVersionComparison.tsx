"use client";

import { useState } from "react";
import { getV2RootPomPreview } from "../../../lib/controlTowerApi";

type ComparisonStatus = "matches" | "different" | "missing_in_pom" | "no_explicit_pom_version";

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
};

type Props = {
  jobId: string;
  stage4Completed: boolean;
};

type PomVersion = {
  version: string | null;
  source: string;
};

type ZipEntry = {
  method: number;
  compressedData: Uint8Array;
};

export default function Stage4TargetVersionComparison({ jobId, stage4Completed }: Props) {
  const [fileName, setFileName] = useState("");
  const [rows, setRows] = useState<TargetVersionComparisonRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleFileSelected(file: File | null) {
    setError(null);
    setRows([]);
    setFileName(file?.name ?? "");
    if (!file) {
      return;
    }
    if (!stage4Completed) {
      setError("Stage 4 must complete before comparing target versions.");
      return;
    }
    setLoading(true);
    try {
      const targetRows = await readTargetVersionRowsFromFile(file);
      if (targetRows.length === 0) {
        throw new Error("Target version file did not contain any dependency rows.");
      }
      const pomPreview = await getV2RootPomPreview(jobId, 4);
      const pomText = pomPreview.content ?? pomPreview.preview;
      if (!pomPreview.exists || !pomText.trim()) {
        throw new Error("Stage 4 root pom.xml is not available yet.");
      }
      setRows(compareTargetVersionsToPom(targetRows, pomText));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to compare target versions.");
    } finally {
      setLoading(false);
    }
  }

  const summary = summarizeComparison(rows);

  return (
    <section className="panel cockpit-panel target-version-panel">
      <h2>Target Version File</h2>
      <p className="meta">
        Upload a CSV or Excel .xlsx file with target dependency versions. This compares the file with the Stage 4 root pom.xml only; it does not modify files or run validation.
      </p>
      <div className="csv-upload-row">
        <input
          aria-label="Upload target version file"
          accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          disabled={loading || !stage4Completed}
          type="file"
          onChange={(event) => void handleFileSelected(event.currentTarget.files?.[0] ?? null)}
        />
      </div>
      {!stage4Completed && (
        <p className="meta">Target version comparison unlocks after Stage 4 completes successfully.</p>
      )}
      {fileName && <p className="meta">File: <code>{fileName}</code></p>}
      {loading && <p className="meta">Reading target versions and Stage 4 POM...</p>}
      {error && <p className="target-version-error" role="alert">{error}</p>}
      {rows.length > 0 && (
        <>
          <div className="target-version-summary">
            <span className="status-badge completed">{summary.matches} match</span>
            <span className="status-badge running">{summary.different} different</span>
            <span className="status-badge blocked">{summary.noExplicitVersion} managed/no version</span>
            <span className="status-badge failed">{summary.missing} missing</span>
          </div>
          <div className="target-version-table-wrap">
            <table className="target-version-table">
              <thead>
                <tr>
                  <th>Dependency</th>
                  <th>CSV target</th>
                  <th>Stage 4 POM</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.rowNumber}-${row.coordinate}`} className={`target-version-${row.status}`}>
                    <td><code>{row.coordinate}</code></td>
                    <td>{row.targetVersion}</td>
                    <td>{row.pomVersion ?? "not explicit"}</td>
                    <td>{formatComparisonStatus(row.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <style>{`
        .target-version-panel {
          max-height: 520px;
        }
        .csv-upload-row {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 0.6rem;
          margin: 0.75rem 0;
        }
        .target-version-error {
          background: #fff0f0;
          border: 1px solid #e7b4b4;
          border-radius: 10px;
          color: #9f1d1d;
          font-size: 0.86rem;
          padding: 0.65rem 0.75rem;
        }
        .target-version-summary {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          margin: 0.75rem 0;
        }
        .target-version-table-wrap {
          overflow: auto;
        }
        .target-version-table {
          border-collapse: collapse;
          font-size: 0.85rem;
          min-width: 680px;
          width: 100%;
        }
        .target-version-table th,
        .target-version-table td {
          border-bottom: 1px solid #e6ece9;
          padding: 0.55rem 0.45rem;
          text-align: left;
          vertical-align: top;
        }
        .target-version-table th {
          color: #44524c;
          font-weight: 800;
        }
        .target-version-table code {
          overflow-wrap: anywhere;
          white-space: normal;
        }
        .target-version-different td {
          background: #fffaf0;
        }
        .target-version-missing_in_pom td {
          background: #fff4f4;
        }
        .target-version-no_explicit_pom_version td {
          background: #faf7ff;
        }
      `}</style>
    </section>
  );
}

export async function readTargetVersionRowsFromFile(file: File): Promise<TargetVersionRow[]> {
  const fileName = file.name.toLowerCase();
  if (fileName.endsWith(".xlsx")) {
    return parseTargetVersionsXlsx(await file.arrayBuffer());
  }
  if (fileName.endsWith(".xls")) {
    throw new Error("Legacy .xls files are not supported. Save the spreadsheet as .xlsx or CSV.");
  }
  return parseTargetVersionsCsv(await file.text());
}

export function parseTargetVersionsCsv(csvText: string): TargetVersionRow[] {
  const parsedRows = parseCsv(csvText);
  return parseTargetVersionRows(parsedRows, "CSV");
}

export async function parseTargetVersionsXlsx(workbookBytes: ArrayBuffer): Promise<TargetVersionRow[]> {
  const entries = await readZipTextEntries(workbookBytes);
  const sharedStrings = parseSharedStringsXml(entries.get("xl/sharedStrings.xml") ?? "");
  const worksheetPath = findFirstWorksheetPath(entries);
  const worksheetXml = entries.get(worksheetPath);
  if (!worksheetXml) {
    throw new Error("Excel file does not contain a readable first worksheet.");
  }
  return parseTargetVersionRows(parseWorksheetXmlRows(worksheetXml, sharedStrings), "Excel");
}

export function parseTargetVersionRows(parsedRows: string[][], sourceLabel: string): TargetVersionRow[] {
  if (parsedRows.length < 2) {
    return [];
  }
  const headers = parsedRows[0].map(normalizeHeader);
  const groupIndex = findHeaderIndex(headers, ["groupid", "group", "group_id"]);
  const artifactIndex = findHeaderIndex(headers, ["artifactid", "artifact", "artifact_id", "dependency"]);
  const versionIndex = findHeaderIndex(headers, ["targetversion", "target_version", "version", "target"]);
  const coordinateIndex = findHeaderIndex(headers, ["coordinate", "gav", "dependencycoordinate", "dependency_coordinate"]);

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
    if (!groupId && !artifactId && !targetVersion) {
      return [];
    }
    if (!groupId || !artifactId || !targetVersion) {
      throw new Error(`${sourceLabel} row ${rowNumber} must include groupId, artifactId, and target version.`);
    }
    return [{
      rowNumber,
      coordinate: `${groupId}:${artifactId}`,
      groupId,
      artifactId,
      targetVersion,
    }];
  });
}

async function readZipTextEntries(workbookBytes: ArrayBuffer): Promise<Map<string, string>> {
  const view = new DataView(workbookBytes);
  const bytes = new Uint8Array(workbookBytes);
  const directoryOffset = findCentralDirectoryOffset(view);
  const entries = new Map<string, string>();
  let offset = directoryOffset;

  while (offset + 46 <= bytes.length && view.getUint32(offset, true) === 0x02014b50) {
    const method = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const fileNameLength = view.getUint16(offset + 28, true);
    const extraLength = view.getUint16(offset + 30, true);
    const commentLength = view.getUint16(offset + 32, true);
    const localHeaderOffset = view.getUint32(offset + 42, true);
    const fileName = decodeUtf8(bytes.slice(offset + 46, offset + 46 + fileNameLength));
    const entry = readZipLocalEntry(view, bytes, localHeaderOffset, method, compressedSize);

    if (fileName.endsWith(".xml") || fileName.endsWith(".rels")) {
      entries.set(fileName.replace(/\\/g, "/"), decodeUtf8(await inflateZipEntry(entry)));
    }
    offset += 46 + fileNameLength + extraLength + commentLength;
  }

  return entries;
}

function findCentralDirectoryOffset(view: DataView): number {
  for (let offset = view.byteLength - 22; offset >= 0; offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) {
      return view.getUint32(offset + 16, true);
    }
  }
  throw new Error("Excel file is not a readable .xlsx workbook.");
}

function readZipLocalEntry(
  view: DataView,
  bytes: Uint8Array,
  localHeaderOffset: number,
  method: number,
  compressedSize: number,
): ZipEntry {
  if (view.getUint32(localHeaderOffset, true) !== 0x04034b50) {
    throw new Error("Excel file contains an unreadable worksheet entry.");
  }
  const fileNameLength = view.getUint16(localHeaderOffset + 26, true);
  const extraLength = view.getUint16(localHeaderOffset + 28, true);
  const dataStart = localHeaderOffset + 30 + fileNameLength + extraLength;
  return {
    method,
    compressedData: bytes.slice(dataStart, dataStart + compressedSize),
  };
}

async function inflateZipEntry(entry: ZipEntry): Promise<Uint8Array> {
  if (entry.method === 0) {
    return entry.compressedData;
  }
  if (entry.method !== 8) {
    throw new Error("Excel file uses an unsupported compression method.");
  }
  if (typeof DecompressionStream === "undefined") {
    throw new Error("This browser cannot read .xlsx files. Save the spreadsheet as CSV instead.");
  }
  const compressedBuffer = entry.compressedData.buffer.slice(
    entry.compressedData.byteOffset,
    entry.compressedData.byteOffset + entry.compressedData.byteLength,
  ) as ArrayBuffer;
  const stream = new Blob([compressedBuffer]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function findFirstWorksheetPath(entries: Map<string, string>): string {
  const workbookXml = entries.get("xl/workbook.xml") ?? "";
  const relsXml = entries.get("xl/_rels/workbook.xml.rels") ?? "";
  const sheetMatch = /<sheet\b[^>]*\br:id="([^"]+)"/.exec(workbookXml);
  if (sheetMatch) {
    const relationshipPattern = new RegExp(`<Relationship\\b[^>]*\\bId="${escapeRegExp(sheetMatch[1])}"[^>]*\\bTarget="([^"]+)"`);
    const relationshipMatch = relationshipPattern.exec(relsXml);
    if (relationshipMatch) {
      return normalizeWorkbookTargetPath(relationshipMatch[1]);
    }
  }
  return "xl/worksheets/sheet1.xml";
}

function normalizeWorkbookTargetPath(target: string): string {
  const decodedTarget = decodeXmlText(target);
  if (decodedTarget.startsWith("/")) {
    return decodedTarget.slice(1);
  }
  return decodedTarget.startsWith("xl/") ? decodedTarget : `xl/${decodedTarget}`;
}

function parseSharedStringsXml(sharedStringsXml: string): string[] {
  return findXmlBlocks(sharedStringsXml, "si").map((block) => {
    const textParts = [...block.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)]
      .map((match) => decodeXmlText(match[1]));
    return textParts.join("");
  });
}

function parseWorksheetXmlRows(worksheetXml: string, sharedStrings: string[]): string[][] {
  return findXmlBlocks(worksheetXml, "row").map((rowBlock) => {
    const cells: string[] = [];
    const cellPattern = /<c\b([^>]*)>([\s\S]*?)<\/c>/g;
    let match: RegExpExecArray | null;
    let nextColumn = 0;
    while ((match = cellPattern.exec(rowBlock)) !== null) {
      const attributes = match[1];
      const body = match[2];
      const cellRef = /\br="([A-Z]+)\d+"/.exec(attributes);
      const columnIndex = cellRef ? excelColumnToIndex(cellRef[1]) : nextColumn;
      cells[columnIndex] = readWorksheetCellValue(attributes, body, sharedStrings);
      nextColumn = columnIndex + 1;
    }
    return cells.map((cell) => cell ?? "");
  }).filter((row) => row.some(Boolean));
}

function readWorksheetCellValue(attributes: string, body: string, sharedStrings: string[]): string {
  const type = /\bt="([^"]+)"/.exec(attributes)?.[1] ?? "";
  if (type === "s") {
    const sharedStringIndex = Number(extractXmlTag(body, "v") ?? "");
    return Number.isFinite(sharedStringIndex) ? sharedStrings[sharedStringIndex] ?? "" : "";
  }
  if (type === "inlineStr") {
    return [...body.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)]
      .map((match) => decodeXmlText(match[1]))
      .join("")
      .trim();
  }
  return (extractXmlTag(body, "v") ?? "").trim();
}

export function compareTargetVersionsToPom(
  targetRows: TargetVersionRow[],
  pomText: string,
): TargetVersionComparisonRow[] {
  const pomVersions = parsePomDependencyVersions(pomText);
  return targetRows.map((row) => {
    const pomVersion = pomVersions.get(row.coordinate);
    if (!pomVersion) {
      return { ...row, pomVersion: null, versionSource: "not_found", status: "missing_in_pom" };
    }
    if (!pomVersion.version) {
      return { ...row, pomVersion: null, versionSource: pomVersion.source, status: "no_explicit_pom_version" };
    }
    return {
      ...row,
      pomVersion: pomVersion.version,
      versionSource: pomVersion.source,
      status: normalizeVersion(pomVersion.version) === normalizeVersion(row.targetVersion) ? "matches" : "different",
    };
  });
}

function parsePomDependencyVersions(pomText: string): Map<string, PomVersion> {
  const properties = parsePomProperties(pomText);
  const versions = new Map<string, PomVersion>();
  for (const block of findXmlBlocks(pomText, "dependency")) {
    const groupId = extractXmlTag(block, "groupId");
    const artifactId = extractXmlTag(block, "artifactId");
    if (!groupId || !artifactId) {
      continue;
    }
    const rawVersion = extractXmlTag(block, "version");
    const resolvedVersion = rawVersion ? resolvePomVersion(rawVersion, properties) : null;
    versions.set(`${groupId}:${artifactId}`, {
      version: resolvedVersion,
      source: rawVersion?.startsWith("${") ? "property" : "dependency",
    });
  }
  const parentBlock = findXmlBlocks(pomText, "parent")[0];
  if (parentBlock) {
    const groupId = extractXmlTag(parentBlock, "groupId");
    const artifactId = extractXmlTag(parentBlock, "artifactId");
    const version = extractXmlTag(parentBlock, "version");
    if (groupId && artifactId) {
      versions.set(`${groupId}:${artifactId}`, { version: version ?? null, source: "parent" });
    }
  }
  return versions;
}

function parsePomProperties(pomText: string): Map<string, string> {
  const properties = new Map<string, string>();
  const propertiesBlock = findXmlBlocks(pomText, "properties")[0] ?? "";
  const tagPattern = /<([\w.-]+)>\s*([^<]+?)\s*<\/\1>/g;
  let match: RegExpExecArray | null;
  while ((match = tagPattern.exec(propertiesBlock)) !== null) {
    properties.set(match[1], decodeXmlText(match[2].trim()));
  }
  return properties;
}

function resolvePomVersion(rawVersion: string, properties: Map<string, string>): string {
  const propertyMatch = /^\$\{([^}]+)\}$/.exec(rawVersion.trim());
  if (!propertyMatch) {
    return rawVersion.trim();
  }
  return properties.get(propertyMatch[1]) ?? rawVersion.trim();
}

function findXmlBlocks(xmlText: string, tagName: string): string[] {
  const pattern = new RegExp(`<${tagName}\\b[^>]*>[\\s\\S]*?<\\/${tagName}>`, "g");
  return xmlText.match(pattern) ?? [];
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
      if (char === "\r" && next === "\n") {
        index += 1;
      }
      row.push(cell.trim());
      if (row.some(Boolean)) {
        rows.push(row);
      }
      row = [];
      cell = "";
      continue;
    }
    cell += char;
  }
  row.push(cell.trim());
  if (row.some(Boolean)) {
    rows.push(row);
  }
  return rows;
}

function summarizeComparison(rows: TargetVersionComparisonRow[]) {
  return {
    matches: rows.filter((row) => row.status === "matches").length,
    different: rows.filter((row) => row.status === "different").length,
    missing: rows.filter((row) => row.status === "missing_in_pom").length,
    noExplicitVersion: rows.filter((row) => row.status === "no_explicit_pom_version").length,
  };
}

function formatComparisonStatus(status: ComparisonStatus): string {
  if (status === "matches") return "Matches target";
  if (status === "different") return "Different version";
  if (status === "missing_in_pom") return "Missing from POM";
  return "No explicit POM version";
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

function excelColumnToIndex(column: string): number {
  return column.split("").reduce((index, char) => {
    return index * 26 + char.charCodeAt(0) - 64;
  }, 0) - 1;
}

function decodeUtf8(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

function decodeXmlText(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
