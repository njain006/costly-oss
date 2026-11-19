"use client";

import LoadError from "@/components/load-error";

import { useState } from "react";
import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import api from "@/lib/api";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import DataFreshness from "@/components/data-freshness";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { COLORS } from "@/lib/constants";
import { formatCurrency } from "@/lib/format";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { AlertTriangle, TrendingDown, DollarSign } from "lucide-react";
import WarehouseHealth, { type WarehouseHealthData } from "@/components/warehouse-health";

interface WarehouseInfo {
  name: string; size: string; state: string; auto_suspend: number;
  min_cluster: number; max_cluster: number; credits_per_hour: number; config_visible?: boolean;
}

interface WarehouseData {
  warehouses: WarehouseInfo[];
  activity: Array<{ date: string; warehouse: string; credits: number }>;
  load_history: Array<{ date: string; warehouse: string; avg_running: number; avg_queued: number }>;
  wh_stats: Array<{ name: string; query_count: number; failed_count: number; avg_cache_hit_pct: number; avg_duration_s: number }>;
  fetched_at?: string;
  cached?: boolean;
  demo?: boolean;
}

interface AutoSuspendRec {
  warehouse: string; current_suspend_s: number | null; recommended_suspend_s: number | null;
  resume_count: number; idle_waste_credits: number; monthly_savings: number;
  ddl_command: string | null; gap_p50_s: number | null; gap_p75_s: number | null; needs_change: boolean;
  size?: string | null; metered_credits?: number; idle_pct?: number; idle_cost_monthly?: number; note?: string | null;
}

interface AutoSuspendData {
  recommendations: AutoSuspendRec[];
  total_monthly_savings: number;
  fetched_at?: string; demo?: boolean;
  total_idle_cost_monthly?: number;
}

interface SpillageData {
  by_warehouse: Array<{ warehouse: string; query_count: number; spill_local_gb: number; spill_remote_gb: number }>;
  by_user: Array<{ user: string; query_count: number; spill_local_gb: number; spill_remote_gb: number }>;
  top_queries: Array<{ query_id: string; warehouse: string; user: string; spill_local_gb: number; spill_remote_gb: number; duration_s: number; query_text: string }>;
  summary: { total_spill_gb: number; affected_queries: number; affected_warehouses: number };
  fetched_at?: string; demo?: boolean;
}

