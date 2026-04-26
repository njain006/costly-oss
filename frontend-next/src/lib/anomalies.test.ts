/**
 * Vitest port of the original inline anomaly tests.
 *
 * All 17 cases from the inline harness are preserved as discrete `it` blocks
 * so the runner can report each independently. Pure-function tests — no DOM
 * or network — but executed by Vitest for unified output and coverage.
 */
import { describe, expect, it } from "vitest";
import {
  ackLocal,
  anomalySignature,
  buildAnomalyList,
  computeStatus,
  deriveFromTrend,
  emptyLocalState,
  loadLocalState,
  markExpected,
  muteSignature,
  normalizeAnomaly,
  probableCause,
  saveLocalState,
  type RawAnomaly,
} from "./anomalies";

const BASE_RAW: RawAnomaly = {
  _id: "abc123",
  date: "2026-04-20",
  type: "zscore_spike",
  severity: "high",
  scope: "platform",
  platform: "Snowflake",
  resource: "",
  cost: 240,
  baseline_mean: 100,
  pct_change: 140,
  zscore: 3.2,
  message: "Snowflake spend of $240 is 140% above its 30-day average of $100",
  detected_at: "2026-04-20T09:42:00Z",
  acknowledged: false,
};

describe("anomalySignature", () => {
  it("is stable across case differences", () => {
    const a = anomalySignature({
      scope: "platform",
      platform: "Snowflake",
      resource: "",
      type: "zscore_spike",
    });
    const b = anomalySignature({
      scope: "PLATFORM",
      platform: "snowflake",
      resource: "",
      type: "ZSCORE_SPIKE",
    });
    expect(a).toBe(b);
  });

  it("differentiates by resource", () => {
    const wh = anomalySignature({
      scope: "resource",
      platform: "Snowflake",
      resource: "ANALYTICS_WH",
      type: "zscore_spike",
    });
    const ops = anomalySignature({
      scope: "resource",
      platform: "Snowflake",
      resource: "OPS_WH",
      type: "zscore_spike",
    });
    expect(wh).not.toBe(ops);
  });
});

describe("normalizeAnomaly", () => {
  it("derives deltaUsd and deltaPct when missing", () => {
    const norm = normalizeAnomaly({ ...BASE_RAW, pct_change: undefined }, null);
    expect(norm.deltaUsd).toBe(140);
    expect(norm.deltaPct).toBe(140);
  });

  it("honors local ack overlay", () => {
    const local = {
      ...emptyLocalState(),
      acknowledged: { abc123: true as const },
    };
    const norm = normalizeAnomaly({ ...BASE_RAW, acknowledged: false }, local);
    expect(norm.acknowledged).toBe(true);
  });
});

describe("computeStatus", () => {
  it("'new' when nothing else applies", () => {
    const base = normalizeAnomaly(BASE_RAW, null);
    expect(computeStatus(base, emptyLocalState(), 1_700_000_000_000)).toBe(
      "new",
    );
  });

  it("muted window respects expiration", () => {
    const now = 1_700_000_000_000;
    const base = normalizeAnomaly(BASE_RAW, null);
    const state = muteSignature(emptyLocalState(), base.signature, "7d", now);
    expect(computeStatus(base, state, now)).toBe("muted");
    expect(
      computeStatus(base, state, now + 8 * 24 * 60 * 60 * 1000),
    ).toBe("new");
  });

  it("markExpected wins over other status", () => {
    const base = normalizeAnomaly(BASE_RAW, null);
    const state = markExpected(emptyLocalState(), base.signature);
    expect(computeStatus(base, state, 1_700_000_000_000)).toBe("expected");
  });

  it("server ack maps to 'acknowledged'", () => {
    const base = normalizeAnomaly({ ...BASE_RAW, acknowledged: true }, null);
    expect(computeStatus(base, emptyLocalState(), 1_700_000_000_000)).toBe(
      "acknowledged",
    );
  });
});

