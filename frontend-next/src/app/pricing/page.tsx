import Link from "next/link";
import { DollarSign, Check } from "lucide-react";

const TIERS = [
  {
    name: "Free",
    price: "$0",
    period: "/mo",
    description: "Get started with cost visibility across your core platforms.",
    cta: "Get Started Free",
    ctaHref: "/login",
    highlight: false,
    badge: null,
    features: [
      "3 platform connections",
      "7-day data retention",
      "Basic cost dashboard",
      "Cost breakdown by platform",
      "Community support",
    ],
  },
  {
    name: "Pro",
    price: "$49",
    period: "/mo",
    description: "Full cost intelligence across your entire data stack.",
    cta: "Start Free Trial",
    ctaHref: "/login",
    highlight: true,
    badge: "Most Popular",
    features: [
      "Unlimited platform connections",
      "90-day data retention",
      "AI cost agent",
      "Smart cost recommendations",
      "Anomaly detection & alerts",
      "Slack & email notifications",
      "Cost attribution by team & project",
      "Priority support",
    ],
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "For organizations with advanced security and compliance needs.",
    cta: "Contact Sales",
    ctaHref: "mailto:hello@costly.dev",
    highlight: false,
    badge: null,
    features: [
      "Everything in Pro",
      "Unlimited data retention",
      "SSO & RBAC",
      "Custom connectors",
      "Dedicated customer success",
      "Custom SLA",
      "Custom reporting & exports",
      "On-prem deployment option",
    ],
  },
];

