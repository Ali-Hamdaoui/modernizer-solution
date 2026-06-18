"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";

import {
  createV2JobPayload,
  DEFAULT_V2_STAGE_CONTINUATION_POLICY,
  type V2StageContinuationPolicy,
} from "../../../lib/controlTowerApi";

// ── Types ──────────────────────────────────────────────────────────

interface ParsedEnvResult {
  parsed: {
    run_name: string;
    legacy_app_path: string;
    output_parent_path: string;
    ai_hub_path: string;
    java_homes: { java11: string; java17: string; java21: string };
    maven_cmd: string;
    migration_flags: { proof_level: string; skip_endpoint_smoke: boolean | null };
    stage_continuation_policy: string;
  };
  ignored_keys: string[];
  blocked_keys: string[];
}

interface SetupResponse {
  setup_id: string;
  run_name: string;
  legacy_app_path: string;
  output_parent_path: string;
  ai_hub_path: string;
  java_homes: { java11: string; java17: string; java21: string };
  maven_cmd: string;
  proof_level: string;
  skip_endpoint_smoke: boolean;
  migration_flags: Record<string, unknown>;
  setup_checksum: string;
  created_at: string;
}

interface PreflightResponse {
  preflight_id: string;
  setup_id: string;
  all_ready: boolean;
  azure_model_ready?: boolean;
  azure_model_failure_reason?: string;
  azure_model_response_snippet?: string;
  azure_model_checked_at?: string;
  readiness: Record<string, boolean>;
  warnings: string[];
  errors: string[];
  checked_at: string;
}

interface ReadinessResponse {
  ready: boolean;
  setup_checksum: string;
  preflight_checksum_match: boolean;
  gates: Record<string, boolean>;
}

interface SettingsResponse {
  azure: {
    profile_id: string;
    provider: string;
    endpoint: { env_ref: string; configured: boolean };
    roles: Record<string, { env_ref: string; configured: boolean; deployment_label: string; enabled: boolean }>;
  };
  local_mode: {
    enabled: boolean;
    allowed_source_roots: string[];
    allowed_output_roots: string[];
  };
}

function sanitizeSmokeSnippet(value: string): string {
  return value
    .replace(/sk-[A-Za-z0-9_-]+/g, "[redacted-token]")
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer [redacted-token]")
    .slice(0, 240);
}

export function getStartReadinessCopy(
  readiness: ReadinessResponse | null,
): { label: string; ready: boolean } {
  const ready = readiness?.ready === true && readiness?.preflight_checksum_match === true;
  return {
    label: ready ? "READY" : "NOT READY",
    ready,
  };
}

export function getAzureSmokeCopy(
  preflight: PreflightResponse | null,
): { label: string; checkedAt: string; failureReason: string; snippet: string } {
  if (!preflight || preflight.azure_model_ready === undefined) {
    return {
      label: "Azure model smoke: not run",
      checkedAt: "",
      failureReason: "",
      snippet: "",
    };
  }

  if (preflight.azure_model_ready) {
    return {
      label: preflight.azure_model_checked_at ? "Azure model smoke: PASS" : "Azure model smoke: PASS (skipped)",
      checkedAt: preflight.checked_at,
      failureReason: "",
      snippet: "",
    };
  }

  const reason = preflight.azure_model_failure_reason || "invalid_response";
  const snippet = preflight.azure_model_response_snippet
    ? sanitizeSmokeSnippet(preflight.azure_model_response_snippet)
    : "";
  const suffix = snippet ? ` — ${snippet}` : "";
  return {
    label: `Azure model smoke: FAIL — ${reason}${suffix}`,
    checkedAt: preflight.checked_at,
    failureReason: reason,
    snippet,
  };
}

// ── API helpers ────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

function mutationHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Origin: "http://127.0.0.1:3000",
    "X-Control-Tower-Client": "control-tower-frontend",
  };
}

async function parseEnv(envBlock: string): Promise<ParsedEnvResult> {
  const res = await fetch(`${API_BASE}/v1/migration-setups/parse-env`, {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify({ env_block: envBlock }),
  });
  if (!res.ok) throw new Error(`Parse failed: ${res.status}`);
  return res.json();
}

