/**
 * Component tests for `<StatCard />`.
 *
 * StatCard is a tiny presentational KPI card with no async dependencies, so
 * tests focus on prop-to-DOM mappings (title, value, description, icon
 * rendered as svg). The icon is exercised by passing a real lucide icon and
 * asserting that an `<svg>` is present — we don't pin a specific icon path
 * so updates to lucide-react don't break this test.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TrendingUp } from "lucide-react";
import StatCard from "./stat-card";

describe("<StatCard />", () => {
  it("renders title, value and description", () => {
    render(
      <StatCard
        title="Open anomalies"
        value={42}
        icon={TrendingUp}
        description="3 high-severity"
      />,
    );

    expect(screen.getByText("Open anomalies")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("3 high-severity")).toBeInTheDocument();
  });

  it("omits description block when not provided", () => {
    render(<StatCard title="Cost" value="$1,234" icon={TrendingUp} />);

    expect(screen.getByText("Cost")).toBeInTheDocument();
    expect(screen.getByText("$1,234")).toBeInTheDocument();
    expect(screen.queryByText(/high-severity/)).not.toBeInTheDocument();
  });

  it("renders the icon as an svg", () => {
    const { container } = render(
      <StatCard title="Cost" value="$0" icon={TrendingUp} />,
    );
    // Lucide icons render as <svg>. We don't assert the path so future icon
    // updates don't break this test.
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("accepts a string value (e.g. pre-formatted currency)", () => {
    render(<StatCard title="Impact" value="$1,234" icon={TrendingUp} />);
    expect(screen.getByText("$1,234")).toBeInTheDocument();
  });

  it("forwards a custom className to the card root", () => {
    const { container } = render(
      <StatCard
        title="Cost"
        value={0}
        icon={TrendingUp}
        className="test-marker-class"
      />,
    );
    expect(
      container.querySelector(".test-marker-class"),
    ).toBeInTheDocument();
  });
});