const FAQ = [
  {
    q: "Which platforms does Costly support?",
    a: "Costly connects to 15+ data platforms including AWS (21 services), Snowflake, BigQuery, Databricks, dbt Cloud, Fivetran, Airbyte, OpenAI, GitHub Actions, Looker, Tableau, Monte Carlo, and more. New connectors are added regularly.",
  },
  {
    q: "Do you store my API keys or credentials?",
    a: "Yes — but only encrypted. All credentials are encrypted with AES-256 (Fernet) before being written to our database. Plaintext secrets are never logged or stored.",
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
    q: "What is the AI cost agent?",
    a: "The AI agent is a conversational interface that answers questions about your data platform spend in plain English. Ask things like 'Which platform had the biggest cost spike this week?' or 'What's driving our warehouse compute costs up?'",
  },
  {
    q: "Can I upgrade or downgrade my plan?",
    a: "Yes, anytime. Upgrades take effect immediately. Downgrades apply at the end of your billing cycle. No long-term commitment required on Pro.",
  },
  {
    q: "Is there a free trial for Pro?",
    a: "Yes — Pro comes with a 14-day free trial. No credit card required to start.",
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
          <DollarSign className="h-5 w-5 text-sky-400" />
          costly
        </Link>
        <div className="hidden md:flex gap-6 items-center">
          <Link
            href="/#features"
            className="text-slate-400 text-sm hover:text-white transition"
          >
            Features
          </Link>
          <Link href="/pricing" className="text-sky-400 text-sm font-semibold">
            Pricing
          </Link>
          <Link
            href="/setup"
            className="text-slate-400 text-sm hover:text-white transition"
          >
            Docs
          </Link>
          <Link
            href="/login"
            className="px-4 py-1.5 border border-white/20 rounded-md text-slate-200 text-sm font-medium hover:border-white/40 transition"
          >
            Log in
          </Link>
          <Link
            href="/login"
            className="px-4 py-1.5 bg-sky-600 rounded-md text-white text-sm font-semibold hover:bg-sky-700 transition"
          >
            Get Started
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="pt-28 pb-14 text-center bg-[#0B1929]">
        <div className="inline-block bg-sky-500/10 border border-sky-500/25 rounded-full px-4 py-1 text-xs text-sky-400 font-semibold uppercase tracking-wider mb-4">
          Simple, transparent pricing
        </div>
        <h1 className="text-4xl md:text-5xl font-extrabold text-white tracking-tight mb-4">
          Know exactly what your data stack costs
        </h1>
        <p className="text-slate-400 text-lg max-w-xl mx-auto">
          Connect 15+ platforms in minutes. Spot waste, get AI recommendations,
          and stop paying for what you don&apos;t need.
        </p>
      </section>

      {/* Pricing cards */}
      <section className="bg-[#0B1929] px-6 pb-24">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
          {TIERS.map((tier) => (
            <div
              key={tier.name}
              className={`relative rounded-2xl p-8 flex flex-col ${
                tier.highlight
                  ? "bg-gradient-to-b from-sky-950 to-[#0B1929] border-2 border-sky-500 shadow-xl shadow-sky-500/20 md:-mt-4 md:-mb-4"
                  : "bg-[#0f2035] border border-white/10"
              }`}
            >
              {tier.badge && (
                <div className="absolute -top-3.5 left-1/2 -translate-x-1/2">
                  <span className="inline-block bg-sky-500 text-white text-xs font-bold px-3 py-1 rounded-full shadow-lg shadow-sky-500/30">
                    {tier.badge}
                  </span>
                </div>
              )}

              <div className="mb-6">
                <div
                  className={`text-xs font-bold uppercase tracking-wider mb-2 ${
                    tier.highlight ? "text-sky-400" : "text-slate-400"
                  }`}
                >
                  {tier.name}
                </div>
                <div className="flex items-baseline gap-1 mb-2">
                  <span className="text-4xl font-extrabold tracking-tight text-white">
                    {tier.price}
                  </span>
                  {tier.period && (
                    <span className="text-slate-400 text-sm">{tier.period}</span>
                  )}
                </div>
                <p className="text-slate-400 text-sm leading-relaxed">
                  {tier.description}
                </p>
              </div>

              <div className="h-px bg-white/10 mb-6" />

              <ul className="space-y-3 mb-8 flex-1">
                {tier.features.map((f) => (
                  <li
                    key={f}
                    className="flex items-start gap-2.5 text-sm text-slate-300"
                  >
                    <Check
                      className={`h-4 w-4 mt-0.5 shrink-0 ${
                        tier.highlight ? "text-sky-400" : "text-emerald-500"
                      }`}
                    />
                    {f}
                  </li>
                ))}
              </ul>

              <Link
                href={tier.ctaHref}
                className={`block w-full text-center py-3 rounded-lg text-sm font-bold transition ${
                  tier.highlight
                    ? "bg-sky-600 text-white hover:bg-sky-700 shadow-lg shadow-sky-500/30"
                    : "bg-white/10 text-white hover:bg-white/15 border border-white/10"
                }`}
              >
                {tier.cta}
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* Feature comparison note */}
      <section className="bg-[#FAFBFC] py-12 px-6 text-center border-t border-slate-100">
        <p className="text-slate-500 text-sm max-w-lg mx-auto">
          All plans include end-to-end encryption in transit and at rest.
          Self-hosted deployment keeps your data in your own infrastructure.
        </p>
      </section>

      {/* FAQ */}
      <section className="px-6 py-16 bg-white">
        <div className="max-w-[700px] mx-auto">
          <h2 className="text-2xl font-extrabold text-slate-900 mb-2 text-center tracking-tight">
            Frequently asked questions
          </h2>
          <p className="text-slate-500 text-sm text-center mb-10">
            Everything you need to know about Costly pricing and features.
          </p>
          <div className="space-y-4">
            {FAQ.map(({ q, a }) => (
              <div
                key={q}
                className="rounded-xl border border-slate-200 px-6 py-5"
              >
                <div className="font-bold text-slate-900 mb-1.5 text-[0.95rem]">
                  {q}
                </div>
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
          Connect your stack in minutes. Free to start — no credit card required.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link
            href="/login"
            className="inline-block px-8 py-3.5 bg-sky-600 text-white rounded-lg text-sm font-bold hover:bg-sky-700 transition shadow-lg shadow-sky-500/30"
          >
            Get Started Free &rarr;
          </Link>
          <Link
            href="mailto:hello@costly.dev"
            className="inline-block px-8 py-3.5 border border-white/20 text-slate-200 rounded-lg text-sm font-semibold hover:border-white/40 transition"
          >
            Talk to Sales
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-[#0B1929] px-6 py-6 text-center text-slate-600 text-sm border-t border-white/5">
        costly &mdash; Data Platform Cost Intelligence
      </footer>
    </div>
  );
}
