import Link from "next/link";
import {
  BarChart3,
  DollarSign,
  Zap,
  Shield,
  ArrowRight,
  Database,
  Activity,
  TrendingDown,
  Clock,
  ChevronRight,
  Check,
  AlertTriangle,
  Layers,
  Eye,
  Bot,
  Bell,
  GitBranch,
  Cloud,
  Cpu,
  Sparkles,
  Github,
  Star,
} from "lucide-react";

const GITHUB_REPO_URL = "https://github.com/njain006/costly-oss";

/* ---------- data ---------- */

const HERO_STATS = [
  { value: "15+", label: "platforms connected" },
  { value: "<5 min", label: "to first insight" },
  { value: "100%", label: "read-only & safe" },
];

const PLATFORMS = [
  { name: "Anthropic", category: "AI", color: "rose" },
  { name: "OpenAI", category: "AI", color: "green" },
  { name: "Gemini", category: "AI", color: "purple" },
  { name: "dbt Cloud", category: "Transform", color: "emerald" },
  { name: "AWS", category: "Cloud", color: "amber" },
  { name: "BigQuery", category: "Warehouse", color: "blue" },
  { name: "Databricks", category: "Compute", color: "orange" },
  { name: "Snowflake", category: "Warehouse", color: "sky" },
  { name: "Looker", category: "BI", color: "indigo" },
  { name: "Tableau", category: "BI", color: "blue" },
  { name: "Omni", category: "BI", color: "violet" },
  { name: "Fivetran", category: "Ingest", color: "violet" },
  { name: "Airbyte", category: "Ingest", color: "cyan" },
  { name: "GitHub Actions", category: "CI/CD", color: "slate" },
  { name: "GitLab CI", category: "CI/CD", color: "orange" },
  { name: "Monte Carlo", category: "Quality", color: "teal" },
];

const FEATURES = [
  {
    icon: BarChart3,
    tag: "Dashboard",
    title: "Unified Cost Dashboard",
    tagColor: "text-indigo-400 bg-indigo-50",
    iconColor: "bg-indigo-50 text-indigo-500",
    description:
      "See every dollar across your entire data stack in one place. Break down spend by platform, team, pipeline, and time — no more switching between billing consoles.",
  },
  {
    icon: Bot,
    tag: "AI",
    title: "AI Cost Agent",
    tagColor: "text-violet-400 bg-violet-50",
    iconColor: "bg-violet-50 text-violet-500",
    description:
      "Ask questions in plain English. \u201cWhy did our AWS bill spike last Tuesday?\u201d or \u201cWhich dbt models are most expensive?\u201d — get instant, cited answers.",
  },
  {
    icon: Sparkles,
    tag: "Intelligence",
    title: "AI Spend Intelligence",
    tagColor: "text-amber-500 bg-amber-50",
    iconColor: "bg-amber-50 text-amber-500",
    description:
      "Cross-provider AI cost dashboard — compare OpenAI vs Anthropic vs Gemini. Token breakdowns, model-level costs, and migration recommendations.",
  },
  {
    icon: Database,
    tag: "Connectors",
    title: "Open-Source Connector Layer",
    tagColor: "text-emerald-500 bg-emerald-50",
    iconColor: "bg-emerald-50 text-emerald-500",
    description:
      "15 connectors for warehouses, pipelines, BI tools, AI models, and CI/CD. Read-only credentials. No agents or data extraction — we query APIs directly.",
  },
  {
    icon: AlertTriangle,
    tag: "Monitoring",
    title: "Anomaly Detection",
    tagColor: "text-rose-500 bg-rose-50",
    iconColor: "bg-rose-50 text-rose-500",
    description:
      "Catch cost spikes before they become surprise bills. Rolling-average baselines with per-platform thresholds alert you the moment something looks off.",
  },
  {
    icon: Bell,
    tag: "Alerts",
    title: "Budget Alerts",
    tagColor: "text-cyan-500 bg-cyan-50",
    iconColor: "bg-cyan-50 text-cyan-500",
    description:
      "Set daily, weekly, or monthly budget thresholds per platform or team. Get notified via Slack or email before you exceed targets.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    icon: Database,
    title: "Connect your platforms",
    description:
      "Add read-only credentials for any platform in your stack. OAuth where available, API keys otherwise. Each connector takes under 2 minutes.",
  },
  {
    step: "02",
    icon: BarChart3,
    title: "See everything in one dashboard",
    description:
      "Costs normalize into a unified model — warehouses, pipelines, BI seats, AI tokens, CI minutes — all in one place with consistent breakdowns.",
  },
  {
    step: "03",
    icon: Sparkles,
    title: "Act on AI-powered recommendations",
    description:
      "The AI agent surfaces specific optimizations with projected savings. Review, approve, and in some cases execute changes directly from the UI.",
  },
];

