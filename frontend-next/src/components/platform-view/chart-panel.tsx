"use client";

import { ChartConfig } from "@/lib/platform-registry";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { COLORS } from "@/lib/constants";
import { formatCurrency, formatNumber, formatBytes, formatDuration } from "@/lib/format";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  CartesianGrid, XAxis, YAxis, Tooltip, Legend,
} from "recharts";

function smartFormat(value: number, keys: { key: string; label: string }[]): string {
  const label = keys[0]?.label?.toLowerCase() || "";
  if (label.includes("cost") || label.includes("spend")) return formatCurrency(value);
  if (label.includes("byte") || label.includes("size") || label.includes("storage")) return formatBytes(value);
  if (label.includes("duration") || label.includes("time")) return formatDuration(value);
  return formatNumber(value);
}

export function ChartPanel({
  config,
  data,
  loading,
}: {
  config: ChartConfig;
  data: unknown[] | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">{config.title}</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-64" /></CardContent>
      </Card>
    );
  }

  if (!data || !Array.isArray(data) || data.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">{config.title}</CardTitle></CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center text-sm text-slate-400">No data available</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={config.span === 2 ? "lg:col-span-2" : ""}>
      <CardHeader><CardTitle className="text-base">{config.title}</CardTitle></CardHeader>
      <CardContent>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            {renderChart(config, data)}
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

function renderChart(config: ChartConfig, data: unknown[]) {
  const colors = COLORS.chart;

  switch (config.type) {
    case "area":
    case "stacked-area":
      return (
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey={config.xKey} tick={{ fontSize: 11 }} tickFormatter={(v) => typeof v === "string" && v.includes("-") ? v.slice(5) : v} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => smartFormat(Number(v), config.yKeys)} />
          <Tooltip formatter={(v) => smartFormat(Number(v), config.yKeys)} />
          <Legend />
          {config.yKeys.map((yk, i) => (
            <Area
              key={yk.key}
              type="monotone"
              dataKey={yk.key}
              name={yk.label}
              stackId={config.type === "stacked-area" ? "1" : undefined}
              fill={yk.color || colors[i % colors.length]}
              stroke={yk.color || colors[i % colors.length]}
              fillOpacity={0.6}
            />
          ))}
        </AreaChart>
      );

    case "bar":
      return (
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey={config.xKey} tick={{ fontSize: 11 }} tickFormatter={(v) => typeof v === "string" && v.includes("-") ? v.slice(5) : v} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v) => smartFormat(Number(v), config.yKeys)} />
          <Legend />
          {config.yKeys.map((yk, i) => (
            <Bar key={yk.key} dataKey={yk.key} name={yk.label} fill={yk.color || colors[i % colors.length]} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      );

    case "horizontal-bar":
      return (
        <BarChart data={data.slice(0, 10)} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey={config.xKey} type="category" tick={{ fontSize: 11 }} width={120} />
          <Tooltip formatter={(v) => smartFormat(Number(v), config.yKeys)} />
          {config.yKeys.map((yk, i) => (
            <Bar key={yk.key} dataKey={yk.key} name={yk.label} fill={yk.color || colors[i % colors.length]} radius={[0, 4, 4, 0]} />
          ))}
        </BarChart>
      );

    case "pie":
      return (
        <PieChart>
          <Pie
            data={data.slice(0, 8)}
            dataKey={config.yKeys[0]?.key || "value"}
            nameKey={config.xKey}
            cx="50%" cy="50%"
            innerRadius={50}
            outerRadius={80}
            paddingAngle={2}
            label={({ percent }) => (percent ?? 0) > 0.05 ? `${((percent ?? 0) * 100).toFixed(0)}%` : ""}
            labelLine={false}
          >
            {data.slice(0, 8).map((_, i) => (
              <Cell key={i} fill={colors[i % colors.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v) => smartFormat(Number(v), config.yKeys)} />
          <Legend />
        </PieChart>
      );

    default:
      return <AreaChart data={data}><Area dataKey="value" /></AreaChart>;
  }
}
