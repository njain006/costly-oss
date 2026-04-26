"use client";

import { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  ArrowRight,
  ArrowLeft,
  Sparkles,
  Zap,
  TrendingDown,
  DollarSign,
  Link2,
  CheckCircle2,
  BarChart3,
  AlertCircle,
} from "lucide-react";

// ─── Platform Definitions ─────────────────────────────────────────────────────

interface PlatformDef {
  key: string;
  label: string;
  category: string;
  fields: { key: string; label: string; type: string; placeholder: string }[];
  setupGuide?: string | string[];
  setupLanguage?: string;
}

const PLATFORMS: PlatformDef[] = [
  {
    key: "snowflake",
    label: "Snowflake",
    category: "Warehouse",
    fields: [
      { key: "account", label: "Account", type: "text", placeholder: "xy12345.us-east-1" },
      { key: "user", label: "User", type: "text", placeholder: "COSTLY_USER" },
      { key: "private_key", label: "Private Key (PEM)", type: "password", placeholder: "Paste RSA private key" },
    ],
    setupLanguage: "sql",
    setupGuide: [
      "-- Run these in Snowflake as ACCOUNTADMIN (2 minutes)",
      "CREATE ROLE IF NOT EXISTS COSTLY_ROLE;",
      "GRANT MONITOR USAGE ON ACCOUNT TO ROLE COSTLY_ROLE;",
      "GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE COSTLY_ROLE;",
      "CREATE USER IF NOT EXISTS COSTLY_USER",
      "  DEFAULT_ROLE = COSTLY_ROLE",
      "  DEFAULT_WAREHOUSE = COMPUTE_WH;",
      "GRANT ROLE COSTLY_ROLE TO USER COSTLY_USER;",
      "",
      "-- Generate key pair (run locally)",
      "openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out costly_key.p8 -nocrypt",
      "openssl rsa -in costly_key.p8 -pubout -out costly_key.pub",
      "",
      "-- Set the public key on the user",
      "ALTER USER COSTLY_USER SET RSA_PUBLIC_KEY='<paste public key here>';",
    ],
  },
  {
    key: "aws",
    label: "AWS",
    category: "Cloud",
    fields: [
      { key: "aws_access_key_id", label: "Access Key ID", type: "text", placeholder: "AKIA..." },
      { key: "aws_secret_access_key", label: "Secret Access Key", type: "password", placeholder: "Secret key" },
      { key: "region", label: "Region", type: "text", placeholder: "us-east-1" },
    ],
    setupLanguage: "json",
    setupGuide: [
      "// Create an IAM user with this policy:",
      '{',
      '  "Version": "2012-10-17",',
      '  "Statement": [{',
      '    "Effect": "Allow",',
      '    "Action": [',
      '      "ce:GetCostAndUsage",',
      '      "ce:GetCostForecast"',
      '    ],',
      '    "Resource": "*"',
      '  }]',
      '}',
    ],
  },
  {
    key: "dbt_cloud",
    label: "dbt Cloud",
    category: "Transform",
    fields: [
      { key: "api_token", label: "API Token", type: "password", placeholder: "dbtc_..." },
      { key: "account_id", label: "Account ID", type: "text", placeholder: "12345" },
    ],
    setupGuide: "Go to Account Settings \u2192 API Access \u2192 Generate Service Token",
  },
  {
    key: "openai",
    label: "OpenAI",
    category: "AI",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "sk-..." },
      { key: "org_id", label: "Organization ID (optional)", type: "text", placeholder: "org-..." },
    ],
    setupGuide: "Go to platform.openai.com \u2192 Settings \u2192 API Keys \u2192 Create new key",
  },
  {
    key: "anthropic",
    label: "Anthropic API",
    category: "AI",
    fields: [
      { key: "api_key", label: "Admin API Key", type: "password", placeholder: "sk-ant-admin-..." },
    ],
    setupGuide: "console.anthropic.com \u2192 Settings \u2192 Admin Keys. Not a regular sk-ant key.",
  },
  {
    key: "claude_code",
    label: "Claude Code",
    category: "AI",
    fields: [
      { key: "projects_dir", label: "Projects directory", type: "text", placeholder: "~/.claude/projects" },
    ],
    setupGuide: "Parses local session JSONLs. Self-hosted only. Set to /claude-projects if you mounted ~/.claude/projects in docker-compose.",
  },
  {
    key: "gemini",
    label: "Gemini",
    category: "AI",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "AIza..." },
      { key: "project_id", label: "GCP Project ID (for Vertex)", type: "text", placeholder: "my-project" },
    ],
    setupGuide: "Go to aistudio.google.com \u2192 Get API Key \u2192 Create API key",
  },
  {
    key: "fivetran",
    label: "Fivetran",
    category: "Ingestion",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "API key" },
      { key: "api_secret", label: "API Secret", type: "password", placeholder: "API secret" },
    ],
    setupGuide: "Go to Settings \u2192 API Config \u2192 Generate API Key and Secret",
  },
  {
    key: "airbyte",
    label: "Airbyte",
    category: "Ingestion",
    fields: [
      { key: "api_key", label: "API Key / Token", type: "password", placeholder: "API key" },
      { key: "workspace_id", label: "Workspace ID (optional)", type: "text", placeholder: "Workspace ID" },
    ],
    setupGuide: "Go to Settings \u2192 API Tokens \u2192 Generate a new token",
  },
  {
    key: "gcp",
    label: "BigQuery",
    category: "Warehouse",
    fields: [
      { key: "project_id", label: "Project ID", type: "text", placeholder: "my-gcp-project" },
      { key: "service_account_json", label: "Service Account JSON", type: "password", placeholder: "Paste JSON key" },
    ],
    setupGuide: "Go to GCP Console \u2192 IAM \u2192 Service Accounts \u2192 Create key (JSON)",
  },
  {
    key: "databricks",
    label: "Databricks",
    category: "Warehouse",
    fields: [
      { key: "account_id", label: "Account ID", type: "text", placeholder: "Account ID" },
      { key: "access_token", label: "Access Token", type: "password", placeholder: "dapi..." },
      { key: "workspace_url", label: "Workspace URL", type: "text", placeholder: "https://xxx.cloud.databricks.com" },
    ],
    setupGuide: "Go to Settings \u2192 Developer \u2192 Access Tokens \u2192 Generate New Token",
  },
  {
    key: "looker",
    label: "Looker",
    category: "BI",
    fields: [
      { key: "base_url", label: "Base URL", type: "text", placeholder: "https://company.looker.com" },
      { key: "client_id", label: "Client ID", type: "text", placeholder: "Client ID" },
      { key: "client_secret", label: "Client Secret", type: "password", placeholder: "Client secret" },
    ],
    setupGuide: "Go to Admin \u2192 Users \u2192 API Keys \u2192 New API Key",
  },
  {
    key: "tableau",
    label: "Tableau",
    category: "BI",
    fields: [
      { key: "server_url", label: "Server URL", type: "text", placeholder: "https://tableau.company.com" },
      { key: "token_name", label: "PAT Name", type: "text", placeholder: "Token name" },
      { key: "token_value", label: "PAT Value", type: "password", placeholder: "Token value" },
    ],
    setupGuide: "Go to My Account Settings \u2192 Personal Access Tokens \u2192 Create",
  },
  {
    key: "github",
    label: "GitHub Actions",
    category: "CI/CD",
    fields: [
      { key: "token", label: "Personal Access Token", type: "password", placeholder: "ghp_..." },
      { key: "org", label: "Organization (optional)", type: "text", placeholder: "my-org" },
    ],
    setupGuide: "Go to Settings \u2192 Developer Settings \u2192 Personal Access Tokens \u2192 Generate",
  },
  {
    key: "gitlab",
    label: "GitLab CI",
    category: "CI/CD",
    fields: [
      { key: "token", label: "Personal Access Token", type: "password", placeholder: "glpat-..." },
      { key: "namespace", label: "Group / Namespace (optional)", type: "text", placeholder: "my-group" },
    ],
    setupGuide: "Go to Preferences \u2192 Access Tokens \u2192 Add new token",
  },
  {
    key: "monte_carlo",
    label: "Monte Carlo",
    category: "Quality",
    fields: [
      { key: "api_key_id", label: "API Key ID", type: "text", placeholder: "Key ID" },
      { key: "api_key_token", label: "API Key Token", type: "password", placeholder: "Token" },
    ],
    setupGuide: "Go to Settings \u2192 API Keys \u2192 Create Key",
  },
  {
    key: "omni",
    label: "Omni",
    category: "BI",
    fields: [
      { key: "api_key", label: "API Key", type: "password", placeholder: "API key" },
      { key: "org_id", label: "Organization ID", type: "text", placeholder: "org-..." },
    ],
    setupGuide: "Go to Admin \u2192 API Keys \u2192 Generate",
  },
];

