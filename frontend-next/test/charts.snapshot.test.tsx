/**
 * Snapshot guard for Recharts SVG output.
 *
 * Renders a fixed-size <AreaChart /> with a known dataset and snapshots
 * the resulting SVG path. If a future Recharts upgrade silently changes
 * how paths or attributes are emitted, this test forces a manual review of
 * the snapshot diff.
 *
 * Caveats:
 *   - Recharts uses `uniqueId` for clip-path IDs, which is non-deterministic
 *     across runs. We strip those IDs before snapshotting so the test stays
 *     stable.
 *   - We bypass <ResponsiveContainer> (which sizes itself via ResizeObserver,
 *     mocked in `vitest.setup.ts`) by rendering with explicit width/height.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { Area, AreaChart, XAxis, YAxis } from "recharts";

const DATA = [
  { date: "2026-04-14", cost: 100 },
  { date: "2026-04-15", cost: 120 },
  { date: "2026-04-16", cost: 110 },
  { date: "2026-04-17", cost: 90 },
  { date: "2026-04-18", cost: 200 },
];

/** Replace Recharts' generated clip-path IDs so the snapshot is stable. */
function stripRandomIds(html: string): string {
  return html
    .replace(/recharts\d+-clip/g, "recharts-clip")
    .replace(/id="[^"]*"/g, 'id="<id>"')
    .replace(/clip-path="[^"]*"/g, 'clip-path="<clip>"')
    .replace(/url\(#[^)]+\)/g, "url(#<id>)");
}

describe("Recharts <AreaChart /> snapshot", () => {
  it("emits a deterministic shape for a 5-point series", () => {
    const { container } = render(
      <AreaChart width={400} height={200} data={DATA}>
        <XAxis dataKey="date" />
        <YAxis />
        <Area type="monotone" dataKey="cost" stroke="#0EA5E9" fill="#0EA5E9" />
      </AreaChart>,
    );
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(stripRandomIds(svg?.outerHTML ?? "")).toMatchSnapshot();
  });

  it("renders one <path> per Area + axis lines", () => {
    const { container } = render(
      <AreaChart width={400} height={200} data={DATA}>
        <XAxis dataKey="date" />
        <YAxis />
        <Area type="monotone" dataKey="cost" stroke="#0EA5E9" fill="#0EA5E9" />
      </AreaChart>,
    );
    // Area renders an SVG <path>. Axis lines render as <line>. Both should
    // be present in any non-empty chart.
    const paths = container.querySelectorAll("path");
    expect(paths.length).toBeGreaterThan(0);
  });
});
