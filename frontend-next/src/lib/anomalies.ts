/**
 * Anomaly utilities — pure functions, no React or network.
 *
 * Handles:
 *  - Normalizing raw anomaly records from the backend into a UI-friendly shape.
 *  - Computing an anomaly "signature" for client-side mute/mark-expected tracking.
 *  - Deriving anomalies from a plain `daily_trend` series when the backend has none.
 *  - Filtering and grouping helpers consumed by the page component.
 *
 * Keep this file free of React imports so it can be exercised with `node --test`
 * once a test runner is wired up.
 */

export type AnomalyStatus = "new" | "acknowledged" | "muted" | "expected" | "resolved";

export type AnomalySeverity = "high" | "medium" | "low";

export interface RawAnomaly {
  _id?: string;
  id?: string;
  date: string;
  type?: string;
  severity?: string;
  scope?: string;
  platform?: string;
  resource?: string;
  cost?: number;
  baseline_mean?: number;
  baseline?: number;
  previous_cost?: number;
  pct_change?: number;
  zscore?: number;
  message?: string;
  detected_at?: string;
  acknowledged?: boolean;
  acknowledged_at?: string;
}

export interface NormalizedAnomaly {
  id: string;
  signature: string;
  date: string;
  detectedAt: string;
  type: string;
  severity: AnomalySeverity;
  scope: string;
  platform: string;
  resource: string;
  cost: number;
  baseline: number;
  deltaUsd: number;
  deltaPct: number;
  message: string;
  acknowledged: boolean;
  derived: boolean;
}

export interface AnomalyListResponse {
  anomalies: RawAnomaly[];
  count?: number;
  unacknowledged?: number;
}

export interface DailyTrendPoint {
  date: string;
  cost?: number;
  [platform: string]: string | number | undefined;
}

/** Local-only state persisted in localStorage for mute / mark-expected / ack. */
export interface LocalAnomalyState {
  muted: Record<string, { until: number | null }>;
  expected: Record<string, true>;
  acknowledged: Record<string, true>;
}

export const MUTE_PRESETS = [
  { id: "7d", label: "Mute 7d", ms: 7 * 24 * 60 * 60 * 1000 },
  { id: "30d", label: "Mute 30d", ms: 30 * 24 * 60 * 60 * 1000 },
  { id: "forever", label: "Mute forever", ms: null },
] as const;

export type MuteDuration = (typeof MUTE_PRESETS)[number]["id"];

/** Build a stable signature used for mute/expected de-dup across re-detections. */
export function anomalySignature(a: Pick<RawAnomaly, "scope" | "platform" | "resource" | "type">): string {
  const parts = [a.scope ?? "total", a.platform ?? "", a.resource ?? "", a.type ?? "spike"];
  return parts.map((p) => p.toLowerCase().trim()).join("::");
}

/** Normalize one backend record plus the local-state overlay into UI shape. */
export function normalizeAnomaly(raw: RawAnomaly, local: LocalAnomalyState | null): NormalizedAnomaly {
  const id = raw.id ?? raw._id ?? `${raw.date}-${raw.type ?? ""}-${raw.platform ?? ""}-${raw.resource ?? ""}`;
  const signature = anomalySignature(raw);
  const baseline = raw.baseline_mean ?? raw.baseline ?? raw.previous_cost ?? 0;
  const cost = raw.cost ?? 0;
  const deltaUsd = cost - baseline;
  const deltaPct = raw.pct_change ?? (baseline > 0 ? ((cost - baseline) / baseline) * 100 : 0);
  const severity = ((raw.severity ?? "medium").toLowerCase() as AnomalySeverity) ?? "medium";
  const ackLocal = Boolean(local?.acknowledged?.[id]);

  return {
    id: String(id),
    signature,
    date: raw.date,
    detectedAt: raw.detected_at ?? raw.date,
    type: raw.type ?? "spike",
    severity: severity === "high" || severity === "medium" || severity === "low" ? severity : "medium",
    scope: raw.scope ?? "total",
    platform: raw.platform ?? "",
    resource: raw.resource ?? "",
    cost: round2(cost),
    baseline: round2(baseline),
    deltaUsd: round2(deltaUsd),
    deltaPct: round1(deltaPct),
    message: raw.message ?? buildFallbackMessage(raw),
    acknowledged: Boolean(raw.acknowledged) || ackLocal,
    derived: false,
  };
}