const CATEGORY_COLORS: Record<string, string> = {
  Warehouse: "bg-cyan-100 text-cyan-700",
  Cloud: "bg-orange-100 text-orange-700",
  Transform: "bg-green-100 text-green-700",
  AI: "bg-purple-100 text-purple-700",
  Ingestion: "bg-blue-100 text-blue-700",
  BI: "bg-indigo-100 text-indigo-700",
  "CI/CD": "bg-slate-100 text-slate-700",
  Quality: "bg-teal-100 text-teal-700",
};

// ─── Step 1: Stack Selection ──────────────────────────────────────────────────

function StepStack({
  selected,
  onToggle,
  onContinue,
}: {
  selected: Set<string>;
  onToggle: (key: string) => void;
  onContinue: () => void;
}) {
  return (
    <div className="space-y-8">
      <div className="text-center max-w-xl mx-auto">
        <h1 className="text-2xl font-bold text-slate-900 mb-2">
          What&apos;s in your data stack?
        </h1>
        <p className="text-sm text-slate-500">
          Select the platforms you use. We&apos;ll help you connect them and
          start tracking costs in minutes.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {PLATFORMS.map((p) => {
          const isSelected = selected.has(p.key);
          return (
            <button
              key={p.key}
              onClick={() => onToggle(p.key)}
              className={`relative rounded-xl border p-4 text-left transition-all duration-150 hover:shadow-md hover:-translate-y-0.5 ${
                isSelected
                  ? "border-sky-400 bg-sky-50 ring-1 ring-sky-400"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              {isSelected && (
                <div className="absolute top-2.5 right-2.5 h-5 w-5 rounded-full bg-sky-500 flex items-center justify-center">
                  <Check className="h-3 w-3 text-white" />
                </div>
              )}
              <p className="font-semibold text-sm text-slate-900 mb-1">
                {p.label}
              </p>
              <Badge
                variant="secondary"
                className={`text-[10px] px-1.5 py-0 font-medium ${
                  CATEGORY_COLORS[p.category] || "bg-slate-100 text-slate-600"
                }`}
              >
                {p.category}
              </Badge>
            </button>
          );
        })}
      </div>

      <div className="flex justify-center">
        <Button
          size="lg"
          onClick={onContinue}
          disabled={selected.size === 0}
          className="gap-2 bg-sky-600 hover:bg-sky-700 px-8"
        >
          Continue
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
      {selected.size > 0 && (
        <p className="text-center text-xs text-slate-400">
          {selected.size} platform{selected.size !== 1 ? "s" : ""} selected
        </p>
      )}
    </div>
  );
}

// ─── Step 2: Connect Platforms ─────────────────────────────────────────────────

function CopyBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative">
      <pre className="bg-[#0B1929] text-slate-300 text-xs rounded-lg p-4 overflow-x-auto leading-relaxed font-mono">
        {text}
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2.5 right-2.5 p-1.5 rounded-md bg-white/10 hover:bg-white/20 transition text-slate-400 hover:text-white"
        title="Copy to clipboard"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-green-400" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}

function PlatformConnectCard({
  platform,
  isConnected,
  onConnected,
}: {
  platform: PlatformDef;
  isConnected: boolean;
  onConnected: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [connName, setConnName] = useState(`Production ${platform.label}`);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const guideText = useMemo(() => {
    if (!platform.setupGuide) return null;
    return Array.isArray(platform.setupGuide)
      ? platform.setupGuide.join("\n")
      : platform.setupGuide;
  }, [platform.setupGuide]);

  const isSimpleGuide =
    typeof platform.setupGuide === "string" ||
    !platform.setupGuide;

  const allFieldsFilled = platform.fields.every((f) => !!credentials[f.key]);

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      await api.post("/platforms/connect", {
        platform: platform.key,
        name: connName,
        credentials,
      });
      onConnected();
    } catch (err) {
      setError(
        typeof err === "string"
          ? err
          : "Connection failed. Check your credentials and try again."
      );
    } finally {
      setConnecting(false);
    }
  };

  if (isConnected) {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50/50 p-4 flex items-center gap-3">
        <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
        <div>
          <p className="font-semibold text-sm text-slate-900">
            {platform.label}
          </p>
          <p className="text-xs text-green-600">Connected successfully</p>
        </div>
      </div>
    );
  }

  return (
    <Card className="overflow-hidden border-slate-200">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <p className="font-semibold text-sm text-slate-900">
            {platform.label}
          </p>
          <Badge
            variant="secondary"
            className={`text-[10px] px-1.5 py-0 font-medium ${
              CATEGORY_COLORS[platform.category] || "bg-slate-100 text-slate-600"
            }`}
          >
            {platform.category}
          </Badge>
        </div>
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-400" />
        )}
      </button>

      {expanded && (
        <CardContent className="border-t border-slate-100 pt-5 space-y-5">
          {/* Setup Guide */}
          {guideText && (
            <div>
              <Label className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 block">
                Setup Guide
              </Label>
              {isSimpleGuide ? (
                <p className="text-sm text-slate-600 bg-slate-50 rounded-lg px-4 py-3 border border-slate-100">
                  {guideText}
                </p>
              ) : (
                <CopyBlock text={guideText} />
              )}
            </div>
          )}

          {/* Credential Fields */}
          <div className="space-y-3">
            <div>
              <Label htmlFor={`${platform.key}-name`} className="text-slate-700">
                Connection Name
              </Label>
              <Input
                id={`${platform.key}-name`}
                className="mt-1.5"
                value={connName}
                onChange={(e) => setConnName(e.target.value)}
                placeholder={`e.g. Production ${platform.label}`}
              />
            </div>
            {platform.fields.map((field) => (
              <div key={field.key}>
                <Label htmlFor={`${platform.key}-${field.key}`} className="text-slate-700">
                  {field.label}
                </Label>
                <Input
                  id={`${platform.key}-${field.key}`}
                  className="mt-1.5"
                  type={field.type}
                  value={credentials[field.key] || ""}
                  onChange={(e) =>
                    setCredentials({ ...credentials, [field.key]: e.target.value })
                  }
                  placeholder={field.placeholder}
                />
              </div>
            ))}
          </div>

          {error && (
            <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2.5">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              {error}
            </div>
          )}

          <Button
            onClick={handleConnect}
            disabled={connecting || !allFieldsFilled || !connName.trim()}
            className="w-full gap-2 bg-sky-600 hover:bg-sky-700"
          >
            {connecting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Link2 className="h-4 w-4" />
            )}
            Test &amp; Connect
          </Button>
        </CardContent>
      )}
    </Card>
  );
}

function StepConnect({
  selectedKeys,
  connectedKeys,
  onConnected,
  onContinue,
  onBack,
}: {
  selectedKeys: Set<string>;
  connectedKeys: Set<string>;
  onConnected: () => void;
  onContinue: () => void;
  onBack: () => void;
}) {
  // Sort: Snowflake first, then AWS, then alphabetically
  const priorityOrder = [
    "snowflake",
    "aws",
    "dbt_cloud",
    "gcp",
    "databricks",
    "openai",
    "anthropic",
    "gemini",
    "fivetran",
    "airbyte",
    "looker",
    "tableau",
    "github",
    "gitlab",
    "monte_carlo",
    "omni",
  ];

  const orderedPlatforms = useMemo(() => {
    return PLATFORMS.filter((p) => selectedKeys.has(p.key)).sort((a, b) => {
      const ai = priorityOrder.indexOf(a.key);
      const bi = priorityOrder.indexOf(b.key);
      return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
    });
  }, [selectedKeys]);

  const hasConnection = connectedKeys.size > 0;

  return (
    <div className="space-y-8">
      <div className="text-center max-w-xl mx-auto">
        <h1 className="text-2xl font-bold text-slate-900 mb-2">
          Connect your first platform
        </h1>
        <p className="text-sm text-slate-500">
          Follow the setup guide for each platform, enter your credentials, and
          click &quot;Test &amp; Connect&quot;. Connect at least one to continue.
        </p>
      </div>

      {hasConnection && (
        <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-green-500 shrink-0" />
          <p className="text-sm text-green-700 font-medium">
            {connectedKeys.size} platform{connectedKeys.size !== 1 ? "s" : ""}{" "}
            connected. You can connect more or continue.
          </p>
        </div>
      )}

      <div className="space-y-3 max-w-2xl mx-auto">
        {orderedPlatforms.map((platform) => (
          <PlatformConnectCard
            key={platform.key}
            platform={platform}
            isConnected={connectedKeys.has(platform.key)}
            onConnected={onConnected}
          />
        ))}
      </div>

      <div className="flex items-center justify-between max-w-2xl mx-auto">
        <Button variant="ghost" onClick={onBack} className="gap-2 text-slate-500">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <Button
          size="lg"
          onClick={onContinue}
          disabled={!hasConnection}
          className="gap-2 bg-sky-600 hover:bg-sky-700 px-8"
        >
          Continue
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ─── Step 3: Quick Wins ────────────────────────────────────────────────────────

interface SyncResult {
  totalSpend: number;
  platformCount: number;
  savingsFound: number;
  recommendations: { title: string; savings: string; description: string }[];
}

function StepQuickWins({
  connectedKeys,
  onBack,
}: {
  connectedKeys: Set<string>;
  onBack: () => void;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<"syncing" | "done">("syncing");
  const [result, setResult] = useState<SyncResult | null>(null);

  const runSync = useCallback(async () => {
    setPhase("syncing");

    // Fetch connections and trigger sync for each
    try {
      const connections = (await api.get("/platforms")) as {
        id: string;
        platform: string;
      }[];

      // Trigger sync for connected platforms
      const syncPromises = connections
        .filter((c) => connectedKeys.has(c.platform))
        .map((c) =>
          api.post(`/platforms/${c.id}/sync?days=30`).catch(() => null)
        );
      await Promise.allSettled(syncPromises);

      // Try to get cost overview data
      let totalSpend = 0;
      let savingsFound = 0;
      const recommendations: SyncResult["recommendations"] = [];

      try {
        const overview = (await api.get("/overview/summary")) as {
          total_cost?: number;
          potential_savings?: number;
        };
        totalSpend = overview?.total_cost || 0;
        savingsFound = overview?.potential_savings || 0;
      } catch {
        // If overview endpoint doesn't exist or fails, show defaults
      }

      try {
        const recs = (await api.get("/recommendations")) as {
          title?: string;
          estimated_savings?: number;
          description?: string;
        }[];
        if (Array.isArray(recs)) {
          for (const r of recs.slice(0, 3)) {
            recommendations.push({
              title: r.title || "Optimization opportunity",
              savings: r.estimated_savings
                ? formatCurrency(r.estimated_savings)
                : "TBD",
              description: r.description || "",
            });
          }
        }
      } catch {
        // Recommendations may not be available yet
      }

      setResult({
        totalSpend,
        platformCount: connectedKeys.size,
        savingsFound,
        recommendations,
      });
    } catch {
      // Fallback result
      setResult({
        totalSpend: 0,
        platformCount: connectedKeys.size,
        savingsFound: 0,
        recommendations: [],
      });
    }

    setPhase("done");
  }, [connectedKeys]);

  // Trigger sync on mount
  useState(() => {
    runSync();
  });

  if (phase === "syncing") {
    return (
      <div className="flex flex-col items-center justify-center py-20 space-y-6">
        <div className="relative">
          <div className="h-16 w-16 rounded-2xl bg-sky-100 flex items-center justify-center">
            <Loader2 className="h-8 w-8 text-sky-600 animate-spin" />
          </div>
          <div className="absolute -top-1 -right-1 h-5 w-5 rounded-full bg-sky-500 flex items-center justify-center">
            <Sparkles className="h-3 w-3 text-white" />
          </div>
        </div>
        <div className="text-center">
          <h2 className="text-xl font-bold text-slate-900 mb-1">
            Analyzing your data stack...
          </h2>
          <p className="text-sm text-slate-500">
            Fetching costs and finding optimization opportunities
          </p>
        </div>
        <div className="flex items-center gap-2">
          {Array.from(connectedKeys).map((key) => {
            const p = PLATFORMS.find((pl) => pl.key === key);
            return (
              <Badge
                key={key}
                variant="secondary"
                className="text-xs bg-sky-50 text-sky-700 border border-sky-200"
              >
                {p?.label || key}
              </Badge>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 max-w-2xl mx-auto">
      <div className="text-center">
        <div className="inline-flex h-14 w-14 rounded-2xl bg-green-100 items-center justify-center mb-4">
          <CheckCircle2 className="h-7 w-7 text-green-600" />
        </div>
        <h1 className="text-2xl font-bold text-slate-900 mb-2">
          You&apos;re all set!
        </h1>
        <p className="text-sm text-slate-500">
          Here&apos;s what we found across your connected platforms.
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-center">
          <div className="inline-flex h-10 w-10 rounded-lg bg-sky-50 items-center justify-center mb-3">
            <DollarSign className="h-5 w-5 text-sky-600" />
          </div>
          <p className="text-2xl font-bold text-slate-900">
            {result?.totalSpend
              ? formatCurrency(result.totalSpend)
              : "$--"}
          </p>
          <p className="text-xs text-slate-500 mt-1">Total spend found</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-center">
          <div className="inline-flex h-10 w-10 rounded-lg bg-purple-50 items-center justify-center mb-3">
            <BarChart3 className="h-5 w-5 text-purple-600" />
          </div>
          <p className="text-2xl font-bold text-slate-900">
            {result?.platformCount || 0}
          </p>
          <p className="text-xs text-slate-500 mt-1">Platforms connected</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-center">
          <div className="inline-flex h-10 w-10 rounded-lg bg-green-50 items-center justify-center mb-3">
            <TrendingDown className="h-5 w-5 text-green-600" />
          </div>
          <p className="text-2xl font-bold text-slate-900">
            {result?.savingsFound
              ? formatCurrency(result.savingsFound)
              : "$--"}
          </p>
          <p className="text-xs text-slate-500 mt-1">Potential savings</p>
        </div>
      </div>

      {/* Recommendations */}
      {result?.recommendations && result.recommendations.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
            <Zap className="h-4 w-4 text-amber-500" />
            Quick Wins
          </h2>
          <div className="space-y-2">
            {result.recommendations.map((rec, i) => (
              <div
                key={i}
                className="rounded-xl border border-slate-200 bg-white px-5 py-4 flex items-start gap-3"
              >
                <div className="h-8 w-8 rounded-lg bg-amber-50 flex items-center justify-center shrink-0 mt-0.5">
                  <Zap className="h-4 w-4 text-amber-600" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium text-sm text-slate-900">
                      {rec.title}
                    </p>
                    <Badge
                      variant="secondary"
                      className="bg-green-50 text-green-700 text-xs shrink-0"
                    >
                      Save {rec.savings}
                    </Badge>
                  </div>
                  {rec.description && (
                    <p className="text-xs text-slate-500 mt-1">
                      {rec.description}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CTA */}
      <div className="flex items-center justify-between pt-4">
        <Button variant="ghost" onClick={onBack} className="gap-2 text-slate-500">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
        <Button
          size="lg"
          onClick={() => router.push("/overview")}
          className="gap-2 bg-sky-600 hover:bg-sky-700 px-8"
        >
          Go to Dashboard
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ─── Progress Bar ──────────────────────────────────────────────────────────────

function ProgressBar({ step }: { step: number }) {
  const steps = [
    { num: 1, label: "Your Stack" },
    { num: 2, label: "Connect" },
    { num: 3, label: "Quick Wins" },
  ];

  return (
    <div className="flex items-center justify-center gap-2 mb-10">
      {steps.map((s, i) => (
        <div key={s.num} className="flex items-center gap-2">
          <div className="flex items-center gap-2">
            <div
              className={`h-8 w-8 rounded-full flex items-center justify-center text-sm font-bold transition-colors ${
                step >= s.num
                  ? "bg-sky-600 text-white"
                  : "bg-slate-100 text-slate-400"
              }`}
            >
              {step > s.num ? (
                <Check className="h-4 w-4" />
              ) : (
                s.num
              )}
            </div>
            <span
              className={`text-sm font-medium hidden sm:inline ${
                step >= s.num ? "text-slate-900" : "text-slate-400"
              }`}
            >
              {s.label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div
              className={`w-12 h-0.5 mx-1 rounded ${
                step > s.num ? "bg-sky-500" : "bg-slate-200"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const [step, setStep] = useState(1);
  const [selectedPlatforms, setSelectedPlatforms] = useState<Set<string>>(
    new Set()
  );
  const [connectedPlatforms, setConnectedPlatforms] = useState<Set<string>>(
    new Set()
  );

  const handleToggle = (key: string) => {
    setSelectedPlatforms((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const handleConnected = useCallback(() => {
    // Re-fetch connections to get the updated connected list
    api
      .get("/platforms")
      .then((res: unknown) => {
        const connections = res as { platform: string }[];
        setConnectedPlatforms(new Set(connections.map((c) => c.platform)));
      })
      .catch(() => {});
  }, []);

  return (
    <div className="min-h-[80vh] py-8 max-w-4xl mx-auto">
      <ProgressBar step={step} />

      {step === 1 && (
        <StepStack
          selected={selectedPlatforms}
          onToggle={handleToggle}
          onContinue={() => setStep(2)}
        />
      )}

      {step === 2 && (
        <StepConnect
          selectedKeys={selectedPlatforms}
          connectedKeys={connectedPlatforms}
          onConnected={handleConnected}
          onContinue={() => setStep(3)}
          onBack={() => setStep(1)}
        />
      )}

      {step === 3 && (
        <StepQuickWins
          connectedKeys={connectedPlatforms}
          onBack={() => setStep(2)}
        />
      )}
    </div>
  );
}
