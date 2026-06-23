import { describe, expect, it } from "vitest";
import {
  compareTargetVersionsToPom,
  parseTargetVersionRows,
  parseTargetVersionsCsv,
  parseTargetVersionsXlsx,
  type TargetVersionRow,
} from "../app/migrations/[jobId]/Stage4TargetVersionComparison";

describe("Stage 4 target version CSV comparison", () => {
  it("parses target versions from explicit group/artifact/version columns", () => {
    const rows = parseTargetVersionsCsv([
      "groupId,artifactId,targetVersion",
      "com.fasterxml.jackson.core,jackson-databind,2.17.2",
      "org.springframework.boot,spring-boot-starter-web,4.0.0",
    ].join("\n"));

    expect(rows).toEqual([
      {
        rowNumber: 2,
        coordinate: "com.fasterxml.jackson.core:jackson-databind",
        groupId: "com.fasterxml.jackson.core",
        artifactId: "jackson-databind",
        targetVersion: "2.17.2",
      },
      {
        rowNumber: 3,
        coordinate: "org.springframework.boot:spring-boot-starter-web",
        groupId: "org.springframework.boot",
        artifactId: "spring-boot-starter-web",
        targetVersion: "4.0.0",
      },
    ]);
  });

  it("parses target versions from a coordinate column", () => {
    const rows = parseTargetVersionsCsv([
      "coordinate",
      "org.junit.jupiter:junit-jupiter:5.11.4",
    ].join("\n"));

    expect(rows).toEqual([
      {
        rowNumber: 2,
        coordinate: "org.junit.jupiter:junit-jupiter",
        groupId: "org.junit.jupiter",
        artifactId: "junit-jupiter",
        targetVersion: "5.11.4",
      },
    ]);
  });

  it("parses target versions from Excel worksheet rows", () => {
    const rows = parseTargetVersionRows([
      ["groupId", "artifactId", "targetVersion"],
      ["org.springframework.boot", "spring-boot-starter-actuator", "4.0.0"],
      ["com.fasterxml.jackson.core", "jackson-annotations", "2.17.2"],
    ], "Excel");

    expect(rows).toEqual([
      {
        rowNumber: 2,
        coordinate: "org.springframework.boot:spring-boot-starter-actuator",
        groupId: "org.springframework.boot",
        artifactId: "spring-boot-starter-actuator",
        targetVersion: "4.0.0",
      },
      {
        rowNumber: 3,
        coordinate: "com.fasterxml.jackson.core:jackson-annotations",
        groupId: "com.fasterxml.jackson.core",
        artifactId: "jackson-annotations",
        targetVersion: "2.17.2",
      },
    ]);
  });

  it("parses target versions from the first .xlsx worksheet", async () => {
    const workbook = makeStoredZip({
      "xl/workbook.xml": [
        '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
        '<sheets><sheet name="Targets" sheetId="1" r:id="rId1"/></sheets>',
        "</workbook>",
      ].join(""),
      "xl/_rels/workbook.xml.rels": [
        "<Relationships>",
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>',
        "</Relationships>",
      ].join(""),
      "xl/sharedStrings.xml": [
        "<sst>",
        "<si><t>groupId</t></si>",
        "<si><t>artifactId</t></si>",
        "<si><t>targetVersion</t></si>",
        "<si><t>org.springframework.boot</t></si>",
        "<si><t>spring-boot-starter-web</t></si>",
        "<si><t>4.0.0</t></si>",
        "</sst>",
      ].join(""),
      "xl/worksheets/sheet1.xml": [
        "<worksheet><sheetData>",
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>',
        '<row r="2"><c r="A2" t="s"><v>3</v></c><c r="B2" t="s"><v>4</v></c><c r="C2" t="s"><v>5</v></c></row>',
        "</sheetData></worksheet>",
      ].join(""),
    });

    const rows = await parseTargetVersionsXlsx(workbook);

    expect(rows).toEqual([
      {
        rowNumber: 2,
        coordinate: "org.springframework.boot:spring-boot-starter-web",
        groupId: "org.springframework.boot",
        artifactId: "spring-boot-starter-web",
        targetVersion: "4.0.0",
      },
    ]);
  });

  it("compares target rows with Stage 4 POM versions", () => {
    const targets: TargetVersionRow[] = [
      makeTarget("com.fasterxml.jackson.core", "jackson-databind", "2.17.2"),
      makeTarget("org.springframework.boot", "spring-boot-starter-web", "4.0.0"),
      makeTarget("org.junit.jupiter", "junit-jupiter", "5.11.4"),
      makeTarget("com.example", "not-present", "1.0.0"),
    ];
    const pom = `
      <project>
        <properties>
          <jackson.version>2.17.2</jackson.version>
        </properties>
        <dependencies>
          <dependency>
            <groupId>com.fasterxml.jackson.core</groupId>
            <artifactId>jackson-databind</artifactId>
            <version>\${jackson.version}</version>
          </dependency>
          <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
            <version>3.5.0</version>
          </dependency>
          <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter</artifactId>
          </dependency>
        </dependencies>
      </project>
    `;

    const comparison = compareTargetVersionsToPom(targets, pom);

    expect(comparison.map((row) => ({
      coordinate: row.coordinate,
      pomVersion: row.pomVersion,
      versionSource: row.versionSource,
      status: row.status,
    }))).toEqual([
      {
        coordinate: "com.fasterxml.jackson.core:jackson-databind",
        pomVersion: "2.17.2",
        versionSource: "property",
        status: "matches",
      },
      {
        coordinate: "org.springframework.boot:spring-boot-starter-web",
        pomVersion: "3.5.0",
        versionSource: "dependency",
        status: "different",
      },
      {
        coordinate: "org.junit.jupiter:junit-jupiter",
        pomVersion: null,
        versionSource: "dependency",
        status: "no_explicit_pom_version",
      },
      {
        coordinate: "com.example:not-present",
        pomVersion: null,
        versionSource: "not_found",
        status: "missing_in_pom",
      },
    ]);
  });

  it("throws when a CSV row is missing required dependency coordinates", () => {
    expect(() => parseTargetVersionsCsv([
      "groupId,artifactId,targetVersion",
      "com.example,,1.0.0",
    ].join("\n"))).toThrow("CSV row 2 must include groupId, artifactId, and target version.");
  });

  it("reports Excel row numbers when spreadsheet rows are incomplete", () => {
    expect(() => parseTargetVersionRows([
      ["groupId", "artifactId", "targetVersion"],
      ["com.example", "", "1.0.0"],
    ], "Excel")).toThrow("Excel row 2 must include groupId, artifactId, and target version.");
  });
});

