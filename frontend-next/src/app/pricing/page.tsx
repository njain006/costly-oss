import Link from "next/link";
import { DollarSign, Check, Github } from "lucide-react";

const FEATURES = [
  "Unlimited platform connections",
  "15+ connectors (AWS, Snowflake, Databricks, dbt Cloud, OpenAI, and more)",
  "AI expert agents (per-platform cost specialists)",
  "Smart cost recommendations with dollar estimates",
  "Anomaly detection & alerts",
  "Slack & email notifications",
  "Cost attribution by team & project",
  "90-day data retention",
  "Self-hosted — your data stays in your infrastructure",
  "100% open source (MIT license)",
];

const FAQ = [
  {
    q: "Which platforms does Costly support?",
    a: "Costly connects to 15+ data platforms including AWS (21 services), Snowflake, BigQuery, Databricks, dbt Cloud, Fivetran, Airbyte, OpenAI, Anthropic, Gemini, GitHub Actions, Looker, Tableau, Monte Carlo, and more.",
  },
  {
    q: "Is it really free?",
    a: "Yes. Costly is 100% open source under the MIT license. Self-host it on your own infrastructure at no cost. No paid tiers, no feature gates, no usage limits.",
  },
  {
    q: "Do you store my API keys or credentials?",
    a: "Credentials are encrypted with AES-256 (Fernet) before being stored. Since you self-host, everything stays in your own database — nothing leaves your infrastructure.",
  },
  {
    q: "How long does setup take?",
    a: "Most connectors are live in under 2 minutes. You provide read-only API keys or OAuth credentials, and Costly starts pulling cost data immediately.",
  },
  {
    q: "Does Costly modify anything in my platforms?",
    a: "No. Costly is fully read-only across all connectors. When the AI agent recommends an optimization, it shows you exactly what to do — you decide whether to act.",
  },
  {
    q: "What are expert agents?",
    a: "Each platform gets a dedicated AI cost specialist loaded with deep billing knowledge — pricing models, gotchas, optimization patterns. Ask about Snowflake costs and you get a Snowflake billing expert, not a generic chatbot.",
  },
];

