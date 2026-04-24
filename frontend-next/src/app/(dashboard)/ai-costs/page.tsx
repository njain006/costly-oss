"use client";

import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { DollarSign, Zap, TrendingUp, ArrowUpRight, ArrowDownRight, Bot, Lightbulb, Sparkles, PiggyBank } from "lucide-react";
import { formatCurrency, formatNumber } from "@/lib/format";
import { COLORS, DATE_OPTIONS } from "@/lib/constants";
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";

const PROVIDER_COLORS: Record<string, string> = {
  openai: COLORS.chart[0],
  anthropic: COLORS.chart[1],
  claude_code: COLORS.chart[5],
  gemini: COLORS.chart[2],
};

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic API",
  claude_code: "Claude Code",
  gemini: "Gemini",
};

interface AiCostsData {
  kpis: {
    total_cost: number;
    total_tokens: number;
    avg_cost_per_1k: number;
    mom_change: number | null;
    model_count: number;
    provider_count: number;
    cache_hit_rate: number;
    cache_savings_usd: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
  };
  providers: Array<{
    platform: string;
    cost: number;
    tokens: number;
    input_tokens: number;
    output_tokens: number;
    cost_per_1k: number;
  }>;
  daily_spend: Array<{ date: string; openai: number; anthropic: number; claude_code: number; gemini: number }>;
  daily_tokens: Array<{
    date: string;
    input: number;
    output: number;
    cache_read: number;
    cache_write: number;
    total: number;
  }>;
  cost_per_1k_trend: Array<{ date: string; cost_per_1k: number }>;
  model_breakdown: Array<{
    model: string;
    platform: string;
    cost: number;
    tokens: number;
    input_tokens: number;
    output_tokens: number;
    cost_per_1k: number;
  }>;
  recommendations: Array<{
    type: string;
    title: string;
    description: string;
    potential_savings: number;
  }>;
  demo?: boolean;
}

