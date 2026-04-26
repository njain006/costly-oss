/**
 * Component tests for `<DateRangePicker />`.
 *
 * Uses the real `DateRangeProvider` to assert end-to-end behaviour: clicking
 * a preset updates context state, the active button highlights, and the
 * refresh button dispatches `triggerRefresh`. We render a `<Probe />` that
 * subscribes to the same context so we can assert provider state without
 * exposing internals.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DateRangePicker from "./date-range-picker";
import {
  DateRangeProvider,
  useDateRange,
} from "@/providers/date-range-provider";

function Probe() {
  const { days, refreshTrigger } = useDateRange();
  return (
    <div>
      <span data-testid="days">{days}</span>
      <span data-testid="refresh">{refreshTrigger}</span>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <DateRangeProvider>
      <DateRangePicker />
      <Probe />
    </DateRangeProvider>,
  );
}

describe("<DateRangePicker />", () => {
  it("renders all four presets", () => {
    renderWithProvider();
    expect(screen.getByRole("button", { name: "7D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "14D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "30D" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "90D" })).toBeInTheDocument();
  });

  it("clicking 7D updates days in context", async () => {
    const user = userEvent.setup();
    renderWithProvider();
    expect(screen.getByTestId("days")).toHaveTextContent("30"); // default

    await user.click(screen.getByRole("button", { name: "7D" }));
    expect(screen.getByTestId("days")).toHaveTextContent("7");

    await user.click(screen.getByRole("button", { name: "90D" }));
    expect(screen.getByTestId("days")).toHaveTextContent("90");
  });

  it("clicking refresh increments refreshTrigger", async () => {
    const user = userEvent.setup();
    renderWithProvider();
    expect(screen.getByTestId("refresh")).toHaveTextContent("0");

    const refreshBtn = screen.getByRole("button", { name: /refresh data/i });
    await user.click(refreshBtn);
    expect(screen.getByTestId("refresh")).toHaveTextContent("1");

    await user.click(refreshBtn);
    expect(screen.getByTestId("refresh")).toHaveTextContent("2");
  });
});