function buildFallbackMessage(raw: RawAnomaly): string {
  const target = raw.resource
    ? `${raw.platform ?? ""}/${raw.resource}`
    : raw.platform || "Total spend";
  const pct = raw.pct_change ?? 0;
  const cost = raw.cost ?? 0;
  return `${target} at $${cost.toFixed(0)} (+${pct.toFixed(0)}%)`;
}

/** Decide which status badge applies given server ack + local overrides. */
export function computeStatus(a: NormalizedAnomaly, local: LocalAnomalyState | null, now: number = Date.now()): AnomalyStatus {
  if (local?.expected?.[a.signature]) return "expected";
  const mute = local?.muted?.[a.signature];
  if (mute) {
    if (mute.until === null) return "muted";
    if (mute.until > now) return "muted";
  }
  if (a.acknowledged) return "acknowledged";
  return "new";
}

/** Build the in-memory list shown on the page, including derived fallbacks. */
export interface BuildListArgs {
  raw: RawAnomaly[];
  dailyTrend?: DailyTrendPoint[];
  local: LocalAnomalyState | null;
  statusFilter: "all" | "open" | "muted" | "resolved";
  platformFilter: string | "all";
  now?: number;
}

export interface BuildListResult {
  items: (NormalizedAnomaly & { status: AnomalyStatus })[];
  counts: Record<AnomalyStatus | "all", number>;
  fallbackUsed: boolean;
}

export function buildAnomalyList({
  raw,
  dailyTrend,
  local,
  statusFilter,
  platformFilter,
  now = Date.now(),
}: BuildListArgs): BuildListResult {
  let list = raw.map((r) => normalizeAnomaly(r, local));
  let fallbackUsed = false;

  if (list.length === 0 && dailyTrend && dailyTrend.length >= 7) {
    list = deriveFromTrend(dailyTrend);
    fallbackUsed = list.length > 0;
  }

  const withStatus = list.map((a) => ({ ...a, status: computeStatus(a, local, now) }));

  const counts: Record<AnomalyStatus | "all", number> = {
    all: withStatus.length,
    new: 0,
    acknowledged: 0,
    muted: 0,
    expected: 0,
    resolved: 0,
  };
  for (const item of withStatus) counts[item.status] += 1;

  const filtered = withStatus.filter((a) => {
    if (platformFilter !== "all" && a.platform.toLowerCase() !== platformFilter.toLowerCase()) {
      return false;
    }
    if (statusFilter === "all") return true;
    if (statusFilter === "open") return a.status === "new" || a.status === "acknowledged";
    if (statusFilter === "muted") return a.status === "muted" || a.status === "expected";
    if (statusFilter === "resolved") return a.status === "resolved";
    return true;
  });

  // Sort newest first, then by magnitude.
  filtered.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1;
    return Math.abs(b.deltaUsd) - Math.abs(a.deltaUsd);
  });

  return { items: filtered, counts, fallbackUsed };
}

/**
 * Detect spikes from a daily trend series when the backend has no anomalies yet.
 * Uses a simple z-score over the rolling window and flags the last 7 days.
 */
