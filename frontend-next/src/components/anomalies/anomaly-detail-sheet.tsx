"use client";

import { useMemo } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Bot, BellOff, Check, MessageSquare, ThumbsUp } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatCurrency } from "@/lib/format";
import type {
  AnomalyStatus,
  DailyTrendPoint,
  NormalizedAnomaly,
  MuteDuration,
} from "@/lib/anomalies";
import { probableCause } from "@/lib/anomalies";
import Link from "next/link";

interface AnomalyDetailSheetProps {
  anomaly: (NormalizedAnomaly & { status: AnomalyStatus }) | null;
  dailyTrend?: DailyTrendPoint[];
  onClose: () => void;
  onAcknowledge: (a: NormalizedAnomaly) => void;
  onMute: (a: NormalizedAnomaly, duration: MuteDuration) => void;
  onMarkExpected: (a: NormalizedAnomaly) => void;
}

export function AnomalyDetailSheet({
  anomaly,
  dailyTrend,
  onClose,
  onAcknowledge,
  onMute,
  onMarkExpected,
}: AnomalyDetailSheetProps) {
  const chartData = useMemo(() => {
    if (!anomaly || !dailyTrend) return [];
    // Last 14 days including the anomaly day.
    const idx = dailyTrend.findIndex((d) => d.date === anomaly.date);
    if (idx === -1) {
      return dailyTrend.slice(-14).map((d) => ({
        date: d.date,
        cost: Number(d.cost ?? 0),
        isAnomaly: d.date === anomaly.date,
      }));
    }
    const start = Math.max(0, idx - 13);
    return dailyTrend.slice(start, idx + 1).map((d) => ({
      date: d.date,
      cost: Number(d.cost ?? 0),
      isAnomaly: d.date === anomaly.date,
    }));
  }, [anomaly, dailyTrend]);

  const isOpen = anomaly !== null;
  const a = anomaly;

  return (
    <Sheet open={isOpen} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-xl overflow-y-auto"
        aria-describedby={a ? `anomaly-detail-${a.id}-desc` : undefined}
      >
        {a ? (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2 mb-1">
                <Badge variant="outline" className="text-[0.65rem]">
                  {a.status.toUpperCase()}
                </Badge>
                <span className="text-xs text-muted-foreground">{a.date}</span>
              </div>
              <SheetTitle className="pr-8">
                {[a.platform, a.resource].filter(Boolean).join(" · ") || "Total spend"} spike
              </SheetTitle>
              <SheetDescription id={`anomaly-detail-${a.id}-desc`}>
                {a.message}
              </SheetDescription>
            </SheetHeader>

            <div className="px-4 pb-4 space-y-4">
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">Spend</div>
                  <div className="text-lg font-bold tabular-nums">{formatCurrency(a.cost)}</div>
                </div>
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">Baseline</div>
                  <div className="text-lg font-bold tabular-nums text-muted-foreground">
                    {formatCurrency(a.baseline)}
                  </div>
                </div>
                <div className="rounded-md border p-3">
                  <div className="text-xs text-muted-foreground">Δ</div>
                  <div className={`text-lg font-bold tabular-nums ${a.deltaUsd >= 0 ? "text-red-500" : "text-emerald-500"}`}>
                    {a.deltaUsd >= 0 ? "+" : ""}
                    {a.deltaPct.toFixed(0)}%
                  </div>
                </div>
              </div>

              {chartData.length > 0 ? (
                <div className="rounded-md border p-3">
                  <h4 className="text-xs font-semibold text-muted-foreground mb-2">
                    Daily spend — last 14 days
                  </h4>
                  <div className="h-40">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke="#f1f5f9" vertical={false} />
                        <XAxis
                          dataKey="date"
                          tickFormatter={(d) =>
                            new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" })
                          }
                          tick={{ fontSize: 11 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          tickFormatter={(v) => `$${Math.round(Number(v))}`}
                          tick={{ fontSize: 11 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <Tooltip
                          formatter={(v) => formatCurrency(Number(v))}
                          labelFormatter={(l) => new Date(String(l)).toLocaleDateString()}
                        />
                        <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                          {chartData.map((d) => (
                            <Cell key={d.date} fill={d.isAnomaly ? "#DC2626" : "#94A3B8"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ) : null}

              <div>
                <h4 className="text-sm font-semibold mb-2">What we think happened</h4>
                <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                  <li>{probableCause(a)}</li>
                  {a.scope === "platform" ? <li>Aggregated at the platform level — drill into resources on the {a.platform} page.</li> : null}
                  {a.derived ? (
                    <li>Derived client-side from the daily trend (backend anomaly record unavailable).</li>
                  ) : null}
                </ul>
              </div>

              <Separator />

              <div>
                <h4 className="text-sm font-semibold mb-2">Actions</h4>
                <div className="flex flex-wrap gap-2">
                  {a.status === "new" ? (
                    <Button size="sm" onClick={() => onAcknowledge(a)} className="gap-1.5">
                      <Check className="h-3.5 w-3.5" /> Acknowledge
                    </Button>
                  ) : null}
                  <Button size="sm" variant="outline" onClick={() => onMute(a, "7d")} className="gap-1.5">
                    <BellOff className="h-3.5 w-3.5" /> Mute 7d
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => onMute(a, "30d")} className="gap-1.5">
                    <BellOff className="h-3.5 w-3.5" /> Mute 30d
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onMarkExpected(a)} className="gap-1.5">
                    <ThumbsUp className="h-3.5 w-3.5" /> Mark expected
                  </Button>
                </div>
              </div>

              <Separator />

              <div>
                <h4 className="text-sm font-semibold mb-2">Ask Costly</h4>
                <div className="flex flex-wrap gap-2">
                  <Link
                    href={`/chat?q=${encodeURIComponent(
                      `Why did ${a.platform || "total spend"}${a.resource ? ` / ${a.resource}` : ""} spike ${a.deltaPct.toFixed(0)}% on ${a.date}?`,
                    )}`}
                  >
                    <Button size="sm" variant="default" className="gap-1.5">
                      <Bot className="h-3.5 w-3.5" /> Ask agent to investigate
                    </Button>
                  </Link>
                  <Link
                    href={`/chat?q=${encodeURIComponent(
                      `Recommend how to prevent ${a.platform || "this"} spikes going forward`,
                    )}`}
                  >
                    <Button size="sm" variant="outline" className="gap-1.5">
                      <MessageSquare className="h-3.5 w-3.5" /> Ask for fix
                    </Button>
                  </Link>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
