"use client";

import { Suspense, useState, useCallback, useMemo, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useApi } from "@/hooks/use-api";
import api from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Plus,
  Search,
  CheckCircle2,
  RefreshCw,
  Loader2,
  Cloud,
  Database,
  Bot,
  GitBranch,
  BarChart2,
  ShieldCheck,
  Zap,
  Link2,
  Layers,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface PlatformConnection {
  id: string;
  platform: string;
  name: string;
  created_at: string;
  last_synced: string | null;
}

interface ConnectorDef {
  key: string;
  label: string;
  category: string;
  emoji: string;
  description: string;
  accentColor: string;
  badgeColor: string;
  fields: { key: string; label: string; type: string; placeholder: string }[];
}

// ─── Connector Catalog ────────────────────────────────────────────────────────

const CONNECTORS: ConnectorDef[] = [
  // Cloud & Warehouses
  {
    key: "aws",
    label: "AWS",
    category: "Cloud & Warehouses",
    emoji: "☁️",
    description: "S3, Redshift, Glue, MWAA, SageMaker, Bedrock — 21 services via Cost Explorer.",
    accentColor: "bg-orange-50 border-orange-100",
    badgeColor: "bg-orange-100 text-orange-700",
    fields: [
      { key: "aws_access_key_id", label: "Access Key ID", type: "text", placeholder: "AKIA..." },
      { key: "aws_secret_access_key", label: "Secret Access Key", type: "password", placeholder: "Secret key" },
      { key: "region", label: "Region (optional)", type: "text", placeholder: "us-east-1" },
    ],
  },
  {
    key: "snowflake",
    label: "Snowflake",
    category: "Cloud & Warehouses",
    emoji: "❄️",
    description: "Deep cost analytics — warehouse sizing, query patterns, storage by schema.",
    accentColor: "bg-cyan-50 border-cyan-100",
    badgeColor: "bg-cyan-100 text-cyan-700",
    fields: [
      { key: "account", label: "Account Identifier", type: "text", placeholder: "xy12345.us-east-1" },
      { key: "user", label: "User", type: "text", placeholder: "COSTLY_USER" },
      { key: "private_key", label: "Private Key (PEM)", type: "textarea", placeholder: "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----" },
      { key: "warehouse", label: "Warehouse (optional)", type: "text", placeholder: "COMPUTE_WH" },
      { key: "role", label: "Role (optional)", type: "text", placeholder: "COSTLY_ROLE" },
    ],
  },
  {
    key: "gcp",
    label: "BigQuery",
    category: "Cloud & Warehouses",
    emoji: "🔷",
    description: "Bytes scanned, slot usage, and storage costs by dataset and project.",
    accentColor: "bg-blue-50 border-blue-100",
    badgeColor: "bg-blue-100 text-blue-700",
    fields: [
      { key: "project_id", label: "Project ID", type: "text", placeholder: "my-gcp-project" },
      { key: "service_account_json", label: "Service Account JSON", type: "password", placeholder: "Paste JSON key" },
    ],
  },
  {
    key: "databricks",
    label: "Databricks",
    category: "Cloud & Warehouses",
    emoji: "🔶",
    description: "Compute, SQL warehouse, DLT, and ML serving costs tracked by DBU.",
    accentColor: "bg-red-50 border-red-100",
    badgeColor: "bg-red-100 text-red-700",
    fields: [
      { key: "account_id", label: "Account ID", type: "text", placeholder: "Account ID" },
      { key: "access_token", label: "Access Token", type: "password", placeholder: "dapi..." },
      { key: "workspace_url", label: "Workspace URL", type: "text", placeholder: "https://xxx.cloud.databricks.com" },
    ],
  },
  {
    key: "redshift",
    label: "Redshift",
    category: "Cloud & Warehouses",
    emoji: "🟥",
    description:
      "First-class Redshift connector — SYS_QUERY_HISTORY attribution, Serverless RPU, Spectrum scans, and Concurrency Scaling tracked per cluster/workgroup.",
    accentColor: "bg-rose-50 border-rose-100",
    badgeColor: "bg-rose-100 text-rose-700",
    fields: [
      { key: "aws_access_key_id", label: "Access Key ID", type: "text", placeholder: "AKIA..." },
      { key: "aws_secret_access_key", label: "Secret Access Key", type: "password", placeholder: "Secret key" },
      { key: "region", label: "Region", type: "text", placeholder: "us-east-1" },
      { key: "cluster_identifier", label: "Cluster Identifier (provisioned)", type: "text", placeholder: "analytics-prod" },
      { key: "workgroup_name", label: "Workgroup Name (serverless, optional)", type: "text", placeholder: "analytics-wg" },
      { key: "database", label: "Database", type: "text", placeholder: "dev" },
      { key: "db_user", label: "DB User (IAM auth)", type: "text", placeholder: "costly_reader" },
      { key: "secret_arn", label: "Secrets Manager ARN (optional)", type: "text", placeholder: "arn:aws:secretsmanager:..." },
    ],
  },
  // Data Pipelines
  {
    key: "dbt_cloud",
    label: "dbt Cloud",
    category: "Data Pipelines",
    emoji: "🔁",
    description: "Job runs, model execution times, and run frequency across all environments.",
    accentColor: "bg-green-50 border-green-100",
    badgeColor: "bg-green-100 text-green-700",
    fields: [
      { key: "api_token", label: "API Token", type: "password", placeholder: "dbtc_..." },
      { key: "account_id", label: "Account ID", type: "text", placeholder: "12345" },
    ],
  },
  {
    key: "fivetran",
    label: "Fivetran",
    category: "Data Pipelines",
    emoji: "🔌",
    description: "Connector sync costs, MAR (monthly active rows), and data volume tracking.",
    accentColor: "bg-blue-50 border-blue-100",
    badgeColor: "bg-blue-100 text-blue-700",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "API key" },
      { key: "api_secret", label: "API Secret", type: "password", placeholder: "API secret" },
    ],
  },
  {
    key: "airbyte",
    label: "Airbyte",
    category: "Data Pipelines",
    emoji: "🌀",
    description: "Cloud and self-hosted sync jobs, data volume, and connector cost tracking.",
    accentColor: "bg-violet-50 border-violet-100",
    badgeColor: "bg-violet-100 text-violet-700",
    fields: [
      { key: "api_token", label: "API Token", type: "password", placeholder: "API key" },
      { key: "host", label: "Host URL", type: "text", placeholder: "https://cloud.airbyte.com" },
    ],
  },
  // AI & ML
  {
    key: "openai",
    label: "OpenAI",
    category: "AI & ML",
    emoji: "🤖",
    description: "Token usage and spend by model — GPT-4o, o1, embeddings, and more.",
    accentColor: "bg-emerald-50 border-emerald-100",
    badgeColor: "bg-emerald-100 text-emerald-700",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "sk-..." },
      { key: "org_id", label: "Organization ID (optional)", type: "text", placeholder: "org-..." },
    ],
  },
  {
    key: "anthropic",
    label: "Anthropic API",
    category: "AI & ML",
    emoji: "⚡",
    description: "Anthropic API traffic — per-workspace, per-model, cache tiers, batch/flex discounts. Requires an Admin API key from console.anthropic.com → Settings → Admin Keys.",
    accentColor: "bg-purple-50 border-purple-100",
    badgeColor: "bg-purple-100 text-purple-700",
    fields: [
      { key: "api_key", label: "Admin API Key", type: "password", placeholder: "sk-ant-admin-..." },
    ],
  },
  {
    key: "claude_code",
    label: "Claude Code",
    category: "AI & ML",
    emoji: "🤖",
    description: "Claude Code subscription (Max/Pro) usage — parses local session transcripts. Set the path to your ~/.claude/projects directory. Self-hosted only; complements the Anthropic API connector.",
    accentColor: "bg-rose-50 border-rose-100",
    badgeColor: "bg-rose-100 text-rose-700",
    fields: [
      { key: "projects_dir", label: "Projects directory", type: "text", placeholder: "~/.claude/projects" },
    ],
  },
  {
    key: "gemini",
    label: "Gemini",
    category: "AI & ML",
    emoji: "✨",
    description: "AI Studio and Vertex AI usage tracking across all Gemini model versions.",
    accentColor: "bg-yellow-50 border-yellow-100",
    badgeColor: "bg-yellow-100 text-yellow-700",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "AIza..." },
      { key: "project_id", label: "GCP Project ID (for Vertex)", type: "text", placeholder: "my-project" },
      { key: "service_account_json", label: "Service Account JSON (optional, for Vertex AI)", type: "textarea", placeholder: '{"type": "service_account", ...}' },
    ],
  },
  // BI & Analytics
  {
    key: "looker",
    label: "Looker",
    category: "BI & Analytics",
    emoji: "📊",
    description: "Query costs, PDT build times, and user activity across your Looker instance.",
    accentColor: "bg-indigo-50 border-indigo-100",
    badgeColor: "bg-indigo-100 text-indigo-700",
    fields: [
      { key: "instance_url", label: "Base URL", type: "text", placeholder: "https://company.looker.com" },
      { key: "client_id", label: "Client ID", type: "text", placeholder: "Client ID" },
      { key: "client_secret", label: "Client Secret", type: "password", placeholder: "Client secret" },
    ],
  },
  {
    key: "tableau",
    label: "Tableau",
    category: "BI & Analytics",
    emoji: "📈",
    description: "License seats, view usage, and extract refresh costs across sites.",
    accentColor: "bg-sky-50 border-sky-100",
    badgeColor: "bg-sky-100 text-sky-700",
    fields: [
      { key: "server_url", label: "Server URL", type: "text", placeholder: "https://tableau.company.com" },
      { key: "token_name", label: "Personal Access Token Name", type: "text", placeholder: "Token name" },
      { key: "token_secret", label: "Token Secret", type: "password", placeholder: "Token value" },
    ],
  },
  {
    key: "omni",
    label: "Omni",
    category: "BI & Analytics",
    emoji: "🔵",
    description: "User seats, query volume, and cost estimation across your Omni workspace.",
    accentColor: "bg-blue-50 border-blue-100",
    badgeColor: "bg-blue-100 text-blue-700",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "API key" },
      { key: "instance_url", label: "Instance URL", type: "text", placeholder: "https://your-org.omniapp.co" },
    ],
  },
  // CI/CD & DevOps
  {
    key: "github",
    label: "GitHub Actions",
    category: "CI/CD & DevOps",
    emoji: "⚙️",
    description: "Workflow minutes broken down by repo, branch, and runner type.",
    accentColor: "bg-slate-50 border-slate-200",
    badgeColor: "bg-slate-100 text-slate-700",
    fields: [
      { key: "token", label: "Personal Access Token", type: "password", placeholder: "ghp_..." },
      { key: "org", label: "Organization (optional)", type: "text", placeholder: "my-org" },
    ],
  },
  {
    key: "gitlab",
    label: "GitLab CI",
    category: "CI/CD & DevOps",
    emoji: "🦊",
    description: "Pipeline minutes, job duration, and shared runner usage tracking.",
    accentColor: "bg-orange-50 border-orange-100",
    badgeColor: "bg-orange-100 text-orange-700",
    fields: [
      { key: "token", label: "Personal Access Token", type: "password", placeholder: "glpat-..." },
      { key: "group_id", label: "Group ID", type: "text", placeholder: "12345" },
      { key: "instance_url", label: "Instance URL (optional)", type: "text", placeholder: "https://gitlab.com" },
    ],
  },
  // Data Quality
  {
    key: "monte_carlo",
    label: "Monte Carlo",
    category: "Data Quality",
    emoji: "🎲",
    description: "Tables monitored, incidents tracked, and data quality cost attribution.",
    accentColor: "bg-teal-50 border-teal-100",
    badgeColor: "bg-teal-100 text-teal-700",
    fields: [
      { key: "api_key_id", label: "API Key ID", type: "text", placeholder: "Key ID" },
      { key: "api_token", label: "API Token", type: "password", placeholder: "Token" },
    ],
  },
];

