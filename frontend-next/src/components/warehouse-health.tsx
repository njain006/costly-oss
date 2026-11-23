"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import AccessHint from "@/components/access-hint";
import { formatCurrency } from "@/lib/format";

export interface HealthFinding {
  kind: "too_small" | "busy" | "memory" | "cold_starts" | "oversized" | "unknown";
  severity: "high" | "medium" | "low" | "info";
  title: string;
  detail: string;
}

export interface WarehouseHealthRec {
  warehouse: string;
  current_size: string;
  recommended_size: string;
  avg_utilization: number;
  monthly_cost?: number;
  queries?: number;
  queued_queries?: number;
  queued_pct?: number;
  queued_hours?: number;
  queue_p95_s?: number;
  provisioning_queries?: number;
  provisioning_hours?: number;
  spill_local_gb: number;
  spill_remote_gb: number;
  spill_local_queries?: number;
  spill_remote_queries?: number;
  spill_time_pct?: number;
  p95_elapsed_s?: number;
  verdict?: string;
  is_app_warehouse?: boolean;
  findings?: HealthFinding[];
  savings_upper_bound?: number | null;
  ddl_command: string | null;
  reason: string;
  needs_change: boolean;
}

export interface WarehouseHealthData {
  recommendations: WarehouseHealthRec[];
  query_history_available?: boolean;
  query_history_timed_out?: boolean;
  days?: number;
}

const VERDICT: Record<string, { label: string; className: string }> = {
  too_small: { label: "Out of memory", className: "bg-red-100 text-red-800 border-red-200" },
  busy: { label: "Queueing", className: "bg-amber-100 text-amber-800 border-amber-200" },
  memory: { label: "Memory pressure", className: "bg-orange-100 text-orange-800 border-orange-200" },
  cold_starts: { label: "Cold starts", className: "bg-sky-100 text-sky-800 border-sky-200" },
  oversized: { label: "Maybe oversized", className: "bg-violet-100 text-violet-800 border-violet-200" },
  unknown: { label: "Not checked", className: "bg-slate-100 text-slate-600 border-slate-200" },
  healthy: { label: "Healthy", className: "bg-emerald-100 text-emerald-800 border-emerald-200" },
};

// One short "what to do" per finding kind; the full explanation lives in
// "How to read this" so it is not repeated under every warehouse.
const ACTION: Record<string, string> = {
  too_small: "Try one size up for the spilling queries, or rewrite them.",
  busy: "Add clusters (MAX_CLUSTER_COUNT) or move a workload to its own warehouse.",
  memory: "If these queries are slow, try them on one size up.",
  cold_starts: "Normal with short auto-suspend; change only if people notice delays.",
  oversized: "Test one size down with real workloads.",
};

const GLOSSARY = [
  {
    term: "Queue wait",
    text: "Time a query waited because the warehouse was already running as many queries as it can. Fix with more clusters or by splitting workloads, not a bigger size.",
  },
  {
    term: "Cold-start wait",
    text: "Time a query waited for a suspended warehouse (or a new cluster) to start. Normal with short auto-suspend; only matters if people notice.",
  },
  {
    term: "Local spill",
    text: "The query ran out of memory and used the warehouse's local disk. Still works, but slower. A little is normal; a lot means the heavy queries want more memory.",
  },
  {
    term: "Remote spill",
    text: "The query ran out of memory and local disk, and wrote to remote storage. Much slower and costlier. Almost always worth fixing: one size up, or rewrite the query.",
  },
  {
    term: "Load",
    text: "Average number of queries running at once. Low load with no queue and no spill suggests a smaller size may do.",
  },
];

function fmtHours(h?: number) {
  if (!h) return "0";
  if (h < 1) return `${Math.round(h * 60)} min`;
  return `${h.toFixed(1)} h`;
}

function fmtGb(gb: number) {
  if (gb >= 1024) return `${(gb / 1024).toFixed(1)} TB`;
  if (gb >= 1) return `${gb.toFixed(0)} GB`;
  if (gb > 0) return `${(gb * 1024).toFixed(0)} MB`;
  return "0";
}

function fmtSeconds(s?: number) {
  if (!s) return "—";
  if (s >= 3600) return `${(s / 3600).toFixed(1)} h`;
  if (s >= 60) return `${(s / 60).toFixed(1)} min`;
  return `${s.toFixed(1)} s`;
}

