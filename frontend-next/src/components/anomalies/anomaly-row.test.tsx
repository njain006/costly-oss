/**
 * Component tests for `<AnomalyRow />`.
 *
 * AnomalyRow is the per-item presentational unit on the anomalies page. It
 * renders a status badge, severity indicator, delta, and a row of action
 * buttons whose handlers are passed in as props. We assert:
 *   - Badge label matches the provided status.
 *   - Acknowledge button is only present in the "new" state (PRD: don't
 *     re-ack what's already acked).
 *   - Clicking each visible button fires the corresponding callback with
 *     the anomaly object.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnomalyRow } from "./anomaly-row";
import {
  normalizeAnomaly,
  type AnomalyStatus,
  type RawAnomaly,
} from "@/lib/anomalies";

const RAW: RawAnomaly = {
  _id: "row-1",
  date: "2026-04-20",
  type: "zscore_spike",
  severity: "high",
  scope: "platform",
  platform: "Snowflake",
  resource: "",
  cost: 240,
  baseline_mean: 100,
  pct_change: 140,
  message: "Snowflake spend $240 vs $100 baseline",
  detected_at: "2026-04-20T09:42:00Z",
};

function makeAnomaly(status: AnomalyStatus = "new") {
  return { ...normalizeAnomaly(RAW, null), status };
}

function renderRow(status: AnomalyStatus = "new") {
  const onInvestigate = vi.fn();
  const onAcknowledge = vi.fn();
  const onMute = vi.fn();
  const onMarkExpected = vi.fn();
  const anomaly = makeAnomaly(status);
  render(
    <AnomalyRow
      anomaly={anomaly}
      onInvestigate={onInvestigate}
      onAcknowledge={onAcknowledge}
      onMute={onMute}
      onMarkExpected={onMarkExpected}
    />,
  );
  return { anomaly, onInvestigate, onAcknowledge, onMute, onMarkExpected };
}

describe("<AnomalyRow />", () => {
  it.each<[AnomalyStatus, string]>([
    ["new", "NEW"],
    ["acknowledged", "ACK"],
    ["muted", "MUTED"],
    ["expected", "EXPECTED"],
    ["resolved", "RESOLVED"],
  ])("renders the correct badge label for status=%s", (status, label) => {
    renderRow(status);
    // Headline uses the platform name; we scope to data-slot=badge to avoid
    // colliding with other text on the row.
    const badges = document.querySelectorAll('[data-slot="badge"]');
    const labels = Array.from(badges).map((b) => b.textContent?.trim());
    expect(labels).toContain(label);
  });

  it("only shows Acknowledge button when status is 'new'", () => {
    const { unmount } = render(
      <AnomalyRow
        anomaly={makeAnomaly("new")}
        onInvestigate={vi.fn()}
        onAcknowledge={vi.fn()}
        onMute={vi.fn()}
        onMarkExpected={vi.fn()}
      />,
    );
    // Two acknowledge entry-points exist when new: the dedicated button and
    // a duplicate inside the more-actions menu. The dedicated button has the
    // accessible name "Acknowledge this anomaly".
    expect(
      screen.getByRole("button", { name: /acknowledge this anomaly/i }),
    ).toBeInTheDocument();
    unmount();

    render(
      <AnomalyRow
        anomaly={makeAnomaly("acknowledged")}
        onInvestigate={vi.fn()}
        onAcknowledge={vi.fn()}
        onMute={vi.fn()}
        onMarkExpected={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /acknowledge this anomaly/i }),
    ).not.toBeInTheDocument();
  });

  it("clicking Investigate fires onInvestigate with the anomaly", async () => {
    const user = userEvent.setup();
    const { anomaly, onInvestigate } = renderRow("new");
    await user.click(
      screen.getByRole("button", { name: /investigate anomaly/i }),
    );
    expect(onInvestigate).toHaveBeenCalledTimes(1);
    expect(onInvestigate).toHaveBeenCalledWith(anomaly);
  });

  it("clicking Acknowledge fires onAcknowledge with the anomaly", async () => {
    const user = userEvent.setup();
    const { anomaly, onAcknowledge } = renderRow("new");
    await user.click(
      screen.getByRole("button", { name: /acknowledge this anomaly/i }),
    );
    expect(onAcknowledge).toHaveBeenCalledWith(anomaly);
  });

  it("renders the 'derived' badge when anomaly is derived", () => {
    const onNoop = vi.fn();
    const a = { ...makeAnomaly("new"), derived: true };
    render(
      <AnomalyRow
        anomaly={a}
        onInvestigate={onNoop}
        onAcknowledge={onNoop}
        onMute={onNoop}
        onMarkExpected={onNoop}
      />,
    );
    expect(screen.getByText("derived")).toBeInTheDocument();
  });

  it("Mark expected button calls onMarkExpected", async () => {
    const user = userEvent.setup();
    const { anomaly, onMarkExpected } = renderRow("new");
    await user.click(
      screen.getByRole("button", { name: /mark this pattern as expected/i }),
    );
    expect(onMarkExpected).toHaveBeenCalledWith(anomaly);
  });

  it("renders the +delta currency in the row header", () => {
    renderRow("new");
    // deltaUsd is +140 for the seed anomaly.
    const article = screen.getByRole("article");
    expect(within(article).getByText(/\+\$140/)).toBeInTheDocument();
  });
});