describe("deriveFromTrend", () => {
  it("returns empty for short series", () => {
    const short = [
      { date: "2026-04-01", cost: 10 },
      { date: "2026-04-02", cost: 12 },
    ];
    expect(deriveFromTrend(short)).toHaveLength(0);
  });

  it("flags a spike at the end", () => {
    const series = Array.from({ length: 14 }, (_, i) => ({
      date: `2026-04-${String(i + 1).padStart(2, "0")}`,
      cost: i === 13 ? 500 : 100,
    }));
    const derived = deriveFromTrend(series);
    expect(derived.length).toBeGreaterThanOrEqual(1);
    expect(derived[0].derived).toBe(true);
    expect(derived[0].type).toBe("zscore_spike");
  });

  it("flat series has no anomalies", () => {
    const series = Array.from({ length: 14 }, (_, i) => ({
      date: `2026-04-${String(i + 1).padStart(2, "0")}`,
      cost: 100,
    }));
    expect(deriveFromTrend(series)).toHaveLength(0);
  });
});

describe("buildAnomalyList", () => {
  it("falls back to derived when backend is empty", () => {
    const dailyTrend = Array.from({ length: 14 }, (_, i) => ({
      date: `2026-04-${String(i + 1).padStart(2, "0")}`,
      cost: i === 13 ? 500 : 100,
    }));
    const result = buildAnomalyList({
      raw: [],
      dailyTrend,
      local: emptyLocalState(),
      statusFilter: "all",
      platformFilter: "all",
    });
    expect(result.fallbackUsed).toBe(true);
    expect(result.items.length).toBeGreaterThanOrEqual(1);
  });

  it("platform filter excludes non-matching", () => {
    const result = buildAnomalyList({
      raw: [BASE_RAW, { ...BASE_RAW, _id: "xyz", platform: "OpenAI" }],
      local: emptyLocalState(),
      statusFilter: "all",
      platformFilter: "Snowflake",
    });
    expect(result.items).toHaveLength(1);
    expect(result.items[0].platform).toBe("Snowflake");
  });

  it("'open' status filter excludes muted", () => {
    const norm = normalizeAnomaly(BASE_RAW, null);
    const state = muteSignature(emptyLocalState(), norm.signature, "7d");
    const result = buildAnomalyList({
      raw: [BASE_RAW],
      local: state,
      statusFilter: "open",
      platformFilter: "all",
    });
    expect(result.items).toHaveLength(0);
  });
});

describe("probableCause", () => {
  it("uses resource wording when scope is 'resource'", () => {
    const norm = normalizeAnomaly(
      { ...BASE_RAW, scope: "resource", resource: "ANALYTICS_WH" },
      null,
    );
    expect(probableCause(norm)).toMatch(/ANALYTICS_WH/);
  });

  it("always returns a string", () => {
    const norm = normalizeAnomaly(
      { ...BASE_RAW, scope: "total", platform: "", type: "unknown" },
      null,
    );
    expect(typeof probableCause(norm)).toBe("string");
  });
});

describe("local state persistence", () => {
  it("round-trips through a fake Storage", () => {
    const store: Record<string, string> = {};
    const fake: Storage = {
      length: 0,
      clear: () => {
        for (const k of Object.keys(store)) delete store[k];
      },
      getItem: (k) => store[k] ?? null,
      key: () => null,
      removeItem: (k) => {
        delete store[k];
      },
      setItem: (k, v) => {
        store[k] = v;
      },
    };
    const muted = muteSignature(
      emptyLocalState(),
      "sig-a",
      "30d",
      1_700_000_000_000,
    );
    const expected = markExpected(muted, "sig-b");
    const acked = ackLocal(expected, "id-c");
    saveLocalState(acked, fake);
    const restored = loadLocalState(fake);
    expect(restored.muted["sig-a"]?.until).toBe(
      1_700_000_000_000 + 30 * 24 * 60 * 60 * 1000,
    );
    expect(restored.expected["sig-b"]).toBe(true);
    expect(restored.acknowledged["id-c"]).toBe(true);
  });
});
