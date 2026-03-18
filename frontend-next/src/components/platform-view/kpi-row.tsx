"use client";

import { KpiConfig } from "@/lib/platform-registry";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber, formatBytes, formatDuration } from "@/lib/format";

function formatValue(value: unknown, format: KpiConfig["format"]): string {
  const n = Number(value) || 0;
  switch (format) {
    case "currency": return formatCurrency(n);
    case "number": return formatNumber(n);
    case "bytes": return formatBytes(n);
    case "duration": return formatDuration(n);
    case "percent": return `${n.toFixed(1)}%`;
    default: return String(value);
  }
}

export function KpiRow({ kpis, data, loading }: { kpis: KpiConfig[]; data: Record<string, unknown> | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        {kpis.map((k) => <Skeleton key={k.key} className="h-24 rounded-lg" />)}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
      {kpis.map((kpi) => {
        const Icon = kpi.icon;
        return (
          <Card key={kpi.key}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-slate-500">{kpi.title}</p>
                  <p className="text-2xl font-bold text-slate-900 mt-1">
                    {formatValue(data.kpis && typeof data.kpis === "object" ? (data.kpis as Record<string, unknown>)[kpi.key] : data[kpi.key], kpi.format)}
                  </p>
                </div>
                <div className="h-10 w-10 rounded-lg bg-sky-50 flex items-center justify-center">
                  <Icon className="h-5 w-5 text-sky-600" />
                </div>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
