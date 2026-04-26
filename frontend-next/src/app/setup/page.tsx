"use client";

import Link from "next/link";
import {
  DollarSign,
  Shield,
  Clock,
  Database,
  ChevronRight,
  ExternalLink,
  Terminal,
  Cpu,
  GitBranch,
  BarChart3,
  Zap,
  Cloud,
  CircleCheck,
} from "lucide-react";

// ───────────────────────────────────────────────────────────────────────────
// Platform catalog — grouped by category, AI first per the current pitch.
// Each entry links to /platforms (auth-gated) with its `key` preselected.
// ───────────────────────────────────────────────────────────────────────────

type Platform = {
  key: string;
  name: string;
  tracks: string;
  credentials: string;
  docsUrl?: string;
  setupMins: string;
};

type Category = {
  id: string;
  title: string;
  intro: string;
  icon: typeof Cpu;
  accent: string;
  platforms: Platform[];
};

const CATEGORIES: Category[] = [
  {
    id: "ai",
    title: "AI & LLM APIs",
    intro: "Per-model, per-workspace, cache-tier cost for the models your team actually uses.",
    icon: Cpu,
    accent: "from-violet-500 to-indigo-500",
    platforms: [
      {
        key: "anthropic",
        name: "Anthropic API",
        tracks: "API traffic per workspace / api_key / model / service_tier, with cache_read / cache_write_5m / cache_write_1h tokens broken out and batch/flex discounts applied.",
        credentials: "Admin API key from console.anthropic.com → Settings → Admin Keys (not your regular sk-ant key).",
        docsUrl: "https://platform.claude.com/docs/en/api/admin-api/usage-cost/get-messages-usage-report",
        setupMins: "2",
      },
      {
        key: "claude_code",
        name: "Claude Code",
        tracks: "Subscription (Max/Pro) usage invisible to the Admin API — parses local session transcripts under ~/.claude/projects/ and aggregates per day / project / model with full cache-tier split.",
        credentials: "Path to your ~/.claude/projects directory. Self-hosted only; complements the Anthropic API connector.",
        setupMins: "1",
      },
      {
        key: "openai",
        name: "OpenAI",
        tracks: "All 8 Usage buckets (completions, embeddings, moderations, images, audio, vector_stores, code_interpreter, fine-tune). Cached input, reasoning tokens, batch API 50% discount.",
        credentials: "Organization Admin API key + optional Org ID.",
        docsUrl: "https://platform.openai.com/docs/api-reference/usage",
        setupMins: "2",
      },
      {
        key: "gemini",
        name: "Gemini / Vertex AI",
        tracks: "Vertex AI + AI Studio usage via BigQuery Billing export. Context-tier pricing for 2.5 Pro, cached content, thinking tokens.",
        credentials: "Service account JSON + billing-export project and dataset. AI Studio key alone won't surface costs.",
        docsUrl: "https://cloud.google.com/billing/docs/how-to/export-data-bigquery-tables/standard-usage",
        setupMins: "5",
      },
    ],
  },
  {
    id: "pipelines",
    title: "Pipelines & Transforms",
    intro: "Where warehouse compute actually gets spent.",
    icon: GitBranch,
    accent: "from-emerald-500 to-teal-500",
    platforms: [
      {
        key: "dbt_cloud",
        name: "dbt Cloud",
        tracks: "Model-level spend via manifest + run_results, seats, and IDE session usage.",
        credentials: "dbt Cloud API token + account ID.",
        docsUrl: "https://docs.getdbt.com/docs/dbt-cloud-apis/overview",
        setupMins: "3",
      },
      {
        key: "fivetran",
        name: "Fivetran",
        tracks: "MAR (Monthly Active Rows) per connector + destination, sync-frequency, and historical credits burn.",
        credentials: "API key + API secret.",
        docsUrl: "https://fivetran.com/docs/rest-api",
        setupMins: "2",
      },
      {
        key: "airbyte",
        name: "Airbyte",
        tracks: "Connection volume (rows synced, bytes) per connection. Cloud and OSS supported.",
        credentials: "API token. Self-hosted needs host URL.",
        docsUrl: "https://reference.airbyte.com",
        setupMins: "2",
      },
    ],
  },
  {
    id: "warehouses",
    title: "Warehouses",
    intro: "Compute + storage + serverless credit lines across every major warehouse.",
    icon: Database,
    accent: "from-sky-500 to-cyan-500",
    platforms: [
      {
        key: "gcp",
        name: "BigQuery",
        tracks: "On-demand vs Editions detection, per-region + per-reservation slot-hour cost, active vs long-term storage, streaming, BI Engine. Multi-region supported.",
        credentials: "Service account JSON + project ID.",
        docsUrl: "https://cloud.google.com/bigquery/docs/information-schema-jobs",
        setupMins: "3",
      },
      {
        key: "databricks",
        name: "Databricks",
        tracks: "system.billing.usage + list_prices — per-SKU, per-cloud, per-job/cluster/notebook/warehouse attribution. Photon flagged. All origin products (JOBS, SQL, DLT, MODEL_SERVING, APPS, AGENT_BRICKS, etc.).",
        credentials: "Account ID + workspace URL + access token + SQL warehouse HTTP path.",
        docsUrl: "https://docs.databricks.com/en/admin/system-tables/billing.html",
        setupMins: "4",
      },
      {
        key: "snowflake",
        name: "Snowflake",
        tracks: "ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY (preferred) + ACCOUNT_USAGE fallback. Serverless credit lines (Snowpipe, Auto-Clustering, Search, QAS, Cortex), QUERY_ATTRIBUTION by user/role/query-tag, storage active + time-travel + failsafe.",
        credentials: "Key-pair auth: account identifier + user + PEM private key + optional role/warehouse.",
        docsUrl: "https://docs.snowflake.com/en/sql-reference/organization-usage/usage_in_currency_daily",
        setupMins: "5",
      },
      {
        key: "redshift",
        name: "Redshift",
        tracks: "Dedicated Redshift connector — SYS_QUERY_HISTORY per-query attribution, SYS_SERVERLESS_USAGE RPU-seconds, SYS_EXTERNAL_QUERY_DETAIL for Spectrum TB scanned, STL_CONCURRENCY_SCALING_USAGE beyond the 1-free-hour/day tier. Provisioned RA3/DC2 per-node-hour + Serverless per-RPU-hour both supported.",
        credentials: "AWS access key + secret + region + cluster_identifier (provisioned) or workgroup_name (serverless) + database + db_user (IAM auth) or secret_arn.",
        docsUrl: "https://docs.aws.amazon.com/redshift/latest/dg/sys-query-history.html",
        setupMins: "4",
      },
    ],
  },
  {
    id: "bi",
    title: "BI & Analytics",
    intro: "Per-dashboard + per-user cost, joined to the warehouse that actually runs the queries.",
    icon: BarChart3,
    accent: "from-indigo-500 to-purple-500",
    platforms: [
      {
        key: "looker",
        name: "Looker",
        tracks: "system__activity-based usage: per-dashboard, per-explore, per-user, PDT builds.",
        credentials: "Client ID + client secret + instance URL.",
        setupMins: "3",
      },
      {
        key: "tableau",
        name: "Tableau",
        tracks: "Admin Insights + REST /jobs for refresh history, per-workbook views, per-user seats.",
        credentials: "Server URL + personal access token (name + secret) + site ID.",
        setupMins: "3",
      },
      {
        key: "omni",
        name: "Omni",
        tracks: "Seat count + system activity queries.",
        credentials: "API key + instance URL.",
        setupMins: "2",
      },
    ],
  },
  {
    id: "infra",
    title: "Cloud & CI/CD",
    intro: "Cloud infrastructure and build minutes — the invisible line items.",
    icon: Cloud,
    accent: "from-amber-500 to-orange-500",
    platforms: [
      {
        key: "aws",
        name: "AWS",
        tracks: "21+ services through Cost Explorer. Compute, storage, databases, analytics, streaming, AI/ML, orchestration. Tag grouping optional.",
        credentials: "Access key + secret key + optional region. IAM policy scoped to Cost Explorer + service inventory reads.",
        docsUrl: "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/Welcome.html",
        setupMins: "4",
      },
      {
        key: "github",
        name: "GitHub Actions",
        tracks: "Runner minutes by OS/size, Packages, LFS, Copilot, Codespaces (enhanced billing API).",
        credentials: "Personal access token with read:org + admin:org billing scope.",
        setupMins: "2",
      },
      {
        key: "gitlab",
        name: "GitLab CI",
        tracks: "CI minutes per project with runner cost_factor applied, billable members, namespace storage.",
        credentials: "API token + instance URL + group ID.",
        setupMins: "2",
      },
    ],
  },
  {
    id: "quality",
    title: "Data Quality",
    intro: "Data observability tools that bill separately from the warehouse.",
    icon: Zap,
    accent: "from-teal-500 to-cyan-500",
    platforms: [
      {
        key: "monte_carlo",
        name: "Monte Carlo",
        tracks: "Monitored assets + monitors + incidents.",
        credentials: "API key ID + API token.",
        setupMins: "2",
      },
    ],
  },
];

