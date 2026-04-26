/**
 * Page-level tests for `/anomalies`.
 *
 * Exercises the full page through MSW-mocked endpoints:
 *   1. Renders an empty state when the API returns `[]`.
 *   2. Renders one row per anomaly when the API returns a list.
 *   3. Mute persists across re-renders via localStorage round-trip.
 *
 * The `useApi` hook resolves once MSW responds, so `findBy*` queries are
 * preferred over `getBy*` for any post-fetch assertions.
 */
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "../../../../test/mocks/server";
import AnomaliesPage from "./page";

function makeAnomaly(overrides: Record<string, unknown> = {}) {
  return {
    _id: `id-${Math.random().toString(36).slice(2, 8)}`,
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
    acknowledged: false,
    ...overrides,
  };
}

describe("/anomalies page", () => {
  it("renders the empty state when the API returns []", async () => {
    server.use(
      http.get("*/api/anomalies", () =>
        HttpResponse.json({ anomalies: [], count: 0, unacknowledged: 0 }),
      ),
      http.get("*/api/platforms/costs", () =>
        HttpResponse.json({ daily_trend: [] }),
      ),
    );

    render(<AnomaliesPage />);

    // Header + status filter copy renders synchronously; the empty state
    // is gated on the fetch resolving, so use findByText.
    expect(
      await screen.findByText(/No anomalies detected in the selected window/i),
    ).toBeInTheDocument();
  });

  it("renders one row per anomaly when the API returns a list", async () => {
    const list = [
      makeAnomaly({ _id: "a1" }),
      makeAnomaly({ _id: "a2", platform: "OpenAI" }),
    ];
    server.use(
      http.get("*/api/anomalies", () =>
        HttpResponse.json({
          anomalies: list,
          count: 2,
          unacknowledged: 2,
        }),
      ),
      http.get("*/api/platforms/costs", () =>
        HttpResponse.json({ daily_trend: [] }),
      ),
    );

    render(<AnomaliesPage />);

    // Two articles for the two anomalies.
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(2);
    });
  });

  it("muting an anomaly persists across re-renders via localStorage", async () => {
    const list = [makeAnomaly({ _id: "mute-1" })];
    server.use(
      http.get("*/api/anomalies", () =>
        HttpResponse.json({ anomalies: list }),
      ),
      http.get("*/api/platforms/costs", () =>
        HttpResponse.json({ daily_trend: [] }),
      ),
    );

    const user = userEvent.setup();
    const { unmount } = render(<AnomaliesPage />);

    // Wait for the row to appear, then mute it.
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    // The dropdown trigger has aria-label="More actions". The first one in
    // the row is the Mute dropdown (visible label "Mute"); the second is
    // the kebab menu. Open the first.
    const moreActionsButtons = screen.getAllByRole("button", {
      name: /more actions/i,
    });
    await user.click(moreActionsButtons[0]);
    // Pick "Mute 7 days" from the dropdown (rendered into a portal).
    const muteOption = await screen.findByRole("menuitem", {
      name: /Mute 7 days/i,
    });
    await user.click(muteOption);

    // The default status filter is "open", so muting should hide the row.
    await waitFor(() => {
      expect(screen.queryAllByRole("article")).toHaveLength(0);
    });

    // localStorage should now contain the persisted mute.
    const stored = window.localStorage.getItem("costly_anomaly_state_v1");
    expect(stored).toBeTruthy();
    const parsed = JSON.parse(stored ?? "{}");
    expect(Object.keys(parsed.muted ?? {})).toHaveLength(1);

    // Unmount + remount: the page should re-hydrate the mute and keep the
    // anomaly hidden in the default "open" view.
    unmount();
    render(<AnomaliesPage />);
    await waitFor(() => {
      // After remount the API still returns the same anomaly, but the mute
      // overlay from localStorage filters it out of the "open" view.
      expect(screen.queryAllByRole("article")).toHaveLength(0);
    });
  });
});
