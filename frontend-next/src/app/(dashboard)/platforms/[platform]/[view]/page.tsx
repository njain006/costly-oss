"use client";

import { use, useMemo } from "react";
import { notFound } from "next/navigation";
import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import { useAuth } from "@/providers/auth-provider";
import { PLATFORM_REGISTRY } from "@/lib/platform-registry";
import { KpiRow } from "@/components/platform-view/kpi-row";
import { ChartPanel } from "@/components/platform-view/chart-panel";
import { DataTablePanel } from "@/components/platform-view/data-table-panel";
import { generateDemoViewData } from "@/lib/platform-demo-data";

interface ViewData {
  kpis: Record<string, unknown>;
  charts: Record<string, unknown[]>;
  table: unknown[];
  demo?: boolean;
}

export default function PlatformViewPage({
  params,
}: {
  params: Promise<{ platform: string; view: string }>;
}) {
  const { platform: platformKey, view: viewSlug } = use(params);
  const { days, refreshTrigger } = useDateRange();
  const { isDemo } = useAuth();

  const registry = PLATFORM_REGISTRY[platformKey];
  const viewConfig = registry?.views.find((v) => v.slug === viewSlug);

  const { data: liveData, loading } = useApi<ViewData>(
    !isDemo && registry ? `/platforms/${platformKey}/${viewSlug}?days=${days}&refresh=${refreshTrigger > 0}` : null,
    [days, refreshTrigger],
  );

  const demoData = useMemo(
    () => (registry && viewConfig ? generateDemoViewData(platformKey, viewSlug, days) : null),
    [platformKey, viewSlug, days, registry, viewConfig],
  );

  if (!registry || !viewConfig) notFound();

  const isUsingDemo = isDemo;
  const data: ViewData | null = isUsingDemo ? demoData : (liveData ?? null);

  const Icon = viewConfig.icon;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 flex items-center justify-center">
          <Icon className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            {registry.label} — {viewConfig.label}
          </h1>
          <p className="text-sm text-slate-500">
            {isUsingDemo ? "Demo data" : `Last ${days} days`}
          </p>
        </div>
      </div>

      {/* KPIs */}
      <KpiRow kpis={viewConfig.kpis} data={data as Record<string, unknown> | null} loading={loading && !isUsingDemo} />

      {/* Charts */}
      <div className="grid lg:grid-cols-3 gap-6 mb-8">
        {viewConfig.charts.map((chart) => (
          <ChartPanel
            key={chart.key}
            config={chart}
            data={data?.charts?.[chart.key] ?? null}
            loading={loading && !isUsingDemo}
          />
        ))}
      </div>

      {/* Table */}
      <DataTablePanel
        config={viewConfig.table}
        data={data?.table ?? null}
        loading={loading && !isUsingDemo}
      />
    </div>
  );
}