function makeTarget(groupId: string, artifactId: string, targetVersion: string): TargetVersionRow {
  return {
    rowNumber: 1,
    coordinate: `${groupId}:${artifactId}`,
    groupId,
    artifactId,
    targetVersion,
  };
}

function makeStoredZip(entries: Record<string, string>): ArrayBuffer {
  const encoder = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;

  for (const [name, content] of Object.entries(entries)) {
    const fileName = encoder.encode(name);
    const data = encoder.encode(content);
    const localHeader = new Uint8Array(30 + fileName.length);
    const localView = new DataView(localHeader.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(8, 0, true);
    localView.setUint32(18, data.length, true);
    localView.setUint32(22, data.length, true);
    localView.setUint16(26, fileName.length, true);
    localHeader.set(fileName, 30);
    localParts.push(localHeader, data);

    const centralHeader = new Uint8Array(46 + fileName.length);
    const centralView = new DataView(centralHeader.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(10, 0, true);
    centralView.setUint32(20, data.length, true);
    centralView.setUint32(24, data.length, true);
    centralView.setUint16(28, fileName.length, true);
    centralView.setUint32(42, offset, true);
    centralHeader.set(fileName, 46);
    centralParts.push(centralHeader);

    offset += localHeader.length + data.length;
  }

  const centralOffset = offset;
  const centralSize = centralParts.reduce((size, part) => size + part.length, 0);
  const endHeader = new Uint8Array(22);
  const endView = new DataView(endHeader.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(8, centralParts.length, true);
  endView.setUint16(10, centralParts.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, centralOffset, true);

  const bytes = concatBytes([...localParts, ...centralParts, endHeader]);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

function concatBytes(parts: Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((size, part) => size + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}