export default function WarehouseHealth({
  data,
  onResize,
}: {
  data: WarehouseHealthData;
  onResize: (rec: WarehouseHealthRec) => void;
}) {
  const recs = data.recommendations;
  const counts = recs.reduce<Record<string, number>>((acc, r) => {
    const v = r.verdict ?? "healthy";
    acc[v] = (acc[v] ?? 0) + 1;
    return acc;
  }, {});
  const queuedHours = recs.reduce((s, r) => s + (r.queued_hours ?? 0), 0);
  const coldHours = recs.reduce((s, r) => s + (r.provisioning_hours ?? 0), 0);
  const localGb = recs.reduce((s, r) => s + r.spill_local_gb, 0);
  const remoteGb = recs.reduce((s, r) => s + r.spill_remote_gb, 0);
  const needsAttention = recs.filter((r) => r.findings && r.findings.length > 0 && r.verdict !== "unknown");

  return (
    <div className="space-y-6">
      {(data.query_history_available === false || data.query_history_timed_out) && (
        <AccessHint what="queue and spill data" denied={data.query_history_available === false} timedOut={data.query_history_timed_out} />
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryTile label="Queue wait" value={fmtHours(queuedHours)} hint="Queries waiting for capacity" warn={queuedHours >= 1} />
        <SummaryTile label="Cold-start wait" value={fmtHours(coldHours)} hint="Waiting for a warehouse to start" />
        <SummaryTile label="Local spill" value={fmtGb(localGb)} hint="Ran out of memory, used local disk" warn={localGb >= 100} />
        <SummaryTile label="Remote spill" value={fmtGb(remoteGb)} hint="Ran out of memory and disk" warn={remoteGb >= 1} danger={remoteGb >= 1} />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            {needsAttention.length === 0
              ? "All warehouses look healthy"
              : `${needsAttention.length} warehouse${needsAttention.length === 1 ? "" : "s"} need a look`}
          </CardTitle>
          <div className="flex flex-wrap gap-2 pt-1">
            {Object.entries(counts).map(([v, n]) => (
              <Badge key={v} variant="outline" className={VERDICT[v]?.className}>
                {VERDICT[v]?.label ?? v}: {n}
              </Badge>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {needsAttention.map((r) => (
            <div key={r.warehouse} className="rounded-lg border p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{r.warehouse}</span>
                {r.is_app_warehouse && (
                  <Badge variant="outline" className="text-[10px]">used by this app</Badge>
                )}
                <span className="text-xs text-muted-foreground">
                  {r.current_size}
                  {r.monthly_cost ? ` · ${formatCurrency(r.monthly_cost)}/mo` : ""}
                  {r.queries ? ` · ${r.queries.toLocaleString()} queries` : ""}
                </span>
                {r.ddl_command && (
                  <Button size="sm" variant="outline" className="ml-auto h-7" onClick={() => onResize(r)}>
                    Try {r.recommended_size}
                  </Button>
                )}
              </div>
              <ul className="mt-2 space-y-1.5">
                {r.findings!.map((f, i) => (
                  <li key={i} className="text-sm">
                    <Badge variant="outline" className={`mr-2 ${VERDICT[f.kind]?.className ?? ""}`}>
                      {VERDICT[f.kind]?.label ?? f.kind}
                    </Badge>
                    <span className="font-medium">{f.title}</span>
                    {ACTION[f.kind] && <span className="text-muted-foreground"> — {ACTION[f.kind]}</span>}
                  </li>
                ))}
              </ul>
              {r.savings_upper_bound ? (
                <p className="text-xs text-muted-foreground mt-2">
                  At most {formatCurrency(r.savings_upper_bound)}/mo if nothing slows down. Test before keeping it.
                </p>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Every warehouse</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Warehouse</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Queued</TableHead>
                <TableHead className="text-right">Queue wait</TableHead>
                <TableHead className="text-right">Slowest 5% queued</TableHead>
                <TableHead className="text-right">Cold-start wait</TableHead>
                <TableHead className="text-right">Local spill</TableHead>
                <TableHead className="text-right">Remote spill</TableHead>
                <TableHead className="text-right">Time in spilling queries</TableHead>
                <TableHead className="text-right">Slowest 5% queries</TableHead>
                <TableHead className="text-right">Load</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recs.map((r) => {
                const v = VERDICT[r.verdict ?? "healthy"] ?? VERDICT.healthy;
                return (
                  <TableRow key={r.warehouse}>
                    <TableCell>
                      <div className="font-medium">{r.warehouse}</div>
                      <div className="text-xs text-muted-foreground">{r.current_size}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={v.className}>{v.label}</Badge>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.queued_queries ? `${r.queued_queries.toLocaleString()} (${(r.queued_pct ?? 0).toFixed(1)}%)` : "0"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmtHours(r.queued_hours)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtSeconds(r.queue_p95_s)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtHours(r.provisioning_hours)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {fmtGb(r.spill_local_gb)}
                      {r.spill_local_queries ? <div className="text-xs text-muted-foreground">{r.spill_local_queries.toLocaleString()} queries</div> : null}
                    </TableCell>
                    <TableCell className={`text-right tabular-nums ${r.spill_remote_gb >= 1 ? "text-red-600 font-semibold" : ""}`}>
                      {fmtGb(r.spill_remote_gb)}
                      {r.spill_remote_queries ? <div className="text-xs text-muted-foreground">{r.spill_remote_queries.toLocaleString()} queries</div> : null}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{r.spill_time_pct ? `${r.spill_time_pct.toFixed(0)}%` : "0%"}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtSeconds(r.p95_elapsed_s)}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.avg_utilization.toFixed(2)}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground mt-3">
            Last {data.days ?? 30} days, from Snowflake query history. &quot;Slowest 5%&quot; is the 95th percentile.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">How to read this</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid md:grid-cols-2 gap-x-8 gap-y-3 text-sm">
            {GLOSSARY.map((g) => (
              <div key={g.term}>
                <dt className="font-medium">{g.term}</dt>
                <dd className="text-muted-foreground">{g.text}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryTile({ label, value, hint, warn, danger }: { label: string; value: string; hint: string; warn?: boolean; danger?: boolean }) {
  return (
    <Card className={danger ? "border-red-200" : warn ? "border-amber-200" : undefined}>
      <CardContent className="p-4">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className={`text-2xl font-bold tabular-nums ${danger ? "text-red-600" : warn ? "text-amber-600" : ""}`}>{value}</div>
        <div className="text-xs text-muted-foreground mt-1">{hint}</div>
      </CardContent>
    </Card>
  );
}
