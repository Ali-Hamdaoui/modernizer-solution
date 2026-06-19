"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

interface ParsedEnvResult {
  parsed: {
    run_name: string;
    legacy_app_path: string;
    output_parent_path: string;
    ai_hub_path: string;
    java_homes: { java11: string; java17: string; java21: string };
    maven_cmd: string;
    migration_flags: { proof_level: string; skip_endpoint_smoke: boolean | null };
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
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

function mutationHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Origin: "http://127.0.0.1:3000",
    "X-Control-Tower-Client": "control-tower-frontend",
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
  const suffix = snippet ? ` - ${snippet}` : "";
  return {
    label: `Azure model smoke: FAIL - ${reason}${suffix}`,
    checkedAt: preflight.checked_at,
    failureReason: reason,
    snippet,
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

  const updateField = useCallback((key: keyof FormFields, value: string | boolean) => {
    setFields((prev) => ({ ...prev, [key]: value }));
  }, []);

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
      setReadiness(await fetchReadiness(setupResult.setup_id));
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
      setAzureSettings(await fetchSettings());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Settings load failed");
    } finally {
      setLoading(null);
    }
  }, []);

  const startState = getStartReadinessCopy(readiness);
  const azureSmokeCopy = getAzureSmokeCopy(preflight);
  const startEnabled = startState.ready;

  return (
    <div className="migration-setup-grid">
      <fieldset className="setup-card">
        <legend>1. Env Block</legend>
        <div className="section-body">
          <p className="meta">
            Paste your PowerShell env block to auto-fill local paths. Azure
            secrets are blocked.
          </p>
          <textarea
            rows={6}
            className="env-textarea"
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
        </div>
      </fieldset>

      <fieldset className="setup-card">
        <legend>2. Project Paths</legend>
        <div className="section-body">
          <TextField label="Run Name" required value={fields.run_name} onChange={(value) => updateField("run_name", value)} placeholder="my-app-v2" />
          <TextField label="Legacy App Path" required value={fields.legacy_app_path} onChange={(value) => updateField("legacy_app_path", value)} placeholder="C:\\work\\apps\\legacy-service" />
          <TextField label="Output Parent Path" required value={fields.output_parent_path} onChange={(value) => updateField("output_parent_path", value)} placeholder="C:\\work\\modernized" />
          <TextField label="AI Hub Path" required value={fields.ai_hub_path} onChange={(value) => updateField("ai_hub_path", value)} placeholder="C:\\Users\\me\\modernizer-solution-ai-hub" />
        </div>
      </fieldset>

      <fieldset className="setup-card">
        <legend>3. Toolchain and Proof</legend>
        <div className="section-body">
          <TextField label="JAVA11_HOME" required value={fields.java11_home} onChange={(value) => updateField("java11_home", value)} placeholder="C:\\Tools\\jdk-11" />
          <TextField label="JAVA17_HOME" required value={fields.java17_home} onChange={(value) => updateField("java17_home", value)} placeholder="C:\\Tools\\jdk-17" />
          <TextField label="JAVA21_HOME" required value={fields.java21_home} onChange={(value) => updateField("java21_home", value)} placeholder="C:\\Tools\\jdk-21" />
          <TextField label="Maven Command" required value={fields.maven_cmd} onChange={(value) => updateField("maven_cmd", value)} placeholder="C:\\Tools\\apache-maven-3.9.15\\bin\\mvn.cmd" />
          <div className="field-row">
            <label>Proof Level</label>
            <select value={fields.proof_level} onChange={(e) => updateField("proof_level", e.target.value)}>
              <option value="analyzed">Analyzed</option>
              <option value="build_test_verified">Build & Test Verified</option>
              <option value="runtime_verified">Runtime Verified</option>
            </select>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={fields.skip_endpoint_smoke}
              onChange={(e) => updateField("skip_endpoint_smoke", e.target.checked)}
            />
            Skip Endpoint Smoke Test
          </label>
        </div>
      </fieldset>

      <fieldset className="setup-card">
        <legend>4. Setup and Azure</legend>
        <div className="section-body">
          <div className="button-row">
            <button onClick={handleSaveSetup} disabled={!!loading || !fields.run_name || !fields.legacy_app_path}>
              {loading === "Saving setup..." ? "Saving..." : "Save Setup"}
            </button>
            <button onClick={handleLoadSettings} disabled={!!loading}>
              {loading === "Loading settings..." ? "Loading..." : "Check Azure Settings"}
            </button>
            {setupResult && (
              <button onClick={handleRunPreflight} disabled={!!loading}>
                {loading === "Running preflight..." ? "Running..." : "Run Preflight"}
              </button>
            )}
          </div>
          {error && <div className="error-box">{error}</div>}
          {setupResult && (
            <div className="info-box">
              <p>Setup saved: <code>{setupResult.run_name}</code></p>
              <p className="meta">Setup ID: <code>{setupResult.setup_id}</code></p>
            </div>
          )}
          {azureSettings ? (
            <div className="info-box">
              <p>Provider: <code>{azureSettings.azure.provider}</code></p>
              <p>Endpoint: <code>{azureSettings.azure.endpoint.configured ? "Configured" : "Not Configured"}</code></p>
              <p className="meta">Endpoint configured is not smoke evidence. Run preflight to get a PASS or FAIL verdict.</p>
            </div>
          ) : (
            <p className="empty-state">Azure settings have not been checked.</p>
          )}
        </div>
      </fieldset>

      <fieldset className="setup-card">
        <legend>5. Preflight Results</legend>
        <div className="section-body">
          {preflight ? (
            <>
              <p>All Ready: <strong className={preflight.all_ready ? "text-green" : "text-red"}>{preflight.all_ready ? "YES" : "NO"}</strong></p>
              <div className="checks-list">
                {Object.entries(preflight.readiness || {}).map(([key, val]) => (
                  <p key={key} className="check-row">{key}: {val ? "PASS" : "FAIL"}</p>
                ))}
              </div>
              {preflight.warnings.length > 0 && (
                <div className="warning-box">
                  <p>Warnings:</p>
                  <ul>{preflight.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                </div>
              )}
              {preflight.errors.length > 0 && (
                <div className="error-box">
                  <p>Errors:</p>
                  <ul>{preflight.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              )}
              <div className="info-box">
                <p>{azureSmokeCopy.label}</p>
                <p className="meta">Smoke checked at: <code>{azureSmokeCopy.checkedAt || preflight.checked_at}</code></p>
                {azureSmokeCopy.failureReason && <p className="warning">Failure reason: <code>{azureSmokeCopy.failureReason}</code></p>}
                {azureSmokeCopy.snippet && <p className="meta">Evidence: <code>{azureSmokeCopy.snippet}</code></p>}
              </div>
            </>
          ) : (
            <p className="empty-state">Save setup, then run preflight to see readiness gates.</p>
          )}
        </div>
      </fieldset>

      <fieldset className="setup-card">
        <legend>6. Start Readiness</legend>
        <div className="section-body">
          {readiness ? (
            <>
              <p>Checksum Match: {readiness.preflight_checksum_match ? "YES" : "NO (re-run preflight)"}</p>
              <p>Ready: <strong className={startEnabled ? "text-green" : "text-red"}>{startState.label}</strong></p>
              <button
                className="start-button"
                disabled={!startEnabled}
                title={
                  !readiness.preflight_checksum_match
                    ? "Preflight is stale - run preflight again"
                    : !readiness.ready
                      ? "Fix errors above"
                      : "Start migration"
                }
                onClick={async () => {
                  if (!setupResult) return;
                  setLoading("Starting migration...");
                  setError(null);
                  try {
                    const jobRes = await fetch(`${API_BASE}/v1/v2/migration-jobs`, {
                      method: "POST",
                      headers: mutationHeaders(),
                      body: JSON.stringify({ setup_id: setupResult.setup_id }),
                    });
                    if (!jobRes.ok) throw new Error(`Job creation failed: ${jobRes.status}`);
                    const jobData = await jobRes.json();

                    const stageRes = await fetch(`${API_BASE}/v1/v2/migration-jobs/start-stage1`, {
                      method: "POST",
                      headers: mutationHeaders(),
                      body: JSON.stringify({
                        job_id: jobData.job_id,
                        setup_id: setupResult.setup_id,
                      }),
                    });
                    if (!stageRes.ok) throw new Error(`Stage 1 start failed: ${stageRes.status}`);

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
            </>
          ) : (
            <p className="empty-state">Start is available after a passing readiness check.</p>
          )}
        </div>
      </fieldset>

      <style>{`
        .migration-setup-grid {
          display: grid;
          gap: 12px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
          height: 100%;
          min-height: 0;
        }
        .setup-card {
          background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(249, 252, 251, 0.96));
          border: 1px solid #d8dfdc;
          border-radius: 16px;
          box-shadow: 0 18px 44px rgba(23, 32, 29, 0.08);
          display: flex;
          flex-direction: column;
          min-height: 0;
          overflow: hidden;
          padding: 12px;
        }
        legend {
          font-size: 0.9rem;
          font-weight: 800;
          padding: 0 0.35rem;
        }
        .section-body {
          display: flex;
          flex: 1;
          flex-direction: column;
          gap: 10px;
          min-height: 0;
          overflow: auto;
          padding-right: 4px;
        }
        .meta,
        .empty-state {
          color: #66736d;
          font-size: 0.86rem;
          line-height: 1.35;
        }
        .empty-state {
          border: 1px dashed #c7d0cc;
          border-radius: 10px;
          padding: 10px;
        }
        .env-textarea {
          flex: 1;
          min-height: 132px;
          resize: vertical;
        }
        textarea,
        input,
        select {
          background: #fff;
          border: 1px solid #c7d0cc;
          border-radius: 10px;
          color: #17201d;
          min-width: 0;
          padding: 10px 12px;
          width: 100%;
        }
        textarea,
        code,
        .check-row {
          font-family: Consolas, "Cascadia Mono", monospace;
        }
        .field-row {
          display: flex;
          flex-direction: column;
          gap: 5px;
        }
        .field-row label,
        .checkbox-row {
          color: #2d3a36;
          font-size: 0.86rem;
          font-weight: 700;
        }
        .checkbox-row {
          align-items: center;
          display: flex;
          gap: 8px;
        }
        .checkbox-row input {
          width: auto;
        }
        .button-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        button {
          background: linear-gradient(135deg, #0f766e, #115e59);
          border: 0;
          border-radius: 10px;
          box-shadow: 0 10px 20px rgba(15, 118, 110, 0.18);
          color: #fff;
          cursor: pointer;
          font-size: 0.88rem;
          font-weight: 800;
          min-height: 40px;
          padding: 8px 14px;
        }
        button:disabled {
          box-shadow: none;
          cursor: not-allowed;
          opacity: 0.5;
        }
        .start-button {
          width: fit-content;
        }
        .error-box,
        .warning-box,
        .info-box {
          border-radius: 10px;
          line-height: 1.35;
          overflow-wrap: anywhere;
          padding: 10px;
        }
        .error-box {
          background: #fff5f5;
          border: 1px solid #d92d20;
        }
        .warning-box {
          background: #fffbeb;
          border: 1px solid #d6a100;
        }
        .info-box {
          background: #f0fdfa;
          border: 1px solid #77d7c7;
        }
        .text-green {
          color: #087443;
        }
        .text-red {
          color: #b42318;
        }
        .checks-list {
          display: grid;
          gap: 4px;
        }
        .check-row {
          font-size: 0.8rem;
          margin: 0;
          overflow-wrap: anywhere;
        }
        .warning {
          color: #8a6100;
        }
        ul {
          margin: 6px 0 0;
          padding-left: 18px;
        }
        @media (max-width: 1100px) {
          .migration-setup-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            grid-template-rows: repeat(3, minmax(0, 1fr));
          }
        }
        @media (max-width: 760px) {
          .migration-setup-grid {
            grid-template-columns: 1fr;
            grid-template-rows: repeat(6, minmax(0, 1fr));
            height: auto;
          }
          .setup-card {
            min-height: 320px;
          }
        }
      `}</style>
    </div>
  );
}

function TextField({
  label,
  onChange,
  placeholder,
  required = false,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  placeholder: string;
  required?: boolean;
  value: string;
}) {
  return (
    <div className="field-row">
      <label>
        {label} {required && <strong>*</strong>}
      </label>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}
