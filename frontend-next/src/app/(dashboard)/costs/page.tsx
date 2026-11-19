"use client";

import UserTypeFilter, { filterByUserType, useUserTypeFilter } from "@/components/user-type-filter";

import LoadError from "@/components/load-error";

import { useMemo } from "react";
import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import DataFreshness from "@/components/data-freshness";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCurrency, formatNumber } from "@/lib/format";
import { COLORS } from "@/lib/constants";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface CostsData {
  daily: Array<{ date: string; warehouse: string; cost: number; credits: number }>;
  by_user: Array<{ user: string; cost: number; queries: number }>;
  fetched_at?: string;
  cached?: boolean;
  demo?: boolean;
}

interface CostAttributionData {
  by_user: Array<{ user: string; cost_usd: number; query_count: number; pct: number; type?: string; type_source?: string }>;
  by_role: Array<{ role: string; cost_usd: number; query_count: number; pct: number }>;
  by_database: Array<{ database: string; cost_usd: number; query_count: number; pct: number }>;
  by_warehouse: Array<{ warehouse: string; cost_usd: number; credits: number }>;
  top_queries: Array<{ query_id: string; user: string; warehouse: string; role: string; duration_s: number; query_text: string; est_cost_usd: number }>;
  total_cost_usd: number;
  fetched_at?: string; demo?: boolean;
}

export default function CostAnalysisPage() {
  const { days, refreshTrigger } = useDateRange();
  const { data, loading, error: loadError } = useApi<CostsData>(
    `/costs?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const { data: attrData } = useApi<CostAttributionData>(
    `/cost-attribution?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const userType = useUserTypeFilter();
  const usersShown = filterByUserType(attrData?.by_user ?? [], userType, (u) => u.type);

  const chartData = useMemo<{ data: Record<string, number>[]; warehouses: string[] }>(() => {
    if (!data?.daily) return { data: [], warehouses: [] };
    const dateMap: Record<string, Record<string, number>> = {};
    const warehouses = new Set<string>();
    for (const d of data.daily) {
      warehouses.add(d.warehouse);
      if (!dateMap[d.date]) dateMap[d.date] = { date: d.date as unknown as number };
      (dateMap[d.date] as Record<string, number>)[d.warehouse] = d.cost;
    }
    return { data: Object.values(dateMap), warehouses: Array.from(warehouses) };
  }, [data]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">Cost Analysis</h1>
          {data && <DataFreshness fetchedAt={data.fetched_at} cached={data.cached} demo={data.demo} />}
        </div>
        <DateRangePicker />
      </div>
      <DemoBanner />

      <LoadError error={loadError} />
      {loading ? (
        <Skeleton className="h-80 rounded-lg" />
      ) : data ? (
        <Tabs defaultValue="warehouse">
          <TabsList>
            <TabsTrigger value="warehouse">By Warehouse</TabsTrigger>
            <TabsTrigger value="user">By User</TabsTrigger>
            <TabsTrigger value="role">By Role</TabsTrigger>
            <TabsTrigger value="database">By Database</TabsTrigger>
          </TabsList>

          {/* By Warehouse (existing chart) */}
          <TabsContent value="warehouse">
            <Card className="mb-6">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Daily Cost by Warehouse</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={chartData.data}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                      <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                      <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                      {chartData.warehouses.map((wh, i) => (
                        <Area key={wh} type="monotone" dataKey={wh} stackId="1" fill={COLORS.chart[i % COLORS.chart.length]} stroke={COLORS.chart[i % COLORS.chart.length]} fillOpacity={0.6} />
                      ))}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {attrData && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Warehouse Cost Breakdown</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Warehouse</TableHead>
                        <TableHead className="text-right">Cost</TableHead>
                        <TableHead className="text-right">Credits</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {attrData.by_warehouse.map((w) => (
                        <TableRow key={w.warehouse}>
                          <TableCell className="font-medium">{w.warehouse}</TableCell>
                          <TableCell className="text-right">{formatCurrency(w.cost_usd)}</TableCell>
                          <TableCell className="text-right">{w.credits.toFixed(1)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* By User */}
          <TabsContent value="user">
            {attrData ? (
              <>
                <Card className="mb-6">
                  <CardHeader className="pb-2">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <CardTitle className="text-base">Cost by User</CardTitle>
                      <UserTypeFilter />
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={usersShown} layout="vertical">
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                          <YAxis dataKey="user" type="category" tick={{ fontSize: 11 }} width={120} />
                          <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                          <Bar dataKey="cost_usd" name="Cost" fill={COLORS.chart[0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">User Cost Details</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>User</TableHead>
                          <TableHead className="text-right">Cost</TableHead>
                          <TableHead className="text-right">Queries</TableHead>
                          <TableHead className="text-right">Share</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {usersShown.map((u) => (
                          <TableRow key={u.user}>
                            <TableCell className="font-medium">{u.user}{u.type && <span className="ml-1.5 text-[10px] text-muted-foreground">{u.type === "service" ? "service" : "person"}{u.type_source === "guess" ? "?" : ""}</span>}</TableCell>
                            <TableCell className="text-right">{formatCurrency(u.cost_usd)}</TableCell>
                            <TableCell className="text-right">{formatNumber(u.query_count)}</TableCell>
                            <TableCell className="text-right">{u.pct}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </>
            ) : (
              <Skeleton className="h-80 rounded-lg" />
            )}
          </TabsContent>

          {/* By Role */}
          <TabsContent value="role">
            {attrData ? (
              <>
                <Card className="mb-6">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Cost by Role</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={attrData.by_role} layout="vertical">
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                          <YAxis dataKey="role" type="category" tick={{ fontSize: 11 }} width={120} />
                          <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                          <Bar dataKey="cost_usd" name="Cost" fill={COLORS.chart[1]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Role Cost Details</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Role</TableHead>
                          <TableHead className="text-right">Cost</TableHead>
                          <TableHead className="text-right">Queries</TableHead>
                          <TableHead className="text-right">Share</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {attrData.by_role.map((r) => (
                          <TableRow key={r.role}>
                            <TableCell className="font-medium">{r.role}</TableCell>
                            <TableCell className="text-right">{formatCurrency(r.cost_usd)}</TableCell>
                            <TableCell className="text-right">{formatNumber(r.query_count)}</TableCell>
                            <TableCell className="text-right">{r.pct}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </>
            ) : (
              <Skeleton className="h-80 rounded-lg" />
            )}
          </TabsContent>

          {/* By Database */}
          <TabsContent value="database">
            {attrData ? (
              <>
                <Card className="mb-6">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Cost by Database</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-64">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={attrData.by_database} layout="vertical">
                          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} />
                          <YAxis dataKey="database" type="category" tick={{ fontSize: 11 }} width={120} />
                          <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                          <Bar dataKey="cost_usd" name="Cost" fill={COLORS.chart[2]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Database Cost Details</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Database</TableHead>
                          <TableHead className="text-right">Cost</TableHead>
                          <TableHead className="text-right">Queries</TableHead>
                          <TableHead className="text-right">Share</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {attrData.by_database.map((d) => (
                          <TableRow key={d.database}>
                            <TableCell className="font-medium">{d.database}</TableCell>
                            <TableCell className="text-right">{formatCurrency(d.cost_usd)}</TableCell>
                            <TableCell className="text-right">{formatNumber(d.query_count)}</TableCell>
                            <TableCell className="text-right">{d.pct}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </>
            ) : (
              <Skeleton className="h-80 rounded-lg" />
            )}
          </TabsContent>
        </Tabs>
      ) : null}
    </div>
  );
}