const PRE_FLIGHT = [
  {
    icon: Shield,
    title: "Read-only, every connector",
    body: "Every credential costly asks for is scoped to billing / usage read endpoints. No writes, no schema changes, no data extraction.",
  },
  {
    icon: Clock,
    title: "Under 5 minutes per platform",
    body: "Most connectors take 2–3 minutes. Nothing requires a CSV export or an on-prem agent.",
  },
  {
    icon: CircleCheck,
    title: "Works without all platforms",
    body: "Connect just one and the dashboard lights up. Add more later — costs aggregate across everything.",
  },
];

function PlatformCard({ p }: { p: Platform }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 hover:border-indigo-300 hover:shadow-sm transition">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <div className="font-semibold text-slate-900 text-base">{p.name}</div>
          <div className="text-xs text-slate-500 mt-0.5">~{p.setupMins} min setup</div>
        </div>
        <Link
          href={`/platforms?add=${p.key}`}
          className="inline-flex items-center gap-1 px-3 py-1.5 bg-slate-900 hover:bg-slate-700 text-white text-xs font-semibold rounded-md whitespace-nowrap"
        >
          Connect
          <ChevronRight className="h-3 w-3" />
        </Link>
      </div>
      <div className="text-sm text-slate-600 leading-relaxed mb-3">{p.tracks}</div>
      <div className="text-xs text-slate-500 border-t border-slate-100 pt-3 leading-relaxed">
        <span className="font-medium text-slate-700">Credentials: </span>
        {p.credentials}
      </div>
      {p.docsUrl && (
        <a
          href={p.docsUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 mt-2"
        >
          Vendor docs
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  );
}

export default function SetupPage() {
  return (
    <div className="min-h-screen bg-white">
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 md:px-10 h-[60px] bg-white/95 backdrop-blur-md border-b border-slate-200">
        <Link
          href="/"
          className="flex items-center gap-2 text-lg font-extrabold text-slate-900 tracking-tight"
        >
          <DollarSign className="h-5 w-5 text-emerald-500" />
          costly
        </Link>
        <div className="hidden md:flex gap-6 items-center text-sm">
          <Link href="/" className="text-slate-500 hover:text-slate-900">Home</Link>
          <Link href="/pricing" className="text-slate-500 hover:text-slate-900">Pricing</Link>
          <a
            href="https://github.com/njain006/costly-oss"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-500 hover:text-slate-900"
          >
            GitHub
          </a>
          <Link
            href="/login"
            className="px-4 py-1.5 bg-slate-900 hover:bg-slate-700 text-white rounded-md font-semibold"
          >
            Get Started
          </Link>
        </div>
      </nav>

      <section className="pt-[100px] pb-14 px-6 bg-gradient-to-b from-slate-50 to-white">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-indigo-50 border border-indigo-200 rounded-full px-4 py-1.5 text-xs text-indigo-700 font-semibold uppercase tracking-wider mb-6">
            <Terminal className="h-3.5 w-3.5" />
            Setup Guide
          </div>
          <h1 className="text-4xl md:text-5xl font-extrabold text-slate-900 tracking-tight mb-5 leading-[1.1]">
            Connect your AI &amp; data stack
            <br />
            <span className="bg-gradient-to-r from-indigo-500 via-violet-500 to-purple-500 bg-clip-text text-transparent">
              in five minutes.
            </span>
          </h1>
          <p className="text-slate-600 text-lg max-w-2xl mx-auto leading-relaxed">
            17 connectors across AI APIs, pipelines, warehouses, BI, cloud, and CI/CD.
            Read-only, no ETL, no data leaves your accounts. Pick what you run and copy a
            credential. That&apos;s it.
          </p>
        </div>
      </section>

      <section className="px-6 pb-14">
        <div className="max-w-5xl mx-auto grid md:grid-cols-3 gap-4">
          {PRE_FLIGHT.map(({ icon: Icon, title, body }) => (
            <div key={title} className="rounded-xl border border-slate-200 bg-white p-5">
              <Icon className="h-5 w-5 text-indigo-500 mb-3" />
              <div className="font-semibold text-slate-900 mb-1">{title}</div>
              <div className="text-sm text-slate-600 leading-relaxed">{body}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="px-6 pb-20">
        <div className="max-w-5xl mx-auto space-y-14">
          {CATEGORIES.map((cat) => {
            const Icon = cat.icon;
            return (
              <div key={cat.id} id={cat.id}>
                <div className="flex items-center gap-3 mb-2">
                  <div
                    className={`h-9 w-9 rounded-lg bg-gradient-to-br ${cat.accent} flex items-center justify-center`}
                  >
                    <Icon className="h-4 w-4 text-white" />
                  </div>
                  <h2 className="text-2xl font-bold text-slate-900">{cat.title}</h2>
                </div>
                <p className="text-slate-500 text-sm mb-6 ml-12">{cat.intro}</p>
                <div className="grid md:grid-cols-2 gap-4">
                  {cat.platforms.map((p) => (
                    <PlatformCard key={p.key} p={p} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Snowflake detailed walkthrough — collapsed by default */}
      <section className="px-6 pb-14">
        <div className="max-w-4xl mx-auto">
          <details className="group rounded-xl border border-slate-200 bg-white overflow-hidden">
            <summary className="cursor-pointer px-6 py-4 font-semibold text-slate-900 hover:bg-slate-50 flex items-center justify-between">
              <span>Snowflake key-pair auth — full walkthrough</span>
              <ChevronRight className="h-4 w-4 text-slate-500 transition group-open:rotate-90" />
            </summary>
            <div className="px-6 pb-6 pt-2 space-y-5 text-sm text-slate-700 leading-relaxed">
              <p>
                Snowflake requires key-pair auth for read-only programmatic access. Costly never asks for
                a password. Run these four steps once on any machine with <code className="bg-slate-100 px-1 py-0.5 rounded">openssl</code>.
              </p>

              <div>
                <div className="font-semibold text-slate-900 mb-2">1. Generate a key pair locally</div>
                <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 text-xs overflow-x-auto leading-6">
{`openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub`}
                </pre>
              </div>

              <div>
                <div className="font-semibold text-slate-900 mb-2">
                  2. Assign the public key to a Snowflake user
                </div>
                <p className="mb-2 text-slate-600">
                  Strip the PEM header/footer and newlines from <code className="bg-slate-100 px-1 py-0.5 rounded">rsa_key.pub</code>, then run in Snowflake:
                </p>
                <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 text-xs overflow-x-auto leading-6">
{`CREATE USER IF NOT EXISTS costly_user
  TYPE = SERVICE
  DEFAULT_ROLE = costly_role
  RSA_PUBLIC_KEY = 'MIIBIjANBgkqh...<paste single-line pubkey>';`}
                </pre>
              </div>

              <div>
                <div className="font-semibold text-slate-900 mb-2">
                  3. Grant read access to ACCOUNT_USAGE
                </div>
                <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 text-xs overflow-x-auto leading-6">
{`CREATE ROLE IF NOT EXISTS costly_role;
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE costly_role;
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE costly_role;
GRANT ROLE costly_role TO USER costly_user;`}
                </pre>
                <p className="mt-2 text-slate-600 text-xs">
                  Replace <code className="bg-slate-100 px-1 py-0.5 rounded">COMPUTE_WH</code> with any warehouse the role can use for
                  ACCOUNT_USAGE queries. For org-level data (preferred),{" "}
                  <code className="bg-slate-100 px-1 py-0.5 rounded">GRANT APPLICATION ROLE ORGADMIN TO ROLE costly_role;</code> as well.
                </p>
              </div>

              <div>
                <div className="font-semibold text-slate-900 mb-2">4. Paste into costly</div>
                <ul className="list-disc ml-6 space-y-1 text-slate-600">
                  <li>
                    <span className="font-medium text-slate-800">Account identifier:</span> the portion of your Snowflake URL
                    before <code className="bg-slate-100 px-1 py-0.5 rounded">.snowflakecomputing.com</code> (e.g. <code className="bg-slate-100 px-1 py-0.5 rounded">xy12345.us-east-1</code>).
                  </li>
                  <li>
                    <span className="font-medium text-slate-800">User:</span> <code className="bg-slate-100 px-1 py-0.5 rounded">costly_user</code>
                  </li>
                  <li>
                    <span className="font-medium text-slate-800">Private key:</span> paste the full contents of{" "}
                    <code className="bg-slate-100 px-1 py-0.5 rounded">rsa_key.p8</code>, including the{" "}
                    <code className="bg-slate-100 px-1 py-0.5 rounded">BEGIN/END PRIVATE KEY</code> lines.
                  </li>
                  <li>
                    <span className="font-medium text-slate-800">Role:</span> <code className="bg-slate-100 px-1 py-0.5 rounded">costly_role</code>
                  </li>
                </ul>
              </div>

              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
                <span className="font-semibold">Note:</span> ACCOUNT_USAGE views have built-in latency of 45 min to 3 hours.
                First sync typically shows data in under 10 min, but may take longer on a fresh account.
              </div>
            </div>
          </details>
        </div>
      </section>

      <section className="px-6 pb-20">
        <div className="max-w-3xl mx-auto rounded-2xl border border-slate-200 bg-gradient-to-br from-indigo-50 to-violet-50 p-8 text-center">
          <h3 className="text-2xl font-bold text-slate-900 mb-3">Ready?</h3>
          <p className="text-slate-600 mb-6 leading-relaxed">
            Sign in and add your first connection. The dashboard fills in as soon as the first sync
            completes (usually within a minute).
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link
              href="/login"
              className="px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-lg shadow-sm"
            >
              Sign in
            </Link>
            <Link
              href="/demo"
              className="px-6 py-3 border border-slate-300 text-slate-700 hover:bg-white font-medium rounded-lg"
            >
              Try the demo first
            </Link>
          </div>
        </div>
      </section>

      <footer className="px-6 py-10 border-t border-slate-200 text-center text-xs text-slate-500">
        costly — open-source AI &amp; data cost intelligence ·{" "}
        <a
          href="https://github.com/njain006/costly-oss"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-slate-700"
        >
          github.com/njain006/costly-oss
        </a>
      </footer>
    </div>
  );
}