export default function AiCostsPage() {
  const [days, setDays] = useState(30);
  const { data, loading } = useApi<AiCostsData>(`/ai-costs?days=${days}`, [days]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-24" />)}
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          <Skeleton className="h-72 md:col-span-2" />
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }

  if (!data || data.demo) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-slate-900">AI Spend Intelligence</h1>
        <Card>
          <CardContent className="p-12 text-center">
            <Bot className="h-12 w-12 mx-auto text-slate-300 mb-4" />
            <h2 className="text-lg font-semibold text-slate-700 mb-2">No AI Platforms Connected</h2>
            <p className="text-sm text-slate-500 mb-4">
              Connect OpenAI, Anthropic, or Gemini on the Platforms page to see cross-provider AI cost intelligence.
            </p>
            <a href="/platforms" className="text-sm text-sky-600 hover:underline">Go to Platforms →</a>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { kpis, providers, daily_spend, daily_tokens, cost_per_1k_trend, model_breakdown, recommendations } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">AI Spend Intelligence</h1>
        <div className="flex gap-1 bg-slate-100 rounded-lg p-1">
          {DATE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setDays(opt.value)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition ${
                days === opt.value ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Cards — 6 tiles to keep cache savings visible (the wedge vs Vantage/CloudZero) */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard title="Total AI Spend" value={formatCurrency(kpis.total_cost)} icon={DollarSign} />
        <StatCard title="Total Tokens" value={formatNumber(kpis.total_tokens)} icon={Zap} />
        <StatCard
          title="Cache Hit Rate"
          value={`${kpis.cache_hit_rate.toFixed(1)}%`}
          icon={Sparkles}
          description={`${formatNumber(kpis.cache_read_tokens)} cached / ${formatNumber(kpis.cache_write_tokens)} written`}
        />
        <StatCard
          title="Saved by Caching"
          value={formatCurrency(kpis.cache_savings_usd)}
          icon={PiggyBank}
          description="vs list-price input"
        />
        <StatCard
          title="Avg $/1K Tokens"
          value={`$${kpis.avg_cost_per_1k.toFixed(3)}`}
          icon={TrendingUp}
        />
        <StatCard
          title="vs Previous Period"
          value={kpis.mom_change !== null ? `${kpis.mom_change > 0 ? "+" : ""}${kpis.mom_change.toFixed(1)}%` : "N/A"}
          icon={kpis.mom_change !== null && kpis.mom_change > 0 ? ArrowUpRight : ArrowDownRight}
          description={`${kpis.model_count} models · ${kpis.provider_count} providers`}
        />
      </div>

      {/* Provider Comparison */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Provider Comparison</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-slate-500 text-xs">
                  <th className="text-left py-2 font-medium">Provider</th>
                  <th className="text-right py-2 font-medium">Spend</th>
                  <th className="text-right py-2 font-medium">Input Tokens</th>
                  <th className="text-right py-2 font-medium">Output Tokens</th>
                  <th className="text-right py-2 font-medium">$/1K Tokens</th>
                  <th className="text-right py-2 font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {providers.map((p) => (
                  <tr key={p.platform} className="border-b last:border-0">
                    <td className="py-2.5 font-medium flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: PROVIDER_COLORS[p.platform] }} />
                      {PROVIDER_LABELS[p.platform] || p.platform}
                    </td>
                    <td className="text-right py-2.5 font-semibold">{formatCurrency(p.cost)}</td>
                    <td className="text-right py-2.5 text-slate-600">{formatNumber(p.input_tokens)}</td>
                    <td className="text-right py-2.5 text-slate-600">{formatNumber(p.output_tokens)}</td>
                    <td className="text-right py-2.5 text-slate-600">${p.cost_per_1k.toFixed(3)}</td>
                    <td className="text-right py-2.5">
                      <Badge variant="secondary" className="text-xs">
                        {kpis.total_cost > 0 ? `${((p.cost / kpis.total_cost) * 100).toFixed(0)}%` : "0%"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Charts Row 1 */}
      <div className="grid md:grid-cols-3 gap-4">
        {/* Daily Spend by Provider */}
        <Card className="md:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Daily AI Spend by Provider</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={daily_spend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  formatter={(v) => formatCurrency(Number(v))}
                  labelFormatter={(l) => `Date: ${l}`}
                  contentStyle={{ fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="anthropic" name="Anthropic API" stackId="1"
                  fill={PROVIDER_COLORS.anthropic} stroke={PROVIDER_COLORS.anthropic} fillOpacity={0.65} />
                <Area type="monotone" dataKey="claude_code" name="Claude Code" stackId="1"
                  fill={PROVIDER_COLORS.claude_code} stroke={PROVIDER_COLORS.claude_code} fillOpacity={0.65} />
                <Area type="monotone" dataKey="openai" name="OpenAI" stackId="1"
                  fill={PROVIDER_COLORS.openai} stroke={PROVIDER_COLORS.openai} fillOpacity={0.65} />
                <Area type="monotone" dataKey="gemini" name="Gemini" stackId="1"
                  fill={PROVIDER_COLORS.gemini} stroke={PROVIDER_COLORS.gemini} fillOpacity={0.65} />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Token tier breakdown — cache_read / cache_write / input / output */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Daily Tokens by Tier</CardTitle>
            <p className="text-xs text-slate-500">Cache reads are 10% of list input price; writes are 25–100% premium.</p>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={daily_tokens.slice(-14)}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v) => v.slice(5)} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => formatNumber(v)} />
                <Tooltip
                  formatter={(v, name) => [formatNumber(Number(v)), String(name)]}
                  contentStyle={{ fontSize: 12 }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="cache_read" name="Cache read" stackId="t" fill={COLORS.chart[6]} />
                <Bar dataKey="cache_write" name="Cache write" stackId="t" fill={COLORS.chart[7]} />
                <Bar dataKey="input" name="Uncached input" stackId="t" fill={COLORS.chart[3]} />
                <Bar dataKey="output" name="Output" stackId="t" fill={COLORS.chart[4]} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 2 */}
      <div className="grid md:grid-cols-2 gap-4">
        {/* Cost per 1K Tokens Trend */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Cost Efficiency Trend ($/1K Tokens)</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={cost_per_1k_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  formatter={(v) => `$${Number(v).toFixed(4)}`}
                  contentStyle={{ fontSize: 12 }}
                />
                <Line type="monotone" dataKey="cost_per_1k" name="$/1K Tokens"
                  stroke={COLORS.accent} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Model Breakdown */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Cost by Model</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-y-auto max-h-[240px]">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white">
                  <tr className="border-b text-slate-500 text-xs">
                    <th className="text-left py-1.5 font-medium">Model</th>
                    <th className="text-right py-1.5 font-medium">Spend</th>
                    <th className="text-right py-1.5 font-medium">Tokens</th>
                    <th className="text-right py-1.5 font-medium">$/1K</th>
                  </tr>
                </thead>
                <tbody>
                  {model_breakdown.map((m, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className="py-1.5">
                        <div className="flex items-center gap-1.5">
                          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: PROVIDER_COLORS[m.platform] }} />
                          <span className="font-medium text-xs">{m.model}</span>
                        </div>
                      </td>
                      <td className="text-right py-1.5 font-semibold text-xs">{formatCurrency(m.cost)}</td>
                      <td className="text-right py-1.5 text-slate-600 text-xs">{formatNumber(m.tokens)}</td>
                      <td className="text-right py-1.5 text-slate-600 text-xs">${m.cost_per_1k.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Lightbulb className="h-4 w-4 text-amber-500" />
              AI Cost Recommendations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {recommendations.map((rec, i) => (
                <div key={i} className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg">
                  <div className={`px-2 py-0.5 rounded text-xs font-medium ${
                    rec.type === "model_migration" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
                  }`}>
                    {rec.type === "model_migration" ? "Switch Model" : "Efficiency"}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800">{rec.title}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{rec.description}</p>
                  </div>
                  <Badge variant="secondary" className="shrink-0 text-green-700 bg-green-50">
                    Save ~{formatCurrency(rec.potential_savings)}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