async function fetchSettings(): Promise<SettingsResponse> {
  const res = await fetch(`${API_BASE}/v1/settings/ai`, {
    headers: { Host: "127.0.0.1:8000" },
  });
  if (!res.ok) throw new Error(`Settings failed: ${res.status}`);
  return res.json();
}

async function createSetup(payload: Record<string, unknown>): Promise<SetupResponse> {
  const res = await fetch(`${API_BASE}/v1/migration-setups`, {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Create setup failed: ${res.status}`);
  return res.json();
}

async function runPreflight(setupId: string): Promise<PreflightResponse> {
  const res = await fetch(`${API_BASE}/v1/migration-setups/preflight`, {
    method: "POST",
    headers: mutationHeaders(),
    body: JSON.stringify({ setup_id: setupId }),
  });
  if (!res.ok) throw new Error(`Preflight failed: ${res.status}`);
  return res.json();
}

async function fetchReadiness(setupId: string): Promise<ReadinessResponse> {
  const res = await fetch(`${API_BASE}/v1/migration-setups/${setupId}/readiness`, {
    headers: { Host: "127.0.0.1:8000" },
  });
  if (!res.ok) throw new Error(`Readiness failed: ${res.status}`);
  return res.json();
}

// ── Form state ─────────────────────────────────────────────────────

interface FormFields {
  envBlock: string;
  run_name: string;
  legacy_app_path: string;
  output_parent_path: string;
  ai_hub_path: string;
  java11_home: string;
  java17_home: string;
  java21_home: string;
  maven_cmd: string;
  proof_level: string;
  skip_endpoint_smoke: boolean;
  stageContinuationPolicy: V2StageContinuationPolicy;
}

const EMPTY_FIELDS: FormFields = {
  envBlock: "",
  run_name: "",
  legacy_app_path: "",
  output_parent_path: "",
  ai_hub_path: "",
  java11_home: "",
  java17_home: "",
  java21_home: "",
  maven_cmd: "",
  proof_level: "build_test_verified",
  skip_endpoint_smoke: false,
  stageContinuationPolicy: DEFAULT_V2_STAGE_CONTINUATION_POLICY,
};

// ── Component ──────────────────────────────────────────────────────

export function NewMigrationForm() {
  const router = useRouter();
  const [fields, setFields] = useState<FormFields>(EMPTY_FIELDS);
  const [parseResult, setParseResult] = useState<ParsedEnvResult | null>(null);
  const [setupResult, setSetupResult] = useState<SetupResponse | null>(null);
  const [preflight, setPreflight] = useState<PreflightResponse | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [azureSettings, setAzureSettings] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);

  const updateField = useCallback(
    (key: keyof FormFields, value: string | boolean) => {
      setFields((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const handleParseEnv = useCallback(async () => {
    if (!fields.envBlock.trim()) return;
    setLoading("Parsing env block...");
    setError(null);
    try {
      const result = await parseEnv(fields.envBlock);
      setParseResult(result);
      if (result.blocked_keys.length > 0) {
        setError(`Blocked keys detected: ${result.blocked_keys.join(", ")}. These were not parsed.`);
      }
      // Auto-fill fields from parsed result
      const p = result.parsed;
      setFields((prev) => ({
        ...prev,
        run_name: p.run_name || prev.run_name,
        legacy_app_path: p.legacy_app_path || prev.legacy_app_path,
        output_parent_path: p.output_parent_path || prev.output_parent_path,
        ai_hub_path: p.ai_hub_path || prev.ai_hub_path,
        java11_home: p.java_homes.java11 || prev.java11_home,
        java17_home: p.java_homes.java17 || prev.java17_home,
        java21_home: p.java_homes.java21 || prev.java21_home,
        maven_cmd: p.maven_cmd || prev.maven_cmd,
        proof_level: p.migration_flags.proof_level || prev.proof_level,
        skip_endpoint_smoke: p.migration_flags.skip_endpoint_smoke ?? prev.skip_endpoint_smoke,
        stageContinuationPolicy: (p.stage_continuation_policy as V2StageContinuationPolicy) || prev.stageContinuationPolicy,
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Parse failed");
    } finally {
      setLoading(null);
    }
  }, [fields.envBlock]);

  const handleSaveSetup = useCallback(async () => {
    setLoading("Saving setup...");
    setError(null);
    try {
      const result = await createSetup({
        run_name: fields.run_name,
        legacy_app_path: fields.legacy_app_path,
        output_parent_path: fields.output_parent_path,
        ai_hub_path: fields.ai_hub_path,
        java11_home: fields.java11_home,
        java17_home: fields.java17_home,
        java21_home: fields.java21_home,
        maven_cmd: fields.maven_cmd,
        proof_level: fields.proof_level,
        skip_endpoint_smoke: fields.skip_endpoint_smoke,
      });
      setSetupResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setLoading(null);
    }
  }, [fields]);

  const handleRunPreflight = useCallback(async () => {
    if (!setupResult?.setup_id) return;
    setLoading("Running preflight...");
    setError(null);
    try {
      const result = await runPreflight(setupResult.setup_id);
      setPreflight(result);
      // Also fetch readiness
      const readinessResult = await fetchReadiness(setupResult.setup_id);
      setReadiness(readinessResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Preflight failed");
    } finally {
      setLoading(null);
    }
  }, [setupResult?.setup_id]);

  const handleLoadSettings = useCallback(async () => {
    setLoading("Loading settings...");
    setError(null);
    try {
      const result = await fetchSettings();
      setAzureSettings(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Settings load failed");
    } finally {
      setLoading(null);
    }
  }, []);

  // ── Render ──────────────────────────────────────────────────────

  const startState = getStartReadinessCopy(readiness);
  const azureSmokeCopy = getAzureSmokeCopy(preflight);
  const startEnabled = startState.ready;

  return (
    <div className="stack" style={{ maxWidth: "800px" }}>
      {/* Env Parser Section */}
      <fieldset>
        <legend>PowerShell Env Block (optional)</legend>
        <p className="meta">
          Paste your old PowerShell env block to auto-fill fields below.
          Azure secrets are blocked and will not be parsed.
        </p>
        <textarea
          rows={6}
          style={{ width: "100%", fontFamily: "monospace" }}
          placeholder={`$env:JAVA11_HOME = "C:\\Tools\\jdk-11"\n$env:MAVEN_CMD = "C:\\Tools\\mvn.cmd"\n$legacy = "C:\\work\\apps\\my-app"\n...`}
          value={fields.envBlock}
          onChange={(e) => updateField("envBlock", e.target.value)}
        />
        <button onClick={handleParseEnv} disabled={!!loading || !fields.envBlock.trim()}>
          {loading === "Parsing env block..." ? "Parsing..." : "Parse Env Block"}
        </button>
        {parseResult && (
          <div className="info-box">
            <p>Parsed: {parseResult.parsed.run_name || "(no run name)"}</p>
            {parseResult.ignored_keys.length > 0 && (
              <p className="meta">Ignored keys: {parseResult.ignored_keys.join(", ")}</p>
            )}
            {parseResult.blocked_keys.length > 0 && (
              <p className="warning">Blocked keys: {parseResult.blocked_keys.join(", ")}</p>
            )}
          </div>
        )}
      </fieldset>

      {/* Manual Fields Section */}
      <fieldset>
        <legend>Migration Setup</legend>

        <div className="field-row">
          <label>
            Run Name <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.run_name}
            onChange={(e) => updateField("run_name", e.target.value)}
            placeholder="my-app-v2"
          />
        </div>

        <div className="field-row">
          <label>
            Legacy App Path <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.legacy_app_path}
            onChange={(e) => updateField("legacy_app_path", e.target.value)}
            placeholder="C:\work\apps\legacy-service"
          />
        </div>

        <div className="field-row">
          <label>
            Output Parent Path <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.output_parent_path}
            onChange={(e) => updateField("output_parent_path", e.target.value)}
            placeholder="C:\work\modernized"
          />
        </div>

        <div className="field-row">
          <label>
            AI Hub Path <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.ai_hub_path}
            onChange={(e) => updateField("ai_hub_path", e.target.value)}
            placeholder="C:\Users\me\modernizer-solution-ai-hub"
          />
        </div>

        <div className="field-row">
          <label>
            JAVA11_HOME <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.java11_home}
            onChange={(e) => updateField("java11_home", e.target.value)}
            placeholder="C:\Tools\jdk-11"
          />
        </div>

        <div className="field-row">
          <label>
            JAVA17_HOME <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.java17_home}
            onChange={(e) => updateField("java17_home", e.target.value)}
            placeholder="C:\Tools\jdk-17"
          />
        </div>

        <div className="field-row">
          <label>
            JAVA21_HOME <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.java21_home}
            onChange={(e) => updateField("java21_home", e.target.value)}
            placeholder="C:\Tools\jdk-21"
          />
        </div>

        <div className="field-row">
          <label>
            Maven Command <strong>*</strong>
          </label>
          <input
            type="text"
            value={fields.maven_cmd}
            onChange={(e) => updateField("maven_cmd", e.target.value)}
            placeholder="C:\Tools\apache-maven-3.9.15\bin\mvn.cmd"
          />
        </div>

        <div className="field-row">
          <label>Proof Level</label>
          <select
            value={fields.proof_level}
            onChange={(e) => updateField("proof_level", e.target.value)}
          >
            <option value="analyzed">Analyzed</option>
            <option value="build_test_verified">Build & Test Verified</option>
            <option value="runtime_verified">Runtime Verified</option>
          </select>
        </div>

        <div className="field-row">
          <label>
            <input
              type="checkbox"
              checked={fields.skip_endpoint_smoke}
              onChange={(e) => updateField("skip_endpoint_smoke", e.target.checked)}
            />{" "}
            Skip Endpoint Smoke Test
          </label>
        </div>
      </fieldset>

      {/* Actions */}
      <div className="button-row">
        <button onClick={handleSaveSetup} disabled={!!loading || !fields.run_name || !fields.legacy_app_path}>
          {loading === "Saving setup..." ? "Saving..." : "Save Setup"}
        </button>

        <button onClick={handleLoadSettings} disabled={!!loading}>
          {loading === "Loading settings..." ? "Loading..." : "Check Azure Settings"}
        </button>
      </div>

      {/* Error */}
      {error && <div className="error-box">{error}</div>}

      {/* Azure Settings */}
      {azureSettings && (
        <fieldset>
          <legend>Azure Settings</legend>
          <p>
            Provider: <code>{azureSettings.azure.provider}</code>
          </p>
          <p>
            Endpoint:{" "}
            <code>
              {azureSettings.azure.endpoint.configured ? "✓ Configured" : "✗ Not Configured"}
            </code>
          </p>
          <p className="meta">
            Endpoint configured is not smoke evidence. Run preflight to get a PASS or FAIL verdict.
          </p>
        </fieldset>
      )}

      {/* Preflight */}
      {setupResult && (
        <div className="button-row">
          <button onClick={handleRunPreflight} disabled={!!loading}>
            {loading === "Running preflight..." ? "Running..." : "Run Preflight"}
          </button>
        </div>
      )}

      {/* Preflight Results */}
      {preflight && (
        <fieldset>
          <legend>Preflight Results</legend>
          <p>
            All Ready:{" "}
            <strong className={preflight.all_ready ? "text-green" : "text-red"}>
              {preflight.all_ready ? "YES" : "NO"}
            </strong>
          </p>
          {Object.entries(preflight.readiness || {}).map(([key, val]) => (
            <p key={key} className="check-row">
              {key}: {val ? "✓" : "✗"}
            </p>
          ))}
          {preflight.warnings.length > 0 && (
            <div className="warning-box">
              <p>Warnings:</p>
              <ul>
                {preflight.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {preflight.errors.length > 0 && (
            <div className="error-box">
              <p>Errors:</p>
              <ul>
                {preflight.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="info-box">
            <p>{azureSmokeCopy.label}</p>
            <p className="meta">
              Smoke checked at: <code>{azureSmokeCopy.checkedAt || preflight.checked_at}</code>
            </p>
            {azureSmokeCopy.failureReason && (
              <p className="warning">
                Failure reason: <code>{azureSmokeCopy.failureReason}</code>
              </p>
            )}
            {azureSmokeCopy.snippet && (
              <p className="meta">
                Evidence: <code>{azureSmokeCopy.snippet}</code>
              </p>
            )}
          </div>
        </fieldset>
      )}

      {/* Readiness / Start Button */}
      {readiness && (
        <fieldset>
          <legend>Start Readiness</legend>
          <p>
            Checksum Match:{" "}
            {readiness.preflight_checksum_match ? "✓" : "✗ (re-run preflight)"}
          </p>
          <p>
            Ready:{" "}
            <strong className={startEnabled ? "text-green" : "text-red"}>
              {startState.label}
            </strong>
          </p>
          <button
            className="start-button"
            disabled={!startEnabled}
            title={
              !readiness.preflight_checksum_match
                ? "Preflight is stale — run preflight again"
                : !readiness.ready
                  ? "Fix errors above"
                  : "Start migration"
            }
            onClick={async () => {
              if (!setupResult) return;
              setLoading("Starting migration...");
              setError(null);
              try {
                // 1. Create V2 job
                const jobPayload = createV2JobPayload(
                  setupResult.setup_id,
                  fields.stageContinuationPolicy || DEFAULT_V2_STAGE_CONTINUATION_POLICY,
                );
                const jobRes = await fetch(`${API_BASE}/v1/v2/migration-jobs`, {
                  method: "POST",
                  headers: mutationHeaders(),
                  body: JSON.stringify(jobPayload),
                });
                if (!jobRes.ok) throw new Error(`Job creation failed: ${jobRes.status}`);
                const jobData = await jobRes.json();

                // 2. Start Stage 1
                const stageRes = await fetch(`${API_BASE}/v1/v2/migration-jobs/start-stage1`, {
                  method: "POST",
                  headers: mutationHeaders(),
                  body: JSON.stringify({
                    job_id: jobData.job_id,
                    setup_id: setupResult.setup_id,
                  }),
                });
                if (!stageRes.ok) throw new Error(`Stage 1 start failed: ${stageRes.status}`);

                // 3. Navigate to cockpit
                router.push(`/migrations/${jobData.job_id}`);
              } catch (e) {
                setError(e instanceof Error ? e.message : "Start failed");
              } finally {
                setLoading(null);
              }
            }}
          >
            {startEnabled ? "Start Migration" : "Cannot Start"}
          </button>
        </fieldset>
      )}

      <style>{`
        .stack { display: flex; flex-direction: column; gap: 1rem; padding: 1rem; }
        .meta { font-size: 0.85rem; color: #666; }
        fieldset { border: 1px solid #ccc; border-radius: 6px; padding: 1rem; }
        legend { font-weight: 600; padding: 0 0.5rem; }
        .field-row { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.75rem; }
        .field-row label { font-size: 0.9rem; font-weight: 500; }
        .field-row input, .field-row select { padding: 0.5rem; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem; }
        .field-row input[type="checkbox"] { width: auto; }
        .button-row { display: flex; gap: 0.5rem; }
        button { padding: 0.5rem 1rem; border: 1px solid #888; border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
        .start-button { background: #0066cc; color: white; border-color: #0055aa; font-weight: 600; padding: 0.75rem 1.5rem; }
        .error-box { border: 1px solid #cc0000; background: #fff0f0; padding: 0.75rem; border-radius: 4px; }
        .warning-box { border: 1px solid #ccaa00; background: #fffff0; padding: 0.75rem; border-radius: 4px; }
        .info-box { border: 1px solid #0066cc; background: #f0f6ff; padding: 0.75rem; border-radius: 4px; }
        .text-green { color: #008800; }
        .text-red { color: #cc0000; }
        .check-row { font-family: monospace; font-size: 0.85rem; margin: 0.15rem 0; }
        .warning { color: #886600; }
      `}</style>
    </div>
  );
}
