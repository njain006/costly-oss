"use client";

import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import DataFreshness from "@/components/data-freshness";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { HardDrive, DollarSign, Database, AlertTriangle } from "lucide-react";
import { formatCurrency } from "@/lib/format";
import { COLORS } from "@/lib/constants";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

interface StorageData {
  tables: Array<{
    database: string; schema: string; table: string;
    size_gb: number; active_gb: number; time_travel_gb: number;
    failsafe_gb: number; stale: boolean;
  }>;
  total_gb: number;
  storage_cost_monthly: number;
  trend: Array<{ date: string; table_gb: number; stage_gb: number; failsafe_gb: number; total_gb: number }>;
  by_database: Array<{ database: string; total_gb: number; avg_db_gb: number; avg_failsafe_gb: number }>;
  fetched_at?: string;
  cached?: boolean;
  demo?: boolean;
}

interface StaleTable {
  database: string; schema: string; table: string;
  size_gb: number; last_queried: string; days_since_queried: number;
  monthly_cost: number; recommendation: string;
}

interface StaleTableData {
  stale_tables: StaleTable[];
  stale_count: number;
  stale_total_gb: number;
  stale_monthly_cost: number;
  available?: boolean;
  reason?: string;
  fetched_at?: string; demo?: boolean;
}

export default function StoragePage() {
  const { days, refreshTrigger } = useDateRange();
  const { data, loading } = useApi<StorageData>(
    `/storage?days=${days}&refresh=${refreshTrigger > 0}`,
    [days, refreshTrigger]
  );
  const { data: staleData } = useApi<StaleTableData>(
    `/stale-tables?days=${days}&refresh=${refreshTrigger > 0}`,
    [days, refreshTrigger]
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">Storage</h1>
          {data && <DataFreshness fetchedAt={data.fetched_at} cached={data.cached} demo={data.demo} />}
        </div>
        <DateRangePicker />
      </div>
      <DemoBanner />

      {loading ? (
        <Skeleton className="h-80 rounded-lg" />
      ) : data ? (
        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="stale">Stale Tables</TabsTrigger>
          </TabsList>

          {/* Overview (existing content) */}
          <TabsContent value="overview">
            <div className="grid md:grid-cols-3 gap-4 mb-6">
              <StatCard title="Total Storage" value={`${data.total_gb >= 1000 ? (data.total_gb / 1000).toFixed(1) + " TB" : data.total_gb.toFixed(1) + " GB"}`} icon={HardDrive} />
              <StatCard title="Monthly Cost" value={formatCurrency(data.storage_cost_monthly)} icon={DollarSign} />
              <StatCard title="Databases" value={data.by_database.length} icon={Database} />
            </div>

            <div className="grid lg:grid-cols-2 gap-6 mb-6">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Storage Growth</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={data.trend}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                        <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v} GB`} />
                        <Tooltip formatter={(v) => `${Number(v).toFixed(1)} GB`} />
                        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                        <Area type="monotone" dataKey="table_gb" stackId="1" fill={COLORS.primary} stroke={COLORS.primary} fillOpacity={0.6} name="Tables (incl. time travel)" />
                        <Area type="monotone" dataKey="stage_gb" stackId="1" fill={COLORS.chart[1]} stroke={COLORS.chart[1]} fillOpacity={0.4} name="Stage" />
                        <Area type="monotone" dataKey="failsafe_gb" stackId="1" fill={COLORS.chart[2]} stroke={COLORS.chart[2]} fillOpacity={0.3} name="Fail-safe" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">By Database</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Database</TableHead>
                        <TableHead className="text-right">Total GB</TableHead>
                        <TableHead className="text-right">Failsafe GB</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.by_database.map((d) => (
                        <TableRow key={d.database}>
                          <TableCell className="font-medium">{d.database}</TableCell>
                          <TableCell className="text-right">{d.total_gb.toFixed(1)}</TableCell>
                          <TableCell className="text-right">{d.avg_failsafe_gb.toFixed(1)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Tables</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Table</TableHead>
                      <TableHead className="text-right">Size GB</TableHead>
                      <TableHead className="text-right">Active GB</TableHead>
                      <TableHead className="text-right">Failsafe GB</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.tables.slice(0, 20).map((t) => (
                      <TableRow key={`${t.database}.${t.schema}.${t.table}`}>
                        <TableCell className="text-sm">
                          <span className="text-muted-foreground">{t.database}.{t.schema}.</span>
                          <span className="font-medium">{t.table}</span>
                        </TableCell>
                        <TableCell className="text-right text-sm">{t.size_gb.toFixed(1)}</TableCell>
                        <TableCell className="text-right text-sm">{t.active_gb.toFixed(1)}</TableCell>
                        <TableCell className="text-right text-sm">{t.failsafe_gb.toFixed(1)}</TableCell>
                        <TableCell>
                          {t.stale && <Badge variant="destructive" className="text-xs">Stale</Badge>}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Stale Tables tab */}
          <TabsContent value="stale">
            {staleData ? (
              <>
                <div className="grid md:grid-cols-3 gap-4 mb-6">
                  <StatCard title="Stale Tables" value={staleData.stale_count} icon={AlertTriangle} />
                  <StatCard title="Total Size" value={`${staleData.stale_total_gb.toFixed(1)} GB`} icon={HardDrive} />
                  <StatCard title="Monthly Waste" value={formatCurrency(staleData.stale_monthly_cost)} icon={DollarSign} />
                </div>

                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Tables Not Queried in 90+ Days</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {staleData.available === false ? (
                      <p className="text-sm text-muted-foreground py-8 text-center">Not checked: {staleData.reason}</p>
                    ) : staleData.stale_tables.length === 0 ? (
                      <p className="text-sm text-muted-foreground py-8 text-center">No stale tables found.</p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Table</TableHead>
                            <TableHead className="text-right">Size GB</TableHead>
                            <TableHead>Last Queried</TableHead>
                            <TableHead className="text-right">Days Since</TableHead>
                            <TableHead className="text-right">Monthly Cost</TableHead>
                            <TableHead>Recommendation</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {staleData.stale_tables.map((t) => (
                            <TableRow key={`${t.database}.${t.schema}.${t.table}`}>
                              <TableCell className="text-sm">
                                <span className="text-muted-foreground">{t.database}.{t.schema}.</span>
                                <span className="font-medium">{t.table}</span>
                              </TableCell>
                              <TableCell className="text-right">{t.size_gb.toFixed(1)}</TableCell>
                              <TableCell className="text-sm">{t.last_queried}</TableCell>
                              <TableCell className="text-right">{t.days_since_queried}</TableCell>
                              <TableCell className="text-right">{formatCurrency(t.monthly_cost)}</TableCell>
                              <TableCell>
                                <Badge
                                  variant={t.recommendation === "Drop or archive" ? "destructive" : "secondary"}
                                  className="text-xs"
                                >
                                  {t.recommendation}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
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