const PLATFORM_CATEGORIES = [
  {
    icon: Cpu,
    label: "AI & LLM APIs",
    platforms: "Claude, OpenAI, Gemini",
    color: "bg-violet-50 text-violet-500",
  },
  {
    icon: GitBranch,
    label: "Pipelines & Transforms",
    platforms: "dbt Cloud, Fivetran, Airbyte",
    color: "bg-emerald-50 text-emerald-500",
  },
  {
    icon: BarChart3,
    label: "BI & Analytics",
    platforms: "Looker, Tableau, Omni",
    color: "bg-indigo-50 text-indigo-500",
  },
  {
    icon: Cloud,
    label: "Data Warehouses",
    platforms: "BigQuery, Databricks, Snowflake",
    color: "bg-blue-50 text-blue-500",
  },
  {
    icon: Zap,
    label: "CI/CD & Cloud",
    platforms: "GitHub Actions, GitLab CI, AWS",
    color: "bg-amber-50 text-amber-600",
  },
  {
    icon: Shield,
    label: "Data Quality",
    platforms: "Monte Carlo",
    color: "bg-teal-50 text-teal-500",
  },
];

const TRUST_ITEMS = [
  {
    icon: Shield,
    title: "100% read-only",
    description: "We never write to your platforms. No risk of data modification.",
    color: "bg-emerald-50 text-emerald-500",
  },
  {
    icon: Clock,
    title: "5-minute setup",
    description: "Paste a credential, see data. No agents, no ETL, no infrastructure.",
    color: "bg-indigo-50 text-indigo-500",
  },
  {
    icon: Database,
    title: "No data extraction",
    description: "We query billing APIs directly. Your data never leaves your accounts.",
    color: "bg-violet-50 text-violet-500",
  },
  {
    icon: TrendingDown,
    title: "Open connector layer",
    description: "All 15 connectors are open source. Audit exactly what we query.",
    color: "bg-amber-50 text-amber-500",
  },
];

const colorMap: Record<string, string> = {
  sky: "bg-sky-500/10 text-sky-400 border-sky-500/20",
  blue: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  orange: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  amber: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  emerald: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  violet: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  cyan: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  green: "bg-green-500/10 text-green-400 border-green-500/20",
  rose: "bg-rose-500/10 text-rose-400 border-rose-500/20",
  purple: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  indigo: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
  slate: "bg-slate-500/10 text-slate-400 border-slate-500/20",
  teal: "bg-teal-500/10 text-teal-400 border-teal-500/20",
};

