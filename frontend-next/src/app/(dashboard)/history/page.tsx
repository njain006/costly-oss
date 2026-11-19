"use client";

import LoadError from "@/components/load-error";

import { useState, useCallback } from "react";
import { useDateRange } from "@/providers/date-range-provider";
import { useApi } from "@/hooks/use-api";
import DateRangePicker from "@/components/date-range-picker";
import DemoBanner from "@/components/demo-banner";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import AccessHint from "@/components/access-hint";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Download, RefreshCw, Loader2 } from "lucide-react";
import { formatDuration, formatBytes, formatCurrency } from "@/lib/format";

interface HistoryData {
  data: Array<{
    query_id: string; user_name: string; warehouse_name: string; query_type: string;
    total_elapsed_ms: number; bytes_scanned: number; cost_usd: number;
    execution_status: string; query_text: string; end_time: string;
  }>;
  total: number; page: number; pages: number;
  summary: { total_elapsed_sum_ms?: number; cost_usd_sum?: number; failed_count?: number };
  filter_options: { warehouses: string[]; databases: string[]; users: string[] };
}

export default function QueryHistoryPage() {
  const { days } = useDateRange();
  const [warehouse, setWarehouse] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [syncing, setSyncing] = useState(false);

  const params = new URLSearchParams({ days: String(days), page: String(page), limit: "50" });
  if (warehouse) params.set("warehouse", warehouse);
  if (status) params.set("status", status);
  if (search) params.set("query_text_search", search);

  const { data, loading, error: loadError, refetch } = useApi<HistoryData>(
    `/history/queries?${params.toString()}`,
    [days, warehouse, status, search, page]
  );

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      await api.post(`/sync/queries?days=${days}`);
      refetch();
    } catch {
      // error
    } finally {
      setSyncing(false);
    }
  }, [days, refetch]);

  const handleExport = useCallback(() => {
    const exportParams = new URLSearchParams({ days: String(days) });
    if (warehouse) exportParams.set("warehouse", warehouse);
    if (status) exportParams.set("status", status);
    if (search) exportParams.set("query_text_search", search);
    window.open(`/api/history/export?${exportParams.toString()}`, "_blank");
  }, [days, warehouse, status, search]);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Query History</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleSync} disabled={syncing}>
            {syncing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            Sync
          </Button>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="h-4 w-4 mr-2" />
            Export CSV
          </Button>
          <DateRangePicker />
        </div>
      </div>
      <DemoBanner />

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <Select value={warehouse} onValueChange={setWarehouse}>
          <SelectTrigger className="w-44"><SelectValue placeholder="All Warehouses" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">All Warehouses</SelectItem>
            {data?.filter_options?.warehouses.map((w) => (
              <SelectItem key={w} value={w}>{w}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-36"><SelectValue placeholder="All Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">All Status</SelectItem>
            <SelectItem value="SUCCESS">Success</SelectItem>
            <SelectItem value="FAIL">Failed</SelectItem>
          </SelectContent>
        </Select>
        <Input
          placeholder="Search query text..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="max-w-xs"
        />
      </div>

      {/* Summary */}
      {data?.summary && (
        <div className="flex gap-4 mb-4 text-sm text-muted-foreground">
          <span>{data.total.toLocaleString()} queries</span>
          {data.summary.cost_usd_sum != null && <span>Total cost: {formatCurrency(data.summary.cost_usd_sum)}</span>}
          {data.summary.failed_count != null && data.summary.failed_count > 0 && (
            <span className="text-red-500">{data.summary.failed_count} failed</span>
          )}
        </div>
      )}

      <LoadError error={loadError} />
      {loading ? (
        <Skeleton className="h-80 rounded-lg" />
      ) : data ? (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Warehouse</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Scanned</TableHead>
                  <TableHead>Cost</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="max-w-xs">Query</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.data.map((q) => (
                  <TableRow key={q.query_id}>
                    <TableCell className="text-xs">{new Date(q.end_time).toLocaleString()}</TableCell>
                    <TableCell className="text-sm">{q.user_name}</TableCell>
                    <TableCell className="text-sm">{q.warehouse_name}</TableCell>
                    <TableCell className="text-sm">{formatDuration(q.total_elapsed_ms)}</TableCell>
                    <TableCell className="text-sm">{formatBytes(q.bytes_scanned)}</TableCell>
                    <TableCell className="text-sm">{formatCurrency(q.cost_usd)}</TableCell>
                    <TableCell>
                      <Badge variant={q.execution_status === "FAIL" ? "destructive" : "secondary"} className="text-xs">
                        {q.execution_status}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-muted-foreground font-mono">
                      {q.query_text}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
              {data.data.length === 0 && <AccessHint what="query history" denied={(data as { query_history_available?: boolean }).query_history_available === false} timedOut={(data as { query_history_timed_out?: boolean }).query_history_timed_out === true} />}

            {/* Pagination */}
            {data.pages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t">
                <span className="text-sm text-muted-foreground">
                  Page {data.page} of {data.pages}
                </span>
                <div className="flex gap-2">
                  <Button
                    variant="outline" size="sm"
                    disabled={page <= 1}
                    onClick={() => setPage(page - 1)}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline" size="sm"
                    disabled={page >= data.pages}
                    onClick={() => setPage(page + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
