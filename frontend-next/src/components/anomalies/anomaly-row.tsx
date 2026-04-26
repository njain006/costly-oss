"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  ArrowRight,
  BellOff,
  Check,
  CheckCircle2,
  MoreHorizontal,
  ThumbsUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/format";
import type {
  AnomalyStatus,
  MuteDuration,
  NormalizedAnomaly,
} from "@/lib/anomalies";
import { probableCause } from "@/lib/anomalies";

interface AnomalyRowProps {
  anomaly: NormalizedAnomaly & { status: AnomalyStatus };
  onInvestigate: (a: NormalizedAnomaly) => void;
  onAcknowledge: (a: NormalizedAnomaly) => void;
  onMute: (a: NormalizedAnomaly, duration: MuteDuration) => void;
  onMarkExpected: (a: NormalizedAnomaly) => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  high: "text-red-500",
  medium: "text-amber-500",
  low: "text-sky-500",
};

const STATUS_LABEL: Record<AnomalyStatus, string> = {
  new: "NEW",
  acknowledged: "ACK",
  muted: "MUTED",
  expected: "EXPECTED",
  resolved: "RESOLVED",
};

const STATUS_VARIANT: Record<AnomalyStatus, "default" | "secondary" | "outline" | "destructive" | "ghost"> = {
  new: "default",
  acknowledged: "secondary",
  muted: "outline",
  expected: "outline",
  resolved: "outline",
};

function relativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = now - then;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diff < minute) return "just now";
  if (diff < hour) return `${Math.round(diff / minute)}m ago`;
  if (diff < day) return `${Math.round(diff / hour)}h ago`;
  if (diff < 7 * day) return `${Math.round(diff / day)}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function AnomalyRow({ anomaly, onInvestigate, onAcknowledge, onMute, onMarkExpected }: AnomalyRowProps) {
  const cause = useMemo(() => probableCause(anomaly), [anomaly]);
  const deltaPositive = anomaly.deltaUsd >= 0;
  const severityColor = SEVERITY_COLOR[anomaly.severity] ?? "text-slate-400";
  const dimmed = anomaly.status === "muted" || anomaly.status === "expected" || anomaly.status === "resolved";
  const statusLabel = STATUS_LABEL[anomaly.status];
  const when = relativeTime(anomaly.detectedAt || anomaly.date);
  const target = [anomaly.platform, anomaly.resource].filter(Boolean).join(" · ") || "Total spend";

  return (
    <article
      aria-labelledby={`anomaly-${anomaly.id}-headline`}
      className={cn(
        "group rounded-lg border bg-card p-4 transition-colors",
        dimmed ? "border-border/50 opacity-60" : "border-border hover:border-sky-200 dark:hover:border-sky-800",
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className={cn("text-xs font-bold", severityColor)} aria-hidden>
              {deltaPositive ? "▲" : "▼"}
            </span>
            <Badge variant={STATUS_VARIANT[anomaly.status]} className="text-[0.65rem] tracking-wider">
              {statusLabel}
            </Badge>
            <span className="text-xs text-muted-foreground">{when}</span>
            {anomaly.derived ? (
              <Badge variant="outline" className="text-[0.65rem] text-amber-600 border-amber-300">
                derived
              </Badge>
            ) : null}
            <span className="ml-auto text-sm font-semibold tabular-nums">
              <span className={cn(deltaPositive ? "text-red-500" : "text-emerald-500")}>
                {deltaPositive ? "+" : ""}
                {formatCurrency(anomaly.deltaUsd)}
              </span>
              <span className="text-muted-foreground font-normal ml-1.5">
                ({deltaPositive ? "+" : ""}
                {anomaly.deltaPct.toFixed(0)}%)
              </span>
            </span>
          </div>

          <h3
            id={`anomaly-${anomaly.id}-headline`}
            className="text-sm font-semibold text-foreground"
          >
            {target} {anomaly.scope === "resource" ? "resource spike" : anomaly.scope === "platform" ? "platform spike" : "spike vs baseline"}
          </h3>

          <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
            {anomaly.message}
          </p>

          <p className="text-xs text-muted-foreground mt-1.5 italic">
            Likely cause: {cause}
          </p>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 flex-wrap">
        <Button
          size="sm"
          variant="default"
          onClick={() => onInvestigate(anomaly)}
          className="gap-1.5 h-8"
          aria-label={`Investigate anomaly from ${anomaly.date}`}
        >
          Investigate <ArrowRight className="h-3.5 w-3.5" />
        </Button>

        {anomaly.status === "new" ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onAcknowledge(anomaly)}
            className="gap-1.5 h-8"
            aria-label="Acknowledge this anomaly"
          >
            <Check className="h-3.5 w-3.5" /> Acknowledge
          </Button>
        ) : null}

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="outline" className="gap-1.5 h-8" aria-label="More actions">
              <BellOff className="h-3.5 w-3.5" /> Mute
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onClick={() => onMute(anomaly, "7d")}>Mute 7 days</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onMute(anomaly, "30d")}>Mute 30 days</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onMute(anomaly, "forever")}>Mute permanently</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          size="sm"
          variant="ghost"
          onClick={() => onMarkExpected(anomaly)}
          className="gap-1.5 h-8"
          aria-label="Mark this pattern as expected"
        >
          <ThumbsUp className="h-3.5 w-3.5" /> Mark expected
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="ghost" className="h-8 w-8 p-0 ml-auto" aria-label="More actions">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onAcknowledge(anomaly)}>
              <CheckCircle2 className="h-3.5 w-3.5 mr-2" /> Acknowledge
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onMute(anomaly, "7d")}>Mute 7 days</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onMute(anomaly, "30d")}>Mute 30 days</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onMute(anomaly, "forever")}>Mute permanently</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onMarkExpected(anomaly)}>Mark expected</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </article>
  );
}