export default function WarehousesPage() {
  const { days, refreshTrigger } = useDateRange();
  const { data, loading, error: loadError } = useApi<WarehouseData>(
    `/warehouses?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const { data: sizingData } = useApi<WarehouseHealthData>(
    `/warehouses/sizing?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const { data: suspendData } = useApi<AutoSuspendData>(
    `/warehouses/autosuspend?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const { data: spillData } = useApi<SpillageData>(
    `/spillage?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );

  const [ddlDialog, setDdlDialog] = useState<{ open: boolean; ddl: string; type: string; warehouse: string; value: string }>({
    open: false, ddl: "", type: "", warehouse: "", value: "",
  });
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<{ success: boolean; message: string } | null>(null);

  const executeAction = async () => {
    setExecuting(true);
    setExecResult(null);
    try {
      if (ddlDialog.type === "resize") {
        const res = await api.post(`/warehouses/${ddlDialog.warehouse}/resize`, { new_size: ddlDialog.value }) as { success: boolean; error?: string };
        setExecResult({ success: res.success, message: res.success ? "Warehouse resized successfully" : (res.error || "Failed") });
      } else if (ddlDialog.type === "autosuspend") {
        const res = await api.post(`/warehouses/${ddlDialog.warehouse}/autosuspend`, { seconds: parseInt(ddlDialog.value) }) as { success: boolean; error?: string };
        setExecResult({ success: res.success, message: res.success ? "Auto-suspend updated successfully" : (res.error || "Failed") });
      }
    } catch (err) {
      setExecResult({ success: false, message: String(err) });
    }
    setExecuting(false);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">Warehouses</h1>
          {data && <DataFreshness fetchedAt={data.fetched_at} cached={data.cached} demo={data.demo} />}
        </div>
        <DateRangePicker />
      </div>
      <DemoBanner />

      <LoadError error={loadError} />
      {loading ? (
        <Skeleton className="h-80 rounded-lg" />
      ) : data ? (
        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="sizing">Health: queue &amp; spill</TabsTrigger>
            <TabsTrigger value="autosuspend">Auto-Suspend</TabsTrigger>
            <TabsTrigger value="spillage">Spillage</TabsTrigger>
          </TabsList>

          {/* Overview tab */}
          <TabsContent value="overview">
            <Card className="mb-6">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Warehouse Configuration</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Size</TableHead>
                      <TableHead>State</TableHead>
                      <TableHead>Auto-Suspend</TableHead>
                      <TableHead>Clusters</TableHead>
                      <TableHead>Credits/hr</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.warehouses.map((wh) => (
                      <TableRow key={wh.name}>
                        <TableCell className="font-medium">{wh.name}</TableCell>
                        <TableCell>{wh.size}</TableCell>
                        <TableCell>
                          <Badge variant={wh.state === "RUNNING" ? "default" : "secondary"} className="text-xs">
                            {wh.state === "unknown" ? "—" : wh.state}
                          </Badge>
                        </TableCell>
                        {wh.config_visible === false ? (
                          <>
                            <TableCell className="text-muted-foreground" title="This role cannot see the warehouse settings. Grant MONITOR on the warehouse to show them.">—</TableCell>
                            <TableCell className="text-muted-foreground">—</TableCell>
                            <TableCell>{wh.credits_per_hour || "—"}</TableCell>
                          </>
                        ) : (
                          <>
                            <TableCell>
                              {wh.auto_suspend === 0 ? "never" : `${wh.auto_suspend}s`}
                              {(wh.auto_suspend > 300 || wh.auto_suspend === 0) && (
                                <Badge variant="destructive" className="text-xs ml-2">High</Badge>
                              )}
                            </TableCell>
                            <TableCell>{wh.min_cluster}-{wh.max_cluster}</TableCell>
                            <TableCell>{wh.credits_per_hour}</TableCell>
                          </>
                        )}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <div className="grid lg:grid-cols-2 gap-6 mb-6">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Credits by Warehouse</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={(() => {
                        const map: Record<string, Record<string, number>> = {};
                        data.activity.forEach((a) => {
                          if (!map[a.date]) map[a.date] = {};
                          map[a.date][a.warehouse] = a.credits;
                        });
                        return Object.entries(map).map(([date, whs]) => ({ date, ...whs }));
                      })()}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                        <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                        <YAxis tick={{ fontSize: 11 }} />
                        <Tooltip />
                        <Legend />
                        {data.warehouses.map((wh, i) => (
                          <Bar key={wh.name} dataKey={wh.name} stackId="1" fill={COLORS.chart[i % COLORS.chart.length]} />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Health Metrics</CardTitle>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Warehouse</TableHead>
                        <TableHead className="text-right">Queries</TableHead>
                        <TableHead className="text-right">Cache Hit %</TableHead>
                        <TableHead className="text-right">Avg Duration</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.wh_stats.map((s) => (
                        <TableRow key={s.name}>
                          <TableCell className="font-medium">{s.name}</TableCell>
                          <TableCell className="text-right">{s.query_count.toLocaleString()}</TableCell>
                          <TableCell className="text-right">{s.avg_cache_hit_pct}%</TableCell>
                          <TableCell className="text-right">{s.avg_duration_s}s</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* Right-Sizing tab */}
          <TabsContent value="sizing">
            {sizingData ? (
              <WarehouseHealth
                data={sizingData}
                onResize={(rec) => setDdlDialog({
                  open: true,
                  ddl: rec.ddl_command!,
                  type: "resize",
                  warehouse: rec.warehouse,
                  value: rec.recommended_size,
                })}
              />
            ) : (
              <Skeleton className="h-80 rounded-lg" />
            )}
          </TabsContent>

          {/* Auto-Suspend tab */}
          <TabsContent value="autosuspend">
            {suspendData ? (
              <>
                {(suspendData.total_idle_cost_monthly ?? 0) > 0 && (
                  <Card className="mb-6 bg-amber-50 border-amber-200">
                    <CardContent className="p-5">
                      <div className="text-sm text-amber-800">Idle warehouse spend (running with no queries), per month</div>
                      <div className="text-3xl font-bold text-amber-900">{formatCurrency(suspendData.total_idle_cost_monthly!)}</div>
                      <div className="text-xs text-amber-700 mt-1">Metered compute minus credits attributed to queries. Includes auto-suspend tails, the 60s minimum per resume and gaps between queries. Upper bound on what tuning can save.</div>
                    </CardContent>
                  </Card>
                )}
                {suspendData.total_monthly_savings > 0 && (
                  <Card className="mb-6 bg-emerald-50 border-emerald-200">
                    <CardContent className="p-5 flex items-center gap-4">
                      <div className="h-12 w-12 rounded-lg bg-emerald-100 flex items-center justify-center">
                        <DollarSign className="h-6 w-6 text-emerald-600" />
                      </div>
                      <div>
                        <div className="text-sm text-emerald-700">Potential Monthly Savings from Auto-Suspend Tuning</div>
                        <div className="text-3xl font-bold text-emerald-800">{formatCurrency(suspendData.total_monthly_savings)}</div>
                      </div>
                    </CardContent>
                  </Card>
                )}
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Auto-Suspend Recommendations</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Warehouse</TableHead>
                          <TableHead className="text-right">Idle %</TableHead>
                          <TableHead className="text-right">Idle $/mo</TableHead>
                          <TableHead className="text-right">Current</TableHead>
                          <TableHead className="text-right">Recommended</TableHead>
                          <TableHead className="text-right">P75 Gap</TableHead>
                          <TableHead className="text-right">Resume Count</TableHead>
                          <TableHead className="text-right">Idle Waste</TableHead>
                          <TableHead className="text-right">Monthly Savings</TableHead>
                          <TableHead>Action</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {suspendData.recommendations.map((rec) => (
                          <TableRow key={rec.warehouse}>
                            <TableCell className="font-medium whitespace-normal min-w-[220px] max-w-[360px]">
                              {rec.warehouse}
                              {rec.size && <span className="ml-1 text-xs text-muted-foreground">{rec.size}</span>}
                              {rec.note && <div className="text-xs text-muted-foreground font-normal">{rec.note}</div>}
                            </TableCell>
                            <TableCell className={`text-right text-sm ${(rec.idle_pct ?? 0) >= 50 ? "text-amber-600 font-semibold" : ""}`}>{rec.idle_pct != null ? `${rec.idle_pct.toFixed(0)}%` : "—"}</TableCell>
                            <TableCell className="text-right text-sm">{rec.idle_cost_monthly != null ? formatCurrency(rec.idle_cost_monthly) : "—"}</TableCell>
                            <TableCell className="text-right">{rec.current_suspend_s != null ? `${rec.current_suspend_s}s` : "?"}</TableCell>
                            <TableCell className="text-right">
                              {rec.recommended_suspend_s == null ? (
                                <span className="text-muted-foreground">—</span>
                              ) : rec.needs_change ? (
                                <span className="font-semibold text-sky-700">{rec.recommended_suspend_s}s</span>
                              ) : (
                                <span className="text-muted-foreground">{rec.recommended_suspend_s}s</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right text-sm">{rec.gap_p75_s != null ? `${rec.gap_p75_s}s` : "—"}</TableCell>
                            <TableCell className="text-right text-sm">{rec.resume_count.toLocaleString()}</TableCell>
                            <TableCell className="text-right text-sm">
                              {rec.idle_waste_credits > 0 ? (
                                <span className="text-amber-600">{rec.idle_waste_credits.toFixed(1)} credits</span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right">
                              {rec.monthly_savings > 0 ? (
                                <span className="font-semibold text-emerald-600">{formatCurrency(rec.monthly_savings)}</span>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                            </TableCell>
                            <TableCell>
                              {rec.ddl_command && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => setDdlDialog({
                                    open: true,
                                    ddl: rec.ddl_command!,
                                    type: "autosuspend",
                                    warehouse: rec.warehouse,
                                    value: String(rec.recommended_suspend_s),
                                  })}
                                >
                                  Update
                                </Button>
                              )}
                            </TableCell>
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

          {/* Spillage tab */}
          <TabsContent value="spillage">
            {spillData ? (
              <>
                <div className="grid md:grid-cols-3 gap-4 mb-6">
                  <StatCard title="Total Spillage" value={`${spillData.summary.total_spill_gb.toFixed(1)} GB`} icon={AlertTriangle} />
                  <StatCard title="Affected Queries" value={spillData.summary.affected_queries.toLocaleString()} icon={TrendingDown} />
                  <StatCard title="Affected Warehouses" value={spillData.summary.affected_warehouses} icon={TrendingDown} />
                </div>

                <div className="grid lg:grid-cols-2 gap-6 mb-6">
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">Spillage by Warehouse</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={spillData.by_warehouse} layout="vertical">
                            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                            <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `${v} GB`} />
                            <YAxis dataKey="warehouse" type="category" tick={{ fontSize: 11 }} width={120} />
                            <Tooltip />
                            <Legend />
                            <Bar dataKey="spill_local_gb" name="Local" fill={COLORS.chart[0]} stackId="1" />
                            <Bar dataKey="spill_remote_gb" name="Remote" fill={COLORS.chart[3]} stackId="1" />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base">Spillage by User</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>User</TableHead>
                            <TableHead className="text-right">Queries</TableHead>
                            <TableHead className="text-right">Local GB</TableHead>
                            <TableHead className="text-right">Remote GB</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {spillData.by_user.map((u) => (
                            <TableRow key={u.user}>
                              <TableCell className="font-medium">{u.user}</TableCell>
                              <TableCell className="text-right">{u.query_count}</TableCell>
                              <TableCell className="text-right">{u.spill_local_gb.toFixed(1)}</TableCell>
                              <TableCell className="text-right">{u.spill_remote_gb.toFixed(1)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>
                </div>

                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Top Spilling Queries</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="max-w-xs">Query</TableHead>
                          <TableHead>Warehouse</TableHead>
                          <TableHead>User</TableHead>
                          <TableHead className="text-right">Local GB</TableHead>
                          <TableHead className="text-right">Remote GB</TableHead>
                          <TableHead className="text-right">Duration</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {spillData.top_queries.map((q) => (
                          <TableRow key={q.query_id}>
                            <TableCell className="max-w-xs truncate text-xs text-muted-foreground font-mono">{q.query_text}</TableCell>
                            <TableCell className="text-sm">{q.warehouse}</TableCell>
                            <TableCell className="text-sm">{q.user}</TableCell>
                            <TableCell className="text-right">{q.spill_local_gb.toFixed(1)}</TableCell>
                            <TableCell className="text-right">{q.spill_remote_gb.toFixed(1)}</TableCell>
                            <TableCell className="text-right">{q.duration_s.toFixed(0)}s</TableCell>
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

      {/* DDL Confirmation Dialog */}
      <Dialog open={ddlDialog.open} onOpenChange={(open) => {
        if (!open) {
          setDdlDialog({ open: false, ddl: "", type: "", warehouse: "", value: "" });
          setExecResult(null);
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm DDL Execution</DialogTitle>
            <DialogDescription>
              The following SQL command will be executed on your connected warehouse:
            </DialogDescription>
          </DialogHeader>
          <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-sm font-mono overflow-x-auto">
            {ddlDialog.ddl}
          </pre>
          {execResult && (
            <div className={`rounded-lg p-3 text-sm ${execResult.success ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>
              {execResult.message}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              setDdlDialog({ open: false, ddl: "", type: "", warehouse: "", value: "" });
              setExecResult(null);
            }}>
              Cancel
            </Button>
            {!execResult?.success && (
              <Button onClick={executeAction} disabled={executing}>
                {executing ? "Executing..." : "Execute"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
