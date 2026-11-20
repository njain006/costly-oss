"use client";

import { useState } from "react";
import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import AccessHint from "@/components/access-hint";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Layers, Hash, Clock } from "lucide-react";
import { formatNumber, formatDuration, formatCurrency } from "@/lib/format";

interface Workload {
  workload_id: string; sample_query: string; execution_count: number;
  avg_seconds: number; p95_seconds: number; total_seconds: number;
  total_credits: number; total_gb_scanned: number; sample_user: string; sample_warehouse: string;
}

interface WorkloadsData {
  workloads: Workload[];
  total_workloads: number;
  total_executions: number;
}

interface RunData {
  runs: Array<{
    query_id: string; start_time: string; duration_ms: number;
    user: string; warehouse: string; bytes_scanned: number; cache_hit_pct: number;
  }>;
}

interface QueryPattern {
  pattern_hash: string; example_query: string; execution_count: number;
  total_cost_usd: number; avg_duration_s: number; avg_scan_ratio: number;
  avg_spill_gb: number; avg_cache_pct: number; flags: string[]; recommendation: string;
}

interface QueryPatternData {
  patterns: QueryPattern[];
  total_patterns: number;
  total_cost_usd: number;
  fetched_at?: string; demo?: boolean;
}

const flagColors: Record<string, string> = {
  cacheable: "bg-sky-100 text-sky-700",
  full_scan: "bg-red-100 text-red-700",
  spilling: "bg-amber-100 text-amber-700",
};

export default function WorkloadsPage() {
  const { days, refreshTrigger } = useDateRange();
  const { data, loading, error } = useApi<WorkloadsData>(
    `/workloads?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const { data: patternData } = useApi<QueryPatternData>(
    `/query-patterns?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const [selectedWl, setSelectedWl] = useState<Workload | null>(null);
  const { data: runsData } = useApi<RunData>(
    selectedWl ? `/workloads/${selectedWl.workload_id}/runs?days=${days}` : null,
    [selectedWl?.workload_id, days]
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Workloads</h1>
        <DateRangePicker />
      </div>
      <DemoBanner />

      {!loading && !data && (
        <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">
          Could not load this page{error ? ` (${error})` : ""}. Results are prepared in the background every few hours;
          try again in a few minutes, or use refresh to compute now (can take a minute on large accounts).
        </div>
      )}
      {loading ? (
        <div>
          <Skeleton className="h-80 rounded-lg" />
          <p className="text-xs text-muted-foreground mt-2">Loading. The first load on a large account can take up to a minute.</p>
        </div>
      ) : data ? (
        <Tabs defaultValue="workloads">
          <TabsList>
            <TabsTrigger value="workloads">Recurring Workloads</TabsTrigger>
            <TabsTrigger value="patterns">Patterns</TabsTrigger>
          </TabsList>

          {/* Existing workloads content */}
          <TabsContent value="workloads">
            <div className="grid md:grid-cols-3 gap-4 mb-6">
              <StatCard title="Workloads" value={data.total_workloads} icon={Layers} />
              <StatCard title="Total Executions" value={formatNumber(data.total_executions)} icon={Hash} />
              <StatCard title="Period" value={`${days} days`} icon={Clock} />
            </div>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Recurring Query Patterns</CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="max-w-xs">Query</TableHead>
                      <TableHead className="text-right">Runs</TableHead>
                      <TableHead className="text-right">Avg</TableHead>
                      <TableHead className="text-right">P95</TableHead>
                      <TableHead className="text-right">Total GB</TableHead>
                      <TableHead>User</TableHead>
                      <TableHead>Warehouse</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.workloads.map((wl) => (
                      <TableRow
                        key={wl.workload_id}
                        className="cursor-pointer hover:bg-slate-50"
                        onClick={() => setSelectedWl(wl)}
                      >
                        <TableCell className="max-w-xs truncate text-xs text-muted-foreground font-mono">
                          {wl.sample_query}
                        </TableCell>
                        <TableCell className="text-right font-medium">{wl.execution_count}</TableCell>
                        <TableCell className="text-right">{wl.avg_seconds.toFixed(1)}s</TableCell>
                        <TableCell className="text-right">{wl.p95_seconds.toFixed(1)}s</TableCell>
                        <TableCell className="text-right">{wl.total_gb_scanned.toFixed(1)}</TableCell>
                        <TableCell className="text-sm">{wl.sample_user}</TableCell>
                        <TableCell className="text-sm">{wl.sample_warehouse}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {data.workloads.length === 0 && <AccessHint what="workloads" denied={(data as { query_history_available?: boolean }).query_history_available === false} timedOut={(data as { query_history_timed_out?: boolean }).query_history_timed_out === true} />}
              </CardContent>
            </Card>

            <Sheet open={!!selectedWl} onOpenChange={() => setSelectedWl(null)}>
              <SheetContent className="w-[600px] sm:max-w-[600px]">
                <SheetHeader>
                  <SheetTitle>Workload Runs</SheetTitle>
                </SheetHeader>
                {selectedWl && (
                  <div className="mt-4 space-y-4">
                    <div className="p-3 bg-slate-50 rounded-lg text-xs font-mono break-all">
                      {selectedWl.sample_query}
                    </div>
                    {runsData?.runs && (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Time</TableHead>
                            <TableHead>Duration</TableHead>
                            <TableHead>User</TableHead>
                            <TableHead>Cache %</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {runsData.runs.map((r) => (
                            <TableRow key={r.query_id}>
                              <TableCell className="text-xs">{new Date(r.start_time).toLocaleString()}</TableCell>
                              <TableCell>{formatDuration(r.duration_ms)}</TableCell>
                              <TableCell className="text-sm">{r.user}</TableCell>
                              <TableCell>{r.cache_hit_pct}%</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </div>
                )}
              </SheetContent>
            </Sheet>
          </TabsContent>

          {/* Patterns tab */}
          <TabsContent value="patterns">
            {patternData ? (
              <>
                <div className="grid md:grid-cols-3 gap-4 mb-6">
                  <StatCard title="Unique Patterns" value={patternData.total_patterns} icon={Layers} />
                  <StatCard title="Total Cost" value={formatCurrency(patternData.total_cost_usd)} icon={Hash} />
                  <StatCard title="Period" value={`${days} days`} icon={Clock} />
                </div>

                <div className="space-y-4">
                  {patternData.patterns.map((p) => (
                    <Card key={p.pattern_hash}>
                      <CardContent className="p-5">
                        <div className="flex items-start justify-between gap-4 mb-3">
                          <pre className="text-xs font-mono text-muted-foreground bg-slate-50 rounded-lg p-3 overflow-x-auto flex-1 max-w-full">
                            {p.example_query}
                          </pre>
                        </div>
                        <div className="flex items-center flex-wrap gap-2 mb-3">
                          {p.flags.map((flag) => (
                            <span key={flag} className={`text-xs font-medium px-2 py-0.5 rounded ${flagColors[flag] || "bg-slate-100 text-slate-700"}`}>
                              {flag}
                            </span>
                          ))}
                          <Badge variant="outline" className="text-xs">{p.execution_count}x runs</Badge>
                          <Badge variant="outline" className="text-xs">{formatCurrency(p.total_cost_usd)} total</Badge>
                          <Badge variant="outline" className="text-xs">{p.avg_duration_s.toFixed(1)}s avg</Badge>
                        </div>
                        <p className="text-sm text-muted-foreground">{p.recommendation}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
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
