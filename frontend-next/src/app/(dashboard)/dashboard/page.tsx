"use client";

import UserTypeFilter, { filterByUserType, useUserTypeFilter } from "@/components/user-type-filter";

import LoadError from "@/components/load-error";

import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import api from "@/lib/api";
import { useState } from "react";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import ReviewSummary from "@/components/review-summary";
import DataFreshness from "@/components/data-freshness";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DollarSign, CreditCard, Warehouse, Zap, AlertTriangle, HardDrive } from "lucide-react";
import { formatCurrency, formatNumber } from "@/lib/format";
import { COLORS } from "@/lib/constants";
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";

interface DashboardData {
  total_cost: number;
  total_credits: number;
  active_warehouses: number;
  query_count: number;
  failed_queries: number;
  storage_gb: number;
  query_history_available?: boolean;
  queries_source?: string;
  cost_trend: Array<{
    date: string;
    cost: number;
    compute_cost: number;
    cloud_services_cost: number;
    serverless_cost?: number;
    ai_cost?: number;
    rolling_avg?: number;
  }>;
  top_warehouses: Array<{ name: string; credits: number; cost: number }>;
  top_users: Array<{ user: string; cost: number; queries: number; type?: "service" | "human"; type_source?: string }>;
  cost_by_user_type?: { service: number; human: number };
  connection_id?: string;
  anomalies: Array<{ date: string; cost: number; label: string }>;
  fetched_at?: string;
  cached?: boolean;
  demo?: boolean;
}

export default function DashboardPage() {
  const { days, refreshTrigger } = useDateRange();
  // Local overrides so a click flips the badge immediately.
  const [typeOverride, setTypeOverride] = useState<Record<string, "service" | "human">>({});
  const userType = useUserTypeFilter();
  const { data, loading, error: loadError } = useApi<DashboardData>(
    `/dashboard?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          {data && <DataFreshness fetchedAt={data.fetched_at} cached={data.cached} demo={data.demo} />}
        </div>
        <DateRangePicker />
      </div>

      <DemoBanner />

      <LoadError error={loadError} />
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : data ? (
        <>
          <ReviewSummary
            totalCost={data.total_cost}
            days={days}
            trend={data.cost_trend}
            topWarehouse={data.top_warehouses[0]}
            serviceShare={data.cost_by_user_type && (data.cost_by_user_type.service + data.cost_by_user_type.human) > 0
              ? (100 * data.cost_by_user_type.service) / (data.cost_by_user_type.service + data.cost_by_user_type.human)
              : undefined}
          />
          {/* Stat Cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-8">
            <StatCard title="Credits" value={formatNumber(data.total_credits)} icon={CreditCard} />
            <StatCard title="Warehouses" value={data.active_warehouses} icon={Warehouse} />
            <StatCard title="Queries" value={formatNumber(data.query_count)} icon={Zap} description={data.queries_source === "query_attribution" ? "warehouse queries over ~100ms" : undefined} />
            <StatCard title="Failed" value={data.query_history_available === false ? "—" : formatNumber(data.failed_queries)} icon={AlertTriangle} description={data.query_history_available === false ? "needs query history access" : undefined} />
            <StatCard title="Storage" value={`${data.storage_gb >= 1000 ? (data.storage_gb / 1000).toFixed(1) + " TB" : data.storage_gb.toFixed(1) + " GB"}`} icon={HardDrive} />
          </div>

          {/* Charts */}
          <div className="grid lg:grid-cols-3 gap-6 mb-8">
            {/* Cost Trend */}
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Cost Trend</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.cost_trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                      <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                      <Area type="monotone" dataKey="compute_cost" stackId="1" fill={COLORS.primary} stroke={COLORS.primary} fillOpacity={0.6} name="Compute" />
                      <Area type="monotone" dataKey="cloud_services_cost" stackId="1" fill={COLORS.chart[4]} stroke={COLORS.chart[4]} fillOpacity={0.4} name="Cloud Services" />
                      <Area type="monotone" dataKey="ai_cost" stackId="1" fill={COLORS.chart[2]} stroke={COLORS.chart[2]} fillOpacity={0.5} name="AI (Cortex, Copilot)" />
                      <Area type="monotone" dataKey="serverless_cost" stackId="1" fill={COLORS.chart[3]} stroke={COLORS.chart[3]} fillOpacity={0.5} name="Serverless & other" />
                      {data.anomalies.map((a) => (
                        <ReferenceLine key={a.date} x={a.date} stroke="#ef4444" strokeDasharray="3 3" label={{ value: "!", fill: "#ef4444", fontSize: 12 }} />
                      ))}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* Top Warehouses */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Top Warehouses</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.top_warehouses} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis type="number" tick={{ fontSize: 11 }} />
                      <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={150} />
                      <Tooltip formatter={(v) => `${Number(v).toFixed(1)} credits`} />
                      <Bar dataKey="credits" fill={COLORS.primary} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Top Users (anomalies are summarised at the top and on the Anomalies page) */}
          <div className="grid gap-6">

            <Card>
              <CardHeader className="pb-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">Top Users by Cost</CardTitle>
                  <UserTypeFilter />
                </div>
              </CardHeader>
              <CardContent>
                {data.cost_by_user_type && (
                  <div className="flex gap-4 mb-3 text-xs text-muted-foreground">
                    <span>Service accounts: <b className="text-slate-800">{formatCurrency(data.cost_by_user_type.service)}</b></span>
                    <span>People: <b className="text-slate-800">{formatCurrency(data.cost_by_user_type.human)}</b></span>
                    <span className="ml-auto">click a tag to correct it</span>
                  </div>
                )}
                <div className="space-y-2">
                  {filterByUserType(data.top_users, userType, (u) => typeOverride[u.user] ?? u.type).map((u, i) => {
                    const t = typeOverride[u.user] ?? u.type ?? "human";
                    const flip = async () => {
                      const next = t === "service" ? "human" : "service";
                      setTypeOverride((o) => ({ ...o, [u.user]: next }));
                      if (data.connection_id) {
                        try { await api.put(`/platforms/${data.connection_id}/user-types`, { user: u.user, type: next }); } catch { /* keep local */ }
                      }
                    };
                    return (
                    <div key={u.user} className="flex items-center justify-between py-2 border-b last:border-0">
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-medium text-muted-foreground w-5">{i + 1}</span>
                        <span className="text-sm font-medium">{u.user}</span>
                        <button
                          onClick={flip}
                          title={u.type_source === "guess" && !typeOverride[u.user] ? "Guessed from the name. Click to change." : "Click to change."}
                          className={`text-[10px] px-1.5 py-0.5 rounded border ${t === "service" ? "bg-slate-100 text-slate-600 border-slate-200" : "bg-sky-50 text-sky-700 border-sky-200"}`}
                        >
                          {t === "service" ? "service" : "person"}{u.type_source === "guess" && !typeOverride[u.user] ? "?" : ""}
                        </button>
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-semibold">{formatCurrency(u.cost)}</div>
                        <div className="text-xs text-muted-foreground">{formatNumber(u.queries)} queries</div>
                      </div>
                    </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