// ─── Category Config ──────────────────────────────────────────────────────────

const CATEGORIES: { label: string; icon: React.ElementType; color: string }[] = [
  { label: "Cloud & Warehouses", icon: Cloud, color: "text-blue-600" },
  { label: "Data Pipelines", icon: Layers, color: "text-green-600" },
  { label: "AI & ML", icon: Bot, color: "text-purple-600" },
  { label: "BI & Analytics", icon: BarChart2, color: "text-indigo-600" },
  { label: "CI/CD & DevOps", icon: GitBranch, color: "text-slate-700" },
  { label: "Data Quality", icon: ShieldCheck, color: "text-teal-600" },
];

// ─── Connect Dialog ───────────────────────────────────────────────────────────

function ConnectDialog({
  connector,
  open,
  onOpenChange,
  onSuccess,
}: {
  connector: ConnectorDef | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSuccess: () => void;
}) {
  const [connName, setConnName] = useState("");
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Claude Code JSONL upload state (hosted-mode alternative to filesystem path)
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    records: number;
    turns_parsed: number;
    files: number;
    total_cost_usd: number;
  } | null>(null);

  const handleClose = () => {
    onOpenChange(false);
    setConnName("");
    setCredentials({});
    setError(null);
    setUploadFiles(null);
    setUploadResult(null);
  };

  const handleUpload = async () => {
    if (!uploadFiles || uploadFiles.length === 0) return;
    setUploading(true);
    setError(null);
    setUploadResult(null);
    try {
      const form = new FormData();
      for (const f of Array.from(uploadFiles)) form.append("files", f);
      const result = await api.post<unknown, {
        records: number;
        turns_parsed: number;
        files: number;
        total_cost_usd: number;
      }>("/platforms/claude-code/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadResult(result);
      onSuccess();
    } catch (err) {
      setError(typeof err === "string" ? err : "Upload failed. Make sure the files are Claude Code JSONL transcripts.");
    } finally {
      setUploading(false);
    }
  };

  const handleConnect = async () => {
    if (!connector || !connName) return;
    setSaving(true);
    setError(null);
    try {
      // Fill in defaults for optional fields left empty
      const creds = { ...credentials };
      for (const f of connector.fields) {
        if (!creds[f.key] && f.label.toLowerCase().includes("optional") && f.placeholder) {
          creds[f.key] = f.placeholder;
        }
      }
      await api.post("/platforms/connect", {
        platform: connector.key,
        name: connName,
        credentials: creds,
      });
      handleClose();
      onSuccess();
    } catch (err) {
      setError(typeof err === "string" ? err : "Connection failed. Check your credentials and try again.");
    } finally {
      setSaving(false);
    }
  };

  // Fields with "(optional)" in the label are not required
  const isFormValid =
    !!connector &&
    connName.trim().length > 0 &&
    connector.fields.every(
      (f) => f.label.toLowerCase().includes("optional") || !!credentials[f.key]
    );

  if (!connector) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-base">
            <span className="text-xl">{connector.emoji}</span>
            Connect {connector.label}
          </DialogTitle>
          <DialogDescription>{connector.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-1">
          <div>
            <Label htmlFor="conn-name">Connection Name</Label>
            <Input
              id="conn-name"
              className="mt-1.5"
              value={connName}
              onChange={(e) => setConnName(e.target.value)}
              placeholder={`e.g. Production ${connector.label}`}
            />
          </div>
          {connector.fields.map((field) => (
            <div key={field.key}>
              <Label htmlFor={field.key}>{field.label}</Label>
              {field.type === "textarea" ? (
                <textarea
                  id={field.key}
                  className="mt-1.5 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-mono h-28 resize-none focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-transparent"
                  value={credentials[field.key] || ""}
                  onChange={(e) =>
                    setCredentials({ ...credentials, [field.key]: e.target.value })
                  }
                  placeholder={field.placeholder}
                />
              ) : (
                <Input
                  id={field.key}
                  className="mt-1.5"
                  type={field.type}
                  value={credentials[field.key] || ""}
                  onChange={(e) =>
                    setCredentials({ ...credentials, [field.key]: e.target.value })
                  }
                  placeholder={field.placeholder}
                />
              )}
            </div>
          ))}

          {/* Claude Code: JSONL upload alternative to filesystem path.
              The filesystem path only works if the backend can read the
              user's ~/.claude/projects (i.e. self-hosted with a docker
              volume mount). Hosted users upload files directly instead. */}
          {connector.key === "claude_code" && (
            <div className="border-t border-slate-200 pt-4 mt-2">
              <div className="flex items-baseline justify-between">
                <Label className="text-sm font-semibold">Or upload JSONL files</Label>
                <span className="text-[0.65rem] text-slate-400 uppercase tracking-wider">For hosted users</span>
              </div>

              <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-600 leading-relaxed">
                <p className="font-medium text-slate-800 mb-1">Where to find the files:</p>
                <ul className="space-y-0.5 pl-4 list-disc">
                  <li>
                    macOS / Linux: <span className="font-mono">~/.claude/projects/</span>
                  </li>
                  <li>
                    Windows: <span className="font-mono">%USERPROFILE%\.claude\projects\</span>
                  </li>
                  <li>Each project has its own folder (e.g. <span className="font-mono">-Users-jain-src/</span>)</li>
                  <li>Inside each folder: one <span className="font-mono">*.jsonl</span> file per session</li>
                </ul>
                <p className="mt-2 font-medium text-slate-800">Can&apos;t see the <span className="font-mono">.claude</span> folder? It&apos;s hidden by default. Three ways in:</p>
                <ol className="mt-1 space-y-0.5 pl-4 list-decimal text-slate-600">
                  <li>
                    In the file picker, press <kbd className="font-mono text-[0.7rem] bg-slate-200 px-1 py-0.5 rounded">⇧⌘.</kbd> to toggle hidden files (Mac) /{" "}
                    <kbd className="font-mono text-[0.7rem] bg-slate-200 px-1 py-0.5 rounded">Ctrl+H</kbd> (Linux)
                  </li>
                  <li>
                    Press <kbd className="font-mono text-[0.7rem] bg-slate-200 px-1 py-0.5 rounded">⇧⌘G</kbd> in the picker and paste <span className="font-mono">~/.claude/projects</span>
                  </li>
                  <li>
                    Run <span className="font-mono">open ~/.claude/projects</span> in Terminal first, then drag files from that Finder window into the picker below
                  </li>
                </ol>
                <p className="mt-2 text-slate-500">
                  Limits: 100MB per file, 500MB per upload.
                </p>
              </div>

              <input
                type="file"
                multiple
                accept=".jsonl,application/x-ndjson,application/json,text/plain"
                onChange={(e) => setUploadFiles(e.target.files)}
                className="mt-3 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-indigo-600 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-indigo-700 file:cursor-pointer"
              />

              {uploadFiles && uploadFiles.length > 0 && !uploadResult && (
                <p className="mt-2 text-xs text-slate-500">
                  {uploadFiles.length} file{uploadFiles.length === 1 ? "" : "s"} selected ·{" "}
                  {Math.round(Array.from(uploadFiles).reduce((s, f) => s + f.size, 0) / 1024 / 1024)} MB total
                </p>
              )}

              {uploadResult && (
                <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-900">
                  <div className="font-semibold">✓ Uploaded successfully</div>
                  <div className="text-xs mt-1 text-emerald-800">
                    {uploadResult.files} file(s) · {uploadResult.turns_parsed.toLocaleString()} turns parsed ·{" "}
                    {uploadResult.records} cost record(s) · ${uploadResult.total_cost_usd.toLocaleString()} total
                  </div>
                  <div className="text-xs mt-1 text-emerald-700">
                    Your data is on the AI Costs page now.
                  </div>
                </div>
              )}

              <Button
                onClick={handleUpload}
                disabled={uploading || !uploadFiles || uploadFiles.length === 0}
                variant="outline"
                className="mt-3 w-full gap-2"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                {uploading ? "Parsing files…" : "Upload & parse"}
              </Button>
            </div>
          )}

          {error && (
            <p className="text-sm text-red-500 bg-red-50 border border-red-100 rounded-md px-3 py-2">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleConnect} disabled={saving || !isFormValid} className="gap-2">
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Link2 className="h-4 w-4" />
            )}
            Test &amp; Connect
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Connector Card ───────────────────────────────────────────────────────────

function ConnectorCard({
  connector,
  isConnected,
  onConnect,
}: {
  connector: ConnectorDef;
  isConnected: boolean;
  onConnect: (connector: ConnectorDef) => void;
}) {
  return (
    <div
      className={`group relative rounded-xl border bg-white p-5 transition-all duration-150 hover:shadow-md hover:-translate-y-0.5 ${
        isConnected ? "ring-1 ring-green-300 border-green-200" : "border-slate-200 hover:border-slate-300"
      }`}
    >
      {isConnected && (
        <div className="absolute top-3 right-3">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
        </div>
      )}
      <div className="flex items-start gap-3 mb-3">
        <span className="text-2xl leading-none mt-0.5">{connector.emoji}</span>
        <div className="min-w-0">
          <p className="font-semibold text-slate-900 text-sm leading-tight">{connector.label}</p>
          <span
            className={`inline-block mt-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${connector.badgeColor}`}
          >
            {connector.category}
          </span>
        </div>
      </div>
      <p className="text-xs text-slate-500 leading-relaxed mb-4">{connector.description}</p>
      <Button
        size="sm"
        variant={isConnected ? "outline" : "default"}
        className="w-full gap-1.5 text-xs h-8"
        onClick={() => !isConnected && onConnect(connector)}
        disabled={isConnected}
      >
        {isConnected ? (
          <>
            <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
            Connected
          </>
        ) : (
          <>
            <Plus className="h-3.5 w-3.5" />
            Connect
          </>
        )}
      </Button>
    </div>
  );
}

// ─── Connected Platform Row ───────────────────────────────────────────────────

function ConnectedRow({
  conn,
  syncing,
  onSync,
}: {
  conn: PlatformConnection;
  syncing: boolean;
  onSync: (id: string) => void;
}) {
  const connector = CONNECTORS.find((c) => c.key === conn.platform);
  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 transition-colors">
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-lg">{connector?.emoji ?? "🔌"}</span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-900 truncate">{conn.name}</p>
          <p className="text-xs text-slate-400 mt-0.5">
            {connector?.label ?? conn.platform}
            {conn.last_synced
              ? ` · Synced ${new Date(conn.last_synced).toLocaleDateString()}`
              : " · Never synced"}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-4 shrink-0">
        <Badge variant="outline" className="text-[10px] text-green-600 border-green-200 bg-green-50">
          Active
        </Badge>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={() => onSync(conn.id)}
          disabled={syncing}
          title="Sync now"
        >
          {syncing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5 text-slate-400" />
          )}
        </Button>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PlatformsPage() {
  // useSearchParams requires a Suspense boundary per Next.js 15.
  return (
    <Suspense fallback={null}>
      <PlatformsPageInner />
    </Suspense>
  );
}

function PlatformsPageInner() {
  const { data: connections, loading, refetch } = useApi<PlatformConnection[]>("/platforms");
  const { data: sfStatus } = useApi<{ has_connection: boolean }>("/connections/status");
  const [search, setSearch] = useState("");
  const [activeConnector, setActiveConnector] = useState<ConnectorDef | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [syncing, setSyncing] = useState<string | null>(null);

  // Honor ?add=<connector_key> deep-link from the Setup page.
  const searchParams = useSearchParams();
  const router = useRouter();
  useEffect(() => {
    const addKey = searchParams.get("add");
    if (!addKey) return;
    const target = CONNECTORS.find((c) => c.key === addKey);
    if (target) {
      setActiveConnector(target);
      setDialogOpen(true);
      // Clear the query param so refresh doesn't re-open.
      router.replace("/platforms");
    }
  }, [searchParams, router]);

  const connectedKeys = useMemo(() => {
    const keys = new Set((connections ?? []).map((c) => c.platform));
    if (sfStatus?.has_connection) keys.add("snowflake");
    return keys;
  }, [connections, sfStatus]);

  const connectedCount = connectedKeys.size;

  const filteredConnectors = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return CONNECTORS;
    return CONNECTORS.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        c.category.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q)
    );
  }, [search]);

  const handleConnect = (connector: ConnectorDef) => {
    setActiveConnector(connector);
    setDialogOpen(true);
  };

  const handleSync = useCallback(
    async (id: string) => {
      setSyncing(id);
      try {
        await api.post(`/platforms/${id}/sync?days=30`);
        refetch();
      } catch {
        // silent
      } finally {
        setSyncing(null);
      }
    },
    [refetch]
  );

  const groupedFiltered = useMemo(() => {
    const map: Record<string, ConnectorDef[]> = {};
    for (const c of filteredConnectors) {
      if (!map[c.category]) map[c.category] = [];
      map[c.category].push(c);
    }
    return map;
  }, [filteredConnectors]);

  return (
    <div className="space-y-8">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Platform Connections</h1>
          <p className="text-sm text-slate-500 mt-1">
            Connect your data stack to get a unified cost view across all platforms.
          </p>
        </div>
        <Button
          className="gap-2 shrink-0 self-start sm:self-auto"
          onClick={() => {
            setActiveConnector(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="h-4 w-4" />
          Add Platform
        </Button>
      </div>

      {/* ── Summary bar ── */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex items-center gap-3 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <div className="h-9 w-9 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
            <Zap className="h-4 w-4 text-blue-600" />
          </div>
          <div>
            <p className="text-xs text-slate-500">Connected</p>
            <p className="text-lg font-bold text-slate-900 leading-tight">
              {connectedCount}{" "}
              <span className="text-sm font-normal text-slate-400">of 16 platforms</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <div className="h-9 w-9 rounded-lg bg-green-50 flex items-center justify-center shrink-0">
            <Database className="h-4 w-4 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-slate-500">Categories</p>
            <p className="text-lg font-bold text-slate-900 leading-tight">
              6{" "}
              <span className="text-sm font-normal text-slate-400">platform types</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <div className="h-9 w-9 rounded-lg bg-purple-50 flex items-center justify-center shrink-0">
            <Bot className="h-4 w-4 text-purple-600" />
          </div>
          <div>
            <p className="text-xs text-slate-500">AI Connectors</p>
            <p className="text-lg font-bold text-slate-900 leading-tight">
              3{" "}
              <span className="text-sm font-normal text-slate-400">OpenAI · Anthropic · Gemini</span>
            </p>
          </div>
        </div>
      </div>

      {/* ── Connected platforms ── */}
      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-14 rounded-lg" />
          <Skeleton className="h-14 rounded-lg" />
        </div>
      ) : connections && connections.length > 0 ? (
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            Connected Platforms
          </h2>
          <div className="space-y-2">
            {connections.map((conn) => (
              <ConnectedRow
                key={conn.id}
                conn={conn}
                syncing={syncing === conn.id}
                onSync={handleSync}
              />
            ))}
          </div>
        </div>
      ) : null}

      {/* ── Search ── */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 pointer-events-none" />
        <Input
          className="pl-9 bg-white"
          placeholder="Search platforms by name or category..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* ── Connector catalog by category ── */}
      {Object.keys(groupedFiltered).length === 0 ? (
        <div className="text-center py-16 text-slate-500">
          <Search className="h-8 w-8 mx-auto mb-3 text-slate-300" />
          <p className="font-medium">No platforms match &ldquo;{search}&rdquo;</p>
          <p className="text-sm text-slate-400 mt-1">Try a different keyword or clear the search.</p>
        </div>
      ) : (
        <div className="space-y-10">
          {CATEGORIES.filter((cat) => groupedFiltered[cat.label]).map((cat) => {
            const Icon = cat.icon;
            const items = groupedFiltered[cat.label];
            return (
              <div key={cat.label}>
                <div className="flex items-center gap-2 mb-4">
                  <Icon className={`h-4 w-4 ${cat.color}`} />
                  <h2 className="text-sm font-semibold text-slate-700">{cat.label}</h2>
                  <span className="text-xs text-slate-400 font-normal">
                    ({items.length} platform{items.length !== 1 ? "s" : ""})
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {items.map((connector) => (
                    <ConnectorCard
                      key={connector.key}
                      connector={connector}
                      isConnected={connectedKeys.has(connector.key)}
                      onConnect={handleConnect}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Connect Dialog ── */}
      <ConnectDialog
        connector={activeConnector}
        open={dialogOpen && activeConnector !== null}
        onOpenChange={(v) => {
          setDialogOpen(v);
          if (!v) setActiveConnector(null);
        }}
        onSuccess={refetch}
      />
    </div>
  );
}
