"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useApi } from "@/hooks/use-api";
import api from "@/lib/api";
import DemoBanner from "@/components/demo-banner";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle,
  BellOff,
  CheckCircle2,
  RefreshCcw,
  Sparkles,
  TrendingUp,
} from "lucide-react";
import { AnomalyRow } from "@/components/anomalies/anomaly-row";
import { AnomalyDetailSheet } from "@/components/anomalies/anomaly-detail-sheet";
import {
  ackLocal,
  buildAnomalyList,
  clearSignature,
  emptyLocalState,
  loadLocalState,
  markExpected,
  muteSignature,
  saveLocalState,
  type AnomalyStatus,
  type DailyTrendPoint,
  type LocalAnomalyState,
  type MuteDuration,
  type NormalizedAnomaly,
  type RawAnomaly,
} from "@/lib/anomalies";

type StatusFilter = "all" | "open" | "muted" | "resolved";

interface AnomalyResponse {
  anomalies?: RawAnomaly[];
  count?: number;
  unacknowledged?: number;
}

interface UnifiedCosts {
  daily_trend?: DailyTrendPoint[];
  demo?: boolean;
}

// Accept either `{anomalies: [...]}` (router shape) or a bare array
// (some demo endpoints/error fallbacks). Normalise to an array.
function coerceList(data: unknown): RawAnomaly[] {
  if (!data) return [];
  if (Array.isArray(data)) return data as RawAnomaly[];
  if (typeof data === "object" && data !== null) {
    const maybe = (data as AnomalyResponse).anomalies;
    if (Array.isArray(maybe)) return maybe;
  }
  return [];
}

