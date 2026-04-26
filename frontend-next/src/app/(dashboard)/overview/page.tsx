"use client";

import { useState, useMemo } from "react";
import { useApi } from "@/hooks/use-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import StatCard from "@/components/stat-card";
import { formatCurrency, formatNumber } from "@/lib/format";
import { COLORS, DATE_OPTIONS } from "@/lib/constants";
import {
  DollarSign,
  TrendingUp,
  Bot,
  Cloud,
  Database,
  GitBranch,
  Snowflake,
  Zap,
  ArrowUp,
  ArrowDown,
  Minus,
  AlertTriangle,
  MessageSquare,
  Lightbulb,
  Activity,
  Users,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  CartesianGrid,
  Legend,
  type PieLabelRenderProps,
} from "recharts";

// ─── Types ───────────────────────────────────────────────────────────────────

interface UnifiedCosts {
  total_cost: number;
  days: number;
  by_platform: { platform: string; cost: number }[];
  by_category: { category: string; cost: number }[];
  by_service: { service: string; platform: string; cost: number; trend: number }[];
  daily_trend: { date: string; cost: number; aws: number; snowflake: number; openai: number; other: number }[];
  top_resources: { platform: string; resource: string; cost: number; usage: number; trend: number }[];
  by_account?: {
    platform: string;
    connection_id: string | null;
    account_name: string;
    account_id: string;
    cost: number;
  }[];
  demo?: boolean;
}

interface AnomalyData {
  type: string;
  severity: string;
  platform: string;
  resource: string;
  date: string;
  cost: number;
  baseline: number;
  change_pct: number;
}

interface QuickWin {
  id: string;
  title: string;
  description: string;
  category: string;
  potential_savings: number | null;
  effort: string;
  priority: string;
}

interface PlatformHealth {
  id: string;
  platform: string;
  name: string;
  last_synced: string | null;
  created_at: string;
}

// ─── Label maps ──────────────────────────────────────────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  snowflake: "Snowflake",
  aws: "AWS",
  dbt_cloud: "dbt Cloud",
  anthropic: "Anthropic",
  gcp: "BigQuery",
  databricks: "Databricks",
  openai: "OpenAI",
  gemini: "Gemini",
  fivetran: "Fivetran",
  airbyte: "Airbyte",
  monte_carlo: "Monte Carlo",
  looker: "Looker",
  tableau: "Tableau",
  omni: "Omni",
  github: "GitHub Actions",
  gitlab: "GitLab CI",
};

const PLATFORM_ICONS: Record<string, typeof Cloud> = {
  snowflake: Snowflake,
  aws: Cloud,
  dbt_cloud: GitBranch,
  anthropic: Bot,
  openai: Bot,
  github: GitBranch,
  fivetran: Database,
};

const CATEGORY_LABELS: Record<string, string> = {
  compute: "Compute",
  storage: "Storage",
  transformation: "Transformation",
  ai_inference: "AI Inference",
  orchestration: "Orchestration",
  ingestion: "Ingestion",
  networking: "Networking",
  serving: "Serving",
  licensing: "Licensing",
  ci_cd: "CI/CD",
};

// ─── Demo data generators ────────────────────────────────────────────────────

function generateDemoTrend(days: number): UnifiedCosts["daily_trend"] {
  const result = [];
  const now = new Date();
  // Base costs per platform with slight daily variance
  const bases = { aws: 142, snowflake: 104, openai: 80, other: 95 };
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dateStr = d.toISOString().split("T")[0];
    // Weekend dips
    const isWeekend = d.getDay() === 0 || d.getDay() === 6;
    const weekendFactor = isWeekend ? 0.62 : 1.0;
    // Gradual growth trend
    const growthFactor = 1 + (days - i) * 0.003;
    // Random daily noise
    const noise = () => 0.85 + Math.random() * 0.3;
    const aws = Math.round(bases.aws * weekendFactor * growthFactor * noise());
    const snowflake = Math.round(bases.snowflake * weekendFactor * growthFactor * noise());
    const openai = Math.round(bases.openai * weekendFactor * growthFactor * noise());
    const other = Math.round(bases.other * weekendFactor * noise());
    result.push({ date: dateStr, cost: aws + snowflake + openai + other, aws, snowflake, openai, other });
  }
  return result;
}

