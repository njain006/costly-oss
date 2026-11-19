"use client";

// The 30-second review: what we spent, what changed, and the few changes
// worth making, with the SQL ready to copy. Reads the same precomputed
// results as the Dashboard and Recommendations pages, so it loads instantly.
import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/hooks/use-api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Copy } from "lucide-react";
import { formatCurrency } from "@/lib/format";

interface Rec {
  id: string;
  title: string;
  potential_savings: number | null;
  priority: string;
  category: string;
  ddl_command?: string | null;
}

interface TrendPoint { date: string; cost: number }

export default function ReviewSummary({
  totalCost, days, trend, topWarehouse, serviceShare,
}: {
  totalCost: number;
  days: number;
  trend: TrendPoint[];
  topWarehouse?: { name: string; cost: number };
  serviceShare?: number;
}) {
  const { data: recs } = useApi<Rec[]>(`/recommendations`, []);
  const [copied, setCopied] = useState<string | null>(null);

  const half = Math.floor(trend.length / 2);
  const first = trend.slice(0, half).reduce((s, d) => s + d.cost, 0);
  const second = trend.slice(half).reduce((s, d) => s + d.cost, 0);
  const change = first > 0 ? ((second - first) / first) * 100 : null;
  const peak = trend.reduce<TrendPoint | null>((m, d) => (!m || d.cost > m.cost ? d : m), null);
  const avg = trend.length ? trend.reduce((s, d) => s + d.cost, 0) / trend.length : 0;

  const actions = (recs || [])
    .filter((r) => r.category !== "info")
    .sort((a, b) => (b.potential_savings || 0) - (a.potential_savings || 0)
      || (a.priority === "high" ? -1 : 1) - (b.priority === "high" ? -1 : 1))
    .slice(0, 3);
  const savings = (recs || []).reduce((s, r) => s + (r.potential_savings || 0), 0);

  const copy = async (text: string, id: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(null), 1500); } catch { /* ignore */ }
  };

  return (
    <Card className="mb-8 border-slate-200">
      <CardContent className="p-5 grid md:grid-cols-2 gap-6">
        <div className="space-y-2">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Last {days} days</div>
          <div className="text-3xl font-bold text-slate-900">{formatCurrency(totalCost)}</div>
          <ul className="text-sm text-slate-600 space-y-1">
            {change != null && (
              <li>
                Second half of the period was{" "}
                <b className={change > 0 ? "text-red-600" : "text-emerald-600"}>
                  {change > 0 ? "+" : ""}{change.toFixed(0)}%
                </b>{" "}vs the first half.
              </li>
            )}
            {peak && avg > 0 && peak.cost > avg * 1.8 && (
              <li>Biggest day: <b>{peak.date}</b> at {formatCurrency(peak.cost)} ({(peak.cost / avg).toFixed(1)}× a normal day).</li>
            )}
            {topWarehouse && (
              <li>Largest warehouse: <b>{topWarehouse.name}</b>, {formatCurrency(topWarehouse.cost)} ({((topWarehouse.cost / (totalCost || 1)) * 100).toFixed(0)}%).</li>
            )}
            {serviceShare != null && (
              <li>Service accounts drive <b>{serviceShare.toFixed(0)}%</b> of query compute.</li>
            )}
          </ul>
        </div>
        <div>
          <div className="flex items-baseline justify-between mb-2">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Do next</div>
            {savings > 0 && <div className="text-sm text-emerald-700 font-semibold">~{formatCurrency(savings)}/mo available</div>}
          </div>
          {recs == null ? (
            <div className="text-sm text-slate-400">Loading recommendations…</div>
          ) : actions.length === 0 ? (
            <div className="text-sm text-slate-500">Nothing urgent.</div>
          ) : (
            <ol className="space-y-2">
              {actions.map((r, i) => (
                <li key={r.id} className="text-sm flex items-start gap-2">
                  <span className="text-slate-400 w-4">{i + 1}.</span>
                  <div className="flex-1">
                    <div className="text-slate-800">{r.title}</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      {r.potential_savings ? <span className="text-xs text-emerald-700">saves ~{formatCurrency(r.potential_savings)}/mo</span> : null}
                      {r.ddl_command && (
                        <Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => copy(r.ddl_command!, r.id)}>
                          <Copy className="h-3 w-3 mr-1" />{copied === r.id ? "Copied" : "Copy SQL"}
                        </Button>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
          <Link href="/recommendations" className="text-xs text-sky-700 mt-3 inline-block">All recommendations and the full action plan →</Link>
        </div>
      </CardContent>
    </Card>
  );
}