export function deriveFromTrend(daily: DailyTrendPoint[]): NormalizedAnomaly[] {
  if (daily.length < 7) return [];
  const costs = daily.map((d) => Number(d.cost ?? 0));
  const mean = costs.reduce((a, b) => a + b, 0) / costs.length;
  if (mean < 5) return [];
  const variance = costs.reduce((sum, c) => sum + (c - mean) ** 2, 0) / costs.length;
  const stddev = Math.sqrt(variance);
  if (stddev === 0) return [];

  const out: NormalizedAnomaly[] = [];
  const recent = daily.slice(-7);
  for (const point of recent) {
    const cost = Number(point.cost ?? 0);
    const z = (cost - mean) / stddev;
    if (z >= 2) {
      const pct = mean > 0 ? ((cost - mean) / mean) * 100 : 0;
      out.push({
        id: `derived-${point.date}`,
        signature: anomalySignature({ scope: "total", platform: "", resource: "", type: "zscore_spike" }),
        date: point.date,
        detectedAt: point.date,
        type: "zscore_spike",
        severity: z >= 3 ? "high" : "medium",
        scope: "total",
        platform: "",
        resource: "",
        cost: round2(cost),
        baseline: round2(mean),
        deltaUsd: round2(cost - mean),
        deltaPct: round1(pct),
        message: `Total daily spend of $${cost.toFixed(0)} is ${pct.toFixed(0)}% above the ${daily.length}-day average of $${mean.toFixed(0)} (z-score ${z.toFixed(1)})`,
        acknowledged: false,
        derived: true,
      });
    }
  }
  return out;
}

/**
 * A naive probable-cause classifier: looks at the scope + type + daily_trend
 * context and returns a single-line explanation that is better than nothing.
 */
export function probableCause(a: NormalizedAnomaly): string {
  if (a.scope === "resource" && a.resource) {
    return `Resource ${a.resource} on ${a.platform || "this platform"} is running hotter than its 30-day baseline.`;
  }
  if (a.scope === "platform" && a.platform) {
    return `Usage concentrated on ${a.platform}. Check for new workloads or pipelines deployed around ${a.date}.`;
  }
  if (a.type.includes("week")) {
    return "Same-weekday spend is up — likely a recurring workload tuning issue.";
  }
  if (a.type.includes("day_over_day")) {
    return "Sudden day-over-day jump — look for new deploys, runaway loops, or one-off backfills.";
  }
  return "Spend deviates from the rolling baseline. Unknown cause — click Investigate for details.";
}

/** Storage helpers — thin wrappers so localStorage usage stays testable. */
const STORAGE_KEY = "costly_anomaly_state_v1";

export function emptyLocalState(): LocalAnomalyState {
  return { muted: {}, expected: {}, acknowledged: {} };
}

export function loadLocalState(storage?: Storage): LocalAnomalyState {
  const store = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
  if (!store) return emptyLocalState();
  const raw = store.getItem(STORAGE_KEY);
  if (!raw) return emptyLocalState();
  try {
    const parsed = JSON.parse(raw) as Partial<LocalAnomalyState>;
    return {
      muted: parsed.muted ?? {},
      expected: parsed.expected ?? {},
      acknowledged: parsed.acknowledged ?? {},
    };
  } catch {
    return emptyLocalState();
  }
}

export function saveLocalState(state: LocalAnomalyState, storage?: Storage): void {
  const store = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
  if (!store) return;
  store.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function muteSignature(state: LocalAnomalyState, signature: string, duration: MuteDuration, now: number = Date.now()): LocalAnomalyState {
  const preset = MUTE_PRESETS.find((m) => m.id === duration);
  const until = preset?.ms == null ? null : now + preset.ms;
  return {
    ...state,
    muted: { ...state.muted, [signature]: { until } },
  };
}

export function markExpected(state: LocalAnomalyState, signature: string): LocalAnomalyState {
  return {
    ...state,
    expected: { ...state.expected, [signature]: true },
  };
}

export function ackLocal(state: LocalAnomalyState, id: string): LocalAnomalyState {
  return {
    ...state,
    acknowledged: { ...state.acknowledged, [id]: true },
  };
}

export function clearSignature(state: LocalAnomalyState, signature: string): LocalAnomalyState {
  const muted = { ...state.muted };
  delete muted[signature];
  const expected = { ...state.expected };
  delete expected[signature];
  return { ...state, muted, expected };
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