function scaleDemoData(days: number) {
  // Scale costs relative to 30-day baseline
  const scale = days / 30;
  return {
    total_cost: Math.round(12847 * scale),
    days,
    demo: true,
    by_platform: [
      { platform: "aws", cost: Math.round(4200 * scale) },
      { platform: "snowflake", cost: Math.round(3100 * scale) },
      { platform: "openai", cost: Math.round(2400 * scale) },
      { platform: "dbt_cloud", cost: Math.round(1800 * scale) },
      { platform: "fivetran", cost: Math.round(890 * scale) },
      { platform: "github", cost: Math.round(457 * scale) },
    ],
    by_category: [
      { category: "compute", cost: Math.round(4820 * scale) },
      { category: "ai_inference", cost: Math.round(3240 * scale) },
      { category: "transformation", cost: Math.round(2100 * scale) },
      { category: "ingestion", cost: Math.round(1400 * scale) },
      { category: "storage", cost: Math.round(820 * scale) },
      { category: "ci_cd", cost: Math.round(467 * scale) },
    ],
    by_service: [
      { service: "EC2 Compute", platform: "aws", cost: Math.round(2140 * scale), trend: 4.2 },
      { service: "Snowflake Compute", platform: "snowflake", cost: Math.round(2080 * scale), trend: -1.8 },
      { service: "GPT-4o API", platform: "openai", cost: Math.round(1560 * scale), trend: 18.4 },
      { service: "dbt Jobs", platform: "dbt_cloud", cost: Math.round(1280 * scale), trend: 2.1 },
      { service: "S3 Storage", platform: "aws", cost: Math.round(820 * scale), trend: 1.4 },
      { service: "Fivetran Connectors", platform: "fivetran", cost: Math.round(740 * scale), trend: 0.0 },
      { service: "RDS Postgres", platform: "aws", cost: Math.round(690 * scale), trend: 0.8 },
      { service: "GitHub Actions", platform: "github", cost: Math.round(457 * scale), trend: 7.3 },
    ],
    by_account: [
      { platform: "aws", connection_id: "demo-aws-prod", account_name: "AWS Production", account_id: "111122223333", cost: Math.round(2800 * scale) },
      { platform: "aws", connection_id: "demo-aws-data", account_name: "AWS Data Platform", account_id: "444455556666", cost: Math.round(980 * scale) },
      { platform: "aws", connection_id: "demo-aws-sandbox", account_name: "AWS Sandbox", account_id: "777788889999", cost: Math.round(420 * scale) },
      { platform: "snowflake", connection_id: "demo-sf-prod", account_name: "Snowflake Prod", account_id: "xy12345", cost: Math.round(3100 * scale) },
      { platform: "openai", connection_id: "demo-openai", account_name: "OpenAI Main", account_id: "org-main", cost: Math.round(2400 * scale) },
    ],
    top_resources: [
      { platform: "aws", resource: "prod-analytics-cluster (EC2)", cost: Math.round(1420 * scale), usage: 487200, trend: 3.2 },
      { platform: "snowflake", resource: "TRANSFORM_WH (X-Large)", cost: Math.round(1190 * scale), usage: 210, trend: -4.1 },
      { platform: "openai", resource: "gpt-4o (production)", cost: Math.round(1060 * scale), usage: 4820000, trend: 22.7 },
      { platform: "dbt_cloud", resource: "prod_daily_refresh", cost: Math.round(840 * scale), usage: 180, trend: 0.9 },
      { platform: "openai", resource: "text-embedding-3-large", cost: Math.round(500 * scale), usage: 18200000, trend: 11.2 },
      { platform: "fivetran", resource: "salesforce → snowflake", cost: Math.round(480 * scale), usage: 0, trend: 0.0 },
      { platform: "aws", resource: "prod-rds-postgres (db.r6g.2xl)", cost: Math.round(460 * scale), usage: 720, trend: 1.5 },
      { platform: "github", resource: "CI/CD pipelines (ubuntu-latest)", cost: Math.round(390 * scale), usage: 2840, trend: 6.8 },
    ],
    daily_trend: generateDemoTrend(days),
  } as UnifiedCosts;
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

function TrendBadge({ pct }: { pct: number }) {
  if (Math.abs(pct) < 0.5) return <span className="flex items-center gap-0.5 text-xs text-slate-400"><Minus className="h-3 w-3" /> —</span>;
  if (pct > 0)
    return <span className="flex items-center gap-0.5 text-xs text-red-500 font-medium"><ArrowUp className="h-3 w-3" />{pct.toFixed(1)}%</span>;
  return <span className="flex items-center gap-0.5 text-xs text-emerald-500 font-medium"><ArrowDown className="h-3 w-3" />{Math.abs(pct).toFixed(1)}%</span>;
}

// Custom tooltip for stacked area chart
function StackedTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + p.value, 0);
  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-xs">
      <div className="font-semibold text-slate-700 mb-2">
        {label ? new Date(label).toLocaleDateString("en", { weekday: "short", month: "short", day: "numeric" }) : ""}
      </div>
      {[...payload].reverse().map((p) => (
        <div key={p.name} className="flex items-center justify-between gap-4 mb-1">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full inline-block" style={{ backgroundColor: p.color }} />
            <span className="text-slate-600">{p.name}</span>
          </span>
          <span className="font-medium text-slate-800">{formatCurrency(p.value)}</span>
        </div>
      ))}
      <div className="border-t border-slate-100 mt-2 pt-2 flex justify-between font-semibold text-slate-800">
        <span>Total</span>
        <span>{formatCurrency(total)}</span>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OverviewPage() {
  const [days, setDays] = useState(30);
  const { data: liveData, loading } = useApi<UnifiedCosts>(`/platforms/costs?days=${days}`, [days]);
  const { data: anomalies } = useApi<AnomalyData[]>(liveData && !liveData.demo ? `/anomalies?days=${days}` : null, [days, liveData]);
  const { data: quickWins } = useApi<QuickWin[]>(liveData && !liveData.demo ? '/recommendations' : null, [liveData]);
  const { data: platforms } = useApi<PlatformHealth[]>(liveData && !liveData.demo ? '/platforms' : null, [liveData]);
  const { data: aiCosts } = useApi<{
    kpis: { cache_hit_rate: number; cache_savings_usd: number; cache_read_tokens: number; cache_write_tokens: number };
  }>(liveData && !liveData.demo ? `/ai-costs?days=${days}` : null, [days, liveData]);

  // Show empty state only when no platforms are connected (demo flag from backend)
  const hasData = liveData && !liveData.demo;
  const data: UnifiedCosts | null = useMemo(
    () => (hasData ? liveData! : null),
    [hasData, liveData]
  );

  // Donut chart label renderer
  const renderCustomLabel = (props: PieLabelRenderProps) => {
    const { cx, cy, midAngle, innerRadius, outerRadius, percent } = props;
    if ((percent ?? 0) < 0.05) return null;
    const RADIAN = Math.PI / 180;
    const ir = Number(innerRadius ?? 0);
    const or = Number(outerRadius ?? 0);
    const ma = Number(midAngle ?? 0);
    const r = ir + (or - ir) * 0.5;
    const x = Number(cx ?? 0) + r * Math.cos(-ma * RADIAN);
    const y = Number(cy ?? 0) + r * Math.sin(-ma * RADIAN);
    return (
      <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600}>
        {`${((percent ?? 0) * 100).toFixed(0)}%`}
      </text>
    );
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-8 w-40" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24 rounded-lg" />)}
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          <Skeleton className="md:col-span-2 h-80 rounded-lg" />
          <Skeleton className="h-80 rounded-lg" />
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          <Skeleton className="h-72 rounded-lg" />
          <Skeleton className="h-72 rounded-lg" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Platform Overview</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Unified cost intelligence across all connected data platforms
          </p>
        </div>
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <div className="h-14 w-14 rounded-full bg-slate-100 flex items-center justify-center mb-4">
              <Database className="h-7 w-7 text-slate-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 mb-2">No platforms connected</h2>
            <p className="text-sm text-slate-500 max-w-md mb-6">
              Connect your data platforms to see real cost data. Costly supports AWS, Snowflake, OpenAI, Anthropic, dbt Cloud, and 10 more.
            </p>
            <Button onClick={() => window.location.href = "/settings"} className="gap-2">
              <Zap className="h-4 w-4" />
              Connect a Platform
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const dailyAvg = data.total_cost / (data.days || 1);
  const aiCost = data.by_category.find((c) => c.category === "ai_inference")?.cost ?? 0;
  const aiPct = data.total_cost > 0 ? (aiCost / data.total_cost) * 100 : 0;

  const firstHalf = data.daily_trend.slice(0, Math.floor(data.daily_trend.length / 2));
  const secondHalf = data.daily_trend.slice(Math.floor(data.daily_trend.length / 2));
  const firstHalfTotal = firstHalf.reduce((s, d) => s + d.cost, 0);
  const secondHalfTotal = secondHalf.reduce((s, d) => s + d.cost, 0);
  const momChange = firstHalfTotal > 0 ? ((secondHalfTotal - firstHalfTotal) / firstHalfTotal) * 100 : 0;

  return (
    <div className="space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Platform Overview</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Unified cost intelligence across all connected data platforms
          </p>
        </div>
        <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
          {DATE_OPTIONS.map((opt) => (
            <Button
              key={opt.value}
              variant={days === opt.value ? "default" : "ghost"}
              size="sm"
              className="h-7 px-3 text-xs"
              onClick={() => setDays(opt.value)}
            >
              {opt.label}
            </Button>
          ))}
        </div>
      </div>

      {/* KPI Cards — 6 tiles (adds Cache Hit Rate, our wedge vs Vantage/CloudZero) */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard
          title="Total Spend"
          value={formatCurrency(data.total_cost)}
          icon={DollarSign}
          description={`Last ${days} days`}
        />
        <StatCard
          title="Daily Average"
          value={formatCurrency(dailyAvg)}
          icon={TrendingUp}
          description={`${data.by_platform.length} platforms`}
        />
        <StatCard
          title="AI Spend"
          value={formatCurrency(aiCost)}
          icon={Bot}
          description={`${aiPct.toFixed(1)}% of total`}
        />
        <StatCard
          title="Cache Hit Rate"
          value={aiCosts?.kpis ? `${aiCosts.kpis.cache_hit_rate.toFixed(1)}%` : "—"}
          icon={Activity}
          description={aiCosts?.kpis ? `~${formatCurrency(aiCosts.kpis.cache_savings_usd)} saved` : "No AI data yet"}
        />
        <StatCard
          title="Top Category"
          value="AI Inference"
          icon={Zap}
          description={formatCurrency(aiCost)}
        />
        <StatCard
          title="Period Trend"
          value={`${momChange >= 0 ? '+' : ''}${momChange.toFixed(1)}%`}
          icon={momChange >= 0 ? ArrowUp : ArrowDown}
          description={`vs prior ${Math.floor(days / 2)}d`}
        />
      </div>

      {/* Row 1: Daily Trend (stacked area) + Platform Donut */}
      <div className="grid md:grid-cols-3 gap-4">

        {/* Daily Spend Trend — stacked area by platform */}
        <Card className="md:col-span-2">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-slate-700">Daily Spend Trend</CardTitle>
              <span className="text-xs text-slate-400">By platform, last {days} days</span>
            </div>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={data.daily_trend} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(d) => new Date(d).toLocaleDateString("en", { month: "short", day: "numeric" })}
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                  interval={Math.ceil(days / 8) - 1}
                />
                <YAxis
                  tickFormatter={(v) => `$${v}`}
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                  width={55}
                />
                <Tooltip content={<StackedTooltip />} />
                <Legend
                  iconType="circle"
                  iconSize={8}
                  wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                />
                <Area type="monotone" dataKey="aws" name="AWS" stackId="1"
                  stroke={COLORS.chart[0]} fill={COLORS.chart[0]} fillOpacity={0.8} />
                <Area type="monotone" dataKey="snowflake" name="Snowflake" stackId="1"
                  stroke={COLORS.chart[1]} fill={COLORS.chart[1]} fillOpacity={0.8} />
                <Area type="monotone" dataKey="openai" name="OpenAI" stackId="1"
                  stroke={COLORS.chart[2]} fill={COLORS.chart[2]} fillOpacity={0.8} />
                <Area type="monotone" dataKey="other" name="Other" stackId="1"
                  stroke={COLORS.chart[3]} fill={COLORS.chart[3]} fillOpacity={0.6} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Platform Donut */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700">By Platform</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={190}>
              <PieChart>
                <Pie
                  data={data.by_platform}
                  dataKey="cost"
                  nameKey="platform"
                  cx="50%"
                  cy="50%"
                  innerRadius={52}
                  outerRadius={82}
                  paddingAngle={2}
                  labelLine={false}
                  label={renderCustomLabel}
                >
                  {data.by_platform.map((_, i) => (
                    <Cell key={i} fill={COLORS.chart[i % COLORS.chart.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => formatCurrency(Number(v))} />
              </PieChart>
            </ResponsiveContainer>
            <div className="space-y-1.5 mt-1">
              {data.by_platform.map((p, i) => {
                const pct = data.total_cost > 0 ? (p.cost / data.total_cost) * 100 : 0;
                return (
                  <div key={p.platform} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2 min-w-0">
                      <div
                        className="h-2.5 w-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: COLORS.chart[i % COLORS.chart.length] }}
                      />
                      <span className="text-slate-600 truncate">{PLATFORM_LABELS[p.platform] || p.platform}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0 ml-2">
                      <span className="font-semibold text-slate-800">{formatCurrency(p.cost)}</span>
                      <span className="text-slate-400 w-8 text-right">{pct.toFixed(0)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Row 2: By Category (horizontal bars) + By Service (table) */}
      <div className="grid md:grid-cols-2 gap-4">

        {/* By Category */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700">By Category</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={data.by_category} layout="vertical" margin={{ top: 0, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                <XAxis
                  type="number"
                  tickFormatter={(v) => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`}
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                />
                <YAxis
                  type="category"
                  dataKey="category"
                  tickFormatter={(c) => CATEGORY_LABELS[c] || c}
                  tick={{ fontSize: 11 }}
                  stroke="#94a3b8"
                  width={96}
                />
                <Tooltip
                  formatter={(v) => [formatCurrency(Number(v)), "Cost"]}
                  labelFormatter={(c) => CATEGORY_LABELS[c] || c}
                />
                <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                  {data.by_category.map((_, i) => (
                    <Cell key={i} fill={COLORS.chart[i % COLORS.chart.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* By Service — mini table */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700">By Service</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-0">
              {/* Header row */}
              <div className="grid grid-cols-12 pb-2 border-b border-slate-100 text-xs font-medium text-slate-400 uppercase tracking-wide">
                <span className="col-span-5">Service</span>
                <span className="col-span-3">Platform</span>
                <span className="col-span-2 text-right">Cost</span>
                <span className="col-span-2 text-right">Trend</span>
              </div>
              {data.by_service.map((s, i) => (
                <div key={i} className="grid grid-cols-12 items-center py-2 border-b border-slate-50 last:border-0 text-sm">
                  <span className="col-span-5 text-slate-800 font-medium truncate pr-2">{s.service}</span>
                  <span className="col-span-3 text-slate-500 text-xs truncate">{PLATFORM_LABELS[s.platform] || s.platform}</span>
                  <span className="col-span-2 text-right font-semibold text-slate-800">{formatCurrency(s.cost)}</span>
                  <span className="col-span-2 flex justify-end"><TrendBadge pct={s.trend} /></span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Row 2.5: By Account — multi-account breakdown (AWS orgs, Snowflake accounts, AI orgs) */}
      {data.by_account && data.by_account.length > 1 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                <Users className="h-4 w-4 text-sky-500" />
                By Account
              </CardTitle>
              <span className="text-xs text-slate-400">
                {data.by_account.length} account{data.by_account.length === 1 ? "" : "s"} across{" "}
                {new Set(data.by_account.map((a) => a.platform)).size} platform
                {new Set(data.by_account.map((a) => a.platform)).size === 1 ? "" : "s"}
              </span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-0">
              {/* Header row */}
              <div className="grid grid-cols-12 pb-2 border-b border-slate-100 text-xs font-medium text-slate-400 uppercase tracking-wide">
                <span className="col-span-5">Account</span>
                <span className="col-span-2">Platform</span>
                <span className="col-span-3">Account ID</span>
                <span className="col-span-2 text-right">Cost</span>
              </div>
              {data.by_account.map((a, i) => {
                const Icon = PLATFORM_ICONS[a.platform] || Database;
                const pct = data.total_cost > 0 ? (a.cost / data.total_cost) * 100 : 0;
                return (
                  <div
                    key={`${a.platform}-${a.connection_id ?? a.account_id}-${i}`}
                    className="grid grid-cols-12 items-center py-2.5 border-b border-slate-50 last:border-0 text-sm"
                  >
                    <div className="col-span-5 flex items-center gap-2.5 min-w-0 pr-2">
                      <div className="h-7 w-7 rounded-md bg-slate-100 flex items-center justify-center shrink-0">
                        <Icon className="h-4 w-4 text-slate-500" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-slate-900 truncate">
                          {a.account_name || "Unknown"}
                        </div>
                        <div className="text-xs text-slate-400">{pct.toFixed(1)}% of total</div>
                      </div>
                    </div>
                    <span className="col-span-2 text-xs text-slate-500 truncate">
                      {PLATFORM_LABELS[a.platform] || a.platform}
                    </span>
                    <span className="col-span-3 text-xs text-slate-400 font-mono truncate">
                      {a.account_id || "—"}
                    </span>
                    <span className="col-span-2 text-right font-semibold text-slate-800">
                      {formatCurrency(a.cost)}
                    </span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Row 3: Top Cost Drivers */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold text-slate-700">Top Cost Drivers</CardTitle>
            <span className="text-xs text-slate-400">% of total spend</span>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-0">
            {data.top_resources.map((r, i) => {
              const Icon = PLATFORM_ICONS[r.platform] || Database;
              const pct = data.total_cost > 0 ? (r.cost / data.total_cost) * 100 : 0;
              return (
                <div key={i} className="flex items-center gap-3 py-2.5 border-b border-slate-50 last:border-0">
                  {/* Rank */}
                  <span className="text-xs font-medium text-slate-300 w-5 shrink-0 text-right">{i + 1}</span>

                  {/* Platform icon */}
                  <div className="h-7 w-7 rounded-md bg-slate-100 flex items-center justify-center shrink-0">
                    <Icon className="h-4 w-4 text-slate-500" />
                  </div>

                  {/* Resource name + platform */}
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-900 truncate">{r.resource}</div>
                    <div className="text-xs text-slate-400">
                      {PLATFORM_LABELS[r.platform] || r.platform}
                      {r.usage > 0 && ` · ${formatNumber(r.usage)} units`}
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="w-24 shrink-0 hidden sm:block">
                    <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(pct * 3, 100)}%`,
                          backgroundColor: COLORS.chart[i % COLORS.chart.length],
                        }}
                      />
                    </div>
                  </div>

                  {/* Cost + pct */}
                  <div className="text-right shrink-0 ml-2">
                    <div className="text-sm font-semibold text-slate-900">{formatCurrency(r.cost)}</div>
                    <div className="text-xs text-slate-400">{pct.toFixed(1)}%</div>
                  </div>

                  {/* Trend */}
                  <div className="shrink-0 w-14 flex justify-end">
                    <TrendBadge pct={r.trend} />
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Row 4: Anomalies */}
      {anomalies && anomalies.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-500" />
                Cost Anomalies
              </CardTitle>
              <span className="text-xs text-slate-400">{anomalies.length} detected</span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-3">
              {anomalies.slice(0, 6).map((a, i) => (
                <div key={i} className={`p-3 rounded-lg border ${a.severity === 'high' ? 'bg-red-50 border-red-200' : 'bg-amber-50 border-amber-200'}`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className={`text-xs font-semibold uppercase ${a.severity === 'high' ? 'text-red-600' : 'text-amber-600'}`}>{a.severity}</span>
                    <span className="text-xs text-slate-500">{a.date}</span>
                  </div>
                  <div className="text-sm font-medium text-slate-800 truncate">{a.resource || a.platform}</div>
                  <div className="flex items-center justify-between mt-1.5">
                    <span className="text-xs text-slate-500">{formatCurrency(a.baseline)} baseline</span>
                    <span className="text-xs font-semibold text-red-600">+{a.change_pct.toFixed(0)}%</span>
                  </div>
                  <button
                    onClick={() => window.location.href = `/chat?q=Why did ${a.resource || a.platform} costs spike on ${a.date}?`}
                    className="mt-2 text-xs text-sky-600 hover:text-sky-700 font-medium flex items-center gap-1"
                  >
                    <MessageSquare className="h-3 w-3" />
                    Ask Expert
                  </button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Row 5: Quick Wins */}
      {quickWins && quickWins.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                <Lightbulb className="h-4 w-4 text-amber-500" />
                Quick Wins
              </CardTitle>
              <Button variant="ghost" size="sm" className="h-7 text-xs text-sky-600" onClick={() => window.location.href = '/recommendations'}>
                View all
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid md:grid-cols-3 gap-3">
              {quickWins
                .filter((r) => r.priority === 'high' || r.potential_savings)
                .slice(0, 3)
                .map((r) => (
                  <div key={r.id} className="p-3 bg-slate-50 rounded-lg border border-slate-200">
                    <div className="flex items-center gap-2 mb-1.5">
                      <Badge variant={r.priority === 'high' ? 'destructive' : 'secondary'} className="text-[10px] h-5">{r.priority}</Badge>
                      <Badge variant="outline" className="text-[10px] h-5">{r.effort}</Badge>
                    </div>
                    <div className="text-sm font-medium text-slate-800 mb-1">{r.title}</div>
                    <div className="text-xs text-slate-500 line-clamp-2">{r.description}</div>
                    {r.potential_savings && r.potential_savings > 0 && (
                      <div className="mt-2 text-sm font-semibold text-emerald-600">
                        Save ~{formatCurrency(r.potential_savings)}/mo
                      </div>
                    )}
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Row 6: Platform Health */}
      {platforms && platforms.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
              <Activity className="h-4 w-4 text-sky-500" />
              Platform Health
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {platforms.map((p) => {
                const lastSync = p.last_synced ? new Date(p.last_synced) : null;
                const hoursAgo = lastSync ? (Date.now() - lastSync.getTime()) / (1000 * 60 * 60) : null;
                const isStale = hoursAgo !== null && hoursAgo > 24;
                const isFresh = hoursAgo !== null && hoursAgo <= 1;
                return (
                  <div key={p.id} className={`p-3 rounded-lg border ${isStale ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium text-slate-800">{PLATFORM_LABELS[p.platform] || p.platform}</span>
                      <div className={`h-2 w-2 rounded-full ${isFresh ? 'bg-emerald-400' : isStale ? 'bg-amber-400' : 'bg-slate-300'}`} />
                    </div>
                    <div className="text-xs text-slate-500 truncate">{p.name}</div>
                    <div className={`text-xs mt-1 ${isStale ? 'text-amber-600 font-medium' : 'text-slate-400'}`}>
                      {lastSync ? (hoursAgo! < 1 ? 'Just now' : hoursAgo! < 24 ? `${Math.round(hoursAgo!)}h ago` : `${Math.round(hoursAgo! / 24)}d ago`) : 'Never synced'}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