export default function PricingPage() {
  return (
    <div className="bg-white min-h-screen">
      {/* Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 md:px-10 h-[60px] bg-[#0B1929]/95 backdrop-blur-md border-b border-white/5">
        <Link
          href="/"
          className="flex items-center gap-2 text-lg font-extrabold text-white tracking-tight"
        >
          <DollarSign className="h-5 w-5 text-indigo-400" />
          costly
        </Link>
        <div className="hidden md:flex gap-6 items-center">
          <Link href="/#features" className="text-slate-400 text-sm hover:text-white transition">Features</Link>
          <Link href="/pricing" className="text-indigo-400 text-sm font-semibold">Pricing</Link>
          <Link href="/setup" className="text-slate-400 text-sm hover:text-white transition">Docs</Link>
          <Link href="/login" className="px-4 py-1.5 border border-white/20 rounded-md text-slate-200 text-sm font-medium hover:border-white/40 transition">Log in</Link>
          <Link href="/login" className="px-4 py-1.5 bg-indigo-600 rounded-md text-white text-sm font-semibold hover:bg-indigo-700 transition">Get Started</Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-28 pb-14 text-center bg-[#0B1929]">
        <div className="inline-block bg-emerald-500/10 border border-emerald-500/25 rounded-full px-4 py-1 text-xs text-emerald-400 font-semibold uppercase tracking-wider mb-4">
          Free & Open Source
        </div>
        <h1 className="text-4xl md:text-5xl font-extrabold text-white tracking-tight mb-4">
          $0. No catch.
        </h1>
        <p className="text-slate-400 text-lg max-w-xl mx-auto">
          Costly is 100% free and open source. Self-host it, own your data,
          and get AI-powered cost intelligence across your entire data stack.
        </p>
      </section>

      {/* Single pricing card */}
      <section className="bg-[#0B1929] px-6 pb-24">
        <div className="max-w-lg mx-auto">
          <div className="relative rounded-2xl p-8 bg-gradient-to-b from-indigo-950 to-[#0B1929] border-2 border-indigo-500 shadow-xl shadow-indigo-500/20">
            <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
              <span className="inline-block bg-emerald-500 text-white text-xs font-bold px-3 py-1 rounded-full shadow-lg shadow-emerald-500/30">
                Everything Included
              </span>
            </div>

            <div className="mb-6 text-center">
              <div className="flex items-baseline gap-1 justify-center mb-2">
                <span className="text-5xl font-extrabold tracking-tight text-white">$0</span>
                <span className="text-slate-400 text-sm">/forever</span>
              </div>
              <p className="text-slate-400 text-sm">
                Self-hosted. No limits. No credit card.
              </p>
            </div>

            <div className="h-px bg-white/10 mb-6" />

            <ul className="space-y-3 mb-8">
              {FEATURES.map((f) => (
                <li key={f} className="flex items-start gap-2.5 text-sm text-slate-300">
                  <Check className="h-4 w-4 mt-0.5 shrink-0 text-emerald-400" />
                  {f}
                </li>
              ))}
            </ul>

            <div className="space-y-3">
              <Link
                href="/login"
                className="block w-full text-center py-3 rounded-lg text-sm font-bold bg-indigo-600 text-white hover:bg-indigo-700 transition shadow-lg shadow-indigo-500/30"
              >
                Get Started Free &rarr;
              </Link>
              <a
                href="https://github.com/njain006/costly-oss"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 w-full py-3 rounded-lg text-sm font-semibold bg-white/10 text-white hover:bg-white/15 border border-white/10 transition"
              >
                <Github className="h-4 w-4" />
                View on GitHub
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Note */}
      <section className="bg-[#FAFBFC] py-12 px-6 text-center border-t border-slate-100">
        <p className="text-slate-500 text-sm max-w-lg mx-auto">
          All data stays in your infrastructure. End-to-end encryption in transit and at rest.
          Deploy with Docker Compose in under 5 minutes.
        </p>
      </section>

      {/* FAQ */}
      <section className="px-6 py-16 bg-white">
        <div className="max-w-[700px] mx-auto">
          <h2 className="text-2xl font-extrabold text-slate-900 mb-2 text-center tracking-tight">
            Frequently asked questions
          </h2>
          <p className="text-slate-500 text-sm text-center mb-10">
            Everything you need to know about Costly.
          </p>
          <div className="space-y-4">
            {FAQ.map(({ q, a }) => (
              <div key={q} className="rounded-xl border border-slate-200 px-6 py-5">
                <div className="font-bold text-slate-900 mb-1.5 text-[0.95rem]">{q}</div>
                <div className="text-slate-500 text-sm leading-relaxed">{a}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 py-20 bg-[#0B1929] text-center">
        <h2 className="text-2xl md:text-3xl font-extrabold text-white mb-3 tracking-tight">
          Stop flying blind on data platform costs
        </h2>
        <p className="text-slate-400 mb-8 text-base max-w-md mx-auto">
          Deploy in 5 minutes. Connect your stack. Let the AI experts find the waste.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link
            href="/login"
            className="inline-block px-8 py-3.5 bg-indigo-600 text-white rounded-lg text-sm font-bold hover:bg-indigo-700 transition shadow-lg shadow-indigo-500/30"
          >
            Get Started Free &rarr;
          </Link>
          <a
            href="https://github.com/njain006/costly-oss"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center gap-2 px-8 py-3.5 border border-white/20 text-slate-200 rounded-lg text-sm font-semibold hover:border-white/40 transition"
          >
            <Github className="h-4 w-4" />
            Star on GitHub
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-[#0B1929] px-6 py-6 text-center text-slate-600 text-sm border-t border-white/5">
        costly &mdash; Free & Open Source Data Platform Cost Intelligence
      </footer>
    </div>
  );
}
