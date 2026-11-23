"use client";

import UserTypeFilter, { filterByUserType, useUserTypeFilter } from "@/components/user-type-filter";

import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import AccessHint from "@/components/access-hint";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDuration, formatBytes } from "@/lib/format";
import { COLORS } from "@/lib/constants";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";

interface QueryData {
  data: Array<{
    query_id: string;
    user: string;
    user_type?: string;
    user_type_source?: string;
    warehouse: string;
    duration_ms: number;
    bytes_scanned: number;
    query_text: string;
    execution_ms: number;
    compilation_ms: number;
    queue_overload_ms: number;
    blocked_ms: number;
    execution_status?: string;
    cost_usd?: number;
  }>;
  total: number;
  page: number;
  pages: number;
}

export default function QueryPerformancePage() {
  const { days, refreshTrigger } = useDateRange();
  const { data, loading, error } = useApi<QueryData>(
    `/queries?days=${days}&refresh=${refreshTrigger}`,
    [days, refreshTrigger]
  );
  const userType = useUserTypeFilter();
  const rowsShown = filterByUserType(data?.data ?? [], userType, (q) => q.user_type);

  const phaseData = data?.data.slice(0, 10).map((q) => ({
    id: q.query_id.slice(0, 8),
    execution: q.execution_ms,
    compilation: q.compilation_ms,
    queue: q.queue_overload_ms,
    blocked: q.blocked_ms,
  }));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Query Performance</h1>
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
        <>
          {phaseData && phaseData.length > 0 && (
            <Card className="mb-6">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Top 10 Queries - Phase Breakdown</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={phaseData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                      <XAxis dataKey="id" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => formatDuration(v)} />
                      <Tooltip formatter={(v) => formatDuration(Number(v))} />
                      <Legend />
                      <Bar dataKey="execution" stackId="1" fill={COLORS.primary} name="Execution" />
                      <Bar dataKey="compilation" stackId="1" fill={COLORS.chart[1]} name="Compilation" />
                      <Bar dataKey="queue" stackId="1" fill={COLORS.chart[2]} name="Queue" />
                      <Bar dataKey="blocked" stackId="1" fill={COLORS.chart[3]} name="Blocked" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base">Queries ({data.total.toLocaleString()} total)</CardTitle>
                <div className="flex items-center gap-2">
                  {userType !== "all" && (
                    <span className="text-xs text-muted-foreground">
                      {rowsShown.length} of the {data.data.length} slowest on this page
                    </span>
                  )}
                  <UserTypeFilter />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>User</TableHead>
                    <TableHead>Warehouse</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Scanned</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="max-w-xs">Query</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rowsShown.map((q) => (
                    <TableRow key={q.query_id}>
                      <TableCell className="font-medium text-sm">{q.user}{q.user_type && <span className="ml-1.5 text-[10px] text-muted-foreground">{q.user_type === "service" ? "service" : "person"}{q.user_type_source === "guess" ? "?" : ""}</span>}</TableCell>
                      <TableCell className="text-sm">{q.warehouse}</TableCell>
                      <TableCell className="text-sm">{formatDuration(q.duration_ms)}</TableCell>
                      <TableCell className="text-sm">{formatBytes(q.bytes_scanned)}</TableCell>
                      <TableCell>
                        <Badge variant={q.execution_status === "FAIL" ? "destructive" : "secondary"} className="text-xs">
                          {q.execution_status || "SUCCESS"}
                        </Badge>
                      </TableCell>
                      <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                        {q.query_text}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {data.data.length === 0 && <AccessHint what="queries" denied={(data as { query_history_available?: boolean }).query_history_available === false} timedOut={(data as { query_history_timed_out?: boolean }).query_history_timed_out === true} />}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
