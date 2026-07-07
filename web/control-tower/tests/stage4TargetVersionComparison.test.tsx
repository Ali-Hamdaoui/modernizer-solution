import { describe, expect, it } from "vitest";
import {
  compareTargetVersionsToPom,
  parseTargetVersionsCsv,
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

  it("rejects missing columns and invalid versions", () => {
    expect(() => parseTargetVersionsCsv("name,version\nlib,1.0.0")).toThrow(/must include/);
    expect(() => parseTargetVersionsCsv("groupId,artifactId,targetVersion\ncom.example,lib,1.0 <bad>")).toThrow(/invalid target version/);
  });

  it("rejects duplicate target rows with conflicting versions", () => {
    expect(() => parseTargetVersionsCsv([
      "groupId,artifactId,targetVersion",
      "com.example,lib,1.0.0",
      "com.example,lib,2.0.0",
    ].join("\n"))).toThrow(/duplicates com.example:lib/);
  });

  it("compares target rows with direct, property, managed, missing, and duplicate POM versions", () => {
    const targets: TargetVersionRow[] = [
      makeTarget("com.fasterxml.jackson.core", "jackson-databind", "2.17.2"),
      makeTarget("com.google.code.gson", "gson", "2.11.0"),
      makeTarget("org.junit.jupiter", "junit-jupiter", "5.11.4"),
      makeTarget("com.example", "missing", "1.0.0"),
      makeTarget("com.example", "duplicate", "2.0.0"),
    ];
    const pom = `
      <project>
        <properties>
          <jackson.version>2.17.2</jackson.version>
        </properties>
        <dependencyManagement>
          <dependencies>
            <dependency>
              <groupId>org.junit.jupiter</groupId>
              <artifactId>junit-jupiter</artifactId>
              <version>5.10.0</version>
            </dependency>
          </dependencies>
        </dependencyManagement>
        <dependencies>
          <dependency>
            <groupId>com.fasterxml.jackson.core</groupId>
            <artifactId>jackson-databind</artifactId>
            <version>\${jackson.version}</version>
          </dependency>
          <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.9.0</version>
          </dependency>
          <dependency>
            <groupId>com.example</groupId>
            <artifactId>duplicate</artifactId>
            <version>1.0.0</version>
          </dependency>
          <dependency>
            <groupId>com.example</groupId>
            <artifactId>duplicate</artifactId>
            <version>1.1.0</version>
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
      canApply: row.canApply,
    }))).toEqual([
      {
        coordinate: "com.fasterxml.jackson.core:jackson-databind",
        pomVersion: "2.17.2",
        versionSource: "property",
        status: "matches",
        canApply: false,
      },
      {
        coordinate: "com.google.code.gson:gson",
        pomVersion: "2.9.0",
        versionSource: "dependency",
        status: "different",
        canApply: true,
      },
      {
        coordinate: "org.junit.jupiter:junit-jupiter",
        pomVersion: "5.10.0",
        versionSource: "dependency_management",
        status: "different",
        canApply: true,
      },
      {
        coordinate: "com.example:missing",
        pomVersion: null,
        versionSource: "not_found",
        status: "missing_in_pom",
        canApply: false,
      },
      {
        coordinate: "com.example:duplicate",
        pomVersion: "1.1.0",
        versionSource: "dependency",
        status: "blocked",
        canApply: false,
      },
    ]);
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