/* ---------- page ---------- */

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#FAFBFC]">
      {/* ── Nav ── */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 md:px-10 h-[60px] bg-[#0B1929]/95 backdrop-blur-md border-b border-white/5">
        <Link
          href="/"
          className="flex items-center gap-2 text-lg font-extrabold text-white tracking-tight"
        >
          <DollarSign className="h-5 w-5 text-emerald-400" />
          costly
        </Link>
        <div className="hidden md:flex gap-6 items-center">
          <a
            href="#features"
            className="text-slate-400 text-sm hover:text-white transition"
          >
            Features
          </a>
          <Link
            href="/pricing"
            className="text-slate-400 text-sm hover:text-white transition"
          >
            Pricing
          </Link>
          <Link
            href="/setup"
            className="text-slate-400 text-sm hover:text-white transition"
          >
            Docs
          </Link>
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-slate-400 text-sm hover:text-white transition"
            aria-label="Star costly on GitHub"
          >
            <Github className="h-4 w-4" />
            <span className="hidden lg:inline">GitHub</span>
          </a>
          <Link
            href="/login"
            className="px-4 py-1.5 border border-white/20 rounded-md text-slate-200 text-sm font-medium hover:border-white/40 transition"
          >
            Log in
          </Link>
          <Link
            href="/login"
            className="px-4 py-1.5 bg-indigo-600 rounded-md text-white text-sm font-semibold hover:bg-indigo-700 transition"
          >
            Get Started
          </Link>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="relative pt-[100px] pb-24 bg-[#0B1929] overflow-hidden">
        {/* subtle grid bg */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage:
              "url(\"data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\")",
          }}
        />
        {/* radial glow — warm indigo instead of sky */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-indigo-600/10 blur-[100px] rounded-full pointer-events-none" />

        <div className="relative max-w-5xl mx-auto px-6 text-center">
          {/* Eyebrow */}
          <div className="inline-flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/25 rounded-full px-4 py-1.5 text-xs text-indigo-300 font-semibold uppercase tracking-wider mb-6">
            <Github className="h-3.5 w-3.5" />
            Open Source · MIT · Self-Hostable
          </div>

          {/* Headline */}
          <h1 className="text-4xl sm:text-5xl md:text-[3.75rem] font-extrabold text-white tracking-tight leading-[1.1] mb-6">
            See every dollar your
            <br />
            <span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-purple-400 bg-clip-text text-transparent">
              AI and data stack costs
            </span>
          </h1>

          {/* Sub-headline */}
          <p className="text-lg md:text-xl text-slate-400 max-w-2xl mx-auto leading-relaxed mb-10">
            An open-source AI agent for your Claude, GPT, dbt, warehouse, and
            cloud bills. Connect 15+ platforms in minutes — self-host in 10, or
            use our cloud.
          </p>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
            <Link
              href="/demo"
              className="px-8 py-3.5 bg-indigo-600 rounded-lg text-white text-base font-bold hover:bg-indigo-700 transition shadow-lg shadow-indigo-500/30 flex items-center gap-2"
            >
              <Eye className="h-4 w-4" />
              Try Live Demo
            </Link>
            <a
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="px-8 py-3.5 border border-slate-700 rounded-lg text-slate-200 text-base font-medium hover:bg-slate-800/50 hover:border-slate-600 transition flex items-center gap-2"
            >
              <Star className="h-4 w-4" />
              Star on GitHub
              <ArrowRight className="h-4 w-4 opacity-60" />
            </a>
          </div>

          {/* Hero stats */}
          <div className="flex items-center justify-center gap-10 md:gap-16">
            {HERO_STATS.map(({ value, label }) => (
              <div key={label} className="text-center">
                <div className="text-2xl md:text-3xl font-extrabold text-white tracking-tight">
                  {value}
                </div>
                <div className="text-xs md:text-sm text-slate-500 mt-1">
                  {label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Product Mockup ── */}
      <section className="bg-[#0B1929] pb-20">
        <div className="relative max-w-5xl mx-auto px-6">
          <Link href="/demo" className="block group">
            <div className="rounded-xl border border-slate-700/60 bg-slate-900/80 shadow-2xl shadow-indigo-500/5 overflow-hidden group-hover:border-indigo-500/40 group-hover:shadow-indigo-500/15 transition-all">
              <div className="flex items-center gap-1.5 px-4 py-2.5 bg-slate-800/80 border-b border-slate-700/50">
                <div className="w-3 h-3 rounded-full bg-red-500/60" />
                <div className="w-3 h-3 rounded-full bg-amber-500/60" />
                <div className="w-3 h-3 rounded-full bg-emerald-500/60" />
                <span className="ml-3 text-xs text-slate-500 font-mono">
                  costly — Overview
                </span>
                <span className="ml-auto text-xs text-indigo-400 font-medium opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                  <Eye className="h-3 w-3" />
                  Click to try live demo
                </span>
              </div>
              <div className="p-6 md:p-8">
                {/* Mock top metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                  {[
                    { label: "Total MTD Spend", value: "$38,420", trend: "-11%", color: "text-emerald-400" },
                    { label: "Platforms Connected", value: "8", trend: "Active", color: "text-indigo-400" },
                    { label: "AI Recommendations", value: "12", trend: "New", color: "text-violet-400" },
                    { label: "Projected Savings", value: "$9,840/mo", trend: "15 actions", color: "text-amber-400" },
                  ].map((m) => (
                    <div
                      key={m.label}
                      className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/30"
                    >
                      <div className="text-xs text-slate-500 mb-1">{m.label}</div>
                      <div className="text-xl font-bold text-white">{m.value}</div>
                      <div className={`text-xs mt-1 font-medium ${m.color}`}>
                        {m.trend}
                      </div>
                    </div>
                  ))}
                </div>
                {/* Mock platform breakdown */}
                <div className="grid md:grid-cols-2 gap-4 mb-4">
                  <div className="bg-slate-800/30 rounded-lg border border-slate-700/20 p-4">
                    <div className="text-xs text-slate-500 mb-3 font-medium">Spend by Platform (MTD)</div>
                    {[
                      { name: "Anthropic", pct: 72, val: "$14.2K", color: "bg-rose-500" },
                      { name: "AWS", pct: 61, val: "$12.1K", color: "bg-amber-500" },
                      { name: "OpenAI", pct: 34, val: "$6.8K", color: "bg-emerald-500" },
                      { name: "dbt Cloud", pct: 18, val: "$3.5K", color: "bg-violet-500" },
                    ].map((p) => (
                      <div key={p.name} className="flex items-center gap-3 mb-2">
                        <div className="text-xs text-slate-400 w-24 shrink-0">{p.name}</div>
                        <div className="flex-1 bg-slate-700/40 rounded-full h-2">
                          <div className={`${p.color} h-2 rounded-full`} style={{ width: `${p.pct}%` }} />
                        </div>
                        <div className="text-xs text-slate-300 w-12 text-right">{p.val}</div>
                      </div>
                    ))}
                  </div>
                  <div className="bg-slate-800/30 rounded-lg border border-slate-700/20 p-4">
                    <div className="text-xs text-slate-500 mb-3 font-medium">Daily Spend (30 days)</div>
                    <div className="flex items-end justify-between gap-0.5 h-[88px]">
                      {[42, 55, 38, 71, 63, 48, 82, 61, 53, 76, 44, 39, 57, 50, 64, 73, 60, 46, 54, 69, 75, 63, 51, 58, 45, 66, 55, 49, 61, 70].map(
                        (h, i) => (
                          <div
                            key={i}
                            className="flex-1 bg-gradient-to-t from-indigo-600 to-violet-400 rounded-t-sm opacity-70"
                            style={{ height: `${h}%` }}
                          />
                        )
                      )}
                    </div>
                    <div className="flex items-center justify-between mt-1.5 text-[0.6rem] text-slate-600">
                      <span>30d ago</span>
                      <span>Today</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </Link>
        </div>
      </section>

      {/* ── Platforms Grid ── */}
      <section className="bg-[#0F2035] border-y border-white/5 py-16 px-6 overflow-hidden">
        <div className="max-w-5xl mx-auto">
          <p className="text-center text-xs font-bold uppercase tracking-widest text-slate-500 mb-8">
            15+ connectors across your entire data stack
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            {PLATFORMS.map(({ name, category, color }) => (
              <div
                key={name}
                className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium ${colorMap[color] ?? "bg-slate-500/10 text-slate-400 border-slate-500/20"}`}
              >
                <span>{name}</span>
                <span className="opacity-50">·</span>
                <span className="opacity-60">{category}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Platform Categories ── */}
      <section className="px-6 py-20 bg-[#FAFBFC]">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <div className="inline-block bg-indigo-500/10 border border-indigo-500/20 rounded-full px-4 py-1 text-xs text-indigo-500 font-semibold uppercase tracking-wider mb-4">
              Coverage
            </div>
            <h2 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight">
              Every layer of your data stack
            </h2>
            <p className="text-slate-500 mt-3 text-lg max-w-xl mx-auto">
              Warehouses, pipelines, BI, AI models, CI/CD — if it has a bill, costly tracks it.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 gap-5">
            {PLATFORM_CATEGORIES.map(({ icon: Icon, label, platforms, color }) => (
              <div
                key={label}
                className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:border-indigo-200 hover:shadow-md hover:shadow-indigo-500/5 transition-all"
              >
                <div className={`h-9 w-9 rounded-lg ${color.split(" ")[0]} flex items-center justify-center mb-3`}>
                  <Icon className={`h-5 w-5 ${color.split(" ")[1]}`} />
                </div>
                <div className="font-bold text-slate-900 text-sm mb-1">{label}</div>
                <div className="text-xs text-slate-500">{platforms}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="scroll-mt-20 px-6 py-20 bg-[#FAFBFC] border-t border-slate-200">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <div className="inline-block bg-violet-500/10 border border-violet-500/20 rounded-full px-4 py-1 text-xs text-violet-500 font-semibold uppercase tracking-wider mb-4">
              Platform Capabilities
            </div>
            <h2 className="text-3xl md:text-4xl font-extrabold text-slate-900 tracking-tight">
              Not just dashboards — actionable intelligence
            </h2>
            <p className="text-slate-500 mt-3 text-lg max-w-2xl mx-auto">
              costly connects your cost data across platforms and uses AI to surface
              what matters: where to cut, what to fix, and what to watch.
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            {FEATURES.map(({ icon: Icon, tag, title, description, tagColor, iconColor }) => (
              <div
                key={title}
                className="group rounded-xl border border-slate-200 bg-white p-6 hover:border-indigo-200 hover:shadow-md hover:shadow-indigo-500/5 transition-all"
              >
                <div className="flex items-start gap-4">
                  <div className={`h-10 w-10 shrink-0 rounded-lg ${iconColor.split(" ")[0]} flex items-center justify-center`}>
                    <Icon className={`h-5 w-5 ${iconColor.split(" ")[1]}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`text-[0.65rem] font-bold uppercase tracking-wider ${tagColor} px-2 py-0.5 rounded`}>
                        {tag}
                      </span>
                    </div>
                    <h3 className="text-base font-bold text-slate-900 mb-2">
                      {title}
                    </h3>
                    <p className="text-sm text-slate-600 leading-relaxed">
                      {description}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it Works ── */}
      <section className="px-6 py-20 bg-[#0B1929]">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <div className="inline-block bg-emerald-500/10 border border-emerald-500/20 rounded-full px-4 py-1 text-xs text-emerald-400 font-semibold uppercase tracking-wider mb-4">
              Getting Started
            </div>
            <h2 className="text-3xl md:text-4xl font-extrabold text-white tracking-tight">
              Connect. Analyze. Optimize.
            </h2>
            <p className="text-slate-400 mt-3 text-lg max-w-xl mx-auto">
              From zero to full data stack visibility in under 5 minutes.
            </p>
          </div>
          <div className="grid md:grid-cols-3 gap-8">
            {HOW_IT_WORKS.map(({ step, icon: Icon, title, description }) => (
              <div key={step} className="relative">
                <div className="flex items-center gap-3 mb-4">
                  <div className="text-4xl font-extrabold text-indigo-900 leading-none">
                    {step}
                  </div>
                  <div className="h-8 w-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
                    <Icon className="h-4 w-4 text-indigo-400" />
                  </div>
                </div>
                <h3 className="text-base font-bold text-white mb-2">{title}</h3>
                <p className="text-sm text-slate-400 leading-relaxed">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── AI Agent Highlight ── */}
      <section className="px-6 py-20 bg-[#FAFBFC] border-y border-slate-200">
        <div className="max-w-5xl mx-auto">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            <div>
              <div className="inline-block bg-violet-500/10 border border-violet-500/20 rounded-full px-4 py-1 text-xs text-violet-500 font-semibold uppercase tracking-wider mb-4">
                AI Cost Agent
              </div>
              <h2 className="text-3xl font-extrabold text-slate-900 tracking-tight mb-4">
                Ask your cost data anything
              </h2>
              <p className="text-slate-500 leading-relaxed mb-6">
                The AI agent has 15 tools — one per connector — and can answer complex
                cross-platform questions instantly. No SQL, no pivot tables, no
                switching between billing consoles.
              </p>
              <div className="space-y-3">
                {[
                  "Why did our spend spike last Tuesday?",
                  "Which dbt models cost the most this month?",
                  "Compare our Fivetran vs Airbyte costs",
                  "Show me all AI API spend by model",
                  "What are my top 5 optimization opportunities?",
                ].map((q) => (
                  <div
                    key={q}
                    className="flex items-center gap-2 text-sm text-slate-700"
                  >
                    <ChevronRight className="h-4 w-4 text-violet-400 shrink-0" />
                    <span className="italic text-slate-600">&ldquo;{q}&rdquo;</span>
                  </div>
                ))}
              </div>
            </div>
            {/* Mock chat UI */}
            <div className="rounded-xl bg-slate-900 border border-slate-700/60 overflow-hidden shadow-2xl">
              <div className="flex items-center gap-1.5 px-4 py-2.5 bg-slate-800/80 border-b border-slate-700/50">
                <div className="w-2.5 h-2.5 rounded-full bg-red-500/50" />
                <div className="w-2.5 h-2.5 rounded-full bg-amber-500/50" />
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/50" />
                <span className="ml-2 text-[0.65rem] text-slate-500 font-mono">
                  costly — AI Agent
                </span>
              </div>
              <div className="p-5 space-y-4">
                {/* User message */}
                <div className="flex justify-end">
                  <div className="bg-indigo-600 rounded-xl rounded-tr-sm px-4 py-2.5 max-w-[80%]">
                    <p className="text-sm text-white">
                      Why did our Claude spend spike last week?
                    </p>
                  </div>
                </div>
                {/* Agent response */}
                <div className="flex justify-start">
                  <div className="bg-slate-800 border border-slate-700/50 rounded-xl rounded-tl-sm px-4 py-3 max-w-[90%]">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Bot className="h-3.5 w-3.5 text-violet-400" />
                      <span className="text-[0.65rem] font-semibold text-violet-400 uppercase tracking-wider">costly AI</span>
                    </div>
                    <p className="text-sm text-slate-300 leading-relaxed mb-2">
                      Anthropic spend jumped <span className="text-amber-400 font-semibold">+58%</span> Mon–Thu. The driver is a <span className="text-rose-400 font-semibold">prompt-caching regression</span> — cache-hit rate fell from <span className="text-emerald-400 font-semibold">71%</span> to <span className="text-rose-400 font-semibold">12%</span> on your <code className="text-violet-300">sales-agent</code> workflow after last Tuesday&apos;s deploy. An extra 41M cache-write tokens cost <span className="text-amber-400 font-semibold">+$2.1K</span>.
                    </p>
                    <div className="flex items-center gap-2 mt-3 pt-3 border-t border-slate-700/40">
                      <div className="text-[0.65rem] text-emerald-400 font-medium bg-emerald-500/10 border border-emerald-500/20 rounded px-2 py-0.5">
                        Recommendation: Restore cache-friendly system prompt → est. $1,400/mo saved
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Trust Section ── */}
      <section className="px-6 py-20 bg-[#FAFBFC]">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <div className="inline-block bg-emerald-500/10 border border-emerald-500/20 rounded-full px-4 py-1 text-xs text-emerald-500 font-semibold uppercase tracking-wider mb-4">
              Built for Trust
            </div>
            <h2 className="text-3xl font-extrabold text-slate-900 tracking-tight">
              Safe, transparent, and auditable
            </h2>
          </div>
          <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-5">
            {TRUST_ITEMS.map(({ icon: Icon, title, description, color }) => (
              <div
                key={title}
                className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm text-center"
              >
                <div className={`h-10 w-10 rounded-lg ${color.split(" ")[0]} flex items-center justify-center mx-auto mb-3`}>
                  <Icon className={`h-5 w-5 ${color.split(" ")[1]}`} />
                </div>
                <div className="font-bold text-slate-900 text-sm mb-1.5">{title}</div>
                <div className="text-xs text-slate-500 leading-relaxed">{description}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Coverage Checklist ── */}
      <section className="px-6 py-20 bg-[#FAFBFC] border-t border-slate-200">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <div className="inline-block bg-amber-500/10 border border-amber-500/20 rounded-full px-4 py-1 text-xs text-amber-500 font-semibold uppercase tracking-wider mb-4">
              What costly tracks
            </div>
            <h2 className="text-3xl font-extrabold text-slate-900 tracking-tight">
              Full-stack cost visibility
            </h2>
            <p className="text-slate-500 mt-3 text-lg">
              Every category of data infrastructure spend, in one unified model.
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 overflow-hidden bg-white">
            {[
              { area: "AI & LLM API spend (per model, cache, service tier)", platforms: "Claude, OpenAI, Gemini" },
              { area: "Transformation runs (per model, per project)", platforms: "dbt Cloud" },
              { area: "Cloud infrastructure (21 services)", platforms: "AWS" },
              { area: "Warehouse compute & storage", platforms: "BigQuery, Databricks, Snowflake" },
              { area: "Data ingestion pipelines", platforms: "Fivetran, Airbyte" },
              { area: "BI tool licensing & usage", platforms: "Looker, Tableau, Omni" },
              { area: "CI/CD pipeline minutes", platforms: "GitHub Actions, GitLab CI" },
              { area: "Data quality monitoring", platforms: "Monte Carlo" },
            ].map(({ area, platforms }, i) => (
              <div
                key={area}
                className={`flex items-center justify-between px-6 py-4 ${
                  i > 0 ? "border-t border-slate-100" : ""
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className="h-6 w-6 rounded-full bg-emerald-50 flex items-center justify-center shrink-0">
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                  </div>
                  <span className="text-sm font-semibold text-slate-900">{area}</span>
                </div>
                <span className="text-xs font-medium text-slate-400 bg-slate-50 px-3 py-1 rounded-full shrink-0 ml-4 hidden sm:block">
                  {platforms}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Bottom CTA ── */}
      <section className="px-6 py-24 bg-[#0B1929] text-center relative overflow-hidden">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-indigo-600/10 blur-[80px] rounded-full pointer-events-none" />
        <div className="relative max-w-2xl mx-auto">
          <h2 className="text-3xl md:text-4xl font-extrabold text-white tracking-tight mb-4">
            Your data stack has one bill now.
          </h2>
          <p className="text-slate-400 text-lg mb-8 leading-relaxed">
            Connect your platforms in under 5 minutes. Explore the live demo first — no
            signup required.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/demo"
              className="px-10 py-3.5 bg-indigo-600 text-white rounded-lg text-base font-bold hover:bg-indigo-700 transition shadow-lg shadow-indigo-500/30 flex items-center gap-2"
            >
              <Eye className="h-4 w-4" />
              Try Live Demo
            </Link>
            <Link
              href="/login"
              className="px-10 py-3.5 border border-slate-700 text-slate-300 rounded-lg text-base font-medium hover:bg-slate-800/50 transition flex items-center gap-2"
            >
              Get Started Free
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="bg-[#0B1929] border-t border-white/5 px-6 py-10">
        <div className="max-w-5xl mx-auto">
          <div className="grid md:grid-cols-4 gap-8 mb-8">
            <div>
              <div className="flex items-center gap-2 text-white font-extrabold mb-3">
                <DollarSign className="h-4 w-4 text-emerald-400" />
                costly
              </div>
              <p className="text-sm text-slate-500 leading-relaxed">
                Multi-platform data cost intelligence. See every dollar your data stack
                costs — in one place.
              </p>
            </div>
            <div>
              <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                Product
              </div>
              <div className="space-y-2">
                <a
                  href="#features"
                  className="block text-sm text-slate-500 hover:text-slate-300 transition"
                >
                  Features
                </a>
                <Link
                  href="/pricing"
                  className="block text-sm text-slate-500 hover:text-slate-300 transition"
                >
                  Pricing
                </Link>
                <Link
                  href="/setup"
                  className="block text-sm text-slate-500 hover:text-slate-300 transition"
                >
                  Setup Guide
                </Link>
              </div>
            </div>
            <div>
              <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                Connectors
              </div>
              <div className="space-y-2">
                {["Anthropic", "OpenAI", "dbt Cloud", "AWS", "BigQuery"].map((p) => (
                  <span key={p} className="block text-sm text-slate-500">{p}</span>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                Resources
              </div>
              <div className="space-y-2">
                <Link
                  href="/demo"
                  className="block text-sm text-slate-500 hover:text-slate-300 transition"
                >
                  Live Demo
                </Link>
                <Link
                  href="/setup"
                  className="block text-sm text-slate-500 hover:text-slate-300 transition"
                >
                  Documentation
                </Link>
                <Link
                  href="/login"
                  className="block text-sm text-slate-500 hover:text-slate-300 transition"
                >
                  Sign In
                </Link>
              </div>
            </div>
          </div>
          <div className="border-t border-slate-800/60 pt-6 flex flex-col sm:flex-row items-center justify-center gap-3 text-xs text-slate-600">
            <span>costly &mdash; Open-source AI &amp; Data Cost Intelligence</span>
            <span className="hidden sm:inline">·</span>
            <a
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 hover:text-slate-400 transition"
            >
              <Github className="h-3.5 w-3.5" />
              github.com/njain006/costly-oss
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