export default function AnomaliesPage() {
  const [days, setDays] = useState(30);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("open");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [local, setLocal] = useState<LocalAnomalyState>(() => emptyLocalState());
  const [selected, setSelected] = useState<(NormalizedAnomaly & { status: AnomalyStatus }) | null>(null);
  const [running, setRunning] = useState(false);

  // Hydrate local state from storage on mount.
  useEffect(() => {
    setLocal(loadLocalState());
  }, []);

  const { data: raw, loading, refetch, error } = useApi<AnomalyResponse | RawAnomaly[]>(`/anomalies?days=${days}`, [days]);
  const { data: costs } = useApi<UnifiedCosts>(`/platforms/costs?days=${days}`, [days]);

  const updateLocal = useCallback((next: LocalAnomalyState) => {
    setLocal(next);
    saveLocalState(next);
  }, []);

  const persistAck = useCallback(
    async (id: string) => {
      // Optimistic local ack first — API may fail for derived anomalies that
      // don't have a server record, which is expected. Don't surface an error.
      updateLocal(ackLocal(local, id));
      if (id.startsWith("derived-")) return;
      try {
        await api.post(`/anomalies/${id}/acknowledge`);
        refetch();
      } catch {
        // Keep the local ack even if the server call errors.
      }
    },
    [local, refetch, updateLocal],
  );

  const handleMute = useCallback(
    (a: NormalizedAnomaly, duration: MuteDuration) => {
      updateLocal(muteSignature(local, a.signature, duration));
    },
    [local, updateLocal],
  );

  const handleMarkExpected = useCallback(
    (a: NormalizedAnomaly) => {
      updateLocal(markExpected(local, a.signature));
    },
    [local, updateLocal],
  );

  const handleClearSignature = useCallback(
    (signature: string) => {
      updateLocal(clearSignature(local, signature));
    },
    [local, updateLocal],
  );

  const rawList = useMemo(() => coerceList(raw), [raw]);

  const { items, counts, fallbackUsed } = useMemo(
    () =>
      buildAnomalyList({
        raw: rawList,
        dailyTrend: costs?.daily_trend,
        local,
        statusFilter,
        platformFilter,
      }),
    [rawList, costs, local, statusFilter, platformFilter],
  );

  const platforms = useMemo(() => {
    const set = new Set<string>();
    for (const r of rawList) if (r.platform) set.add(r.platform);
    return Array.from(set).sort();
  }, [rawList]);

  // KPIs
  const totalImpact = useMemo(
    () => items.filter((i) => i.status === "new").reduce((s, i) => s + Math.abs(i.deltaUsd), 0),
    [items],
  );
  const highSeverityCount = items.filter((i) => i.severity === "high" && i.status === "new").length;

  const handleRunDetection = async () => {
    setRunning(true);
    try {
      await api.post("/anomalies/detect");
      refetch();
    } catch {
      // ignore — user can retry
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <header className="flex items-start justify-between gap-4 mb-6 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Anomalies</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Cost spikes detected automatically from your unified spend history. Mute, acknowledge, or mark patterns as expected to train the detector.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <SelectTrigger className="h-9 w-[110px]" aria-label="Date range">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="14">Last 14 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 90 days</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRunDetection}
            disabled={running}
            className="gap-1.5"
            aria-label="Run anomaly detection now"
          >
            <RefreshCcw className={`h-3.5 w-3.5 ${running ? "animate-spin" : ""}`} />
            {running ? "Detecting..." : "Re-scan"}
          </Button>
        </div>
      </header>

      <DemoBanner />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard
          title="Open anomalies"
          value={counts.new}
          icon={AlertTriangle}
          description={`${highSeverityCount} high-severity`}
        />
        <StatCard
          title="Impact today"
          value={totalImpact > 0 ? `$${totalImpact.toFixed(0)}` : "$0"}
          icon={TrendingUp}
          description="Sum of new spikes vs baseline"
        />
        <StatCard
          title="Acknowledged"
          value={counts.acknowledged}
          icon={CheckCircle2}
          description="Seen, still open"
        />
        <StatCard
          title="Muted / expected"
          value={counts.muted + counts.expected}
          icon={BellOff}
          description="Suppressed from default view"
        />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <CardTitle className="text-base">Timeline</CardTitle>
            <div className="flex items-center gap-2">
              {platforms.length > 0 ? (
                <Select value={platformFilter} onValueChange={setPlatformFilter}>
                  <SelectTrigger className="h-9 w-[160px]" aria-label="Filter by platform">
                    <SelectValue placeholder="All platforms" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All platforms</SelectItem>
                    {platforms.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : null}
              <Tabs value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                <TabsList>
                  <TabsTrigger value="all">All ({counts.all})</TabsTrigger>
                  <TabsTrigger value="open">Open ({counts.new + counts.acknowledged})</TabsTrigger>
                  <TabsTrigger value="muted">Muted ({counts.muted + counts.expected})</TabsTrigger>
                  <TabsTrigger value="resolved">Resolved ({counts.resolved})</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {fallbackUsed ? (
            <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-900 p-3 text-xs text-amber-900 dark:text-amber-200 flex items-start gap-2">
              <Sparkles className="h-4 w-4 mt-0.5 shrink-0" />
              <div>
                Showing anomalies derived client-side from daily spend. Run <em>Re-scan</em> above or connect more platforms for server-side detection with per-resource granularity.
              </div>
            </div>
          ) : null}

          {loading ? (
            <div className="space-y-3">
              <Skeleton className="h-24 rounded-lg" />
              <Skeleton className="h-24 rounded-lg" />
              <Skeleton className="h-24 rounded-lg" />
            </div>
          ) : error ? (
            <EmptyErrorState onRetry={refetch} />
          ) : items.length === 0 ? (
            <EmptyState statusFilter={statusFilter} />
          ) : (
            <div className="space-y-3">
              {items.map((a) => (
                <AnomalyRow
                  key={a.id}
                  anomaly={a}
                  onInvestigate={(x) => setSelected({ ...x, status: a.status })}
                  onAcknowledge={(x) => persistAck(x.id)}
                  onMute={handleMute}
                  onMarkExpected={handleMarkExpected}
                />
              ))}
            </div>
          )}

          {(counts.muted + counts.expected > 0) && statusFilter !== "muted" ? (
            <div className="mt-6 border-t pt-4">
              <h4 className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                Muted / expected signatures
              </h4>
              <MutedList local={local} onClear={handleClearSignature} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      <AnomalyDetailSheet
        anomaly={selected}
        dailyTrend={costs?.daily_trend}
        onClose={() => setSelected(null)}
        onAcknowledge={(x) => {
          persistAck(x.id);
          setSelected(null);
        }}
        onMute={(x, duration) => {
          handleMute(x, duration);
          setSelected(null);
        }}
        onMarkExpected={(x) => {
          handleMarkExpected(x);
          setSelected(null);
        }}
      />
    </div>
  );
}

function EmptyState({ statusFilter }: { statusFilter: StatusFilter }) {
  const copy = statusFilter === "muted"
    ? "No muted or expected anomalies. Mute signatures you don't want to see from the list."
    : statusFilter === "resolved"
      ? "Nothing resolved yet — anomalies stay in the timeline until they fall outside the window."
      : "No anomalies detected in the selected window. Enjoy the quiet.";
  return (
    <div className="text-center py-12 text-muted-foreground">
      <CheckCircle2 className="h-10 w-10 text-emerald-500 mx-auto mb-2" aria-hidden />
      <p className="text-sm">{copy}</p>
    </div>
  );
}

function EmptyErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="text-center py-10 text-muted-foreground">
      <AlertTriangle className="h-8 w-8 text-amber-500 mx-auto mb-2" aria-hidden />
      <p className="text-sm">Couldn&apos;t load anomalies. The backend may be warming up.</p>
      <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

function MutedList({
  local,
  onClear,
}: {
  local: LocalAnomalyState;
  onClear: (signature: string) => void;
}) {
  const entries = useMemo(() => {
    const mutedKeys = Object.keys(local.muted);
    const expectedKeys = Object.keys(local.expected);
    const signatures = new Set([...mutedKeys, ...expectedKeys]);
    return Array.from(signatures).map((sig) => ({
      signature: sig,
      muted: local.muted[sig],
      expected: Boolean(local.expected[sig]),
    }));
  }, [local]);

  if (entries.length === 0) return null;

  return (
    <ul className="space-y-1.5">
      {entries.map((e) => (
        <li key={e.signature} className="flex items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2 min-w-0">
            {e.expected ? (
              <Badge variant="outline" className="shrink-0">expected</Badge>
            ) : null}
            {e.muted ? (
              <Badge variant="outline" className="shrink-0">
                {e.muted.until ? `muted until ${new Date(e.muted.until).toLocaleDateString()}` : "muted forever"}
              </Badge>
            ) : null}
            <code className="truncate text-muted-foreground" title={e.signature}>
              {e.signature}
            </code>
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => onClear(e.signature)}
            aria-label={`Clear override for ${e.signature}`}
          >
            Clear
          </Button>
        </li>
      ))}
    </ul>
  );
}
