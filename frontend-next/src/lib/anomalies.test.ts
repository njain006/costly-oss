/**
 * Pure-function tests for `./anomalies`.
 *
 * The repo does not yet have a JS unit-test runner configured (tests live in
 * `frontend-next/e2e/*` and use Playwright). To avoid adding a dependency just
 * for this module we ship a tiny inline harness: run with any TS-aware runner
 * (vitest, jest, bun test, ts-node) and the exported `__runAnomalyTests` will
 * throw on the first failing assertion.
 *
 * Manual smoke check:
 *
 *   cd frontend-next
 *   npx tsx src/lib/anomalies.test.ts
 *
 * Because these are pure functions with no DOM or network dependency, they
 * also double as living documentation for the module contract.
 */

import {
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
  ackLocal,
  type RawAnomaly,
} from "./anomalies";

type Test = { name: string; run: () => void };

function assertEqual<T>(actual: T, expected: T, message?: string): void {
  const sameObject = JSON.stringify(actual) === JSON.stringify(expected);
  if (actual !== expected && !sameObject) {
    throw new Error(`${message ?? "assertEqual failed"}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertTrue(cond: unknown, message?: string): void {
  if (!cond) throw new Error(message ?? "assertTrue failed");
}

function assertMatches(value: string, re: RegExp, message?: string): void {
  if (!re.test(value)) throw new Error(message ?? `assertMatches failed: ${value}`);
}

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

const tests: Test[] = [
  {
    name: "anomalySignature: stable across case differences",
    run: () => {
      const a = anomalySignature({ scope: "platform", platform: "Snowflake", resource: "", type: "zscore_spike" });
      const b = anomalySignature({ scope: "PLATFORM", platform: "snowflake", resource: "", type: "ZSCORE_SPIKE" });
      assertEqual(a, b);
    },
  },
  {
    name: "anomalySignature: differentiates by resource",
    run: () => {
      const wh = anomalySignature({ scope: "resource", platform: "Snowflake", resource: "ANALYTICS_WH", type: "zscore_spike" });
      const ops = anomalySignature({ scope: "resource", platform: "Snowflake", resource: "OPS_WH", type: "zscore_spike" });
      assertTrue(wh !== ops);
    },
  },
  {
    name: "normalizeAnomaly: derives deltaUsd and deltaPct when missing",
    run: () => {
      const norm = normalizeAnomaly({ ...BASE_RAW, pct_change: undefined }, null);
      assertEqual(norm.deltaUsd, 140);
      assertEqual(norm.deltaPct, 140);
    },
  },
  {
    name: "normalizeAnomaly: honors local ack overlay",
    run: () => {
      const local = { ...emptyLocalState(), acknowledged: { abc123: true as const } };
      const norm = normalizeAnomaly({ ...BASE_RAW, acknowledged: false }, local);
      assertEqual(norm.acknowledged, true);
    },
  },
  {
    name: "computeStatus: 'new' when nothing else applies",
    run: () => {
      const base = normalizeAnomaly(BASE_RAW, null);
      assertEqual(computeStatus(base, emptyLocalState(), 1_700_000_000_000), "new");
    },
  },
  {
    name: "computeStatus: muted window respects expiration",
    run: () => {
      const now = 1_700_000_000_000;
      const base = normalizeAnomaly(BASE_RAW, null);
      const state = muteSignature(emptyLocalState(), base.signature, "7d", now);
      assertEqual(computeStatus(base, state, now), "muted");
      assertEqual(computeStatus(base, state, now + 8 * 24 * 60 * 60 * 1000), "new");
    },
  },
  {
    name: "computeStatus: markExpected wins",
    run: () => {
      const base = normalizeAnomaly(BASE_RAW, null);
      const state = markExpected(emptyLocalState(), base.signature);
      assertEqual(computeStatus(base, state, 1_700_000_000_000), "expected");
    },
  },
  {
    name: "computeStatus: server ack maps to 'acknowledged'",
    run: () => {
      const base = normalizeAnomaly({ ...BASE_RAW, acknowledged: true }, null);
      assertEqual(computeStatus(base, emptyLocalState(), 1_700_000_000_000), "acknowledged");
    },
  },
  {
    name: "deriveFromTrend: empty for short series",
    run: () => {
      const short = [
        { date: "2026-04-01", cost: 10 },
        { date: "2026-04-02", cost: 12 },
      ];
      assertEqual(deriveFromTrend(short).length, 0);
    },
  },
  {
    name: "deriveFromTrend: flags a spike at the end",
    run: () => {
      const series = Array.from({ length: 14 }, (_, i) => ({
        date: `2026-04-${String(i + 1).padStart(2, "0")}`,
        cost: i === 13 ? 500 : 100,
      }));
      const derived = deriveFromTrend(series);
      assertTrue(derived.length >= 1);
      assertEqual(derived[0].derived, true);
      assertEqual(derived[0].type, "zscore_spike");
    },
  },
  {
    name: "deriveFromTrend: flat series has no anomalies",
    run: () => {
      const series = Array.from({ length: 14 }, (_, i) => ({
        date: `2026-04-${String(i + 1).padStart(2, "0")}`,
        cost: 100,
      }));
      assertEqual(deriveFromTrend(series).length, 0);
    },
  },
  {
    name: "buildAnomalyList: falls back to derived when backend is empty",
    run: () => {
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
      assertEqual(result.fallbackUsed, true);
      assertTrue(result.items.length >= 1);
    },
  },
  {
    name: "buildAnomalyList: platform filter excludes non-matching",
    run: () => {
      const result = buildAnomalyList({
        raw: [BASE_RAW, { ...BASE_RAW, _id: "xyz", platform: "OpenAI" }],
        local: emptyLocalState(),
        statusFilter: "all",
        platformFilter: "Snowflake",
      });
      assertEqual(result.items.length, 1);
      assertEqual(result.items[0].platform, "Snowflake");
    },
  },
  {
    name: "buildAnomalyList: 'open' status filter excludes muted",
    run: () => {
      const norm = normalizeAnomaly(BASE_RAW, null);
      const state = muteSignature(emptyLocalState(), norm.signature, "7d");
      const result = buildAnomalyList({
        raw: [BASE_RAW],
        local: state,
        statusFilter: "open",
        platformFilter: "all",
      });
      assertEqual(result.items.length, 0);
    },
  },
  {
    name: "probableCause: uses resource wording when scope is 'resource'",
    run: () => {
      const norm = normalizeAnomaly({ ...BASE_RAW, scope: "resource", resource: "ANALYTICS_WH" }, null);
      assertMatches(probableCause(norm), /ANALYTICS_WH/);
    },
  },
  {
    name: "probableCause: always returns a string",
    run: () => {
      const norm = normalizeAnomaly({ ...BASE_RAW, scope: "total", platform: "", type: "unknown" }, null);
      assertEqual(typeof probableCause(norm), "string");
    },
  },
  {
    name: "local state: round-trips through a fake Storage",
    run: () => {
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
      const muted = muteSignature(emptyLocalState(), "sig-a", "30d", 1_700_000_000_000);
      const expected = markExpected(muted, "sig-b");
      const acked = ackLocal(expected, "id-c");
      saveLocalState(acked, fake);
      const restored = loadLocalState(fake);
      assertEqual(restored.muted["sig-a"]?.until, 1_700_000_000_000 + 30 * 24 * 60 * 60 * 1000);
      assertEqual(restored.expected["sig-b"], true);
      assertEqual(restored.acknowledged["id-c"], true);
    },
  },
];

export function __runAnomalyTests(): { passed: number; failed: number; failures: string[] } {
  let passed = 0;
  const failures: string[] = [];
  for (const t of tests) {
    try {
      t.run();
      passed += 1;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      failures.push(`${t.name}: ${msg}`);
    }
  }
  return { passed, failed: failures.length, failures };
}

// Allow direct execution with `npx tsx src/lib/anomalies.test.ts`.
if (typeof process !== "undefined" && process.argv?.[1]?.endsWith("anomalies.test.ts")) {
  const result = __runAnomalyTests();
  // eslint-disable-next-line no-console
  console.log(`anomalies.test.ts: ${result.passed} passed, ${result.failed} failed`);
  if (result.failed > 0) {
    for (const f of result.failures) console.error(`  ✗ ${f}`);
    process.exit(1);
  }
}
